#!/usr/bin/env bash
# The platform's tests against a throwaway PostgreSQL, so the database tests run instead of skipping.
#
#   scripts/test-platform.sh [pytest args]
#
# The throwaway server is set up as scripts/test-pipeline-chain.sh sets up its own: init/platform-db.sql,
# init/project-databases.sql, the owner roles and the project database setup in template1, the reader roles,
# then every platform migration as platform_migrator (PLATFORM_TEST_MIGRATE_DATABASE_URL, which the platform
# also provisions and drops project databases with). A throwaway immudb (with a
# signing key) runs the ledger store, export checker and route tests. Everything is removed on exit.
#
# A skip fails the run unless its reason is in tests/skip_guard.py's ALLOWED_SKIPS (the opt-in drills, the
# pipeline chain, the adapters end-to-end test): a missing service must not hide a test.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/scripts/lib/throwaway-pg.sh"
. "$ROOT/scripts/lib/throwaway-minio.sh"
. "$ROOT/scripts/lib/throwaway-immudb.sh"
# every throwaway goes on exit
# shellcheck disable=SC2034 # read by tpg_start
TPG_OWN_TRAP=1
trap 'tpg_cleanup; tminio_cleanup; timmu_cleanup' EXIT
trap 'tpg_cleanup; tminio_cleanup; timmu_cleanup; exit 130' INT
trap 'tpg_cleanup; tminio_cleanup; timmu_cleanup; exit 143' TERM

# Its tests make and drop hundreds of project databases; each DROP DATABASE waits for a checkpoint,
# minutes apiece with fsync on. Nothing in a throwaway server has to survive a crash.
TPG_PG_ARGS="-c fsync=off -c full_page_writes=off -c synchronous_commit=off" tpg_start platform-tests >/dev/null
tpg_init_platform "$ROOT"
for f in platform-role inspector-role report-roles; do tpg_su platform -f - < "$ROOT/init/$f.sql" >/dev/null; done
for f in $(ls "$ROOT/platform/migrations" | sort); do tpg_platform_migration platform "$ROOT/platform/migrations/$f" >/dev/null; done

# The proof-file store's contract on a real MinIO (tests/test_proof_store.py), when the stack's MinIO image
# is built here (CI builds it). Without it those tests skip, and the skip guard fails the run.
if tminio_start platform-tests; then
  export PROOF_TEST_S3_URL=$TMINIO_URL PROOF_TEST_S3_USER=$TMINIO_USER PROOF_TEST_S3_PASSWORD=$TMINIO_PASSWORD
fi

# The ledger's immudb: required, so a missing server fails the ledger tests instead of skipping them.
timmu_start platform-tests
cd "$ROOT/platform"
export LEDGER_TEST_IMMUDB_URL=$TIMMU_URL LEDGER_TEST_IMMUDB_ADMIN_PASSWORD=$TIMMU_ADMIN_PASSWORD \
  LEDGER_TEST_IMMUDB_PUBLIC_KEY=$TIMMU_PUBLIC_KEY
uv run --extra dev python -c 'import os; from tests.ledger.immudb_box import wait_for; wait_for(os.environ["LEDGER_TEST_IMMUDB_URL"], os.environ["LEDGER_TEST_IMMUDB_ADMIN_PASSWORD"])'

LEDGER_TESTS_REQUIRED=1 PLATFORM_TESTS_STRICT_SKIPS=1 \
PLATFORM_TEST_DATABASE_URL=$(tpg_dsn platform_rw platform) \
PLATFORM_TEST_MIGRATE_DATABASE_URL=$(tpg_dsn platform_migrator platform) \
EVIDENCE_TEST_READER_URL="postgresql://report_ro:report_ro@127.0.0.1:${PORT}/{database}" \
PLATFORM_TEST_SUPERUSER_URL="postgresql://${TPG_SU}:${TPG_PW}@127.0.0.1:${PORT}/platform" \
  uv run --extra dev pytest -p no:cacheprovider -p tests.skip_guard -rs "$@"
