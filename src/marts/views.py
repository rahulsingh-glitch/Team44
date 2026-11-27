"""mart.* — thin reporting views for the Superset dashboard.

The dashboard reads ONLY these views, so gold/obs tables can evolve without
breaking charts. Views (not tables): always current, nothing to refresh.
Idempotent: CREATE OR REPLACE. Run: python -m src.marts.views
"""

from __future__ import annotations

import psycopg

from src.common.db import connect
from src.dq.schema import create_dq_schema
from src.gold.anomaly import create_anomaly_schema
from src.gold.schema import create_gold_schema
from src.observability.schema import create_obs_schema

VIEWS: dict[str, str] = {
    # ---------------------------------------------------- feeder consumption
    "feeder_consumption_daily": """
        SELECT reading_date, feeder_id, zone_id,
               round(energy_kwh, 3) AS energy_kwh,
               meters, meters_complete, completeness_pct
        FROM gold.consumption_daily_feeder""",
    "feeder_consumption_hourly": """
        SELECT hour_ts, reading_date, feeder_id, zone_id,
               round(energy_kwh, 3) AS energy_kwh, meters_reporting
        FROM gold.consumption_hourly_feeder""",
    "billing_status": """
        SELECT billing_month, zone_id, billing_status,
               count(*) AS meters,
               round(sum(energy_kwh), 3) AS energy_kwh,
               round(avg(completeness_pct), 2) AS avg_completeness_pct
        FROM gold.billing_monthly
        GROUP BY billing_month, zone_id, billing_status""",
    # --------------------------------------------------------------- anomalies
    "anomaly_list": """
        SELECT a.detected_date, a.anomaly_type,
               coalesce(a.meter_id, '(feeder)') AS meter_id,
               a.feeder_id, a.zone_id, a.window_start, a.window_end,
               round(extract(epoch FROM a.window_end - a.window_start) / 3600, 2)
                   AS window_hours,
               a.score,
               CASE a.anomaly_type
                 WHEN 'SPIKE' THEN format('%s kWh vs mean %s (z=%s)',
                      a.evidence->>'energy_kwh', a.evidence->>'history_mean_kwh', a.score)
                 WHEN 'TAMPER' THEN format('0 kWh over %sh, %s/%s neighbours normal',
                      a.evidence->>'window_hours', a.evidence->>'neighbours_normal',
                      a.evidence->>'neighbours')
                 WHEN 'OUTAGE' THEN format('%s/%s meters missing for %s slots',
                      a.evidence->>'max_meters_missing', a.evidence->>'meters_on_feeder',
                      a.evidence->>'slots')
               END AS summary
        FROM gold.anomaly a""",
    # ----------------------------------------------------- data completeness
    "zone_completeness": """
        SELECT m.metric_date AS reading_date, m.scope AS zone_id,
               m.value AS completeness_pct,
               (SELECT count(*) FROM silver.dq_flags f
                 WHERE f.reading_date = m.metric_date
                   AND (m.scope = 'ALL' OR f.zone_id = m.scope)) AS meter_days_flagged
        FROM obs.metrics m
        WHERE m.metric_name = 'completeness_pct'""",
    "dq_scorecard": """
        SELECT check_date, check_name, status, pass_rate, threshold,
               rows_checked, rows_failed AS rows_caught, invariant_ok
        FROM obs.dq_results""",
    # ------------------------------------------------------- pipeline health
    "pipeline_runs": """
        SELECT run_id, stage, metric_date, status, started_at, ended_at,
               duration_s, rows_out, error
        FROM obs.run_log""",
    "pipeline_metrics": """
        SELECT metric_date,
               max(value) FILTER (WHERE metric_name = 'dq_pass_rate')     AS dq_pass_rate,
               max(value) FILTER (WHERE metric_name = 'completeness_pct') AS completeness_pct,
               max(value) FILTER (WHERE metric_name = 'duplicate_rate')   AS duplicate_rate,
               max(value) FILTER (WHERE metric_name = 'ingest_lag_s')     AS ingest_lag_s,
               max(value) FILTER (WHERE metric_name = 'run_duration_s')   AS run_duration_s,
               max(value) FILTER (WHERE metric_name = 'readings')         AS readings,
               max(value) FILTER (WHERE metric_name = 'quarantine_count') AS quarantined
        FROM obs.metrics
        WHERE scope = 'ALL'
        GROUP BY metric_date""",
    "alerts": """
        SELECT fired_at, metric_date, alert_name, scope AS zone_id,
               value AS completeness_pct, baseline AS baseline_pct,
               evidence->'worst_feeders'->0->>'feeder_id' AS worst_feeder,
               message
        FROM obs.alert""",
}


def create_mart_views(conn: psycopg.Connection) -> list[str]:
    # make sure every source exists (fresh DB before the first pipeline run)
    for create in (
        create_gold_schema,
        create_anomaly_schema,
        create_obs_schema,
        create_dq_schema,
    ):
        create(conn)
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS mart")
        for name, body in VIEWS.items():
            cur.execute(f"CREATE OR REPLACE VIEW mart.{name} AS {body}")
    conn.commit()
    return [f"mart.{n}" for n in VIEWS]


if __name__ == "__main__":
    with connect() as c:
        made = create_mart_views(c)
        for v in made:
            (n,) = c.execute(f"SELECT count(*) FROM {v}").fetchone()
            print(f"[mart] {v}: {n} rows")
