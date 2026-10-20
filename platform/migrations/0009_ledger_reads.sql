-- Page views and other browser-reported moments: best effort, never in immudb, kept for
-- PAGE_VIEW_RETENTION. The person is a random reference.
DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    RAISE EXCEPTION 'schema ledger is missing: run init/project-databases.sql as the superuser (postgres-setup does on every start)';
  END IF;
END
$guard$;

-- For the read routes: who acted, by kind, in the read index (the `ai` filter).
ALTER TABLE ledger.event_index ADD COLUMN IF NOT EXISTS actor_kind text;

CREATE TABLE IF NOT EXISTS ledger.page_view (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_pid uuid NOT NULL,
    actor_ref   text NOT NULL,
    action      text NOT NULL,
    details     jsonb NOT NULL DEFAULT '{}',
    request_id  uuid,
    at          timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS page_view_by_project ON ledger.page_view (project_pid, at);
