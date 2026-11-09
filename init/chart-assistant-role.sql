-- The chart assistant's role: it makes and reads the projects' mock databases (assistant_mock_<pid hex>_<digest>),
-- whose rows are invented, though their labels (targets, short dimension values) are the project's real ones. It may
-- create databases and nothing else: no project database lets it connect
-- (CONNECT is never granted to PUBLIC on them), and it holds no privilege on any table it did not make. Runs as the
-- superuser on a fresh volume (docker-entrypoint-initdb.d) and on every start from postgres-setup, which passes the
-- password as a psql variable.
\if :{?assistant_mock_password}
\else
\set assistant_mock_password assistant_mock
\endif

SELECT 'CREATE ROLE assistant_mock LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assistant_mock') \gexec
SELECT format('ALTER ROLE assistant_mock WITH LOGIN NOSUPERUSER CREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              :'assistant_mock_password') \gexec
-- the platform database: CONNECT and TEMPORARY come to every role from PUBLIC unless taken back there, so a
-- revoke from this role alone gives it nothing to lose. Every role that works in platform holds CONNECT of its
-- own (init/platform-db.sql, inspector-role.sql, report-roles.sql), so PUBLIC loses both and the assistant's role
-- gets nothing there.
REVOKE CONNECT, TEMPORARY ON DATABASE platform FROM PUBLIC;
REVOKE ALL ON DATABASE platform FROM assistant_mock;
