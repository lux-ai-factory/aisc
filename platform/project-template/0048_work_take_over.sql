-- A take-over, kept: who lost a part, who has it now, which owner moved it and why. The reason was only in the
-- ledger event; the person who lost the part sees it in My tasks, and the report's "Who did what" block lists
-- it. The platform writes the row in the same transaction as the take-over (platform_service/work/holds.py).
-- Never changed or removed, by anyone (guard triggers, init/guard-triggers.txt). Whether the former holder put
-- the line away is a row of its own in work.take_over_dismissed, written once.
CREATE TABLE IF NOT EXISTS work.take_over (
    id            bigserial PRIMARY KEY,
    task          uuid NOT NULL REFERENCES work.task,
    round         int NOT NULL,
    part          text NOT NULL,
    from_subject  text,                         -- NULL when nobody held the part
    from_name     text,
    to_subject    text NOT NULL,
    to_name       text NOT NULL,
    by_subject    text NOT NULL,
    by_name       text NOT NULL,
    reason        text NOT NULL CHECK (btrim(reason) <> ''),
    at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS take_over_of_round ON work.take_over (task, round);
CREATE INDEX IF NOT EXISTS take_over_from ON work.take_over (from_subject);

CREATE OR REPLACE FUNCTION work.take_over_is_kept() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION 'take-overs are kept: work.take_over is never truncated';
  END IF;
  RAISE EXCEPTION 'take-over % is kept: a take-over is never changed or removed', OLD.id;
END
$f$;
CREATE OR REPLACE TRIGGER take_over_is_append_only BEFORE UPDATE OR DELETE ON work.take_over
    FOR EACH ROW EXECUTE FUNCTION work.take_over_is_kept();
CREATE OR REPLACE TRIGGER take_over_is_not_truncated BEFORE TRUNCATE ON work.take_over
    FOR EACH STATEMENT EXECUTE FUNCTION work.take_over_is_kept();

-- The former holder put the take-over's line in My tasks away
CREATE TABLE IF NOT EXISTS work.take_over_dismissed (
    take_over  bigint PRIMARY KEY REFERENCES work.take_over,
    at         timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON work.take_over, work.take_over_dismissed FROM PUBLIC;
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT SELECT, INSERT ON work.take_over, work.take_over_dismissed TO platform_rw;
    GRANT USAGE ON SEQUENCE work.take_over_id_seq TO platform_rw;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
    GRANT SELECT ON work.take_over TO report_ro;
  END IF;
END
$g$;
