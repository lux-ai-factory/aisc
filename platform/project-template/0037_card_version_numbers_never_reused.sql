-- A card version number is handed out once per project, ever. Ledger events, reports and checklist answers
-- cite a version by its number, so a number given to a version that later went (a hand removal) must not be
-- given to another. The highest number handed out is kept in a one-row counter that only goes up; the
-- platform advances it under the advisory lock it takes for every new version.
--
-- Safe on an existing install: the counter starts at the highest number the project's versions or its
-- ledger outbox have ever named (a removed version's card_version.created event still names its number), so
-- no existing version is renumbered and the next save gets a number nobody has had.
CREATE TABLE IF NOT EXISTS project.system_number (
    only_row  boolean PRIMARY KEY DEFAULT true CHECK (only_row),
    last      integer NOT NULL CHECK (last >= 0)
);
COMMENT ON TABLE project.system_number IS
    'The highest card version number ever handed out in this project: the next version takes the one after it';

INSERT INTO project.system_number (only_row, last)
SELECT true, greatest(
         (SELECT coalesce(max(number), 0) FROM project.system),
         (SELECT coalesce(max(item_version::integer), 0) FROM ledger.outbox
           WHERE action = 'card_version.created' AND item_version ~ '^[0-9]{1,9}$'))
ON CONFLICT (only_row) DO NOTHING;

-- The counter never goes down and is never emptied.
CREATE OR REPLACE FUNCTION project.system_number_only_rises() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.last >= OLD.last THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'the card version counter only goes up: a number is never handed out twice';
END
$f$;
CREATE OR REPLACE TRIGGER system_number_only_rises BEFORE UPDATE OR DELETE ON project.system_number
    FOR EACH ROW EXECUTE FUNCTION project.system_number_only_rises();
CREATE OR REPLACE TRIGGER system_number_no_truncate BEFORE TRUNCATE ON project.system_number
    FOR EACH STATEMENT EXECUTE FUNCTION project.system_number_only_rises();

REVOKE ALL ON project.system_number FROM PUBLIC;
DO $g$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_rw') THEN
    REVOKE ALL ON project.system_number FROM platform_rw;
    GRANT SELECT, UPDATE ON project.system_number TO platform_rw;
  END IF;
END
$g$;
