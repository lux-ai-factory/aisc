#!/usr/bin/env bash
# The pipeline, step 1 to step 6, on one throwaway database (pipeline 2026-09-23, 03 WP12).
#
#   scripts/test-pipeline-chain.sh                 # the whole chain; exit 0 when every step passes
#   scripts/test-pipeline-chain.sh --break <link>  # break one link; exit 0 when the run fails at
#                                                  # the step that consumes it (S12.2)
#
# Links: qualification_fk, co_fk, engine_stamp, controls_stamp, card_component.
#
# One postgres:14-alpine container (scripts/lib/throwaway-pg.sh) with every migration at HEAD
# (platform, qualification, engine, control-objectives) and, before step 5, the project's own
# database with the platform template and the controls migrations. The container is removed on
# exit (S12.3). Never the host's 5432, never `docker compose`.
#
# Each step runs the tests of one module that carry the chain tag, selected by name:
#   pytest (platform, control-objectives):  -m chain -k chain_step<N>
#   vitest (qualification, controls):       -t chain_step<N>
#   Django (engine):                        manage.py test aisc_backend --tag chain -k chain_step<N>
# They share ids through $CHAIN_JSON (a JSON object; each step reads what earlier steps wrote and
# adds its own keys: project_pid, v1_pid, v2_pid, card_v1_id, assessment_v1_id, plugin_id,
# evaluation_pid, checklist_id, submission_id). Every step also gets CHAIN_PORT, CHAIN_SU_DSN
# (superuser on the platform database), CHAIN_BREAK and the module's usual test DSN variable,
# pointed at the throwaway database. A step whose module has no chain test yet FAILS with
# "MISSING chain test"; a check that did not run is not a check that passed.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TPG_OWN_TRAP=1
. "$ROOT/scripts/lib/throwaway-pg.sh"

BREAK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --break) BREAK=${2:-}; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
# the step that consumes each link
declare -A CONSUMER=([qualification_fk]=2 [card_component]=3 [co_fk]=3 [engine_stamp]=8 [controls_stamp]=8)
if [ -n "$BREAK" ] && [ -z "${CONSUMER[$BREAK]:-}" ]; then
  echo "unknown link: $BREAK (one of: ${!CONSUMER[*]})" >&2; exit 2
fi

SCRATCH=${CHAIN_SCRATCH:-$(mktemp -d "${TMPDIR:-/tmp}/pipeline-chain.XXXXXX")}
mkdir -p "$SCRATCH"
export CHAIN_JSON=$SCRATCH/chain.json
trap 'tpg_cleanup' EXIT
trap 'tpg_cleanup; exit 130' INT
trap 'tpg_cleanup; exit 143' TERM

BACKEND=$ROOT/apps/backend
SHARED_PYTHONPATH=$ROOT/shared/plugin-interface/src:$ROOT/shared/plugin-manager/src

tpg_start chain || { echo "CHAIN FAIL at setup: throwaway postgres did not start"; exit 1; }
echo "container: $TPG_NAME"
export CHAIN_PORT=$PORT CHAIN_BREAK=$BREAK
export CHAIN_CONTAINER=$TPG_NAME
export CHAIN_SU_DSN="postgresql://${TPG_SU}:${TPG_PW}@127.0.0.1:${PORT}/platform"
python3 -c "import json,sys; json.dump({'port': int(sys.argv[1]), 'container': sys.argv[2], 'break': sys.argv[3] or None}, open(sys.argv[4], 'w'))" \
  "$PORT" "$TPG_NAME" "$BREAK" "$CHAIN_JSON"

setup() {
  tpg_init_platform "$ROOT" || return 1
  local f
  for f in $(ls "$ROOT/platform/migrations" | sort); do tpg_platform_migration platform "$ROOT/platform/migrations/$f" || return 1; done
  (cd "$ROOT/apps/qualification" && DATABASE_URL="$(tpg_dsn qualification_rw platform)?schema=qualification" \
     node_modules/.bin/prisma migrate deploy) || return 1
  (cd "$BACKEND" && DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw \
     DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
     PYTHONPATH="$SHARED_PYTHONPATH" .venv/bin/python manage.py migrate --noinput) || return 1
  (cd "$ROOT/apps/control-objectives" && \
     DATABASE_URL="postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/platform" \
     uv run --quiet alembic upgrade head) || return 1
}

# The project's own database, as the platform provisions it: made by platform_rw, the template
# applied, then the controls migrations as controls_rw.
project_database() {
  local pid hex db f
  pid=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('project_pid') or '')" "$CHAIN_JSON")
  [ -n "$pid" ] || { echo "no project_pid in $CHAIN_JSON (step 1 writes it)"; return 1; }
  hex=${pid//-/}; db=project_$hex
  if [ -z "$(tpg_su postgres -tA -c "SELECT 1 FROM pg_database WHERE datname = '$db'")" ]; then
    tpg_as postgres platform_rw -c "CREATE DATABASE \"$db\"" || return 1
  fi
  for f in $(ls "$ROOT/platform/project-template" | sort); do
    tpg_as "$db" platform_rw -f - < "$ROOT/platform/project-template/$f" >/dev/null || return 1
  done
  (cd "$ROOT/apps/controls" && DATABASE_URL="$(tpg_dsn controls_rw "$db")?schema=controls" \
     node_modules/.bin/prisma migrate deploy) || return 1
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); d['project_db']=sys.argv[2]; json.dump(d, open(sys.argv[1],'w'))" "$CHAIN_JSON" "$db"
}

# step N -> command (run from the repo root); a runner exit status and output are judged below
step_cmd() {
  local n=$1
  local plat="cd platform && PLATFORM_TEST_DATABASE_URL=$(tpg_dsn platform_rw platform) uv run --extra dev pytest -q -p no:cacheprovider -m chain -k chain_step$n"
  local ctrl="cd apps/controls && PROJECT_DATABASE_URL='postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls' npx vitest run -t chain_step$n"
  case $n in
    1|6) echo "$plat" ;;
    2) echo "cd apps/qualification && DATABASE_URL='$(tpg_dsn qualification_rw platform)?schema=qualification' npx vitest run -t chain_step$n" ;;
    3) echo "cd apps/control-objectives && CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/platform uv run pytest -q -p no:cacheprovider -m chain -k chain_step$n" ;;
    4) echo "cd apps/backend && DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT=$PORT DB_SCHEMA=engine PYTHONPATH=$SHARED_PYTHONPATH .venv/bin/python manage.py test aisc_backend --tag chain -k chain_step$n" ;;
    5|7) echo "$ctrl" ;;
    8) echo "uv run --quiet --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/pipeline_chain/test_dashboard_queries.py" ;;
  esac
}
STEP_NAME=([1]="platform: project and v1" [2]="qualification: card v1 with 2 card_component rows"
  [3]="control-objectives: assessment on v1" [4]="engine: plugin with catalogue_slug, evaluation stamped v1"
  [5]="controls: checklist with catalogueId" [6]="platform: v2" [7]="controls: an answer stamped v2"
  [8]="dashboard: the two WP11 dataset queries")

# Judge a runner's result: passed, failed, or missing (no chain test collected).
judge() { # exit-status output
  local rc=$1 out=$2
  if grep -qE 'no tests ran|collected 0 items|Ran 0 tests|No test files found|No test found' <<<"$out"; then echo missing; return; fi
  if [ "$rc" = 5 ]; then echo missing; return; fi     # pytest: nothing collected
  if [ "$rc" = 0 ] && ! grep -qE '[0-9]+ passed|^OK|Tests +[0-9]+ passed' <<<"$out"; then echo missing; return; fi
  [ "$rc" = 0 ] && echo passed || echo failed
}

# break a link, at the moment it is made (see the header)
apply_break() { # after-step
  [ -n "$BREAK" ] || return 0
  case "$BREAK:$1" in
    qualification_fk:0) tpg_su platform -c "ALTER TABLE qualification.qualification DROP CONSTRAINT IF EXISTS qualification_system_id_fkey" ;;
    co_fk:0)            tpg_su platform -c "ALTER TABLE control_objectives.project DROP CONSTRAINT IF EXISTS fk_project_system_id_core_system" ;;
    card_component:2)   tpg_su platform -c "DELETE FROM qualification.card_component" ;;
    engine_stamp:4)     tpg_su platform -c "UPDATE engine.evaluation SET system_id = NULL" ;;
    controls_stamp:7)   local db; db=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('project_db') or '')" "$CHAIN_JSON")
                        tpg_su "$db" -c "UPDATE controls.submission_answer SET system_version_pid = NULL, system_version_number = NULL" ;;
  esac
}

finish() { # failing-step
  local at=$1
  if [ -z "$BREAK" ]; then
    if [ "$at" = 0 ]; then echo "CHAIN PASS"; exit 0; fi
    echo "CHAIN FAIL at step $at (${STEP_NAME[$at]:-setup})"; exit 1
  fi
  local want=${CONSUMER[$BREAK]}
  if [ "$at" = "$want" ]; then echo "BREAK $BREAK OK: the run failed at step $at, which consumes the link"; exit 0; fi
  if [ "$at" = 0 ]; then echo "BREAK $BREAK WRONG: the run passed with the link broken"; exit 1; fi
  echo "BREAK $BREAK WRONG: the run failed at step $at (${STEP_NAME[$at]:-setup}), expected step $want"; exit 1
}

if ! setup > "$SCRATCH/setup.log" 2>&1; then
  echo "setup failed ($SCRATCH/setup.log):"; grep -m3 -iE 'error|exception' "$SCRATCH/setup.log"
  finish setup
fi
apply_break 0
for n in 1 2 3 4 5 6 7 8; do
  if [ "$n" = 5 ] && ! project_database > "$SCRATCH/project-db.log" 2>&1; then
    echo "step 5: project database could not be prepared ($SCRATCH/project-db.log)"; finish 5
  fi
  cmd=$(step_cmd $n)
  out=$(cd "$ROOT" && bash -c "$cmd" 2>&1); rc=$?
  printf '%s\n' "$out" > "$SCRATCH/step$n.log"
  verdict=$(judge "$rc" "$out")
  case $verdict in
    passed)  echo "step $n PASS (${STEP_NAME[$n]})" ;;
    missing) echo "step $n FAIL: MISSING chain test chain_step$n (${STEP_NAME[$n]}) ($SCRATCH/step$n.log)"; finish $n ;;
    failed)  echo "step $n FAIL (${STEP_NAME[$n]}) ($SCRATCH/step$n.log)"; printf '%s\n' "$out" | tail -8 | sed 's/^/    /'; finish $n ;;
  esac
  apply_break $n
done
finish 0
