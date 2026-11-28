-- The report's "Who did what" block reads who did the work and who checked it: the tasks, their parts, the doers
-- of each round and the sign-offs. report_ro reads those four tables and nothing else of schema work (not the
-- holds, the rules or the switch). Safe on an existing install: grants only.
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
    GRANT USAGE ON SCHEMA work TO report_ro;
    GRANT SELECT ON work.task, work.part, work.doer, work.sign_off TO report_ro;
  END IF;
END $g$;
