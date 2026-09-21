-- A read-only role for the results dashboard, which reads evaluation results
-- out of the platform's own database and must never write to it.
--
-- Runs once on a fresh Postgres volume, against POSTGRES_DB (`aisc`). The
-- backend's tables do not exist yet at this point, so instead of granting on
-- existing tables this sets DEFAULT PRIVILEGES: every table the platform user
-- creates later is readable by dashboard_ro automatically.
CREATE ROLE dashboard_ro LOGIN PASSWORD 'dashboard_ro';
GRANT CONNECT ON DATABASE aisc TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dashboard_ro;

-- On Postgres 14 and earlier the `public` schema grants CREATE to PUBLIC, so a
-- role with only USAGE can still create tables. Take that away from everyone
-- and hand it back to the platform user alone, which is the only account that
-- should be creating objects here.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CREATE ON SCHEMA public TO "aisc-postgres-user";
