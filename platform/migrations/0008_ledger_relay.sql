-- The relay's Postgres side in the platform database (docs/superpowers/ledger-2026-10-02/02-spec.md 4.2,
-- 6.1, 6.4). Platform only: no module role can reach core.outbox or the ledger schema.
DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ledger') THEN
    RAISE EXCEPTION 'schema ledger is missing: run init/project-databases.sql as the superuser (postgres-setup does on every start)';
  END IF;
END
$guard$;

-- The platform's own events (members, projects, LLM keys, card versions, step 4 links) and those posted
-- on the internal route, written in the same transaction as the change they describe (R2.4).
CREATE TABLE IF NOT EXISTS core.outbox (
    event_id         uuid PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    emitter          text NOT NULL,
    project_pid      uuid,
    request_id       uuid,
    run_id           uuid,
    action           text NOT NULL,
    item_type        text,
    item_id          text,
    item_version     text,
    card_version     uuid,
    content          jsonb,
    before           jsonb,
    after            jsonb,
    details          jsonb NOT NULL DEFAULT '{}',
    outcome          text NOT NULL DEFAULT 'ok',
    registry_version integer,
    model            text,
    extra            jsonb NOT NULL DEFAULT '{}',
    delivered_seq    bigint,
    delivered_reason text,
    delivered_at     timestamptz
);
CREATE INDEX IF NOT EXISTS outbox_undelivered ON core.outbox (project_pid, occurred_at) WHERE delivered_at IS NULL;

-- What the relay accepted or rejected, per log: the read index (spec 6.3) and what the binding checks
-- count (per_request, runs, chains, witnessed writes with no event). Keyed by the log's database name, so
-- the platform log (no project) has its own sequence; unique on the event id within a log only.
CREATE TABLE IF NOT EXISTS ledger.event_index (
    log          text NOT NULL,
    seq          bigint NOT NULL,
    event_id     text NOT NULL,
    project_pid  uuid,
    action       text NOT NULL,
    actor_ref    text,
    step         integer,
    source_app   text,
    item_type    text,
    item_id      text,
    card_version uuid,
    outcome      text,
    occurred_at  timestamptz,
    request_id   uuid,
    run_id       uuid,
    before_sha256 text,
    after_sha256 text,
    reason       text,
    row_digest   text,                         -- what the emitter sent: a re-sent row that differs is an alarm
    PRIMARY KEY (log, seq),
    UNIQUE (log, event_id)
);
CREATE INDEX IF NOT EXISTS event_index_request ON ledger.event_index (request_id, action);
CREATE INDEX IF NOT EXISTS event_index_run ON ledger.event_index (run_id) WHERE run_id IS NOT NULL;

-- Frozen content of each entry, until the evidence store (phase 10): the log holds only its digest.
CREATE TABLE IF NOT EXISTS ledger.content (
    log         text NOT NULL,
    event_id    text NOT NULL,
    project_pid uuid,
    content     jsonb,
    before      jsonb,
    after       jsonb,
    PRIMARY KEY (log, event_id)
);
