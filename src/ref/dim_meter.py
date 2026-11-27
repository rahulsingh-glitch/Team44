"""ref.dim_meter — meter master loaded from the generator's CSV.

Silver needs it for UNKNOWN_METER checks, feeder/zone enrichment and the
unit fallback (CLAUDE.md §4 UNIT RULE). Upsert, so re-loading is idempotent.
"""

from __future__ import annotations

import csv
from pathlib import Path

import psycopg

DDL = """
CREATE SCHEMA IF NOT EXISTS ref;
CREATE TABLE IF NOT EXISTS ref.dim_meter (
    meter_id       TEXT PRIMARY KEY,
    feeder_id      TEXT     NOT NULL,
    zone_id        TEXT     NOT NULL,
    unit           TEXT     NOT NULL CHECK (unit IN ('Wh', 'kWh')),
    schema_version SMALLINT NOT NULL,
    model          TEXT,
    firmware       TEXT,
    install_date   DATE
);
CREATE INDEX IF NOT EXISTS ix_dim_meter_feeder ON ref.dim_meter (feeder_id);
"""

UPSERT = """
INSERT INTO ref.dim_meter
    (meter_id, feeder_id, zone_id, unit, schema_version, model, firmware, install_date)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (meter_id) DO UPDATE SET
    feeder_id = EXCLUDED.feeder_id, zone_id = EXCLUDED.zone_id,
    unit = EXCLUDED.unit, schema_version = EXCLUDED.schema_version,
    model = EXCLUDED.model, firmware = EXCLUDED.firmware,
    install_date = EXCLUDED.install_date
"""


def create_ref_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def load_dim_meter(conn: psycopg.Connection, csv_path: Path) -> int:
    """Upsert the meter master. Returns rows read (0 if the CSV is absent)."""
    create_ref_schema(conn)
    if not csv_path.is_file():
        return 0
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = [
            (
                r["meter_id"],
                r["feeder_id"],
                r["zone_id"],
                r["unit"],
                int(r["schema_version"]),
                r.get("model") or None,
                r.get("firmware") or None,
                r.get("install_date") or None,
            )
            for r in csv.DictReader(fh)
        ]
    with conn.cursor() as cur:
        cur.executemany(UPSERT, rows)
    conn.commit()
    return len(rows)


def fetch_meters(conn: psycopg.Connection) -> dict[str, dict]:
    """meter_id -> {feeder_id, zone_id, unit}."""
    with conn.cursor() as cur:
        cur.execute("SELECT meter_id, feeder_id, zone_id, unit FROM ref.dim_meter")
        return {
            m: {"feeder_id": f, "zone_id": z, "unit": u}
            for m, f, z, u in cur.fetchall()
        }
