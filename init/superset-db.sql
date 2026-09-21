-- Create the metadata database for the results dashboard
-- (apps/results-dashboard). Runs once on a fresh Postgres volume. Superset's
-- `db upgrade` applies its schema into this DB but does not create the DB.
CREATE DATABASE superset;
