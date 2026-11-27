# GridPulse one-command interface. Included from the root Makefile, so all
# paths are relative to the repo root. Requires Docker Desktop + GNU make.
# (Windows without make: run the docker compose commands in docs/runbook.md §1.)
.PHONY: up down nuke schemas ps logs seed run test backfill fmt lint

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

test:               ## run every test
	pytest -q

fmt:                ## auto-format
	black src tests scripts && ruff check --fix src tests scripts

lint:               ## check formatting + lint (what CI runs)
	ruff check src tests scripts && black --check src tests scripts
