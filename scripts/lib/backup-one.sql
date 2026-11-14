-- One database's backup, run by scripts/backup-databases.sh through psql inside the Postgres container.
-- The row counts and the dump come from one snapshot: the transaction exports it, the counts are taken in it,
-- and pg_dump reads the same snapshot while the transaction is still open. So a backup taken while the stack
-- writes still compares exactly with its restore.
--
-- psql variables: counts_file (where the counts go, inside the container), counts_query (table-counts.sql).
-- Environment: BACKUP_USER, BACKUP_DB. The dump goes to psql's standard output.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT pg_export_snapshot() AS snap \gset
-- \! takes no psql variables, so the snapshot reaches pg_dump through the environment
\setenv BACKUP_SNAPSHOT :snap
\o :counts_file
:counts_query \gexec
\o
\! pg_dump -U "$BACKUP_USER" -d "$BACKUP_DB" -Fc --snapshot="$BACKUP_SNAPSHOT"
COMMIT;
