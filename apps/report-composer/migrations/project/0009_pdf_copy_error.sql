-- Why a Word report has no PDF copy, so the list can say so instead of silently leaving out Download PDF:
-- 'renderer_unavailable' (the renderer could not make it) or 'too_large' (over 25 MB). NULL when the copy was
-- made, for a PDF report, and for a Word report made before this column. Safe on an existing install: one
-- empty column, no row changes.
ALTER TABLE report_composer.generated_report ADD COLUMN IF NOT EXISTS pdf_copy_error text
    CHECK (pdf_copy_error IS NULL OR pdf_copy_error IN ('renderer_unavailable', 'too_large'));
