#!/bin/sh
# The report-grants one-shot: SELECT for report_ro on the tables the report reads, in the platform
# and superset databases and in every project database. Superuser, idempotent, runs on every
# start after the module migrations. Design: docs/superpowers/report-2026-09-23/02-architecture.md,
# deviation D6.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
WAIT=${REPORT_GRANTS_WAIT_SECONDS:-600}

until pg_isready -q; do sleep 1; done

# The engine's tables come from aisc-backend's own migrations, which no one-shot waits for.
i=0
until [ "$(psql -d platform -tAc "SELECT to_regclass('engine.measurement') IS NOT NULL")" = "t" ]; do
  i=$((i + 1))
  if [ "$i" -ge "$WAIT" ]; then
    echo "[report-grants] engine.measurement is not there after ${WAIT}s; granting what exists"
    break
  fi
  sleep 1
done

psql -v ON_ERROR_STOP=1 -d platform -f "$HERE/report-ro-grants.sql"

# Every project database: the controls tables are owned by controls_rw.
for db in $(psql -d platform -tAc "SELECT datname FROM pg_database WHERE datname ~ '^project_[0-9a-f]{32}$' ORDER BY 1"); do
  psql -v ON_ERROR_STOP=1 -d "$db" <<'SQL'
DO $grants$
DECLARE
    t text;
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO report_ro', current_database());
    IF to_regnamespace('controls') IS NOT NULL THEN
        EXECUTE 'GRANT USAGE ON SCHEMA controls TO report_ro';
        FOREACH t IN ARRAY ARRAY['checklist', 'checklist_question', 'submission',
                                 'submission_answer', 'source'] LOOP
            IF to_regclass('controls.' || t) IS NOT NULL THEN
                EXECUTE format('GRANT SELECT ON controls.%I TO report_ro', t);
            END IF;
        END LOOP;
    END IF;
END
$grants$;
SQL
  echo "[report-grants] $db"
done

# Databases made later are copies of template1: controls_rw's tables there become readable too.
psql -v ON_ERROR_STOP=1 -d template1 -c \
  "ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw GRANT SELECT ON TABLES TO report_ro"
echo "[report-grants] done"
