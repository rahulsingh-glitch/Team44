"""Partition registry + helpers (ADR-0002).

Native Postgres RANGE partitioning:
- bronze.meter_events_raw by source_date, DAILY (+ DEFAULT for NULL dates)
- silver.{meter_readings, quarantine, gaps, dq_flags} by reading_date, DAILY
- gold.consumption_{hourly, daily} by reading_date, MONTHLY

Writers call ensure_partition() before inserting (idempotent). Each layer's
create_*_schema() wraps its DDL in detach_legacy()/restore_legacy() so a
database built before partitioning is migrated in place, in one transaction.
"""

from __future__ import annotations

import datetime as dt
import re

import psycopg
from psycopg import sql

# table -> (partition key column, grain)
PARTITIONED: dict[str, tuple[str, str]] = {
    "bronze.meter_events_raw": ("source_date", "day"),
    "silver.meter_readings": ("reading_date", "day"),
    "silver.quarantine": ("reading_date", "day"),
    "silver.gaps": ("reading_date", "day"),
    "silver.dq_flags": ("reading_date", "day"),
    "gold.consumption_hourly": ("reading_date", "month"),
    "gold.consumption_daily": ("reading_date", "month"),
}

_BOUND_RE = re.compile(r"FROM \('([\d-]+)'\) TO \('([\d-]+)'\)")


def _split(table: str) -> tuple[str, str]:
    schema, name = table.split(".")
    return schema, name


def bounds(table: str, day: dt.date) -> tuple[str, dt.date, dt.date]:
    """(partition name, lower incl., upper excl.) holding `day` for `table`."""
    _, grain = PARTITIONED[table]
    _, name = _split(table)
    if grain == "day":
        return f"{name}_p{day:%Y%m%d}", day, day + dt.timedelta(days=1)
    lo = day.replace(day=1)
    hi = (lo + dt.timedelta(days=32)).replace(day=1)
    return f"{name}_p{lo:%Y%m}", lo, hi


def ensure_partition(conn: psycopg.Connection, table: str, day: dt.date) -> str:
    """Create the partition of `table` that holds `day`, if missing."""
    schema, name = _split(table)
    part, lo, hi = bounds(table, day)
    conn.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {}.{} PARTITION OF {}.{} "
            "FOR VALUES FROM ({}) TO ({})"
        ).format(
            sql.Identifier(schema),
            sql.Identifier(part),
            sql.Identifier(schema),
            sql.Identifier(name),
            sql.Literal(lo),
            sql.Literal(hi),
        )
    )
    return f"{schema}.{part}"


def ensure_partitions(conn: psycopg.Connection, table: str, days) -> None:
    seen: set[str] = set()
    for d in days:
        if d is None:
            continue
        part = bounds(table, d)[0]
        if part not in seen:
            seen.add(part)
            ensure_partition(conn, table, d)


def list_partitions(
    conn: psycopg.Connection, table: str
) -> list[tuple[str, dt.date | None, dt.date | None]]:
    """[(schema.partition, lower, upper)] — bounds read from the catalog;
    (None, None) for a DEFAULT partition."""
    rows = conn.execute(
        """SELECT n.nspname || '.' || c.relname,
                  pg_get_expr(c.relpartbound, c.oid)
           FROM pg_inherits i
           JOIN pg_class c ON c.oid = i.inhrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE i.inhparent = %s::regclass
           ORDER BY 1""",
        (table,),
    ).fetchall()
    out = []
    for part, expr in rows:
        m = _BOUND_RE.search(expr or "")
        if m:
            out.append((part, dt.date.fromisoformat(m[1]), dt.date.fromisoformat(m[2])))
        else:
            out.append((part, None, None))
    return out


def _relkind(conn: psycopg.Connection, table: str) -> str | None:
    schema, name = _split(table)
    row = conn.execute(
        """SELECT c.relkind FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = %s AND c.relname = %s""",
        (schema, name),
    ).fetchone()
    return row[0] if row else None


def detach_legacy(conn: psycopg.Connection, tables) -> list[tuple[str, str]]:
    """Rename any PLAIN (pre-partitioning) table and its indexes out of the
    way so the partitioned DDL can create the real one. Returns
    [(table, legacy_table)]. No-op for tables already partitioned/absent."""
    moved = []
    for table in tables:
        if _relkind(conn, table) != "r":
            continue
        schema, name = _split(table)
        for (idx,) in conn.execute(
            """SELECT ci.relname FROM pg_index i
               JOIN pg_class ci ON ci.oid = i.indexrelid
               WHERE i.indrelid = %s::regclass""",
            (table,),
        ).fetchall():
            conn.execute(
                sql.SQL("ALTER INDEX {}.{} RENAME TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(idx),
                    sql.Identifier(f"{idx[:50]}_legacy"),
                )
            )
        legacy = f"{name}_legacy"
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                sql.Identifier(schema), sql.Identifier(name), sql.Identifier(legacy)
            )
        )
        moved.append((table, f"{schema}.{legacy}"))
    return moved


def restore_legacy(conn: psycopg.Connection, moved: list[tuple[str, str]]) -> None:
    """Copy legacy rows into the new partitioned table, carry serial
    sequences forward, then drop the legacy table."""
    for table, legacy in moved:
        key, _ = PARTITIONED[table]
        schema, name = _split(table)
        lschema, lname = _split(legacy)
        keys = [
            r[0]
            for r in conn.execute(
                sql.SQL("SELECT DISTINCT {} FROM {}.{}").format(
                    sql.Identifier(key), sql.Identifier(lschema), sql.Identifier(lname)
                )
            ).fetchall()
        ]
        ensure_partitions(conn, table, keys)
        cols = [
            r[0]
            for r in conn.execute(
                """SELECT a.attname FROM pg_attribute a
                   WHERE a.attrelid = %s::regclass AND a.attnum > 0
                     AND NOT a.attisdropped
                     AND a.attname IN (SELECT attname FROM pg_attribute
                                       WHERE attrelid = %s::regclass
                                         AND attnum > 0 AND NOT attisdropped)
                   ORDER BY a.attnum""",
                (table, legacy),
            ).fetchall()
        ]
        collist = sql.SQL(", ").join(map(sql.Identifier, cols))
        conn.execute(
            sql.SQL("INSERT INTO {}.{} ({}) SELECT {} FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(name),
                collist,
                collist,
                sql.Identifier(lschema),
                sql.Identifier(lname),
            )
        )
        for col in cols:
            (seq,) = conn.execute(
                "SELECT pg_get_serial_sequence(%s, %s)", (table, col)
            ).fetchone()
            if seq:
                conn.execute(
                    sql.SQL(
                        "SELECT setval({}, coalesce((SELECT max({}) FROM {}.{}), 0) + 1,"
                        " false)"
                    ).format(
                        sql.Literal(seq),
                        sql.Identifier(col),
                        sql.Identifier(schema),
                        sql.Identifier(name),
                    )
                )
        conn.execute(
            sql.SQL("DROP TABLE {}.{}").format(
                sql.Identifier(lschema), sql.Identifier(lname)
            )
        )
