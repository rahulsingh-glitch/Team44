"""Gold consumption builder: silver.meter_readings -> gold.consumption_{hourly,daily}
and gold.billing_monthly.

IDEMPOTENT per UTC date: build_gold_date(D) deletes D's hourly/daily rows,
re-inserts them from silver, then rebuilds every billing_monthly row for D's
month from consumption_daily — all in ONE transaction. Same silver in -> same
rows out (only run_id differs). Missing intervals are counted, never filled;
quarantined slots carry no billable kWh.
"""

from __future__ import annotations

import datetime as dt

import psycopg

from src.gold.schema import COMPLETE_PCT, INTERVALS_PER_DAY, create_gold_schema
from src.storage.partitions import ensure_partition

HOURLY_SQL = """
INSERT INTO gold.consumption_hourly
    (meter_id, hour_ts, reading_date, feeder_id, zone_id,
     energy_kwh, intervals_present, run_id)
SELECT meter_id,
       date_trunc('hour', reading_ts, 'UTC') AS hour_ts,
       %(d)s::date,
       max(feeder_id), max(zone_id),
       sum(energy_kwh), count(*), %(run_id)s
FROM silver.meter_readings
WHERE reading_date = %(d)s
GROUP BY meter_id, date_trunc('hour', reading_ts, 'UTC')
"""

# Every meter installed by D gets a row, even with zero readings (energy NULL,
# 0% complete) so a full-day outage stays visible instead of reading as 0 kWh.
DAILY_SQL = f"""
INSERT INTO gold.consumption_daily
    (meter_id, reading_date, feeder_id, zone_id, energy_kwh, intervals_present,
     intervals_expected, completeness_pct, is_complete, run_id)
WITH r AS (
    SELECT meter_id, max(feeder_id) AS feeder_id, max(zone_id) AS zone_id,
           sum(energy_kwh) AS energy_kwh, count(*) AS n
    FROM silver.meter_readings
    WHERE reading_date = %(d)s
    GROUP BY meter_id
), m AS (
    SELECT meter_id, feeder_id, zone_id FROM ref.dim_meter
    WHERE install_date IS NULL OR install_date <= %(d)s
)
SELECT coalesce(r.meter_id, m.meter_id),
       %(d)s::date,
       coalesce(r.feeder_id, m.feeder_id),
       coalesce(r.zone_id, m.zone_id),
       r.energy_kwh,
       coalesce(r.n, 0),
       {INTERVALS_PER_DAY},
       round(100.0 * coalesce(r.n, 0) / {INTERVALS_PER_DAY}, 2),
       100.0 * coalesce(r.n, 0) / {INTERVALS_PER_DAY} > {COMPLETE_PCT},
       %(run_id)s
FROM r FULL OUTER JOIN m ON m.meter_id = r.meter_id
"""

# Rebuild the whole month from daily (cheap: <= 31 days). days_processed is
# GLOBAL (distinct dates built for the month) so a meter installed mid-month
# is not stuck OPEN_MONTH forever.
BILLING_SQL = f"""
INSERT INTO gold.billing_monthly
    (meter_id, billing_month, feeder_id, zone_id, energy_kwh, days_with_data,
     days_processed, days_in_month, intervals_present, intervals_expected,
     completeness_pct, billing_status, run_id)
WITH month AS (
    SELECT %(m)s::date AS m0,
           (%(m)s::date + interval '1 month')::date AS m1
), processed AS (
    SELECT count(DISTINCT reading_date) AS n
    FROM gold.consumption_daily, month
    WHERE reading_date >= m0 AND reading_date < m1
), agg AS (
    SELECT meter_id,
           max(feeder_id) AS feeder_id, max(zone_id) AS zone_id,
           coalesce(sum(energy_kwh), 0) AS energy_kwh,
           count(*) FILTER (WHERE intervals_present > 0) AS days_with_data,
           count(*) AS days_processed,
           sum(intervals_present) AS intervals_present,
           sum(intervals_expected) AS intervals_expected
    FROM gold.consumption_daily, month
    WHERE reading_date >= m0 AND reading_date < m1
    GROUP BY meter_id
)
SELECT a.meter_id, month.m0, a.feeder_id, a.zone_id, a.energy_kwh,
       a.days_with_data, a.days_processed, (month.m1 - month.m0),
       a.intervals_present, a.intervals_expected,
       round(100.0 * a.intervals_present / a.intervals_expected, 2),
       CASE
           WHEN p.n < (month.m1 - month.m0) THEN 'OPEN_MONTH'
           WHEN 100.0 * a.intervals_present / a.intervals_expected <= {COMPLETE_PCT}
               THEN 'LOW_COMPLETENESS'
           ELSE 'BILLABLE'
       END,
       %(run_id)s
FROM agg a, month, processed p
"""


def build_gold_date(conn: psycopg.Connection, day: dt.date | str, run_id: str) -> dict:
    """Rebuild gold consumption for one UTC date + its billing month."""
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    month = day.replace(day=1)
    create_gold_schema(conn)
    params = {"d": day, "m": month, "run_id": run_id}
    try:
        ensure_partition(conn, "gold.consumption_hourly", day)
        ensure_partition(conn, "gold.consumption_daily", day)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM gold.consumption_hourly WHERE reading_date = %s", (day,)
            )
            cur.execute(
                "DELETE FROM gold.consumption_daily WHERE reading_date = %s", (day,)
            )
            cur.execute(HOURLY_SQL, params)
            hourly = cur.rowcount
            cur.execute(DAILY_SQL, params)
            daily = cur.rowcount
            cur.execute(
                "DELETE FROM gold.billing_monthly WHERE billing_month = %s", (month,)
            )
            cur.execute(BILLING_SQL, params)
            billing = cur.rowcount
            cur.execute(
                """SELECT coalesce(sum(energy_kwh), 0),
                          count(*) FILTER (WHERE NOT is_complete)
                   FROM gold.consumption_daily WHERE reading_date = %s""",
                (day,),
            )
            kwh, incomplete = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "run_id": run_id,
        "date": day.isoformat(),
        "hourly": hourly,
        "daily": daily,
        "incomplete_meters": incomplete,
        "kwh": kwh,
        "billing_month": month.isoformat(),
        "billing_rows": billing,
    }
