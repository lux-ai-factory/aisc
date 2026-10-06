-- controls_rw's password. init/platform-db.sql makes every role with its own name as password;
-- controls_rw may connect to every project database and write its controls schema, so its password must not be guessable by anything on the network (the eval worker runs
-- plugin code there). Review pass 2026-10-06, as init/control-objectives-role.sql.
-- Runs as the superuser on every start from postgres-setup, which passes the password as a psql
-- variable (scripts/secrets.sh makes CONTROLS_RW_PASSWORD); without one it leaves the role as it is, so a fresh
-- volume works until postgres-setup has run.
\if :{?controls_rw_password}
SELECT format('ALTER ROLE controls_rw WITH LOGIN PASSWORD %L', :'controls_rw_password') \gexec
\endif
