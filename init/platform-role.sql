-- platform_rw's password (phase 2 review M1, 2026-10-02). init/platform-db.sql makes every role with
-- its own name as password; the platform service writes the ledger's Postgres side and ledger_identity,
-- the database that names people, so its password must not be guessable by anything on the network.
-- Superuser. Runs on every start from postgres-setup, which passes the password as a psql variable
-- (scripts/secrets.sh makes PLATFORM_RW_PASSWORD); without one it leaves the role as it is, so a
-- fresh volume works until postgres-setup has run. Kept out of init/platform-db.sql and
-- init/project-databases.sql, which the isolation guard dumps (as init/report-roles.sql is).
\if :{?platform_rw_password}
SELECT format('ALTER ROLE platform_rw WITH LOGIN PASSWORD %L', :'platform_rw_password') \gexec
\endif
