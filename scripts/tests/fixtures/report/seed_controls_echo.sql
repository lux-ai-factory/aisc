-- Seed of project Echo's own database (schema controls), for the end-to-end test. Superuser.
SET session_replication_role = replica;
INSERT INTO controls.source (id, slug, name, updated_at) VALUES ('src-e', 'eu-ai-act', 'EU AI Act', now());
INSERT INTO controls.checklist (id, title, "sourceId", "controlTopic", updated_at) VALUES
  ('cl-e', 'Echo checklist', 'src-e', 'Transparency', now());
INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article) VALUES
  ('qe1', 'cl-e', 1, 'Is it documented?', 'Art. 13'),
  ('qe2', 'cl-e', 2, 'Is it logged?', 'Art. 12');
INSERT INTO controls.submission (id, "checklistId", label, status, version, "previousVersionId", updated_at) VALUES
  ('sub-e1', 'cl-e', 'Echo pass one', 'Closed', 1, NULL, now()),
  ('sub-e2', 'cl-e', 'Echo pass two', 'Draft', 2, 'sub-e1', now());
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at) VALUES
  ('ae-1', 'sub-e1', 'qe1', 'Answer E1MARK', 2, 'e1000000-0000-4000-8000-000000000001', 1, now()),
  ('ae-2', 'sub-e2', 'qe1', 'Answer E2MARK', 4, 'e2000000-0000-4000-8000-000000000002', 2, now()),
  ('ae-3', 'sub-e2', 'qe2', 'Logged E2MARK', 5, 'e2000000-0000-4000-8000-000000000002', 2, now());
SET session_replication_role = origin;
