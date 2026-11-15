-- The report composer's tables belong to report_composer_owner, a role no application logs in as.
--
-- Migrations run as report_composer_migrator (REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL), whose sessions
-- act as report_composer_owner; the composer connects as report_composer_rw, which from here on reads and
-- writes rows only: it cannot create, alter, truncate or put triggers on these tables, nor lift a guard. On
-- the layout revisions it may only insert and read. A generated report's references to the card versions it
-- covers and compares with restrict: the versions cannot be deleted from under it.
--
-- In a project database this stops first unless the schema is report_composer_owner's and the session acts
-- as report_composer_owner: the platform hands the schema over (template 0033) once postgres-setup has made
-- the role. Safe on an install whose tables report_composer_rw made: they are handed to the owner here.

DO $owner$
BEGIN
  IF current_database() ~ '^project_[0-9a-f]{32}$' AND (
       NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_owner')
       OR (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'report_composer')
          IS DISTINCT FROM 'report_composer_owner'
       OR current_user <> 'report_composer_owner') THEN
    RAISE EXCEPTION 'report_composer_owner is missing or does not own schema report_composer: run postgres-setup and the platform first, then migrate as report_composer_migrator (REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL)';
  END IF;
END
$owner$;

ALTER TABLE report_composer.generated_report
    DROP CONSTRAINT generated_report_system_id_fkey,
    ADD CONSTRAINT generated_report_system_id_fkey
        FOREIGN KEY (system_id) REFERENCES project.system (pid) ON DELETE RESTRICT,
    DROP CONSTRAINT generated_report_compare_to_fkey,
    ADD CONSTRAINT generated_report_compare_to_fkey
        FOREIGN KEY (compare_to) REFERENCES project.system (pid) ON DELETE RESTRICT;

DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_owner')
     OR current_user <> 'report_composer_owner' THEN
    RETURN;                                      -- a scratch database outside the stack: nothing to hand over
  END IF;
  -- what the runtime role made before it stopped migrating
  REASSIGN OWNED BY report_composer_rw TO report_composer_owner;
  REVOKE CREATE ON SCHEMA report_composer FROM report_composer_rw;
  GRANT USAGE ON SCHEMA report_composer TO report_composer_rw;

  REVOKE ALL ON ALL TABLES IN SCHEMA report_composer FROM report_composer_rw;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA report_composer TO report_composer_rw;
  REVOKE UPDATE, DELETE ON report_composer.layout_revision FROM report_composer_rw;
  -- the migrations' own record is the migrator's
  REVOKE ALL ON report_composer.schema_migration FROM report_composer_rw;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA report_composer FROM report_composer_rw;
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA report_composer TO report_composer_rw;
  ALTER DEFAULT PRIVILEGES FOR ROLE report_composer_owner IN SCHEMA report_composer
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO report_composer_rw;
  ALTER DEFAULT PRIVILEGES FOR ROLE report_composer_owner IN SCHEMA report_composer
    GRANT USAGE, SELECT ON SEQUENCES TO report_composer_rw;
END
$roles$;
