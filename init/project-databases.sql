-- Project databases: one per project, made by the platform service.
--
-- Runs as the superuser, and is safe to run again: on a fresh volume from
-- docker-entrypoint-initdb.d, and on an existing one from the postgres-setup
-- service, which runs it on every start. It must keep running after the shared
-- module schemas and core.system are retired (isolation cutover C9) and after
-- they are dropped (stage 7): every line about core.system is guarded, and
-- nothing here touches the retired module schemas of the platform database
-- (docs/superpowers/isolation-2026-09-25/01-specs.md I2.8, 03-coding-plan.md P1-D3, G4).
--
-- CREATEDB is the whole of what the platform is given. It owns the databases it
-- makes and nothing else; the module roles are granted into each one by the
-- template it applies (platform/project-template/).
ALTER ROLE platform_rw CREATEDB;

-- New databases are copies of template1. On Postgres 14 its public schema lets
-- every role create tables, which would give each module a second, unowned place
-- to write in every project database.
\connect template1
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- The template gives each module role its own search_path in each project database
-- (ALTER ROLE <module role> IN DATABASE <that database> SET search_path = <its schema>). That
-- statement needs SUPERUSER or CREATEROLE, and platform_rw, which applies the template, has
-- neither (CREATEROLE on PG14 is close to superuser). So it runs through this one function,
-- owned by the superuser, that executes only that exact statement, for one of the four module
-- roles paired with its own schema, in the database it is called in, and refuses anything else.
-- In template1, so every database made afterwards has it; `isolate provision` installs it into a
-- project database made before this existed (platform_service.projectdb.install_setup_function).
CREATE SCHEMA IF NOT EXISTS aisc_setup;
REVOKE ALL ON SCHEMA aisc_setup FROM PUBLIC;
GRANT USAGE ON SCHEMA aisc_setup TO platform_rw;
CREATE OR REPLACE FUNCTION aisc_setup.apply_role_setting(stmt text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
DECLARE
  m text[];
BEGIN
  m := regexp_match(stmt,
    '^ALTER ROLE (qualification_rw|control_objectives_rw|engine_rw|report_composer_rw)'
    ' IN DATABASE (project_[0-9a-f]{32})'
    ' SET search_path = (qualification|control_objectives|engine|report_composer)$');
  IF m IS NULL OR m[1] <> m[3] || '_rw' OR m[2] <> current_database() THEN
    RAISE EXCEPTION 'refused: %', left(stmt, 200);
  END IF;
  EXECUTE stmt;
END
$fn$;
REVOKE ALL ON FUNCTION aisc_setup.apply_role_setting(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION aisc_setup.apply_role_setting(text) TO platform_rw;

\connect platform
-- The install-wide library of report presets (D4), for a volume made before init/platform-db.sql
-- made it. A missing role is skipped. (Forms are per project: there is no form library.)
DO $libraries$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_rw') THEN
    CREATE SCHEMA IF NOT EXISTS report_library AUTHORIZATION report_composer_rw;
  END IF;
END
$libraries$;

-- The ledger's Postgres side (docs/superpowers/ledger-2026-10-02/02-spec.md 6.1): the platform
-- service owns it and its migrations (0006 onwards) make its tables. No module role gets USAGE, so
-- none can read the witness records, the person mapping or the pool. Making a schema takes a
-- superuser, hence here (every start) and in init/platform-db.sql (a fresh volume), not in a migration.
DO $ledger$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    CREATE SCHEMA ledger AUTHORIZATION platform_rw;
  END IF;
END
$ledger$;
REVOKE ALL ON SCHEMA ledger FROM PUBLIC;

-- The pre-isolation core.system, only while it is in use: absent (a fresh volume, or after the
-- stage-7 drop) or retired (its comment begins with 'retired:', set by cutover C9), none of this
-- runs, so a start after the retirement cannot give it back to anyone.
--
-- While in use: core.system is the platform's to migrate (platform migration 0003 adds its
-- version number and the only-latest rule). It was made by the superuser in the pre-isolation
-- init/platform-db.sql; this hands it over, and again changes nothing.
--
-- A card version belongs to its project (platform migration 0004). core.system is unique on
-- (pid, project_id), and the module tables that pin their work to one version point at that
-- pair, so a row cannot name a version of another project. On an existing volume a module may
-- migrate before this file or the platform runs: its migration then finds no constraint to point
-- at, leaves its key out and says so. This adds the constraint, and then any such key that is
-- missing, under the module's own name and ON DELETE rule (the same statement as its migration).
-- A table that does not exist yet is skipped: its module's migration adds the key when it makes
-- it. 8190233523 is the lock the module migrations and platform 0004 take too.
DO $$
DECLARE
  k record;
BEGIN
  IF to_regclass('core.system') IS NULL
     OR coalesce(obj_description(to_regclass('core.system'), 'pg_class'), '') LIKE 'retired:%' THEN
    RETURN;
  END IF;
  EXECUTE 'ALTER TABLE core.system OWNER TO platform_rw';
  PERFORM pg_advisory_xact_lock(8190233523);
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = to_regclass('core.system') AND conname = 'system_pid_project_id_key') THEN
    EXECUTE 'ALTER TABLE core.system ADD CONSTRAINT system_pid_project_id_key UNIQUE (pid, project_id)';
  END IF;
  FOR k IN SELECT * FROM (VALUES
      ('qualification.qualification',      'qualification_system_id_project_id_fkey',     'CASCADE'),
      ('control_objectives.project',       'fk_project_system_id_project_id_core_system', 'CASCADE'),
      ('report_composer.layout',           'layout_system_id_project_id_fkey',            'NO ACTION'),
      ('report_composer.generated_report', 'generated_report_system_id_project_id_fkey',  'NO ACTION')
    ) AS t(table_name, constraint_name, on_delete)
  LOOP
    IF to_regclass(k.table_name) IS NOT NULL AND NOT EXISTS (
         SELECT 1 FROM pg_constraint
          WHERE conrelid = to_regclass(k.table_name) AND conname = k.constraint_name) THEN
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I FOREIGN KEY (system_id, project_id)'
                     ' REFERENCES core.system (pid, project_id) ON DELETE %s',
                     k.table_name, k.constraint_name, k.on_delete);
    END IF;
  END LOOP;
END $$;
