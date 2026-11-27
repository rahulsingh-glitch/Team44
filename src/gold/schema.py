"""Gold DDL — consumption + billing (CLAUDE.md §3).

Meter-grain tables are the source of truth; feeder/zone roll-ups are VIEWS over
them so the three levels can never drift apart. Idempotent: safe on every run.
All energy is kWh (taken from silver.energy_kwh as-is — never re-converted).
"""

from __future__ import annotations

import psycopg

from src.storage.partitions import detach_legacy, restore_legacy

INTERVALS_PER_DAY = 96  # 15-min readings (CLAUDE.md §4 TIME RULE)
COMPLETE_PCT = 90  # CLAUDE.md §5: completeness per meter per day > 90%

BILLING_STATUSES = ("BILLABLE", "LOW_COMPLETENESS", "OPEN_MONTH")
_STATUS_LIST = ", ".join(f"'{s}'" for s in BILLING_STATUSES)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS gold;

-- one row per meter per UTC hour that has >=1 accepted reading
CREATE TABLE IF NOT EXISTS gold.consumption_hourly (
    meter_id          TEXT          NOT NULL,
    hour_ts           TIMESTAMPTZ   NOT NULL,   -- UTC hour start
    reading_date      DATE          NOT NULL,   -- UTC date of hour_ts
    feeder_id         TEXT          NOT NULL,
    zone_id           TEXT          NOT NULL,
    energy_kwh        NUMERIC(16,6) NOT NULL,
    intervals_present SMALLINT      NOT NULL CHECK (intervals_present BETWEEN 1 AND 4),
    run_id            TEXT          NOT NULL,
    PRIMARY KEY (meter_id, hour_ts, reading_date)
) PARTITION BY RANGE (reading_date);   -- monthly partitions (ADR-0002)
CREATE INDEX IF NOT EXISTS ix_cons_hourly_date_zone
    ON gold.consumption_hourly (reading_date, zone_id);
CREATE INDEX IF NOT EXISTS ix_cons_hourly_date_feeder
    ON gold.consumption_hourly (reading_date, feeder_id);

-- one row per installed meter per UTC date; energy_kwh NULL = no readings at
-- all (an outage must never look like 0 kWh consumption). Gaps are NOT filled.
CREATE TABLE IF NOT EXISTS gold.consumption_daily (
    meter_id           TEXT          NOT NULL,
    reading_date       DATE          NOT NULL,
    feeder_id          TEXT          NOT NULL,
    zone_id            TEXT          NOT NULL,
    energy_kwh         NUMERIC(16,6),
    intervals_present  SMALLINT      NOT NULL,
    intervals_expected SMALLINT      NOT NULL DEFAULT {INTERVALS_PER_DAY},
    completeness_pct   NUMERIC(5,2)  NOT NULL,
    is_complete        BOOLEAN       NOT NULL,   -- completeness_pct > {COMPLETE_PCT}
    run_id             TEXT          NOT NULL,
    PRIMARY KEY (meter_id, reading_date)
) PARTITION BY RANGE (reading_date);   -- monthly partitions (ADR-0002)
CREATE INDEX IF NOT EXISTS ix_cons_daily_date_zone
    ON gold.consumption_daily (reading_date, zone_id);
CREATE INDEX IF NOT EXISTS ix_cons_daily_date_feeder
    ON gold.consumption_daily (reading_date, feeder_id);

-- one row per meter per calendar month, billing-ready kWh (measured only)
CREATE TABLE IF NOT EXISTS gold.billing_monthly (
    meter_id           TEXT          NOT NULL,
    billing_month      DATE          NOT NULL,   -- first day of month
    feeder_id          TEXT          NOT NULL,
    zone_id            TEXT          NOT NULL,
    energy_kwh         NUMERIC(18,6) NOT NULL,
    days_with_data     SMALLINT      NOT NULL,
    days_processed     SMALLINT      NOT NULL,
    days_in_month      SMALLINT      NOT NULL,
    intervals_present  INTEGER       NOT NULL,
    intervals_expected INTEGER       NOT NULL,   -- days_in_month * {INTERVALS_PER_DAY}
    completeness_pct   NUMERIC(5,2)  NOT NULL,   -- vs processed days
    billing_status     TEXT          NOT NULL CHECK (billing_status IN ({_STATUS_LIST})),
    run_id             TEXT          NOT NULL,
    PRIMARY KEY (meter_id, billing_month)
);
CREATE INDEX IF NOT EXISTS ix_billing_month_zone
    ON gold.billing_monthly (billing_month, zone_id);

CREATE OR REPLACE VIEW gold.consumption_hourly_feeder AS
SELECT hour_ts, reading_date, feeder_id, zone_id,
       sum(energy_kwh) AS energy_kwh,
       count(*) AS meters_reporting,
       sum(intervals_present) AS intervals_present
FROM gold.consumption_hourly
GROUP BY hour_ts, reading_date, feeder_id, zone_id;

CREATE OR REPLACE VIEW gold.consumption_hourly_zone AS
SELECT hour_ts, reading_date, zone_id,
       sum(energy_kwh) AS energy_kwh,
       count(*) AS meters_reporting,
       sum(intervals_present) AS intervals_present
FROM gold.consumption_hourly
GROUP BY hour_ts, reading_date, zone_id;

CREATE OR REPLACE VIEW gold.consumption_daily_feeder AS
SELECT reading_date, feeder_id, zone_id,
       sum(energy_kwh) AS energy_kwh,
       count(*) AS meters,
       count(*) FILTER (WHERE is_complete) AS meters_complete,
       round(100.0 * sum(intervals_present) / sum(intervals_expected), 2)
           AS completeness_pct
FROM gold.consumption_daily
GROUP BY reading_date, feeder_id, zone_id;

CREATE OR REPLACE VIEW gold.consumption_daily_zone AS
SELECT reading_date, zone_id,
       sum(energy_kwh) AS energy_kwh,
       count(*) AS meters,
       count(*) FILTER (WHERE is_complete) AS meters_complete,
       round(100.0 * sum(intervals_present) / sum(intervals_expected), 2)
           AS completeness_pct
FROM gold.consumption_daily
GROUP BY reading_date, zone_id;
"""


GOLD_PARTITIONED = ("gold.consumption_hourly", "gold.consumption_daily")


def create_gold_schema(conn: psycopg.Connection) -> None:
    moved = detach_legacy(conn, GOLD_PARTITIONED)
    with conn.cursor() as cur:
        cur.execute(DDL)
    restore_legacy(conn, moved)
    conn.commit()
