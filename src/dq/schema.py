"""DQ DDL — obs.dq_results (per check per date) + silver.dq_flags (§5 quality
flag per meter-day). Idempotent. silver.dq_flags is RANGE-partitioned daily
like the rest of silver (ADR-0002)."""

from __future__ import annotations

import psycopg

CHECK_STATUSES = ("PASS", "WARN", "FAIL")
_STATUS_LIST = ", ".join(f"'{s}'" for s in CHECK_STATUSES)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS obs;
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS obs.dq_results (
    check_date    DATE         NOT NULL,
    check_name    TEXT         NOT NULL,
    rows_checked  BIGINT       NOT NULL,
    rows_failed   BIGINT       NOT NULL,   -- caught by the rule (quarantined / flagged)
    pass_rate     NUMERIC(9,6) NOT NULL,
    threshold     NUMERIC(9,6) NOT NULL,
    status        TEXT         NOT NULL CHECK (status IN ({_STATUS_LIST})),
    invariant_ok  BOOLEAN,                 -- NULL = check has no silver invariant
    detail        JSONB        NOT NULL,
    run_id        TEXT         NOT NULL,
    recorded_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (check_date, check_name)
);

CREATE TABLE IF NOT EXISTS silver.dq_flags (
    meter_id          TEXT         NOT NULL,
    reading_date      DATE         NOT NULL,
    flag_code         TEXT         NOT NULL CHECK (flag_code IN ('LOW_COMPLETENESS')),
    feeder_id         TEXT         NOT NULL,
    zone_id           TEXT         NOT NULL,
    intervals_present SMALLINT     NOT NULL,
    completeness_pct  NUMERIC(5,2) NOT NULL,
    run_id            TEXT         NOT NULL,
    PRIMARY KEY (meter_id, reading_date, flag_code)
) PARTITION BY RANGE (reading_date);
CREATE INDEX IF NOT EXISTS ix_dq_flags_date_zone
    ON silver.dq_flags (reading_date, zone_id);
"""


def create_dq_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
