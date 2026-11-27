# Agent 4 — DevOps + SRE  ·  Mohammad Nabi Hasan

**Owns:** docker-compose stack, schema creation, the Airflow DAG (deps, retries,
backfill), CI + the deliberately-failing test, observability (`obs.run_log`,
`obs.metrics`, health page, one alert), and the **runbook**. You lead the SRE drill.
**Scored areas you anchor:** SRE & observability (10), Deployment/CI (5), Performance (5).

> Read `00-orchestration.md` first. You **unblock everyone** in hour 1 — stack and
> schemas must be green by T+1:00. Scaffolds exist in `deploy/` and `deploy/ci/ci.yml`.

## Dependencies & handoffs
- **Blocks everyone** until stack + schemas are up (do this first).
- **Hands off:** a `run_log` write-helper everyone calls; a live alert before 3:30.

## Phase 1 — Stack + schemas + one-command start (0:20–1:00)

**Tasks:** `make up` brings up Postgres (and Airflow if used) and creates the
`bronze/silver/gold/mart/obs` schemas. Prove a **fresh-clone start** works.

**Session prompts**
- `Finish deploy/docker-compose.yml and a make up target that starts Postgres 18, waits for health, and runs a script to create schemas bronze, silver, gold, mart, obs. Plan first.`
- `Write src/observability/run_log.py with a helper log_run(run_id, dag, task, status, rows_in, rows_out) that appends to obs.run_log, and a context manager that times a task and writes started_at/ended_at. Add a test.`

**DoD:** `make up` on a fresh clone yields green schemas; run_log helper tested.

## Phase 2 — DAG, CI, one-command run (1:00–2:30)

**Tasks:** Airflow DAG `ingest → bronze → silver → dq_gate → gold → marts → publish`
with retries and a **backfill** parametrised by date range; CI runs lint + tests on
every push; keep one **deliberately-failing test** ready to prove CI turns red.

**Session prompts**
- `Write the Airflow 3.3 DAG chaining our pipeline steps with dependencies, 2 retries, and a dq_gate task that fails the run if dq_pass_rate < ALERT_DQ_PASS_RATE_MIN. Add a backfill entry parametrised by date_from/date_to. Plan first.`
- `Place deploy/ci/ci.yml at .github/workflows/ci.yml, running ruff + black --check + pytest on push. Confirm the suite is green, then show me how unskipping tests/test_deliberately_failing.py makes CI red.`

**DoD:** DAG runs end to end with retries; `make backfill` works; CI green on push; failing-test proof ready.

## Phase 3 — Observability (2:30–3:30)

**Tasks:** `obs.metrics` (dq_pass_rate, quarantine_count, freshness_lag); a health page
endpoint; **one alert** (e.g. dq_pass_rate below threshold, or a freshness breach). These
must be live **before** 3:30 — you can't "detect it in your own metrics" otherwise.

**Session prompts**
- `Write a simple /health endpoint (FastAPI or Flask) that reads obs.metrics and the latest obs.run_log and returns status + the three key metrics as JSON. Plan first.`
- `Add an alert rule: when dq_pass_rate < threshold or a source misses its freshness deadline, write an alert row and print a clear ALERT line. Add test_late_file_raises_freshness_failure.`

## Phase 4 — Performance (quick, parallel)
State a target (e.g. full day processed in < N min), run the pipeline on the full ~2M
rows once, note the bottleneck and one fix. Put the result in `docs/test-plan.md` and the presentation.

## Phase 5 — SRE drill (3:30–4:15) — you drive
1. **Detect** the symptom in your own dashboard/alert (not from the mentor).
2. **Triage:** give Claude the **trimmed** log lines + the metric (never the whole log). Get ranked hypotheses.
3. Team (Tech Lead) picks which hypothesis to test.
4. **Fix** the cause, add a **regression test** and an **alert**, verify against the metric.
5. Write the RCA in `docs/runbook.md §6`; Tech Lead approves the runbook.

**Session prompt**
- `Here are the 6 relevant log lines and the affected metric: <<paste trimmed>>. Give 3 ranked hypotheses for the root cause and the single cheapest check for each. Do not change code yet.`

## Your pitfalls
- Leaving observability until after 3:30 — then you have nothing to detect with (common fail).
- Pasting whole logs to Claude in the drill — trim to the relevant lines.
