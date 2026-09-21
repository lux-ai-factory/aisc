#!/usr/bin/env bash
# The access contract of the one database, asserted by connecting as each role.
#
# One database does not mean everyone sees everything. Each module owns a schema,
# reads the shared core, and is refused the rest. These are the assertions that
# make that a fact rather than an intention, so a stray GRANT fails the suite.
set -uo pipefail
PGC=${PGCONTAINER:-postgres}
HOST=${PGHOST:-localhost}
DB=${PLATFORM_DB:-platform}
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

# run SQL as a role; prints nothing, returns non-zero when refused
as() { docker exec "$PGC" psql "postgresql://$1:$1@$HOST:5432/$DB" -v ON_ERROR_STOP=1 -At -c "$2" >/dev/null 2>&1; }

allow() { as "$1" "$2" && ok "$1: $3" || no "$1: $3 (was refused)"; }
deny()  { as "$1" "$2" && no "$1: $3 (was ALLOWED)" || ok "$1: $3"; }

echo "1. the platform service owns the core"
allow platform_rw  "insert into core.project (name, slug) values ('probe','probe-$$')" "can create a project"
allow platform_rw  "select count(*) from core.project"                                "can read projects"

echo "2. every module can read the core and cannot change it"
for r in qualification_rw control_objectives_rw controls_rw engine_rw; do
  allow "$r" "select count(*) from core.project" "reads core.project"
  allow "$r" "select count(*) from core.system"  "reads core.system"
  deny  "$r" "insert into core.project (name, slug) values ('x','x-$$-$r')" "cannot write core.project"
  deny  "$r" "delete from core.system" "cannot delete systems"
done

echo "3. a module owns its own schema"
allow qualification_rw      "create table if not exists qualification.probe (x int)"      "creates in its schema"
allow control_objectives_rw "create table if not exists control_objectives.probe (x int)" "creates in its schema"
allow controls_rw           "create table if not exists controls.probe (x int)"           "creates in its schema"
allow engine_rw             "create table if not exists engine.probe (x int)"             "creates in its schema"
allow engine_rw             "insert into engine.probe values (1)"                         "writes its own table"

echo "4. and cannot reach another module's"
deny qualification_rw "select * from engine.probe"             "cannot read the engine's schema"
deny engine_rw        "select * from qualification.probe"      "cannot read qualification's schema"
deny controls_rw      "select * from control_objectives.probe" "cannot read control objectives"
deny engine_rw        "create table controls.sneaky (x int)"   "cannot create in another schema"

echo "5. the dashboard reads everything and writes nothing"
for s in core qualification control_objectives controls engine; do
  case "$s" in
    core) allow dashboard_ro "select count(*) from core.project" "reads core";;
    *)    allow dashboard_ro "select count(*) from $s.probe"     "reads $s";;
  esac
done
deny dashboard_ro "insert into engine.probe values (2)"                     "cannot write the engine's schema"
deny dashboard_ro "insert into core.project (name, slug) values ('x','y')"  "cannot write core"
deny dashboard_ro "create table core.sneaky (x int)"                        "cannot create tables"

echo "6. nobody creates objects in public"
for r in qualification_rw engine_rw dashboard_ro platform_rw; do
  deny "$r" "create table public.sneaky_$$ (x int)" "cannot create in public"
done

# clean up the probes, as the owner
docker exec "$PGC" psql -U "${POSTGRES_USER:-aisc-postgres-user}" -d "$DB" -At -c "
  drop table if exists qualification.probe, control_objectives.probe, controls.probe, engine.probe;
  delete from core.project where slug like 'probe-%';" >/dev/null 2>&1

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
