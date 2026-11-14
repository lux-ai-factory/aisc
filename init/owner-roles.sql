-- Owner roles and migrator logins: who may change a schema, as against who uses it.
--
-- Each module schema belongs to a NOLOGIN owner role, <module>_owner. Only its migrator, the LOGIN role
-- <module>_migrator, reaches it: the migrator is a member of the owner and every session it opens starts
-- as the owner (ALTER ROLE ... SET role), so what a migration makes belongs to the owner. The runtime
-- roles the apps connect as (<module>_rw) are not members of their owner: a request can read and write
-- rows, never lift a guard trigger, truncate or drop what the guards protect.
--
-- Each owner is a member of its runtime role, so a migration can hand the runtime role's older objects
-- over to the owner (ALTER ... OWNER) and keeps whatever the runtime role was granted.
--
-- platform_owner alone may create databases: the platform makes and drops project databases through
-- platform_migrator (PLATFORM_MIGRATE_DATABASE_URL), and ends other roles' sessions on a project database
-- only through aisc_setup.end_project_sessions, below, instead of pg_signal_backend.
--
-- Runs as the superuser in the database `platform` on every start, from postgres-setup, after
-- init/project-databases.sql and init/platform-role.sql (both give platform_rw what this takes back).
-- Safe to run again. postgres-setup passes each migrator's password as a psql variable
-- (<module>_migrator_password, made by scripts/secrets.sh); without one a migrator keeps the password it
-- has, or, when it is new, gets its own name, as init/platform-db.sql does for the runtime roles (test
-- beds only: compose always passes them).

DO $owners$
DECLARE
  m text;
BEGIN
  FOREACH m IN ARRAY ARRAY['qualification', 'controls', 'control_objectives', 'report_composer', 'engine',
                           'platform'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = m || '_rw') THEN
      RAISE EXCEPTION 'role %_rw is missing: run init/platform-db.sql and init/report-roles.sql first', m;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = m || '_owner') THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', m || '_owner');
    END IF;
    EXECUTE format('ALTER ROLE %I NOLOGIN NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL',
                   m || '_owner');
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = m || '_migrator') THEN
      EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', m || '_migrator', m || '_migrator');
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
                   m || '_migrator');
    EXECUTE format('GRANT %I TO %I', m || '_owner', m || '_migrator');
    EXECUTE format('ALTER ROLE %I SET role = %I', m || '_migrator', m || '_owner');
    EXECUTE format('GRANT %I TO %I', m || '_rw', m || '_owner');
    EXECUTE format('GRANT CONNECT ON DATABASE platform TO %I', m || '_migrator');
  END LOOP;
END
$owners$;

-- Only the platform's owner makes databases; the platform's runtime role no longer does, nor may it end
-- other roles' sessions (init/project-databases.sql and older versions of init/platform-role.sql gave it both).
ALTER ROLE platform_owner CREATEDB;
ALTER ROLE platform_rw NOCREATEDB;
REVOKE pg_signal_backend FROM platform_rw;
-- owning the schema `ledger` here takes CREATE on the database
GRANT CONNECT, CREATE ON DATABASE platform TO platform_owner;
-- the platform's migrations name core's tables unqualified, as platform_rw's sessions there do
ALTER ROLE platform_migrator IN DATABASE platform SET search_path = core;

\if :{?qualification_migrator_password}
SELECT format('ALTER ROLE qualification_migrator PASSWORD %L', :'qualification_migrator_password') \gexec
\endif
\if :{?controls_migrator_password}
SELECT format('ALTER ROLE controls_migrator PASSWORD %L', :'controls_migrator_password') \gexec
\endif
\if :{?control_objectives_migrator_password}
SELECT format('ALTER ROLE control_objectives_migrator PASSWORD %L', :'control_objectives_migrator_password') \gexec
\endif
\if :{?report_composer_migrator_password}
SELECT format('ALTER ROLE report_composer_migrator PASSWORD %L', :'report_composer_migrator_password') \gexec
\endif
\if :{?engine_migrator_password}
SELECT format('ALTER ROLE engine_migrator PASSWORD %L', :'engine_migrator_password') \gexec
\endif
\if :{?platform_migrator_password}
SELECT format('ALTER ROLE platform_migrator PASSWORD %L', :'platform_migrator_password') \gexec
\endif

-- Deleting a project ends the sessions the apps hold on its database before DROP DATABASE: through this
-- one function, owned by the superuser, that ends only non-superuser sessions on a database named like a
-- project's, and returns how many. Only platform_owner may call it.
CREATE SCHEMA IF NOT EXISTS aisc_setup;
REVOKE ALL ON SCHEMA aisc_setup FROM PUBLIC;
GRANT USAGE ON SCHEMA aisc_setup TO platform_owner, platform_rw;
CREATE OR REPLACE FUNCTION aisc_setup.end_project_sessions(dbname text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
DECLARE
  ended integer;
BEGIN
  IF dbname IS NULL OR dbname !~ '^project_[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'refused: % is not a project database', left(coalesce(dbname, 'null'), 80);
  END IF;
  SELECT count(*) INTO ended
    FROM (SELECT pg_terminate_backend(a.pid)
            FROM pg_stat_activity a LEFT JOIN pg_roles r ON r.oid = a.usesysid
           WHERE a.datname = dbname AND a.pid <> pg_backend_pid() AND NOT coalesce(r.rolsuper, false)) t;
  RETURN ended;
END
$fn$;
REVOKE ALL ON FUNCTION aisc_setup.end_project_sessions(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION aisc_setup.end_project_sessions(text) TO platform_owner;
