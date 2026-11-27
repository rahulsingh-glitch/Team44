"""obs.metrics + the ONE alert (COMPLETENESS_DROP).

record_metrics(conn, D, run_id, landing) replaces D's metrics:
  completeness_pct  (scope ALL + per zone)  from gold.consumption_daily
  readings, quarantine_count, duplicate_rate (ALL)  from silver
  ingest_lag_s      (ALL) worst file: bronze load_time - landing file mtime
run_duration_s is written by the pipeline at the end of a run.

evaluate_alert(conn, D, run_id) — COMPLETENESS_DROP fires per scope (ALL, each
zone) when completeness_pct < ALERT_COMPLETENESS_MIN_PCT, or is more than
ALERT_COMPLETENESS_DROP_PTS below the mean of that scope's previous (up to) 7
days. Writes obs.alert (D's alerts replaced) and prints an ALERT line to
stderr. Call in date order: the baseline reads earlier dates' metrics.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import psycopg

from src.bronze.load import iter_landing_files
from src.observability.schema import create_obs_schema

ALERT_NAME = "COMPLETENESS_DROP"
BASELINE_DAYS = 7
DATE_METRICS = (
    "completeness_pct",
    "readings",
    "quarantine_count",
    "duplicate_rate",
    "ingest_lag_s",
)


def thresholds() -> dict:
    return {
        "min_pct": float(os.environ.get("ALERT_COMPLETENESS_MIN_PCT", "90")),
        "drop_pts": float(os.environ.get("ALERT_COMPLETENESS_DROP_PTS", "2.0")),
        "baseline_days": BASELINE_DAYS,
    }


def _ingest_lag_s(
    conn: psycopg.Connection, day: dt.date, landing: Path | None
) -> float | None:
    """Worst (load_time - file mtime) over D's landing files that were loaded.

    Only files whose bronze load happened AT/AFTER the file's current mtime
    count. A file rewritten after its load (re-delivered / re-seeded with the
    same bytes -> bronze skips it by checksum) no longer carries its original
    arrival time, so comparing would give a NEGATIVE lag. None = no file on D
    has a measurable arrival->load lag."""
    if landing is None or not Path(landing).is_dir():
        return None
    mtimes = {
        p.relative_to(landing).as_posix(): dt.datetime.fromtimestamp(
            p.stat().st_mtime, dt.UTC
        )
        for p in iter_landing_files(Path(landing), day.isoformat())
    }
    if not mtimes:
        return None
    rows = conn.execute(
        """SELECT DISTINCT ON (source_file) source_file, load_time
           FROM bronze.load_log
           WHERE status = 'loaded' AND source_file = ANY(%s)
           ORDER BY source_file, load_time DESC""",
        (list(mtimes),),
    ).fetchall()
    lags = [(lt - mtimes[sf]).total_seconds() for sf, lt in rows if lt >= mtimes[sf]]
    return round(max(lags), 3) if lags else None


def record_metrics(
    conn: psycopg.Connection,
    day: dt.date | str,
    run_id: str,
    landing: Path | None = None,
) -> dict:
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    create_obs_schema(conn)
    rows: list[tuple[str, str, float | None]] = []
    for scope, pct in conn.execute(
        """SELECT 'ALL', round(100.0 * sum(intervals_present) / sum(intervals_expected), 4)
           FROM gold.consumption_daily WHERE reading_date = %(d)s
           HAVING count(*) > 0
           UNION ALL
           SELECT zone_id, round(100.0 * sum(intervals_present) / sum(intervals_expected), 4)
           FROM gold.consumption_daily WHERE reading_date = %(d)s GROUP BY zone_id""",
        {"d": day},
    ).fetchall():
        rows.append(("completeness_pct", scope, pct))
    readings, quarantined, dups = conn.execute(
        """SELECT (SELECT count(*) FROM silver.meter_readings WHERE reading_date = %(d)s),
                  (SELECT count(*) FROM silver.quarantine WHERE reading_date = %(d)s),
                  (SELECT count(*) FROM silver.quarantine
                    WHERE reading_date = %(d)s AND reason_code = 'DUPLICATE')""",
        {"d": day},
    ).fetchone()
    rows += [
        ("readings", "ALL", readings),
        ("quarantine_count", "ALL", quarantined),
        (
            "duplicate_rate",
            "ALL",
            round(dups / (readings + dups), 6) if readings + dups else 0,
        ),
        ("ingest_lag_s", "ALL", _ingest_lag_s(conn, day, landing)),
    ]
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM obs.metrics WHERE metric_date = %s AND metric_name = ANY(%s)",
            (day, list(DATE_METRICS)),
        )
        cur.executemany(
            "INSERT INTO obs.metrics (metric_date, metric_name, scope, value, run_id)"
            " VALUES (%s, %s, %s, %s, %s)",
            [(day, n, s, v, run_id) for n, s, v in rows],
        )
    conn.commit()
    return {f"{n}[{s}]": v for n, s, v in rows}


def record_run_duration(
    conn: psycopg.Connection, day: dt.date | str, run_id: str, seconds: float
) -> None:
    create_obs_schema(conn)
    conn.execute(
        """INSERT INTO obs.metrics (metric_date, metric_name, scope, value, run_id)
           VALUES (%s, 'run_duration_s', 'ALL', %s, %s)
           ON CONFLICT (metric_date, metric_name, scope) DO UPDATE
           SET value = EXCLUDED.value, run_id = EXCLUDED.run_id, recorded_at = now()""",
        (day, round(seconds, 3), run_id),
    )
    conn.commit()


def evaluate_alert(conn: psycopg.Connection, day: dt.date | str, run_id: str) -> list:
    """Evaluate COMPLETENESS_DROP for D; returns the alerts fired."""
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    create_obs_schema(conn)
    th = thresholds()
    scopes = conn.execute(
        """SELECT t.scope, t.value,
                  (SELECT avg(b.value) FROM obs.metrics b
                    WHERE b.metric_name = 'completeness_pct' AND b.scope = t.scope
                      AND b.metric_date BETWEEN %(d)s::date - %(n)s AND %(d)s::date - 1)
                    AS baseline
           FROM obs.metrics t
           WHERE t.metric_name = 'completeness_pct' AND t.metric_date = %(d)s
           ORDER BY t.scope""",
        {"d": day, "n": BASELINE_DAYS},
    ).fetchall()
    fired = []
    for scope, value, baseline in scopes:
        reasons = []
        if value < th["min_pct"]:
            reasons.append(f"below floor {th['min_pct']}%")
        if baseline is not None and baseline - value > th["drop_pts"]:
            reasons.append(
                f"dropped {float(baseline - value):.2f} pts vs {BASELINE_DAYS}d mean"
            )
        if not reasons:
            continue
        worst = conn.execute(
            """SELECT feeder_id, completeness_pct, meters - meters_complete
               FROM gold.consumption_daily_feeder
               WHERE reading_date = %s AND (%s = 'ALL' OR zone_id = %s)
               ORDER BY completeness_pct, feeder_id LIMIT 3""",
            (day, scope, scope),
        ).fetchall()
        evidence = {
            "reasons": reasons,
            "worst_feeders": [
                {"feeder_id": f, "completeness_pct": float(p), "meters_incomplete": m}
                for f, p, m in worst
            ],
        }
        base_txt = f"{float(baseline):.2f}%" if baseline is not None else "n/a"
        msg = (
            f"ALERT {ALERT_NAME} date={day} scope={scope} "
            f"completeness={float(value):.2f}% baseline={base_txt} "
            f"({'; '.join(reasons)}); worst feeder="
            f"{worst[0][0] if worst else 'n/a'}"
        )
        fired.append((scope, value, baseline, evidence, msg))
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM obs.alert WHERE alert_name = %s AND metric_date = %s",
            (ALERT_NAME, day),
        )
        cur.executemany(
            "INSERT INTO obs.alert (alert_name, metric_date, scope, value, baseline,"
            " threshold, evidence, message, run_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (ALERT_NAME, day, s, v, b, json.dumps(th), json.dumps(e), m, run_id)
                for s, v, b, e, m in fired
            ],
        )
    conn.commit()
    for *_, msg in fired:
        print(msg, file=sys.stderr, flush=True)
    return fired
