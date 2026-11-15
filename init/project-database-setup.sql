-- What every project database holds from the superuser: the steps its owners may not do themselves, and
-- the alarm that keeps its guard triggers in place.
--
-- Runs as the superuser on every start, from postgres-setup: in template1, so every project database made
-- afterwards is a copy that has it, then in each existing project_<hex> database. After
-- init/project-databases.sql (which makes aisc_setup.apply_role_setting) and init/owner-roles.sql (the
-- roles named here). Safe to run again.

CREATE SCHEMA IF NOT EXISTS aisc_setup;
REVOKE ALL ON SCHEMA aisc_setup FROM PUBLIC;
GRANT USAGE ON SCHEMA aisc_setup TO platform_rw, platform_owner;

-- The platform's template runs as platform_owner now: it sets the module roles' search_path as before.
DO $setting$
BEGIN
  IF to_regprocedure('aisc_setup.apply_role_setting(text)') IS NULL THEN
    RAISE EXCEPTION 'aisc_setup.apply_role_setting is missing: run init/project-databases.sql first';
  END IF;
  GRANT EXECUTE ON FUNCTION aisc_setup.apply_role_setting(text) TO platform_owner;
END
$setting$;

-- A module schema belongs to its owner role. The platform's template makes the five module schemas, as
-- platform_owner, and hands each to its owner through this function, which changes the owner of one of
-- those five schemas, in a project database, and nothing else. The platform's runtime role keeps USAGE,
-- which it had as the schema's owner (it counts what the engine's ledger outbox still holds before a
-- project is deleted). The module's runtime role keeps USAGE and loses CREATE, which the template gave it:
-- only the module's migrator, acting as the owner, makes tables there. Only platform_owner may call it.
CREATE OR REPLACE FUNCTION aisc_setup.hand_schema_to_owner(schema_name text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
BEGIN
  IF schema_name IS NULL
     OR schema_name NOT IN ('qualification', 'controls', 'control_objectives', 'report_composer', 'engine') THEN
    RAISE EXCEPTION 'refused: % is not a module schema', left(coalesce(schema_name, 'null'), 80);
  END IF;
  IF current_database() !~ '^project_[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'refused: % is not a project database', current_database();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = schema_name || '_owner') THEN
    RAISE EXCEPTION 'role %_owner is missing: run init/owner-roles.sql (postgres-setup does on every start)',
      schema_name;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = schema_name) THEN
    RAISE EXCEPTION 'schema % does not exist', schema_name;
  END IF;
  EXECUTE format('ALTER SCHEMA %I OWNER TO %I', schema_name, schema_name || '_owner');
  EXECUTE format('GRANT USAGE ON SCHEMA %I TO platform_rw', schema_name);
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = schema_name || '_rw') THEN
    EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM %I', schema_name, schema_name || '_rw');
  END IF;
END
$fn$;
REVOKE ALL ON FUNCTION aisc_setup.hand_schema_to_owner(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION aisc_setup.hand_schema_to_owner(text) TO platform_owner;

-- The guard triggers: the same list as init/guard-triggers.txt (scripts/tests/test_owner_roles.py checks
-- that the two agree). Kept equal to it on every start.
CREATE TABLE IF NOT EXISTS aisc_setup.guard_trigger (
    table_name   text NOT NULL,
    trigger_name text NOT NULL,
    PRIMARY KEY (table_name, trigger_name)
);
REVOKE ALL ON aisc_setup.guard_trigger FROM PUBLIC;
GRANT SELECT ON aisc_setup.guard_trigger TO PUBLIC;
WITH listed (table_name, trigger_name) AS (VALUES
    ('trace.call', 'call_append_only'),
    ('trace.call', 'call_no_truncate'),
    ('project.system', 'system_no_delete'),
    ('project.system', 'system_no_truncate'),
    ('qualification.card_history', 'card_history_is_append_only'),
    ('qualification.card_history', 'card_history_is_not_truncated'),
    ('qualification.qualification', 'qualification_only_latest_changes'),
    ('qualification.qualification', 'qualification_no_delete'),
    ('qualification.qualification', 'qualification_no_truncate'),
    ('control_objectives.mapping_archive', 'mapping_archive_is_append_only'),
    ('control_objectives.mapping_archive', 'mapping_archive_is_never_truncated'),
    ('report_composer.layout_revision', 'layout_revision_is_append_only'),
    ('report_composer.layout_revision', 'layout_revision_is_never_truncated'),
    ('engine.aisc_backend_evaluation', 'evaluation_system_is_fixed'),
    ('engine.aisc_backend_measurement', 'aisc_backend_measurement_append_only'),
    ('engine.aisc_backend_measurement', 'aisc_backend_measurement_no_truncate'),
    ('engine.aisc_backend_observation', 'aisc_backend_observation_append_only'),
    ('engine.aisc_backend_observation', 'aisc_backend_observation_no_truncate'),
    ('engine.aisc_backend_ledgeroutbox', 'ledgeroutbox_only_marks'),
    ('engine.aisc_backend_ledgeroutbox', 'ledgeroutbox_no_delete'),
    ('engine.aisc_backend_ledgeroutbox', 'ledgeroutbox_no_truncate'),
    ('engine.aisc_backend_pluginconfig', 'pluginconfig_is_fixed'),
    ('engine.aisc_backend_pluginconfig', 'pluginconfig_no_truncate')
), unlisted AS (
    DELETE FROM aisc_setup.guard_trigger g
     WHERE NOT EXISTS (SELECT 1 FROM listed l WHERE l.table_name = g.table_name AND l.trigger_name = g.trigger_name)
)
INSERT INTO aisc_setup.guard_trigger (table_name, trigger_name)
SELECT table_name, trigger_name FROM listed ON CONFLICT DO NOTHING;

-- The alarm: a listed guard trigger that ends up disabled after an ALTER TABLE or ALTER TRIGGER, or that a
-- DROP removes (with its table or schema too), stops the statement, whoever runs it. Only the superuser can
-- get past it, by disabling the event trigger first; scripts/verify.sh then reports the lifted guard.
CREATE OR REPLACE FUNCTION aisc_setup.guard_triggers_stay() RETURNS event_trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
DECLARE
  hit record;
BEGIN
  IF TG_EVENT = 'sql_drop' THEN
    SELECT g.table_name, g.trigger_name INTO hit
      FROM pg_event_trigger_dropped_objects() d
      JOIN aisc_setup.guard_trigger g
        ON d.object_type = 'trigger'
       AND d.address_names[1] || '.' || d.address_names[2] = g.table_name
       AND d.address_names[3] = g.trigger_name
     LIMIT 1;
  ELSE
    SELECT g.table_name, g.trigger_name INTO hit
      FROM aisc_setup.guard_trigger g
      JOIN pg_trigger t ON t.tgrelid = to_regclass(g.table_name) AND t.tgname = g.trigger_name
     WHERE t.tgenabled <> 'O'
     LIMIT 1;
  END IF;
  IF hit.trigger_name IS NOT NULL THEN
    RAISE EXCEPTION 'guard trigger % on % cannot be disabled or dropped', hit.trigger_name, hit.table_name;
  END IF;
END
$fn$;
REVOKE ALL ON FUNCTION aisc_setup.guard_triggers_stay() FROM PUBLIC;

DO $alarm$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'aisc_guard_triggers_stay') THEN
    CREATE EVENT TRIGGER aisc_guard_triggers_stay ON ddl_command_end
      WHEN TAG IN ('ALTER TABLE', 'ALTER TRIGGER')
      EXECUTE FUNCTION aisc_setup.guard_triggers_stay();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'aisc_guard_triggers_stay_on_drop') THEN
    CREATE EVENT TRIGGER aisc_guard_triggers_stay_on_drop ON sql_drop
      EXECUTE FUNCTION aisc_setup.guard_triggers_stay();
  END IF;
END
$alarm$;
ALTER EVENT TRIGGER aisc_guard_triggers_stay ENABLE;
ALTER EVENT TRIGGER aisc_guard_triggers_stay_on_drop ENABLE;

-- The database inspector (init/inspector-role.sql) reads every schema here but the three that hold
-- endpoints and keys (connection, llm, helper): USAGE and SELECT on what is there, and SELECT on what the
-- platform, the modules and their owners make later. One function, so the platform's template applies the
-- same rule to a project made between two starts (platform/project-template/0035_inspector_reads_by_schema.sql).
CREATE OR REPLACE FUNCTION aisc_setup.inspector_reads() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
DECLARE
  s text;
  r text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'inspector_ro') THEN
    RETURN;
  END IF;
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname IN ('connection', 'llm', 'helper') LOOP
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM inspector_ro', s);
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM inspector_ro', s);
  END LOOP;
  FOR s IN SELECT nspname FROM pg_namespace
            WHERE nspname NOT IN ('connection', 'llm', 'helper', 'aisc_setup', 'information_schema', 'public')
              AND nspname NOT LIKE 'pg\_%' LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO inspector_ro', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO inspector_ro', s);
    FOR r IN SELECT rolname FROM pg_roles
              WHERE rolname IN ('platform_owner', 'platform_rw', s || '_rw', s || '_owner') LOOP
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO inspector_ro', r, s);
    END LOOP;
  END LOOP;
END
$fn$;
REVOKE ALL ON FUNCTION aisc_setup.inspector_reads() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION aisc_setup.inspector_reads() TO platform_owner;
SELECT aisc_setup.inspector_reads();
