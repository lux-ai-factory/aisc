-- The engine: its schema in this project's database.
--
-- The schema is made here and owned by platform_rw; the tables are made only by the module's
-- own migrations, as engine_rw, which may connect, use and create in this schema and nowhere else.
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
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'engine_rw') THEN
    RAISE EXCEPTION 'role engine_rw does not exist: run init/platform-db.sql or init/report-roles.sql first';
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO engine_rw', current_database());
  PERFORM aisc_setup.apply_role_setting(
    format('ALTER ROLE engine_rw IN DATABASE %I SET search_path = engine', current_database()));
END
$grant$;

CREATE SCHEMA IF NOT EXISTS engine;
GRANT USAGE, CREATE ON SCHEMA engine TO engine_rw;
COMMENT ON SCHEMA engine IS 'Step 4: this project''s datasets, models, plugins, evaluations and measurements.';

DO $readers$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
    GRANT USAGE ON SCHEMA engine TO report_ro;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_ro') THEN
    GRANT USAGE ON SCHEMA engine TO dashboard_ro;
  END IF;
END
$readers$;
