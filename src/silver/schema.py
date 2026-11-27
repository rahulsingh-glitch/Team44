"""Silver DDL — normalised readings, quarantine, gaps (CLAUDE.md §3).

Idempotent: safe to call on every run. `reading_date` is carried on every table
and every table is RANGE-partitioned daily by it (ADR-0002); partition keys
must be part of each PK. A pre-partitioning DB is migrated in place.
"""

from __future__ import annotations

import psycopg

from src.storage.partitions import detach_legacy, restore_legacy

REASON_CODES = (
    "UNKNOWN_METER",
    "NEGATIVE_ENERGY",
    "REGISTER_DECREASE_NO_ROLLOVER",
    "UNPARSEABLE",
    "BAD_SCHEMA",
    "DUPLICATE",
)

_REASON_LIST = ", ".join(f"'{c}'" for c in REASON_CODES)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS silver.meter_readings (
    meter_id        TEXT          NOT NULL,
    reading_ts      TIMESTAMPTZ   NOT NULL,     -- UTC, 15-min aligned
    reading_date    DATE          NOT NULL,     -- UTC date of reading_ts
    feeder_id       TEXT          NOT NULL,
    zone_id         TEXT          NOT NULL,
    energy_kwh      NUMERIC(14,6) NOT NULL,     -- interval consumption, kWh
    register_kwh    NUMERIC(16,6) NOT NULL,     -- cumulative register, kWh
    source_unit     TEXT          NOT NULL,     -- Wh | kWh (as reported)
    status          TEXT,
    voltage         NUMERIC(7,2),               -- v2 only
    firmware        TEXT,                       -- v2 only
    schema_version  SMALLINT      NOT NULL,
    rollover        BOOLEAN       NOT NULL DEFAULT false,
    is_duplicate    BOOLEAN       NOT NULL DEFAULT false,
    bronze_event_id BIGINT        NOT NULL,
    run_id          TEXT          NOT NULL,
    PRIMARY KEY (meter_id, reading_ts, reading_date)
) PARTITION BY RANGE (reading_date);
CREATE INDEX IF NOT EXISTS ix_meter_readings_date_zone
    ON silver.meter_readings (reading_date, zone_id);
CREATE INDEX IF NOT EXISTS ix_meter_readings_date_feeder
    ON silver.meter_readings (reading_date, feeder_id);

CREATE TABLE IF NOT EXISTS silver.quarantine (
    quarantine_id   BIGSERIAL     NOT NULL,
    reading_date    DATE          NOT NULL,
    meter_id        TEXT,
    reading_ts      TIMESTAMPTZ,
    reason_code     TEXT          NOT NULL CHECK (reason_code IN ({_REASON_LIST})),
    detail          TEXT,
    raw_row         JSONB         NOT NULL,
    bronze_event_id BIGINT,
    source_file     TEXT,
    run_id          TEXT          NOT NULL,
    PRIMARY KEY (quarantine_id, reading_date)
) PARTITION BY RANGE (reading_date);
CREATE INDEX IF NOT EXISTS ix_quarantine_date_reason
    ON silver.quarantine (reading_date, reason_code);

CREATE TABLE IF NOT EXISTS silver.gaps (
    meter_id          TEXT        NOT NULL,
    interval_start    TIMESTAMPTZ NOT NULL,   -- first missing slot
    interval_end      TIMESTAMPTZ NOT NULL,   -- exclusive: start of next present slot
    missing_intervals INTEGER     NOT NULL,
    reading_date      DATE        NOT NULL,
    feeder_id         TEXT,
    zone_id           TEXT,
    run_id            TEXT        NOT NULL,
    PRIMARY KEY (meter_id, interval_start, reading_date)
) PARTITION BY RANGE (reading_date);
CREATE INDEX IF NOT EXISTS ix_gaps_date ON silver.gaps (reading_date);
"""


SILVER_TABLES = ("silver.meter_readings", "silver.quarantine", "silver.gaps")


def create_silver_schema(conn: psycopg.Connection) -> None:
    moved = detach_legacy(conn, SILVER_TABLES)
    with conn.cursor() as cur:
        cur.execute(DDL)
    restore_legacy(conn, moved)
    conn.commit()
