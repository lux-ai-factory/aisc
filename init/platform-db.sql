-- The platform database: one database, one core, one schema per module.
--
-- Runs once on a fresh Postgres volume, before any app migrates.
--
-- Why one database. Every module used to keep its own -- qualification,
-- controls, control_objectives, aisc -- and each had its own idea of what it
-- was working on. The same assessment could not be followed from step 1 to
-- step 6, and the same AI system appeared as a `systemName` string in one place
-- and a `model` row in another, with nothing connecting them.
--
-- Why schemas and roles rather than trust. One database does not mean one
-- namespace and it does not mean everyone sees everything: each module owns a
-- schema, reads the core, and is refused the rest. The grants below are the
-- contract, and scripts/verify-db-access.sh asserts it by connecting as each
-- role and trying what it must and must not be able to do.
CREATE DATABASE platform;

\connect platform

-- No object creation in public: an unqualified CREATE should fail loudly rather
-- than land somewhere nobody looks. (On PG14 public also grants CREATE to
-- PUBLIC, which would make every role below able to create tables here.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- core: what the whole platform shares. Written by the platform service only;
-- every module reads it and none may change it.
-- ---------------------------------------------------------------------------
CREATE SCHEMA core;

-- An assessment.
CREATE TABLE core.project (
    pid         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX project_created_at_idx ON core.project (created_at DESC);

-- The AI system under assessment: the thing qualification describes and the
-- thing the engine runs tests against. One row, referenced by both, so
-- "the system" means the same object in every module.
CREATE TABLE core.system (
    pid         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES core.project (pid) ON DELETE CASCADE,
    name        text NOT NULL,
    version     text,
    provider    text,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    -- a system's name is unique inside its project, not globally: two projects
    -- may legitimately assess systems with the same name
    UNIQUE (project_id, name, version)
);
CREATE INDEX system_project_idx ON core.system (project_id);

COMMENT ON TABLE core.project IS 'An assessment, defined once for the whole platform.';
COMMENT ON TABLE core.system  IS 'The AI system under assessment: qualification describes it, the engine tests it.';

-- ---------------------------------------------------------------------------
-- one schema per module
-- ---------------------------------------------------------------------------
CREATE SCHEMA qualification;
CREATE SCHEMA control_objectives;
CREATE SCHEMA controls;
CREATE SCHEMA engine;

COMMENT ON SCHEMA qualification      IS 'Step 1: qualifications and system cards.';
COMMENT ON SCHEMA control_objectives IS 'Step 2: risks, mappings and their runs.';
COMMENT ON SCHEMA controls           IS 'Step 5: checklists, submissions and answers.';
COMMENT ON SCHEMA engine             IS 'Step 4: datasets, models, plugins, evaluations, measurements.';

-- ---------------------------------------------------------------------------
-- roles: a module may write its own schema, read the core, and nothing else.
--
-- Passwords are dev values, as everywhere else in this compose. Each app is
-- given only its own role, so a mistake in one module cannot read another's
-- data or rewrite the project it belongs to.
-- ---------------------------------------------------------------------------
-- Roles are cluster-wide, so one may already exist (dashboard_ro is created by
-- init/dashboard-ro.sql for the engine's database). Creating them
-- conditionally keeps this script runnable on a cluster that is not empty.
DO $roles$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('qualification_rw'),
        ('control_objectives_rw'),
        ('controls_rw'),
        ('engine_rw'),
        -- the platform service: the only writer of the core
        ('platform_rw'),
        -- the dashboard: reads everything, writes nothing
        ('dashboard_ro')
    ) AS t(role_name)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.role_name) THEN
            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', r.role_name, r.role_name);
        END IF;
    END LOOP;
END
$roles$;

-- everyone may connect, and see the core
GRANT CONNECT ON DATABASE platform TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, platform_rw, dashboard_ro;
GRANT USAGE ON SCHEMA core TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, dashboard_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, dashboard_ro;

-- the core belongs to the platform service
GRANT USAGE, CREATE ON SCHEMA core TO platform_rw;
GRANT ALL ON ALL TABLES IN SCHEMA core TO platform_rw;
GRANT ALL ON ALL SEQUENCES IN SCHEMA core TO platform_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT ALL ON TABLES TO platform_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT ALL ON SEQUENCES TO platform_rw;

-- each module owns its schema: it migrates and writes there, and the dashboard
-- may read it
DO $$
DECLARE
    m record;
BEGIN
    FOR m IN SELECT * FROM (VALUES
        ('qualification',      'qualification_rw'),
        ('control_objectives', 'control_objectives_rw'),
        ('controls',           'controls_rw'),
        ('engine',             'engine_rw')
    ) AS t(schema_name, role_name)
    LOOP
        EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO %I', m.schema_name, m.role_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL ON TABLES TO %I',
                       m.role_name, m.schema_name, m.role_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT ALL ON SEQUENCES TO %I',
                       m.role_name, m.schema_name, m.role_name);
        -- the dashboard reads what the module creates, now and later
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO dashboard_ro', m.schema_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO dashboard_ro',
                       m.role_name, m.schema_name);
        -- a module's default search_path is its own schema, so an unqualified
        -- CREATE TABLE from its migrations lands in the right place
        EXECUTE format('ALTER ROLE %I IN DATABASE platform SET search_path = %I, core',
                       m.role_name, m.schema_name);
    END LOOP;
END
$$;

ALTER ROLE platform_rw  IN DATABASE platform SET search_path = core;
ALTER ROLE dashboard_ro IN DATABASE platform SET search_path = core, qualification, control_objectives, controls, engine;
