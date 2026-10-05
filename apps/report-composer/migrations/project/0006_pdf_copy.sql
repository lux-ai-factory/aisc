-- Every report can be downloaded as PDF (2026-10-05). A Word report keeps the PDF rendered in the same
-- generation from the same snapshot, so both show the same data; a PDF report needs no copy.
ALTER TABLE report_composer.generated_report ADD COLUMN pdf_copy bytea;
ALTER TABLE report_composer.generated_report ADD COLUMN pdf_copy_sha256 text;
