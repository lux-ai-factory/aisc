-- Create the dedicated database for the controls app (apps/controls).
-- Runs once on a fresh Postgres volume, alongside the platform's POSTGRES_DB.
-- Prisma applies the schema into this DB but does not create the DB itself.
CREATE DATABASE controls;
