-- Who did the work, rounds, and checks.
--
-- Holds say who holds a part now; a release deletes the row and a take-over overwrites it. So every save that
-- passes work.claim_for_save also records its person in work.doer, once per person, part and round, in the
-- save's transaction. A task's round is one pass from open to done: a save on a done task starts the next one
-- (open again, round + 1) instead of being refused, so a checked card can still be changed; a save on a task in
-- check is still refused (AH002), now with who submitted it and when.
--
-- Checks: how many people check each kind of task (work.staffing_rule), what a submit stores on the task (the
-- content hash and card state, computed here by one function per held kind), and the sign-offs, which are
-- never changed or removed. Safe on an existing install: columns with defaults or empty, new empty tables, and
-- functions replaced.
ALTER TABLE work.task ADD COLUMN IF NOT EXISTS round int NOT NULL DEFAULT 1 CHECK (round >= 1);
-- the last submit: by whom and when, the content hash and card state it was given on, and who held each part
-- it released ({part: [subject, name]}), so a send back gives each part to its last holder
ALTER TABLE work.task ADD COLUMN IF NOT EXISTS submitted_by_subject text,
                      ADD COLUMN IF NOT EXISTS submitted_by_name text,
                      ADD COLUMN IF NOT EXISTS submitted_at timestamptz,
                      ADD COLUMN IF NOT EXISTS content_hash text,
                      ADD COLUMN IF NOT EXISTS card_state jsonb,
                      ADD COLUMN IF NOT EXISTS released jsonb NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS work.doer (
    task            uuid NOT NULL,
    round           int NOT NULL,
    part            text NOT NULL,
    person_subject  text NOT NULL,
    person_name     text NOT NULL,
    first_saved_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task, round, part, person_subject),
    FOREIGN KEY (task, part) REFERENCES work.part (task, key) ON DELETE CASCADE
);
REVOKE ALL ON work.doer FROM PUBLIC;
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON work.doer TO platform_rw;
  END IF;
END
$g$;

CREATE OR REPLACE FUNCTION work.claim_for_save(p_kind text, p_subject text, p_part text, p_label text,
                                               p_person_subject text, p_person_name text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $f$
DECLARE
  t record;
  h record;
BEGIN
  IF NOT coalesce((SELECT enabled FROM work.setting WHERE name = 'holds'), false) THEN
    RETURN;
  END IF;
  INSERT INTO work.task (kind, subject) VALUES (p_kind, p_subject) ON CONFLICT (kind, subject) DO NOTHING;
  -- a done task opens its next round; two saves at once: the second waits for the first, then finds it open.
  -- A save refused below rolls this back with it.
  UPDATE work.task SET state = 'open', round = round + 1
   WHERE kind = p_kind AND subject = p_subject AND state = 'done';
  SELECT id, state, round, submitted_by_name, submitted_at INTO t
    FROM work.task WHERE kind = p_kind AND subject = p_subject FOR SHARE;
  IF t.state <> 'open' THEN
    RAISE EXCEPTION 'this task is in check and does not change' USING ERRCODE = 'AH002',
      DETAIL = json_build_object('submitted_by', t.submitted_by_name, 'submitted_at', t.submitted_at)::text;
  END IF;
  INSERT INTO work.part (task, key, label) VALUES (t.id, p_part, p_label) ON CONFLICT (task, key) DO NOTHING;
  INSERT INTO work.hold (task, part, holder_subject, holder_name)
       VALUES (t.id, p_part, p_person_subject, p_person_name) ON CONFLICT (task, part) DO NOTHING;
  SELECT holder_subject, holder_name, since INTO h FROM work.hold WHERE task = t.id AND part = p_part FOR SHARE;
  IF h.holder_subject <> p_person_subject THEN
    RAISE EXCEPTION 'someone else holds this part' USING ERRCODE = 'AH001',
      DETAIL = json_build_object('holder', h.holder_name, 'since', h.since)::text;
  END IF;
  INSERT INTO work.doer (task, round, part, person_subject, person_name)
       VALUES (t.id, t.round, p_part, p_person_subject, p_person_name) ON CONFLICT DO NOTHING;
END
$f$;
REVOKE ALL ON FUNCTION work.claim_for_save(text, text, text, text, text, text) FROM PUBLIC;

-- How many people check each kind of task: one row per change, the latest wins; a kind with no row needs none
CREATE TABLE IF NOT EXISTS work.staffing_rule (
    id              bigserial PRIMARY KEY,
    kind            text NOT NULL,
    checkers        int NOT NULL CHECK (checkers BETWEEN 0 AND 5),
    set_by_subject  text NOT NULL,
    set_by_name     text NOT NULL,
    set_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS staffing_rule_latest ON work.staffing_rule (kind, set_at DESC, id DESC);
REVOKE ALL ON work.staffing_rule FROM PUBLIC;
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT SELECT, INSERT ON work.staffing_rule TO platform_rw;
    GRANT USAGE ON SEQUENCE work.staffing_rule_id_seq TO platform_rw;
  END IF;
END
$g$;

-- The content a check is given on, as one hash per held kind, and the card state it was made on. Both run as
-- the caller (platform_rw), which reads the content columns the modules' migrations grant it and nothing else.
-- A hash is the sha256 of the content as jsonb text, rows in a fixed order; what a person does not save
-- (timestamps, the AI's draft, ids) is left out, so the hash moves when the content moves and only then.

-- The latest card version and its revision; NULL while the project has none
CREATE OR REPLACE FUNCTION work.card_state() RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog AS $f$
  SELECT jsonb_build_object('version', pid, 'number', number, 'revision', card_revision)
    FROM project.saved_system ORDER BY number DESC LIMIT 1
$f$;

-- The project's card: the latest stored card (latest version, latest revision): its answers, its components
-- and risk blocks, and the corrections of its components
CREATE OR REPLACE FUNCTION work.card_content_hash() RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $f$
DECLARE
  latest record;
  content jsonb;
BEGIN
  SELECT q.id, q."ontologyPatch" AS patch INTO latest
    FROM qualification.qualification q JOIN project.saved_system s ON s.pid = q.system_id
   ORDER BY s.number DESC, q.revision DESC LIMIT 1;
  content := jsonb_build_object(
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

-- A checklist submission: its answers
CREATE OR REPLACE FUNCTION work.checklist_content_hash(p_submission text) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $f$
DECLARE
  content jsonb;
BEGIN
  SELECT coalesce(jsonb_agg(jsonb_build_array(a."questionId", a.answer, a.score) ORDER BY a."questionId"), '[]')
    INTO content FROM controls.submission_answer a WHERE a."submissionId" = p_submission;
  RETURN encode(sha256(convert_to(content::text, 'UTF8')), 'hex');
END
$f$;

-- The risk register of a card version: its ratings, comments, mappings and key ticks
CREATE OR REPLACE FUNCTION work.register_content_hash(p_version text) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $f$
DECLARE
  assessment text;
  content jsonb;
BEGIN
  SELECT id INTO assessment FROM control_objectives.project WHERE system_id = p_version::uuid;
  content := jsonb_build_object(
    'risks', (SELECT coalesce(jsonb_agg(jsonb_build_array(
                       r.risk_id, r.rating_impact, r.rating_likelihood, r.severity_comment,
                       (SELECT coalesce(jsonb_agg(m.objective_id ORDER BY m.objective_id), '[]')
                          FROM control_objectives.mapped_objective m WHERE m.risk_row_id = r.id))
                     ORDER BY r.risk_id), '[]')
                FROM control_objectives.risk r WHERE r.project_id = assessment),
    'keys', (SELECT coalesce(jsonb_agg(jsonb_build_array(k.objective_id, k.key) ORDER BY k.objective_id), '[]')
               FROM control_objectives.objective_key k WHERE k.project_id = assessment));
  RETURN encode(sha256(convert_to(content::text, 'UTF8')), 'hex');
END
$f$;

-- One function per held kind; any other kind has no content to check yet
CREATE OR REPLACE FUNCTION work.content_hash(p_kind text, p_subject text) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $f$
BEGIN
  CASE p_kind
    WHEN 'describe_system' THEN RETURN work.card_content_hash();
    WHEN 'fill_checklist' THEN RETURN work.checklist_content_hash(p_subject);
    WHEN 'rate_risks' THEN RETURN work.register_content_hash(p_subject);
    ELSE RAISE EXCEPTION 'a task of kind % has no content hash', p_kind USING ERRCODE = 'AH003';
  END CASE;
END
$f$;

REVOKE ALL ON FUNCTION work.card_state(), work.card_content_hash(), work.checklist_content_hash(text),
                       work.register_content_hash(text), work.content_hash(text, text) FROM PUBLIC;
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT EXECUTE ON FUNCTION work.card_state(), work.card_content_hash(), work.checklist_content_hash(text),
                              work.register_content_hash(text), work.content_hash(text, text) TO platform_rw;
  END IF;
END
$g$;

-- A sign-off: agree, or send back with a reason, on the content hash and card state the signer was shown.
-- Never changed or removed, by anyone (guard triggers, init/guard-triggers.txt).
CREATE TABLE IF NOT EXISTS work.sign_off (
    id              bigserial PRIMARY KEY,
    task            uuid NOT NULL REFERENCES work.task,
    round           int NOT NULL,
    signer_subject  text NOT NULL,
    signer_name     text NOT NULL,
    answer          text NOT NULL CHECK (answer IN ('agree', 'send_back')),
    reason          text CHECK (answer = 'agree' OR btrim(coalesce(reason, '')) <> ''),
    content_hash    text NOT NULL,
    card_state      jsonb,
    at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sign_off_of_round ON work.sign_off (task, round);

CREATE OR REPLACE FUNCTION work.sign_off_is_kept() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION 'sign-offs are kept: work.sign_off is never truncated';
  END IF;
  RAISE EXCEPTION 'sign-off % is kept: a sign-off is never changed or removed', OLD.id;
END
$f$;
CREATE OR REPLACE TRIGGER sign_off_is_append_only BEFORE UPDATE OR DELETE ON work.sign_off
    FOR EACH ROW EXECUTE FUNCTION work.sign_off_is_kept();
CREATE OR REPLACE TRIGGER sign_off_is_not_truncated BEFORE TRUNCATE ON work.sign_off
    FOR EACH STATEMENT EXECUTE FUNCTION work.sign_off_is_kept();

REVOKE ALL ON work.sign_off FROM PUBLIC;
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT SELECT, INSERT ON work.sign_off TO platform_rw;
    GRANT USAGE ON SEQUENCE work.sign_off_id_seq TO platform_rw;
  END IF;
END
$g$;
