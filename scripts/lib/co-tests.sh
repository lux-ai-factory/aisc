#!/usr/bin/env bash
# The control objectives suite on a throwaway Postgres of its own, then removed.
#
#   scripts/lib/co-tests.sh [pytest arguments]      # from anywhere
#
# The suite drops and recreates the database it is given, so it refuses to run without
# CONTROL_OBJECTIVES_TEST_DATABASE_URL, and refuses 5432 (the running stack's Postgres). This starts
# a container on a port the kernel picks (scripts/lib/throwaway-pg.sh), gives it the platform's roles,
# points the suite at a scratch
# database on it and removes the container when the suite ends, however it ends.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
. "$ROOT/scripts/lib/throwaway-pg.sh"
tpg_start co >/dev/null
# the platform's roles and databases, as postgres-setup makes them: the isolation tests act as
# platform_rw and check what the readers (report_ro, dashboard_ro) may read
tpg_init_platform "$ROOT"
export CONTROL_OBJECTIVES_TEST_DATABASE_URL="postgresql://$TPG_SU:$TPG_PW@127.0.0.1:$PORT/co_tests"
cd "$ROOT/apps/control-objectives"
uv run pytest -q "$@"
