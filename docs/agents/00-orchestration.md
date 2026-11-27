# Agent 0 — Orchestration (READ FIRST, everyone)

This playbook splits the build across **five agents**, one per team member, each driven
in their own Claude Code session. This file is the shared contract that lets all five
work the same repo in parallel without colliding. Read it before opening your own brief.

> How to run your agent: open Claude Code in the repo root, make sure `CLAUDE.md` is
> present (it's read automatically), then paste your brief's **Session prompts** one at
> a time. **One task per session** — start a fresh session per component to avoid
> context bloat. Plan first, approve the plan, then let it code.

---

## 0.1 The golden rules (apply to every agent)

1. **Plan first.** Every session: ask Claude for a short plan, a human approves it, *then* code.
2. **Every must-have has a test.** Nothing is "done" until a test proves it, and `make test` is green.
3. **Small steps, small commits.** One change per commit, prefixed `feat|fix|test|docs|ci|chore`.
4. **Branch per feature.** `feature/<thing>`; merge to `main` only after one teammate reviews.
5. **Idempotent by default.** Any transform must give identical output on re-run.
6. **Run it, read it, before you keep it.** Reviewer runs and reads each change (don't accept code you can't explain).
7. **Log the notable Claude moments** into `docs/claude-log.md` — especially corrections you made.
8. **Synthetic data only. No secrets. No client data. Ever.**

## 0.2 The shared data contract (so agents don't block each other)

Every agent codes against these **fixed names**. If a name must change, the Tech Lead
changes it here first and tells everyone. This contract is what lets Gold start before
Silver is finished — you build against the agreed shape, then wire the real source.

**Warehouse:** PostgreSQL 18 (Docker image). Orchestration: Airflow 3.3 (Docker image). Dashboard: Superset.

**Schemas / layers**
- `bronze.*` — raw landed tables, one per source + `bronze.load_log`
- `silver.*` — cleaned tables + `silver.quarantine`
- `gold.*` — `gold.fact_sales`, `gold.dim_product`, `gold.dim_store`, `gold.dim_customer`, `gold.dim_date`
- `mart.*` — `mart.daily_store_sales`, `mart.product_margin_by_category`
- `obs.*` — `obs.run_log`, `obs.metrics`

**`bronze.load_log` columns** (Bronze agent owns, everyone reads):
`run_id, source_name, file_name, load_time, row_count, checksum`

**`silver.quarantine` columns** (Silver agent owns):
`run_id, source_name, raw_row (json), reason_code, quarantined_at`

**`gold.fact_sales` grain:** one row per sale line.
Keys: `product_key, store_key, customer_key, date_key`. Measures: `quantity, unit_price, amount, is_return`.

**`gold.dim_product` is SCD2:** `product_key (surrogate), product_id (natural), product_name, category, unit_price, valid_from, valid_to, is_current`.

**`obs.run_log` columns** (DevOps agent owns, everyone writes via a helper):
`run_id, dag, task, status, rows_in, rows_out, started_at, ended_at`

**Reason codes (closed list):** `UNKNOWN_PRODUCT, UNKNOWN_STORE, NEGATIVE_QTY, UNPARSEABLE_AMOUNT, DUPLICATE_KEY, PK_NULL`.

## 0.3 Build order & dependencies

Parallel where possible; the dotted deps are the only hard blocks.

```
Agent 1 (Tech Lead) ── sets contract, decisions, CLAUDE.md ──┐ (hour 0–1, unblocks all)
Agent 4 (DevOps)    ── stack up, schemas, run_log helper ────┤ (hour 0–1, unblocks all)
Agent 2 (Bronze+Silver) ── needs schemas ───────────────────┤
Agent 3 (Gold+Marts)    ── builds vs contract, wires to silver when ready
Agent 5 (DQ+Dashboard+Evidence) ── DQ anytime; dashboard needs gold/marts (~2:30)
```

**Critical path:** stack+schemas (A4) → bronze+silver (A2) → gold (A3) → marts (A3) → dashboard (A5).
Everyone keeps a **working end-to-end slice alive from hour 1** — even on fake rows — so the demo never depends on a last-minute integration.

## 0.4 Integration checkpoints (Tech Lead runs these)

- **T+1:00** — stack green, schemas exist, contract frozen, CLAUDE.md done, synthetic data generating.
- **T+2:00** — bronze+silver landing real data; gold building on contract; DQ checks running.
- **T+3:00** — gold+marts populated; dashboard reading real data; `make run` works end to end; CI green.
- **T+3:30** — **freeze features.** Observability + one alert live. Enter SRE drill.
- **T+4:15** — RCA written. Enter demo prep.
- **T+4:45** — all 10 artifacts in the shared folder; demo rehearsed once.

## 0.5 Definition of done (every component)

- [ ] Code merged to `main` after one review
- [ ] A test with a rule-stating name proves it, and `make test` is green
- [ ] Formatter + linter pass (`make lint`)
- [ ] It runs via `make run` / the DAG, not just locally in one person's head
- [ ] Its artifact section in `docs/` is updated
- [ ] A line in `docs/claude-log.md` if Claude was corrected

## 0.6 The 10 artifacts — single owner each (draft as you go, not at the end)

| Artifact | Owner |
|---|---|
| Code base + README + one-command run | A4 DevOps (+ A1 review) |
| LLD | A3 Gold (+ A1) |
| Ideation document | A1 Tech Lead |
| Stories (Excel) | A5 |
| Test plan + Test results | A5 (+ each owner's tests) |
| Dashboard / "UI designs" | A5 |
| Runbook | A4 DevOps |
| Pipeline demo (narration) | A5 |
| Presentation (biz align + security + perf) | A1 Tech Lead |
| Claude usage evidence (CLAUDE.md + log) | A5 (everyone contributes) |

## 0.7 On the day, before anyone codes

The revealed card may differ from OmniRetail. Tech Lead does the 6 prep steps (read &
restate, ask Claude for gaps, slice scope, decide big choices, prep setup, plan the clock),
updates the `<<...>>` markers in `CLAUDE.md`, `docs/lld.md`, `docs/ideation.md`, and
adjusts the contract above. Then each agent opens its brief.
