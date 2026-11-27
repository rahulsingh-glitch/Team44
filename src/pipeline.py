"""Pipeline entry point: run one day or backfill a range.

Medallion steps wired so far: ref.dim_meter -> bronze landing -> silver
normalisation. Later layers (dq -> gold -> anomaly) extend `_run_dates`.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from src.bronze.load import discover_dates, load_date, new_run_id
from src.common.db import connect
from src.ref.dim_meter import load_dim_meter
from src.silver.load import build_silver_date

LANDING = Path("data/landing")
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


def _run_dates(dates: list[str], landing: Path, stage: str) -> dict:
    run_id = new_run_id("run")
    totals = {"run_id": run_id, **{k: 0 for k in BRONZE_KEYS}, "silver": []}
    with connect() as conn:
        load_dim_meter(conn, landing / "_master" / "dim_meter.csv")
        # bronze first for every date, so silver sees late/adjacent files
        for d in dates:
            s = load_date(conn, landing, d, run_id)
            for k in BRONZE_KEYS:
                totals[k] += s[k]
        _print_bronze(stage, totals)
        for d in dates:
            s = build_silver_date(conn, d, run_id)
            totals["silver"].append(s)
            _print_silver(s)
    return totals


def run(date: str, landing: Path = LANDING) -> dict:
    """Run the pipeline for one date, or 'all' landing dates."""
    if date == "all":
        dates = discover_dates(landing)
    else:
        dates = [dt.date.today().isoformat() if date == "today" else date]
    return _run_dates(dates, landing, "bronze")


def backfill(date_from: str, date_to: str, landing: Path = LANDING) -> dict:
    """Re-run every date in [date_from, date_to] (silver replaces each date)."""
    start = dt.date.fromisoformat(date_from)
    end = dt.date.fromisoformat(date_to)
    dates = [
        (start + dt.timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
    ]
    return _run_dates(dates, landing, "bronze-backfill")


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
