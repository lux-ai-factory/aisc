#!/bin/sh
# The report-grants one-shot: the superuser's repair of the readers' grants.
#
# Every module's tables live in each project's own database project_<hex>, and each module grants
# report_ro and dashboard_ro its tables of the reader list (below) from its own migrations. This
# one-shot is the backstop: in every project database it (re)grants exactly that
# list to both readers and takes away anything else, so a database migrated before a reader
# existed, or a grant revoked by hand, is repaired on the next start. It also grants report_ro the
# superset tables of init/report-ro-grants.sql. `platform` gets nothing from here: the readers'
# rights there come from the init files.
#
# Superuser, idempotent, safe on a project database whose modules have not migrated yet (a table
# that is not there is skipped). Prints database names only. Runs after the module migrate
# one-shots (compose depends_on).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)

until pg_isready -q; do sleep 1; done

psql -v ON_ERROR_STOP=1 -d postgres -f "$HERE/report-ro-grants.sql"

# Databases made later are copies of template1, so an old default privilege there for report_ro on
# controls_rw's tables (it would also cover _prisma_migrations and any later table) is taken away.
psql -v ON_ERROR_STOP=1 -d template1 <<'SQL'
DO $undo$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'controls_rw')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
        EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw REVOKE SELECT ON TABLES FROM report_ro';
    END IF;
END
$undo$;
SQL

for db in $(psql -d postgres -tAc "SELECT datname FROM pg_database WHERE datname ~ '^project_[0-9a-f]{32}$' ORDER BY 1"); do
  psql -v ON_ERROR_STOP=1 -d "$db" <<'SQL'
DO $grants$
DECLARE
    -- exhaustive: the one reader list, for report_ro and dashboard_ro; it must equal READER_TABLES of
    -- scripts/verify-project-databases.sh (scripts/tests/test_report_grants.py checks)
    listed text[] := ARRAY[
        'project.system',
        'target.target',
        'controls.checklist', 'controls.checklist_question', 'controls.source', 'controls.submission',
        'controls.submission_answer',
        'qualification.qualification', 'qualification.qualification_answer', 'qualification.qualification_risk',
        'qualification.knowledge_graph', 'qualification.card_component', 'qualification.question_set',
        'qualification.question_set_version', 'qualification.question_set_version_item', 'qualification.question',
        'qualification.questionnaire', 'qualification.questionnaire_version', 'qualification.questionnaire_version_item',
        'control_objectives.project', 'control_objectives.graph', 'control_objectives.risk',
        'control_objectives.mapped_objective', 'control_objectives.mapping_run',
        'control_objectives.objective_selection', 'control_objectives.objective_key',
        'control_objectives.objective_set', 'control_objectives.objective_set_version',
        'control_objectives.objective_set_version_item', 'control_objectives.objective_profile',
        'control_objectives.objective_profile_version', 'control_objectives.objective_profile_version_item']
        || ARRAY(SELECT 'engine.' || t FROM unnest(ARRAY[
            'aisc_backend_project', 'aisc_backend_aisystem', 'aisc_backend_aicomponent', 'aisc_backend_evaluation',
            'aisc_backend_evaluationplugin', 'aisc_backend_evaluationinput', 'aisc_backend_plugin', 'aisc_backend_observation',
            'aisc_backend_measurement', 'aisc_backend_metric', 'aisc_backend_direct', 'aisc_backend_derived',
            'aisc_backend_metriccategory', 'aisc_backend_metriccategory_metrics', 'aisc_backend_artifact']) AS t);
    -- the schemas a reader may enter (report_composer: USAGE only, no table)
    schemas text[] := ARRAY['project', 'target', 'controls', 'qualification', 'control_objectives', 'engine', 'report_composer'];
    -- the schemas whose other tables a reader must not read: the above, plus secrets and bookkeeping
    guarded text[] := ARRAY['project', 'target', 'controls', 'qualification', 'control_objectives', 'engine',
                            'report_composer', 'llm', 'connection', 'provision'];
    reader text;
    s text;
    rel text;
BEGIN
    FOREACH reader IN ARRAY ARRAY['report_ro', 'dashboard_ro'] LOOP
        CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = reader);
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), reader);
        FOREACH s IN ARRAY schemas LOOP
            IF to_regnamespace(s) IS NOT NULL THEN
                EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, reader);
            END IF;
        END LOOP;
        -- everything else first: every table of the guarded schemas, every right
        FOR rel IN SELECT format('%I.%I', n.nspname, c.relname) FROM pg_class c
                     JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = ANY (guarded) AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                      AND (n.nspname || '.' || c.relname) <> ALL (listed) LOOP
            EXECUTE format('REVOKE ALL ON %s FROM %I', rel, reader);
        END LOOP;
        -- then the list: SELECT and nothing more
        FOREACH rel IN ARRAY listed LOOP
            IF to_regclass(rel) IS NOT NULL THEN
                EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON %s FROM %I', rel, reader);
                EXECUTE format('GRANT SELECT ON %s TO %I', rel, reader);
            END IF;
        END LOOP;
        -- plugin_config.config may hold tool settings: only the columns that tie a run to its tool,
        -- and the configuration's name, which the report's Test runs block prints (2026-09-28)
        IF to_regclass('engine.aisc_backend_pluginconfig') IS NOT NULL THEN
            EXECUTE format('GRANT SELECT (id, plugin_id, name) ON engine.aisc_backend_pluginconfig TO %I', reader);
        END IF;
    END LOOP;
    -- no reader right by a default privilege: it would also cover secrets and later tables (I2.6)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'controls_rw') THEN
        FOREACH reader IN ARRAY ARRAY['report_ro', 'dashboard_ro'] LOOP
            CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = reader);
            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw REVOKE SELECT ON TABLES FROM %I', reader);
            IF to_regnamespace('controls') IS NOT NULL THEN
                EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw IN SCHEMA controls'
                               ' REVOKE SELECT ON TABLES FROM %I', reader);
            END IF;
        END LOOP;
    END IF;
END
$grants$;
SQL
  echo "[report-grants] $db"
done
echo "[report-grants] done"
