# CLAUDE.md — Team 44 · AI Manthan Wave 2 · Track B · GridPulse

> Read automatically by Claude Code each session. Also a SCORED artifact (Claude usage, 15).

## 1. What we are building
GridPulse — a smart-meter telemetry platform. Ingest meter readings (two schema versions),
normalise them (units → kWh, dedupe, order, mark gaps), produce billing-ready consumption,
and flag anomalies. Consumers: billing analyst, network ops engineer, revenue-protection.

## 2. Key decisions (locked — reasons in the ADRs under docs/adr/)
1. **Transport = file-based JSON landing ONLY. No Kafka.** The card allows files or Kafka;
   we choose files for reliability in the 5-hour window. Events land as JSON files in
   data/landing/; a file-based log with offsets stands in for streaming if needed. ADR-0001.
2. **Engine = dbt + PostgreSQL 18** (already running; dbt-postgres 1.9 installed).
3. **Storage = Postgres native RANGE partitioning by reading_date, indexed by zone**;
   compaction = daily partition + scheduled VACUUM/reindex; retention raw 30d, hourly 13mo
   via partition-drop job. ADR-0002.
4. **Late data** handled by backfill for a date range; gaps are MARKED, never silently filled. ADR-0003.

## 3. The telemetry medallion + contract (fixed names — everyone codes to these)
Warehouse: PostgreSQL 18. Orchestration: Airflow 3.3. Dashboard: Superset.

- `bronze.meter_events_raw` — raw JSON preserved, + `schema_version` (1|2), + load metadata
- `bronze.load_log` — run_id, source_file, load_time, row_count, checksum
- `silver.meter_readings` — normalised: energy_kwh, reading_ts (UTC), meter_id, feeder_id,
  zone_id, status, voltage(nullable), firmware(nullable), is_duplicate=false, ordered
- `silver.quarantine` — raw_row(json), reason_code, run_id
- `silver.gaps` — meter_id, interval_start, interval_end (MISSING intervals, not filled)
- `gold.consumption_hourly` / `gold.consumption_daily` — kWh per meter, per feeder, per zone
- `gold.billing_monthly` — per meter, billing-ready kWh
- `gold.anomaly` — anomaly_type (SPIKE|TAMPER|OUTAGE), meter_id/feeder_id, window, evidence
- `ref.dim_meter` (master), `ref.dim_feeder`, `ref.dim_zone`, `ref.dim_date`
- `obs.run_log`, `obs.metrics` (ingest_lag, completeness_pct, duplicate_rate, run_duration)

Reason codes (closed): UNKNOWN_METER, NEGATIVE_ENERGY, REGISTER_DECREASE_NO_ROLLOVER,
UNPARSEABLE, BAD_SCHEMA, DUPLICATE.

## 4. Rules for Claude
- Plan first; approve before code. One layer per session.
- UNIT RULE: all energy stored in kWh. v1 energy is Wh (÷1000); some meters report kWh already
  — detect by a `unit` field or meter-master flag; NEVER double-convert.
- TIME RULE: all timestamps normalised to UTC; readings are 15-min intervals.
- GAPS: missing intervals are recorded in silver.gaps, never interpolated/filled.
- IDEMPOTENT: re-running a date replaces that date, identical output; duplicates skipped.
- Every must-have has a test. snake_case. No secrets, synthetic data only.

## 5. Data quality rules
- meter_id exists in ref.dim_meter, else quarantine (UNKNOWN_METER).
- energy not negative (NEGATIVE_ENERGY).
- cumulative register never decreases unless rollover flagged (REGISTER_DECREASE_NO_ROLLOVER).
- completeness per meter per day > 90%, else a quality flag on that day.

## 6. The three anomaly checks (gold.anomaly)
- SPIKE: z-score of a meter's interval kWh vs its own history > threshold (e.g. 4).
- TAMPER: zero consumption for 48h while neighbours on the same feeder are normal.
- OUTAGE: many meters on one feeder missing readings in the same window.

## 7. Defect → mechanism cheatsheet (expect these in the data)
| Defect | Mechanism |
|---|---|
| Schema v1 vs v2 | ingest both, record schema_version, v2 adds voltage/firmware |
| Wh vs kWh | unit conversion rule (§4), quarantine if ambiguous |
| Duplicates | dedupe on (meter_id, reading_ts) |
| Out-of-order events | order by reading_ts in silver |
| Missing intervals | silver.gaps, not filled |
| Register rollover | flag; a decrease without a flag → quarantine |

## 8. Standards
Repo manthan-w2-b-team44; protected main; feature/ branches; commits feat|fix|test|docs|ci|chore;
src/ tests/ docs/ deploy/; README+CLAUDE.md at root; test names state rule+result.

## 9. Commands
make up / make seed / make run / make test / make backfill DATE_FROM=.. DATE_TO=..
