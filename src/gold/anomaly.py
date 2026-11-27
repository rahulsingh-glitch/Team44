"""Gold anomaly detection -> gold.anomaly (CLAUDE.md §6).

Three checks, each run for one UTC detection date D:

- SPIKE  : a reading on D whose z-score vs the SAME meter's readings over the
           7 days up to D (leave-one-out: the reading is excluded from its own
           mean/stddev) exceeds SPIKE_Z.
- TAMPER : a meter reporting (>= TAMPER_MIN_PRESENT of slots present) exactly
           0 kWh across the 48h window D-1..D while >= NEIGHBOUR_NORMAL_FRAC of
           the other meters on its feeder consumed > 0. Missing slots are NOT
           zeros — absence is a gap/outage, not tamper.
- OUTAGE : 15-min slots on D where >= OUTAGE_MIN_FRAC and >= OUTAGE_MIN_METERS
           of a feeder's installed meters have no reading; consecutive slots
           are merged into one window (gaps-and-islands).

IDEMPOTENT per date: build_anomaly_date(D) deletes rows with detected_date = D
and re-inserts in ONE transaction. Run AFTER gold for every date (TAMPER reads
gold.consumption_daily for D-1). A multi-day tamper yields one row per day as
its 48h window slides — by design.
"""

from __future__ import annotations

import datetime as dt

import psycopg

from src.gold.schema import INTERVALS_PER_DAY

SPIKE_Z = 4.0
SPIKE_HISTORY_DAYS = 7  # D-6 .. D inclusive
SPIKE_MIN_HISTORY = 96  # need >= one day of other readings

TAMPER_DAYS = 2  # 48h
TAMPER_MIN_PRESENT = 0.9
NEIGHBOUR_NORMAL_FRAC = 0.8

OUTAGE_MIN_FRAC = 0.5
OUTAGE_MIN_METERS = 3

ANOMALY_TYPES = ("SPIKE", "TAMPER", "OUTAGE")
_TYPE_LIST = ", ".join(f"'{t}'" for t in ANOMALY_TYPES)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS gold;
CREATE TABLE IF NOT EXISTS gold.anomaly (
    anomaly_type   TEXT        NOT NULL CHECK (anomaly_type IN ({_TYPE_LIST})),
    subject_id     TEXT        NOT NULL,   -- meter_id, or feeder_id for OUTAGE
    meter_id       TEXT,                   -- NULL for OUTAGE (feeder-level)
    feeder_id      TEXT        NOT NULL,
    zone_id        TEXT        NOT NULL,
    window_start   TIMESTAMPTZ NOT NULL,   -- UTC
    window_end     TIMESTAMPTZ NOT NULL,   -- UTC, exclusive
    detected_date  DATE        NOT NULL,
    score          NUMERIC(12,4) NOT NULL,
    evidence       JSONB       NOT NULL,
    run_id         TEXT        NOT NULL,
    PRIMARY KEY (anomaly_type, subject_id, window_start)
);
CREATE INDEX IF NOT EXISTS ix_anomaly_date_feeder
    ON gold.anomaly (detected_date, feeder_id);
CREATE INDEX IF NOT EXISTS ix_anomaly_type_date
    ON gold.anomaly (anomaly_type, detected_date);
"""

# Leave-one-out z-score from per-meter window aggregates (n, sum, sum of squares).
SPIKE_SQL = f"""
INSERT INTO gold.anomaly
    (anomaly_type, subject_id, meter_id, feeder_id, zone_id, window_start,
     window_end, detected_date, score, evidence, run_id)
WITH hist AS (
    SELECT meter_id,
           count(*) AS n,
           sum(energy_kwh::float8) AS s,
           sum(energy_kwh::float8 * energy_kwh::float8) AS q
    FROM silver.meter_readings
    WHERE reading_date BETWEEN %(d)s::date - {SPIKE_HISTORY_DAYS - 1} AND %(d)s
    GROUP BY meter_id
), loo AS (
    SELECT r.meter_id, r.feeder_id, r.zone_id, r.reading_ts,
           r.energy_kwh::float8 AS x,
           h.n - 1 AS n1,
           (h.s - r.energy_kwh::float8) / (h.n - 1) AS mean,
           h.q - r.energy_kwh::float8 * r.energy_kwh::float8 AS q1
    FROM silver.meter_readings r
    JOIN hist h USING (meter_id)
    WHERE r.reading_date = %(d)s AND h.n - 1 >= {SPIKE_MIN_HISTORY}
), z AS (
    SELECT *,
           sqrt(greatest((q1 - n1 * mean * mean) / (n1 - 1), 0)) AS sd
    FROM loo
)
SELECT 'SPIKE', meter_id, meter_id, feeder_id, zone_id,
       reading_ts, reading_ts + interval '15 minutes', %(d)s::date,
       round(((x - mean) / sd)::numeric, 4),
       jsonb_build_object(
           'energy_kwh', round(x::numeric, 6),
           'history_mean_kwh', round(mean::numeric, 6),
           'history_stddev_kwh', round(sd::numeric, 6),
           'history_n', n1,
           'z_threshold', {SPIKE_Z}),
       %(run_id)s
FROM z
WHERE sd > 1e-9 AND (x - mean) / sd > {SPIKE_Z}
"""

TAMPER_SQL = f"""
INSERT INTO gold.anomaly
    (anomaly_type, subject_id, meter_id, feeder_id, zone_id, window_start,
     window_end, detected_date, score, evidence, run_id)
WITH w AS (
    SELECT meter_id, max(feeder_id) AS feeder_id, max(zone_id) AS zone_id,
           count(*) AS days,
           sum(intervals_present) AS present,
           coalesce(sum(energy_kwh), 0) AS kwh
    FROM gold.consumption_daily
    WHERE reading_date BETWEEN %(d)s::date - {TAMPER_DAYS - 1} AND %(d)s
    GROUP BY meter_id
), suspect AS (
    SELECT * FROM w
    WHERE days = {TAMPER_DAYS}
      AND kwh = 0
      AND present >= {TAMPER_MIN_PRESENT} * {TAMPER_DAYS * INTERVALS_PER_DAY}
), nb AS (
    SELECT s.meter_id,
           count(o.meter_id) AS neighbours,
           count(o.meter_id) FILTER (WHERE o.kwh > 0) AS neighbours_normal,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY o.kwh) AS neighbour_median_kwh
    FROM suspect s
    JOIN w o ON o.feeder_id = s.feeder_id AND o.meter_id <> s.meter_id
    GROUP BY s.meter_id
)
SELECT 'TAMPER', s.meter_id, s.meter_id, s.feeder_id, s.zone_id,
       (%(d)s::date - {TAMPER_DAYS - 1})::timestamp AT TIME ZONE 'UTC',
       (%(d)s::date + 1)::timestamp AT TIME ZONE 'UTC',
       %(d)s::date,
       round(nb.neighbours_normal::numeric / nb.neighbours, 4),
       jsonb_build_object(
           'window_hours', {TAMPER_DAYS * 24},
           'intervals_present', s.present,
           'intervals_expected', {TAMPER_DAYS * INTERVALS_PER_DAY},
           'meter_kwh', 0,
           'neighbours', nb.neighbours,
           'neighbours_normal', nb.neighbours_normal,
           'neighbour_median_kwh', round(nb.neighbour_median_kwh::numeric, 6)),
       %(run_id)s
FROM suspect s JOIN nb USING (meter_id)
WHERE nb.neighbours > 0
  AND nb.neighbours_normal::numeric / nb.neighbours >= {NEIGHBOUR_NORMAL_FRAC}
"""

OUTAGE_SQL = f"""
INSERT INTO gold.anomaly
    (anomaly_type, subject_id, meter_id, feeder_id, zone_id, window_start,
     window_end, detected_date, score, evidence, run_id)
WITH fm AS (
    SELECT feeder_id, max(zone_id) AS zone_id, count(*) AS meters
    FROM ref.dim_meter
    WHERE install_date IS NULL OR install_date <= %(d)s
    GROUP BY feeder_id
), slots AS (
    SELECT generate_series(
        %(d)s::date::timestamp AT TIME ZONE 'UTC',
        (%(d)s::date + 1)::timestamp AT TIME ZONE 'UTC' - interval '15 minutes',
        interval '15 minutes') AS slot_ts
), present AS (
    SELECT r.feeder_id, r.reading_ts AS slot_ts, count(*) AS n
    FROM silver.meter_readings r
    JOIN ref.dim_meter m USING (meter_id)
    WHERE r.reading_date = %(d)s
      AND (m.install_date IS NULL OR m.install_date <= %(d)s)
    GROUP BY r.feeder_id, r.reading_ts
), miss AS (
    SELECT fm.feeder_id, fm.zone_id, fm.meters, s.slot_ts,
           fm.meters - coalesce(p.n, 0) AS missing
    FROM fm CROSS JOIN slots s
    LEFT JOIN present p ON p.feeder_id = fm.feeder_id AND p.slot_ts = s.slot_ts
), hit AS (
    SELECT *,
           slot_ts - row_number() OVER (PARTITION BY feeder_id ORDER BY slot_ts)
                     * interval '15 minutes' AS grp
    FROM miss
    WHERE missing >= {OUTAGE_MIN_METERS}
      AND missing::numeric / meters >= {OUTAGE_MIN_FRAC}
)
SELECT 'OUTAGE', feeder_id, NULL, feeder_id, max(zone_id),
       min(slot_ts), max(slot_ts) + interval '15 minutes', %(d)s::date,
       round(max(missing::numeric / meters), 4),
       jsonb_build_object(
           'meters_on_feeder', max(meters),
           'max_meters_missing', max(missing),
           'min_meters_missing', min(missing),
           'slots', count(*),
           'min_fraction_threshold', {OUTAGE_MIN_FRAC},
           'min_meters_threshold', {OUTAGE_MIN_METERS}),
       %(run_id)s
FROM hit
GROUP BY feeder_id, grp
"""


def create_anomaly_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def build_anomaly_date(
    conn: psycopg.Connection, day: dt.date | str, run_id: str
) -> dict:
    """Recompute gold.anomaly for one detection date. Returns counts per type."""
    day = dt.date.fromisoformat(day) if isinstance(day, str) else day
    create_anomaly_schema(conn)
    params = {"d": day, "run_id": run_id}
    counts: dict[str, int] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gold.anomaly WHERE detected_date = %s", (day,))
            for kind, stmt in (
                ("SPIKE", SPIKE_SQL),
                ("TAMPER", TAMPER_SQL),
                ("OUTAGE", OUTAGE_SQL),
            ):
                cur.execute(stmt, params)
                counts[kind] = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"run_id": run_id, "date": day.isoformat(), **counts}
