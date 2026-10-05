-- Drops the shared controls schema. Controls keeps each project's data in that project's
-- database (platform/project-template/0001_controls.sql); the shared schema holds only the
-- 17 example checklists once seeded into it, and no answers.
DROP SCHEMA IF EXISTS controls CASCADE;
