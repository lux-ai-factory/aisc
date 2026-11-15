-- A card version made for a card that was never saved is abandoned, not deleted (project.system refuses
-- DELETE, 0034). Qualification sends an attempt id with each version it asks for; when the card write then
-- fails, it withdraws the version by that id: the row stays, marked abandoned with a reason, and is never the
-- latest again. Its number is never given again either (the next number counts every row).
--
-- Every reader of "the latest version" reads project.saved_system, which leaves abandoned rows out. Safe on
-- an existing install: three empty columns, a view, and the latest-changes rule now judging "latest" among the
-- versions that are kept; no row changes.
ALTER TABLE project.system ADD COLUMN IF NOT EXISTS attempt uuid UNIQUE;
ALTER TABLE project.system ADD COLUMN IF NOT EXISTS abandoned_at timestamptz;
ALTER TABLE project.system ADD COLUMN IF NOT EXISTS abandoned_reason text
    CHECK (abandoned_reason IS NULL OR length(abandoned_reason) <= 500);

CREATE OR REPLACE VIEW project.saved_system AS
    SELECT pid, number, name, version, provider, description, created_at, updated_at, created_by, card_revision
      FROM project.system
     WHERE abandoned_at IS NULL;
COMMENT ON VIEW project.saved_system IS
    'The card versions that were saved (an abandoned one, made for a card that was never saved, is left out)';

-- Only the latest kept version may change, and an abandoned one never does again.
CREATE OR REPLACE FUNCTION project.system_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF NEW.number <> OLD.number OR OLD.abandoned_at IS NOT NULL
     OR OLD.number < (SELECT max(number) FROM project.system WHERE abandoned_at IS NULL) THEN
    RAISE EXCEPTION 'system version % is not the latest and cannot change', OLD.number;
  END IF;
  RETURN NEW;
END $f$;

-- Whoever reads project.system reads the view; platform_rw only reads it (it writes the table).
REVOKE ALL ON project.saved_system FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['platform_rw', 'qualification_rw', 'control_objectives_rw', 'controls_rw', 'engine_rw',
                           'report_composer_rw', 'report_ro', 'dashboard_ro'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON project.saved_system FROM %I', r);
      EXECUTE format('GRANT SELECT ON project.saved_system TO %I', r);
    END IF;
  END LOOP;
  IF to_regprocedure('aisc_setup.inspector_reads()') IS NOT NULL THEN
    PERFORM aisc_setup.inspector_reads();
  END IF;
END $g$;
