-- The database inspector (pgAdmin and SchemaSpy, behind the launcher's admin gate): one role that
-- reads the tables of the schemas it is given and writes none. It is not a reader of all data: a project's
-- connection, llm and helper schemas, which hold endpoints and keys, are not given to it
-- (aisc_setup.inspector_reads, init/project-database-setup.sql, run in each project database).
-- Runs as the superuser, from docker-entrypoint-initdb.d on a fresh volume (as
-- 70-inspector-role.sql, after the superset database exists) and on every start from
-- postgres-setup, which passes the password as a psql variable. Each project database lets it connect through the project template
-- (platform/project-template/0004_inspector.sql).
\if :{?inspector_password}
\else
\set inspector_password inspector_ro
\endif

SELECT 'CREATE ROLE inspector_ro LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'inspector_ro') \gexec
SELECT format('ALTER ROLE inspector_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'inspector_password') \gexec

-- Sessions cannot write either. Earlier versions of this file made it a reader of all data: taken back.
REVOKE pg_read_all_data FROM inspector_ro;
ALTER ROLE inspector_ro SET default_transaction_read_only = on;

-- pg_read_all_data reaches every database a role can connect to, and PUBLIC may connect to these
-- two by default: Keycloak's holds the password hashes, Superset's the dashboard's secrets. Only
-- the superuser uses them, and it connects either way, so closing them to PUBLIC changes nothing
-- else. report_ro keeps the CONNECT on superset that init/report-roles.sql grants it by name.
SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', datname)
  FROM pg_database WHERE datname IN ('keycloak', 'superset') \gexec

GRANT CONNECT ON DATABASE platform TO inspector_ro;

-- In the platform database it reads the projects (core) and the ledger's Postgres side, what is there and
-- what the platform's migrations make later (they run as platform_owner, init/owner-roles.sql, which
-- postgres-setup runs before this file).
GRANT USAGE ON SCHEMA core TO inspector_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO inspector_ro;
DO $ledger$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    GRANT USAGE ON SCHEMA ledger TO inspector_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA ledger TO inspector_ro;
  END IF;
END
$ledger$;
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO inspector_ro',
              r.rolname, n.nspname)
  FROM pg_roles r CROSS JOIN pg_namespace n
 WHERE r.rolname IN ('platform_owner', 'platform_rw') AND n.nspname IN ('core', 'ledger') \gexec

-- Nobody connects to the platform database by right of PUBLIC: every role that works there holds CONNECT of
-- its own (init/platform-db.sql, init/report-roles.sql, init/owner-roles.sql and the line above).
REVOKE CONNECT, TEMPORARY ON DATABASE platform FROM PUBLIC;
