-- The platform's objects here belong to platform_owner; platform_rw, the role its requests run as, keeps
-- reading and writing rows and nothing more. Owning a table is what lets a role disable its triggers,
-- truncate, alter or drop it, so the role the requests use owns nothing (init/owner-roles.sql).
--
-- From this migration on the platform migrates as platform_migrator, whose sessions act as platform_owner
-- (PLATFORM_MIGRATE_DATABASE_URL). platform_owner is a member of platform_rw, so it may hand over what
-- platform_rw owns. Only what platform_rw owns moves: core.project stays the superuser's, as
-- init/platform-db.sql made it. Running it again changes nothing.

DO $handover$
DECLARE
  s text;
  o record;
BEGIN
  IF current_user <> 'platform_owner' THEN
    RAISE EXCEPTION 'platform migrations run as platform_migrator, whose sessions act as platform_owner, not as %:'
      ' run init/owner-roles.sql (postgres-setup does on every start) and set PLATFORM_MIGRATE_DATABASE_URL',
      current_user;
  END IF;
  FOREACH s IN ARRAY ARRAY['core', 'ledger'] LOOP
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
  END LOOP;

  -- platform_rw reads and writes the rows of what it owned, as before: no TRIGGER, TRUNCATE or REFERENCES
  GRANT USAGE ON SCHEMA ledger TO platform_rw;
  FOR o IN SELECT n.nspname, c.relname, c.relkind
             FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('core', 'ledger') AND pg_get_userbyid(c.relowner) = 'platform_owner'
              AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  LOOP
    IF o.relkind = 'S' THEN
      EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I.%I TO platform_rw', o.nspname, o.relname);
    ELSE
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I.%I TO platform_rw', o.nspname, o.relname);
    END IF;
  END LOOP;
END
$handover$;

-- what later migrations make, platform_rw may use the same way
ALTER DEFAULT PRIVILEGES FOR ROLE platform_owner IN SCHEMA core, ledger
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO platform_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE platform_owner IN SCHEMA core, ledger
    GRANT USAGE, SELECT ON SEQUENCES TO platform_rw;
