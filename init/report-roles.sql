-- The report's two roles and the composer's schema (report run 2026-09-23, 02 D6 (a), D13).
-- Superuser. Runs on a fresh volume from docker-entrypoint-initdb.d (60-report-roles.sql, after the
-- superset database exists) and on every start from postgres-setup, which passes the passwords as
-- psql variables. Kept out of init/platform-db.sql and init/project-databases.sql on purpose: the
-- guard dumps those two (G1/G2).
\if :{?report_ro_password}
\else
\set report_ro_password report_ro
\endif
\if :{?report_composer_password}
\else
\set report_composer_password report_composer_rw
\endif

\connect platform

SELECT 'CREATE ROLE report_ro LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') \gexec
SELECT 'CREATE ROLE report_composer_rw LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_rw') \gexec
SELECT format('ALTER ROLE report_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'report_ro_password') \gexec
SELECT format('ALTER ROLE report_composer_rw WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'report_composer_password') \gexec

-- the renderer's sessions are read-only by default; its privileges are SELECT only anyway
ALTER ROLE report_ro SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE platform TO report_ro, report_composer_rw;
SELECT 'GRANT CONNECT ON DATABASE superset TO report_ro'
 WHERE EXISTS (SELECT 1 FROM pg_database WHERE datname = 'superset') \gexec

-- core: the renderer reads project and system; the composer also reads memberships
GRANT USAGE ON SCHEMA core TO report_ro, report_composer_rw;
GRANT SELECT ON core.project, core.system TO report_ro, report_composer_rw;
GRANT REFERENCES ON core.project, core.system TO report_composer_rw;
SELECT 'GRANT SELECT ON core.project_member TO report_composer_rw'
 WHERE to_regclass('core.project_member') IS NOT NULL \gexec
-- project_member is made by platform migration 0001 as platform_rw, possibly after this file ran
ALTER DEFAULT PRIVILEGES FOR ROLE platform_rw IN SCHEMA core GRANT SELECT ON TABLES TO report_composer_rw;

CREATE SCHEMA IF NOT EXISTS report_composer AUTHORIZATION report_composer_rw;
ALTER SCHEMA report_composer OWNER TO report_composer_rw;
COMMENT ON SCHEMA report_composer IS 'Step 7: report layouts, templates and generated reports.';
ALTER ROLE report_composer_rw IN DATABASE platform SET search_path = report_composer, core;
