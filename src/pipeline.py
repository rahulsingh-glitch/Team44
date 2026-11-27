"""Pipeline entry point: run one day or backfill a range.

Stages (one function each; the CLI and the Airflow DAG call the same ones):
stage_bronze (ref.dim_meter + landing) -> stage_silver -> stage_dq (checks +
gate) -> stage_gold (consumption) -> stage_anomaly -> stage_publish
(compaction + obs metrics + COMPLETENESS_DROP alert). Every stage is timed
into obs.run_log (stage 'pipeline' = whole run; failures recorded, then
re-raised). The DQ gate raises DQGateError (stopping gold) for a failing date
unless DQ_GATE=warn. Retention is NOT run here (src/storage/maintenance.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import time
from pathlib import Path

from src.bronze.load import discover_dates, load_date, new_run_id
from src.common.db import connect
from src.dq.checks import DQGateError, dq_gate, gate_mode, run_dq_date
from src.gold.anomaly import build_anomaly_date
from src.gold.consumption import build_gold_date
from src.observability.metrics import (
    evaluate_alert,
    record_metrics,
    record_run_duration,
)
from src.observability.run_log import track
from src.ref.dim_meter import load_dim_meter
from src.silver.load import build_silver_date
from src.storage.maintenance import compact

# GRIDPULSE_LANDING lets Airflow (container paths) point at the mounted landing dir
LANDING = Path(os.environ.get("GRIDPULSE_LANDING", "data/landing"))
BRONZE_KEYS = ("loaded", "skipped_duplicate", "unparseable", "rows")


def _print_bronze(stage: str, s: dict) -> None:
    print(
        f"[{stage}] run_id={s['run_id']} loaded={s['loaded']} "
        f"skipped_duplicate={s['skipped_duplicate']} unparseable={s['unparseable']} "
        f"rows={s['rows']}"
    )


def _print_silver(s: dict) -> None:
    print(
        f"[silver] date={s['date']} readings={s['readings']} "
        f"quarantined={s['quarantined']} {s['reasons']} "
        f"gaps={s['gaps']} missing_intervals={s['missing_intervals']}"
    )


def _print_dq(s: dict) -> None:
    print(
        f"[dq] date={s['date']} dq_pass_rate={s['dq_pass_rate']} "
        f"flagged_meter_days={s['meter_days_flagged']} gate_ok={s['gate_ok']} "
        f"{s['checks']}"
    )


def _print_gold(s: dict) -> None:
    print(
        f"[gold] date={s['date']} hourly={s['hourly']} daily={s['daily']} "
        f"incomplete_meters={s['incomplete_meters']} kwh={s['kwh']:.3f} "
        f"billing_month={s['billing_month']} billing_rows={s['billing_rows']}"
    )


def _print_anomaly(s: dict) -> None:
    print(
        f"[anomaly] date={s['date']} SPIKE={s['SPIKE']} TAMPER={s['TAMPER']} "
        f"OUTAGE={s['OUTAGE']}"
    )


def _run_dates(dates: list[str], landing: Path, stage: str) -> dict:
    run_id = new_run_id("run")
    totals: dict = {"run_id": run_id}
    t0 = time.perf_counter()
    with track(run_id, "pipeline") as whole:
        whole["detail"] = {"mode": stage, "dates": dates}
        totals.update(stage_bronze(dates, run_id, landing, label=stage))
        totals["silver"] = stage_silver(dates, run_id)
        totals["dq"] = stage_dq(dates, run_id)
        totals["gold"] = stage_gold(dates, run_id)
        totals["anomaly"] = stage_anomaly(dates, run_id)
        totals.update(stage_publish(dates, run_id, landing))
        whole["rows_out"] = totals["rows"]
    if dates:
        with connect() as conn:
            record_run_duration(conn, dates[-1], run_id, time.perf_counter() - t0)
    return totals


# --- stages: one function per DAG task; the CLI calls them in the same order.
# Each opens its own connection so it can run in a separate Airflow task.


def stage_bronze(
    dates: list[str], run_id: str, landing: Path = LANDING, label: str = "bronze"
) -> dict:
    """ref.dim_meter + land every date's files (bronze first for ALL dates, so
    silver sees late/adjacent files)."""
    totals = {k: 0 for k in BRONZE_KEYS}
    with connect() as conn:
        load_dim_meter(conn, landing / "_master" / "dim_meter.csv")
        for d in dates:
            with track(run_id, "bronze", d) as t:
                s = load_date(conn, landing, d, run_id)
                t["rows_out"], t["detail"] = s["rows"], s
            for k in BRONZE_KEYS:
                totals[k] += s[k]
    _print_bronze(label, {"run_id": run_id, **totals})
    return totals


def stage_silver(dates: list[str], run_id: str) -> list[dict]:
    out = []
    with connect() as conn:
        for d in dates:
            with track(run_id, "silver", d) as t:
                s = build_silver_date(conn, d, run_id)
                t["rows_out"], t["detail"] = s["readings"], s
            out.append(s)
            _print_silver(s)
    return out


def stage_dq(dates: list[str], run_id: str) -> list[dict]:
    """DQ after ALL silver dates (REGISTER_MONOTONIC looks back across days),
    then the gate: raises DQGateError unless DQ_GATE=warn."""
    out = []
    with connect() as conn:
        for d in dates:
            with track(run_id, "dq", d) as t:
                s = run_dq_date(conn, d, run_id)
                t["rows_out"], t["detail"] = s["evaluated"], s
            out.append(s)
            _print_dq(s)
    failing = dq_gate(out)
    if failing:
        msg = f"DQ gate failed for {failing} (mode={gate_mode()})"
        if gate_mode() == "enforce":
            with track(run_id, "dq_gate") as t:
                t["detail"] = {"failing_dates": failing}
                raise DQGateError(msg + " - gold not built")
        print(f"[dq] WARNING {msg} - continuing (DQ_GATE=warn)")
    return out


def stage_gold(dates: list[str], run_id: str) -> list[dict]:
    """After ALL silver dates, so each date's month rebuild sees them."""
    out = []
    with connect() as conn:
        for d in dates:
            with track(run_id, "gold", d) as t:
                s = build_gold_date(conn, d, run_id)
                t["rows_out"], t["detail"] = s["hourly"], s
            out.append(s)
            _print_gold(s)
    return out


def stage_anomaly(dates: list[str], run_id: str) -> list[dict]:
    """After ALL gold dates: TAMPER reads consumption_daily for D-1."""
    out = []
    with connect() as conn:
        for d in dates:
            with track(run_id, "anomaly", d) as t:
                s = build_anomaly_date(conn, d, run_id)
                t["rows_out"], t["detail"] = s["SPIKE"] + s["TAMPER"] + s["OUTAGE"], s
            out.append(s)
            _print_anomaly(s)
    return out


def stage_publish(dates: list[str], run_id: str, landing: Path = LANDING) -> dict:
    """Compaction (VACUUM, own autocommit connection) + obs metrics and the
    COMPLETENESS_DROP alert, in DATE ORDER (the alert baseline reads earlier
    dates)."""
    with track(run_id, "storage") as t:
        res = compact(dates)  # VACUUM (ANALYZE) only; REINDEX is `make compact`
        t["rows_out"], t["detail"] = len(res["done"]), res
    print(
        f"[storage] vacuumed partitions={len(res['done'])} "
        f"skipped_lock_busy={len(res['skipped'])}"
    )
    alerts = []
    with connect() as conn:
        for d in sorted(dates):
            with track(run_id, "obs", d) as t:
                m = record_metrics(conn, d, run_id, landing)
                fired = evaluate_alert(conn, d, run_id)
                t["rows_out"], t["detail"] = len(fired), m
            alerts += [(d, f[0]) for f in fired]
            print(
                f"[obs] date={d} completeness={m.get('completeness_pct[ALL]')} "
                f"duplicate_rate={m['duplicate_rate[ALL]']} "
                f"ingest_lag_s={m['ingest_lag_s[ALL]']} alerts={len(fired)}"
            )
    return {"compacted": res, "alerts": alerts}


def date_range(date_from: str, date_to: str) -> list[str]:
    start = dt.date.fromisoformat(date_from)
    end = dt.date.fromisoformat(date_to)
    return [
        (start + dt.timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
    ]


def run(date: str, landing: Path = LANDING) -> dict:
    """Run the pipeline for one date, or 'all' landing dates."""
    if date == "all":
        dates = discover_dates(landing)
    else:
        dates = [dt.date.today().isoformat() if date == "today" else date]
    return _run_dates(dates, landing, "bronze")


def backfill(date_from: str, date_to: str, landing: Path = LANDING) -> dict:
    """Re-run every date in [date_from, date_to] (silver replaces each date)."""
    return _run_dates(date_range(date_from, date_to), landing, "bronze-backfill")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument(
        "--date", default="today", help="YYYY-MM-DD, or 'all' for every landing date"
    )
    b = sub.add_parser("backfill")
    b.add_argument("--date-from", required=True)
    b.add_argument("--date-to", required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.date)
    else:
        backfill(a.date_from, a.date_to)


if __name__ == "__main__":
    main()
