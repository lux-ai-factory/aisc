-- A card version is never deleted. Runs, evidence, reviews and reports name one; a version that disappeared
-- would leave them pointing at nothing. project.system refuses DELETE and TRUNCATE for every role, its owner
-- and the superuser included; a card is corrected through a revision of its latest version (0032), and a
-- project leaves whole, by dropping its database. The two triggers are listed in init/guard-triggers.txt,
-- so nobody but the superuser can disable or drop them.
--
-- The evidence that names a version restricts instead of cascading: an evidence link or review keeps the
-- version it was made on.
CREATE OR REPLACE FUNCTION project.system_is_kept() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION 'card versions are kept: project.system is never truncated';
  END IF;
  RAISE EXCEPTION 'card version % is kept: a version is never deleted', OLD.pid;
END
$f$;

CREATE OR REPLACE TRIGGER system_no_delete BEFORE DELETE ON project.system
    FOR EACH ROW EXECUTE FUNCTION project.system_is_kept();
CREATE OR REPLACE TRIGGER system_no_truncate BEFORE TRUNCATE ON project.system
    FOR EACH STATEMENT EXECUTE FUNCTION project.system_is_kept();

DO $restrict$
DECLARE
  k record;
BEGIN
  FOR k IN SELECT c.conname, c.conrelid::regclass AS tbl, pg_get_constraintdef(c.oid) AS def
             FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE c.contype = 'f' AND c.confrelid = 'project.system'::regclass AND n.nspname = 'evidence'
              AND c.confdeltype <> 'r'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I, ADD CONSTRAINT %I %s ON DELETE RESTRICT',
                   k.tbl, k.conname, k.conname,
                   regexp_replace(k.def, ' ON DELETE (CASCADE|SET NULL|SET DEFAULT|NO ACTION|RESTRICT)', ''));
  END LOOP;
END
$restrict$;
