-- The report composer reads who is in a project.
--
-- core.project_member is made by 0001 as platform_rw, which owns it; the composer's role is made
-- by init/report-roles.sql. Default privileges for platform_rw in core would also cover
-- core.schema_migration, which no module may read, so the grant is on the one table, here, by its
-- owner. report-roles.sql grants the same when the table already exists, so the order of the two
-- does not matter. A volume without the role skips it.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_rw') THEN
    GRANT SELECT ON core.project_member TO report_composer_rw;
  END IF;
END $$;
