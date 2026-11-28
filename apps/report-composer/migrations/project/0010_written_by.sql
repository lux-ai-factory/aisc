-- Who last changed each text written in a layout (a block's commentary, a free text, a chapter's introduction, a
-- tool's commentary), and when, kept with the revision a save makes: {instance id: {path: {sub, by, at}}}.
-- NULL for a revision saved before this column: its texts name nobody. Safe on an existing install: one empty
-- column, no row changes, so the append-only revisions stay as they were.
ALTER TABLE report_composer.layout_revision ADD COLUMN IF NOT EXISTS written jsonb;
