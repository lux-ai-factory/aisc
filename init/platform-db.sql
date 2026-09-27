-- The platform database: what every project shares, and nothing that belongs to one project.
--
-- Runs once on a fresh Postgres volume, before any app migrates.
--
-- One database per project (isolation 2026-09-25, docs/superpowers/isolation-2026-09-25/01-specs.md
-- I1.3, I1.4, I2.8). Every module keeps a project's data in that project's own database
-- (project_<pid without hyphens>, made by the platform service from platform/project-template/):
-- the card versions (project.system), qualification, control objectives, controls, the engine and
-- the report composer. What stays here is only what knows no project: the projects and who is in
-- them (core), the catalogue of tests and controls, the install-wide library of qualification
-- forms (form_library, D3) and of report presets (report_library, D4).
--
-- Why schemas and roles rather than trust. Each module reads the projects and their members and
-- nothing else here; the grants below are the contract, and the isolation's verify script asserts
-- it by role (has_*_privilege). The pre-isolation version of this file, which made core.system and
-- the module schemas, is kept as a test fixture at
-- scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql.
--
-- Created only if it is not already the bootstrap database: POSTGRES_DB is `platform`, and the
-- image makes that one itself before running this script.
SELECT 'CREATE DATABASE platform'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'platform')\gexec

\connect platform

-- No object creation in public: an unqualified CREATE should fail loudly rather
-- than land somewhere nobody looks. (On PG14 public also grants CREATE to
-- PUBLIC, which would make every role below able to create tables here.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- core: the projects and their members. Written by the platform service only;
-- every module reads it and none may change it. core.project_member and
-- core.schema_migration are made by the platform's own migrations.
-- ---------------------------------------------------------------------------
CREATE SCHEMA core;

-- An assessment. Its pid names its database: project_<pid without hyphens>.
CREATE TABLE core.project (
    pid         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX project_created_at_idx ON core.project (created_at DESC);

COMMENT ON TABLE core.project IS 'An assessment, defined once for the whole platform.';

-- ---------------------------------------------------------------------------
-- the catalogue: reference data, the same for every project
-- ---------------------------------------------------------------------------
CREATE SCHEMA catalogue;
COMMENT ON SCHEMA catalogue IS 'Step 3: the registry of tests and controls. Reference data: the same for every project, so nothing in it belongs to one.';

-- ---------------------------------------------------------------------------
-- roles: a module may connect here, read the projects and their members, and
-- nothing else; everything it writes is in a project database.
--
-- Passwords are dev values, as everywhere else in this compose. Each app is
-- given only its own role, so a mistake in one module cannot read another's
-- data or rewrite the project it belongs to.
-- ---------------------------------------------------------------------------
-- Roles are cluster-wide, so one may already exist. Creating them
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
        -- the catalogue: the registry of tests and controls
        ('catalogue_rw'),
        -- the report composer (init/report-roles.sql sets its real password on every start)
        ('report_composer_rw'),
        -- the platform service: the only writer of the core
        ('platform_rw'),
        -- the dashboard: reads each project's database, and here only who is in which project
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
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw,
    report_composer_rw, platform_rw, dashboard_ro;
GRANT USAGE ON SCHEMA core TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw,
    report_composer_rw, dashboard_ro;

-- A module reads core.project to resolve the project it was entered inside (I1.4): SELECT only, no
-- REFERENCES (no module table here points at it any more). dashboard_ro reads memberships only;
-- core.project_member's SELECT comes from platform migrations 0001 and 0005, which make it.
GRANT SELECT ON core.project TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw, report_composer_rw;

-- the core belongs to the platform service
GRANT USAGE, CREATE ON SCHEMA core TO platform_rw;
GRANT ALL ON ALL TABLES IN SCHEMA core TO platform_rw;
GRANT ALL ON ALL SEQUENCES IN SCHEMA core TO platform_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT ALL ON TABLES TO platform_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT ALL ON SEQUENCES TO platform_rw;

-- the catalogue belongs to its module
GRANT USAGE, CREATE ON SCHEMA catalogue TO catalogue_rw;
ALTER ROLE catalogue_rw IN DATABASE platform SET search_path = catalogue, core;

-- The two install-wide libraries: they hold no project's data (D3, D4). Each is owned by the module
-- that migrates it; a project copies what it uses into its own database.
CREATE SCHEMA form_library AUTHORIZATION qualification_rw;
COMMENT ON SCHEMA form_library IS 'The install-wide library of qualification forms (D3): no project data.';
CREATE SCHEMA report_library AUTHORIZATION report_composer_rw;
COMMENT ON SCHEMA report_library IS 'The install-wide library of report presets (D4): no project data.';

ALTER ROLE platform_rw  IN DATABASE platform SET search_path = core;
ALTER ROLE dashboard_ro IN DATABASE platform SET search_path = core;
