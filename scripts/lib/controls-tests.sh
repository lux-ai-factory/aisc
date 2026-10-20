#!/usr/bin/env bash
# The controls app's integration tests on a throwaway Postgres of their own, then removed.
#
#   scripts/lib/controls-tests.sh [vitest arguments]
#
# The tests make project databases from platform/project-template, so they need the roles and
# databases postgres-setup makes; never the running stack's Postgres on 5432.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
. "$ROOT/scripts/lib/throwaway-pg.sh"
TPG_PG_ARGS="-c fsync=off -c full_page_writes=off -c synchronous_commit=off" tpg_start controls >/dev/null
tpg_init_platform "$ROOT" >/dev/null
tpg_su postgres -f - < "$ROOT/init/report-roles.sql" >/dev/null
cd "$ROOT/apps/controls"
CONTROLS_TEST_PG_CONTAINER=$TPG_NAME \
PROJECT_DATABASE_URL="$(tpg_dsn controls_rw '{database}')?schema=controls&connection_limit=2" \
  npx vitest run test/integration "$@"
