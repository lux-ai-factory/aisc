-- Step 4, collect evidence (evidence links plan 2026-09-30): which test or control gives evidence for
-- which control objective, many to many. Per project, not per card version (D3): a link survives a
-- new version; one whose objective is no longer selected is shown stale, not dropped (D7).
-- Written only by the platform. A test is named by its plugin's package_name, a control by its
-- checklist id (controls.checklist.id): the names the report matches runs and answers on.
-- The readers (report renderer, dashboard) read it to say how each objective is covered, and the report
-- composer copies it into a report's snapshot when it issues one (D5).
CREATE SCHEMA IF NOT EXISTS evidence;

CREATE TABLE IF NOT EXISTS evidence.link (
    objective_id text NOT NULL CHECK (objective_id ~ '^R[0-9]+\.[0-9]+$'),
    kind         text NOT NULL CHECK (kind IN ('test', 'control')),
    item_key     text NOT NULL CHECK (length(btrim(item_key)) BETWEEN 1 AND 200),
    created_by   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (objective_id, kind, item_key)
);

REVOKE ALL ON SCHEMA evidence FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA evidence FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['report_ro', 'dashboard_ro', 'report_composer_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA evidence TO %I', r);
      EXECUTE format('GRANT SELECT ON evidence.link TO %I', r);
    END IF;
  END LOOP;
END $g$;

COMMENT ON SCHEMA evidence IS 'Step 4: which tests and controls give evidence for which control objective (platform-owned).';
