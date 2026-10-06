-- A built-in layout generates reports like the project's own (2026-10-06). A report belongs to a layout of
-- the project, so a built-in gets one record per project (builtin_id = its id, e.g. builtin-summary), made
-- at its first report and kept in step with the built-in at every report. The record is not one of the
-- project's layouts: never listed, never edited, and its name stays free for the project's own layouts.
ALTER TABLE report_composer.layout ADD COLUMN builtin_id text;
CREATE UNIQUE INDEX layout_builtin_id_key ON report_composer.layout (builtin_id) WHERE builtin_id IS NOT NULL;

DROP INDEX report_composer.layout_name_key;
CREATE UNIQUE INDEX layout_name_key ON report_composer.layout (name) WHERE deleted_at IS NULL AND builtin_id IS NULL;
