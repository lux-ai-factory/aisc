-- The connectors service's role and schema.
-- Runs as the superuser, from docker-entrypoint-initdb.d on a fresh volume (as
-- 80-connectors-db.sql) and from postgres-setup, which passes the password as a psql variable.
-- Safe to run again. No grant on schema engine on purpose: the freeze guard
-- (scripts/guard-frozen.sh) compares engine's GRANTs too.
\if :{?connector_password}
\else
\set connector_password connector_rw
\endif

SELECT 'CREATE ROLE connector_rw LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'connector_rw') \gexec
SELECT format('ALTER ROLE connector_rw WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'connector_password') \gexec

GRANT CONNECT ON DATABASE platform TO connector_rw;
\connect platform
CREATE SCHEMA IF NOT EXISTS connector AUTHORIZATION connector_rw;
ALTER ROLE connector_rw IN DATABASE platform SET search_path = connector;
