#!/usr/bin/env bash
# Is what must not change still unchanged?
#
#   scripts/guard-frozen.sh                    # G1..G5
#   scripts/guard-frozen.sh --only G3,G4       # a subset
#   scripts/guard-frozen.sh --reference-only   # build the reference dump (Sean's master), print its path
#   scripts/guard-frozen.sh --orders           # engine 0023, qualification's card versions, platform 0003: all 6 orders
#                                              # (the old chain, on the pre-isolation trees; its reference is e34fca3)
#
# G1  engine schema at HEAD, migrated by migrate_projects into a project database, equals the
#     schema Sean's origin/master makes up to exactly the differences g1_allowed lists: our three
#     columns with their indexes and keys, the mode marker table, and in configurator minus the
#     login tables 0019 drops
# G2  retired: it froze qualification.knowledge_graph and qualification_risk, which are
#     our own tables (the VAIR form added columns to the second). The freeze is there so we never
#     diverge from the originals: the authors' AIRO/VAIR files (G3) and Sean's code (G1, G4, G5).
# G3  the vendored AIRO/VAIR files, as their authors published them, hash as pinned
# G4  backend, eval and webapp byte-identical to Sean's origin/master (the base of
#     feat/deployment-modes) but for the files scripts/guard-frozen-intended.txt names with their
#     task and reason; plugin-interface without new commits, plugin-manager clean and at PM_REF
#     (Méril's feat/dev-catalogue-staging, not master)
# G5  engine models equal Sean's origin/master but for the files G4's list names for the backend;
#     makemigrations has nothing to make
#
# Every database is a throwaway postgres:15-alpine container (scripts/lib/throwaway-pg.sh) on a
# port the kernel picks, removed on exit. The candidate's engine and qualification tables are
# made where the stack makes them: in a project database (tpg_project_db, then manage.py
# migrate_projects and prisma migrate deploy there). The reference and the --orders fixture are
# the shared layout of before the project databases, built from the trees of the top-level commit
# f01288a, since the current init files do not make the module schemas in platform. Dumps are
# --no-privileges: grants are proven by scripts/tests/test_project_grants.py and
# verify-project-databases.sh I16.1. The host's 5432 (the live stack) is never a target and no
# `docker compose` command is run.
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

MODE=all; ONLY="G1,G3,G4,G5"
while [ $# -gt 0 ]; do
  case "$1" in
    --reference-only) MODE=reference ;;
    --orders) MODE=orders ;;
    --only) ONLY=$2; shift
            case ",$ONLY," in *,G2,*) echo "G2 is retired (2026-09-30): knowledge_graph and qualification_risk are our own tables; see the header" >&2; exit 2 ;; esac ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

BACKEND=$ROOT/apps/backend
QUAL=$ROOT/apps/qualification
CO=$ROOT/apps/control-objectives
PY=${GUARD_BACKEND_PY:-$BACKEND/.venv/bin/python}   # overridable only so a test can force a failure
# The reference engines need their own dependencies (Sean's master keeps django-allauth, which
# the candidate's configurator does without), so each runs in a virtualenv made once from its own
# uv.lock and kept in GUARD_CACHE: G1's from origin/master's lock, --orders' (e34fca3, dfe4120)
# from e34fca3's. GUARD_BACKEND_PY, when set, is used for them too.
GUARD_CACHE=${GUARD_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/aisc-guard}
PRISMA=$QUAL/node_modules/.bin/prisma
SOURCE=${GUARD_SOURCE:-head}
# The backend image installs these from ../../shared (dfe4120); the local venv may hold older
# copies, so the checked-out sources come first.
SHARED_PYTHONPATH=$ROOT/shared/plugin-interface/src:$ROOT/shared/plugin-manager/src

# G4's list (scripts/guard-frozen-intended.txt) names the engine repos' base, Sean's origin/master.
INTENDED=${GUARD_INTENDED:-$ROOT/scripts/guard-frozen-intended.txt}   # overridable so a test can leave a file out
intended_base() { awk -v r="$1" '$1 == "base" && $2 == r { print $3 }' "$INTENDED"; }

# Pinned references
ENGINE_REF=$(intended_base backend)   # G1, G5: Sean's origin/master of the backend (1b1efe9), G4's base
ORDERS_ENGINE_REF=e34fca3   # --orders only: the pre-isolation reference its six orders are compared with
[ -n "$ENGINE_REF" ] || { echo "no 'base backend' line in $INTENDED" >&2; exit 2; }
QUAL_REF=e112001            # qualification before the card-versions migration
PI_REF=97eddea              # G4's engine references: scripts/guard-frozen-intended.txt
PM_REF=46e1867              # plugin-manager: Méril's origin/feat/dev-catalogue-staging (public index without login), not master
LIVE_TOP=ad6262f            # top-level commit whose init/ and platform/ are the live shape
LIVE_ENGINE=dfe4120         # backend with 0022, as live
MCAS_PID=1e722ea2-4ce3-47fa-81bf-11a6b53ad679
ENGINE_0023_GLOB='0023_*.py'   # the OLD chain on purpose: --orders' E step, on f01288a's backend (0023_one_system_per_project_again); the new chain ends at 0021
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

# --orders: the trees from before the project databases (the backend and qualification commits of
# f01288a's gitlinks).
# Its E and Q steps cannot run on the isolated candidate: the engine's default database is a dummy
# there, and qualification's card-versions migration was folded into the project baseline.
prepare_order_trees() {
  [ -d "$WORK/ord" ] && return 0
  tree "$ROOT" "$ORDERS_TOP_REF" "$WORK/ord/top" init platform/migrations
  tree "$BACKEND" "$(git -C "$ROOT" rev-parse "$ORDERS_TOP_REF:apps/backend")" "$WORK/ord/backend"
  tree "$QUAL" "$(git -C "$ROOT" rev-parse "$ORDERS_TOP_REF:apps/qualification")" "$WORK/ord/qualification" prisma
  tree "$CO" "$(git -C "$ROOT" rev-parse "$ORDERS_TOP_REF:apps/control-objectives")" "$WORK/ord/co" alembic alembic.ini src
  tree "$BACKEND" "$ORDERS_ENGINE_REF" "$WORK/ord/ref-backend"
}

reference_python() { # rev tree: prints the python of a reference engine, making its virtualenv once
  local rev=$1 src=$2
  if [ -n "${GUARD_BACKEND_PY:-}" ]; then echo "$GUARD_BACKEND_PY"; return 0; fi
  local venv="$GUARD_CACHE/backend-$(git -C "$BACKEND" rev-parse --short=7 "$rev^{commit}")"
  if [ ! -x "$venv/bin/python" ]; then
    mkdir -p "$GUARD_CACHE"
    local tmp="$venv.tmp.$$"
    rm -rf "$tmp"
    (cd "$src" && uv export --frozen --no-dev --no-emit-project --no-hashes) \
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
# G1's allowed differences: what the candidate, migrated by
# migrate_projects into a project database (configurator), may add to or lack from the schema
# Sean's master makes. One line each: `<+|-> <kind> <name>`, and for an addition ` | <definition>`,
# which must then match too. Kinds: table, column <table>.<column>, constraint <table>.<name>,
# fk <table>.<name>, index <table>.<name>, sequence <name>. A table on one side only is one
# difference: its columns, constraints, indexes and sequences go with it. Any other difference,
# and any line here that is not a difference, fails G1 with its name.
g1_allowed() { # the list, or GUARD_G1_ALLOWED's file (so a test can leave a line out)
  if [ -n "${GUARD_G1_ALLOWED:-}" ]; then cat "$GUARD_G1_ALLOWED"; return; fi
  cat <<'G1_ALLOWED_END'
# G1_ALLOWED_BEGIN
# 0015: the catalogue entry an enabled plugin came from
+ column aisc_backend_plugin.catalogue_slug | character varying(255)
# 0016: the system an evaluation ran against; db_index=True makes its index; 0020 points the key
# at this project database's project.system (the platform's core.system before the isolation)
+ column aisc_backend_evaluation.system_id | uuid
+ index aisc_backend_evaluation.aisc_backend_evaluation_system_id_db29add6 | CREATE INDEX aisc_backend_evaluation_system_id_db29add6 ON engine.aisc_backend_evaluation USING btree (system_id)
+ fk aisc_backend_evaluation.aisc_backend_evaluation_system_id_fkey | FOREIGN KEY (system_id) REFERENCES project.system(pid) ON DELETE SET NULL
# 0016, 0017, 0018: the platform project of an engine project (column project_id, db_index=True),
# one engine project per platform project; no foreign key in a project database (core is not there)
+ column aisc_backend_project.project_id | uuid
+ index aisc_backend_project.aisc_backend_project_platform_project_id_f61734b2 | CREATE INDEX aisc_backend_project_platform_project_id_f61734b2 ON engine.aisc_backend_project USING btree (project_id)
+ index aisc_backend_project.one_project_per_platform_project | CREATE UNIQUE INDEX one_project_per_platform_project ON engine.aisc_backend_project USING btree (project_id) WHERE (project_id IS NOT NULL)
# 0021: the database records its mode
+ table engine_deployment | mode character varying(16) NOT NULL; ALTER TABLE engine.engine_deployment OWNER TO engine_rw;
# 0019, configurator: no login of its own, so Django's auth, session and admin tables and allauth's go
- table account_emailaddress
- table account_emailconfirmation
- table auth_group
- table auth_group_permissions
- table auth_permission
- table auth_user
- table auth_user_groups
- table auth_user_user_permissions
- table django_admin_log
- table django_session
G1_ALLOWED_END
}

g1_compare() { # reference-dump candidate-dump allowed-list -> the differences not allowed, one per line
  python3 - "$1" "$2" "$3" <<'CMP'
import re, sys

def objects(path):
    """{key: definition} of a --schema-only dump of the engine schema, keyed as G1's list."""
    blocks, cur = [], None
    for line in open(path).read().splitlines():
        m = re.match(r"-- Name: (.*); Type: (.*); Schema: engine; Owner: ", line)
        if m:
            cur = [m.group(1), m.group(2), []]; blocks.append(cur)
        elif cur and line.strip() and not line.startswith("--") and not line.startswith("\\"):
            cur[2].append(line.strip())
    out, owner, whole = {}, {}, {}
    for name, kind, lines in blocks:
        text = " ".join(lines)
        if kind == "TABLE":
            cols, rest, inside = [], [], False
            for l in lines:
                if l.startswith("CREATE TABLE "):
                    inside = True; continue
                if inside and l.startswith(")"):
                    inside = False; continue
                (cols if inside else rest).append(l.rstrip(","))
            # a table's own entry is what is not a column (its owner); a table on one side only
            # is compared whole, columns included
            out[f"table {name}"] = "; ".join(rest)
            whole[f"table {name}"] = "; ".join(cols + rest)
            owner[f"table {name}"] = name
            for c in cols:
                if c.startswith("CONSTRAINT "):
                    key, value = f"constraint {name}.{c.split()[1]}", c
                else:
                    col = c.split()[0].strip('"')
                    key, value = f"column {name}.{col}", c[len(c.split()[0]):].strip()
                out[key] = value; owner[key] = name
        elif kind in ("CONSTRAINT", "FK CONSTRAINT"):
            table, con = name.split(" ", 1)
            key = f"{'fk' if kind == 'FK CONSTRAINT' else 'constraint'} {table}.{con}"
            out[key] = re.sub(r"^ALTER TABLE ONLY \S+ ADD CONSTRAINT \S+ ", "", text).rstrip(";")
            owner[key] = table
        elif kind == "INDEX":
            table = re.search(r" ON (?:ONLY )?engine\.(\S+) ", text).group(1)
            key = f"index {table}.{name}"
            out[key] = text.rstrip(";"); owner[key] = table
        elif kind == "SEQUENCE":
            m = re.search(r"ALTER TABLE engine\.(\S+) ALTER COLUMN|OWNED BY engine\.([^.\s]+)\.", text)
            key = f"sequence {name}"
            out[key] = text; owner[key] = (m.group(1) or m.group(2)) if m else None
        else:
            out[f"{kind.lower()} {name}"] = text
    return out, owner, whole

ref, ref_owner, _ = objects(sys.argv[1])
cand, cand_owner, cand_whole = objects(sys.argv[2])
allowed = {}
for line in open(sys.argv[3]).read().splitlines():
    if line.strip() and not line.lstrip().startswith("#"):
        key, _, definition = line.partition(" | ")
        allowed[key.strip()] = definition.strip() or None
ref_tables = {k[6:] for k in ref if k.startswith("table ")}
cand_tables = {k[6:] for k in cand if k.startswith("table ")}
only_ref, only_cand = ref_tables - cand_tables, cand_tables - ref_tables
found = {}
for key in sorted(set(ref) | set(cand)):
    if key in ref and key in cand:
        if ref[key] != cand[key]:
            found[f"~ {key}"] = cand[key]
    elif key in cand:
        t = cand_owner.get(key)
        if t in only_cand and key != f"table {t}":
            continue
        found[f"+ {key}"] = cand_whole.get(key, cand[key])
    else:
        t = ref_owner.get(key)
        if t in only_ref and key != f"table {t}":
            continue
        found[f"- {key}"] = None
bad = []
for d, definition in found.items():
    if d not in allowed:
        bad.append(f"not listed: {d}")
    elif allowed[d] is not None and allowed[d] != definition:
        bad.append(f"listed with another definition: {d} (candidate: {definition})")
for d in allowed:
    if d not in found:
        bad.append(f"listed but not a difference: {d}")
for b in bad:
    print(b)
CMP
}
snapshot() { tpg_su postgres -c "DROP DATABASE IF EXISTS \"$1\"" >/dev/null; tpg_copy_db platform "$1"; }
restore() { tpg_su postgres -c "DROP DATABASE platform WITH (FORCE)" >/dev/null; tpg_copy_db "$1" platform; }

start_db() {
  tpg_start guard || { fail G0 "throwaway postgres did not start"; exit 1; }
  echo "container: $TPG_NAME"
}

build_reference() { # [rev tree]: the engine of rev (default $ENGINE_REF, Sean's master)
  # The reference engine, and e112001's qualification (which needs platform 0002's
  # core.ai_system_version, so 0002 runs here too; it touches no engine table).
  # Sean's master has no DB_SCHEMA setting, so its tables go to the engine schema through
  # PGOPTIONS; an engine that sets its own search_path (e34fca3's DB_SCHEMA) overrides it.
  local rev=${1:-$ENGINE_REF} src=${2:-$WORK/ref/backend}
  tpg_init_platform "$WORK/live/top" || return 1
  snapshot pristine
  platform_migrations "$WORK/live/top" 0001_project_membership.sql 0002_one_ai_system_per_project.sql >"$OUT/ref.log" 2>&1 || return 1
  prisma_deploy "$WORK/ref/qualification" >>"$OUT/ref.log" 2>&1 || return 1
  local ref_py
  ref_py=$(reference_python "$rev" "$src" 2>>"$OUT/ref.log") || return 1
  PGOPTIONS="-c search_path=engine" ENGINE_PY=$ref_py engine_migrate "$src" >>"$OUT/ref.log" 2>&1 || return 1
  engine_dump platform > "$OUT/engine.reference.sql"
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
}

why() { # summary of missing pieces and failed steps
  cat "$OUT/candidate.missing" "$OUT/candidate.errors" 2>/dev/null | tr '\n' ';'
}

g1() {
  g1_allowed > "$OUT/g1.allowed"
  diff -u "$OUT/engine.reference.sql" "$OUT/engine.candidate.sql" > "$OUT/g1.diff"
  g1_compare "$OUT/engine.reference.sql" "$OUT/engine.candidate.sql" "$OUT/g1.allowed" > "$OUT/g1.differences" \
    || echo "the comparison itself failed" >> "$OUT/g1.differences"
  if [ ! -s "$OUT/g1.differences" ]; then
    pass G1 "(engine schema equals Sean's master plus the listed additions)"
  else
    fail G1 "engine schema differs from Sean's master ($ENGINE_REF) beyond the list: $(paste -sd';' "$OUT/g1.differences" | sed 's/;/; /g') ($OUT/g1.differences, $OUT/g1.diff) $(why)"
  fi
}

g3() {
  if (cd "$ROOT" && sha256sum -c --quiet - <<'SUMS'
6274d2d8711e046cf38f1b5b2980188094d4aa87b5af79804005a06468fd8469  apps/qualification/services/ontology/airo/airo.ttl
6b42323726e7a82a5c4782a6d9398fc44db21bd4e0ca9fd4807558190c173605  apps/qualification/services/ontology/airo/vair.ttl
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

# G4: since feat/deployment-modes the engine repos are Sean's
# origin/master plus a configurator mode, so their reference is that base, and every file the
# branch adds or changes is named, with its task and reason, in $INTENDED. Any other file that
# differs from the base (added, changed or removed) fails G4.
intended_listed() { # repo path
  awk -v r="$1" -v f="$2" '$1 == r && $2 == f { found = 1 } END { exit !found }' "$INTENDED"
}

g4() {
  local ok=1 f bad repo base
  for repo in backend eval webapp; do
    base=$(intended_base "$repo")
    if [ -z "$base" ] || ! git -C "$ROOT/apps/$repo" cat-file -e "$base^{commit}" 2>/dev/null; then
      ok=0; fail G4 "$repo: no base commit in $INTENDED"; continue
    fi
    bad=""
    for f in $(changed_names "$ROOT/apps/$repo" "$base"); do
      intended_listed "$repo" "$f" || bad="$bad $f"
    done
    [ -z "$bad" ] || { ok=0; fail G4 "$repo: files not on the list differ from origin/master ($base):$bad"; }
  done
  local n
  n=$(git -C "$ROOT/shared/plugin-interface" rev-list --count "$PI_REF..HEAD")
  [ "$n" = 0 ] || { ok=0; fail G4 "shared/plugin-interface has $n commits after $PI_REF"; }
  [ -z "$(git -C "$ROOT/shared/plugin-manager" status --porcelain)" ] || { ok=0; fail G4 "shared/plugin-manager is not clean"; }
  [ "$(git -C "$ROOT/shared/plugin-manager" rev-parse HEAD)" = "$(git -C "$ROOT/shared/plugin-manager" rev-parse "$PM_REF^{commit}" 2>/dev/null)" ] \
    || { ok=0; fail G4 "shared/plugin-manager is not at $PM_REF (Task 9b, Méril's feat/dev-catalogue-staging)"; }
  [ $ok = 1 ] && pass G4
}

g5() {
  local ok=1
  # Sean's models but for the files G4's list names for the backend (the three added columns)
  local f bad=""
  for f in $(changed_names "$BACKEND" "$ENGINE_REF" aisc_backend/models); do
    intended_listed backend "$f" || bad="$bad $f"
  done
  [ -z "$bad" ] || { ok=0; fail G5 "aisc_backend/models differs from Sean's master ($ENGINE_REF) in files not on the list:$bad"; }
  prepare_trees
  if ! (cd "$WORK/cand/backend" && DB_ENGINE=django.db.backends.sqlite3 DB_NAME="$WORK/g5.db" \
        PYTHONPATH="$SHARED_PYTHONPATH" "$PY" manage.py makemigrations --check --dry-run) > "$OUT/g5.log" 2>&1; then
    ok=0; fail G5 "makemigrations --check reports changes ($OUT/g5.log)"
  fi
  [ $ok = 1 ] && pass G5
}

# Migration orders (--orders): engine 0023 (E), qualification's card versions (Q) and platform
# 0003 (P), applied in every order on a live-shaped fixture. A regression check of history: the
# three steps are those of the trees from before the project databases ($ORDERS_TOP_REF).
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
  ENGINE_PY=$(reference_python "$ORDERS_ENGINE_REF" "$WORK/ord/ref-backend") engine_migrate "$WORK/live/backend" || return 1
  # control objectives as it was before the project databases (the current alembic refuses `platform`)
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
  build_reference "$ORDERS_ENGINE_REF" "$WORK/ord/ref-backend" > /dev/null || { fail S4 "could not build the reference ($OUT/ref.log)"; return; }
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
  # Without the ownership fix, E and Q pass and P fails on core.system's owner; after the
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
    if selected G1; then
      prepare_trees; start_db
      if build_reference > /dev/null; then
        build_candidate
        selected G1 && g1
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
