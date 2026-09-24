#!/usr/bin/env bash
# The databases agree with each other: a read-only consistency check of the stack.
#
#   ./scripts/verify-db-consistency.sh [--only C1,C3]
#
# What this asserts, against the RUNNING stack's Postgres (or the one PG* points at):
#   C1 every project database belongs to a project, and every project has its database,
#   C2 no database or platform schema outside the known list (the old standalone ones too),
#   C3 a card version's name, version and provider read the same in every module,
#   C4 every reference into core.project and core.system resolves, to the right project,
#   C5 every stored Keycloak subject is a user of the aisc realm (WARN),
#   C6 an assessment's graph is still the card's current knowledge graph (WARN),
#   C7 no project database is behind on its template or controls migrations,
#   C8 snake_case columns and timestamptz in the schemas that are not frozen (WARN).
# The catalogue is out of scope. Every session is default_transaction_read_only=on and
# only SELECTs are sent: this reads, it never changes a row.
#
# Connection: PGHOST (127.0.0.1), PGPORT (5432), PGUSER (aisc-postgres-user) and PGPASSWORD,
# read from the postgres container's environment when unset. It is never printed.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
export PGHOST=${PGHOST:-127.0.0.1} PGPORT=${PGPORT:-5432} PGUSER=${PGUSER:-aisc-postgres-user}
if [ -z "${PGPASSWORD:-}" ]; then
  PGPASSWORD=$(docker exec "${PGCONTAINER:-postgres}" printenv POSTGRES_PASSWORD 2>/dev/null) || {
    echo "no PGPASSWORD, and none readable from the ${PGCONTAINER:-postgres} container" >&2; exit 2; }
  export PGPASSWORD
fi
cd "$HERE" && exec uv run --no-project --quiet --with 'psycopg[binary]' python -m db_consistency "$@"
