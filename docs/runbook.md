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
| Health page | http://localhost:8000/health | served by the observability layer (added in a later session) |

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
make run                                   # one day
make backfill DATE_FROM=2025-01-01 DATE_TO=2025-01-07
```

## 3. Where to look when something breaks (DETECT)
- Dashboard DQ scorecard: <<url>>
- Health page: http://localhost:8000/health
- Airflow UI (task failures): http://localhost:8080
- Tables: `run_log`, `metrics`, `quarantine`

## 4. Common incidents (TRIAGE → FIX)
| Symptom | Likely cause | Fix | Verify |
|---|---|---|---|
| DQ pass-rate drops | source schema change / bad values | <<...>> | re-check scorecard |
| Day double-counts | re-delivered file not skipped | check checksum ledger | row counts stable on re-run |
| Freshness alert | late/missing source file | run backfill for the date | freshness lag clears |
| DAG task retries then fails | <<...>> | <<...>> | task green in Airflow |

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
