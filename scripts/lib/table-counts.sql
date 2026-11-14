-- One statement per ordinary table of the database, each answering "<schema>.<table><TAB><rows>", in name order.
-- Run it with \gexec (scripts/backup-databases.sh does): the counts of a backup and of its restore are compared
-- line by line. No semicolon at the end: the backup sends it as a psql variable followed by \gexec.
SELECT format('SELECT %L || chr(9) || count(*) FROM %I.%I', n.nspname || '.' || c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\_toast%'
ORDER BY n.nspname, c.relname
