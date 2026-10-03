-- The ledger's Postgres side: the pool of immudb databases and their last verified state.
-- In schema `ledger`, which init/platform-db.sql (a fresh volume) and init/project-databases.sql
-- (postgres-setup, every start) make, owned by this service; no module role can reach it.

DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    RAISE EXCEPTION 'schema ledger is missing: run init/project-databases.sql as the superuser (postgres-setup does on every start)';
  END IF;
END
$guard$;

-- The operator's pool of immudb databases (scripts/ledger-pool.sh adds rows). A project takes one at
-- creation and keeps it for ever; the table is also the list of databases expected to exist.
-- server_id is the server's own identity (immudb's UUID, or memory:<uuid> in tests), never its
-- address, so a database of another server is never handed out.
CREATE TABLE IF NOT EXISTS ledger.pool (
    db           text PRIMARY KEY CHECK (db ~ '^ledger[0-9a-f]{32}$'),
    server_id    text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
    assigned_pid uuid,
    assigned_at  timestamptz,
    CHECK ((assigned_pid IS NULL) = (assigned_at IS NULL))
);
-- One database per project, and two creations at once can't share one.
CREATE UNIQUE INDEX IF NOT EXISTS pool_one_per_project ON ledger.pool (assigned_pid)
    WHERE assigned_pid IS NOT NULL;
CREATE INDEX IF NOT EXISTS pool_free ON ledger.pool (server_id, created_at)
    WHERE assigned_pid IS NULL;

-- The last verified immudb state of each database, kept outside immudb. It only moves forward, by
-- compare-and-set.
CREATE TABLE IF NOT EXISTS ledger.state (
    db         text PRIMARY KEY,
    tx_id      bigint NOT NULL CHECK (tx_id >= 0),
    tx_hash    bytea NOT NULL,
    signature  bytea,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
