-- Create the dedicated database for the qualification app (apps/qualification).
-- Runs once on a fresh Postgres volume, alongside the platform's POSTGRES_DB.
-- Prisma applies the schema into this DB but does not create the DB itself.
CREATE DATABASE qualification;
