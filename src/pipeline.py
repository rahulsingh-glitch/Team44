"""Pipeline entry point: run one day or backfill a range.

Medallion steps are wired here as each layer lands. Currently: bronze landing.
Later layers (silver -> dq -> gold -> marts) extend `run`.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from src.bronze.load import load_all, load_date, new_run_id
from src.common.db import connect

LANDING = Path("data/landing")


def _print_summary(stage: str, summary: dict) -> None:
    print(
        f"[{stage}] run_id={summary['run_id']} "
        f"loaded={summary['loaded']} skipped_duplicate={summary['skipped_duplicate']} "
        f"unparseable={summary['unparseable']} rows={summary['rows']}"
    )


def run(date: str, landing: Path = LANDING) -> dict:
    """Run the pipeline for one date (or 'all' landing dates). Bronze for now."""
    run_id = new_run_id()
    with connect() as conn:
        if date == "all":
            summary = load_all(conn, landing, run_id)
        else:
            resolved = dt.date.today().isoformat() if date == "today" else date
            summary = load_date(conn, landing, resolved, run_id)
    _print_summary("bronze", summary)
    return summary


def backfill(date_from: str, date_to: str, landing: Path = LANDING) -> dict:
    """Land every date in [date_from, date_to]."""
    start = dt.date.fromisoformat(date_from)
    end = dt.date.fromisoformat(date_to)
    run_id = new_run_id()
    totals = {
        "run_id": run_id,
        "loaded": 0,
        "skipped_duplicate": 0,
        "unparseable": 0,
        "rows": 0,
    }
    with connect() as conn:
        day = start
        while day <= end:
            s = load_date(conn, landing, day.isoformat(), run_id)
            for k in ("loaded", "skipped_duplicate", "unparseable", "rows"):
                totals[k] += s[k]
            day += dt.timedelta(days=1)
    _print_summary("bronze-backfill", totals)
    return totals


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
