-- catalogue_rw's password. init/platform-db.sql makes every role with its own name as password;
-- catalogue_rw writes the catalogue schema on platform (the tests and controls every project installs from), so its password must not be guessable by anything on the network (the eval worker runs
-- plugin code there). Review pass 2026-10-06, as init/control-objectives-role.sql.
-- Runs as the superuser on every start from postgres-setup, which passes the password as a psql
-- variable (scripts/secrets.sh makes CATALOGUE_RW_PASSWORD); without one it leaves the role as it is, so a fresh
-- volume works until postgres-setup has run.
\if :{?catalogue_rw_password}
SELECT format('ALTER ROLE catalogue_rw WITH LOGIN PASSWORD %L', :'catalogue_rw_password') \gexec
\endif
