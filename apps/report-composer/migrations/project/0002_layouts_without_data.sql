-- A layout is structure only; the data a report covers
-- (the AI card version, the period of test runs, other versions, the version compared with) is
-- chosen when it is generated and recorded on the report.
ALTER TABLE report_composer.layout ADD COLUMN show_index boolean NOT NULL DEFAULT true;
UPDATE report_composer.layout SET show_index = (toc <> 'off');
ALTER TABLE report_composer.layout
    DROP CONSTRAINT layout_toc_check, DROP COLUMN toc,
    DROP CONSTRAINT layout_language_check, DROP COLUMN language,
    DROP CONSTRAINT layout_system_id_fkey, DROP COLUMN system_id;

-- options that named one run or one version leave the layout
UPDATE report_composer.layout_block SET options = options - 'evaluations' WHERE block_type = 'test_results';
UPDATE report_composer.layout_block SET options = jsonb_set(options, '{compare_to}', '"previous"')
    WHERE block_type = 'changes_since' AND options ? 'compare_to' AND options->>'compare_to' <> 'previous';

ALTER TABLE report_composer.generated_report
    ADD COLUMN period_from timestamptz,
    ADD COLUMN period_to timestamptz,
    ADD COLUMN other_versions boolean NOT NULL DEFAULT false,
    ADD COLUMN compare_to uuid CONSTRAINT generated_report_compare_to_fkey REFERENCES project.system (pid),
    ADD CONSTRAINT generated_report_period_check
        CHECK (period_from IS NULL OR period_to IS NULL OR period_from < period_to);
