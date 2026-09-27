-- The report's two roles and the composer's library schema (report run 2026-09-23, 02 D6 (a), D13).
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

-- core (isolation 2026-09-25, 01-specs.md I1.4): the renderer reads the project here and everything
-- else in the project's own database; the composer also reads memberships. No core.system (it lives
-- in each project database as project.system) and no REFERENCES (no composer table here points at
-- core any more).
GRANT USAGE ON SCHEMA core TO report_ro, report_composer_rw;
GRANT SELECT ON core.project TO report_ro, report_composer_rw;
-- project_member is made by platform migration 0001 as platform_rw, possibly after this file ran;
-- platform migration 0005 grants the same, so the order does not matter
SELECT 'GRANT SELECT ON core.project_member TO report_composer_rw'
 WHERE to_regclass('core.project_member') IS NOT NULL \gexec

-- The composer's schemas: report_composer lives in each project database (template
-- 0010_report_composer.sql); here only the install-wide library of presets (D4), which
-- init/platform-db.sql makes on a fresh volume. Nothing here touches the retired shared
-- report_composer schema (03-coding-plan.md P1-D3, G4).
CREATE SCHEMA IF NOT EXISTS report_library AUTHORIZATION report_composer_rw;
ALTER ROLE report_composer_rw IN DATABASE platform SET search_path = report_library, core;
