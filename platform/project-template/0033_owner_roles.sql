-- This project's database and the platform's schemas in it belong to platform_owner; each module schema
-- belongs to its module's owner role. platform_rw, the role the platform's requests run as, keeps reading
-- and writing rows and nothing more: owning a table is what lets a role disable its triggers, truncate,
-- alter or drop it (init/owner-roles.sql).
--
-- Applied as platform_migrator, whose sessions act as platform_owner; platform_owner is a member of
-- platform_rw, so it may hand over what platform_rw owns. Only what platform_rw owns moves. The module
-- schemas are handed over by aisc_setup.hand_schema_to_owner (init/project-database-setup.sql), since
-- giving an object to another role's owner takes the superuser.
--
-- The schema `catalogue`, which platform_rw makes when the project chooses its catalogue, stays platform_rw's
-- (platform_service/catalogue.py makes and changes its tables at that choice and at each update): platform_rw
-- keeps CREATE on this database for it.
DO $handover$
DECLARE
  s text;
  o record;
BEGIN
  IF current_user <> 'platform_owner' THEN
    RAISE EXCEPTION 'the project template is applied as platform_migrator, whose sessions act as platform_owner,'
      ' not as %: run init/owner-roles.sql (postgres-setup does on every start) and set'
      ' PLATFORM_MIGRATE_DATABASE_URL', current_user;
  END IF;
  IF to_regprocedure('aisc_setup.hand_schema_to_owner(text)') IS NULL THEN
    RAISE EXCEPTION 'aisc_setup.hand_schema_to_owner is missing: run init/project-database-setup.sql in this'
      ' database (postgres-setup does on every start)';
  END IF;

  IF (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()) <> 'platform_owner' THEN
    EXECUTE format('ALTER DATABASE %I OWNER TO platform_owner', current_database());
  END IF;
  EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO platform_rw', current_database());

  FOREACH s IN ARRAY ARRAY['project', 'evidence', 'trace', 'ledger', 'provision', 'connection', 'helper', 'llm',
                           'target'] LOOP
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s);
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s AND pg_get_userbyid(nspowner) = 'platform_rw') THEN
      EXECUTE format('ALTER SCHEMA %I OWNER TO platform_owner', s);
    END IF;
    -- tables, views and sequences of their own (a column's sequence follows its table)
    FOR o IN SELECT c.relname, c.relkind
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = s AND pg_get_userbyid(c.relowner) = 'platform_rw'
                AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
                AND NOT (c.relkind = 'S' AND EXISTS (
                      SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a', 'i')))
    LOOP
      EXECUTE format('ALTER %s %I.%I OWNER TO platform_owner',
                     CASE o.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                                    WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END, s, o.relname);
    END LOOP;
    FOR o IN SELECT p.oid::regprocedure AS sig, p.prokind
               FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname = s AND pg_get_userbyid(p.proowner) = 'platform_rw'
    LOOP
      EXECUTE format('ALTER %s %s OWNER TO platform_owner',
                     CASE o.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END, o.sig);
    END LOOP;

    -- platform_rw reads and writes rows, as before: no TRIGGER, TRUNCATE or REFERENCES. Card versions are
    -- never deleted and a recorded call never changes, so neither is granted there.
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO platform_rw', s);
    FOR o IN SELECT c.relname, c.relkind
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = s AND pg_get_userbyid(c.relowner) = 'platform_owner'
                AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    LOOP
      IF o.relkind = 'S' THEN
        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I.%I TO platform_rw', s, o.relname);
      ELSIF s = 'project' AND o.relname = 'system' THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON project.system TO platform_rw';
      ELSIF s = 'trace' AND o.relname = 'call' THEN
        EXECUTE 'GRANT SELECT, INSERT ON trace.call TO platform_rw';
      ELSE
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I.%I TO platform_rw', s, o.relname);
      END IF;
    END LOOP;
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO platform_rw', s);
    -- what later template files make, platform_rw may use the same way
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE platform_owner IN SCHEMA %I'
                   ' GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO platform_rw', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE platform_owner IN SCHEMA %I'
                   ' GRANT USAGE, SELECT ON SEQUENCES TO platform_rw', s);
  END LOOP;

  FOREACH s IN ARRAY ARRAY['qualification', 'controls', 'control_objectives', 'report_composer', 'engine'] LOOP
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s);
    PERFORM aisc_setup.hand_schema_to_owner(s);
  END LOOP;
END
$handover$;
