#!/usr/bin/env bash
# Is what must not change still unchanged? (docs/superpowers/pipeline-2026-09-23/03-specs.md)
#
#   scripts/guard-frozen.sh                    # G1..G5
#   scripts/guard-frozen.sh --only G3,G4       # a subset
#   scripts/guard-frozen.sh --reference-only   # build the e34fca3 reference dump, print its path
#   scripts/guard-frozen.sh --orders           # engine 0023, qualification's card versions, platform 0003: all 6 orders
#
# G1  engine schema at HEAD, migrated by migrate_projects into a project database, equals the
#     engine schema at backend e34fca3 up to the two differences of isolation I7.9
# G2  qualification.knowledge_graph and qualification.qualification_risk unchanged since e112001
#     (the candidate's are made in a project database)
# G3  the vendored AIRO/VAIR files hash as pinned
# G4  Sean's files of 2026-09-23 byte-identical (backend e34fca3, webapp 429f62c, after the
#     isolation's named edits are taken out), eval changed only in the isolation's worker files,
#     plugin-interface without new commits, plugin-manager clean
# G5  engine models unchanged, makemigrations has nothing to make
#
# Every database is a throwaway postgres:14-alpine container (scripts/lib/throwaway-pg.sh) on a
# port the kernel picks, removed on exit. Since the isolation (2026-09-25, I7.12, I19.2) the
# candidate's engine and qualification tables are made where the stack makes them: in a project
# database (tpg_project_db, then manage.py migrate_projects and prisma migrate deploy there). The
# reference and the --orders fixture are the pre-isolation shared layout, built from the trees of
# the top-level commit f01288a (03-coding-plan.md G3), since the current init files no longer make
# the module schemas in platform. Dumps are --no-privileges: grants are proven by
# scripts/tests/test_project_grants.py and verify-project-databases.sh I16.1. The host's 5432 (the live stack) is never a target and
# no `docker compose` command is run.
#
# Sources: committed trees (`git archive <rev>`), so other people's uncommitted files do not
# change the verdict. GUARD_SOURCE=worktree reads the working trees instead (to check before
# committing). Outputs go to $GUARD_OUT (default: a fresh mktemp dir), printed at the end.
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
# The reference engines (e34fca3, dfe4120) need their own dependencies (django-allauth, which the
# candidate dropped with 0024), so they run in a virtualenv made once from e34fca3's uv.lock and
# kept in GUARD_CACHE. GUARD_BACKEND_PY, when set, is used for them too.
GUARD_CACHE=${GUARD_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/aisc-guard}
PRISMA=$QUAL/node_modules/.bin/prisma
SOURCE=${GUARD_SOURCE:-head}
# The backend image installs these from ../../shared (dfe4120); the local venv may hold older
# copies, so the checked-out sources come first.
SHARED_PYTHONPATH=$ROOT/shared/plugin-interface/src:$ROOT/shared/plugin-manager/src

# Pinned references
ENGINE_REF=e34fca3          # backend: merge of Sean's work
QUAL_REF=e112001            # qualification before the card-versions migration
WEBAPP_REF=429f62c          # webapp: Sean's files
EVAL_REF=e5b1b0a
PI_REF=97eddea
DOCKERFILE_COMMIT=dfe4120
LIVE_TOP=ad6262f            # top-level commit whose init/ and platform/ are the live shape
LIVE_ENGINE=dfe4120         # backend with 0022, as live
MCAS_PID=1e722ea2-4ce3-47fa-81bf-11a6b53ad679
ENGINE_0023_GLOB='0023_*.py'
PLATFORM_0003=0003_card_versions_in_core_system.sql
QUAL_CARD_VERSIONS=20260923210000_card_versions_point_at_core_system
CO_LIVE_REV=3b91d0e7a52c
ORDERS_TOP_REF=f01288a      # top-level commit before the isolation: --orders runs on its trees

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

# Source trees: references, candidates and the live shape, unpacked under $WORK.
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
  tree "$ROOT" "$(cand_rev)" "$WORK/cand/top" init platform/migrations platform/project-template
  tree "$ROOT" "$LIVE_TOP" "$WORK/live/top" init platform/migrations
  tree "$BACKEND" "$LIVE_ENGINE" "$WORK/live/backend"
}

# --orders: the pre-isolation trees (the backend and qualification commits of f01288a's gitlinks).
# Its E and Q steps cannot run on the isolated candidate: the engine's default database is a dummy
# there, and qualification's card-versions migration was folded into the project baseline.
prepare_order_trees() {
  [ -d "$WORK/ord" ] && return 0
  tree "$ROOT" "$ORDERS_TOP_REF" "$WORK/ord/top" init platform/migrations
  tree "$BACKEND" "$(git -C "$ROOT" rev-parse "$ORDERS_TOP_REF:apps/backend")" "$WORK/ord/backend"
  tree "$QUAL" "$(git -C "$ROOT" rev-parse "$ORDERS_TOP_REF:apps/qualification")" "$WORK/ord/qualification" prisma
  tree "$CO" "$(git -C "$ROOT" rev-parse "$ORDERS_TOP_REF:apps/control-objectives")" "$WORK/ord/co" alembic alembic.ini src
}

reference_python() { # prints the python of the reference engines, making its virtualenv once
  if [ -n "${GUARD_BACKEND_PY:-}" ]; then echo "$GUARD_BACKEND_PY"; return 0; fi
  local venv="$GUARD_CACHE/backend-$ENGINE_REF"
  if [ ! -x "$venv/bin/python" ]; then
    mkdir -p "$GUARD_CACHE"
    local tmp="$venv.tmp.$$"
    rm -rf "$tmp"
    (cd "$WORK/ref/backend" && uv export --frozen --no-dev --no-emit-project --no-hashes) \
      | grep -v -e '^-e ' -e '^ *#' > "$WORK/reference-requirements.txt" || return 1
    uv venv -q --python 3.12 "$tmp" >&2 || return 1
    uv pip install -q --python "$tmp/bin/python" -r "$WORK/reference-requirements.txt" >&2 || return 1
    mv "$tmp" "$venv" 2>/dev/null || rm -rf "$tmp"   # another run made it meanwhile
  fi
  echo "$venv/bin/python"
}

# Migration steps against the throwaway "platform" database. ENGINE_PY picks the python.
engine_migrate() { # tree [app target]
  local t=$1; shift
  (cd "$t" && DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw \
     DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
     PYTHONPATH="$SHARED_PYTHONPATH" "${ENGINE_PY:-$PY}" manage.py migrate --noinput "$@")
}
prisma_deploy() { # tree [database]
  DATABASE_URL="$(tpg_dsn qualification_rw "${2:-platform}")?schema=qualification" \
    "$PRISMA" migrate deploy --schema "$1/prisma/schema.prisma"
}
platform_migrations() { # tree [names...]; default every file
  local t=$1; shift; local f
  if [ $# -eq 0 ]; then set -- $(ls "$t/platform/migrations" | sort); fi
  for f in "$@"; do tpg_platform_migration platform "$t/platform/migrations/$f" || return 1; done
}
# Schema dumps without privileges, and without the schema's own lines (its owner and comment
# differ by design: platform_rw owns a project database's module schemas).
engine_dump() { # db
  tpg_dump "$1" --schema-only --schema=engine --no-privileges \
    | grep -v -E '^(CREATE SCHEMA|ALTER SCHEMA|COMMENT ON SCHEMA) |^-- Name: (SCHEMA )?engine; Type: (SCHEMA|COMMENT); Schema: -; Owner: '
}
airo_dump() { # db
  tpg_dump "$1" --schema-only --no-privileges -t qualification.knowledge_graph -t qualification.qualification_risk
}
# The two differences isolation I7.9 makes in the engine's definitions (migration 0025): no foreign
# key from engine.project(project_id) to core.project, and the evaluation's system_id key points
# at project.system(pid) instead of core.system(pid), same ON DELETE.
normalise_reference() { # reference-dump -> stdout
  python3 - "$1" <<'NORM'
import re, sys
text = open(sys.argv[1]).read()
blocks = text.split("\n\n")
out = []
for b in blocks:
    if re.search(r"ALTER TABLE ONLY engine\.project\s+ADD CONSTRAINT \w+ FOREIGN KEY \(project_id\) REFERENCES core\.project", b):
        # the comment header pg_dump writes above it goes too
        if out and out[-1].lstrip().startswith("--") and "FK CONSTRAINT" in out[-1]:
            out.pop()
        continue
    out.append(b.replace("REFERENCES core.system(pid)", "REFERENCES project.system(pid)"))
sys.stdout.write("\n\n".join(out))
NORM
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
  tpg_init_platform "$WORK/live/top" || return 1
  snapshot pristine
  platform_migrations "$WORK/live/top" 0001_project_membership.sql 0002_one_ai_system_per_project.sql >"$OUT/ref.log" 2>&1 || return 1
  prisma_deploy "$WORK/ref/qualification" >>"$OUT/ref.log" 2>&1 || return 1
  local ref_py
  ref_py=$(reference_python 2>>"$OUT/ref.log") || return 1
  ENGINE_PY=$ref_py engine_migrate "$WORK/ref/backend" >>"$OUT/ref.log" 2>&1 || return 1
  engine_dump platform > "$OUT/engine.reference.sql"
  airo_dump platform > "$OUT/airo.reference.sql"
  echo "reference dump: $OUT/engine.reference.sql"
}

build_candidate() {
  # A fresh platform made by the candidate's own init files and migrations, one project, its
  # database made as the platform makes it, then each module's own migrate step in it.
  tpg_su postgres -c "DROP DATABASE platform WITH (FORCE)" >/dev/null
  tpg_su postgres -c "CREATE DATABASE platform" >/dev/null
  : > "$OUT/cand.log"
  tpg_init_platform "$WORK/cand/top" >>"$OUT/cand.log" 2>&1 || echo "candidate init failed" >> "$OUT/candidate.errors"
  platform_migrations "$WORK/cand/top" >>"$OUT/cand.log" 2>&1 || echo "platform migrations failed" >> "$OUT/candidate.errors"
  tpg_as platform platform_rw -c "INSERT INTO core.project (pid, name, slug) VALUES ('$MCAS_PID', 'MCAS', 'mcas')" \
    >>"$OUT/cand.log" 2>&1 || echo "core.project row failed" >> "$OUT/candidate.errors"
  local db
  db=$(tpg_project_db "$MCAS_PID" "$WORK/cand/top/platform/project-template" 2>>"$OUT/cand.log") \
    || { echo "project database failed" >> "$OUT/candidate.errors"; db=project_${MCAS_PID//-/}; }
  prisma_deploy "$WORK/cand/qualification" "$db" >>"$OUT/cand.log" 2>&1 || echo "qualification migrations failed" >> "$OUT/candidate.errors"
  # migrate_projects (aisc_backend/deployment.py) only migrates a database per project in
  # configurator mode: the Configurator is what this guard checks, so it says so.
  (cd "$WORK/cand/backend" && AISC_DEPLOYMENT=configurator \
     DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw \
     DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_SCHEMA=engine \
     PYTHONPATH="$SHARED_PYTHONPATH" "$PY" manage.py migrate_projects) >>"$OUT/cand.log" 2>&1 \
    || echo "engine migrate_projects failed" >> "$OUT/candidate.errors"
  engine_dump "$db" > "$OUT/engine.candidate.sql"
  airo_dump "$db" > "$OUT/airo.candidate.sql"
}

why() { # summary of missing pieces and failed steps
  cat "$OUT/candidate.missing" "$OUT/candidate.errors" 2>/dev/null | tr '\n' ';'
}

g1() {
  normalise_reference "$OUT/engine.reference.sql" > "$OUT/engine.reference.normalised.sql"
  if diff -u "$OUT/engine.reference.normalised.sql" "$OUT/engine.candidate.sql" > "$OUT/g1.diff"; then
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

# What a base is compared with: HEAD, or nothing (the working tree) when GUARD_SOURCE=worktree.
cand_head() { [ "$SOURCE" = worktree ] || echo HEAD; }
diff_quiet() { # repo base paths...
  local repo=$1 base=$2; shift 2
  git -C "$repo" diff --quiet "$base" $(cand_head) -- "$@"
}
changed_names() { # repo base paths...
  local repo=$1 base=$2; shift 2
  git -C "$repo" diff --name-only "$base" $(cand_head) -- "$@"
}

sean_backend_files() {
  git -C "$BACKEND" log --author=seanblevins --since=2026-09-23T00:00 --until=2026-09-24T00:00 \
    --name-only --format= "$ENGINE_REF" | sort -u | while read -r f; do
      [ -n "$f" ] && git -C "$BACKEND" cat-file -e "$ENGINE_REF:$f" 2>/dev/null && echo "$f"
    done
}
# Files the backend may add or change on top of $ENGINE_REF. Tests are checked separately:
# Sean's must be identical, new ones are allowed. The isolation's files (E1, E2; I7.12) are
# named one by one.
backend_allowed() {
  case "$1" in
    aisc_backend/migrations/0022_parts_belong_to_a_version_of_the_one_system.py) return 0 ;;
    aisc_backend/migrations/0023_*.py) return 0 ;;
    aisc_backend/repositories/system_version_repository.py) return 0 ;;
    aisc_backend/signals/*) return 0 ;;
    aisc_backend/apps.py) return 0 ;;
    aisc_backend/tests/*) return 0 ;;
  esac
  isolation_allowed "$1"
}
# The isolation's backend files (04-E1-notes.md and 04-E2-notes.md, "For V1").
isolation_allowed() {
  case "$1" in
    config/settings.py|config/settings_single_database.py) return 0 ;;
    aisc_backend/projectdb.py|aisc_backend/project_door.py) return 0 ;;
    aisc_backend/management/__init__.py|aisc_backend/management/commands/__init__.py) return 0 ;;
    aisc_backend/management/commands/migrate_projects.py) return 0 ;;
    aisc_backend/migrations/0025_the_database_is_the_project.py) return 0 ;;
    aisc_backend/auth/membership.py|aisc_backend/platform_projects.py) return 0 ;;
    aisc_backend/repositories/measurement_repository.py) return 0 ;;
    aisc_backend/services/celery_service.py) return 0 ;;
  esac
  return 1
}
# Sean's files the isolation may change (I7.12): the project database settings.
SEAN_ISOLATION_FILES=" config/settings.py "
# The isolation's worker files in apps/eval (E2: the run ticket).
EVAL_ISOLATION_FILES=" aisc_eval/service/api_client.py aisc_eval/celery_tasks.py tests/test_run_ticket.py "

# A file as the candidate has it (HEAD, or the working tree with GUARD_SOURCE=worktree).
cand_file() { # repo path
  if [ "$SOURCE" = worktree ]; then cat "$1/$2"; else git -C "$1" show "HEAD:$2"; fi
}
# Sean's webapp file with the isolation's edits taken out (E2, T7): apiFetch( back to fetch(, the
# one import of projectHeader and every line tagged // I7.4 (isolation) removed.
webapp_without_isolation() { # path
  cand_file "$ROOT/apps/webapp" "$1" \
    | sed -e 's/apiFetch(/fetch(/g' \
    | grep -v -E '^import \{ apiFetch \} from "(\./|\.\./|\.\./\.\./)(api/)?projectHeader";$' \
    | grep -v -E '// I7\.4 \(isolation\)$'
}
# The backend Dockerfile up to its CMD block (the block from "# Default command" on).
before_cmd() { sed '/^# Default command/,$d'; }

g4() {
  local ok=1 f bad="" sean
  # Sean's backend files: byte-identical to e34fca3 (including routers/evaluation.py and
  # models/evaluation.py), except the ones the isolation must change
  sean=$(sean_backend_files)
  for f in $sean; do
    case "$SEAN_ISOLATION_FILES" in *" $f "*) continue ;; esac
    diff_quiet "$BACKEND" "$ENGINE_REF" "$f" || bad="$bad $f"
  done
  if [ -n "$bad" ]; then ok=0; fail G4 "backend: Sean's files differ from $ENGINE_REF:$bad"; fi
  bad=""
  for f in $(changed_names "$BACKEND" "$ENGINE_REF" aisc_backend config); do
    backend_allowed "$f" || bad="$bad $f"
  done
  if [ -n "$bad" ]; then ok=0; fail G4 "backend: files outside the allowed set differ from $ENGINE_REF:$bad"; fi
  # Dockerfile: exactly dfe4120's change up to the CMD block; the CMD block (isolation I7.6) runs
  # no migration but migrate_projects
  local want got cmd
  want=$(git -C "$BACKEND" show "$DOCKERFILE_COMMIT:Dockerfile" | before_cmd)
  got=$(cand_file "$BACKEND" Dockerfile | before_cmd)
  if [ "$want" != "$got" ]; then ok=0; fail G4 "backend: Dockerfile differs from $ENGINE_REF by more than $DOCKERFILE_COMMIT"; fi
  cmd=$(cand_file "$BACKEND" Dockerfile | sed -n '/^# Default command/,$p' | grep -v '^#')
  if grep -qE 'manage\.py migrate($|[^_])' <<<"$cmd"; then ok=0; fail G4 "backend: the Dockerfile's CMD still migrates"; fi
  # Webapp: Sean's files of 2026-09-23, after the isolation's named edits are taken out
  local web=(src/api/api.tsx src/components/AISystemSettings.tsx src/components/plugin/PluginConfigForm.tsx
    src/components/plugin/PluginEvaluationForm.tsx src/components/plugin/PluginEvaluationForm.test.tsx
    src/models/models.tsx src/pages/PluginsConfig.tsx src/pages/PluginStartEvaluation.tsx
    src/pages/PluginStartEvaluation.test.tsx src/pages/Settings.tsx)
  bad=""
  for f in "${web[@]}"; do
    [ "$(webapp_without_isolation "$f")" = "$(git -C "$ROOT/apps/webapp" show "$WEBAPP_REF:$f")" ] || bad="$bad $f"
  done
  if [ -n "$bad" ]; then ok=0; fail G4 "webapp: Sean's files differ from $WEBAPP_REF:$bad"; fi
  # apps/eval: only the isolation's worker files changed since $EVAL_REF
  bad=""
  for f in $(changed_names "$ROOT/apps/eval" "$EVAL_REF"); do
    case "$EVAL_ISOLATION_FILES" in *" $f "*) ;; *) bad="$bad $f" ;; esac
  done
  [ -z "$bad" ] || { ok=0; fail G4 "apps/eval: files other than the isolation's differ from $EVAL_REF:$bad"; }
  local n
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

# Migration orders (--orders): engine 0023 (E), qualification's card versions (Q) and platform
# 0003 (P), applied in every order on a live-shaped fixture. A historical regression since the
# isolation: the three steps are those of the pre-isolation trees ($ORDERS_TOP_REF).
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
  ENGINE_PY=$(reference_python) engine_migrate "$WORK/live/backend" || return 1
  # control objectives as it was before the isolation (its alembic now refuses `platform`)
  (cd "$WORK/ord/co" && DATABASE_URL="postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:$PORT/platform" \
     PYTHONPATH="$WORK/ord/co/src" "$CO/.venv/bin/python" -m alembic upgrade "$CO_LIVE_REV") || return 1
}

step() { # E|Q|P -> run that step on "platform"
  case "$1" in
    E) ls "$WORK/ord/backend/aisc_backend/migrations/"$ENGINE_0023_GLOB >/dev/null 2>&1 \
         || { echo "MISSING engine $ENGINE_0023_GLOB"; return 1; }
       local m; m=$(basename "$(ls "$WORK/ord/backend/aisc_backend/migrations/"$ENGINE_0023_GLOB | head -1)" .py)
       engine_migrate "$WORK/ord/backend" aisc_backend "$m" ;;
    Q) [ -d "$WORK/ord/qualification/prisma/migrations/$QUAL_CARD_VERSIONS" ] \
         || { echo "MISSING qualification $QUAL_CARD_VERSIONS"; return 1; }
       prisma_deploy "$WORK/ord/qualification" ;;
    P) [ -f "$WORK/ord/top/platform/migrations/$PLATFORM_0003" ] \
         || { echo "MISSING platform $PLATFORM_0003"; return 1; }
       platform_migrations "$WORK/ord/top" "$PLATFORM_0003" ;;
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
  prepare_order_trees
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
    tpg_su platform -f - < "$WORK/ord/top/init/project-databases.sql" >/dev/null 2>&1 || true   # postgres-setup
    local steps_ok=1 x out
    for x in $(echo "$o" | grep -o .); do
      if ! out=$(step "$x" 2>&1); then steps_ok=0; echo "order $o: step $x failed: $(echo "$out" | grep -m1 -iE 'missing|error|exception' )"; fi
    done
    engine_dump platform > "$OUT/engine.order-$o.sql"
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
  # S4.4: without the ownership fix, E and Q pass and P fails on core.system's owner; after the
  # fix P succeeds on a re-run.
  restore fixture
  local e q p1 p2 rec
  e=$(step E 2>&1); local es=$?
  q=$(step Q 2>&1); local qs=$?
  p1=$(step P 2>&1); local ps=$?
  rec=$(tpg_su platform -tA -c "SELECT count(*) FROM core.schema_migration WHERE name = '$PLATFORM_0003'" 2>&1)
  tpg_su platform -f - < "$WORK/ord/top/init/project-databases.sql" >/dev/null 2>&1
  p2=$(step P 2>&1); local p2s=$?
  if [ $es = 0 ] && [ $qs = 0 ] && [ $ps != 0 ] && grep -q "core.system must be owned by platform_rw" <<<"$p1" \
     && [ "$rec" = 0 ] && [ $p2s = 0 ]; then
    pass S4.4
  else
    fail S4.4 "E=$es Q=$qs P(before fix)=$ps recorded=$rec P(after fix)=$p2s; $(echo "$p1" | grep -m1 -iE 'missing|error|exception')"
  fi
}

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
