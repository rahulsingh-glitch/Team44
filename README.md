# manthan-w2-b-team44 — OmniRetail Lakehouse (Track B)

Daily sales **medallion pipeline**: raw landing → bronze → silver → gold star schema
→ marts → dashboard, with data quality and observability built in.

> Rehearsal repo for AI Manthan Wave 2 (27 Nov). On the day, clone the starter
> template provided at kick-off and port these patterns into it. Do **not** bring
> pre-built solution code for the revealed card into the room — this skeleton is a
> structure/pattern template; confirm with a mentor if unsure.

## Quick start (one command)

```bash
make up        # start Postgres + Airflow (or the DuckDB-only path), create schemas
make seed      # generate synthetic data into data/landing/
make run       # run the pipeline end to end for one day
make test      # run the full test suite
```

Then open:
- Dashboard: http://localhost:8088 (Superset) or http://localhost:8501 (Streamlit)
- Airflow:  http://localhost:8080
- Health page: http://localhost:8000/health

## Architecture

```
sources ──▶ bronze (land + metadata) ──▶ silver (typed, dedup, quarantine)
            ──▶ gold (fact + SCD2 dims) ──▶ marts ──▶ dashboard
                                      observability: run_log, metrics, DQ scorecard, alert
```

See `docs/lld.md` for the full design and `docs/ideation.md` for the problem framing
and trade-offs.

## Repository layout

| Path | What lives here |
|---|---|
| `src/ingestion` | Read source files, compute checksums |
| `src/bronze` | Land files untouched + load metadata |
| `src/silver` | Typing, dedup, standardise, quarantine |
| `src/gold` | Star schema, SCD2 dimensions, facts |
| `src/marts` | Business aggregates |
| `src/dq` | Data-quality checks + scorecard |
| `src/observability` | run_log/metrics tables, health page, alert |
| `dbt/` | dbt project (models, snapshots for SCD2, tests) |
| `deploy/` | docker-compose, Dockerfile, Makefile, CI |
| `docs/` | LLD, ideation, runbook, test plan, Claude log |
| `tests/` | One test per must-have; `test_<rule>_<result>` |

## Standards

See `CLAUDE.md`. Formatter + linter must pass before every commit.

## Team 44

Rahul Singh (lead) · Jitesh Binnar · Adarsh Kumar Singh · Mohammad Nabi Hasan · Chetan Pal
