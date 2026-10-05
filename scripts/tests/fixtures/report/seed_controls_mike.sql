-- Seed of project Mike's own database (schema controls), report run v2. Superuser.
-- cl-m1 answered in both versions (mean 2 in version 1, 4.5 in version 2); cl-m2 only in version 2.
SET session_replication_role = replica;
INSERT INTO controls.source (id, slug, name, updated_at) VALUES ('src-m', 'eu-ai-act', 'EU AI Act', now());
INSERT INTO controls.checklist (id, title, "sourceId", "controlTopic", updated_at) VALUES
  ('cl-m1', 'Mijke transparency', 'src-m', 'Transparency', now()),
  ('cl-m2', 'Mijke oversight', 'src-m', 'Oversight', now());
INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article) VALUES
  ('qm1', 'cl-m1', 1, 'Are residents told they talk to a bot?', 'Art. 50'),
  ('qm2', 'cl-m1', 2, 'Are the limits documented?', 'Art. 13'),
  ('qm3', 'cl-m2', 1, 'Can staff take over a conversation?', 'Art. 14');
INSERT INTO controls.submission (id, "checklistId", label, status, version, "previousVersionId", updated_at) VALUES
  ('sub-m1', 'cl-m1', 'Mike pass one', 'Closed', 1, NULL, now()),
  ('sub-m2', 'cl-m1', 'Mike pass two', 'Draft', 2, 'sub-m1', now()),
  ('sub-m3', 'cl-m2', 'Mike oversight', 'Draft', 1, NULL, now());
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at) VALUES
  ('am-1', 'sub-m1', 'qm1', 'Partly M1MARK', 2, 'f1000000-0000-4000-8000-000000000001', 1, now()),
  ('am-2', 'sub-m2', 'qm1', 'Yes, in the first message', 4, 'f2000000-0000-4000-8000-000000000002', 2, now()),
  ('am-3', 'sub-m2', 'qm2', 'Yes, on the help page', 5, 'f2000000-0000-4000-8000-000000000002', 2, now()),
  ('am-4', 'sub-m3', 'qm3', 'Yes, a button', 3, 'f2000000-0000-4000-8000-000000000002', 2, now());
SET session_replication_role = origin;
