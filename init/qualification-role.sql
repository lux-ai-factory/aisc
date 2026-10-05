-- qualification_rw's password. init/platform-db.sql makes every role with its own name as password;
-- qualification_rw may connect to every project database and write its qualification schema, so its
-- password must not be guessable by anything on the network (the eval worker runs plugin code there).
-- Runs as the superuser on every start from postgres-setup, which passes the password as a psql
-- variable (scripts/secrets.sh makes QUALIFICATION_RW_PASSWORD); without one it leaves the role as it
-- is, so a fresh volume works until postgres-setup has run. Kept out of init/platform-db.sql and
-- init/project-databases.sql, whose results the isolation checks compare (as init/platform-role.sql).
\if :{?qualification_rw_password}
SELECT format('ALTER ROLE qualification_rw WITH LOGIN PASSWORD %L', :'qualification_rw_password') \gexec
\endif
