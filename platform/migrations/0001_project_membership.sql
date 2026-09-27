-- A project belongs to the people in it.
--
-- Before this, every signed-in account could list, read and change every
-- project on the platform. Membership is data rather than a realm role because
-- there is one of these per project per person: as roles it would put the shape
-- of the work into Keycloak, where no module can see it without asking.
--
-- The schema, the roles and the two core tables are made once by
-- init/platform-db.sql, which only runs on a fresh volume. Everything after
-- that is here.

CREATE TABLE IF NOT EXISTS core.project_member (
    project_id uuid NOT NULL REFERENCES core.project (pid) ON DELETE CASCADE,
    -- Keycloak's subject. Stable: an email can be changed, and a decision that
    -- keyed on one would follow the new owner of the address.
    subject    text NOT NULL,
    -- for showing a list of members to a person; never what a decision reads
    email      text,
    role       text NOT NULL CHECK (role IN ('viewer', 'editor', 'owner')),
    added_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, subject)
);

CREATE INDEX IF NOT EXISTS project_member_subject_idx ON core.project_member (subject);

-- Who made it is not a column on core.project: the first owner row says so,
-- and adding one would need ownership of a table this service only has rights
-- on. The core tables belong to the role that ran init/platform-db.sql.

COMMENT ON TABLE core.project_member IS
    'Who is in a project, and as what: viewer reads, editor changes the work, owner also decides who is in.';

-- Every module already reads core.project to resolve the project it was
-- entered inside; it reads this to answer "and may this person".
GRANT SELECT ON core.project_member TO
    qualification_rw, control_objectives_rw, controls_rw, engine_rw, catalogue_rw, dashboard_ro;
