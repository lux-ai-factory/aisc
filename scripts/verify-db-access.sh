#!/usr/bin/env bash
# The access contract of the databases, asserted by connecting as each role.
#
# Since the isolation (2026-09-25, I16.1, I19.1) each project has its own database
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
as_in() { docker exec "$PGC" psql "postgresql://$1:$1@$HOST:5432/$2" -v ON_ERROR_STOP=1 -At -c "$3" >/dev/null 2>&1; }
as() { as_in "$1" "$DB" "$2"; }

allow() { as "$1" "$2" && ok "$1: $3" || no "$1: $3 (was refused)"; }
deny()  { as "$1" "$2" && no "$1: $3 (was ALLOWED)" || ok "$1: $3"; }
allow_in() { as_in "$1" "$PROBE_DB" "$2" && ok "$1: $3" || no "$1: $3 (was refused)"; }
deny_in()  { as_in "$1" "$PROBE_DB" "$2" && no "$1: $3 (was ALLOWED)" || ok "$1: $3"; }

echo "1. the platform service owns the core"
allow platform_rw  "insert into core.project (name, slug) values ('probe','probe-$$')" "can create a project"
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
  docker exec "$PGC" psql "postgresql://platform_rw:platform_rw@$HOST:5432/$DB" -At \
    -c "drop database if exists \"$PROBE_DB\" with (force)" >/dev/null 2>&1
}
trap gone EXIT
made=1
docker exec "$PGC" psql "postgresql://platform_rw:platform_rw@$HOST:5432/$DB" -v ON_ERROR_STOP=1 -At \
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
  } | docker exec -i "$PGC" psql "postgresql://platform_rw:platform_rw@$HOST:5432/$PROBE_DB" -v ON_ERROR_STOP=1 -q -f - >/dev/null 2>&1 || made=0
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

# clean up the probe project, as the owner
docker exec "$PGC" psql -U "${POSTGRES_USER:-aisc-postgres-user}" -d "$DB" -At -c "
  delete from core.project where slug like 'probe-%';" >/dev/null 2>&1

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
