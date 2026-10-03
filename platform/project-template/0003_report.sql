-- The report: its renderer reads this project's answers as report_ro. It may connect and
-- look into the controls schema; the SELECT on the tables comes from the report-grants one-shot
-- (controls_rw owns them) and template1's default privileges. Nothing here lets it write.
-- Skipped where report_ro does not exist (a database without the report's roles).
DO $grant$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO report_ro', current_database());
        EXECUTE 'GRANT USAGE ON SCHEMA controls TO report_ro';
    END IF;
END
$grant$;
