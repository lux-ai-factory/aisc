-- Create the dedicated database for the control objectives app
-- (apps/control-objectives). Runs once on a fresh Postgres volume, alongside
-- the platform's POSTGRES_DB. Alembic applies the schema into this DB but does
-- not create the DB itself.
CREATE DATABASE control_objectives;
