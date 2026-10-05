-- A deleted layout keeps its reports. Deleting a layout sets deleted_at; every layout read leaves it
-- out, and its name is free again. Its generated reports stay, still downloadable. The reports' key
-- becomes RESTRICT, so no hard delete of a layout can remove them.
ALTER TABLE report_composer.layout ADD COLUMN deleted_at timestamptz;

ALTER TABLE report_composer.layout DROP CONSTRAINT layout_name_key;
CREATE UNIQUE INDEX layout_name_key ON report_composer.layout (name) WHERE deleted_at IS NULL;

ALTER TABLE report_composer.generated_report DROP CONSTRAINT generated_report_layout_id_fkey;
ALTER TABLE report_composer.generated_report ADD CONSTRAINT generated_report_layout_id_fkey
    FOREIGN KEY (layout_id) REFERENCES report_composer.layout (id) ON DELETE RESTRICT;
