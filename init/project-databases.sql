-- Project databases: one per project, made by the platform service.
--
-- Runs as the superuser, and is safe to run again: on a fresh volume from
-- docker-entrypoint-initdb.d, and on an existing one from the postgres-setup
-- service, which runs it on every start.
--
-- CREATEDB is the whole of what the platform is given. It owns the databases it
-- makes and nothing else; the module roles are granted into each one by the
-- template it applies (platform/project-template/).
ALTER ROLE platform_rw CREATEDB;

-- New databases are copies of template1. On Postgres 14 its public schema lets
-- every role create tables, which would give each module a second, unowned place
-- to write in every project database.
\connect template1
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
