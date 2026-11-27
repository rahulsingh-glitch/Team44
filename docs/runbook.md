# Runbook — OmniRetail Lakehouse (Team 44)

> Scored under **SRE & observability (10)**. The SRE must be able to run EVERY
> command here during the drill. Keep commands copy-pasteable.

## 1. Start / stop (fresh-clone, one command)

Prereq: Docker Desktop running. From a clean checkout:

```bash
make up        # creates .env, starts Postgres 18 + Airflow 3.3 + Superset,
               # waits for healthchecks, creates schemas, prints URLs
make down      # stop the stack, keep data
make nuke      # stop AND delete all volumes (true fresh start)
make ps        # service status
make schemas   # re-create warehouse schemas (idempotent)
```

**Windows without `make`** (run from the repo root; equivalent to `make up`):

```bash
test -f .env || cp .env.example .env
docker compose -f deploy/docker-compose.yml up -d --wait
docker compose -f deploy/docker-compose.yml exec -T warehouse \
  sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/init-schemas.sql
```

After `make up`:

| Service | URL | Login |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| Superset | http://localhost:8088 | admin / admin |
| Warehouse (Postgres 18) | `postgresql://localhost:5432/lakehouse` | postgres / postgres (dev) |
| Health page | http://localhost:8000/health | `make health` (stdlib server, `src/observability/health.py`) |

Schemas created: `bronze, silver, gold, mart, obs, ref`.

> **Security note (dev only).** Airflow 3's SimpleAuthManager stores passwords in
> **plaintext** in `deploy/airflow/simple_auth_manager_passwords.json.generated`
> (committed as `{"admin":"admin"}` so the login is stable across `make down && make up`
> and `make nuke`). This is acceptable for the rehearsal only — swap for FAB or an
> external auth manager (Keycloak) in production. Postgres and Superset dev credentials
> live in `.env` (git-ignored); only `.env.example` is committed.
>
> Postgres 18 note: the warehouse volume is mounted at `/var/lib/postgresql` (not
> `/var/lib/postgresql/data`) — PG18 reserves the `/data` subpath and refuses to boot
> against a volume mounted directly there.

## 2. Run the pipeline
```bash
make run                                   # one day (CLI)
make backfill DATE_FROM=2025-09-01 DATE_TO=2025-09-03
```
**Airflow** (http://localhost:8080, admin/admin) — `gridpulse_pipeline` runs
`land → bronze → silver → dq → consumption → anomaly → publish`, calling the SAME stage
functions as the CLI (identical output). Both DAGs are created **paused**.
```bash
make dag-test DATE=2025-09-03                              # one date, in-process
make airflow-backfill DATE_FROM=2025-09-01 DATE_TO=2025-09-03   # one run per date, in order
```
Range in ONE run: trigger `gridpulse_pipeline` with config `{"date_from": "...", "date_to": "..."}`.
Retries: 2 × 2 min (late landing files); DQ gate failure does **not** retry.
`gridpulse_maintenance` (daily): retention (data clock, or `as_of` param; `dry_run`) →
VACUUM + REINDEX CONCURRENTLY of the last 3 days.

## 3. Where to look when something breaks (DETECT)
- Dashboard: http://localhost:8088/superset/dashboard/gridpulse/ (admin/admin) — tabs: Feeder
  consumption · Anomalies · Data completeness (DQ scorecard) · Pipeline health; Zone filter.
  (Re)build: `make dashboard` (mart.* views + Superset API upsert + chart-query verify).
- Health page: http://localhost:8000/health (`make health`) — `ok` 200 / `degraded` 200
  (alert firing) / `down` 503 (DB unreachable or last pipeline run failed; `last_run.error` says why)
- Airflow UI (task failures): http://localhost:8080
- Tables: `obs.run_log` (one row per stage per run, `status`, `duration_s`, `error`),
  `obs.metrics` (completeness_pct per zone+ALL, duplicate_rate, ingest_lag_s, quarantine_count,
  readings, run_duration_s), `obs.alert`, `silver.quarantine`
- Alert: `COMPLETENESS_DROP` — printed as an `ALERT ...` line on stderr and stored in `obs.alert`.
  Fires per zone/ALL when completeness < `ALERT_COMPLETENESS_MIN_PCT` (90) or drops >
  `ALERT_COMPLETENESS_DROP_PTS` (2.0) below the previous-7-day mean.
- Quick queries:
  `SELECT stage, metric_date, status, error FROM obs.run_log WHERE status <> 'success' ORDER BY started_at DESC LIMIT 10;`
  `SELECT metric_date, scope, value, baseline, evidence->'worst_feeders' FROM obs.alert ORDER BY fired_at DESC;`

## 4. Common incidents (TRIAGE → FIX)
| Symptom | Likely cause | Fix | Verify |
|---|---|---|---|
| DQ pass-rate drops | source schema change / bad values | <<...>> | re-check scorecard |
| Day double-counts | re-delivered file not skipped | check checksum ledger | row counts stable on re-run |
| `ALERT COMPLETENESS_DROP` (zone) | feeder outage / late or missing landing file / quarantine spike | read `evidence.worst_feeders`; check `gold.anomaly` OUTAGE for that feeder+date and `silver.quarantine` counts; if files were late, `make backfill DATE_FROM=D DATE_TO=D` | completeness_pct for the zone back within 2 pts of baseline; alert row gone after re-run |
| `/health` = 503 `down` | last pipeline run failed (or DB down) | `obs.run_log` failed row → `error` + `stage`; fix, re-run the date | `/health` back to 200 |
| Freshness alert | late/missing source file | run backfill for the date | freshness lag clears |
| DAG `land` retries then fails | landing files for the date are late/missing (`FileNotFoundError: no landing files for [...]`) | wait for / re-deliver the files, then clear the task (or `make dag-test DATE=D`) | task green; `/health` back to 200 |
| DAG `dq` fails, no retry | DQ gate: `dq_pass_rate` < `ALERT_DQ_PASS_RATE_MIN` or an invariant FAIL | `SELECT * FROM obs.dq_results WHERE check_date=D AND status<>'PASS'`; fix the source/silver rule, re-run; `DQ_GATE=warn` only as a conscious override | all checks PASS; gold rebuilt |

## 5. SRE drill procedure (3:30)
1. **Detect** the symptom in our own dashboard/alert (not from the mentor).
2. **Triage:** give Claude the trimmed log lines + the metric. Form hypotheses.
3. The team picks which hypothesis to test.
4. **Fix** the cause, add a **regression test** and an **alert**, verify against our metric.
5. Write the **RCA** below. Rahul approves the runbook before the drill ends.

## 6. RCA template
- **What happened:** <<...>>
- **Impact:** <<...>>
- **Root cause:** <<...>>
- **Fix:** <<...>>
- **Prevention (test/alert added):** <<...>>
- **Timeline:** detected <<hh:mm>> → fixed <<hh:mm>>
