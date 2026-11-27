# ADR-0002: partitioning-retention
## Status
Accepted (hackathon) — implemented in `src/storage/` (2026-11-27).

## Context
At target scale (5000 meters × 96 readings) we land ~480k events/day: ~43M bronze
rows and ~43M silver rows over 90 days, growing forever. Every pipeline step is
**per UTC date** (build D, re-run D, backfill D1..D2), and dashboards filter by
date + zone/feeder. Retention is a requirement: raw 30 days, hourly 13 months.
Deleting expired rows with `DELETE` on one big table is slow, bloats the heap and
needs VACUUM FULL to give space back. We run on plain PostgreSQL 18 (no extensions).

## Decision
Native Postgres **RANGE partitioning**, one partition per unit of work:

| Table | Key | Grain | Retention |
|---|---|---|---|
| `bronze.meter_events_raw` | `source_date` | daily + `DEFAULT` (NULL dates) | 30 days |
| `silver.meter_readings`, `silver.quarantine`, `silver.gaps`, `silver.dq_flags` | `reading_date` | daily | 13 months |
| `gold.consumption_hourly` | `reading_date` | monthly | 13 months |
| `gold.consumption_daily` | `reading_date` | monthly | kept (small) |
| `bronze.load_log`, `gold.billing_monthly`, `gold.anomaly`, `ref.*` | — | not partitioned | kept (tiny) |

- **Indexed by zone**: `(reading_date, zone_id)` and `(reading_date, feeder_id)` are
  declared on the parent and propagate to every partition.
- **Partition creation**: writers call `ensure_partition()` before inserting
  (idempotent), so no pre-created calendar and no DEFAULT partition is needed for
  silver/gold (a DEFAULT would block creating a later partition for the same range).
- **Compaction**: every `make run` / `make backfill` ends with `VACUUM (ANALYZE, TRUNCATE false)` on
  the partitions it touched (SHARE UPDATE EXCLUSIVE only; TRUNCATE false so it never asks for the exclusive lock tail-truncation needs — readers unaffected).
  `REINDEX TABLE CONCURRENTLY` runs only in the scheduled `make compact DATE_FROM=
  DATE_TO=`. All maintenance sets `lock_timeout=5s`: a busy partition is skipped and
  reported, never blocks the pipeline. (Found in build: a plain per-run `REINDEX`
  needs ACCESS EXCLUSIVE and hung behind an idle-in-transaction reader — the same
  would happen behind a Superset query.)
- **Retention**: `make retention [AS_OF=] [DRY_RUN=1]` drops whole partitions whose
  upper bound is ≤ `as_of − window` (bounds read from the catalog, not names).
  Not part of `make run`; scheduled as its own Airflow task.
  `as_of` defaults to the **data clock** (`max(silver.reading_date)`) so synthetic
  2025 data is not wiped by wall-clock 2026; production passes `--as-of` today.
- **Migration**: each layer's `create_*_schema()` detects a pre-partitioning plain
  table, renames it `_legacy`, creates the partitioned table, copies rows, carries
  serial sequences forward and drops the legacy — one transaction, idempotent.

## Options considered
- **A. One big table + `DELETE` for retention** — simplest; deletes are slow, bloat
  the heap, and re-running a date scans the whole table. Rejected.
- **B. Monthly partitions everywhere** — fewer partitions; but a re-run/backfill of
  one day rewrites inside a month-sized partition and raw 30-day retention would
  keep up to ~60 days. Used only for gold (small, 13-month horizon).
- **C. TimescaleDB hypertables** — automatic chunks + retention policies; adds an
  extension to install/operate in the 5-hour window. Rejected for scope.
- **D. Native daily (bronze/silver) + monthly (gold) RANGE partitions** — chosen.

## Consequences
- Partition keys must be in every PK: silver/gaps/hourly PKs gained `reading_date`
  (derived from the timestamp, so uniqueness is unchanged); quarantine PK is
  `(quarantine_id, reading_date)`. **Bronze has no PK** (`source_date` may be NULL);
  `event_id` stays unique via its sequence and has a plain index.
- Date-filtered queries prune to one partition (verified with EXPLAIN:
  `reading_date = D` scans only `meter_readings_pYYYYMMDD`; gold month range scans
  only `consumption_hourly_pYYYYMM`).
- Retention is an O(1) `DROP TABLE` per partition, no bloat, no VACUUM FULL.
- **After 30 days bronze is gone**: silver for that date can no longer be rebuilt
  from raw; gold/anomaly backfills still work from silver (kept 13 months).
- Monthly gold partitions are dropped only when the whole month is past the cutoff,
  so hourly may be kept up to ~1 month longer than 13 months.
- Silver's bronze candidate query (`OR left(raw->>'ts',10) = D` for late files)
  cannot prune and touches every bronze partition via the per-partition
  expression index — bounded by the 30-day retention.
