-- Document settings and one coverage map per layout, header, footer
-- and marking per template, the format and fingerprint of a generated report, and saved presets.
-- Additive only. Every new column defaults to what the composer did before this run.

ALTER TABLE report_composer.layout
    ADD COLUMN language text NOT NULL DEFAULT 'en'
        CONSTRAINT layout_language_check CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
    ADD COLUMN toc text NOT NULL DEFAULT 'auto'
        CONSTRAINT layout_toc_check CHECK (toc IN ('auto', 'on', 'off')),
    ADD COLUMN numbering boolean NOT NULL DEFAULT false,
    ADD COLUMN coverage jsonb NOT NULL DEFAULT '[]'
        CONSTRAINT layout_coverage_check CHECK (jsonb_typeof(coverage) = 'array');

ALTER TABLE report_composer.template
    ADD COLUMN header_text text
        CONSTRAINT template_header_text_check CHECK (char_length(header_text) <= 120),
    ADD COLUMN footer_text text
        CONSTRAINT template_footer_text_check CHECK (char_length(footer_text) <= 120),
    ADD COLUMN marking text NOT NULL DEFAULT 'none'
        CONSTRAINT template_marking_check
        CHECK (marking IN ('none', 'public', 'internal', 'confidential', 'strictly_confidential')),
    ADD COLUMN show_document_id boolean NOT NULL DEFAULT false;

ALTER TABLE report_composer.generated_report
    ADD COLUMN format text NOT NULL DEFAULT 'pdf'
        CONSTRAINT generated_report_format_check CHECK (format IN ('pdf', 'docx')),
    ADD COLUMN fingerprint text;

-- A preset is a report structure without project data, seen by every signed-in user.
CREATE TABLE report_composer.preset (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text NOT NULL UNIQUE CONSTRAINT preset_name_check CHECK (char_length(name) BETWEEN 1 AND 120),
    description       text NOT NULL DEFAULT '',
    language          text CONSTRAINT preset_language_check CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
    toc               text CONSTRAINT preset_toc_check CHECK (toc IN ('auto', 'on', 'off')),
    numbering         boolean,
    blocks            jsonb NOT NULL CONSTRAINT preset_blocks_check CHECK (jsonb_typeof(blocks) = 'array'),
    source_project_id uuid REFERENCES core.project (pid) ON DELETE SET NULL,
    created_by        text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- The coverage map moves out of the first Summary block that has links: the layout takes the
-- links of its lowest-position such block, and that block's own links become empty.
-- Neither step changes a layout's revision or its time of change.
WITH first_links AS (
    SELECT DISTINCT ON (b.layout_id) b.layout_id, b.instance_id, b.options -> 'links' AS links
      FROM report_composer.layout_block b
      JOIN report_composer.layout l ON l.id = b.layout_id
     WHERE b.block_type = 'summary_coverage'
       AND jsonb_typeof(b.options -> 'links') = 'array'
       AND jsonb_array_length(b.options -> 'links') > 0
       AND l.coverage = '[]'::jsonb
     ORDER BY b.layout_id, b.position
), moved AS (
    UPDATE report_composer.layout l
       SET coverage = f.links
      FROM first_links f
     WHERE l.id = f.layout_id
    RETURNING l.id
)
UPDATE report_composer.layout_block b
   SET options = jsonb_set(b.options, '{links}', '[]'::jsonb)
  FROM first_links f
 WHERE b.layout_id = f.layout_id AND b.instance_id = f.instance_id
   AND b.layout_id IN (SELECT id FROM moved);
