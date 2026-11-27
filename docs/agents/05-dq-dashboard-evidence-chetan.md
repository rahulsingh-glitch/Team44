# Agent 5 — Data Quality + Dashboard + Claude Evidence + Demo  ·  Chetan Pal

**Owns:** the data-quality checks + DQ scorecard, the dashboard, the **Claude-usage
evidence trail** (CLAUDE.md upkeep, `docs/claude-log.md`), the stories in Excel, the
test plan/results, and narrating the demo. Coming from AI, you're the natural owner of
prompt quality and the evidence layer.
**Scored areas you anchor:** Claude usage (15), Dashboard (5), Data quality (15), Demo & artifacts (10).

> Read `00-orchestration.md` first. DQ can start early against the contract; the
> dashboard needs gold/marts (~T+2:30). The Claude-evidence job runs the **whole day**.

## Dependencies & handoffs
- **Needs:** `silver.quarantine` from A2; `gold.*`/`mart.*` from A3 (~2:30); `obs.metrics` from A4.
- **Hands off:** the DQ scorecard tiles and the narrated demo.

## Running all day — Claude usage evidence (15 pts, most teams underplay this)
Judges ask for prompt history, CLAUDE.md and **corrections made** — not volume.
- Keep `CLAUDE.md` current as decisions change (it's read by every agent and scored).
- After each meaningful session across the team, add a row to `docs/claude-log.md`:
  the prompt intent, what Claude produced, and the **correction** a human made.
- Collect 3–4 of the best reusable prompts. A caught mistake scores higher than flawless output.

## Phase 1 — Stories + DQ rules (0:20–1:30)

**Tasks:** write the backlog (must-haves with acceptance criteria) in the shared Excel;
implement the DQ checks against the contract (completeness, uniqueness, validity,
referential integrity, freshness) producing a `dq_pass_rate` per run.

**Session prompts**
- `From this card's must-have scope, write user stories with acceptance criteria, one per must-have, in a table I can paste into Excel. Mark each as must-have or stretch.`
- `Implement DQ checks over silver/gold using Great Expectations (or SQL assertions): PK not null & unique, qty>=0 unless return, price within 5 std devs, every fact row has a known product+store, freshness by deadline. Emit a dq_pass_rate and per-rule results into obs.metrics. Plan first.`

## Phase 2 — Dashboard (2:30–3:30)

**Tasks:** build the dashboard (Superset or Streamlit) with revenue trend, top products,
store ranking, margin by category, and a **data-quality scorecard** tile. Keep it clean —
it's only 5 points, so don't gold-plate; clarity over polish.

**Session prompts**
- `Build a Streamlit dashboard reading mart.daily_store_sales, mart.product_margin_by_category and obs.metrics with five tiles: revenue trend, top products, store ranking, margin by category, and a DQ scorecard (dq_pass_rate, quarantine_count, freshness). Plan the layout first.`
- `Add empty/loading/error states to each tile so it reads clearly when a table is empty.`

**DoD:** dashboard shows real gold/mart data + a DQ scorecard; readable with empty data.

## Phase 3 — Test plan & results (ongoing → 3:30)
Own `docs/test-plan.md`: make sure every must-have maps to a test (each agent writes
their own; you keep the matrix complete) and record results + any defects found.

## Phase 4 — SRE drill support (3:30–4:15)
The DQ scorecard is likely where the fault shows first — make sure it's visible and
refreshing. Help A4 trim evidence for Claude.

## Phase 5 — Demo (4:15–4:45) — you narrate
Rehearse the five beats once, early:
1. Problem in one sentence (0:20)
2. Architecture + the key decision (0:40)
3. Live happy path — run the DAG, show gold + dashboard (1:30)
4. A failure handled well — show a planted defect skipped / SCD2 history / a quarantined row (1:00)
5. Metrics, the drill, the RCA (1:30)

Confirm all 10 artifacts are in the shared folder before 4:45.

## Your pitfalls
- Treating Claude-evidence as an afterthought — it's 15 points; log corrections live.
- Over-building the dashboard — it's 5 points; a clear scorecard beats a pretty chart.
