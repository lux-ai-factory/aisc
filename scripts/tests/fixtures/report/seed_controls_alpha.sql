-- Seed of project Alpha's own database (schema controls), report test bed. Superuser.
-- Version 2 of Alpha is a2000000-...-02; see seed_platform.sql for the markers.
SET session_replication_role = replica;
INSERT INTO controls.source (id, slug, name, updated_at) VALUES ('src-1', 'eu-ai-act', 'EU AI Act', now());

INSERT INTO controls.checklist (id, title, "sourceId", "controlTopic", description, updated_at) VALUES
  ('cl-1', 'Transparency checklist', 'src-1', 'Transparency', 'Art. 13 duties', now()),
  ('cl-2', 'Oversight checklist', 'src-1', 'Oversight', NULL, now()),
  ('cl-3', 'Unanswered checklist', 'src-1', 'Records', NULL, now());

-- inserted out of "order": the block orders by it (R2.6.2)
INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article, category) VALUES
  ('q2', 'cl-1', 2, 'Are deployers told the limits?', 'Art. 13(3)', 'info'),
  ('q1', 'cl-1', 1, 'Is the system documented?', 'Art. 13(1)', 'info'),
  ('q4', 'cl-1', 4, 'Is the log kept?', 'Art. 12', 'records'),
  ('q3', 'cl-1', 3, 'Are instructions for use written?', 'Art. 13(2)', 'info'),
  ('q5', 'cl-2', 1, 'Can an operator halt it?', 'Art. 14', 'oversight'),
  ('q6', 'cl-3', 1, 'Nobody answered this', 'Art. 12', 'records');

INSERT INTO controls.submission (id, "checklistId", label, status, version, "previousVersionId", closed_at, archived_at, updated_at) VALUES
  ('sub-1', 'cl-1', 'First pass', 'Closed', 1, NULL, now(), NULL, now()),
  ('sub-2', 'cl-1', 'Second pass', 'Draft', 2, 'sub-1', NULL, NULL, now()),
  ('sub-3', 'cl-1', 'Archived pass ARCHMARK', 'Closed', 3, 'sub-2', now(), now(), now()),
  ('sub-4', 'cl-2', 'Oversight pass', 'Closed', 1, NULL, now(), NULL, now()),
  ('sub-5', 'cl-2', 'Oversight pass two', 'Draft', 2, 'sub-4', NULL, NULL, now());

INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at) VALUES
  ('a-1', 'sub-1', 'q1', 'Yes V1MARK', 5, 'a1000000-0000-4000-8000-000000000001', 1, now()),
  ('a-2', 'sub-2', 'q1', 'Documented in the manual', 4, 'a2000000-0000-4000-8000-000000000002', 2, now()),
  ('a-3', 'sub-2', 'q2', 'Partly <b>bold</b>', 1, 'a2000000-0000-4000-8000-000000000002', 2, now()),
  ('a-4', 'sub-2', 'q3', 'Old answer V1MARK', 3, 'a1000000-0000-4000-8000-000000000001', 1, now()),
  ('a-5', 'sub-2', 'q4', 'Unstamped NULLMARK', 2, NULL, NULL, now()),
  ('a-6', 'sub-3', 'q1', 'Archived answer ARCHMARK', 5, 'a2000000-0000-4000-8000-000000000002', 2, now()),
  ('a-7', 'sub-4', 'q5', 'Oversight V1MARK', 3, 'a1000000-0000-4000-8000-000000000001', 1, now()),
  ('a-8', 'sub-5', 'q5', 'Oversight V3MARK', 4, 'a3000000-0000-4000-8000-000000000003', 3, now());
SET session_replication_role = origin;
