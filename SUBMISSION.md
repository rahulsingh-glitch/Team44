# SUBMISSION — the final gate before you're "done"

Run this near 4:15. Nothing here is optional. Run `/gates` first — a gate breach removes the
team from the ranking.

## 1. PASS/FAIL GATES (disqualifying — check first, run `/gates`)

- [ ] **Synthetic/public data only** — no client or confidential data in prompts or repo.
- [ ] **Open-source / free tools only** — nothing subscription-only.
- [ ] **Code stays local / company Git** — nothing pushed outside the approved repo.
- [ ] **No pre-built solution code** — built today; prompt log shows the build.
- [ ] **No secrets in repo** — `.env` git-ignored; only `.env.example` committed; PII handled.

## 2. The ten artifacts — one shared folder, each with an owner

- [ ] **Code base** + README + one-command run — Nabi (+ Rahul review)
- [ ] **LLD** (components, data model, interfaces) — Adarsh (+ Rahul)
- [ ] **Ideation document** (problem, options, chosen approach) — Rahul
- [ ] **Stories (Excel)** with acceptance criteria — Chetan
- [ ] **Test plan** (scope, risks, entry/exit) — Chetan
- [ ] **Test results** (executed cases, defects, evidence) — Chetan (+ each owner's tests)
- [ ] **UI designs / dashboard screens** — Chetan
- [ ] **Runbook** (operate, monitor, recover) + the **RCA** from the drill — Nabi
- [ ] **Pipeline/application demo** (5-minute walkthrough) — Chetan narrates
- [ ] **Presentation** — Rahul — must cover **business alignment, IT security, performance testing**
- [ ] **Claude usage evidence** — CLAUDE.md + docs/claude-log.md (prompts + corrections) — Chetan

## 3. Fresh-clone & CI proof (evaluators will ask)

- [ ] Clone into a clean folder and run `make up` → everything starts (run `/verify-e2e`).
- [ ] `make run` works end to end; re-running a day gives identical totals (idempotency).
- [ ] CI is green on push; unskipping the deliberately-failing test turns CI red.

## 4. The 5-minute demo (same beats for every team — rehearse once, early)

1. Problem in one sentence — 0:20
2. Architecture + the key decision — 0:40
3. Live happy path (run the DAG, show gold + dashboard) — 1:30
4. A failure handled well (planted defect skipped / SCD2 history / quarantined row) — 1:00
5. Metrics, the drill, the RCA — 1:30

## 5. Final submission checklist

- [ ] One shared folder contains all ten artifacts.
- [ ] README explains how to run it.
- [ ] Presentation covers business alignment + IT security + performance testing.
- [ ] Runbook + RCA included.
- [ ] Demo environment started and rehearsed.
- [ ] `docs/status.csv` (and the sheet, if used) shows every task `done`.
