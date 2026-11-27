-- GridPulse warehouse schema bootstrap (idempotent).
-- Creates the medallion + reference + observability schemas used across the
-- telemetry contract in CLAUDE.md §3. Safe to run on every `make up`.
CREATE SCHEMA IF NOT EXISTS bronze;   -- raw meter events + load metadata
CREATE SCHEMA IF NOT EXISTS silver;   -- normalised readings, quarantine, gaps
CREATE SCHEMA IF NOT EXISTS gold;     -- consumption, billing, anomalies
CREATE SCHEMA IF NOT EXISTS mart;     -- business-facing aggregates
CREATE SCHEMA IF NOT EXISTS obs;      -- run_log, metrics (observability)
CREATE SCHEMA IF NOT EXISTS ref;      -- dim_meter, dim_feeder, dim_zone, dim_date

-- Report what exists so `make up` output is self-verifying.
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN ('bronze','silver','gold','mart','obs','ref')
ORDER BY schema_name;
