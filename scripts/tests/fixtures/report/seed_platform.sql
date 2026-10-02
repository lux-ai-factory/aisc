-- Seed of the report test bed (report run 2026-09-23, 02 section 5 step 4), database `platform`.
-- Run as the superuser after the schema fixtures. Fixed ids: scripts/lib/report_bed.py (IDS).
--
-- Markers: every text that belongs to a version other than the one a test pins carries a marker
-- (V1MARK, V3MARK, NULLMARK, BETAMARK, ARCHMARK), so "no other version's data" is one assertion:
-- the marker is absent from the HTML. Version 2 of project A is the usual pinned version.

-- Superuser: the module triggers (only the latest card changes, ...) and the engine's deferrable
-- foreign keys are for the apps' own writes; the seed loads history in one go.
SET session_replication_role = replica;

-- ── core ─────────────────────────────────────────────────────────────────────
INSERT INTO core.project (pid, name, slug, description) VALUES
  ('a0000000-0000-4000-8000-000000000001', 'Alpha project', 'alpha', 'The main test project'),
  ('b0000000-0000-4000-8000-000000000001', 'Beta project BETAMARK', 'beta', 'The victim of every leak test'),
  ('c0000000-0000-4000-8000-000000000001', 'Gamma project', 'gamma', 'A version and nothing else, no project database'),
  ('e0000000-0000-4000-8000-000000000001', 'Echo project', 'echo', 'The end-to-end project');

INSERT INTO core.system (pid, project_id, number, name, version, provider, description, created_at, created_by) VALUES
  ('a1000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000001', 1, 'Alpha scorer', '0.9', 'Acme AI', 'first card V1MARK', '2026-09-01 08:00+00', 'alice'),
  ('a2000000-0000-4000-8000-000000000002', 'a0000000-0000-4000-8000-000000000001', 2, 'Alpha scorer', '1.0', 'Acme AI', 'second card', '2026-09-08 08:00+00', 'alice'),
  ('a3000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000001', 3, 'Alpha scorer', '1.1', 'Acme AI', 'third card V3MARK', '2026-09-15 08:00+00', 'alice'),
  ('b1000000-0000-4000-8000-000000000001', 'b0000000-0000-4000-8000-000000000001', 1, 'Beta bot BETAMARK', NULL, NULL, 'beta card BETAMARK', '2026-09-02 08:00+00', 'bob'),
  ('c1000000-0000-4000-8000-000000000001', 'c0000000-0000-4000-8000-000000000001', 1, 'Gamma model', NULL, NULL, NULL, '2026-09-03 08:00+00', 'alice'),
  ('e1000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001', 1, 'Echo assistant', '1', 'Echo Labs', 'echo card E1MARK', '2026-09-04 08:00+00', 'erin'),
  ('e2000000-0000-4000-8000-000000000002', 'e0000000-0000-4000-8000-000000000001', 2, 'Echo assistant', '2', 'Echo Labs', 'echo card E2MARK', '2026-09-05 08:00+00', 'erin');

INSERT INTO core.project_member (project_id, subject, email, role) VALUES
  ('a0000000-0000-4000-8000-000000000001', 'olga',   'olga@localhost',   'owner'),
  ('a0000000-0000-4000-8000-000000000001', 'alice',  'alice@localhost',  'editor'),
  ('a0000000-0000-4000-8000-000000000001', 'victor', 'victor@localhost', 'viewer'),
  ('b0000000-0000-4000-8000-000000000001', 'bob',    'bob@localhost',    'editor'),
  ('c0000000-0000-4000-8000-000000000001', 'alice',  'alice@localhost',  'editor'),
  ('e0000000-0000-4000-8000-000000000001', 'erin',   'erin@localhost',   'owner');

-- ── qualification (cards) ────────────────────────────────────────────────────
INSERT INTO qualification.qualification
  (id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", updated_at,
   "targetSystemTags", "sectorTags", "marketFormTags", "localityTags", "intendedDeployers", project_id, system_id) VALUES
  ('q-a1', 'Alpha scorer', '0.9', 'Acme AI', 'Scores loan files V1MARK', 'Credit scoring V1MARK', 'Loan officers', now(),
   '{}', '{finance}', '{}', '{}', NULL, 'a0000000-0000-4000-8000-000000000001', 'a1000000-0000-4000-8000-000000000001'),
  ('q-a2', 'Alpha scorer', '1.0', 'Acme AI', 'Scores loan files with explanations', 'Credit scoring', 'Loan officers', now(),
   '{scoring}', '{finance}', '{b2b}', '{eu}', 'Retail banks', 'a0000000-0000-4000-8000-000000000001', 'a2000000-0000-4000-8000-000000000002'),
  ('q-b1', 'Beta bot BETAMARK', '1', 'Beta corp BETAMARK', 'Beta description BETAMARK', 'Chat BETAMARK', 'Anyone', now(),
   '{}', '{}', '{}', '{}', NULL, 'b0000000-0000-4000-8000-000000000001', 'b1000000-0000-4000-8000-000000000001'),
  ('q-e1', 'Echo assistant', '1', 'Echo Labs', 'Echo card E1MARK', 'Help desk', 'Staff', now(),
   '{}', '{}', '{}', '{}', NULL, 'e0000000-0000-4000-8000-000000000001', 'e1000000-0000-4000-8000-000000000001'),
  ('q-e2', 'Echo assistant', '2', 'Echo Labs', 'Echo card E2MARK', 'Help desk', 'Staff', now(),
   '{}', '{}', '{}', '{}', NULL, 'e0000000-0000-4000-8000-000000000001', 'e2000000-0000-4000-8000-000000000002');

-- inserted out of order: the block orders by linked_at, then name (R2.2.3)
INSERT INTO qualification.card_component (id, qualification_id, component_pid, airo_property, name, component_type, object_name, linked_at) VALUES
  ('cc-2', 'q-a2', 'a2c00000-0000-4000-8000-000000000002', 'hasTestingData', 'Holdout set', 'dataset', 'holdout.csv', '2026-09-08 10:00+00'),
  ('cc-1', 'q-a2', 'a2c00000-0000-4000-8000-000000000001', 'hasModel', 'Gradient model', 'model', 'model.pkl', '2026-09-08 09:00+00'),
  ('cc-3', 'q-a2', 'a2c00000-0000-4000-8000-000000000003', 'hasTrainingData', 'Applications 2025', 'dataset', 'train.csv', '2026-09-08 09:00+00'),
  ('cc-v1', 'q-a1', 'a1c00000-0000-4000-8000-000000000001', 'hasModel', 'Old model V1MARK', 'model', 'old.pkl', '2026-09-01 09:00+00'),
  ('cc-b', 'q-b1', 'b1c00000-0000-4000-8000-000000000001', 'hasModel', 'Beta model BETAMARK', 'model', 'beta.pkl', '2026-09-02 09:00+00'),
  ('cc-e2', 'q-e2', 'e2c00000-0000-4000-8000-000000000001', 'hasModel', 'Echo model E2MARK', 'model', 'echo.bin', '2026-09-05 09:00+00');

INSERT INTO qualification.knowledge_graph (id, "qualificationId", digest, turtle, jsonld, nodes, triples, built_at) VALUES
  ('kg-a2', 'q-a2', '0123456789abcdef0123456789abcdef', '# turtle',
   '{"@graph": [
      {"@id": "urn:aisc:system:alpha", "@type": "https://w3id.org/airo#AISystem",
       "https://w3id.org/airo#isProvidedBy": {"@id": "urn:aisc:org:acme"},
       "https://w3id.org/airo#isDeployedBy": {"@id": "urn:aisc:org:bank"},
       "https://w3id.org/airo#hasAIUser": {"@id": "urn:aisc:user:officer"}},
      {"@id": "urn:aisc:org:acme", "http://www.w3.org/2000/01/rdf-schema#label": "Acme AI (provider)"},
      {"@id": "urn:aisc:org:bank", "http://www.w3.org/2000/01/rdf-schema#label": "Retail Bank (deployer)"},
      {"@id": "urn:aisc:user:officer"}
    ]}', 4, 7, '2026-09-08 11:00+00'),
  ('kg-a1', 'q-a1', 'ffffffffffffffffffffffffffffffff', '# turtle',
   '{"@graph": [
      {"@id": "urn:aisc:system:alpha1", "@type": "https://w3id.org/airo#AISystem",
       "https://w3id.org/airo#isProvidedBy": {"@id": "urn:aisc:org:old"}},
      {"@id": "urn:aisc:org:old", "http://www.w3.org/2000/01/rdf-schema#label": "Old provider V1MARK"}
    ]}', 2, 3, '2026-09-01 11:00+00'),
  ('kg-b1', 'q-b1', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '# turtle',
   '{"@graph": [
      {"@id": "urn:aisc:system:beta", "@type": "https://w3id.org/airo#AISystem",
       "https://w3id.org/airo#isProvidedBy": {"@id": "urn:aisc:org:beta"}},
      {"@id": "urn:aisc:org:beta", "http://www.w3.org/2000/01/rdf-schema#label": "Beta corp BETAMARK"}
    ]}', 2, 3, '2026-09-02 11:00+00');

-- `affected` and `impactAreas` are vocabulary ids (fixture airo_vocab.json); the rest is free text (D3).
-- inserted out of order: the block orders by position (R2.3.3)
INSERT INTO qualification.qualification_risk (id, "qualificationId", "position", risk, source, vulnerability, consequence, affected, "impactAreas", control, "followUpControl") VALUES
  ('qr-2', 'q-a2', 2, 'Opaque refusals', 'Model complexity', NULL, 'Applicants cannot contest', 'user', '{fundamental_rights}', 'Explanations', NULL),
  ('qr-1', 'q-a2', 1, 'Bias against applicants <script>alert(1)</script>', 'Training data', 'Historic bias', 'Unfair refusals', 'operator', '{health,safety}', 'Bias audit', 'Quarterly review'),
  ('qr-v1', 'q-a1', 1, 'Old risk V1MARK', 'x', NULL, 'x', 'operator', '{}', 'x', NULL),
  ('qr-b', 'q-b1', 1, 'Beta risk BETAMARK', 'x', NULL, 'x', 'user', '{}', 'x', NULL),
  ('qr-e2', 'q-e2', 1, 'Echo risk E2MARK', 'x', NULL, 'x', 'user', '{}', 'x', NULL),
  ('qr-e1', 'q-e1', 1, 'Echo risk E1MARK', 'x', NULL, 'x', 'user', '{}', 'x', NULL);

-- ── control objectives (assessments) ─────────────────────────────────────────
INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, project_id, system_id) VALUES
  ('coa1', 'Alpha v1', 'd1', now(), now(), 'a0000000-0000-4000-8000-000000000001', 'a1000000-0000-4000-8000-000000000001'),
  ('coa2', 'Alpha v2', 'd2', now(), now(), 'a0000000-0000-4000-8000-000000000001', 'a2000000-0000-4000-8000-000000000002'),
  ('cob1', 'Beta v1', 'd3', now(), now(), 'b0000000-0000-4000-8000-000000000001', 'b1000000-0000-4000-8000-000000000001'),
  ('coe1', 'Echo v1', 'd4', now(), now(), 'e0000000-0000-4000-8000-000000000001', 'e1000000-0000-4000-8000-000000000001'),
  ('coe2', 'Echo v2', 'd5', now(), now(), 'e0000000-0000-4000-8000-000000000001', 'e2000000-0000-4000-8000-000000000002');

INSERT INTO control_objectives.risk (id, project_id, risk_id, "position", text, short_label, source, vulnerability, consequence, impact, stakeholder, control, follow_up_control, areas, vair_terms, provenance, rating_impact, rating_likelihood) VALUES
  (201, 'coa2', 'R-1', 1, 'Bias against applicants', 'Bias', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 4, 3),
  (202, 'coa2', 'R-2', 2, 'Opaque refusals', 'Opacity', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 2, NULL),
  (101, 'coa1', 'R-1', 1, 'Old risk V1MARK', 'Old', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 1, NULL),
  (301, 'cob1', 'R-1', 1, 'Beta risk BETAMARK', 'Beta', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 1, NULL),
  (401, 'coe1', 'R-1', 1, 'Echo risk E1MARK', 'Echo1', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 1, NULL),
  (402, 'coe2', 'R-1', 1, 'Echo risk E2MARK', 'Echo2', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 3, 2);

-- version 2 of Alpha: objectives R1.1, R2.1, R4.1, R5.1 (the fixture CSV labels them)
INSERT INTO control_objectives.mapped_objective (id, risk_row_id, objective_id, quote, rationale) VALUES
  (1, 201, 'R1.1', 'quote one', 'oversight counters bias'),
  (2, 201, 'R2.1', 'quote two', 'data governance counters bias'),
  (3, 202, 'R2.1', 'quote three', 'records explain refusals'),
  (4, 202, 'R4.1', 'quote four', 'accuracy of refusals'),
  (5, 202, 'R5.1', 'quote five', 'transparency to applicants'),
  (6, 101, 'R3.1', 'quote V1MARK', 'rationale V1MARK'),
  (7, 301, 'R3.1', 'quote BETAMARK', 'rationale BETAMARK'),
  (8, 401, 'R3.1', 'quote E1MARK', 'rationale E1MARK'),
  (9, 402, 'R1.1', 'quote E2MARK', 'rationale E2MARK');

INSERT INTO control_objectives.mapping_run (project_id, findings, stops, stop, attempts, error, model, ran_at) VALUES
  ('coa1', '[]', '[]', 'clean', 1, '', 'm', '2026-09-01 12:00+00'),
  ('coa2', '[]', '[]', 'cap', 3, '', 'm', '2026-09-09 12:00+00'),
  ('coe2', '[]', '[]', 'clean', 1, '', 'm', '2026-09-05 12:00+00');

-- ── engine (test results) ────────────────────────────────────────────────────

INSERT INTO engine.aisc_backend_project (id, pid, name, description, status, created_at, project_id) VALUES
  (1, 'a0e00000-0000-4000-8000-000000000001', 'Alpha', '', 'active', now(), 'a0000000-0000-4000-8000-000000000001'),
  (2, 'b0e00000-0000-4000-8000-000000000001', 'Beta BETAMARK', '', 'active', now(), 'b0000000-0000-4000-8000-000000000001'),
  (5, 'e0e00000-0000-4000-8000-000000000001', 'Echo', '', 'active', now(), 'e0000000-0000-4000-8000-000000000001');

INSERT INTO engine.aisc_backend_aisystem (id, pid, name, description, created_at, project_id) VALUES
  (1, 'a0e50000-0000-4000-8000-000000000001', 'Alpha', '', now(), 1),
  (2, 'b0e50000-0000-4000-8000-000000000001', 'Beta', '', now(), 2),
  (5, 'e0e50000-0000-4000-8000-000000000001', 'Echo', '', now(), 5);

INSERT INTO engine.aisc_backend_aicomponent (id, pid, name, description, created_at, data, storage_container, component_type, json_value, system_id) VALUES
  (1, 'a0ec0000-0000-4000-8000-000000000001', 'Scoring model endpoint', '', now(), '', '', 'model', '{}', 1),
  (2, 'a0ec0000-0000-4000-8000-000000000002', 'Holdout prompts', '', now(), '', '', 'dataset', '{}', 1),
  (3, 'b0ec0000-0000-4000-8000-000000000001', 'Beta endpoint BETAMARK', '', now(), '', '', 'model', '{}', 2),
  (5, 'e0ec0000-0000-4000-8000-000000000001', 'Echo endpoint', '', now(), '', '', 'model', '{}', 5);

INSERT INTO engine.aisc_backend_plugin (id, pid, name, description, project_id, package_name, version, display_name, created_at, enabled) VALUES
  (1, 'a0ef0000-0000-4000-8000-000000000001', 'MLARejectEvaluationPlugin', '', 1, 'aisc-plugin-mlareject', '1.0', 'MLA-Reject', now(), true),
  (2, 'a0ef0000-0000-4000-8000-000000000002', 'LangBiTeEvaluationPlugin', '', 1, 'aisc-plugin-langbite', '2.0', 'LangBiTe', now(), true),
  (3, 'a0ef0000-0000-4000-8000-000000000003', 'MysteryEvaluationPlugin', '', 1, 'aisc-plugin-mystery', '0.1', 'Mystery Tool', now(), true),
  (4, 'b0ef0000-0000-4000-8000-000000000001', 'LangBiTeEvaluationPlugin', '', 2, 'aisc-plugin-langbite', '2.0', 'LangBiTe', now(), true),
  (5, 'e0ef0000-0000-4000-8000-000000000001', 'LangBiTeEvaluationPlugin', '', 5, 'aisc-plugin-langbite', '2.0', 'LangBiTe', now(), true);

-- plugin_config.config may hold tool settings; report_ro gets (id, plugin_id) only (D6)
INSERT INTO engine.aisc_backend_pluginconfig (id, pid, config, created_at, plugin_id, description, name) VALUES
  (1, 'a0eb0000-0000-4000-8000-000000000001', '{"api_key": "CONFIGSECRET"}', now(), 1, '', 'c1'),
  (2, 'a0eb0000-0000-4000-8000-000000000002', '{"api_key": "CONFIGSECRET"}', now(), 2, '', 'c2'),
  (3, 'a0eb0000-0000-4000-8000-000000000003', '{}', now(), 3, '', 'c3'),
  (4, 'b0eb0000-0000-4000-8000-000000000001', '{}', now(), 4, '', 'c4'),
  (5, 'e0eb0000-0000-4000-8000-000000000001', '{}', now(), 5, '', 'c5');

INSERT INTO engine.aisc_backend_metric (id, pid, name, description, type_spec, created_at) VALUES
  (1, 'a0e30000-0000-4000-8000-000000000001', 'score', '', 'float', now()),
  (2, 'a0e30000-0000-4000-8000-000000000002', 'bias_rate', '', 'float', now()),
  (3, 'a0e30000-0000-4000-8000-000000000003', 'mystery_metric', '', 'float', now()),
  (4, 'a0e30000-0000-4000-8000-000000000004', 'beta_metric_BETAMARK', '', 'float', now()),
  (5, 'a0e30000-0000-4000-8000-000000000005', 'accuracy_E1MARK', '', 'float', now()),
  (6, 'a0e30000-0000-4000-8000-000000000006', 'accuracy_E2MARK', '', 'float', now()),
  (7, 'a0e30000-0000-4000-8000-000000000007', 'bias_rate_V1MARK', '', 'float', now()),
  (8, 'a0e30000-0000-4000-8000-000000000008', 'bias_rate_V3MARK', '', 'float', now()),
  (9, 'a0e30000-0000-4000-8000-000000000009', 'bias_rate_NULLMARK', '', 'float', now());

-- evaluations: A v1 (Done, MLA-Reject + LangBiTe), A v2 (Done: LangBiTe + Mystery; and one Failed),
-- A v3 (Done), A unversioned (Done), B v1 (Done), E v1 and E v2 (Done)
INSERT INTO engine.aisc_backend_evaluation (id, pid, status, project_id, system_id, created_at) VALUES
  (11, 'a1e00000-0000-4000-8000-000000000011', 'Done',   1, 'a1000000-0000-4000-8000-000000000001', '2026-09-02 09:00+00'),
  (21, 'a2e00000-0000-4000-8000-000000000021', 'Done',   1, 'a2000000-0000-4000-8000-000000000002', '2026-09-10 09:00+00'),
  (22, 'a2e00000-0000-4000-8000-000000000022', 'Failed', 1, 'a2000000-0000-4000-8000-000000000002', '2026-09-11 09:00+00'),
  (23, 'a2e00000-0000-4000-8000-000000000023', 'Done',   1, 'a2000000-0000-4000-8000-000000000002', '2026-09-09 09:00+00'),
  (31, 'a3e00000-0000-4000-8000-000000000031', 'Done',   1, 'a3000000-0000-4000-8000-000000000003', '2026-09-16 09:00+00'),
  (41, 'a0e00000-0000-4000-8000-000000000041', 'Done',   1, NULL, '2026-09-12 09:00+00'),
  (42, 'a0e00000-0000-4000-8000-000000000042', 'Done',   1, NULL, '2026-09-12 10:00+00'),
  (51, 'b1e00000-0000-4000-8000-000000000051', 'Done',   2, 'b1000000-0000-4000-8000-000000000001', '2026-09-03 09:00+00'),
  (61, 'e1e00000-0000-4000-8000-000000000061', 'Done',   5, 'e1000000-0000-4000-8000-000000000001', '2026-09-04 12:00+00'),
  (62, 'e2e00000-0000-4000-8000-000000000062', 'Done',   5, 'e2000000-0000-4000-8000-000000000002', '2026-09-05 12:00+00');

INSERT INTO engine.aisc_backend_evaluationplugin (id, pid, name, description, evaluation_id, plugin_config_id, error_message, started_at, finished_at, status, created_at) VALUES
  (111, 'a1ea0000-0000-4000-8000-000000000111', 'MLARejectEvaluationPlugin', '', 11, 1, '', now(), now(), 'Done', now()),
  (112, 'a1ea0000-0000-4000-8000-000000000112', 'LangBiTeEvaluationPlugin', '', 11, 2, '', now(), now(), 'Done', now()),
  (211, 'a2ea0000-0000-4000-8000-000000000211', 'LangBiTeEvaluationPlugin', '', 21, 2, '', now(), now(), 'Done', now()),
  (212, 'a2ea0000-0000-4000-8000-000000000212', 'MysteryEvaluationPlugin', '', 21, 3, '', now(), now(), 'Done', now()),
  (221, 'a2ea0000-0000-4000-8000-000000000221', 'LangBiTeEvaluationPlugin', '', 22, 2, 'boom', now(), now(), 'Failed', now()),
  (231, 'a2ea0000-0000-4000-8000-000000000231', 'LangBiTeEvaluationPlugin', '', 23, NULL, '', now(), now(), 'Done', now()),
  (311, 'a3ea0000-0000-4000-8000-000000000311', 'LangBiTeEvaluationPlugin', '', 31, 2, '', now(), now(), 'Done', now()),
  (411, 'a0ea0000-0000-4000-8000-000000000411', 'LangBiTeEvaluationPlugin', '', 41, 2, '', now(), now(), 'Done', now()),
  (421, 'a0ea0000-0000-4000-8000-000000000421', 'LangBiTeEvaluationPlugin', '', 42, 2, '', now(), now(), 'Done', now()),
  (511, 'b1ea0000-0000-4000-8000-000000000511', 'LangBiTeEvaluationPlugin', '', 51, 4, '', now(), now(), 'Done', now()),
  (611, 'e1ea0000-0000-4000-8000-000000000611', 'LangBiTeEvaluationPlugin', '', 61, 5, '', now(), now(), 'Done', now()),
  (621, 'e2ea0000-0000-4000-8000-000000000621', 'LangBiTeEvaluationPlugin', '', 62, 5, '', now(), now(), 'Done', now());

-- several inputs per plugin run (D16): LangBiTe of v2 ran on the endpoint and the prompts
INSERT INTO engine.aisc_backend_evaluationinput (id, pid, name, description, created_at, value, component_id, evaluation_plugin_id) VALUES
  (1, 'a0ed0000-0000-4000-8000-000000000001', 'model', '', now(), '{}', 1, 111),
  (2, 'a0ed0000-0000-4000-8000-000000000002', 'model', '', now(), '{}', 1, 112),
  (3, 'a0ed0000-0000-4000-8000-000000000003', 'model', '', now(), '{}', 1, 211),
  (4, 'a0ed0000-0000-4000-8000-000000000004', 'prompts', '', now(), '{}', 2, 211),
  (5, 'a0ed0000-0000-4000-8000-000000000005', 'model', '', now(), '{}', 1, 212),
  (6, 'b0ed0000-0000-4000-8000-000000000001', 'model', '', now(), '{}', 3, 511),
  (7, 'e0ed0000-0000-4000-8000-000000000001', 'model', '', now(), '{}', 5, 611),
  (8, 'e0ed0000-0000-4000-8000-000000000002', 'model', '', now(), '{}', 5, 621);

-- observation.tool = "{package_name}::{name} (v{version})" ties an observation to its plugin run (D8)
INSERT INTO engine.aisc_backend_observation (id, pid, name, description, observer, tool, evaluation_id, created_at) VALUES
  (1101, 'a1eb0000-0000-4000-8000-000000001101', 'mla', '', 'engine', 'aisc-plugin-mlareject::MLARejectEvaluationPlugin (v1.0)', 11, now()),
  (1102, 'a1eb0000-0000-4000-8000-000000001102', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 11, now()),
  (2101, 'a2eb0000-0000-4000-8000-000000002101', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 21, now()),
  (2102, 'a2eb0000-0000-4000-8000-000000002102', 'my', '', 'engine', 'aisc-plugin-mystery::MysteryEvaluationPlugin (v0.1)', 21, now()),
  (2103, 'a2eb0000-0000-4000-8000-000000002103', 'orphan', '', 'engine', 'some-other-tool::Unknown (v9)', 21, now()),
  (2301, 'a2eb0000-0000-4000-8000-000000002301', 'lb', '', 'engine', 'whatever', 23, now()),
  (3101, 'a3eb0000-0000-4000-8000-000000003101', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 31, now()),
  (4101, 'a0eb0000-0000-4000-8000-000000004101', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 41, now()),
  (5101, 'b1eb0000-0000-4000-8000-000000005101', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 51, now()),
  (6101, 'e1eb0000-0000-4000-8000-000000006101', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 61, now()),
  (6201, 'e2eb0000-0000-4000-8000-000000006201', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiTeEvaluationPlugin (v2.0)', 62, now());

INSERT INTO engine.aisc_backend_measurement (id, pid, name, description, unit, "time", score, error, uncertainty, metric_id, observation_id, created_at, dimensions, direction) VALUES
  -- A v1, MLA-Reject: score per case, with language / jailbreak / category dimensions (D9)
  (1, gen_random_uuid(), 'score', '', NULL, now(), 4.0, NULL, 0, 1, 1101, now(), '{"language": "en", "jailbreak": "dan", "category": "hate"}', NULL),
  (2, gen_random_uuid(), 'score', '', NULL, now(), 1.0, NULL, 0, 1, 1101, now(), '{"language": "fr", "jailbreak": "aim", "category": "violence"}', NULL),
  (3, gen_random_uuid(), 'score', '', NULL, now(), 2.5, NULL, 0, 1, 1101, now(), '{"language": "en", "jailbreak": "aim"}', NULL),
  (4, gen_random_uuid(), 'bias_rate_V1MARK', '', '%', now(), 0.25, NULL, 0, 7, 1102, now(), NULL, NULL),
  -- A v2
  (5, gen_random_uuid(), 'bias_rate', '', '%', now(), 0.125, NULL, 0.01, 2, 2101, now(), NULL, 'lower'),
  (6, gen_random_uuid(), 'bias_rate', '', '%', now(), 0.375, NULL, 0.01, 2, 2103, now(), NULL, 'lower'),
  (7, gen_random_uuid(), 'bias_rate', '', '%', now(), 0.5, NULL, 0.01, 2, 2301, now(), NULL, 'lower'),
  -- A v3, unversioned, B v1, Echo
  (8, gen_random_uuid(), 'bias_rate_V3MARK', '', '%', now(), 0.0625, NULL, 0, 8, 3101, now(), NULL, NULL),
  (9, gen_random_uuid(), 'bias_rate_NULLMARK', '', '%', now(), 0.999, NULL, 0, 9, 4101, now(), NULL, NULL),
  (10, gen_random_uuid(), 'beta_metric_BETAMARK', '', NULL, now(), 0.777, NULL, 0, 4, 5101, now(), NULL, NULL),
  (11, gen_random_uuid(), 'accuracy_E1MARK', '', NULL, now(), 0.111, NULL, 0, 5, 6101, now(), NULL, NULL),
  (12, gen_random_uuid(), 'accuracy_E2MARK', '', NULL, now(), 0.222, NULL, 0, 6, 6201, now(), NULL, NULL);

-- A v2, Mystery Tool (no renderer): 505 measurements, of which the generic renderer shows 500 (R7.2.3)
INSERT INTO engine.aisc_backend_measurement (id, pid, name, description, unit, "time", score, error, uncertainty, metric_id, observation_id, created_at, dimensions, direction)
SELECT 1000 + i, gen_random_uuid(), 'mystery_metric', '', 'pt', now(), i, NULL, 0, 3, 2102, now(), NULL, NULL
  FROM generate_series(1, 505) AS i;

INSERT INTO engine.aisc_backend_artifact (id, pid, name, description, data, storage_container, evaluation_plugin_id, created_at, file_size) VALUES
  (1, gen_random_uuid(), 'langbite-report.csv', '', 'ARTIFACTCONTENT', 'bucket', 211, now(), 2048),
  (2, gen_random_uuid(), 'old-report V1MARK.csv', '', 'ARTIFACTCONTENT', 'bucket', 112, now(), 10);

SET session_replication_role = origin;
