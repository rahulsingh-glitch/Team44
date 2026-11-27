#!/usr/bin/env bash
# Superset bootstrap for GridPulse (dev). Idempotent: safe on every `make up`.
# Metadata lives in SUPERSET_HOME (a named volume), so admin + migrations
# survive restarts. Pins the login to admin / admin for the rehearsal.
set -euo pipefail

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
