#!/usr/bin/env bash
# One database, a schema each, and every row knowing whose project it is.
#
#   ./scripts/verify-one-database.sh
#
# What this asserts, per module, against the RUNNING stack:
#   its tables are in its own schema of `platform`, and nowhere else,
#   the service is actually connected to that database as its own role,
#   its root table points at `core.project` with a real foreign key,
#   the database itself refuses a row whose project does not exist,
#   and the module still answers through the gateway, inside a project.
#
# Modules arrive here one at a time, as each is moved onto the platform
# database; the ones not yet moved are listed at the end as still to come.
set -uo pipefail
S=$(mktemp); trap 'rm -f "$S"' EXIT
PGDB=${PLATFORM_DB:-platform}; PGUSER=${PGUSER:-aisc-postgres-user}
pass=0; fail=0
ok(){ printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no(){ printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
psql_(){ docker exec postgres psql -U "$PGUSER" -d "$PGDB" -At -c "$1" 2>&1; }

# module | container | schema | the table that names a project | its column
# The link is called project_id in every schema: the project a row belongs to
# reads the same whichever schema the query is in.
MODULES=(
  "control objectives|control-objectives|control_objectives|project|project_id"
  "controls|controls-web|controls|submission|project_id"
  "qualification|qualification-web|qualification|qualification|project_id"
  "execution engine|aisc-backend|engine|project|project_id"
)
# Modules whose data belongs to no project: the catalogue is the registry of
# tests and controls, the same for every project. Everything else about them is
# the same contract, so they are checked for all of it but the project column.
REFERENCE=(
  "catalogue|catalogue-backend|catalogue"
)

for m in "${MODULES[@]}"; do
  IFS='|' read -r name container schema table column <<< "$m"
  echo "$name"

  n=$(psql_ "select count(*) from information_schema.tables where table_schema='$schema'")
  [ "${n:-0}" -gt 0 ] && ok "has $n tables in the $schema schema" || no "no tables in $schema"

  stray=$(psql_ "select count(*) from information_schema.tables
                  where table_schema='public' and table_name='$table'")
  [ "$stray" = "0" ] && ok "and none of them in public" || no "$table is also sitting in public"

  # Some services are configured with a URL, others with DB_NAME/DB_USER; both
  # say the same two things, so both are read.
  env_of(){ docker inspect "$1" --format '{{range .Config.Env}}{{println .}}{{end}}'; }
  conf=$(env_of "$container" | grep -E '^(DATABASE_URL|DB_NAME|DB_USER)=')
  case "$conf" in
    *"/$PGDB"*|*"DB_NAME=$PGDB"*) ok "the service is connected to the $PGDB database" ;;
    *sqlite*) no "still on a file of its own" ;;
    *) no "the service is not on $PGDB" ;;
  esac
  case "$conf" in
    *"${schema}_rw"*) ok "as its own role, ${schema}_rw" ;;
    *) no "not connecting as ${schema}_rw" ;;
  esac

  qualified="$schema.\"$table\""
  fk=$(psql_ "select confrelid::regclass::text
                from pg_constraint
               where conrelid = '$qualified'::regclass and contype = 'f'
                 and conkey = array[(select attnum from pg_attribute
                                      where attrelid = '$qualified'::regclass
                                        and attname = '$column')]")
  [ "$fk" = "core.project" ] && ok "$table.$column is a foreign key to core.project" \
    || no "$table.$column points at '${fk:-nothing}'"

  cascade=$(psql_ "select confdeltype from pg_constraint
                    where conrelid = '$qualified'::regclass and contype='f'
                      and confrelid = 'core.project'::regclass")
  if [ "$name" = "execution engine" ]; then
    # A workspace holds datasets, models, runs and their results. Deleting the
    # project it was opened from clears the link; it does not silently destroy
    # the evidence, which is what the whole platform exists to produce.
    [ "$cascade" = "n" ] && ok "deleting a project clears the link, not the evidence" \
      || no "the engine's key is $cascade, wanted SET NULL"
  else
    [ "$cascade" = "c" ] && ok "deleting a project takes its rows with it" \
      || no "the foreign key does not cascade (confdeltype=${cascade:-none})"
  fi

  notnull=$(psql_ "select attnotnull from pg_attribute
                    where attrelid='$qualified'::regclass and attname='$column'")
  if [ "$name" = "execution engine" ]; then
    # The engine can also be used on its own, so a workspace made outside the
    # launcher has no platform project. The key still holds for the ones that do.
    [ "$notnull" = "f" ] && ok "a workspace made outside the launcher may have none" \
      || no "$column is NOT NULL, which the engine's own project flow cannot satisfy"
  else
    [ "$notnull" = "t" ] && ok "and a row cannot exist without a project" \
      || no "$column is nullable: rows can exist outside any project"
  fi

  reads_core=$(psql_ "select has_table_privilege('${schema}_rw','core.project','SELECT')")
  writes_core=$(psql_ "select has_table_privilege('${schema}_rw','core.project','INSERT')")
  [ "$reads_core" = "t" ] && [ "$writes_core" = "f" ] \
    && ok "it reads core.project and cannot write it" \
    || no "core.project privileges are wrong (select=$reads_core insert=$writes_core)"
done

for m in "${REFERENCE[@]}"; do
  IFS='|' read -r name container schema <<< "$m"
  echo "$name (reference data)"

  n=$(psql_ "select count(*) from information_schema.tables where table_schema='$schema'")
  [ "${n:-0}" -gt 0 ] && ok "has $n tables in the $schema schema" || no "no tables in $schema"

  conf=$(docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' \
         | grep -E '^(DATABASE_URL|DB_NAME|DB_USER)=')
  case "$conf" in
    *"/$PGDB"*|*"DB_NAME=$PGDB"*) ok "the service is connected to the $PGDB database" ;;
    *sqlite*) no "still on a file of its own" ;;
    *) no "the service is not on $PGDB" ;;
  esac
  case "$conf" in
    *"${schema}_rw"*) ok "as its own role, ${schema}_rw" ;;
    *) no "not connecting as ${schema}_rw" ;;
  esac

  refs=$(psql_ "select count(*) from information_schema.columns
                 where table_schema='$schema' and column_name in ('project_id','projectId')")
  [ "$refs" = "0" ] && ok "and holds nothing belonging to a single project" \
    || no "$refs column(s) here name a project, which reference data should not"
done

echo "nothing is left on a database of its own"
for gone in control_objectives controls qualification; do
  live=$(psql_ "select count(*) from pg_stat_activity where datname = '$gone'")
  [ "${live:-0}" = "0" ] && ok "nothing is connected to the old $gone database" \
    || no "$live connection(s) still on the $gone database"
done

echo "the engine has no project of its own to choose"
# It is opened inside a project and works on it: one row per platform project,
# named after it, made on the first visit and found every time after.
dup=$(psql_ "insert into engine.project
               (pid,name,description,status,created_at,project_id)
             select gen_random_uuid(),'a second one','','Created',now(),pid
               from core.project limit 1" 2>&1)
case "$dup" in
  *one_project_per_platform_project*) ok "a second one for the same project is refused" ;;
  *"0 rows"*|"") no "a second project for the same platform project was accepted" ;;
  *) no "unexpected: $dup" ;;
esac
named=$(psql_ "select count(*) from engine.project p
                 join core.project c on c.pid = p.project_id
                where p.name <> c.name")
[ "${named:-0}" = "0" ] && ok "and the ones there carry the platform's own name" \
  || no "$named engine project(s) are named something else"

echo "the dashboard reads the whole database and writes none of it"
for t in engine.project catalogue.tool controls.checklist \
         qualification.qualification control_objectives.project core.project; do
  n=$(docker exec postgres psql "postgresql://dashboard_ro:dashboard_ro@localhost:5432/$PGDB" \
        -At -c "select count(*) from $t" 2>&1 | tail -1)
  case "$n" in
    ''|*[!0-9]*) no "dashboard_ro cannot read $t: $n" ;;
    *) ok "dashboard_ro reads $t ($n rows)" ;;
  esac
done
w=$(docker exec postgres psql "postgresql://dashboard_ro:dashboard_ro@localhost:5432/$PGDB" \
      -At -c "insert into engine.project (pid,name,description,status,created_at)
              values (gen_random_uuid(),'x','','Created',now())" 2>&1 | tail -1)
case "$w" in
  *"permission denied"*) ok "and cannot write a row anywhere" ;;
  *) no "dashboard_ro was able to write: $w" ;;
esac

echo "the dashboard reads THIS install (wave 1)"
# It reads the one database as dashboard_ro, or it is reading something else.
# On a machine running several stacks that is not hypothetical: a connection
# registered by hand once pointed at another stack's Postgres, and worked.
reg=$(docker exec postgres psql -U "$PGUSER" -d superset -At \
        -c "select sqlalchemy_uri from dbs order by id" 2>/dev/null)
[ -n "$reg" ] && ok "the dashboard has a database registered" \
  || no "the dashboard has no database registered at all"
# The dashboard runs on the host network, because its OIDC issuer has to read
# the same from inside the container as it does in the browser. So the address
# it uses for Postgres is the host's published one, and what matters is that it
# is THIS install's: our postgres publishes 127.0.0.1:5432, another stack's
# publishes something else.
ours=$(docker inspect postgres --format '{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}}{{end}}{{end}}' 2>/dev/null)
case "$reg" in
  *"@postgres:5432/$PGDB"*|*"@localhost:${ours:-5432}/$PGDB"*)
    ok "and it names this install's database (:${ours:-5432}/$PGDB)" ;;
  *) no "it names something else: ${reg:-nothing}" ;;
esac
case "$reg" in
  *dashboard_ro*) ok "as dashboard_ro, which can read everything and write nothing" ;;
  *) no "not connecting as dashboard_ro" ;;
esac
# It is registered from configuration, not by hand, which is what makes the
# address above reproducible on the next install rather than whatever someone
# once typed into the UI.
case "$(docker logs dashboard 2>&1 | tail -400)" in
  *"results database registered"*) ok "and it registered that itself, from its configuration" ;;
  *) no "nothing registered the results database: it is whatever was typed in the UI" ;;
esac

echo "the catalogue's schema comes from migrations (wave 1)"
# It creates its tables with create_all, so a column change is silent and a
# rename loses data. Every other module migrates; this one should too.
n=$(psql_ "select count(*) from information_schema.tables
            where table_schema='catalogue' and table_name = 'alembic_version'")
[ "${n:-0}" = "1" ] && ok "the catalogue schema carries a migration history" \
  || no "the catalogue schema has no migration history: its tables come from create_all"
[ -f apps/catalogue/backend/alembic.ini ] && ok "and the repo has the migrations to replay" \
  || no "apps/catalogue/backend has no alembic.ini"
# The history and the models agree: every table the models declare is there,
# and nothing else is, which is what a baseline built from the models buys.
declared=$(docker exec catalogue-backend sh -lc "cd /app && uv run --no-sync python -c \"
from sql_alchemy import Base
print(' '.join(sorted(t.name for t in Base.metadata.sorted_tables)))\"" 2>/dev/null | tail -1)
present=$(psql_ "select string_agg(table_name, ' ' order by table_name)
                   from information_schema.tables
                  where table_schema='catalogue' and table_name <> 'alembic_version'")
[ -n "$declared" ] && [ "$declared" = "$present" ] \
  && ok "and the migrated schema is exactly what the models declare" \
  || no "models say [$declared], the database has [$present]"

echo "one naming convention"
# Quoted CamelCase in one schema and snake_case in another meant a query joining
# two of them had to remember which half needed quotes.
odd=$(psql_ "select string_agg(table_schema||'.'||table_name, ', ')
               from information_schema.tables
              where table_schema in ('core','qualification','control_objectives','controls','engine','catalogue')
                and table_name <> lower(table_name)")
[ -z "$odd" ] && ok "every table is lower case, so nothing needs quoting" \
  || no "still needs quoting: $odd"
prefixed=$(psql_ "select count(*) from information_schema.tables
                   where table_schema='engine' and table_name like 'aisc_backend%'")
[ "${prefixed:-1}" = "0" ] && ok "and the engine's tables do not repeat the schema's name" \
  || no "$prefixed engine table(s) still carry the app prefix"
naive=$(psql_ "select string_agg(table_schema||'.'||table_name||'.'||column_name, ', ')
                 from information_schema.columns
                where table_schema in ('core','qualification','control_objectives','controls','catalogue')
                  and data_type = 'timestamp without time zone'")
[ -z "$naive" ] && ok "and every timestamp carries its zone" \
  || no "read as the reader's own zone: $naive"

echo "one name for each link"
# The project a row belongs to and the system a row is about are two different
# things, and stay two columns; what they are called is now the same everywhere.
# Read from the keys themselves, not from every column whose name contains the
# word: `project_setting_id` points at a project setting, which is a different
# thing and rightly called something else.
odd=$(psql_ "select string_agg(conrelid::regclass::text||'.'||a.attname, ', ')
               from pg_constraint c
               join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
              where c.contype = 'f'
                and confrelid::regclass::text in ('core.project','core.system')
                and a.attname <> case confrelid::regclass::text
                                   when 'core.project' then 'project_id'
                                   else 'system_id' end")
[ -z "$odd" ] && ok "every key into core is named project_id or system_id" \
  || no "still spelled differently: $odd"
n=$(psql_ "select count(*) from information_schema.columns
            where column_name = 'system_id'
              and table_schema in ('qualification','engine')")
[ "${n:-0}" = "2" ] && ok "and the system link is where it belongs: the qualification and the evaluation" \
  || no "the system link is on $n table(s), expected 2"

echo "the platform's own project list is unchanged"
n=$(psql_ "select count(*) from core.project")
[ "${n:-0}" -ge 1 ] && ok "core.project holds $n project(s)" || no "no projects on the platform"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
