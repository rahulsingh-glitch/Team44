"""Pipeline entry point: run one day or backfill a range.

Wire the medallion steps here: ingest -> bronze -> silver -> dq_gate -> gold -> marts.
Kept thin so `make run` and `make backfill` work during rehearsal.
"""
import argparse


def run(date: str) -> None:
    print(f"[stub] run pipeline for {date}")


def backfill(date_from: str, date_to: str) -> None:
    print(f"[stub] backfill {date_from}..{date_to}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--date", default="today")
    b = sub.add_parser("backfill"); b.add_argument("--date-from", required=True); b.add_argument("--date-to", required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.date)
    else:
        backfill(a.date_from, a.date_to)


if __name__ == "__main__":
    main()
