-- engine_rw's password. init/platform-db.sql makes every role with its own name as password;
-- engine_rw connects to every project database and writes the engine's schema there, so its password
-- must not be guessable by anything on the network (the eval worker runs plugin code there). Review
-- pass 2026-10-06, as init/controls-role.sql.
-- Runs as the superuser on every start from postgres-setup, which passes the password as a psql
-- variable (scripts/secrets.sh makes ENGINE_RW_PASSWORD); without one it leaves the role as it is.
\if :{?engine_rw_password}
SELECT format('ALTER ROLE engine_rw WITH LOGIN PASSWORD %L', :'engine_rw_password') \gexec
\endif
