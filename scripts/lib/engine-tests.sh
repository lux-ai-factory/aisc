#!/usr/bin/env bash
# The engine's (apps/backend) tests, the way CI runs them.
#
#   scripts/lib/engine-tests.sh [manage.py test arguments]              # sqlite, default mode
#   scripts/lib/engine-tests.sh --postgres [manage.py test arguments]   # throwaway Postgres, configurator mode
#
# sqlite mode runs every test package and test_*.py module directly under aisc_backend/tests but `integration`
# (upstream's, it needs a live stack) on a fresh sqlite file that is removed afterwards.
#
# --postgres runs the modules that need a Postgres superuser (the project database tests) on a throwaway
# Postgres (scripts/lib/throwaway-pg.sh, never the stack's port) with the platform's roles, in configurator mode. Those
# tests skip, and the run still says OK, when the database does not reach them: a run that skipped any of them
# fails here.
#
# Both modes run from the engine's lock and ignore the caller's DATABASE_URL. The vendored wheels are the
# engine's only source of the plugin interface, the plugin-manager and aisc_identity.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BACKEND="$ROOT/apps/backend"
TESTS="$BACKEND/aisc_backend/tests"
RUNNER=(uv run --locked --all-extras python manage.py test)

postgres=0
if [ "${1:-}" = "--postgres" ]; then
  postgres=1
  shift
fi

labels=()
if [ $postgres = 0 ]; then
  for entry in "$TESTS"/*; do
    name=$(basename "$entry")
    if [ -d "$entry" ] && [ -f "$entry/__init__.py" ] && [ "$name" != integration ]; then
      labels+=("aisc_backend.tests.$name")
    elif [ -f "$entry" ] && [[ "$name" == test_*.py ]]; then
      labels+=("aisc_backend.tests.${name%.py}")
    fi
  done
else
  for entry in "$TESTS"/*.py; do
    name=$(basename "$entry" .py)
    [ "$name" = isolation_support ] && continue
    if grep -qE 'SUPERUSER_URL_VAR|superuser_url' "$entry"; then
      labels+=("aisc_backend.tests.$name")
    fi
  done
fi
sorted=()   # sorted with a read loop, which bash 3.2 (macOS) also has
while IFS= read -r label; do sorted+=("$label"); done < <(printf '%s\n' "${labels[@]}" | LC_ALL=C sort)
labels=("${sorted[@]}")

if [ $postgres = 0 ]; then
  db_folder=$(mktemp -d)
  trap 'rm -rf "$db_folder"' EXIT
  cd "$BACKEND"
  status=0
  env -u DATABASE_URL -u AISC_DEPLOYMENT \
    DB_ENGINE=django.db.backends.sqlite3 DB_NAME="$db_folder/engine-tests.db" \
    "${RUNNER[@]}" "${labels[@]}" "$@" || status=$?
  exit $status
fi

. "$ROOT/scripts/lib/throwaway-pg.sh"
tpg_start engine >/dev/null
tpg_init_platform "$ROOT"
tpg_su platform -f - < "$ROOT/init/report-roles.sql" >/dev/null
tpg_su platform -f - < "$ROOT/init/inspector-role.sql" >/dev/null

output=$(mktemp)
cd "$BACKEND"
status=0
env -u DATABASE_URL \
  ENGINE_TEST_SUPERUSER_URL="postgresql://$TPG_SU:$TPG_PW@127.0.0.1:$PORT/platform" \
  PLATFORM_TEST_DATABASE_URL="postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform" \
  AISC_DEPLOYMENT=configurator \
  DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw DB_PASSWORD=engine_rw \
  DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
  "${RUNNER[@]}" "${labels[@]}" "$@" 2>&1 | tee "$output" || status=$?
summary=$(grep -E '^(OK|FAILED)( \(|$)' "$output" | tail -1 || true)
rm -f "$output"
if [[ "$summary" =~ skipped=([0-9]+) ]]; then
  echo "engine-tests: ${BASH_REMATCH[1]} database tests skipped: the throwaway database did not reach them" >&2
  exit 1
fi
exit $status
