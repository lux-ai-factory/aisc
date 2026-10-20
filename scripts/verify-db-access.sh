#!/usr/bin/env bash
# The access contract of the databases, asserted by connecting as each role.
#
# Each project has its own database
# project_<pid without hyphens>, where every module owns a schema, reads the card versions in
# project.system, and is refused the rest. `platform` keeps only the list of projects and their
# members. These are the assertions that make that a fact rather than an intention, so a stray
# privilege fails the suite. The module part runs in a throwaway project_<random hex> database on
# the same cluster, made as the platform makes one (platform_rw, the project template) and
# removed afterwards.
set -uo pipefail
PGC=${PGCONTAINER:-postgres}
HOST=${PGHOST:-localhost}
DB=${PLATFORM_DB:-platform}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

# run SQL as a role in a database; prints nothing, returns non-zero when refused
# platform_rw, qualification_rw, control_objectives_rw, controls_rw, catalogue_rw, engine_rw, dashboard_ro,
# report_composer_rw and report_ro have generated passwords (scripts/secrets.sh, applied by postgres-setup).
PLATFORM_RW_PASSWORD=${PLATFORM_RW_PASSWORD:-$(awk 'index($0, "PLATFORM_RW_PASSWORD=") == 1 { print substr($0, 22); exit }' "$ROOT/env.runtime" 2>/dev/null)}
QUALIFICATION_RW_PASSWORD=${QUALIFICATION_RW_PASSWORD:-$(awk 'index($0, "QUALIFICATION_RW_PASSWORD=") == 1 { print substr($0, 27); exit }' "$ROOT/env.runtime" 2>/dev/null)}
CONTROL_OBJECTIVES_RW_PASSWORD=${CONTROL_OBJECTIVES_RW_PASSWORD:-$(awk 'index($0, "CONTROL_OBJECTIVES_RW_PASSWORD=") == 1 { print substr($0, 32); exit }' "$ROOT/env.runtime" 2>/dev/null)}
DASHBOARD_RO_PASSWORD=${DASHBOARD_RO_PASSWORD:-$(awk 'index($0, "DASHBOARD_RO_PASSWORD=") == 1 { print substr($0, 23); exit }' "$ROOT/env.runtime" 2>/dev/null)}
CONTROLS_RW_PASSWORD=${CONTROLS_RW_PASSWORD:-$(awk 'index($0, "CONTROLS_RW_PASSWORD=") == 1 { print substr($0, 22); exit }' "$ROOT/env.runtime" 2>/dev/null)}
CATALOGUE_RW_PASSWORD=${CATALOGUE_RW_PASSWORD:-$(awk 'index($0, "CATALOGUE_RW_PASSWORD=") == 1 { print substr($0, 23); exit }' "$ROOT/env.runtime" 2>/dev/null)}
ENGINE_RW_PASSWORD=${ENGINE_RW_PASSWORD:-$(awk 'index($0, "ENGINE_RW_PASSWORD=") == 1 { print substr($0, 20); exit }' "$ROOT/env.runtime" 2>/dev/null)}
REPORT_COMPOSER_PASSWORD=${REPORT_COMPOSER_PASSWORD:-$(awk 'index($0, "REPORT_COMPOSER_PASSWORD=") == 1 { print substr($0, 26); exit }' "$ROOT/env.runtime" 2>/dev/null)}
REPORT_RO_PASSWORD=${REPORT_RO_PASSWORD:-$(awk 'index($0, "REPORT_RO_PASSWORD=") == 1 { print substr($0, 20); exit }' "$ROOT/env.runtime" 2>/dev/null)}
# pw ROLE sets PW to the role's password (never printed): platform_rw's, qualification_rw's,
# control_objectives_rw's, controls_rw's, catalogue_rw's, engine_rw's, dashboard_ro's, report_composer_rw's
# and report_ro's are generated (each falls back to its own name, the default before it had one)
pw() {
  case "$1" in
    platform_rw) PW=${PLATFORM_RW_PASSWORD:-platform_rw} ;;
    qualification_rw) PW=${QUALIFICATION_RW_PASSWORD:-qualification_rw} ;;
    control_objectives_rw) PW=${CONTROL_OBJECTIVES_RW_PASSWORD:-control_objectives_rw} ;;
    dashboard_ro) PW=${DASHBOARD_RO_PASSWORD:-dashboard_ro} ;;
    controls_rw) PW=${CONTROLS_RW_PASSWORD:-controls_rw} ;;
    catalogue_rw) PW=${CATALOGUE_RW_PASSWORD:-catalogue_rw} ;;
    engine_rw) PW=${ENGINE_RW_PASSWORD:-engine_rw} ;;
    report_composer_rw) PW=${REPORT_COMPOSER_PASSWORD:-report_composer_rw} ;;
    report_ro) PW=${REPORT_RO_PASSWORD:-report_ro} ;;
    *) PW=$1 ;;
  esac
}
pw platform_rw; PLATFORM_PW=$PW
as_in() { pw "$1"; docker exec "$PGC" psql "postgresql://$1:$PW@$HOST:5432/$2" -v ON_ERROR_STOP=1 -At -c "$3" >/dev/null 2>&1; }
as() { as_in "$1" "$DB" "$2"; }

allow() { as "$1" "$2" && ok "$1: $3" || no "$1: $3 (was refused)"; }
# A denial counts only when PostgreSQL refuses for a privilege (permission denied). Any other error (no
# login, no such database or table) proves nothing about the grants and is a FAIL with its first line.
# The probe turns default_transaction_read_only off for its session: the readers' roles default to
# read-only (init/report-roles.sql, init/inspector-role.sql), but a session may turn that off, so only
# a refusal for a privilege shows they cannot write.
refused_in() { # role db sql -> 0 refused for a privilege, 1 allowed, 2 failed otherwise (WHY says how)
  local err
  pw "$1"
  if err=$(docker exec "$PGC" psql "postgresql://$1:$PW@$HOST:5432/$2?options=-c%20default_transaction_read_only%3Doff" \
             -v ON_ERROR_STOP=1 -At -c "$3" 2>&1 >/dev/null); then
    return 1
  fi
  case "$err" in *"permission denied"*) return 0 ;; esac
  WHY=$(printf '%s\n' "$err" | grep -m1 -E 'ERROR|FATAL|error' || printf '%s' "${err:-no answer}")
  return 2
}
denied() { # role db sql what
  refused_in "$1" "$2" "$3"
  case $? in
    0) ok "$1: $4" ;;
    1) no "$1: $4 (was ALLOWED)" ;;
    *) no "$1: $4 (not refused for a privilege: $WHY)" ;;
  esac
}
deny()  { denied "$1" "$DB" "$2" "$3"; }
allow_in() { as_in "$1" "$PROBE_DB" "$2" && ok "$1: $3" || no "$1: $3 (was refused)"; }
deny_in()  { denied "$1" "$PROBE_DB" "$2" "$3"; }

# The one project section 1 makes, removed by its exact slug at the end and on any exit: a pattern
# would also delete a real project whose slug starts the same way ("Probe 1" is probe-1).
PROBE_SLUG="probe-$$"
unprobe() {
  docker exec "$PGC" psql -U "${POSTGRES_USER:-aisc-postgres-user}" -d "$DB" -At -c "
  delete from core.project where slug = '$PROBE_SLUG';" >/dev/null 2>&1
}
trap unprobe EXIT

echo "1. the platform service owns the core"
allow platform_rw  "insert into core.project (name, slug) values ('probe','$PROBE_SLUG')" "can create a project"
allow platform_rw  "select count(*) from core.project"                                "can read projects"

echo "2. every module reads the list of projects and their members, and cannot change them"
for r in qualification_rw control_objectives_rw controls_rw engine_rw report_composer_rw; do
  allow "$r" "select count(*) from core.project"        "reads core.project"
  allow "$r" "select count(*) from core.project_member" "reads core.project_member"
  deny  "$r" "insert into core.project (name, slug) values ('x','x-$$-$r')" "cannot write core.project"
  deny  "$r" "delete from core.project_member" "cannot remove members"
done

# the throwaway project database of sections 3 to 5
PROBE_DB="project_$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
gone() {
  docker exec "$PGC" psql "postgresql://platform_rw:$PLATFORM_PW@$HOST:5432/$DB" -At \
    -c "drop database if exists \"$PROBE_DB\" with (force)" >/dev/null 2>&1
}
trap 'gone; unprobe' EXIT
made=1
docker exec "$PGC" psql "postgresql://platform_rw:$PLATFORM_PW@$HOST:5432/$DB" -v ON_ERROR_STOP=1 -At \
  -c "create database \"$PROBE_DB\"" >/dev/null 2>&1 || made=0
if [ "$made" = 1 ]; then
  {
    echo "begin;"
    echo "create schema if not exists provision;"
    echo "create table if not exists provision.template_migration (name text primary key, applied_at timestamptz not null default now());"
    for f in $(ls "$ROOT/platform/project-template"/*.sql | sort); do
      cat "$f"; echo ";"
      echo "insert into provision.template_migration (name) values ('$(basename "$f")');"
    done
    echo "commit;"
  } | docker exec -i "$PGC" psql "postgresql://platform_rw:$PLATFORM_PW@$HOST:5432/$PROBE_DB" -v ON_ERROR_STOP=1 -q -f - >/dev/null 2>&1 || made=0
fi
if [ "$made" = 1 ]; then ok "platform_rw: made a project database with the template"; else no "platform_rw: could not make a project database with the template"; fi

echo "3. in a project database, a module owns its own schema and reads the card versions"
for pair in qualification:qualification_rw control_objectives:control_objectives_rw controls:controls_rw \
            engine:engine_rw report_composer:report_composer_rw; do
  s=${pair%%:*}; r=${pair#*:}
  allow_in "$r" "create table $s.probe_$$ (x int); insert into $s.probe_$$ values (1); drop table $s.probe_$$" "creates and writes in its schema $s"
  allow_in "$r" "select count(*) from project.system" "reads project.system"
  deny_in  "$r" "insert into project.system (number, name) values (99, 'probe')" "cannot write project.system"
done

echo "4. and cannot reach another module's schema, llm, connection or provision"
deny_in qualification_rw      "create table engine.probe_$$ (x int)"            "cannot create in the engine's schema"
deny_in engine_rw             "create table qualification.probe_$$ (x int)"     "cannot create in qualification's schema"
deny_in control_objectives_rw "create table controls.probe_$$ (x int)"          "cannot create in the controls schema"
deny_in report_composer_rw    "create table control_objectives.probe_$$ (x int)" "cannot create in control objectives' schema"
for r in qualification_rw control_objectives_rw controls_rw engine_rw report_composer_rw; do
  deny_in "$r" "select count(*) from llm.provider"              "cannot read the LLM keys"
  deny_in "$r" "select count(*) from connection.endpoint"       "cannot read the connections"
  deny_in "$r" "select count(*) from target.target"             "cannot read the assessment targets"
  deny_in "$r" "select count(*) from provision.template_migration" "cannot read provisioning"
done

echo "5. the readers read the card versions and write nothing"
for r in dashboard_ro report_ro; do
  allow_in "$r" "select count(*) from project.system" "reads project.system"
  deny_in  "$r" "insert into project.system (number, name) values (98, 'probe')" "cannot write project.system"
  deny_in  "$r" "create table project.sneaky (x int)" "cannot create tables"
  deny_in  "$r" "select count(*) from llm.provider"   "cannot read the LLM keys"
  deny_in  "$r" "select count(*) from connection.endpoint" "cannot read the connections"
done
deny dashboard_ro "insert into core.project (name, slug) values ('x','y')"  "cannot write core"
deny dashboard_ro "create table core.sneaky (x int)"                        "cannot create tables in platform"

# clean up the probe project, as the owner (and again on exit, which finds nothing left)
unprobe

echo "6. nobody creates objects in public"
for r in qualification_rw engine_rw dashboard_ro platform_rw; do
  deny "$r" "create table public.sneaky_$$ (x int)" "cannot create in public"
done

echo "7. the platform service makes project databases, and nobody else does"
probe="probe_db_$$"
allow platform_rw "create database $probe" "can create a database"
allow platform_rw "drop database $probe"   "and drop the one it made"
deny  controls_rw "create database ${probe}_x" "a module cannot create a database"
deny  engine_rw   "create database ${probe}_y" "nor can the engine"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
