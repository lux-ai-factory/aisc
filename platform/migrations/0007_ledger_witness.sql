-- The witness's records (docs/superpowers/ledger-2026-10-02/02-spec.md 3.4): one row per request the
-- gateway asked about, written in the request itself (immudb is off the request path; the relay copies
-- each row into its project's log). The person is a random reference only: the mapping to a name is
-- in the separate database ledger_identity, beyond pgAdmin's read-all role (S8).
DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    RAISE EXCEPTION 'schema ledger is missing: run init/project-databases.sql as the superuser (postgres-setup does on every start)';
  END IF;
END
$guard$;

CREATE TABLE IF NOT EXISTS ledger.witness (
    request_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    mode          text NOT NULL CHECK (mode IN ('record', 'enforce')),
    app           text NOT NULL,
    method        text NOT NULL,
    route_path    text NOT NULL,
    query_hmac    text,
    host          text,
    project_pid   uuid,
    member        boolean NOT NULL DEFAULT false,
    actor_ref     text,
    verified      boolean NOT NULL,
    reason        text,
    next_action   text,
    token_jti     text,
    token_exp     timestamptz,
    delivered_seq bigint
);
CREATE INDEX IF NOT EXISTS witness_by_project ON ledger.witness (project_pid, at);
CREATE INDEX IF NOT EXISTS witness_undelivered ON ledger.witness (at) WHERE delivered_seq IS NULL;
