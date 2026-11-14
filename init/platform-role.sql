-- platform_rw's password. init/platform-db.sql makes every role with its own name as password;
-- the platform service writes the ledger's Postgres side and ledger_identity, the database that
-- names people, so its password must not be guessable by anything on the network.
-- Runs as the superuser on every start from postgres-setup, which passes the password as a psql
-- variable (scripts/secrets.sh makes PLATFORM_RW_PASSWORD); without one it leaves the role as it
-- is, so a fresh volume works until postgres-setup has run. Kept out of init/platform-db.sql and
-- init/project-databases.sql, whose results the isolation checks compare (as for
-- init/report-roles.sql).
\if :{?platform_rw_password}
SELECT format('ALTER ROLE platform_rw WITH LOGIN PASSWORD %L', :'platform_rw_password') \gexec
\endif

-- platform_rw no longer deletes projects and is not given pg_signal_backend: platform_migrator drops a
-- project's database and ends the apps' sessions on it through aisc_setup.end_project_sessions
-- (init/owner-roles.sql, which also takes back the membership earlier versions of this file granted).
