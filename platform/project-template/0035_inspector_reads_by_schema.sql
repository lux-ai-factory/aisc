-- The database inspector reads this project's database by schema, not as a reader of all data: every schema
-- but connection, llm and helper, which hold endpoints and keys (aisc_setup.inspector_reads,
-- init/project-database-setup.sql). postgres-setup applies the same rule on every start; this applies it to
-- a project made between two starts.
DO $inspector$
BEGIN
  IF to_regprocedure('aisc_setup.inspector_reads()') IS NULL THEN
    RAISE EXCEPTION 'aisc_setup.inspector_reads is missing: run init/project-database-setup.sql in this database'
      ' (postgres-setup does on every start)';
  END IF;
  PERFORM aisc_setup.inspector_reads();
END
$inspector$;
