#!/usr/bin/env bash
# Is every guard trigger of every project database there, enabled, and on a table its owner role holds?
#
#   ./scripts/verify-guard-triggers.sh
#
# The guards are the lines of init/guard-triggers.txt. For each project_<hex> database it prints one FAIL line
# per problem (missing, disabled, or a guarded table not owned by its schema's owner role) and a final
# PASS|FAIL line with the count; exit status 1 on any problem (scripts/stackcheck/guard_triggers.py).
# The event trigger aisc_guard_triggers_stay refuses lifting a guard to everyone but the superuser, who can
# drop it first: this is the alarm for that case.
#
# Connection: PGHOST (127.0.0.1), PGPORT (5432), PGUSER and PGPASSWORD, the superuser's from env.runtime
# when unset. Read-only (catalogue queries only); the password is never printed.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
export PGHOST=${PGHOST:-127.0.0.1} PGPORT=${PGPORT:-5432}
if [ -z "${PGUSER:-}" ]; then
  PGUSER=$(awk 'index($0, "POSTGRES_USER=") == 1 { sub(/\r$/, ""); print substr($0, 15); exit }' "$ROOT/env.runtime" 2>/dev/null)
fi
if [ -z "${PGPASSWORD:-}" ]; then
  PGPASSWORD=$(awk 'index($0, "POSTGRES_PASSWORD=") == 1 { sub(/\r$/, ""); print substr($0, 19); exit }' "$ROOT/env.runtime" 2>/dev/null)
fi
if [ -z "${PGUSER:-}" ] || [ -z "${PGPASSWORD:-}" ]; then
  echo "no superuser: set PGUSER and PGPASSWORD, or run scripts/secrets.sh to write env.runtime" >&2
  exit 2
fi
export PGUSER PGPASSWORD
. "$HERE/lib/database-published.sh"
cd "$HERE" && exec uv run --no-project --quiet --with 'psycopg[binary]' python -m stackcheck.guard_triggers
