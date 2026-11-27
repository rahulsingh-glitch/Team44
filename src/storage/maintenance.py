"""Compaction + retention (ADR-0002).

compact(dates)    : VACUUM (ANALYZE) the partitions those dates touch — run at
                    the end of every pipeline run/backfill. reindex=True adds
                    REINDEX CONCURRENTLY (scheduled `make compact` only).
                    Neither blocks readers; a lock_timeout makes a busy
                    partition get SKIPPED (reported), never hang the pipeline.
retention(as_of)  : DROP whole partitions entirely older than each table's
                    retention window. NOT part of `make run` — scheduled
                    separately (Airflow task / `make retention`).

`as_of` defaults to the DATA clock (max silver.reading_date), not wall-clock
today, so synthetic history is not wiped. Production passes --as-of today.

CLI:
  python -m src.storage.maintenance compact --date-from D --date-to D
  python -m src.storage.maintenance retention [--as-of D] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt

import psycopg
from psycopg import sql

from src.common.db import connect
from src.storage.partitions import PARTITIONED, bounds, list_partitions

LOCK_TIMEOUT = "5s"  # maintenance never waits longer than this on a lock

# table -> keep window (Postgres interval). Partitions whose upper bound is
# <= as_of - window hold only expired data and are dropped whole.
RETENTION: dict[str, str] = {
    "bronze.meter_events_raw": "30 days",
    "silver.meter_readings": "13 months",
    "silver.quarantine": "13 months",
    "silver.gaps": "13 months",
    "silver.dq_flags": "13 months",
    "gold.consumption_hourly": "13 months",
}


def _date_range(date_from: str, date_to: str) -> list[dt.date]:
    a, b = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


def compact(
    dates, reindex: bool = False, conn: psycopg.Connection | None = None
) -> dict:
    """VACUUM (ANALYZE) [+ REINDEX CONCURRENTLY] every existing partition
    holding `dates`. Needs autocommit (VACUUM / CONCURRENTLY cannot run in a
    transaction). Returns {"done": [...], "skipped": [(partition, error)]}."""
    dates = [dt.date.fromisoformat(d) if isinstance(d, str) else d for d in dates]
    own = conn is None
    conn = conn or connect(autocommit=True)
    done: list[str] = []
    skipped: list[tuple[str, str]] = []
    try:
        conn.execute(sql.SQL("SET lock_timeout = {}").format(sql.Literal(LOCK_TIMEOUT)))
        for table in PARTITIONED:
            existing = {p for p, _, _ in list_partitions(conn, table)}
            schema = table.split(".")[0]
            wanted = sorted({f"{schema}.{bounds(table, d)[0]}" for d in dates})
            for part in wanted:
                if part not in existing:
                    continue
                ident = sql.Identifier(*part.split("."))
                try:
                    conn.execute(
                        sql.SQL("VACUUM (ANALYZE, TRUNCATE false) {}").format(ident)
                    )
                    if reindex:
                        conn.execute(
                            sql.SQL("REINDEX TABLE CONCURRENTLY {}").format(ident)
                        )
                    done.append(part)
                except psycopg.errors.LockNotAvailable as exc:
                    skipped.append((part, str(exc).strip()))
    finally:
        if own:
            conn.close()
    return {"done": done, "skipped": skipped}


def data_clock(conn: psycopg.Connection) -> dt.date | None:
    return conn.execute(
        "SELECT max(reading_date) FROM silver.meter_readings"
    ).fetchone()[0]


def retention(
    as_of: dt.date | str | None = None,
    dry_run: bool = False,
    conn: psycopg.Connection | None = None,
) -> dict:
    """Drop partitions entirely older than each table's window.
    Returns {as_of, dry_run, dropped: [(partition, lower, upper, table)]}."""
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute(sql.SQL("SET lock_timeout = {}").format(sql.Literal(LOCK_TIMEOUT)))
        if isinstance(as_of, str):
            as_of = dt.date.fromisoformat(as_of)
        as_of = as_of or data_clock(conn)
        dropped = []
        if as_of is None:
            return {"as_of": None, "dry_run": dry_run, "dropped": dropped}
        for table, window in RETENTION.items():
            (keep_from,) = conn.execute(
                "SELECT (%s::date - %s::interval)::date", (as_of, window)
            ).fetchone()
            for part, lo, hi in list_partitions(conn, table):
                if hi is None or hi > keep_from:  # DEFAULT, or holds kept data
                    continue
                dropped.append((part, lo, hi, table))
                if not dry_run:
                    conn.execute(
                        sql.SQL("DROP TABLE {}").format(
                            sql.Identifier(*part.split("."))
                        )
                    )
        conn.commit()
        return {"as_of": as_of, "dry_run": dry_run, "dropped": dropped}
    finally:
        if own:
            conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compact")
    c.add_argument("--date-from", required=True)
    c.add_argument("--date-to", required=True)
    r = sub.add_parser("retention")
    r.add_argument("--as-of", default=None, help="YYYY-MM-DD; default = data clock")
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "compact":
        res = compact(_date_range(a.date_from, a.date_to), reindex=True)
        print(f"[compact] vacuumed+reindexed={len(res['done'])} {res['done']}")
        for part, err in res["skipped"]:
            print(f"[compact] SKIPPED {part} (lock busy): {err}")
    else:
        res = retention(a.as_of, a.dry_run)
        verb = "would drop" if res["dry_run"] else "dropped"
        print(f"[retention] as_of={res['as_of']} {verb}={len(res['dropped'])}")
        for part, lo, hi, table in res["dropped"]:
            print(f"[retention]   {verb} {part} [{lo}, {hi}) of {table}")


if __name__ == "__main__":
    main()
