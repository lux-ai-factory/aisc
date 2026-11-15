#!/usr/bin/env bash
# The engine's (apps/backend) tests, the way CI runs them.
#
#   scripts/lib/engine-tests.sh [labels or files] [manage.py test options]              # sqlite
#   scripts/lib/engine-tests.sh --postgres [labels or files] [manage.py test options]   # throwaway Postgres
#
# sqlite mode runs every test package and test_*.py module directly under aisc_backend/tests but `integration`
# (upstream's, it needs a live stack) on a fresh sqlite file that is removed afterwards, in the default
# (standalone) mode. Then it runs again, in configurator mode (AISC_DEPLOYMENT=configurator), the modules whose
# tests are the Configurator's alone (the door, isolation, the modes: marked configurator_only, configurator_run,
# _CONFIGURATOR_RUN or skipIf(_STANDALONE_RUN)), which a standalone run skips. A module that also needs a
# Postgres superuser runs in --postgres instead. The run fails when either pass fails.
#
# --postgres runs the modules that need a Postgres superuser (the project database tests) on a throwaway
# Postgres (scripts/lib/throwaway-pg.sh, never the stack's port) with the platform's roles, in configurator mode. Those
# tests skip, and the run still says OK, when the database does not reach them: a run that skipped any of them
# fails here.
#
# Labels (aisc_backend.tests.test_x, aisc_backend.tests.test_x.SomeCase) or files (aisc_backend/tests/test_x.py,
# apps/backend/aisc_backend/tests/routers/test_y.py) narrow the run to them; in sqlite mode the configurator
# pass then runs only those of them that are configurator modules. Anything else is passed to manage.py test.
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

CONFIGURATOR_MARK='configurator_only|configurator_run|_CONFIGURATOR_RUN|skipIf\(_STANDALONE_RUN'
SUPERUSER_MARK='SUPERUSER_URL_VAR|superuser_url'

# The package folder a dotted label names, or the module file it or its longest prefix names (a label can go on
# to a test class and method), or nothing.
label_path() { # label
  local rest=$1 path
  path="$BACKEND/$(printf '%s' "$rest" | tr . /)"
  if [ -d "$path" ] && [ -f "$path/__init__.py" ]; then printf '%s\n' "$path"; return; fi
  while [ -n "$rest" ]; do
    path="$BACKEND/$(printf '%s' "$rest" | tr . /)"
    if [ -f "$path.py" ]; then printf '%s\n' "$path.py"; return; fi
    [ "${rest%.*}" = "$rest" ] && return
    rest=${rest%.*}
  done
}

# The configurator modules in a file or folder, as dotted labels.
configurator_modules() { # path
  local file
  while IFS= read -r file; do
    case "$file" in */aisc_backend/tests/integration/*) continue ;; esac
    if grep -qE "$CONFIGURATOR_MARK" "$file" && ! grep -qE "$SUPERUSER_MARK" "$file"; then
      file=${file#"$BACKEND"/}
      file=${file%.py}
      printf '%s\n' "$file" | tr / .
    fi
  done < <(if [ -d "$1" ]; then find "$1" -name 'test_*.py' -type f; else printf '%s\n' "$1"; fi)
}

# the caller's labels and files, then the options for manage.py test
given=()
options=()
for arg in "$@"; do
  case "$arg" in
    *.py|*/*)
      arg=${arg#"$BACKEND"/}
      arg=${arg#apps/backend/}
      arg=${arg%.py}
      given+=("$(printf '%s' "$arg" | tr / .)") ;;
    aisc_backend.*) given+=("$arg") ;;
    *) options+=("$arg") ;;
  esac
done
for label in ${given[@]+"${given[@]}"}; do
  if [ -z "$(label_path "$label")" ]; then
    echo "engine-tests: $label names no test module of the engine" >&2
    exit 2
  fi
done

labels=()
if [ ${#given[@]} -gt 0 ]; then
  labels=("${given[@]}")
elif [ $postgres = 0 ]; then
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
if [ ${#given[@]} -eq 0 ]; then
  sorted=()   # sorted with a read loop, which bash 3.2 (macOS) also has
  while IFS= read -r label; do sorted+=("$label"); done < <(printf '%s\n' "${labels[@]}" | LC_ALL=C sort)
  labels=("${sorted[@]}")
fi

if [ $postgres = 0 ]; then
  # the configurator pass: the configurator modules among the labels, each once, sorted
  configurator=()
  while IFS= read -r label; do [ -n "$label" ] && configurator+=("$label"); done < <(
    for label in "${labels[@]}"; do configurator_modules "$(label_path "$label")"; done | LC_ALL=C sort -u)

  db_folder=$(mktemp -d)
  trap 'rm -rf "$db_folder"' EXIT
  cd "$BACKEND"
  status=0
  env -u DATABASE_URL -u AISC_DEPLOYMENT \
    DB_ENGINE=django.db.backends.sqlite3 DB_NAME="$db_folder/engine-tests.db" \
    "${RUNNER[@]}" "${labels[@]}" ${options[@]+"${options[@]}"} || status=$?
  if [ ${#configurator[@]} -gt 0 ]; then
    configurator_status=0
    env -u DATABASE_URL AISC_DEPLOYMENT=configurator \
      DB_ENGINE=django.db.backends.sqlite3 DB_NAME="$db_folder/engine-configurator-tests.db" \
      "${RUNNER[@]}" "${configurator[@]}" ${options[@]+"${options[@]}"} || configurator_status=$?
    [ $status = 0 ] && status=$configurator_status
  fi
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
  DB_MIGRATE_USER=engine_migrator DB_MIGRATE_PASSWORD=engine_migrator \
  DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
  "${RUNNER[@]}" "${labels[@]}" ${options[@]+"${options[@]}"} 2>&1 | tee "$output" || status=$?
summary=$(grep -E '^(OK|FAILED)( \(|$)' "$output" | tail -1 || true)
rm -f "$output"
if [[ "$summary" =~ skipped=([0-9]+) ]]; then
  echo "engine-tests: ${BASH_REMATCH[1]} database tests skipped: the throwaway database did not reach them" >&2
  exit 1
fi
exit $status
