-- Seed of project Delta's own database (schema controls), report run v2. Superuser.
SET session_replication_role = replica;
INSERT INTO controls.source (id, slug, name, updated_at) VALUES ('src-d', 'eu-ai-act', 'EU AI Act', now());
INSERT INTO controls.checklist (id, title, "sourceId", "controlTopic", updated_at) VALUES
  ('cl-d', 'Delta checklist', 'src-d', 'Records', now());
INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article) VALUES
  ('qd1', 'cl-d', 1, 'Are forms logged?', 'Art. 12');
INSERT INTO controls.submission (id, "checklistId", label, status, version, "previousVersionId", updated_at) VALUES
  ('sub-d1', 'cl-d', 'Delta pass', 'Closed', 1, NULL, now());
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at) VALUES
  ('ad-1', 'sub-d1', 'qd1', 'Yes', 4, 'd1000000-0000-4000-8000-000000000001', 1, now());
SET session_replication_role = origin;
