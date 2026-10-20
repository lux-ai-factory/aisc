#!/usr/bin/env bash
# The platform's tests against a throwaway PostgreSQL, so the database tests run instead of skipping.
#
#   scripts/test-platform.sh [pytest args]
#
# The throwaway server is set up as scripts/test-pipeline-chain.sh sets up its own: init/platform-db.sql,
# init/project-databases.sql, the reader roles, then every platform migration. It is removed on exit.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/scripts/lib/throwaway-pg.sh"
trap 'tpg_cleanup' EXIT
trap 'tpg_cleanup; exit 130' INT
trap 'tpg_cleanup; exit 143' TERM

# Its tests make and drop hundreds of project databases; each DROP DATABASE waits for a checkpoint,
# minutes apiece with fsync on. Nothing in a throwaway server has to survive a crash.
TPG_PG_ARGS="-c fsync=off -c full_page_writes=off -c synchronous_commit=off" tpg_start platform-tests >/dev/null
tpg_init_platform "$ROOT"
for f in platform-role inspector-role report-roles; do tpg_su platform -f - < "$ROOT/init/$f.sql" >/dev/null; done
for f in $(ls "$ROOT/platform/migrations" | sort); do tpg_platform_migration platform "$ROOT/platform/migrations/$f" >/dev/null; done

cd "$ROOT/platform"
PLATFORM_TEST_DATABASE_URL=$(tpg_dsn platform_rw platform) \
EVIDENCE_TEST_READER_URL="postgresql://report_ro:report_ro@127.0.0.1:${PORT}/{database}" \
PLATFORM_TEST_SUPERUSER_URL="postgresql://${TPG_SU}:${TPG_PW}@127.0.0.1:${PORT}/platform" \
  uv run --extra dev pytest -p no:cacheprovider "$@"
