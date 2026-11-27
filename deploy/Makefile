# GridPulse one-command interface. Included from the root Makefile, so all
# paths are relative to the repo root. Requires Docker Desktop + GNU make.
# (Windows without make: run the docker compose commands in docs/runbook.md §1.)
.PHONY: up down nuke schemas ps logs seed run test backfill compact retention health dag-test airflow-backfill dashboard fmt lint

COMPOSE := docker compose -f deploy/docker-compose.yml

up: .env            ## start the whole stack, create schemas, print URLs
	$(COMPOSE) up -d --wait
	$(MAKE) schemas
	@echo ""
	@echo "GridPulse stack is UP:"
	@echo "  Airflow   -> http://localhost:8080   (admin / admin)"
	@echo "  Superset  -> http://localhost:8088   (admin / admin)"
	@echo "  Warehouse -> postgresql://localhost:5432/lakehouse"
	@echo "  Health    -> http://localhost:8000/health   (served by the observability layer, added later)"

down:               ## stop the stack, keep volumes/data
	$(COMPOSE) down

nuke:               ## stop the stack AND delete all volumes (fresh start)
	$(COMPOSE) down -v

schemas:            ## (re)create warehouse schemas, idempotent
	@echo "Creating schemas bronze/silver/gold/mart/obs/ref..."
	$(COMPOSE) exec -T warehouse sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < scripts/init-schemas.sql

ps:                 ## show service status
	$(COMPOSE) ps

logs:               ## tail logs for all services (Ctrl-C to stop)
	$(COMPOSE) logs -f

.env:               ## create .env from the committed example on first run
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

# --- pipeline targets (depend on builder-layer code; kept for the team) ----
seed:               ## generate synthetic data into data/landing/
	python scripts/generate_synthetic_data.py

run:               ## run the pipeline end to end for one day
	python -m src.pipeline run --date $${DATE:-today}

backfill:           ## make backfill DATE_FROM=... DATE_TO=...
	python -m src.pipeline backfill --date-from $(DATE_FROM) --date-to $(DATE_TO)

compact:            ## VACUUM+REINDEX partitions: make compact DATE_FROM=... DATE_TO=...
	python -m src.storage.maintenance compact --date-from $(DATE_FROM) --date-to $(DATE_TO)

retention:          ## drop expired partitions: make retention [AS_OF=YYYY-MM-DD] [DRY_RUN=1]
	python -m src.storage.maintenance retention $(if $(AS_OF),--as-of $(AS_OF)) $(if $(DRY_RUN),--dry-run)

health:             ## serve GET /health on :8000 (HEALTH_PORT) — Ctrl-C to stop
	python -m src.observability.health

dag-test:           ## run the Airflow DAG once in-process: make dag-test DATE=2025-09-03
	$(COMPOSE) exec -T airflow-scheduler airflow dags test gridpulse_pipeline $(DATE)

airflow-backfill:   ## Airflow backfill, dates in order: make airflow-backfill DATE_FROM=... DATE_TO=...
	$(COMPOSE) exec -T airflow-scheduler airflow backfill create --dag-id gridpulse_pipeline \
		--from-date $(DATE_FROM) --to-date $(DATE_TO) --max-active-runs 1 --reprocess-behavior completed

dashboard:          ## mart.* views + provision/refresh the Superset "GridPulse" dashboard (idempotent)
	python -m src.marts.views
	python deploy/superset/provision_dashboard.py --verify

test:               ## run every test
	python -m pytest -q

fmt:                ## auto-format
	python -m black src tests scripts && python -m ruff check --fix src tests scripts

lint:               ## check formatting + lint (what CI runs)
	python -m ruff check src tests scripts && python -m black --check src tests scripts
