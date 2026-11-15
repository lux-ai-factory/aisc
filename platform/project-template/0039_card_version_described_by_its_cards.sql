-- A version is described as its latest card describes it, not as the platform's copy says, when the two
-- disagree. A correction is two writes in two transactions: the platform counts it and rewrites its copy of
-- the version's name, release, provider and description (project.system), then qualification's transaction
-- stores the card at that revision. When that transaction fails after the platform counted, the version's
-- cards are still at the revision before (0038 reads the revision from them), and so is its description:
-- the corrected name must not show on the versions list, the pick page, the summary, the system pages or an
-- answer's stamp while no card says it.
--
-- project.saved_system takes the name, release, provider and description from the version's highest-revision
-- card while the platform's count is above that card's revision, and from project.system otherwise: when the
-- counts agree (the platform's copy is that card's), while the version has no card yet, or while
-- qualification's cards cannot be read (a database qualification has not migrated yet, or before its
-- migration lets platform_rw read a card's identity). Safe on an existing install: no row changes, and the
-- view keeps its columns.
CREATE OR REPLACE FUNCTION project.card_described_of(of_version uuid, counted integer)
RETURNS TABLE (name text, version text, provider text, description text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $f$
BEGIN
  IF to_regclass('qualification.qualification') IS NULL THEN
    RETURN;
  END IF;
  IF NOT (has_column_privilege('qualification.qualification', 'system_id', 'SELECT')
          AND has_column_privilege('qualification.qualification', 'revision', 'SELECT')
          AND has_column_privilege('qualification.qualification', 'systemName', 'SELECT')
          AND has_column_privilege('qualification.qualification', 'systemVersion', 'SELECT')
          AND has_column_privilege('qualification.qualification', 'company', 'SELECT')
          AND has_column_privilege('qualification.qualification', 'description', 'SELECT')) THEN
    RETURN;
  END IF;
  -- as the platform stores an identity (platform_service.systems): the name trimmed, an empty release or
  -- description as none
  RETURN QUERY EXECUTE
    'SELECT btrim(q."systemName"), nullif(btrim(q."systemVersion"), ''''), q.company, nullif(q.description, '''')'
    '  FROM qualification.qualification q'
    ' WHERE q.system_id = $1 AND q.revision < $2'
    '   AND q.revision = (SELECT max(o.revision) FROM qualification.qualification o WHERE o.system_id = $1)'
    USING of_version, counted;
END
$f$;
COMMENT ON FUNCTION project.card_described_of(uuid, integer) IS
    'The name, release, provider and description of card version `of_version` as its highest-revision card gives them, while `counted` (the platform''s count) is above that revision; no row otherwise';
GRANT EXECUTE ON FUNCTION project.card_described_of(uuid, integer) TO PUBLIC;

CREATE OR REPLACE VIEW project.saved_system AS
    SELECT s.pid, s.number,
           CASE WHEN c.name IS NULL THEN s.name ELSE c.name END AS name,
           CASE WHEN c.name IS NULL THEN s.version ELSE c.version END AS version,
           CASE WHEN c.name IS NULL THEN s.provider ELSE c.provider END AS provider,
           CASE WHEN c.name IS NULL THEN s.description ELSE c.description END AS description,
           s.created_at, s.updated_at, s.created_by,
           project.card_revision_of(s.pid, s.card_revision) AS card_revision
      FROM project.system s
      LEFT JOIN LATERAL project.card_described_of(s.pid, s.card_revision) c ON true
     WHERE s.abandoned_at IS NULL;
