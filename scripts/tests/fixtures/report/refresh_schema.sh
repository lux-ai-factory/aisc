#!/usr/bin/env bash
# Schema-only fixtures for the report tests (report run 2026-09-23, 02 section 5).
#
# Reads the LIVE stack's postgres container (`postgres`) with pg_dump --schema-only:
# a read, never a write. The dumps carry no data, no owners and no grants; the test
# bed restores each schema as its own module role, so ownership is as on the stack.
#
#   scripts/tests/fixtures/report/refresh_schema.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SU=${POSTGRES_USER:-aisc-postgres-user}
LIVE=${LIVE_PG_CONTAINER:-postgres}
dump() { docker exec "$LIVE" pg_dump -U "$SU" --schema-only --no-owner --no-privileges "$@" \
  | grep -v -e '^-- Dumped from' -e '^-- Dumped by' -e '^\\restrict ' -e '^\\unrestrict ' \
  | grep -v -e '^COMMENT ON SCHEMA' -e '^SET default_table_access_method' -e 'pg_catalog.set_config(.search_path'; }

# COMMENT ON SCHEMA needs the owner; the bed restores as the module role
for s in qualification control_objectives engine; do
  dump -d platform -n "$s" | grep -v "^CREATE SCHEMA $s;" > "$HERE/schema_$s.sql"
done
# any project database: the controls schema is the same in each (made by controls' migrations)
PROJECT_DB=$(docker exec "$LIVE" psql -U "$SU" -d platform -tAc \
  "SELECT datname FROM pg_database WHERE datname ~ '^project_[0-9a-f]{32}$' ORDER BY datname LIMIT 1")
dump -d "$PROJECT_DB" -n controls | grep -v '^CREATE SCHEMA controls;' > "$HERE/schema_controls.sql"
dump -d superset -n public | grep -v -e '^CREATE SCHEMA public;' -e "^COMMENT ON SCHEMA public" > "$HERE/schema_superset.sql"
wc -l "$HERE"/schema_*.sql
