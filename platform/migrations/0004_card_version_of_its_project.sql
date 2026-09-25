-- A card version belongs to its project: core.system is unique on (pid, project_id).
--
-- The modules that pin their work to one card version (qualification.qualification,
-- control_objectives.project, report_composer.layout and report_composer.generated_report)
-- point at this pair, so a row cannot name project A and a version of project B. A key
-- into the pair needs a unique constraint on it; pid is the primary key, so every row
-- already satisfies it.
--
-- The same constraint is made in two other places, and this file is a no-op after them:
--   init/platform-db.sql makes it on a fresh volume, before any module can connect;
--   init/project-databases.sql (postgres-setup, as the superuser, on every start) makes it
--   on an existing volume, and adds the key of any module whose migration ran before the
--   constraint existed and had to leave its key out.
-- A module's key is its own to add: this role does not own the module tables.
--
-- 8190233523 is the lock those places and the module migrations share, so that no two of
-- them check and add at the same time.

SELECT pg_advisory_xact_lock(8190233523);

-- Isolation 2026-09-25 (03-coding-plan.md P1-D2): without core.system (a volume made after the
-- isolation) there is nothing to constrain.
DO $$
BEGIN
  IF to_regclass('core.system') IS NULL THEN
    RETURN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'core.system'::regclass AND conname = 'system_pid_project_id_key') THEN
    ALTER TABLE core.system ADD CONSTRAINT system_pid_project_id_key UNIQUE (pid, project_id);
  END IF;
END $$;
