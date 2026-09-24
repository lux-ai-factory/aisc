-- Seed of project Beta's own database (schema controls). Superuser. Beta is the leak victim, and
-- holds one checklist of 1005 answered questions, of which the block shows 1000 (R7.2.3).
SET session_replication_role = replica;
INSERT INTO controls.source (id, slug, name, updated_at) VALUES ('src-b', 'beta-src', 'Beta source BETAMARK', now());
INSERT INTO controls.checklist (id, title, "sourceId", "controlTopic", updated_at) VALUES
  ('cl-b', 'Beta checklist BETAMARK', 'src-b', 'Beta', now()),
  ('cl-big', 'Big checklist', 'src-b', 'Volume', now());
INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article) VALUES
  ('qb1', 'cl-b', 1, 'Beta question BETAMARK', 'Art. 1');
INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article)
  SELECT 'big-' || i, 'cl-big', i, 'Question ' || i, NULL FROM generate_series(1, 1005) i;
INSERT INTO controls.submission (id, "checklistId", label, status, version, updated_at) VALUES
  ('sub-b', 'cl-b', 'Beta pass BETAMARK', 'Closed', 1, now()),
  ('sub-big', 'cl-big', 'Big pass', 'Closed', 1, now());
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at) VALUES
  ('ab-1', 'sub-b', 'qb1', 'Beta answer BETAMARK', 2, 'b1000000-0000-4000-8000-000000000001', 1, now());
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at)
  SELECT 'big-a-' || i, 'sub-big', 'big-' || i, 'Answer ' || i, 3, 'b1000000-0000-4000-8000-000000000001', 1, now()
    FROM generate_series(1, 1005) i;
SET session_replication_role = origin;
