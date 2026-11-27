# GridPulse — Team 44 build plan (files-only, no Kafka)

## Decisions locked
- Transport: file-based JSON landing only. No Kafka.
- Engine: dbt + Postgres 18 (already up). Dashboard: Superset. Orchestration: Airflow 3.3.
- Storage: Postgres RANGE partition by reading_date, indexed by zone; retention raw 30d / hourly 13mo.
- Gaps marked, never filled. All energy kWh. All time UTC.

## Roles (owners per layer; everyone reviews a teammate's output)
- Rahul (lead): architecture, ADRs, decisions, reviews/merges, clock, presentation.
- Jitesh: synthetic data, bronze, silver/normalisation (units, dedup, order, gaps).
- Adarsh: consumption (hourly/daily/billing), storage partitioning + retention.
- Chetan: anomaly checks, data quality, Superset dashboard, Claude-usage evidence.
- Nabi: observability + alert, Airflow DAG, CI, runbook; leads SRE drill.

## Build order (each: /build-layer X -> /test-feature X -> /ship)
1 synthetic data · 2 bronze · 3 silver normalisation · 4 consumption · 5 anomalies
· 6 data quality · 7 storage layout · 8 observability+alert · 9 airflow dag · 10 dashboard

## Tests that matter most (crafted data)
- test_wh_converted_to_kwh / test_kwh_meter_not_double_converted
- test_duplicate_reading_is_deduped / test_out_of_order_events_are_ordered
- test_missing_interval_recorded_as_gap_not_filled
- test_register_decrease_without_rollover_is_quarantined
- test_rerun_is_idempotent
- test_spike_flags / test_tamper_flags_48h_zero / test_outage_flags_feeder
- test_completeness_below_90_sets_quality_flag

## ADRs to write (docs/adr/)
- ADR-0001 late data handling (backfill, gaps not filled)
- ADR-0002 partitioning + compaction + retention (why date+zone)
- ADR-0003 schema evolution (v1/v2, unit handling)

## Dashboard tabs (Superset, 5 pts — keep clean)
feeder consumption · anomaly list · completeness % per zone · pipeline-health

## Demo (5 beats): problem (1 line) -> architecture + partitioning decision -> live happy path
(run DAG, show consumption + dashboard) -> a defect handled (gap / dedup / tamper flag) -> metrics + drill + RCA
