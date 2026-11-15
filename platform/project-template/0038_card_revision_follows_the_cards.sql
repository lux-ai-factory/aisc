-- A version's card revision is the highest revision of the cards qualification holds for it, not the
-- platform's own count. A correction is two writes in two transactions: the platform counts it
-- (project.system.card_revision), then qualification's transaction stores the card at that revision. When
-- that transaction fails after the platform counted, there is no card at the new revision; the version
-- must still read the revision its cards are at, so the next correction from that revision is taken and a
-- report never pins a revision with no card behind it.
--
-- project.saved_system, which every reader of the versions reads, takes the revision from
-- project.card_revision_of. It falls back to the platform's count while the version has no card yet, or
-- while qualification's cards cannot be read (a database qualification has not migrated yet, or before its
-- migration lets platform_rw read a card's revision). Safe on an existing install: no row changes.
CREATE OR REPLACE FUNCTION project.card_revision_of(version uuid, counted integer) RETURNS integer
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $f$
DECLARE
  highest integer;
BEGIN
  IF to_regclass('qualification.qualification') IS NULL
     OR NOT has_column_privilege('qualification.qualification', 'system_id', 'SELECT')
     OR NOT has_column_privilege('qualification.qualification', 'revision', 'SELECT') THEN
    RETURN counted;
  END IF;
  EXECUTE 'SELECT max(revision) FROM qualification.qualification WHERE system_id = $1' INTO highest USING version;
  RETURN coalesce(highest, counted);
END
$f$;
COMMENT ON FUNCTION project.card_revision_of(uuid, integer) IS
    'The highest revision of the cards of card version `version`; `counted` (the platform''s count) while it has none';
GRANT EXECUTE ON FUNCTION project.card_revision_of(uuid, integer) TO PUBLIC;

CREATE OR REPLACE VIEW project.saved_system AS
    SELECT pid, number, name, version, provider, description, created_at, updated_at, created_by,
           project.card_revision_of(pid, card_revision) AS card_revision
      FROM project.system
     WHERE abandoned_at IS NULL;
