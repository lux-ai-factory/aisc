-- A generated report points at its project and its version the way its layout does.
--
-- 0001 gave generated_report a key to its layout only; its project_id and system_id pointed at
-- nothing. They get the layout's keys, with the layout's ON DELETE rules: the project's key
-- cascades, and the version's has no rule (NO ACTION, not RESTRICT: deleting a project cascades
-- through core.system and here in one statement, and the check runs at its end).
ALTER TABLE report_composer.generated_report
    ADD CONSTRAINT generated_report_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES core.project (pid) ON DELETE CASCADE;
ALTER TABLE report_composer.generated_report
    ADD CONSTRAINT generated_report_system_id_fkey
    FOREIGN KEY (system_id) REFERENCES core.system (pid);
