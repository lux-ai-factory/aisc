-- The report composer reads who is in a project (isolation 2026-09-25, 01-specs.md I1.4).
--
-- core.project_member is made by 0001 as platform_rw, which owns it; the composer's role came
-- later (init/report-roles.sql). That file used to cover it with default privileges for
-- platform_rw in core, which would also have covered core.schema_migration, which no module may
-- read (I1.4). A grant on the one table instead, here, by its owner. report-roles.sql grants the
-- same when the table already exists, so the order of the two does not matter. A volume without
-- the role skips it.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_rw') THEN
    GRANT SELECT ON core.project_member TO report_composer_rw;
  END IF;
END $$;
