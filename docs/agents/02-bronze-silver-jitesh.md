# Agent 2 — Bronze + Silver  ·  Jitesh Binnar

**Owns:** source ingestion, bronze landing with load metadata, silver typing/dedup/
standardise/quarantine, re-delivery handling, and the **synthetic-data seed script**.
**Scored areas you anchor:** Functional (20), Data quality (15).

> Read `00-orchestration.md` first. You code against the shared contract (§0.2):
> `bronze.load_log`, `silver.quarantine`, the reason-code list. Working stubs already
> exist in `src/common/checksum.py`, `src/common/normalise.py`, `src/silver/quarantine.py`.

## Dependencies & handoffs
- **Needs:** schemas created by A4 (DevOps) — at T+1:00.
- **Hands off:** populated `silver.*` tables to A3 (Gold); `silver.quarantine` feeds A5's DQ scorecard.

## Phase 1 — Synthetic data first (0:20–1:00)
The whole team is blocked without data, so this is your first job.

**Tasks:** finish `scripts/generate_synthetic_data.py` to emit, into `data/landing/`:
POS CSV per store, e-commerce JSON, product/store master CSV — **with the five planted
defects baked in** (re-delivered file, late-arriving rows, a product renamed mid-year,
amounts with currency symbols, mixed time zones). Keep it seeded/deterministic.

**Session prompts**
- `Plan a synthetic data generator using Faker for: 50 stores, 5000 products, 100k customers, ~2M sale lines over 12 months. Output POS CSV per store, e-commerce JSON, product+store master CSV into data/landing/. It must be deterministic with a seed. Plan only — list the functions and the file layout. Don't code yet.`
- `Implement it. Then add five planted defects as separate injectable functions: a byte-identical re-delivered file, late-arriving sales dated to a prior day, one product renamed mid-year, some amounts with currency symbols, and timestamps in mixed time zones.`

## Phase 2 — Bronze (1:00–1:45)

**Tasks:** land every file untouched; write one `bronze.load_log` row per file with
`file_name, load_time, row_count, checksum`; skip re-deliveries via the checksum ledger.

**Session prompts**
- `Using src/common/checksum.py, write the bronze loader: for each file in data/landing/, compute its checksum, and if it is new, land the raw rows into bronze.<source> and append a row to bronze.load_log. If the checksum was seen before, skip it and log a skip. Plan first.`
- `Write a test test_redelivered_file_is_skipped that loads the same file twice and asserts bronze row counts are unchanged on the second load.`

**DoD:** re-delivered file is skipped; load_log populated; test green.

## Phase 3 — Silver (1:45–2:45)

**Tasks:** type-cast, dedup on natural keys, standardise (currency → number via
`parse_amount`, timestamps → one tz via `to_utc`), route bad rows to `silver.quarantine`
with a reason code from the closed list.

**Session prompts**
- `Write the silver transform for sales: cast types, dedupe on (store_id, sale_id), normalise amount with parse_amount and timestamps with to_utc. Any row that fails validation goes to silver.quarantine with a reason_code from our closed list. Reuse src/silver/quarantine.py. Plan first.`
- `Add tests: test_unknown_product_is_quarantined, test_negative_qty_quarantined_unless_return, test_currency_symbols_are_parsed, test_duplicate_sale_is_deduped.`

**DoD:** silver tables typed & deduped; quarantine populated with correct reason codes; tests green.

## Your pitfalls
- Over-cleaning in bronze — bronze lands **untouched**; all cleaning is silver.
- Dropping bad rows silently — they must land in quarantine with a reason (that's scored).
