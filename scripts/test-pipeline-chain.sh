#!/usr/bin/env bash
# The pipeline, step 1 to step 8, on one throwaway database (docs/superpowers/pipeline-2026-09-23/03-specs.md).
#
#   scripts/test-pipeline-chain.sh                 # the whole chain; exit 0 when every step passes
#   scripts/test-pipeline-chain.sh --break <link>  # break one link; exit 0 when the run fails at
#                                                  # the step that consumes it
#
# Links: qualification_fk, co_fk, engine_stamp, controls_stamp, card_component.
#
# One postgres:15-alpine container (scripts/lib/throwaway-pg.sh) with the platform's init files
# and migrations at HEAD. Since the isolation (I19.2) every module lives in the project's own
# database: step 1 makes the project through the platform's API (which provisions project_<hex>),
# then tpg_project_db tops its template up and every module's own migrate one-shot runs against
# it (qualification, controls, control objectives, engine, report composer), exactly as
# scripts/tests/isolation_bed.py does. The container is removed on exit. Never the host's 5432,
# never `docker compose`.
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
# the step that consumes each link (qualification_fk and co_fk are broken after step 1, when the
# project database and its tables exist)
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

chain_get() { # key -> its value in $CHAIN_JSON, empty when unset
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]) or '')" "$CHAIN_JSON" "$1"
}

setup() {
  tpg_init_platform "$ROOT" || return 1
  local f
  for f in inspector-role report-roles; do tpg_su platform -f - < "$ROOT/init/$f.sql" >/dev/null || return 1; done
  for f in $(ls "$ROOT/platform/migrations" | sort); do tpg_platform_migration platform "$ROOT/platform/migrations/$f" || return 1; done
}

# The project's own database, after step 1 made it through the platform's API: its template
# topped up (tpg_project_db, idempotent), then each module's migrate one-shot against {database},
# as the stack's -migrate services run them.
migrate_project_database() {
  local pid db
  pid=$(chain_get project_pid)
  [ -n "$pid" ] || { echo "no project_pid in $CHAIN_JSON (step 1 writes it)"; return 1; }
  db=$(tpg_project_db "$pid") || return 1
  (cd "$ROOT/apps/qualification" && \
     PROJECT_DATABASE_URL="postgresql://qualification_rw:qualification_rw@127.0.0.1:$PORT/{database}?schema=qualification&connection_limit=2" \
     node scripts/migrate-projects.mjs) || return 1
  (cd "$ROOT/apps/controls" && \
     PROJECT_DATABASE_URL="postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls" \
     node scripts/migrate-projects.mjs) || return 1
  (cd "$ROOT/apps/control-objectives" && PYTHONPATH="$ROOT/apps/control-objectives/src" \
     DATABASE_URL="postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/platform" \
     PROJECT_DATABASE_URL="postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/{database}" \
     .venv/bin/python -m aisc_control_objectives.migrate_projects) || return 1
  # migrate_projects (aisc_backend/deployment.py) only migrates a database per project in
  # configurator mode, which is what this chain runs the engine as.
  (cd "$BACKEND" && AISC_DEPLOYMENT=configurator \
     DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw \
     DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
     PYTHONPATH="$SHARED_PYTHONPATH" .venv/bin/python manage.py migrate_projects) || return 1
  (cd "$ROOT/apps/report-composer" && PYTHONPATH="$ROOT/apps/report-composer" \
     REPORT_COMPOSER_DATABASE_URL="$(tpg_dsn report_composer_rw platform)" \
     REPORT_COMPOSER_PROJECT_DATABASE_URL="postgresql://report_composer_rw:report_composer_rw@127.0.0.1:$PORT/{database}" \
     .venv/bin/python -m report_composer.migrate) || return 1
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); d['project_db']=sys.argv[2]; json.dump(d, open(sys.argv[1],'w'))" "$CHAIN_JSON" "$db"
}

# step N -> command (run from the repo root); a runner exit status and output are judged below
step_cmd() {
  local n=$1
  local plat="cd platform && PLATFORM_TEST_DATABASE_URL=$(tpg_dsn platform_rw platform) uv run --extra dev pytest -q -p no:cacheprovider -m chain -k chain_step$n"
  local ctrl="cd apps/controls && PROJECT_DATABASE_URL='postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls' npx vitest run -t chain_step$n"
  case $n in
    1|6) echo "$plat" ;;
    2) echo "cd apps/qualification && PROJECT_DATABASE_URL='postgresql://qualification_rw:qualification_rw@127.0.0.1:$PORT/{database}?schema=qualification' npx vitest run -t chain_step$n" ;;
    3) echo "cd apps/control-objectives && DATABASE_URL=postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/platform PROJECT_DATABASE_URL='postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/{database}' uv run pytest -q -p no:cacheprovider -m chain -k chain_step$n" ;;
    # N7: the label narrows the run to the chain module (the whole suite's other DB tests need a test database)
    # The engine runs in configurator mode, as the stack runs it (project databases, the door).
    4) echo "cd apps/backend && AISC_DEPLOYMENT=configurator DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT=$PORT DB_SCHEMA=engine PYTHONPATH=$SHARED_PYTHONPATH .venv/bin/python manage.py test aisc_backend.tests.test_chain --tag chain -k chain_step$n" ;;
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
# The foreign key of a module table into project.system, removed wherever its name.
drop_fk_into_project_system() { # table
  local db; db=$(chain_get project_db)
  tpg_su "$db" -c "DO \$d\$ DECLARE c text; BEGIN
      FOR c IN SELECT conname FROM pg_constraint WHERE contype = 'f' AND conrelid = '$1'::regclass
                  AND confrelid = 'project.system'::regclass LOOP
        EXECUTE format('ALTER TABLE $1 DROP CONSTRAINT %I', c);
      END LOOP; END \$d\$"
}

apply_break() { # after-step
  [ -n "$BREAK" ] || return 0
  local db; db=$(chain_get project_db)
  case "$BREAK:$1" in
    qualification_fk:1) drop_fk_into_project_system qualification.qualification ;;
    co_fk:1)            drop_fk_into_project_system control_objectives.project ;;
    card_component:2)   tpg_su "$db" -c "DELETE FROM qualification.card_component" ;;
    engine_stamp:4)     tpg_su "$db" -c "UPDATE engine.evaluation SET system_id = NULL" ;;
    controls_stamp:7)   tpg_su "$db" -c "UPDATE controls.submission_answer SET system_version_pid = NULL, system_version_number = NULL" ;;
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
for n in 1 2 3 4 5 6 7 8; do
  cmd=$(step_cmd $n)
  out=$(cd "$ROOT" && bash -c "$cmd" 2>&1); rc=$?
  printf '%s\n' "$out" > "$SCRATCH/step$n.log"
  verdict=$(judge "$rc" "$out")
  case $verdict in
    passed)  echo "step $n PASS (${STEP_NAME[$n]})" ;;
    missing) echo "step $n FAIL: MISSING chain test chain_step$n (${STEP_NAME[$n]}) ($SCRATCH/step$n.log)"; finish $n ;;
    failed)  echo "step $n FAIL (${STEP_NAME[$n]}) ($SCRATCH/step$n.log)"; printf '%s\n' "$out" | tail -8 | sed 's/^/    /'; finish $n ;;
  esac
  if [ "$n" = 1 ] && ! migrate_project_database > "$SCRATCH/project-db.log" 2>&1; then
    echo "step 1: the project database could not be migrated ($SCRATCH/project-db.log)"; finish 1
  fi
  apply_break $n
done
finish 0
