#!/usr/bin/env bash
# Superset bootstrap for GridPulse (dev). Idempotent: safe on every `make up`.
# Metadata lives in SUPERSET_HOME (a named volume), so admin + migrations
# survive restarts. Pins the login to admin / admin for the rehearsal.
set -euo pipefail

# The apache/superset image ships no Postgres driver; the warehouse needs one.
# Installed into the user site (HOME = superset_home volume) and only if
# missing, so restarts stay fast and offline-safe once installed.
if ! python -c "import psycopg2" 2>/dev/null; then
  echo "[superset-init] installing Postgres driver psycopg2-binary==2.9.10..."
  pip install --no-cache-dir --user --quiet psycopg2-binary==2.9.10
fi

echo "[superset-init] upgrading metadata DB..."
superset db upgrade

echo "[superset-init] ensuring admin user (admin / admin)..."
superset fab create-admin \
  --username "${SUPERSET_ADMIN_USER:-admin}" \
  --password "${SUPERSET_ADMIN_PASSWORD:-admin}" \
  --firstname Admin \
  --lastname User \
  --email "${SUPERSET_ADMIN_EMAIL:-admin@example.com}" || true

echo "[superset-init] initialising roles and permissions..."
superset init

echo "[superset-init] starting web server on :8088..."
exec /usr/bin/run-server.sh
