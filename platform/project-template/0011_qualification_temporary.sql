-- qualification may make temporary tables in this project's database.
--
-- 0001 revokes every database right from PUBLIC, TEMPORARY included, and the module templates
-- give back CONNECT only. qualification's two-level forms migration (20260925150000) keeps its
-- bookkeeping in a temporary table (ON COMMIT DROP), so its role needs TEMPORARY here. A
-- temporary table lives in its session only: no other role sees it, and nothing is kept.
DO $grant$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qualification_rw') THEN
    RAISE EXCEPTION 'role qualification_rw does not exist: run init/platform-db.sql or init/report-roles.sql first';
  END IF;
  EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO qualification_rw', current_database());
END
$grant$;
