-- Two reads of the platform's work every module makes: who stored the latest card state and when, and whether
-- the project's holding switch is on. Safe on an existing install: two functions.
--
-- Who stored the latest card state, and when: the card state (work.card_state) with the name of the person who
-- stored its card and the time. A page drawn on one card state compares it with this one and, when it is no
-- longer the latest, says "The AI card changed since you started (who, when)"; a committing action asks once
-- with the same words. Every module reads it, as it reads project.saved_system.
--
-- The person is the card's corrector for a correction (qualification.qualification.amended_by), else the person
-- who saved it (saved_by); both NULL on cards stored before they were recorded, and then the change names no
-- one. The time is the card's created_at. While qualification's cards cannot be read (a database qualification
-- has not migrated yet, or before its migration lets platform_rw read those columns), it names no one, and the
-- time is when the platform last changed the version.
CREATE OR REPLACE FUNCTION work.card_change() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $f$
DECLARE
  latest record;
  by_whom text;
  stored_at timestamptz;
BEGIN
  SELECT pid, number, card_revision, coalesce(updated_at, created_at) AS changed_at INTO latest
    FROM project.saved_system ORDER BY number DESC LIMIT 1;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  IF to_regclass('qualification.qualification') IS NOT NULL
     AND has_column_privilege('qualification.qualification', 'saved_by', 'SELECT')
     AND has_column_privilege('qualification.qualification', 'amended_by', 'SELECT')
     AND has_column_privilege('qualification.qualification', 'created_at', 'SELECT') THEN
    EXECUTE 'SELECT coalesce(amended_by, saved_by), created_at FROM qualification.qualification'
            ' WHERE system_id = $1 AND revision = $2 ORDER BY created_at DESC LIMIT 1'
       INTO by_whom, stored_at USING latest.pid, latest.card_revision;
  END IF;
  RETURN jsonb_build_object('version', latest.pid, 'number', latest.number, 'revision', latest.card_revision,
                            'by', by_whom, 'at', coalesce(stored_at, latest.changed_at));
END
$f$;
COMMENT ON FUNCTION work.card_change() IS
    'The latest card state with who stored its card and when; NULL while the project has no card version';

REVOKE ALL ON FUNCTION work.card_change() FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['platform_rw', 'qualification_rw', 'controls_rw', 'control_objectives_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION work.card_change() TO %I', r);
    END IF;
  END LOOP;
  -- the report composer asks once when the card was corrected since its Generate page was drawn, naming who
  -- corrected it and when; it reads nothing else of the work schema
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_composer_rw') THEN
    GRANT USAGE ON SCHEMA work TO report_composer_rw;
    GRANT EXECUTE ON FUNCTION work.card_change() TO report_composer_rw;
  END IF;
END
$g$;

-- Whether holding is on for the project (work.setting, which only the platform writes). A completing action
-- that also submits its task (closing a checklist submission) submits only while it is on: while it is off the
-- project works as before.
CREATE OR REPLACE FUNCTION work.holds_on() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $f$
  SELECT coalesce((SELECT enabled FROM work.setting WHERE name = 'holds'), false)
$f$;
COMMENT ON FUNCTION work.holds_on() IS 'Whether holding is switched on for the project';

REVOKE ALL ON FUNCTION work.holds_on() FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['platform_rw', 'qualification_rw', 'controls_rw', 'control_objectives_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION work.holds_on() TO %I', r);
    END IF;
  END LOOP;
END
$g$;
