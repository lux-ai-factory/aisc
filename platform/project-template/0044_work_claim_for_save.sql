-- Holding on save: a per-project switch, and work.claim_for_save, which every save on the content of a part
-- calls in the transaction that writes. While the switch is off (no row, or enabled false: the default for
-- existing and new projects) the function does nothing. While it is on, the first save on a part nobody holds
-- takes it, creating the task and the part when they do not exist yet; the holder passes; anyone else is
-- refused as work.require_holder refuses (AH001 with the holder and since, AH002 for a task in check). The hold
-- row is read FOR SHARE, so a take-over waits for a save in progress. Two saves on a free part at once: the
-- second insert waits for the first to commit, then finds the part held. Safe on an existing install: a new
-- empty table and a new function.
-- one row per switch; the only one so far is 'holds'
CREATE TABLE IF NOT EXISTS work.setting (
    name       text PRIMARY KEY CHECK (name IN ('holds')),
    enabled    boolean NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);

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
  SELECT id, state INTO t FROM work.task WHERE kind = p_kind AND subject = p_subject FOR SHARE;
  IF t.state <> 'open' THEN
    RAISE EXCEPTION 'this task is in check and does not change' USING ERRCODE = 'AH002';
  END IF;
  INSERT INTO work.part (task, key, label) VALUES (t.id, p_part, p_label) ON CONFLICT (task, key) DO NOTHING;
  INSERT INTO work.hold (task, part, holder_subject, holder_name)
       VALUES (t.id, p_part, p_person_subject, p_person_name) ON CONFLICT (task, part) DO NOTHING;
  SELECT holder_subject, holder_name, since INTO h FROM work.hold WHERE task = t.id AND part = p_part FOR SHARE;
  IF h.holder_subject <> p_person_subject THEN
    RAISE EXCEPTION 'someone else holds this part' USING ERRCODE = 'AH001',
      DETAIL = json_build_object('holder', h.holder_name, 'since', h.since)::text;
  END IF;
END
$f$;

REVOKE ALL ON work.setting FROM PUBLIC;
REVOKE ALL ON FUNCTION work.claim_for_save(text, text, text, text, text, text) FROM PUBLIC;
DO $g$
DECLARE
  r text;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON work.setting TO platform_rw;
  END IF;
  FOREACH r IN ARRAY ARRAY['qualification_rw', 'controls_rw', 'control_objectives_rw', 'platform_rw'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION work.claim_for_save(text, text, text, text, text, text) TO %I', r);
    END IF;
  END LOOP;
END
$g$;
