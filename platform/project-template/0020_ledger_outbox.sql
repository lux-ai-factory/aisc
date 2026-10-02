-- The ledger's outbox in each project database (docs/superpowers/ledger-2026-10-02/02-spec.md 6.4).
-- An app records what a request did by calling ledger.emit(event) in its own transaction, so a rolled
-- back change leaves no event. Apps hold no right on the tables: emit stamps the role that called it
-- (session_user) and the database's own time, keeps any field it doesn't know in `extra` for the relay
-- to reject, and refuses the platform's own actions (ledger.platform_action, filled by provisioning
-- from the registry). The relay (the platform) reads, marks and binds. Safe to run again.
CREATE SCHEMA IF NOT EXISTS ledger;

CREATE TABLE IF NOT EXISTS ledger.outbox (
    event_id         uuid PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    db_role          text NOT NULL,
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
    extra            jsonb NOT NULL DEFAULT '{}'
);

-- what the relay has done with each row: its seq in the log, or why it was rejected
CREATE TABLE IF NOT EXISTS ledger.delivered (
    event_id     uuid PRIMARY KEY,
    seq          bigint,
    reason       text,
    delivered_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- a Next.js action id and the actions its first request carried (spec 4.5)
CREATE TABLE IF NOT EXISTS ledger.action_binding (
    app           text NOT NULL,
    next_action   text NOT NULL,
    first_request uuid NOT NULL,
    actions       text[] NOT NULL,
    PRIMARY KEY (app, next_action)
);

-- the registry's actions no app may emit (origin platform or browser), kept in step by provisioning
CREATE TABLE IF NOT EXISTS ledger.platform_action (name text PRIMARY KEY);

CREATE OR REPLACE FUNCTION ledger.emit(event jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, ledger AS $emit$
DECLARE
  stored  text[] := ARRAY['event_id', 'request_id', 'run_id', 'action', 'item_type', 'item_id', 'item_version',
                          'card_version', 'content', 'before', 'after', 'details', 'outcome', 'registry_version',
                          'model'];
  stamped text[] := ARRAY['db_role', 'occurred_at'];           -- set here, whatever was sent
  rest    jsonb;
BEGIN
  IF event IS NULL OR jsonb_typeof(event) <> 'object' THEN
    RAISE EXCEPTION 'ledger.emit: an event is a JSON object';
  END IF;
  IF coalesce(event->>'event_id', '') = '' OR coalesce(event->>'action', '') = '' THEN
    RAISE EXCEPTION 'ledger.emit: an event needs event_id and action';
  END IF;
  IF EXISTS (SELECT 1 FROM ledger.platform_action WHERE name = event->>'action') THEN
    RAISE EXCEPTION 'ledger.emit: % is recorded by the platform itself', event->>'action';
  END IF;
  SELECT coalesce(jsonb_object_agg(key, value), '{}'::jsonb) INTO rest
    FROM jsonb_each(event) WHERE key <> ALL (stored) AND key <> ALL (stamped);
  INSERT INTO ledger.outbox (event_id, db_role, request_id, run_id, action, item_type, item_id, item_version,
                             card_version, content, before, after, details, outcome, registry_version, model, extra)
  VALUES ((event->>'event_id')::uuid, session_user, nullif(event->>'request_id', '')::uuid,
          nullif(event->>'run_id', '')::uuid, event->>'action', event->>'item_type', event->>'item_id',
          event->>'item_version', nullif(event->>'card_version', '')::uuid, event->'content', event->'before',
          event->'after', coalesce(event->'details', '{}'::jsonb), coalesce(event->>'outcome', 'ok'),
          (event->>'registry_version')::integer, event->>'model', rest);
END
$emit$;

REVOKE ALL ON SCHEMA ledger FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ledger FROM PUBLIC;
REVOKE ALL ON FUNCTION ledger.emit(jsonb) FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['qualification_rw', 'controls_rw', 'control_objectives_rw', 'report_composer_rw',
                           'platform_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA ledger TO %I', r);
      EXECUTE format('GRANT EXECUTE ON FUNCTION ledger.emit(jsonb) TO %I', r);
    END IF;
  END LOOP;
END
$g$;
