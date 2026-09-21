-- The platform's own database.
--
-- Runs once on a fresh Postgres volume, before any app migrates. Every module
-- already keeps its own database -- qualification, controls, control_objectives,
-- aisc, superset -- and each has its own idea of what it is working on: a
-- qualification, a submission, a project, a project again. Nothing ties them
-- together, so the same assessment cannot be followed from step 1 to step 6.
--
-- This is the one thing they can share: a project, defined once, at the
-- platform level. It deliberately holds nothing else yet. Modules keep their own
-- databases and will reference this project by its id when they are wired to it,
-- one at a time.
CREATE DATABASE platform;

\connect platform

-- pid is what every other service and URL will carry, so it is the identity:
-- generated here, never reused, and stable for the life of the assessment.
CREATE TABLE project (
    pid         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    -- a short, URL-safe handle, unique, for addressing a project in a path
    slug        text NOT NULL UNIQUE,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX project_created_at_idx ON project (created_at DESC);

COMMENT ON TABLE  project IS 'An assessment, defined once for the whole platform.';
COMMENT ON COLUMN project.pid IS 'The identity every module will reference.';
COMMENT ON COLUMN project.slug IS 'URL-safe handle, unique.';
