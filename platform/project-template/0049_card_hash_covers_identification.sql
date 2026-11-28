-- The card's content hash covers every field the card page shows: its Identification and use section (system
-- name, release, provider, description, use case, users, deployers and the VAIR terms and tags) besides its answers,
-- components, risks and the corrections of its components. Before, a change of the system's name or description
-- left an agreement counting. Qualification grants platform_rw those columns (its migration
-- 20261128100000_platform_reads_card_identification).
--
-- A card task already in check keeps its submitted content: when its stored hash is the one the old function gives
-- for the card as it is, it is stored again as the new function gives it, so its check can still be signed.
-- Agreements given before keep the hash they were given on.
DO $rehash$
DECLARE
  old_hash text;
BEGIN
  IF EXISTS (SELECT 1 FROM work.task WHERE kind = 'describe_system' AND state = 'in_check')
     AND to_regclass('qualification.qualification') IS NOT NULL THEN
    BEGIN
      old_hash := work.card_content_hash();
    EXCEPTION WHEN insufficient_privilege THEN
      RETURN;                       -- the role migrating cannot read the card: the check is signed again after a send back
    END;
    CREATE TEMP TABLE card_task_old_hash ON COMMIT DROP AS
      SELECT id FROM work.task WHERE kind = 'describe_system' AND state = 'in_check' AND content_hash = old_hash;
  END IF;
END
$rehash$;

CREATE OR REPLACE FUNCTION work.card_content_hash() RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $f$
DECLARE
  latest record;
  content jsonb;
BEGIN
  SELECT q.id, q."ontologyPatch" AS patch,
         jsonb_build_array(q."systemName", q."systemVersion", q.company, q.description, q."targetUseCase",
                           q."targetUsers", q."intendedDeployers", q.system_type, q.purpose, q.provider_term,
                           q.deployer_term, q."targetSystemTags", q."sectorTags", q."marketFormTags",
                           q."localityTags") AS identification INTO latest
    FROM qualification.qualification q JOIN project.saved_system s ON s.pid = q.system_id
   ORDER BY s.number DESC, q.revision DESC LIMIT 1;
  content := jsonb_build_object(
    'identification', latest.identification,
    'patch', latest.patch,
    'answers', (SELECT coalesce(jsonb_agg(jsonb_build_array(a."toolId", a."questionId", a.answer)
                                          ORDER BY a."toolId", a."questionId"), '[]')
                  FROM qualification.qualification_answer a WHERE a."qualificationId" = latest.id),
    'components', (SELECT coalesce(jsonb_agg(jsonb_build_array(c.position, c.key, c.name, c.role, c.kind,
                                                               c.vair_type, c.provider, c.provider_name)
                                             ORDER BY c.position, c.key), '[]')
                     FROM qualification.qualification_component c WHERE c.qualification_id = latest.id),
    'risks', (SELECT coalesce(jsonb_agg(jsonb_build_array(r.position, r.risk, r.source, r.source_term,
                                                          r.vulnerability, r.consequence, r.consequence_term,
                                                          r.impact_term, r.affected, r."impactAreas")
                                        ORDER BY r.position, r.risk), '[]')
                FROM qualification.qualification_risk r WHERE r."qualificationId" = latest.id));
  RETURN encode(sha256(convert_to(content::text, 'UTF8')), 'hex');
END
$f$;

DO $rehash$
BEGIN
  IF to_regclass('pg_temp.card_task_old_hash') IS NOT NULL THEN
    UPDATE work.task SET content_hash = work.card_content_hash() WHERE id IN (SELECT id FROM card_task_old_hash);
    DROP TABLE card_task_old_hash;
  END IF;
END
$rehash$;
