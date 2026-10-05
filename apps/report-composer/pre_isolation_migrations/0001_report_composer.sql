-- The composer's own tables, in the shared schema before each project had its own database.
CREATE TABLE report_composer.layout (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES core.project (pid) ON DELETE CASCADE,
    -- NO ACTION, not RESTRICT: deleting a project cascades through core.system and here in one statement
    system_id   uuid NOT NULL REFERENCES core.system (pid),
    name        text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    description text NOT NULL DEFAULT '',
    revision    integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL,
    UNIQUE (project_id, name)
);
CREATE TABLE report_composer.layout_block (
    layout_id   uuid NOT NULL REFERENCES report_composer.layout (id) ON DELETE CASCADE,
    instance_id uuid NOT NULL,
    position    integer NOT NULL CHECK (position >= 0),
    block_type  text NOT NULL,
    options     jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (layout_id, instance_id),
    UNIQUE (layout_id, position)
);
CREATE TABLE report_composer.template (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text NOT NULL UNIQUE CHECK (char_length(name) BETWEEN 1 AND 120),
    description       text NOT NULL DEFAULT '',
    blocks            jsonb NOT NULL,
    source_project_id uuid REFERENCES core.project (pid) ON DELETE SET NULL,
    created_by        text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE report_composer.generated_report (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layout_id       uuid NOT NULL REFERENCES report_composer.layout (id) ON DELETE CASCADE,
    layout_revision integer NOT NULL,
    project_id      uuid NOT NULL,
    system_id       uuid NOT NULL,
    snapshot        jsonb NOT NULL,
    status          text NOT NULL CHECK (status IN ('running', 'done', 'partial', 'failed')),
    pdf             bytea,
    sha256          text,
    size_bytes      integer,
    block_statuses  jsonb NOT NULL DEFAULT '[]',
    error_ref       text,
    error_code      text,
    created_by      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX generated_report_layout_idx ON report_composer.generated_report (layout_id, created_at DESC);
