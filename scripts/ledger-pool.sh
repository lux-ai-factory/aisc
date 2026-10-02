#!/usr/bin/env bash
# Make more ledger databases for new projects (docs/superpowers/ledger-2026-10-02/02-spec.md 7.1).
#
#   IMMUDB_ADMIN_PASSWORD=... ./scripts/ledger-pool.sh [N]     # default 20
#
# Only immudb's superuser can create databases (spike M1), and the platform service must never hold
# its password. So an operator runs this: the password goes from this shell's environment into one
# short-lived container's environment, never into a file, never onto the command line, never
# printed. The platform's own immudb user (aisc_ledger, LEDGER_IMMUDB_PASSWORD from env.secrets) is
# created on first use and granted read-write on each new database.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${IMMUDB_ADMIN_PASSWORD:?set IMMUDB_ADMIN_PASSWORD (the immudb superuser password) in this shell first}"
COUNT=${1:-20}
[[ "$COUNT" =~ ^[0-9]+$ ]] || { echo "N must be a number" >&2; exit 2; }
# The platform container has no ledger settings of its own: hand it the immudb address and the ledger
# user's password (env.secrets) too. Every value goes by name (-e NAME), never on the command line.
LEDGER_IMMUDB_PASSWORD=$(awk 'index($0, "LEDGER_IMMUDB_PASSWORD=") == 1 { print substr($0, 24); exit }' env.secrets 2>/dev/null || true)
[ -n "$LEDGER_IMMUDB_PASSWORD" ] || { echo "LEDGER_IMMUDB_PASSWORD is missing from env.secrets: run scripts/secrets.sh first" >&2; exit 1; }
LEDGER_IMMUDB_URL=${LEDGER_IMMUDB_URL:-immudb:3322}
export IMMUDB_ADMIN_PASSWORD LEDGER_IMMUDB_PASSWORD LEDGER_IMMUDB_URL
docker compose -p "${COMPOSE_PROJECT:-aisc}" --env-file env.runtime \
  -f docker-compose.plugin_downloader.yml -f docker-compose-infra.development.yml -f docker-compose.development.yml \
  run --rm --no-deps -e IMMUDB_ADMIN_PASSWORD -e LEDGER_IMMUDB_PASSWORD -e LEDGER_IMMUDB_URL \
  platform python -m platform_service.ledger.pool create "$COUNT"
