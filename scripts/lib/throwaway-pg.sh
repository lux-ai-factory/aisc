# Throwaway Postgres for tests. Sourced, never executed.
#
#   . scripts/lib/throwaway-pg.sh
#   tpg_start guard            # starts aisc-t-guard-<hex> on a free 127.0.0.1 port
#   tpg_su   platform -c 'SELECT 1'
#   tpg_as   platform platform_rw -f - < file.sql
#
# Why this file exists: the running stack's Postgres listens on the host's 5432
# and holds live data. Every test database here is a container of its own, on a
# port the kernel picks, removed on exit (trap on EXIT, INT, TERM). psql and
# pg_dump run inside the container, since the host has neither.
#
# Same major version as the live stack (postgres:15-alpine), so pg_dump output
# is comparable with a dump of the live DB.

TPG_IMAGE=${TPG_IMAGE:-postgres:15-alpine}
TPG_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TPG_SU=aisc-postgres-user
TPG_NAME=""
PORT=""
TPG_PW=""

tpg_free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

tpg_cleanup() {
  if [ -n "$TPG_NAME" ]; then
    docker rm -f "$TPG_NAME" >/dev/null 2>&1 || true
  fi
}

tpg_start() { # label
  local label=${1:-t}
  TPG_NAME="aisc-t-${label}-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  TPG_PW=$(python3 -c 'import secrets; print(secrets.token_hex(12))')
  PORT=$(tpg_free_port)
  if [ -z "$PORT" ] || [ "$PORT" = "5432" ]; then
    echo "throwaway-pg: refusing port '$PORT'" >&2; return 1
  fi
  # A caller with its own traps (that also call tpg_cleanup) sets TPG_OWN_TRAP=1.
  if [ -z "${TPG_OWN_TRAP:-}" ]; then
    trap 'tpg_cleanup' EXIT
    trap 'tpg_cleanup; exit 130' INT
    trap 'tpg_cleanup; exit 143' TERM
  fi
  docker run --rm -d --name "$TPG_NAME" -p "127.0.0.1:${PORT}:5432" \
    -e POSTGRES_USER="$TPG_SU" -e POSTGRES_PASSWORD="$TPG_PW" -e POSTGRES_DB=platform \
    "$TPG_IMAGE" >/dev/null || return 1
  echo "throwaway-pg: container $TPG_NAME on 127.0.0.1:$PORT" >&2
  local i
  for i in $(seq 1 60); do
    # -h 127.0.0.1 inside the container: the image's init server listens on the
    # socket only, so this succeeds once the real server is up.
    if docker exec "$TPG_NAME" psql -h 127.0.0.1 -U "$TPG_SU" -d platform -tAc 'SELECT 1' >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "throwaway-pg: $TPG_NAME did not come up" >&2
  return 1
}

# psql as the superuser, inside the container.
tpg_su() { # db, psql args...
  local db=$1; shift
  docker exec -i -e PGPASSWORD="$TPG_PW" "$TPG_NAME" \
    psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$TPG_SU" -d "$db" "$@"
}

# psql as a module role (dev password = role name, as init/platform-db.sql makes them).
tpg_as() { # db, role, psql args...
  local db=$1 role=$2; shift 2
  docker exec -i -e PGPASSWORD="$role" "$TPG_NAME" \
    psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$role" -d "$db" "$@"
}

# The version banner and pg_dump's per-run random \restrict key are dropped, so two dumps of
# the same schema are byte-identical.
tpg_dump() { # db, pg_dump args...
  local db=$1; shift
  docker exec -e PGPASSWORD="$TPG_PW" "$TPG_NAME" \
    pg_dump -h 127.0.0.1 -U "$TPG_SU" -d "$db" "$@" \
    | grep -v -e '^-- Dumped from' -e '^-- Dumped by' -e '^\\restrict ' -e '^\\unrestrict '
}

# A DSN on the throwaway port. Never the host's 5432.
tpg_dsn() { # role, db, [password]
  local role=$1 db=$2 pw=${3:-$1}
  echo "postgresql://${role}:${pw}@127.0.0.1:${PORT}/${db}"
}

# init/platform-db.sql and init/project-databases.sql, as the superuser, as
# the image's initdb and the postgres-setup service run them.
tpg_init_platform() { # tree (a checkout root holding init/)
  local tree=$1
  tpg_su postgres -f - < "$tree/init/platform-db.sql" >/dev/null
  tpg_su platform -f - < "$tree/init/project-databases.sql" >/dev/null
}

# Apply one platform migration the way platform_service.migrate does: in one
# transaction as platform_rw, recorded in core.schema_migration.
tpg_platform_migration() { # db, file
  local db=$1 file=$2 name
  name=$(basename "$file")
  {
    echo "SET search_path = core;"
    echo "CREATE TABLE IF NOT EXISTS core.schema_migration (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());"
    echo "BEGIN;"
    cat "$file"
    echo ";"
    echo "INSERT INTO core.schema_migration (name) VALUES ('$name');"
    echo "COMMIT;"
  } | tpg_as "$db" platform_rw -f -
}

# A database-scoped role setting (search_path) is keyed by database, so a copy
# made with CREATE DATABASE ... TEMPLATE loses it. Carry them over.
tpg_copy_db() { # template, new
  local tpl=$1 new=$2
  tpg_su postgres -c "CREATE DATABASE \"$new\" TEMPLATE \"$tpl\"" >/dev/null
  tpg_su postgres -tA -c "SELECT format('ALTER ROLE %I IN DATABASE %I SET %s;', r.rolname, '$new', unnest(s.setconfig))
       FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole
       JOIN pg_database d ON d.oid = s.setdatabase WHERE d.datname = '$tpl'" \
    | tpg_su postgres -f - >/dev/null
  tpg_su postgres -c "GRANT CONNECT ON DATABASE \"$new\" TO qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw, platform_rw, dashboard_ro" >/dev/null
}

# A project's database, made the way the platform provisions one (platform_service.projectdb,
# isolation I2.4, I19.2): created by platform_rw, then every pending file of the project template
# applied as platform_rw in one transaction under the platform's advisory lock, each recorded in
# provision.template_migration. Idempotent: a second call applies only files added since.
# The cluster needs init/project-databases.sql first (tpg_init_platform): templates 0007..0010 call
# aisc_setup.apply_role_setting, which it installs in template1. Prints the database name.
tpg_project_db() { # pid [template_dir]
  local pid dir db applied f name
  pid=$(printf '%s' "${1:-}" | tr 'A-F' 'a-f')
  dir=${2:-$TPG_ROOT/platform/project-template}
  if ! [[ "$pid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "tpg_project_db: not a project pid: '${1:-}'" >&2; return 1
  fi
  db=project_${pid//-/}
  if [ -z "$(tpg_su postgres -tA -c "SELECT 1 FROM pg_database WHERE datname = '$db'")" ]; then
    tpg_as platform platform_rw -c "CREATE DATABASE \"$db\"" >/dev/null || return 1
  fi
  applied=$(tpg_as "$db" platform_rw -tA -c \
    "SELECT name FROM provision.template_migration" 2>/dev/null || true)
  {
    echo "BEGIN;"
    echo "SELECT pg_advisory_xact_lock(8190233419);"
    echo "CREATE SCHEMA IF NOT EXISTS provision;"
    echo "CREATE TABLE IF NOT EXISTS provision.template_migration (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());"
    for f in $(ls "$dir"/*.sql | sort); do
      name=$(basename "$f")
      grep -qxF "$name" <<<"$applied" && continue
      cat "$f"
      echo ";"
      echo "INSERT INTO provision.template_migration (name) VALUES ('$name');"
    done
    echo "COMMIT;"
  } | tpg_as "$db" platform_rw -f - >/dev/null || return 1
  echo "$db"
}
