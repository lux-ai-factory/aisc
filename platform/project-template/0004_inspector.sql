-- The database inspector (init/inspector-role.sql) reads this project's database for the launcher's
-- admins. It may connect; pg_read_all_data gives it SELECT, and its sessions are read-only.
-- Skipped where inspector_ro does not exist (a database without the inspector's role).
DO $grant$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'inspector_ro') THEN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO inspector_ro', current_database());
    END IF;
END
$grant$;
