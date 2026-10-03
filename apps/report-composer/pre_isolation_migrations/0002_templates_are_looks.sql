-- A template is a report's look, not a recipe of blocks: font, base
-- font size, primary and accent colour, and a logo. It belongs to one project, which may have any
-- number; a file export carries it to another project. A layout names the template it is saved
-- with. The block-recipe templates of 0001 had no rows anywhere they ran, so they are dropped.
DROP TABLE report_composer.template;

CREATE TABLE report_composer.template (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES core.project (pid) ON DELETE CASCADE,
    name          text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
    -- one of the renderer's fonts (GET /v1/fonts); checked there and here on every write
    font          text NOT NULL CHECK (font ~ '^[a-z0-9-]{1,40}$'),
    font_size_pt  numeric(4, 1) NOT NULL CHECK (font_size_pt BETWEEN 8 AND 16),
    primary_color text NOT NULL CHECK (primary_color ~ '^#[0-9a-fA-F]{6}$'),
    accent_color  text NOT NULL CHECK (accent_color ~ '^#[0-9a-fA-F]{6}$'),
    logo_mime     text CHECK (logo_mime IN ('image/png', 'image/jpeg', 'image/svg+xml')),
    logo          bytea CHECK (octet_length(logo) <= 1048576),
    CHECK ((logo IS NULL) = (logo_mime IS NULL)),
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    text NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    updated_by    text NOT NULL,
    UNIQUE (project_id, name)
);

-- Null for a layout saved before templates were looks, or whose template was deleted: such a
-- layout previews in the platform look, and is saved (and so generated) only once one is chosen.
ALTER TABLE report_composer.layout
    ADD COLUMN template_id uuid REFERENCES report_composer.template (id) ON DELETE SET NULL;
