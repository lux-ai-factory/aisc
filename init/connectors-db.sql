-- The connectors service's role and schema (spec 2026-09-24-connectors-design.md, D1).
-- Superuser. Runs on a fresh volume from docker-entrypoint-initdb.d (80-connectors-db.sql) and on
-- every start from postgres-setup, which passes the password as a psql variable. Idempotent.
-- Deliberately no grant on schema engine: the freeze guard (G1) dumps engine's GRANTs too.
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
