-- Project databases: one per project, made by the platform service.
--
-- Runs as the superuser, and is safe to run again: on a fresh volume from
-- docker-entrypoint-initdb.d, and on an existing one from the postgres-setup
-- service, which runs it on every start.
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

-- core.system is the platform's to migrate (platform migration 0003 adds its version number and
-- the only-latest rule). It was made by the superuser in init/platform-db.sql; this runs as the
-- superuser on every start of postgres-setup, and again changes nothing.
\connect platform
ALTER TABLE core.system OWNER TO platform_rw;

-- A card version belongs to its project (platform migration 0004). core.system is unique on
-- (pid, project_id), and the module tables that pin their work to one version point at that
-- pair, so a row cannot name a version of another project.
--
-- init/platform-db.sql makes the constraint on a fresh volume, before any module can connect.
-- On an existing volume a module may migrate before this file or the platform runs: its
-- migration then finds no constraint to point at, leaves its key out and says so. This adds
-- the constraint, and then any such key that is missing, under the module's own name and ON
-- DELETE rule (the same statement as its migration). A table that does not exist yet is
-- skipped: its module's migration adds the key when it makes it. 8190233523 is the lock the
-- module migrations and platform 0004 take too.
DO $$
DECLARE
  k record;
BEGIN
  PERFORM pg_advisory_xact_lock(8190233523);
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'core.system'::regclass AND conname = 'system_pid_project_id_key') THEN
    ALTER TABLE core.system ADD CONSTRAINT system_pid_project_id_key UNIQUE (pid, project_id);
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
