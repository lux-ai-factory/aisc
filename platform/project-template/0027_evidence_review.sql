-- The Evidence map: a note on each link (why it is evidence, what result counts as a pass), and the review of
-- one card version's map by someone who made none of its links. Any change to the map deletes its review.
-- Written only by the platform; the readers read both to show who reviewed the map.
ALTER TABLE evidence.link ADD COLUMN IF NOT EXISTS note text CHECK (length(note) <= 1000);

CREATE TABLE IF NOT EXISTS evidence.review (
    system_id        uuid PRIMARY KEY REFERENCES project.system (pid) ON DELETE CASCADE,
    reviewed_by      text NOT NULL,
    reviewed_by_name text NOT NULL,
    reviewed_at      timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON evidence.review FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['report_ro', 'dashboard_ro', 'report_composer_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT SELECT ON evidence.review TO %I', r);
    END IF;
  END LOOP;
END $g$;
