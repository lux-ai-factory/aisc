#!/usr/bin/env bash
# Is what must not change still unchanged? (pipeline 2026-09-23, 03 "Guard spec")
#
#   scripts/guard-frozen.sh                    # G1..G5
#   scripts/guard-frozen.sh --only G3,G4       # a subset
#   scripts/guard-frozen.sh --reference-only   # build the e34fca3 reference dump, print its path
#   scripts/guard-frozen.sh --orders           # WP4: 0023 / WP3 prisma / platform 0003 in all 6 orders
#
# G1  engine schema at HEAD equals the engine schema at backend e34fca3
# G2  qualification.knowledge_graph and qualification.qualification_risk unchanged since e112001
# G3  the vendored AIRO/VAIR files hash as pinned
# G4  Sean's files of 2026-09-23 byte-identical (backend e34fca3, webapp 429f62c), eval and
#     plugin-interface without new commits, plugin-manager clean
# G5  engine models unchanged, makemigrations has nothing to make
#
# Every database is a throwaway postgres:14-alpine container (scripts/lib/throwaway-pg.sh) on a
# port the kernel picks, removed on exit. The host's 5432 (the live stack) is never a target and
# no `docker compose` command is run.
#
# Sources: committed trees (`git archive <rev>`), so other people's uncommitted files do not
# change the verdict. GUARD_SOURCE=worktree reads the working trees instead (for stage 5 before
# a commit). Outputs go to $GUARD_OUT (default: a fresh mktemp dir), printed at the end.
#
# Exit status: 0 when every selected check passes, 1 otherwise.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TPG_OWN_TRAP=1
. "$ROOT/scripts/lib/throwaway-pg.sh"

MODE=all; ONLY="G1,G2,G3,G4,G5"
while [ $# -gt 0 ]; do
  case "$1" in
    --reference-only) MODE=reference ;;
    --orders) MODE=orders ;;
    --only) ONLY=$2; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

BACKEND=$ROOT/apps/backend
QUAL=$ROOT/apps/qualification
CO=$ROOT/apps/control-objectives
PY=${GUARD_BACKEND_PY:-$BACKEND/.venv/bin/python}   # overridable only so a test can force a failure
PRISMA=$QUAL/node_modules/.bin/prisma
SOURCE=${GUARD_SOURCE:-head}
# The backend image installs these from ../../shared (dfe4120); the local venv may hold older
# copies, so the checked-out sources come first.
SHARED_PYTHONPATH=$ROOT/shared/plugin-interface/src:$ROOT/shared/plugin-manager/src

# Pinned references (03 Guard spec)
ENGINE_REF=e34fca3          # backend: merge of Sean's work
QUAL_REF=e112001            # qualification before WP3
WEBAPP_REF=429f62c          # webapp: Sean's files
EVAL_REF=e5b1b0a
PI_REF=97eddea
DOCKERFILE_COMMIT=dfe4120
LIVE_TOP=ad6262f            # top-level commit whose init/ and platform/ are the live shape
LIVE_ENGINE=dfe4120         # backend with 0022, as live
MCAS_PID=1e722ea2-4ce3-47fa-81bf-11a6b53ad679
ENGINE_0023_GLOB='0023_*.py'
PLATFORM_0003=0003_card_versions_in_core_system.sql
QUAL_WP3=20260923210000_card_versions_point_at_core_system
CO_LIVE_REV=3b91d0e7a52c

OUT=${GUARD_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/guard-frozen.XXXXXX")}
mkdir -p "$OUT"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/guard-work.XXXXXX")
cleanup_all() { tpg_cleanup; rm -rf "$WORK"; }
trap 'cleanup_all' EXIT
trap 'cleanup_all; exit 130' INT
trap 'cleanup_all; exit 143' TERM

FAILED=0
pass() { echo "$1 PASS${2:+ $2}"; }
fail() { echo "$1 FAIL: $2"; FAILED=1; }
selected() { case ",$ONLY," in *",$1,"*) return 0 ;; esac; return 1; }
log() { echo "[guard] $*" >&2; }

# --- trees ---------------------------------------------------------------------------------
tree() { # repo-dir rev dest [paths...]
  local repo=$1 rev=$2 dest=$3; shift 3
  mkdir -p "$dest"
  if [ "$rev" = "WORKTREE" ]; then
    (cd "$repo" && tar -c --exclude=node_modules --exclude=.venv --exclude=__pycache__ "${@:-.}") | tar -x -C "$dest"
  else
    git -C "$repo" archive "$rev" "$@" | tar -x -C "$dest"
  fi
}
cand_rev() { [ "$SOURCE" = worktree ] && echo WORKTREE || echo HEAD; }

prepare_trees() {
  [ -d "$WORK/ref" ] && return 0
  tree "$BACKEND" "$ENGINE_REF" "$WORK/ref/backend"
  tree "$QUAL" "$QUAL_REF" "$WORK/ref/qualification" prisma
  tree "$BACKEND" "$(cand_rev)" "$WORK/cand/backend"
  tree "$QUAL" "$(cand_rev)" "$WORK/cand/qualification" prisma
  tree "$ROOT" "$(cand_rev)" "$WORK/cand/top" init platform/migrations
  tree "$ROOT" "$LIVE_TOP" "$WORK/live/top" init platform/migrations
  tree "$BACKEND" "$LIVE_ENGINE" "$WORK/live/backend"
}

# --- steps against the throwaway "platform" database ----------------------------------------
engine_migrate() { # tree [app target]
  local t=$1; shift
  (cd "$t" && DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw \
     DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
     PYTHONPATH="$SHARED_PYTHONPATH" "$PY" manage.py migrate --noinput "$@")
}
prisma_deploy() { # tree
  DATABASE_URL="$(tpg_dsn qualification_rw platform)?schema=qualification" \
    "$PRISMA" migrate deploy --schema "$1/prisma/schema.prisma"
}
platform_migrations() { # tree [names...]; default every file
  local t=$1; shift; local f
  if [ $# -eq 0 ]; then set -- $(ls "$t/platform/migrations" | sort); fi
  for f in "$@"; do tpg_platform_migration platform "$t/platform/migrations/$f" || return 1; done
}
snapshot() { tpg_su postgres -c "DROP DATABASE IF EXISTS \"$1\"" >/dev/null; tpg_copy_db platform "$1"; }
restore() { tpg_su postgres -c "DROP DATABASE platform WITH (FORCE)" >/dev/null; tpg_copy_db "$1" platform; }

start_db() {
  tpg_start guard || { fail G0 "throwaway postgres did not start"; exit 1; }
  echo "container: $TPG_NAME"
}

build_reference() {
  # e34fca3's engine, and e112001's qualification (which needs platform 0002's
  # core.ai_system_version, so 0002 runs here too; it touches no engine table).
  tpg_init_platform "$WORK/cand/top" || return 1
  snapshot pristine
  platform_migrations "$WORK/live/top" 0001_project_membership.sql 0002_one_ai_system_per_project.sql >"$OUT/ref.log" 2>&1 || return 1
  prisma_deploy "$WORK/ref/qualification" >>"$OUT/ref.log" 2>&1 || return 1
  engine_migrate "$WORK/ref/backend" >>"$OUT/ref.log" 2>&1 || return 1
  tpg_dump platform --schema-only --schema=engine > "$OUT/engine.reference.sql"
  tpg_dump platform --schema-only -t qualification.knowledge_graph -t qualification.qualification_risk > "$OUT/airo.reference.sql"
  echo "reference dump: $OUT/engine.reference.sql"
}

build_candidate() {
  restore pristine
  local miss=""
  [ -f "$WORK/cand/top/platform/migrations/$PLATFORM_0003" ] || miss="$miss platform/migrations/$PLATFORM_0003"
  ls "$WORK/cand/backend/aisc_backend/migrations/"$ENGINE_0023_GLOB >/dev/null 2>&1 || miss="$miss apps/backend/aisc_backend/migrations/$ENGINE_0023_GLOB"
  [ -d "$WORK/cand/qualification/prisma/migrations/$QUAL_WP3" ] || miss="$miss apps/qualification/prisma/migrations/$QUAL_WP3"
  [ -z "$miss" ] || echo "MISSING:$miss" > "$OUT/candidate.missing"
  : > "$OUT/cand.log"
  platform_migrations "$WORK/cand/top" >>"$OUT/cand.log" 2>&1 || echo "platform migrations failed" >> "$OUT/candidate.errors"
  prisma_deploy "$WORK/cand/qualification" >>"$OUT/cand.log" 2>&1 || echo "qualification migrations failed" >> "$OUT/candidate.errors"
  engine_migrate "$WORK/cand/backend" >>"$OUT/cand.log" 2>&1 || echo "engine migrations failed" >> "$OUT/candidate.errors"
  tpg_dump platform --schema-only --schema=engine > "$OUT/engine.candidate.sql"
  tpg_dump platform --schema-only -t qualification.knowledge_graph -t qualification.qualification_risk > "$OUT/airo.candidate.sql"
}

why() { # summary of missing pieces and failed steps
  cat "$OUT/candidate.missing" "$OUT/candidate.errors" 2>/dev/null | tr '\n' ';'
}

g1() {
  if diff -u "$OUT/engine.reference.sql" "$OUT/engine.candidate.sql" > "$OUT/g1.diff"; then
    pass G1 "(engine schema equals $ENGINE_REF)"
  else
    fail G1 "engine schema differs from $ENGINE_REF ($(grep -c '^[-+][^-+]' "$OUT/g1.diff") lines, $OUT/g1.diff) $(why)"
  fi
}

model_block() { sed -n "/^model $2 {/,/^}/p" <<<"$1"; }
g2() {
  local ok=1 old new m
  if ! diff -u "$OUT/airo.reference.sql" "$OUT/airo.candidate.sql" > "$OUT/g2.diff"; then
    ok=0; fail G2 "knowledge_graph/qualification_risk dump differs ($OUT/g2.diff)"
  fi
  old=$(git -C "$QUAL" show "$QUAL_REF:prisma/schema.prisma")
  if [ "$SOURCE" = worktree ]; then new=$(cat "$QUAL/prisma/schema.prisma"); else new=$(git -C "$QUAL" show HEAD:prisma/schema.prisma); fi
  for m in QualificationRisk KnowledgeGraph; do
    if [ "$(model_block "$old" $m)" != "$(model_block "$new" $m)" ]; then ok=0; fail G2 "model $m changed in schema.prisma"; fi
  done
  [ $ok = 1 ] && pass G2
}

g3() {
  if (cd "$ROOT" && sha256sum -c --quiet - <<'SUMS'
6274d2d8711e046cf38f1b5b2980188094d4aa87b5af79804005a06468fd8469  apps/qualification/services/ontology/airo/airo.ttl
6b42323726e7a82a5c4782a6d9398fc44db21bd4e0ca9fd4807558190c173605  apps/qualification/services/ontology/airo/vair.ttl
a41460bdb536f2073b9ce43e499e817a5fe9032001603c23a5f6adbd0e782b59  apps/qualification/src/data/airo_vocab.json
SUMS
  ) > "$OUT/g3.log" 2>&1; then pass G3 "(hashes)"; else fail G3 "vendored AIRO/VAIR files changed: $(tr '\n' ' ' < "$OUT/g3.log")"; fi
  if [ "${GUARD_G3_PYTEST:-1}" = 1 ]; then
    if docker run --rm -v "$QUAL/services/ontology:/w:ro" -w /w python:3.12-slim sh -c \
        'cp -r /w /t && cd /t && pip install -q -r requirements.txt pytest >/dev/null 2>&1 && python -m pytest -q -p no:cacheprovider tests/test_vendored.py' \
        > "$OUT/g3.pytest.log" 2>&1; then
      pass G3 "(tests/test_vendored.py)"
    else
      fail G3 "services/ontology/tests/test_vendored.py not green ($OUT/g3.pytest.log)"
    fi
  fi
}

diff_quiet() { # repo base paths... ; compares base with HEAD (or the working tree)
  local repo=$1 base=$2; shift 2
  if [ "$SOURCE" = worktree ]; then git -C "$repo" diff --quiet "$base" -- "$@"; else git -C "$repo" diff --quiet "$base" HEAD -- "$@"; fi
}
changed_names() { # repo base paths...
  local repo=$1 base=$2; shift 2
  if [ "$SOURCE" = worktree ]; then git -C "$repo" diff --name-only "$base" -- "$@"; else git -C "$repo" diff --name-only "$base" HEAD -- "$@"; fi
}

sean_backend_files() {
  git -C "$BACKEND" log --author=seanblevins --since=2026-09-23T00:00 --until=2026-09-24T00:00 \
    --name-only --format= "$ENGINE_REF" | sort -u | while read -r f; do
      [ -n "$f" ] && git -C "$BACKEND" cat-file -e "$ENGINE_REF:$f" 2>/dev/null && echo "$f"
    done
}
# Files the pipeline may add or change in the backend (03 WP1, WP9, amendment A1). Tests are
# checked separately: Sean's must be identical, new ones are allowed.
backend_allowed() {
  case "$1" in
    aisc_backend/migrations/0022_parts_belong_to_a_version_of_the_one_system.py) return 0 ;;
    aisc_backend/migrations/0023_*.py) return 0 ;;
    aisc_backend/repositories/system_version_repository.py) return 0 ;;
    aisc_backend/signals/*) return 0 ;;
    aisc_backend/apps.py) return 0 ;;
    aisc_backend/tests/*) return 0 ;;
  esac
  return 1
}

g4() {
  local ok=1 f bad="" sean
  # Sean's backend files: byte-identical to e34fca3 (A1: including routers/evaluation.py and
  # models/evaluation.py)
  sean=$(sean_backend_files)
  for f in $sean; do diff_quiet "$BACKEND" "$ENGINE_REF" "$f" || bad="$bad $f"; done
  if [ -n "$bad" ]; then ok=0; fail G4 "backend: Sean's files differ from $ENGINE_REF:$bad"; fi
  bad=""
  for f in $(changed_names "$BACKEND" "$ENGINE_REF" aisc_backend config); do
    backend_allowed "$f" || bad="$bad $f"
  done
  if [ -n "$bad" ]; then ok=0; fail G4 "backend: files outside the allowed set differ from $ENGINE_REF:$bad"; fi
  # Dockerfile: exactly dfe4120's change
  local want got
  want=$(git -C "$BACKEND" diff "$DOCKERFILE_COMMIT~1" "$DOCKERFILE_COMMIT" -- Dockerfile | grep -v '^index ')
  if [ "$SOURCE" = worktree ]; then got=$(git -C "$BACKEND" diff "$ENGINE_REF" -- Dockerfile | grep -v '^index ');
  else got=$(git -C "$BACKEND" diff "$ENGINE_REF" HEAD -- Dockerfile | grep -v '^index '); fi
  if [ "$want" != "$got" ]; then ok=0; fail G4 "backend: Dockerfile differs from $ENGINE_REF by more than $DOCKERFILE_COMMIT"; fi
  # Webapp: Sean's files of 2026-09-23
  local web=(src/api/api.tsx src/components/AISystemSettings.tsx src/components/plugin/PluginConfigForm.tsx
    src/components/plugin/PluginEvaluationForm.tsx src/components/plugin/PluginEvaluationForm.test.tsx
    src/models/models.tsx src/pages/PluginsConfig.tsx src/pages/PluginStartEvaluation.tsx
    src/pages/PluginStartEvaluation.test.tsx src/pages/Settings.tsx)
  if ! diff_quiet "$ROOT/apps/webapp" "$WEBAPP_REF" "${web[@]}"; then
    ok=0; fail G4 "webapp: Sean's files differ from $WEBAPP_REF: $(changed_names "$ROOT/apps/webapp" "$WEBAPP_REF" "${web[@]}" | tr '\n' ' ')"
  fi
  local n
  n=$(git -C "$ROOT/apps/eval" rev-list --count "$EVAL_REF..HEAD")
  [ "$n" = 0 ] || { ok=0; fail G4 "apps/eval has $n commits after $EVAL_REF"; }
  n=$(git -C "$ROOT/shared/plugin-interface" rev-list --count "$PI_REF..HEAD")
  [ "$n" = 0 ] || { ok=0; fail G4 "shared/plugin-interface has $n commits after $PI_REF"; }
  [ -z "$(git -C "$ROOT/shared/plugin-manager" status --porcelain)" ] || { ok=0; fail G4 "shared/plugin-manager is not clean"; }
  [ $ok = 1 ] && pass G4
}

g5() {
  local ok=1
  diff_quiet "$BACKEND" "$ENGINE_REF" aisc_backend/models || { ok=0; fail G5 "aisc_backend/models differs from $ENGINE_REF: $(changed_names "$BACKEND" "$ENGINE_REF" aisc_backend/models | tr '\n' ' ')"; }
  prepare_trees
  if ! (cd "$WORK/cand/backend" && DB_ENGINE=django.db.backends.sqlite3 DB_NAME="$WORK/g5.db" \
        PYTHONPATH="$SHARED_PYTHONPATH" "$PY" manage.py makemigrations --check --dry-run) > "$OUT/g5.log" 2>&1; then
    ok=0; fail G5 "makemigrations --check reports changes ($OUT/g5.log)"
  fi
  [ $ok = 1 ] && pass G5
}

# --- WP4: migration orders -----------------------------------------------------------------
seed_live_shape() {
  # platform 0001; one project and its system (so 0002 carries it over under the same pid, as
  # it did live); 0002; qualification up to 20260923180000 with the MCAS card, 14 answers and 1
  # risk; engine up to 0022; control-objectives at 3b91d0e7a52c.
  tpg_init_platform "$WORK/live/top" || return 1
  platform_migrations "$WORK/live/top" 0001_project_membership.sql || return 1
  tpg_su platform -c "INSERT INTO core.project (pid, name, slug) VALUES ('00000000-0000-4000-8000-00000000000a', 'MCAS', 'mcas');
    INSERT INTO core.system (pid, project_id, name, version, provider)
      VALUES ('$MCAS_PID', '00000000-0000-4000-8000-00000000000a', 'MCAS', 'v1.2.0', 'LIST');" >/dev/null || return 1
  platform_migrations "$WORK/live/top" 0002_one_ai_system_per_project.sql || return 1
  prisma_deploy "$WORK/ref/qualification" || return 1
  tpg_as platform qualification_rw -c "SET search_path = qualification;
    INSERT INTO qualification (id, project_id, system_id, \"systemName\", \"systemVersion\", company, description,
       \"targetUseCase\", \"targetUsers\", updated_at)
      VALUES ('card-mcas', '00000000-0000-4000-8000-00000000000a', '$MCAS_PID', 'MCAS', 'v1.2.0', 'LIST', 'd', 'u', 'u', now());
    INSERT INTO qualification_answer (id, \"qualificationId\", \"toolId\", \"questionId\", answer)
      SELECT 'a' || g, 'card-mcas', 'tool', 'q' || g, 'yes' FROM generate_series(1, 14) g;
    INSERT INTO qualification_risk (id, \"qualificationId\", position, risk, source, consequence, affected, control)
      VALUES ('r1', 'card-mcas', 0, 'risk', 'src', 'c', 'a', 'ctl');" >/dev/null || return 1
  engine_migrate "$WORK/live/backend" || return 1
  (cd "$CO" && DATABASE_URL="postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/platform" \
     uv run --quiet alembic upgrade "$CO_LIVE_REV") || return 1
}

step() { # E|Q|P -> run that step on "platform"
  case "$1" in
    E) ls "$WORK/cand/backend/aisc_backend/migrations/"$ENGINE_0023_GLOB >/dev/null 2>&1 \
         || { echo "MISSING engine $ENGINE_0023_GLOB"; return 1; }
       local m; m=$(basename "$(ls "$WORK/cand/backend/aisc_backend/migrations/"$ENGINE_0023_GLOB | head -1)" .py)
       engine_migrate "$WORK/cand/backend" aisc_backend "$m" ;;
    Q) [ -d "$WORK/cand/qualification/prisma/migrations/$QUAL_WP3" ] \
         || { echo "MISSING qualification $QUAL_WP3"; return 1; }
       prisma_deploy "$WORK/cand/qualification" ;;
    P) [ -f "$WORK/cand/top/platform/migrations/$PLATFORM_0003" ] \
         || { echo "MISSING platform $PLATFORM_0003"; return 1; }
       platform_migrations "$WORK/cand/top" "$PLATFORM_0003" ;;
  esac
}

s43_check() { # prints problems, empty when S4.3 holds
  local card num ans
  card=$(tpg_su platform -tA -c "SELECT system_id FROM qualification.qualification WHERE id = 'card-mcas'" 2>&1)
  [ "$card" = "$MCAS_PID" ] || echo "card system_id=$card"
  num=$(tpg_su platform -tA -c "SELECT number FROM core.system WHERE pid = '$MCAS_PID'" 2>&1)
  [ "$num" = 1 ] || echo "core.system number=$num"
  ans=$(tpg_su platform -tA -c "SELECT count(*) FROM qualification.qualification_answer" 2>&1)
  [ "$ans" = 14 ] || echo "answers=$ans"
}

orders() {
  prepare_trees
  start_db
  build_reference > /dev/null || { fail S4 "could not build the reference ($OUT/ref.log)"; return; }
  restore pristine
  tpg_su postgres -c "DROP DATABASE platform WITH (FORCE)" >/dev/null
  tpg_su postgres -c "DROP DATABASE pristine" >/dev/null
  # roles are cluster-wide and already there; the fixture starts from init on an empty database
  tpg_su postgres -c "CREATE DATABASE platform" >/dev/null
  if ! seed_live_shape > "$OUT/fixture.log" 2>&1; then
    fail S4 "live-shaped fixture failed ($OUT/fixture.log)"; return
  fi
  snapshot fixture
  local s41=1 s42=1 s43=1 first="" o dump
  for o in EQP EPQ QEP QPE PEQ PQE; do
    restore fixture
    tpg_su platform -f - < "$WORK/cand/top/init/project-databases.sql" >/dev/null 2>&1 || true   # postgres-setup
    local steps_ok=1 x out
    for x in $(echo "$o" | grep -o .); do
      if ! out=$(step "$x" 2>&1); then steps_ok=0; echo "order $o: step $x failed: $(echo "$out" | grep -m1 -iE 'missing|error|exception' )"; fi
    done
    tpg_dump platform --schema-only --schema=engine > "$OUT/engine.order-$o.sql"
    if diff -q "$OUT/engine.reference.sql" "$OUT/engine.order-$o.sql" >/dev/null && [ $steps_ok = 1 ]; then :; else s41=0; echo "order $o: S4.1 engine dump differs or a step failed"; fi
    tpg_dump platform --schema-only -n core -n qualification > "$OUT/core-qual.order-$o.sql"
    if [ -z "$first" ]; then first=$o; elif ! diff -q "$OUT/core-qual.order-$first.sql" "$OUT/core-qual.order-$o.sql" >/dev/null || [ $steps_ok = 0 ]; then s42=0; echo "order $o: S4.2 core/qualification dump differs from order $first or a step failed"; fi
    [ $steps_ok = 1 ] || s42=0
    local p; p=$(s43_check)
    if [ -n "$p" ] || [ $steps_ok = 0 ]; then s43=0; echo "order $o: S4.3 $(echo $p)"; fi
  done
  [ $s41 = 1 ] && pass S4.1 || fail S4.1 "see order lines above"
  [ $s42 = 1 ] && pass S4.2 || fail S4.2 "see order lines above"
  [ $s43 = 1 ] && pass S4.3 || fail S4.3 "see order lines above"
  # S4.4: without the ownership fix, E and Q pass, P fails with S2.8's message; after the fix
  # P succeeds on a re-run.
  restore fixture
  local e q p1 p2 rec
  e=$(step E 2>&1); local es=$?
  q=$(step Q 2>&1); local qs=$?
  p1=$(step P 2>&1); local ps=$?
  rec=$(tpg_su platform -tA -c "SELECT count(*) FROM core.schema_migration WHERE name = '$PLATFORM_0003'" 2>&1)
  tpg_su platform -f - < "$WORK/cand/top/init/project-databases.sql" >/dev/null 2>&1
  p2=$(step P 2>&1); local p2s=$?
  if [ $es = 0 ] && [ $qs = 0 ] && [ $ps != 0 ] && grep -q "core.system must be owned by platform_rw" <<<"$p1" \
     && [ "$rec" = 0 ] && [ $p2s = 0 ]; then
    pass S4.4
  else
    fail S4.4 "E=$es Q=$qs P(before fix)=$ps recorded=$rec P(after fix)=$p2s; $(echo "$p1" | grep -m1 -iE 'missing|error|exception')"
  fi
}

# --- main ------------------------------------------------------------------------------------
case "$MODE" in
  reference)
    prepare_trees; start_db
    if build_reference; then echo "out: $OUT"; exit 0; else echo "reference build failed ($OUT/ref.log)"; exit 1; fi ;;
  orders)
    orders ;;
  all)
    if selected G1 || selected G2; then
      prepare_trees; start_db
      if build_reference > /dev/null; then
        build_candidate
        selected G1 && g1
        selected G2 && g2
      else
        fail G1 "reference build failed ($OUT/ref.log)"
      fi
    fi
    selected G3 && g3
    selected G4 && g4
    selected G5 && g5 ;;
esac
echo "out: $OUT"
[ $FAILED = 0 ] && echo "GUARD PASS" || echo "GUARD FAIL"
exit $FAILED
