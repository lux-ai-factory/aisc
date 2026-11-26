-- Who does what: a task per piece of work, its parts, and who holds each part now. Only the holder saves on a
-- part, and apps check that inside their own transaction through work.require_holder, which locks the hold row
-- FOR SHARE: a take-over (an UPDATE of that row) waits for a save in progress, and the next save sees the new
-- holder. Apps cannot read or write these tables; they only call the function. Safe on an existing install:
-- new schema, empty tables.
CREATE SCHEMA IF NOT EXISTS work;

CREATE TABLE IF NOT EXISTS work.task (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL,
    subject         text NOT NULL,
    state           text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'in_check', 'done')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    checkers_needed int CHECK (checkers_needed BETWEEN 0 AND 5),
    UNIQUE (kind, subject)
);

CREATE TABLE IF NOT EXISTS work.part (
    task  uuid NOT NULL REFERENCES work.task ON DELETE CASCADE,
    key   text NOT NULL,
    label text NOT NULL,
    PRIMARY KEY (task, key)
);

CREATE TABLE IF NOT EXISTS work.hold (
    task            uuid NOT NULL,
    part            text NOT NULL,
    holder_subject  text NOT NULL,
    holder_name     text NOT NULL,
    since           timestamptz NOT NULL DEFAULT now(),
    -- a hand-over the holder offered and the other person has not answered yet
    offered_to_subject text,
    offered_to_name    text,
    PRIMARY KEY (task, part),
    FOREIGN KEY (task, part) REFERENCES work.part (task, key) ON DELETE CASCADE
);

COMMENT ON TABLE work.hold IS 'Who holds each part of a task now; at most one person per part';

-- AH001: not the holder (detail: JSON with holder and since, or no holder); AH002: the task is in check
CREATE OR REPLACE FUNCTION work.require_holder(p_kind text, p_subject text, p_part text, p_person text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $f$
DECLARE
  t record;
  h record;
BEGIN
  SELECT id, state INTO t FROM work.task WHERE kind = p_kind AND subject = p_subject;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'nobody holds this part' USING ERRCODE = 'AH001', DETAIL = '{"holder": null}';
  END IF;
  IF t.state <> 'open' THEN
    RAISE EXCEPTION 'this task is in check and does not change' USING ERRCODE = 'AH002';
  END IF;
  SELECT holder_subject, holder_name, since INTO h FROM work.hold WHERE task = t.id AND part = p_part FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'nobody holds this part' USING ERRCODE = 'AH001', DETAIL = '{"holder": null}';
  END IF;
  IF h.holder_subject <> p_person THEN
    RAISE EXCEPTION 'someone else holds this part' USING ERRCODE = 'AH001',
      DETAIL = json_build_object('holder', h.holder_name, 'since', h.since)::text;
  END IF;
END
$f$;

REVOKE ALL ON SCHEMA work FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA work FROM PUBLIC;
REVOKE ALL ON FUNCTION work.require_holder(text, text, text, text) FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT USAGE ON SCHEMA work TO platform_rw;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA work TO platform_rw;
  END IF;
  FOREACH r IN ARRAY ARRAY['qualification_rw', 'controls_rw', 'control_objectives_rw', 'platform_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA work TO %I', r);
      EXECUTE format('GRANT EXECUTE ON FUNCTION work.require_holder(text, text, text, text) TO %I', r);
    END IF;
  END LOOP;
END
$g$;
