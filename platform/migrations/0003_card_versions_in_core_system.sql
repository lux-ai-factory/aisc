-- Card versions are rows of core.system, numbered per project.
--
-- The decided model (pipeline 2026-09-23): a project has one AI system, and what is
-- versioned is its AI card, the system's description. Each saved card version is one
-- row of core.system, numbered 1, 2, ... per project; only the latest version may
-- change. The freeze model of 0002 (core.ai_system, core.ai_system_version, drafts
-- and frozen versions) goes: its versions are carried back into core.system under the
-- pids they had, so every key into them still names the same version.
--
-- Runs as platform_rw, which must own core.system: init/project-databases.sql hands
-- it over as the superuser.

-- Isolation 2026-09-25 (03-coding-plan.md P1-D2): a volume made after the isolation has no
-- core.system (card versions live in each project database, project.system). Then everything
-- about core.system is skipped and only step 6 runs; where core.system exists (every volume that
-- already applied this file, and the pre-isolation layout the tests rebuild) the statements are
-- the same as before, in one block. plpgsql plans lazily, so the block may name tables that are
-- absent.
DO $m$
BEGIN
  IF to_regclass('core.system') IS NULL THEN
    RAISE NOTICE '0003 skipped: no core.system';
    RETURN;
  END IF;

  -- 1. the superuser must have handed core.system over (init/project-databases.sql)
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'core.system'::regclass) <> current_user THEN
    RAISE EXCEPTION 'core.system must be owned by platform_rw: run init/project-databases.sql as the superuser';
  END IF;

  -- 2. versions 0002 made that core.system does not have yet
  IF to_regclass('core.ai_system_version') IS NOT NULL THEN
    INSERT INTO core.system (pid, project_id, name, version, provider, description, created_at)
    SELECT v.pid, a.project_id, v.name, v.release, v.provider, v.description, v.created_at
      FROM core.ai_system_version v JOIN core.ai_system a ON a.pid = v.ai_system_id
     WHERE NOT EXISTS (SELECT 1 FROM core.system s WHERE s.pid = v.pid);
  END IF;

  -- 3. the version number, and who saved it
  ALTER TABLE core.system ADD COLUMN IF NOT EXISTS number integer;
  ALTER TABLE core.system ADD COLUMN IF NOT EXISTS created_by text;

  -- 4. existing rows are numbered in the order they came in
  UPDATE core.system s SET number = n.rn
    FROM (SELECT pid, row_number() OVER (PARTITION BY project_id ORDER BY created_at, pid) AS rn
            FROM core.system) n
   WHERE s.pid = n.pid AND s.number IS NULL;
  ALTER TABLE core.system ALTER COLUMN number SET NOT NULL;
  ALTER TABLE core.system ADD CONSTRAINT system_number_positive CHECK (number > 0);

  -- 5. a version is known by its number; two versions may carry the same name and release
  DROP INDEX IF EXISTS core.system_identity_idx;
  ALTER TABLE core.system DROP CONSTRAINT IF EXISTS system_project_id_name_version_key;
  ALTER TABLE core.system ADD CONSTRAINT system_project_number_key UNIQUE (project_id, number);

  -- 7. only the latest version changes, and no version changes its number or project
  CREATE FUNCTION core.system_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $f$
  BEGIN
    IF NEW.number <> OLD.number OR NEW.project_id <> OLD.project_id
       OR OLD.number < (SELECT max(number) FROM core.system WHERE project_id = OLD.project_id) THEN
      RAISE EXCEPTION 'system version % of project % is not the latest and cannot change',
        OLD.number, OLD.project_id;
    END IF;
    RETURN NEW;
  END $f$;
  CREATE TRIGGER system_only_latest_changes BEFORE UPDATE ON core.system
    FOR EACH ROW EXECUTE FUNCTION core.system_only_latest_changes();

  -- 8.
  COMMENT ON TABLE core.system IS
    'One saved AI card version of the project''s one AI system; number 1, 2, ... per project.';
END $m$;

-- 6. the freeze model goes (unconditional: 0002 made it on every volume)
DROP TABLE IF EXISTS core.ai_system_version CASCADE;
DROP TABLE IF EXISTS core.ai_system CASCADE;
DROP FUNCTION IF EXISTS core.ai_system_version_is_frozen();
