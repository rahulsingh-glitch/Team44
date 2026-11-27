# Agent 3 — Gold + Marts  ·  Adarsh Kumar Singh

**Owns:** the gold star schema, SCD2 dimensions, fact table(s), the two marts, the
idempotent upsert, and the **data-model section of the LLD**.
**Scored areas you anchor:** Functional (20), Engineering quality (15).

> Read `00-orchestration.md` first. Build against the contract (§0.2) — you can start
> on agreed table shapes before Silver is finished, then wire to real `silver.*` tables.
> The dbt SCD2 scaffold already exists in `dbt/snapshots/dim_product.sql`.

## Dependencies & handoffs
- **Needs:** `silver.*` from A2 (wire at ~T+2:00); schemas from A4 at T+1:00.
- **Hands off:** `gold.*` and `mart.*` to A5 (dashboard) at ~T+2:30.

## Phase 1 — Data model (0:20–1:00)

**Tasks:** finalise the star schema and fill `docs/lld.md §4` (grain, keys, which dims
are SCD2 and why). Agree surrogate-key strategy with the Tech Lead.

**Session prompt**
- `Given this card and our silver contract, design the gold star schema: fact grain, measures, and each dimension with its SCD type. Explain in one line per dimension why it is SCD2 or not. Write it into docs/lld.md section 4 with an ascii star diagram. Plan first.`

## Phase 2 — Dimensions incl. SCD2 (1:00–2:00)

**Tasks:** build `dim_date`, `dim_store`, `dim_customer`, and **`dim_product` as SCD2**
(price/category change keeps history via `valid_from/valid_to/is_current`). Use the dbt
snapshot if you went dbt, or a merge in SQL/Spark otherwise.

**Session prompts**
- `Implement dim_product as SCD2 using the dbt snapshot in dbt/snapshots/dim_product.sql, sourced from our silver product table. Plan the check_cols and the schema first.`
- `Write a test test_product_rename_keeps_history: when a product's category changes mid-year, dim_product has two rows, exactly one is_current, and valid_from/valid_to do not overlap.`

**DoD:** renamed product keeps history; exactly one current row; test green.

## Phase 3 — Fact + idempotent load (2:00–2:45)

**Tasks:** build `fact_sales` joined to dimension surrogate keys; **re-running a day
produces identical results** (merge/upsert on the business key, not blind insert);
rows with an unknown dimension key are quarantined (referential integrity).

**Session prompts**
- `Build fact_sales from silver sales, resolving product_key/store_key/customer_key/date_key against the current dims. Load must be idempotent for a given date: re-running replaces that date's rows, not appends. Plan the merge strategy first.`
- `Write test_rerun_is_idempotent: run the gold load for one date twice and assert fact_sales totals and row counts are identical.`

## Phase 4 — Marts (2:45–3:15)

**Tasks:** `mart.daily_store_sales` and `mart.product_margin_by_category` (the two the
consumers asked for). Keep them thin aggregates over gold.

**Session prompt**
- `Create the two marts as aggregates over gold: daily_store_sales (revenue, units by date, store) and product_margin_by_category. Add a dbt not_null/unique test on each mart's grain. Plan first.`

**DoD:** both marts populated; grain tests green; A5 can read them for the dashboard.

## Your pitfalls
- Non-idempotent fact load (blind inserts) → double-counting on re-run. This is the
  single most-tested Track B failure — prove it with `test_rerun_is_idempotent`.
- SCD2 with overlapping validity windows — test for it.
