-- keycloak_app owns Keycloak's database, so Keycloak no longer connects as the Postgres superuser (which could read
-- every project's database).
-- Runs as the superuser on every start from postgres-setup, which passes the password as the psql
-- variable app_password (scripts/secrets.sh makes KEYCLOAK_DB_PASSWORD); without one it leaves the
-- password as it is. Safe to run again.
-- On a volume made before this file, what the superuser created in the database is handed over;
-- ALTER ... OWNER keeps the grants others hold (report_ro reads superset). A volume without the
-- database is left alone.
SELECT 'CREATE ROLE keycloak_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak_app') \gexec
\if :{?app_password}
SELECT format('ALTER ROLE keycloak_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_password') \gexec
\endif

SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak') AS has_database \gset
\if :has_database
ALTER DATABASE keycloak OWNER TO keycloak_app;
\connect keycloak
ALTER SCHEMA public OWNER TO keycloak_app;
SELECT format('ALTER TABLE %I.%I OWNER TO keycloak_app', schemaname, tablename)
  FROM pg_tables WHERE schemaname = 'public' \gexec
-- a serial's sequence follows its table; the others are handed over here
SELECT format('ALTER SEQUENCE %I.%I OWNER TO keycloak_app', schemaname, sequencename)
  FROM pg_sequences WHERE schemaname = 'public' \gexec
SELECT format('ALTER VIEW %I.%I OWNER TO keycloak_app', schemaname, viewname)
  FROM pg_views WHERE schemaname = 'public' \gexec
SELECT format('ALTER MATERIALIZED VIEW %I.%I OWNER TO keycloak_app', schemaname, matviewname)
  FROM pg_matviews WHERE schemaname = 'public' \gexec
-- functions and types, except an extension's own (they stay with the extension); a range's
-- multirange follows it
SELECT format('ALTER ROUTINE %s OWNER TO keycloak_app', p.oid::regprocedure)
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                     AND d.deptype = 'e') \gexec
SELECT format('ALTER TYPE %I.%I OWNER TO keycloak_app', n.nspname, t.typname)
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd', 'r')
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid
                     AND d.deptype = 'e') \gexec
\endif
