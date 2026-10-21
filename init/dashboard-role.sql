-- dashboard_ro's password. init/platform-db.sql makes every role with its own name as password;
-- dashboard_ro may connect to every project database and read its results, and reads every
-- project's members, so its password must not be guessable by anything on the network (the eval
-- worker runs plugin code there).
-- Runs as the superuser on every start from postgres-setup, which passes the password as a psql
-- variable (scripts/secrets.sh makes DASHBOARD_RO_PASSWORD); without one it leaves the role as it
-- is, so a fresh volume works until postgres-setup has run. Kept out of init/platform-db.sql and
-- init/project-databases.sql, whose results the isolation checks compare (as init/platform-role.sql).
\if :{?dashboard_ro_password}
SELECT format('ALTER ROLE dashboard_ro WITH LOGIN PASSWORD %L', :'dashboard_ro_password') \gexec
\endif
