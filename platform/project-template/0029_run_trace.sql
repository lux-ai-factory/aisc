-- Every call a run made to the system under test, recorded by the platform's protocol doors whatever the
-- plugin: the request as sent, the whole answer or the error, and when. Append-only: a row is never
-- changed or removed, for any role, the owner included. Each row's hash covers the row before it in its run,
-- so an edit, an insertion or a removal shows when the chain is recomputed (platform_service/run_trace.py).
-- Only the platform, the owner of this database, writes; the inspector reads it through pg_read_all_data.
CREATE SCHEMA IF NOT EXISTS trace;
REVOKE ALL ON SCHEMA trace FROM PUBLIC;

CREATE TABLE IF NOT EXISTS trace.call (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run               text NOT NULL CHECK (run ~ '^(pass|key):[0-9a-f]{64}$'),
    seq               integer NOT NULL CHECK (seq >= 1),
    evaluation_plugin uuid NULL,
    connection        text NOT NULL,
    door              text NOT NULL CHECK (door IN ('aisc', 'openai', 'a2a', 'oip')),
    started_at        timestamptz NOT NULL,
    ended_at          timestamptz NOT NULL,
    request           jsonb NOT NULL,
    outcome           text NOT NULL CHECK (outcome IN ('answered', 'failed', 'not_sent')),
    answer            jsonb NULL,
    error             jsonb NULL,
    prev_hash         text NULL CHECK (prev_hash IS NULL OR prev_hash ~ '^[0-9a-f]{64}$'),
    hash              text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (run, seq)
);
CREATE INDEX IF NOT EXISTS call_evaluation_plugin ON trace.call (evaluation_plugin) WHERE evaluation_plugin IS NOT NULL;

REVOKE ALL ON ALL TABLES IN SCHEMA trace FROM PUBLIC;

CREATE OR REPLACE FUNCTION trace.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'trace.call is append-only: a recorded call is never changed or removed';
END $$;

DROP TRIGGER IF EXISTS call_append_only ON trace.call;
CREATE TRIGGER call_append_only BEFORE UPDATE OR DELETE ON trace.call
    FOR EACH ROW EXECUTE FUNCTION trace.refuse_change();
DROP TRIGGER IF EXISTS call_no_truncate ON trace.call;
CREATE TRIGGER call_no_truncate BEFORE TRUNCATE ON trace.call
    FOR EACH STATEMENT EXECUTE FUNCTION trace.refuse_change();
