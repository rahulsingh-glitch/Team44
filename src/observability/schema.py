"""obs DDL — run_log, metrics, alert (CLAUDE.md §3). Idempotent."""

from __future__ import annotations

import psycopg

DDL = """
CREATE SCHEMA IF NOT EXISTS obs;

-- one row per stage per run (stage 'pipeline' = the whole run)
CREATE TABLE IF NOT EXISTS obs.run_log (
    log_id       BIGSERIAL PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    stage        TEXT        NOT NULL,
    metric_date  DATE,                     -- NULL for run-wide stages
    status       TEXT        NOT NULL CHECK (status IN ('running','success','failed')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at     TIMESTAMPTZ,
    duration_s   NUMERIC(12,3),
    rows_out     BIGINT,
    detail       JSONB,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_log_run ON obs.run_log (run_id);
CREATE INDEX IF NOT EXISTS ix_run_log_stage_started ON obs.run_log (stage, started_at DESC);

-- long format: one row per (date, metric, scope); a re-run replaces the date
CREATE TABLE IF NOT EXISTS obs.metrics (
    metric_date  DATE        NOT NULL,
    metric_name  TEXT        NOT NULL,
    scope        TEXT        NOT NULL,     -- 'ALL' or a zone_id
    value        NUMERIC(18,4),
    run_id       TEXT        NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (metric_date, metric_name, scope)
);
CREATE INDEX IF NOT EXISTS ix_metrics_name_date ON obs.metrics (metric_name, metric_date);

-- alert history; a re-run of a date replaces that date's alerts
CREATE TABLE IF NOT EXISTS obs.alert (
    alert_id     BIGSERIAL PRIMARY KEY,
    alert_name   TEXT        NOT NULL,
    metric_date  DATE        NOT NULL,
    scope        TEXT        NOT NULL,
    value        NUMERIC(18,4),
    baseline     NUMERIC(18,4),
    threshold    JSONB       NOT NULL,
    evidence     JSONB       NOT NULL,
    message      TEXT        NOT NULL,
    run_id       TEXT        NOT NULL,
    fired_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (alert_name, metric_date, scope)
);
"""


def create_obs_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
