-- Control objectives: its schema in this project's database.
--
-- The schema is made here and owned by platform_rw; the tables are made only by the module's
-- own migrations, as control_objectives_rw, which may connect, use and create in this schema and nowhere else.
-- The readers get USAGE only: SELECT on the tables comes from the module's migrations.
--
-- The search_path setting: platform_rw cannot run ALTER ROLE <another role> IN DATABASE on PG14
-- (it needs SUPERUSER or CREATEROLE), so the statement goes through aisc_setup.apply_role_setting,
-- a SECURITY DEFINER function that runs only this exact kind of statement for this database
-- (init/project-databases.sql puts it in template1; `isolate provision` adds it to an older database).
DO $grant$
BEGIN
  IF to_regproc('aisc_setup.apply_role_setting') IS NULL THEN
    RAISE EXCEPTION 'aisc_setup.apply_role_setting is missing: run init/project-databases.sql (postgres-setup) or isolate provision';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'control_objectives_rw') THEN
    RAISE EXCEPTION 'role control_objectives_rw does not exist: run init/platform-db.sql or init/report-roles.sql first';
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO control_objectives_rw', current_database());
  PERFORM aisc_setup.apply_role_setting(
    format('ALTER ROLE control_objectives_rw IN DATABASE %I SET search_path = control_objectives', current_database()));
END
$grant$;

CREATE SCHEMA IF NOT EXISTS control_objectives;
GRANT USAGE, CREATE ON SCHEMA control_objectives TO control_objectives_rw;
COMMENT ON SCHEMA control_objectives IS 'Step 2: this project''s assessment, its risks, mappings and their runs.';

DO $readers$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
    GRANT USAGE ON SCHEMA control_objectives TO report_ro;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_ro') THEN
    GRANT USAGE ON SCHEMA control_objectives TO dashboard_ro;
  END IF;
END
$readers$;
