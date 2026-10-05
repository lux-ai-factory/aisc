-- The composer's tables in one project's database.
--
-- The shape that pre_isolation_migrations/0001..0005 made in the shared schema, minus the column that
-- named the project: the database is the project. Column order and constraint names are those of the
-- shared tables, so the platform's data move copies column by column. The version keys point at this
-- database's project.system (NO ACTION). The install-wide structures saved by users live in the
-- library (migrations/library/), not here.
-- Schema only: the coverage-map data step of the shared schema's 0005 ran before the rows were moved.
-- Nothing is granted: the readers get no access to these tables.

CREATE TABLE report_composer.template (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    -- one of the renderer's fonts (GET /v1/fonts); checked there and here on every write
    font             text NOT NULL CHECK (font ~ '^[a-z0-9-]{1,40}$'),
    font_size_pt     numeric(4, 1) NOT NULL CHECK (font_size_pt BETWEEN 8 AND 16),
    primary_color    text NOT NULL CHECK (primary_color ~ '^#[0-9a-fA-F]{6}$'),
    accent_color     text NOT NULL CHECK (accent_color ~ '^#[0-9a-fA-F]{6}$'),
    logo_mime        text CHECK (logo_mime IN ('image/png', 'image/jpeg', 'image/svg+xml')),
    logo             bytea CHECK (octet_length(logo) <= 1048576),
    CHECK ((logo IS NULL) = (logo_mime IS NULL)),
    created_at       timestamptz NOT NULL DEFAULT now(),
    created_by       text NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    updated_by       text NOT NULL,
    header_text      text CONSTRAINT template_header_text_check CHECK (char_length(header_text) <= 120),
    footer_text      text CONSTRAINT template_footer_text_check CHECK (char_length(footer_text) <= 120),
    marking          text NOT NULL DEFAULT 'none' CONSTRAINT template_marking_check
                     CHECK (marking IN ('none', 'public', 'internal', 'confidential', 'strictly_confidential')),
    show_document_id boolean NOT NULL DEFAULT false,
    CONSTRAINT template_name_key UNIQUE (name)
);

CREATE TABLE report_composer.layout (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id   uuid NOT NULL CONSTRAINT layout_system_id_fkey REFERENCES project.system (pid),
    name        text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    description text NOT NULL DEFAULT '',
    revision    integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL,
    -- null for a layout whose template was deleted: it previews in the platform look
    template_id uuid CONSTRAINT layout_template_id_fkey REFERENCES report_composer.template (id) ON DELETE SET NULL,
    -- kept although reports are English only: the data move copies it
    language    text NOT NULL DEFAULT 'en' CONSTRAINT layout_language_check CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
    toc         text NOT NULL DEFAULT 'auto' CONSTRAINT layout_toc_check CHECK (toc IN ('auto', 'on', 'off')),
    numbering   boolean NOT NULL DEFAULT false,
    coverage    jsonb NOT NULL DEFAULT '[]' CONSTRAINT layout_coverage_check CHECK (jsonb_typeof(coverage) = 'array'),
    CONSTRAINT layout_name_key UNIQUE (name)
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

CREATE TABLE report_composer.generated_report (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layout_id       uuid NOT NULL REFERENCES report_composer.layout (id) ON DELETE CASCADE,
    layout_revision integer NOT NULL,
    system_id       uuid NOT NULL CONSTRAINT generated_report_system_id_fkey REFERENCES project.system (pid),
    snapshot        jsonb NOT NULL,
    status          text NOT NULL CHECK (status IN ('running', 'done', 'partial', 'failed')),
    -- the bytes of either format (pdf, docx)
    pdf             bytea,
    sha256          text,
    size_bytes      integer,
    block_statuses  jsonb NOT NULL DEFAULT '[]',
    error_ref       text,
    error_code      text,
    created_by      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    format          text NOT NULL DEFAULT 'pdf' CONSTRAINT generated_report_format_check CHECK (format IN ('pdf', 'docx')),
    fingerprint     text
);
CREATE INDEX generated_report_layout_idx ON report_composer.generated_report (layout_id, created_at DESC);
