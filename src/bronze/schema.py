"""Bronze DDL — raw landing tables (CLAUDE.md §3).

Idempotent: safe to call on every run. Bronze preserves the raw event payload
untouched and records only load metadata; no business validation happens here.
"""

from __future__ import annotations

import psycopg

from src.storage.partitions import detach_legacy, restore_legacy

DDL = """
CREATE SCHEMA IF NOT EXISTS bronze;

-- RANGE-partitioned daily by source_date (ADR-0002). No PK: a partitioned PK
-- must include source_date, which can be NULL (-> DEFAULT partition).
-- event_id stays unique via its sequence.
CREATE TABLE IF NOT EXISTS bronze.meter_events_raw (
    event_id       BIGSERIAL   NOT NULL,
    run_id         TEXT        NOT NULL,
    source_file    TEXT        NOT NULL,
    file_checksum  TEXT        NOT NULL,
    source_date    DATE,
    schema_version SMALLINT,
    raw            JSONB       NOT NULL,
    load_time      TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (source_date);
CREATE TABLE IF NOT EXISTS bronze.meter_events_raw_default
    PARTITION OF bronze.meter_events_raw DEFAULT;
CREATE INDEX IF NOT EXISTS ix_meter_events_raw_event_id
    ON bronze.meter_events_raw (event_id);
CREATE INDEX IF NOT EXISTS ix_meter_events_raw_checksum
    ON bronze.meter_events_raw (file_checksum);
CREATE INDEX IF NOT EXISTS ix_meter_events_raw_source_date
    ON bronze.meter_events_raw (source_date);

CREATE TABLE IF NOT EXISTS bronze.load_log (
    log_id         BIGSERIAL PRIMARY KEY,
    run_id         TEXT        NOT NULL,
    source_file    TEXT        NOT NULL,
    file_checksum  TEXT        NOT NULL,
    source_date    DATE,
    row_count      INTEGER     NOT NULL DEFAULT 0,
    status         TEXT        NOT NULL,     -- loaded | skipped_duplicate | unparseable
    reason         TEXT,
    load_time      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_load_log_checksum
    ON bronze.load_log (file_checksum);
"""


def create_bronze_schema(conn: psycopg.Connection) -> None:
    """Create bronze schema + tables if they do not exist."""
    moved = detach_legacy(conn, ["bronze.meter_events_raw"])
    with conn.cursor() as cur:
        cur.execute(DDL)
    restore_legacy(conn, moved)
    conn.commit()
