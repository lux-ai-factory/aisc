-- One AI system per project, in versions that do not change once used.
--
-- core.system let a project name any number of systems, each a row that could
-- be edited in place, so an evaluation or an AI card could end up describing a
-- system that had since become something else. Now a project has one AI system
-- (core.ai_system), and what the modules point at is a version of it
-- (core.ai_system_version). The latest version is a draft until something
-- depends on it; then it is frozen, and the next edit makes the version after
-- it. platform_service/ai_system.py is the rule; this is what holds it.
--
-- core.system stays for now: qualification and the engine hold foreign keys
-- into it, and they move to core.ai_system_version in their own migrations.
-- Every row of it is carried over below under the same pid, so those keys
-- already name the right version. Dropping it takes the superuser that made it.

CREATE TABLE core.ai_system (
    pid        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- one per project, which is the point
    project_id uuid NOT NULL UNIQUE REFERENCES core.project (pid) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.ai_system_version (
    pid           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ai_system_id  uuid NOT NULL REFERENCES core.ai_system (pid) ON DELETE CASCADE,
    -- 1, 2, 3: ours, and the order they came in
    number        integer NOT NULL CHECK (number > 0),
    name          text NOT NULL CHECK (btrim(name) <> ''),
    -- what its makers call this release ("1.2.0"), if anything; kept as written
    release       text,
    provider      text,
    description   text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    text,
    -- set once, when something first depends on this version
    frozen_at     timestamptz,
    frozen_reason text,
    UNIQUE (ai_system_id, number)
);

-- At most one draft per system. The platform only ever makes the next version
-- after freezing the latest, so the one draft is also the latest.
CREATE UNIQUE INDEX ai_system_one_draft
    ON core.ai_system_version (ai_system_id) WHERE frozen_at IS NULL;

-- A frozen version is what an evaluation ran against or a card described.
-- Nothing changes it, including a query that forgets to look.
CREATE FUNCTION core.ai_system_version_is_frozen() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.frozen_at IS NOT NULL THEN
        RAISE EXCEPTION 'AI system version % is frozen', OLD.pid;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER ai_system_version_frozen
    BEFORE UPDATE ON core.ai_system_version
    FOR EACH ROW EXECUTE FUNCTION core.ai_system_version_is_frozen();

-- Carry over. Every project gets its system; each row of core.system becomes a
-- version of it, oldest first, under the pid it already had. All of them are
-- frozen: a row of core.system was only ever made by qualification when an AI
-- card was submitted for it (the engine never named one), and a version with
-- a submitted card is frozen. The next edit makes the version after them.
INSERT INTO core.ai_system (project_id)
SELECT pid FROM core.project;

--
-- Isolation 2026-09-25 (03-coding-plan.md P1-D2): a volume made after the isolation has no
-- core.system (card versions live in each project database), so the carry-over runs only when it
-- exists; where it exists (every volume that already applied this file) it is the same statement.
-- plpgsql plans lazily, so the branch may name a table that is absent.
DO $$
BEGIN
  IF to_regclass('core.system') IS NOT NULL THEN
    INSERT INTO core.ai_system_version
        (pid, ai_system_id, number, name, release, provider, description, created_at,
         frozen_at, frozen_reason)
    SELECT s.pid, a.pid,
           row_number() OVER (PARTITION BY s.project_id ORDER BY s.created_at, s.pid),
           s.name, s.version, s.provider, s.description, s.created_at,
           now(), 'ai card (carried over from core.system)'
      FROM core.system s
      JOIN core.ai_system a ON a.project_id = s.project_id;
  END IF;
END $$;

-- A project that never named a system starts with a draft named after itself.
INSERT INTO core.ai_system_version (ai_system_id, number, name)
SELECT a.pid, 1, p.name
  FROM core.ai_system a
  JOIN core.project p ON p.pid = a.project_id
 WHERE NOT EXISTS (SELECT 1 FROM core.ai_system_version v WHERE v.ai_system_id = a.pid);

COMMENT ON TABLE core.ai_system IS
    'The one AI system of a project: qualification describes it, the engine tests it.';
COMMENT ON TABLE core.ai_system_version IS
    'A version of a project''s AI system. The latest is a draft until something depends on it, then frozen for good.';

-- Read by every module, as core.system was; referenced by the ones that pin
-- their work to a version.
GRANT SELECT ON core.ai_system, core.ai_system_version TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw, dashboard_ro;
GRANT REFERENCES ON core.ai_system_version TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw;
