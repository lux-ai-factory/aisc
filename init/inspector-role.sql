-- The database inspector (pgAdmin and SchemaSpy, behind the launcher's admin gate): one role that
-- reads every table and writes none.
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

-- SELECT on everything, in every database it may connect to; sessions cannot write either.
GRANT pg_read_all_data TO inspector_ro;
ALTER ROLE inspector_ro SET default_transaction_read_only = on;

-- pg_read_all_data reaches every database a role can connect to, and PUBLIC may connect to these
-- two by default: Keycloak's holds the password hashes, Superset's the dashboard's secrets. Only
-- the superuser uses them, and it connects either way, so closing them to PUBLIC changes nothing
-- else. report_ro keeps the CONNECT on superset that init/report-roles.sql grants it by name.
SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', datname)
  FROM pg_database WHERE datname IN ('keycloak', 'superset') \gexec

GRANT CONNECT ON DATABASE platform TO inspector_ro;
