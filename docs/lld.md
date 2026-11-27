# Low-Level Design (LLD) — Team 44 · Track B

> Scored under **Engineering & data quality (15)** and **Business alignment (10)**.
> Fill the `<<...>>` markers on the day. Keep it to what you actually built.

## 1. Problem & scope

- **Problem statement:** `<<one line from the card>>`
- **Must-have scope (checklist):**
  1. `<<...>>`
  2. `<<...>>`
- **Out of scope / stretch:** `<<only once must-haves pass>>`

## 2. Context diagram

```
<<sources>> ──▶ Bronze ──▶ Silver ──▶ Gold (star) ──▶ Marts ──▶ Dashboard
                                   └─▶ Quarantine
         Observability: run_log, metrics, DQ scorecard, alert
         Orchestration: Airflow DAG (deps, retries, backfill)
```

## 3. Key decisions (with reasons — record at least two)

| # | Decision | Options considered | Why we chose it |
|---|---|---|---|
| 1 | Transform engine | dbt+DuckDB / dbt+Postgres / PySpark | `<<...>>` |
| 2 | Idempotency | checksum ledger / merge-on-key / truncate-reload | `<<...>>` |
| 3 | SCD strategy | SCD2 snapshot / overwrite | `<<...>>` |

## 4. Data model (gold star schema)

**Fact:** `fact_sales` — grain: one row per sale line.
Keys: `product_key`, `store_key`, `customer_key`, `date_key`. Measures: `quantity`,
`unit_price`, `amount`, `is_return`.

**Dimensions:**
- `dim_product` — **SCD2** (price/category change keeps history): `product_key` (surrogate),
  `product_id` (natural), `valid_from`, `valid_to`, `is_current`.
- `dim_store` — `<<SCD type>>`
- `dim_customer` — note PII handling (see security).
- `dim_date` — generated.

```
fact_sales ──▶ dim_product (SCD2)
           ──▶ dim_store
           ──▶ dim_customer
           ──▶ dim_date
```

## 5. Layer contracts

| Layer | Input | Output | Rules |
|---|---|---|---|
| Bronze | raw files | `bronze.<source>` + load metadata | land untouched; filename, load_time, row_count, checksum |
| Silver | bronze | typed/standardised + `quarantine` | dedup, type cast, tz normalise, currency parse |
| Gold | silver | `fact_*`, `dim_*` | surrogate keys, SCD2, referential integrity |
| Marts | gold | `mart_*` | `<<the aggregates consumers asked for>>` |

## 6. Orchestration

- DAG: `ingest → bronze → silver → dq_gate → gold → marts → publish`
- Retries: `<<n>>`; retry delay: `<<...>>`
- Backfill: parametrised by `DATE_FROM`/`DATE_TO`.

## 7. Data quality

| Rule | Layer | Action on fail |
|---|---|---|
| PK not null & unique | silver/gold | quarantine / fail build |
| qty ≥ 0 unless return | silver | quarantine with reason |
| price within 5σ | silver | flag |
| referential integrity | gold | quarantine |
| freshness by deadline | ingestion | freshness failure + alert |

## 8. Observability

- `run_log` (run_id, dag, task, status, rows_in/out, started, ended)
- `metrics` (dq_pass_rate, quarantine_count, freshness_lag)
- Health page endpoint; one alert rule (`<<which metric, which threshold>>`).

## 9. Interfaces / APIs

`<<health endpoint, any service endpoints, dashboard data source>>`

## 10. Security

- Synthetic data only; no secrets in repo; `.env.example` with dummy values.
- PII in `dim_customer`: `<<masking / hashing approach>>`.
