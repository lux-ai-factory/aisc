-- Controls: its schema in this project's database, used by its role.
--
-- This database is one project. Nothing in it names a project, and nothing
-- outside it can be reached from here. The database name is not known when
-- this file is written, hence the DO block (psycopg does not expand psql
-- variables).
DO $grant$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO controls_rw', current_database());
END
$grant$;

CREATE SCHEMA IF NOT EXISTS controls;
GRANT USAGE, CREATE ON SCHEMA controls TO controls_rw;
COMMENT ON SCHEMA controls IS 'Step 5: this project''s checklists, submissions and answers.';
