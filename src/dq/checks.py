"""Data-quality checks (CLAUDE.md §5) — measure and PROVE the silver rules.

For each UTC date D, run_dq_date() writes one obs.dq_results row per check:

  rows_failed   = rows the rule CAUGHT (silver quarantined / flagged them)
  invariant_ok  = a direct query on silver proves nothing bad got THROUGH
  status        = FAIL if the invariant is broken; WARN if pass_rate < threshold;
                  else PASS

Checks: METER_IN_MASTER, ENERGY_NON_NEGATIVE, REGISTER_MONOTONIC,
SCHEMA_PARSEABLE (row level) and COMPLETENESS (meter-day level; flagged days
land in silver.dq_flags as LOW_COMPLETENESS). DUPLICATE is not a quality
failure (dedupe is normal processing) and is excluded from every denominator.

dq_pass_rate[ALL] = rows passing every row-level rule / rows evaluated.
Also written: dq_pass_rate[<check>] and dq_meter_days_flagged[ALL].

dq_gate(results) -> failing dates: dq_pass_rate[ALL] < ALERT_DQ_PASS_RATE_MIN
or any FAIL. The pipeline raises DQGateError unless DQ_GATE=warn.
Idempotent per date (delete + insert in one transaction).
"""

from __future__ import annotations

import datetime as dt
import json
import os

import psycopg

from src.dq.schema import create_dq_schema
from src.gold.schema import COMPLETE_PCT, INTERVALS_PER_DAY
from src.observability.schema import create_obs_schema
from src.storage.partitions import ensure_partition

ROW_CHECKS = {
    "METER_IN_MASTER": ("UNKNOWN_METER",),
    "ENERGY_NON_NEGATIVE": ("NEGATIVE_ENERGY",),
    "REGISTER_MONOTONIC": ("REGISTER_DECREASE_NO_ROLLOVER",),
    "SCHEMA_PARSEABLE": ("UNPARSEABLE", "BAD_SCHEMA"),
}

INVARIANT_SQL = {
    "METER_IN_MASTER": """
        SELECT count(*) FROM silver.meter_readings r
        WHERE r.reading_date = %(d)s
          AND NOT EXISTS (SELECT 1 FROM ref.dim_meter m WHERE m.meter_id = r.meter_id)""",
    "ENERGY_NON_NEGATIVE": """
        SELECT count(*) FROM silver.meter_readings
        WHERE reading_date = %(d)s AND energy_kwh < 0""",
    # previous accepted reading may be on an earlier day (7-day look-back,
    # same bound silver uses), so a decrease across midnight is caught too
    "REGISTER_MONOTONIC": """
        SELECT count(*) FROM (
            SELECT reading_date, rollover, register_kwh,
                   lag(register_kwh) OVER (PARTITION BY meter_id ORDER BY reading_ts)
                       AS prev_register
            FROM silver.meter_readings
            WHERE reading_date BETWEEN %(d)s::date - 7 AND %(d)s
        ) x
        WHERE reading_date = %(d)s AND register_kwh < prev_register AND NOT rollover""",
}

COMPLETENESS_FLAGS_SQL = f"""
INSERT INTO silver.dq_flags
    (meter_id, reading_date, flag_code, feeder_id, zone_id, intervals_present,
     completeness_pct, run_id)
SELECT m.meter_id, %(d)s::date, 'LOW_COMPLETENESS', m.feeder_id, m.zone_id,
       coalesce(r.n, 0), round(100.0 * coalesce(r.n, 0) / {INTERVALS_PER_DAY}, 2),
       %(run_id)s
FROM ref.dim_meter m
LEFT JOIN (SELECT meter_id, count(*) AS n FROM silver.meter_readings
           WHERE reading_date = %(d)s GROUP BY meter_id) r USING (meter_id)
WHERE (m.install_date IS NULL OR m.install_date <= %(d)s)
  AND 100.0 * coalesce(r.n, 0) / {INTERVALS_PER_DAY} <= {COMPLETE_PCT}
"""


class DQGateError(RuntimeError):
    """Raised when a date fails the DQ gate (enforce mode)."""


def pass_rate_min() -> float:
    return float(os.environ.get("ALERT_DQ_PASS_RATE_MIN", "0.98"))


def gate_mode() -> str:
    return (
        "warn" if os.environ.get("DQ_GATE", "enforce").lower() == "warn" else "enforce"
    )


def _status(rate: float, threshold: float, invariant_ok: bool | None) -> str:
    if invariant_ok is False:
        return "FAIL"
    return "WARN" if rate < threshold else "PASS"


def run_dq_date(conn: psycopg.Connection, day: dt.date | str, run_id: str) -> dict:
    """Evaluate every check for D; write obs.dq_results, silver.dq_flags and
    dq metrics into obs.metrics. Returns a summary dict."""
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    create_obs_schema(conn)
    create_dq_schema(conn)
    threshold = pass_rate_min()
    p = {"d": day, "run_id": run_id}

    try:
        ensure_partition(conn, "silver.dq_flags", day)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM silver.meter_readings WHERE reading_date = %(d)s",
                p,
            )
            (accepted,) = cur.fetchone()
            cur.execute(
                """SELECT reason_code, count(*) FROM silver.quarantine
                   WHERE reading_date = %(d)s AND reason_code <> 'DUPLICATE'
                   GROUP BY reason_code""",
                p,
            )
            caught = dict(cur.fetchall())
            evaluated = accepted + sum(caught.values())

            results = []
            for name, codes in ROW_CHECKS.items():
                failed = sum(caught.get(c, 0) for c in codes)
                bad = None
                if name in INVARIANT_SQL:
                    cur.execute(INVARIANT_SQL[name], p)
                    (bad,) = cur.fetchone()
                inv_ok = None if bad is None else bad == 0
                rate = 1.0 if evaluated == 0 else 1 - failed / evaluated
                results.append(
                    (
                        name,
                        evaluated,
                        failed,
                        rate,
                        inv_ok,
                        {
                            "reason_codes": list(codes),
                            "invariant_violations": bad,
                        },
                    )
                )

            cur.execute("DELETE FROM silver.dq_flags WHERE reading_date = %(d)s", p)
            cur.execute(COMPLETENESS_FLAGS_SQL, p)
            flagged = cur.rowcount
            cur.execute(
                """SELECT count(*) FROM ref.dim_meter
                   WHERE install_date IS NULL OR install_date <= %(d)s""",
                p,
            )
            (meter_days,) = cur.fetchone()
            cur.execute(
                """SELECT meter_id, completeness_pct FROM silver.dq_flags
                   WHERE reading_date = %(d)s ORDER BY completeness_pct, meter_id
                   LIMIT 10""",
                p,
            )
            worst = [{"meter_id": m, "completeness_pct": float(c)} for m, c in cur]
            results.append(
                (
                    "COMPLETENESS",
                    meter_days,
                    flagged,
                    1.0 if meter_days == 0 else 1 - flagged / meter_days,
                    None,
                    {
                        "flag_code": "LOW_COMPLETENESS",
                        "rule": f"completeness_pct <= {COMPLETE_PCT}",
                        "worst_meters": worst,
                    },
                )
            )

            row_failed = sum(r[2] for r in results if r[0] in ROW_CHECKS)
            overall = 1.0 if evaluated == 0 else 1 - row_failed / evaluated
            any_fail = any(r[4] is False for r in results)

            cur.execute("DELETE FROM obs.dq_results WHERE check_date = %(d)s", p)
            cur.executemany(
                """INSERT INTO obs.dq_results
                   (check_date, check_name, rows_checked, rows_failed, pass_rate,
                    threshold, status, invariant_ok, detail, run_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        day,
                        name,
                        checked,
                        failed,
                        round(rate, 6),
                        threshold,
                        _status(rate, threshold, inv),
                        inv,
                        json.dumps(detail),
                        run_id,
                    )
                    for name, checked, failed, rate, inv, detail in results
                ],
            )
            metrics = [("dq_pass_rate", "ALL", round(overall, 6))]
            metrics += [("dq_pass_rate", r[0], round(r[3], 6)) for r in results]
            metrics += [("dq_meter_days_flagged", "ALL", flagged)]
            cur.execute(
                "DELETE FROM obs.metrics WHERE metric_date = %s"
                " AND metric_name IN ('dq_pass_rate', 'dq_meter_days_flagged')",
                (day,),
            )
            cur.executemany(
                "INSERT INTO obs.metrics (metric_date, metric_name, scope, value, run_id)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(day, n, s, v, run_id) for n, s, v in metrics],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    gate_ok = overall >= threshold and not any_fail
    return {
        "run_id": run_id,
        "date": day.isoformat(),
        "evaluated": evaluated,
        "dq_pass_rate": round(overall, 6),
        "checks": {r[0]: _status(r[3], threshold, r[4]) for r in results},
        "meter_days_flagged": flagged,
        "gate_ok": gate_ok,
    }


def dq_gate(summaries: list[dict]) -> list[str]:
    """Dates that fail the gate (pass rate under threshold or any FAIL)."""
    return [s["date"] for s in summaries if not s["gate_ok"]]
