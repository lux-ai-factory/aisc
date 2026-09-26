-- A layout's and a report's version belong to their project.
--
-- (system_id, project_id) references core.system (pid, project_id), so a layout or a report
-- cannot name project A and a version of project B. NO ACTION, as their system_id keys.
--
-- The keys need core.system to be unique on (pid, project_id), which the platform makes
-- (init/platform-db.sql on a fresh volume, platform migration 0004 and init/project-databases.sql
-- on an existing one); this role cannot. Where it is not there yet, a key is left out with a
-- notice, and init/project-databases.sql adds it under the same name on its next run.
-- 8190233523 is the lock those places take too.
DO $$
DECLARE
  k record;
BEGIN
  PERFORM pg_advisory_xact_lock(8190233523);
  FOR k IN SELECT * FROM (VALUES
      ('report_composer.layout',           'layout_system_id_project_id_fkey'),
      ('report_composer.generated_report', 'generated_report_system_id_project_id_fkey')
    ) AS t(table_name, constraint_name)
  LOOP
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = to_regclass(k.table_name) AND conname = k.constraint_name) THEN
      CONTINUE;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conrelid = 'core.system'::regclass AND conname = 'system_pid_project_id_key') THEN
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I FOREIGN KEY (system_id, project_id)'
                     ' REFERENCES core.system (pid, project_id)', k.table_name, k.constraint_name);
    ELSE
      RAISE NOTICE 'core.system has no unique (pid, project_id) yet: % is left to init/project-databases.sql',
        k.constraint_name;
    END IF;
  END LOOP;
END $$;
