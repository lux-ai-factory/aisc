-- The versions a person can open: project.carded_system holds the rows of project.saved_system that have at
-- least one stored card, with the same columns. The platform numbers a version first and qualification stores
-- its card after, in another transaction, so saved_system also lists a version whose card is not stored yet
-- (or never will be, until it is withdrawn). The platform's create, revise and withdraw need exactly that list
-- and keep reading saved_system; writers that stamp a record with "the latest card", and lists shown to
-- people, read carded_system.
--
-- A card is a row of qualification.qualification naming the version. While qualification's cards cannot be
-- read (a database qualification has not migrated yet, or before its migration lets platform_rw read a card's
-- version), no version is known to have one and the view is empty. Safe on an existing install: a function
-- and a view, no row changes.
CREATE OR REPLACE FUNCTION project.has_stored_card(of_version uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $f$
DECLARE
  found boolean;
BEGIN
  IF to_regclass('qualification.qualification') IS NULL
     OR NOT has_column_privilege('qualification.qualification', 'system_id', 'SELECT') THEN
    RETURN false;
  END IF;
  EXECUTE 'SELECT EXISTS (SELECT 1 FROM qualification.qualification WHERE system_id = $1)' INTO found
    USING of_version;
  RETURN found;
END
$f$;
COMMENT ON FUNCTION project.has_stored_card(uuid) IS
    'Whether qualification holds a card of card version `of_version`; false while its cards cannot be read';
GRANT EXECUTE ON FUNCTION project.has_stored_card(uuid) TO PUBLIC;

CREATE OR REPLACE VIEW project.carded_system AS
    SELECT pid, number, name, version, provider, description, created_at, updated_at, created_by, card_revision
      FROM project.saved_system
     WHERE project.has_stored_card(pid);
COMMENT ON VIEW project.carded_system IS
    'The saved card versions that have at least one stored card: the versions a person can open';

-- The module roles read it as they read saved_system. The readers (report_ro, dashboard_ro) read an exhaustive
-- list kept in scripts/report-grants.sh and scripts/verify-project-databases.sh, which does not name it yet.
REVOKE ALL ON project.carded_system FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['platform_rw', 'qualification_rw', 'control_objectives_rw', 'controls_rw', 'engine_rw',
                           'report_composer_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT SELECT ON project.carded_system TO %I', r);
    END IF;
  END LOOP;
  IF to_regprocedure('aisc_setup.inspector_reads()') IS NOT NULL THEN
    PERFORM aisc_setup.inspector_reads();
  END IF;
END $g$;
