-- The ledger's schema in the platform database (docs/superpowers/ledger-2026-10-02/02-spec.md 6.1).
--
-- Owned by the platform service, the ledger's only writer: no module role gets USAGE, so none can
-- read the witness records, the person mapping or the pool, nor learn they exist. Its tables are
-- made by the platform's own migrations (platform/migrations/0006_ledger_*.sql onwards).
--
-- Making a schema needs a superuser, so it is here and not a migration. Idempotent: it runs on a
-- fresh volume (docker-entrypoint-initdb.d) and on every start (postgres-setup).
\connect platform

DO $ledger$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    CREATE SCHEMA ledger AUTHORIZATION platform_rw;
  END IF;
END
$ledger$;

REVOKE ALL ON SCHEMA ledger FROM PUBLIC;
COMMENT ON SCHEMA ledger IS 'The immudb ledger''s Postgres side: pool, verified state, witness records. Platform only.';
