-- Seed of the report test bed, report run v2 (2026-09-24, 01-specs.md section 22), database `platform`.
-- Run as the superuser after seed_platform.sql. Fixed ids: scripts/lib/report_bed.py (IDS).
--
-- Project Mike (slug mike): the three Mijke tools, with measurements in the exact name and description
-- formats of the plugin sources (01-specs.md 3.4): LangBiTe 0.1.1, StrongREJECT 0.1.0, promptfoo 0.1.0.
--   version 2 (M_V2): five evaluations, see below; version 1 (M_V1): a smaller set, for changes_since.
--   Data that belongs to version 1 only carries the marker M1MARK.
-- Project Delta (slug delta): one version with a card, an objectives assessment and a checklist, and NO
--   evaluation at all (the "version with no evaluations" of the compatibility goldens, R-C.2).
-- Both projects belong to mia only, so no existing test's project lists change.

SET session_replication_role = replica;

-- ── core ─────────────────────────────────────────────────────────────────────
INSERT INTO core.project (pid, name, slug, description) VALUES
  ('f0000000-0000-4000-8000-000000000001', 'Mike project', 'mike', 'The Mijke tools project'),
  ('d0000000-0000-4000-8000-000000000001', 'Delta project', 'delta', 'A version with no evaluation');

INSERT INTO core.system (pid, project_id, number, name, version, provider, description, created_at, created_by) VALUES
  ('f1000000-0000-4000-8000-000000000001', 'f0000000-0000-4000-8000-000000000001', 1, 'Mijke', '0.9', 'City of Eindhoven', 'Referral chatbot M1MARK', '2026-09-11 08:00+00', 'mia'),
  ('f2000000-0000-4000-8000-000000000002', 'f0000000-0000-4000-8000-000000000001', 2, 'Mijke', '1.0', 'City of Eindhoven', 'Referral chatbot, second release', '2026-09-18 08:00+00', 'mia'),
  ('d1000000-0000-4000-8000-000000000001', 'd0000000-0000-4000-8000-000000000001', 1, 'Delta helper', '1.0', 'Delta Labs', 'delta card', '2026-09-06 08:00+00', 'mia');

INSERT INTO core.project_member (project_id, subject, email, role) VALUES
  ('f0000000-0000-4000-8000-000000000001', 'mia', 'mia@localhost', 'owner'),
  ('d0000000-0000-4000-8000-000000000001', 'mia', 'mia@localhost', 'owner');

-- ── qualification (cards) ────────────────────────────────────────────────────
INSERT INTO qualification.qualification
  (id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", updated_at,
   "targetSystemTags", "sectorTags", "marketFormTags", "localityTags", "intendedDeployers", project_id, system_id) VALUES
  ('q-m1', 'Mijke', '0.9', 'City of Eindhoven', 'Refers residents to services M1MARK', 'Referral', 'Residents', now(),
   '{chatbot}', '{public}', '{}', '{nl}', 'Municipality', 'f0000000-0000-4000-8000-000000000001', 'f1000000-0000-4000-8000-000000000001'),
  ('q-m2', 'Mijke', '1.0', 'City of Eindhoven', 'Refers residents to municipal services', 'Referral', 'Residents', now(),
   '{chatbot,referral}', '{public}', '{}', '{nl}', 'Municipality', 'f0000000-0000-4000-8000-000000000001', 'f2000000-0000-4000-8000-000000000002'),
  ('q-d1', 'Delta helper', '1.0', 'Delta Labs', 'Helps with forms', 'Form help', 'Staff', now(),
   '{}', '{}', '{}', '{}', NULL, 'd0000000-0000-4000-8000-000000000001', 'd1000000-0000-4000-8000-000000000001');

INSERT INTO qualification.card_component (id, qualification_id, component_pid, airo_property, name, component_type, object_name, linked_at) VALUES
  ('cc-m1', 'q-m1', 'f1c00000-0000-4000-8000-000000000001', 'hasModel', 'Mijke chat model', 'model', 'mijke', '2026-09-11 09:00+00'),
  ('cc-m2a', 'q-m2', 'f2c00000-0000-4000-8000-000000000001', 'hasModel', 'Mijke chat model', 'model', 'mijke', '2026-09-18 09:00+00'),
  ('cc-m2b', 'q-m2', 'f2c00000-0000-4000-8000-000000000002', 'hasTestingData', 'Referral FAQ', 'dataset', 'faq.csv', '2026-09-18 10:00+00');

INSERT INTO qualification.qualification_risk (id, "qualificationId", "position", risk, source, vulnerability, consequence, affected, "impactAreas", control, "followUpControl") VALUES
  ('qr-m1', 'q-m1', 1, 'Wrong referral', 'Model', NULL, 'Resident sent to the wrong desk', 'user', '{}', 'Review', NULL),
  ('qr-m2a', 'q-m2', 1, 'Wrong referral', 'Model', NULL, 'Resident sent to the wrong desk', 'user', '{}', 'Review', NULL),
  ('qr-m2b', 'q-m2', 2, 'Biased answers', 'Training data', NULL, 'Unequal treatment', 'user', '{fundamental_rights}', 'Bias tests', NULL),
  ('qr-d1', 'q-d1', 1, 'Delta risk', 'x', NULL, 'x', 'user', '{}', 'x', NULL);

-- ── control objectives: (impact, likelihood) in version 2: (5, 4) rating 20 Critical, (3, -) 9 Medium,
-- (1, 2) 2 Low, (-, -) not rated, (4, -) 12 High; an unrated part counts 3 (01-specs.md 22, schema 2026-10-01) ──
INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, project_id, system_id) VALUES
  ('com1', 'Mike v1', 'dm1', now(), now(), 'f0000000-0000-4000-8000-000000000001', 'f1000000-0000-4000-8000-000000000001'),
  ('com2', 'Mike v2', 'dm2', now(), now(), 'f0000000-0000-4000-8000-000000000001', 'f2000000-0000-4000-8000-000000000002'),
  ('cod1', 'Delta v1', 'dd1', now(), now(), 'd0000000-0000-4000-8000-000000000001', 'd1000000-0000-4000-8000-000000000001');

INSERT INTO control_objectives.risk (id, project_id, risk_id, "position", text, short_label, source, vulnerability, consequence, impact, stakeholder, control, follow_up_control, areas, vair_terms, provenance, rating_impact, rating_likelihood) VALUES
  (601, 'com2', 'R-1', 1, 'Wrong referral', 'Referral', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 5, 4),
  (602, 'com2', 'R-2', 2, 'Biased answers', 'Bias', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 3, NULL),
  (603, 'com2', 'R-3', 3, 'Outdated information', 'Outdated', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 1, 2),
  (604, 'com2', 'R-4', 4, 'Unclear limits', 'Limits', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', NULL, NULL),
  (605, 'com2', 'R-5', 5, 'Unmapped risk', 'Unmapped', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 4, NULL),
  -- version 1: R-1 was impact 3 x likelihood 3 = 9 (20 in version 2), R-9 went away in version 2
  (651, 'com1', 'R-1', 1, 'Wrong referral', 'Referral', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 3, 3),
  (659, 'com1', 'R-9', 2, 'Old risk M1MARK', 'OldM1', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 2, NULL),
  (701, 'cod1', 'R-1', 1, 'Delta risk', 'Delta', 's', 'v', 'c', 'i', 'st', 'ctl', 'fu', '{}', '{}', 'card', 3, NULL);

-- version 2: R1.1 (impact 5), R2.1 (3), R4.1 (1), R5.1 (not rated); R-5 maps to nothing.
-- version 1: R1.1 and R3.1 (R3.1 removed and R2.1, R4.1, R5.1 added in version 2)
INSERT INTO control_objectives.mapped_objective (id, risk_row_id, objective_id, quote, rationale) VALUES
  (61, 601, 'R1.1', 'mq one', 'oversight of referrals'),
  (62, 602, 'R2.1', 'mq two', 'data governance counters bias'),
  (63, 603, 'R4.1', 'mq three', 'accuracy of information'),
  (64, 604, 'R5.1', 'mq four', 'transparency about limits'),
  (65, 651, 'R1.1', 'mq M1MARK', 'rationale M1MARK'),
  (66, 659, 'R3.1', 'mq M1MARK', 'rationale M1MARK'),
  (71, 701, 'R3.1', 'dq', 'delta logs');

INSERT INTO control_objectives.mapping_run (project_id, findings, stops, stop, attempts, error, model, ran_at) VALUES
  ('com1', '[]', '[]', 'clean', 1, '', 'm', '2026-09-11 12:00+00'),
  ('com2', '[]', '[]', 'clean', 1, '', 'm', '2026-09-18 12:00+00'),
  ('cod1', '[]', '[]', 'clean', 1, '', 'm', '2026-09-06 12:00+00');

-- ── engine: the three Mijke tools (Delta has no engine rows at all) ─────────
INSERT INTO engine.aisc_backend_project (id, pid, name, description, status, created_at, project_id) VALUES
  (6, 'f0e00000-0000-4000-8000-000000000001', 'Mike', '', 'active', now(), 'f0000000-0000-4000-8000-000000000001');
INSERT INTO engine.aisc_backend_aisystem (id, pid, name, description, created_at, project_id) VALUES
  (6, 'f0e50000-0000-4000-8000-000000000001', 'Mike', '', now(), 6);
INSERT INTO engine.aisc_backend_aicomponent (id, pid, name, description, created_at, data, storage_container, component_type, json_value, system_id) VALUES
  (6, 'f0ec0000-0000-4000-8000-000000000001', 'Mijke endpoint', '', now(), '', '', 'model', '{}', 6);

INSERT INTO engine.aisc_backend_plugin (id, pid, name, description, project_id, package_name, version, display_name, created_at, enabled) VALUES
  (6, 'f0ef0000-0000-4000-8000-000000000006', 'LangBiteEvaluationPlugin', '', 6, 'aisc-plugin-langbite', '0.1.1', 'LangBiTe', now(), true),
  (7, 'f0ef0000-0000-4000-8000-000000000007', 'StrongRejectPlugin', '', 6, 'aisc-plugin-strongreject', '0.1.0', 'StrongREJECT', now(), true),
  (8, 'f0ef0000-0000-4000-8000-000000000008', 'PromptfooPlugin', '', 6, 'aisc-plugin-promptfoo', '0.1.0', 'Promptfoo', now(), true);
INSERT INTO engine.aisc_backend_pluginconfig (id, pid, config, created_at, plugin_id, description, name) VALUES
  (6, 'f0eb0000-0000-4000-8000-000000000006', '{}', now(), 6, '', 'lb'),
  (7, 'f0eb0000-0000-4000-8000-000000000007', '{}', now(), 7, '', 'sr'),
  (8, 'f0eb0000-0000-4000-8000-000000000008', '{}', now(), 8, '', 'pf');

-- one engine.aisc_backend_metric per measurement name (the engine's rule, 01-specs.md 3.4)
INSERT INTO engine.aisc_backend_metric (id, pid, name, description, type_spec, created_at)
SELECT 100 + n, ('f0e30000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid, name, '', 'float', now()
  FROM (VALUES
    (1, 'LangBiTe Run Success'),
    (2, 'gender | gpt-4o-mini | en_us | prompt | observational'),
    (3, 'gender | gpt-4o-mini | fr_fr | prompt | observational'),
    (4, 'ageism | gpt-4o-mini | en_us | prompt | observational'),
    (5, 'religion | gpt-4o-mini | en_us | prompt | observational'),
    (6, 'Overall Pass Rate'),
    (7, 'All Tolerances Passed'),
    (8, 'StrongREJECT Harmfulness'),
    (9, 'Jailbreak Resistance'),
    (10, 'Worst-Case Jailbreak Harmfulness'),
    (11, 'Baseline Harmfulness (no jailbreak)'),
    (12, 'Harmfulness | none'),
    (13, 'Harmfulness | aim'),
    (14, 'Harmfulness | pair'),
    (15, 'Harmfulness | base64'),
    (16, 'pass_rate'),
    (17, 'fail_rate'),
    (18, 'refusal_rate'),
    (19, 'mean_latency_ms'),
    (20, 'total_cost'),
    (21, 'n_tests')
  ) AS m(n, name);

-- evaluations of M_V2, in created_at order (their readable numbers, R-V2.1):
--   1 = 71 (08:00) StrongREJECT that produced no scores (all 0.0, "No score produced", R-V2.18)
--   2 = 72 (09:00) LangBiTe + StrongREJECT (scored)          -> "Evaluation 2: LangBiTe, StrongREJECT"
--   3 = 73 (10:00) Promptfoo with only latency, cost, tests
--   4 = 74 (11:00) Promptfoo with all six measurements
--   5 = 75 (12:00) Failed: Promptfoo wrote nothing (R-V2.22)
-- M_V1: 70 (2026-09-12) LangBiTe + StrongREJECT, smaller.
INSERT INTO engine.aisc_backend_evaluation (id, pid, status, project_id, system_id, created_at) VALUES
  (70, 'f1e00000-0000-4000-8000-000000000070', 'Done',   6, 'f1000000-0000-4000-8000-000000000001', '2026-09-12 09:00+00'),
  (71, 'f2e00000-0000-4000-8000-000000000071', 'Done',   6, 'f2000000-0000-4000-8000-000000000002', '2026-09-19 08:00+00'),
  (72, 'f2e00000-0000-4000-8000-000000000072', 'Done',   6, 'f2000000-0000-4000-8000-000000000002', '2026-09-19 09:00+00'),
  (73, 'f2e00000-0000-4000-8000-000000000073', 'Done',   6, 'f2000000-0000-4000-8000-000000000002', '2026-09-19 10:00+00'),
  (74, 'f2e00000-0000-4000-8000-000000000074', 'Done',   6, 'f2000000-0000-4000-8000-000000000002', '2026-09-19 11:00+00'),
  (75, 'f2e00000-0000-4000-8000-000000000075', 'Failed', 6, 'f2000000-0000-4000-8000-000000000002', '2026-09-19 12:00+00');

INSERT INTO engine.aisc_backend_evaluationplugin (id, pid, name, description, evaluation_id, plugin_config_id, error_message, started_at, finished_at, status, created_at) VALUES
  (701, 'f1ea0000-0000-4000-8000-000000000701', 'LangBiteEvaluationPlugin', '', 70, 6, '', now(), now(), 'Done', '2026-09-12 09:00+00'),
  (702, 'f1ea0000-0000-4000-8000-000000000702', 'StrongRejectPlugin', '', 70, 7, '', now(), now(), 'Done', '2026-09-12 09:01+00'),
  (711, 'f2ea0000-0000-4000-8000-000000000711', 'StrongRejectPlugin', '', 71, 7, '', now(), now(), 'Done', '2026-09-19 08:00+00'),
  (721, 'f2ea0000-0000-4000-8000-000000000721', 'LangBiteEvaluationPlugin', '', 72, 6, '', now(), now(), 'Done', '2026-09-19 09:00+00'),
  (722, 'f2ea0000-0000-4000-8000-000000000722', 'StrongRejectPlugin', '', 72, 7, '', now(), now(), 'Done', '2026-09-19 09:01+00'),
  (731, 'f2ea0000-0000-4000-8000-000000000731', 'PromptfooPlugin', '', 73, 8, '', now(), now(), 'Done', '2026-09-19 10:00+00'),
  (741, 'f2ea0000-0000-4000-8000-000000000741', 'PromptfooPlugin', '', 74, 8, '', now(), now(), 'Done', '2026-09-19 11:00+00'),
  (751, 'f2ea0000-0000-4000-8000-000000000751', 'PromptfooPlugin', '', 75, 8, 'promptfoo exited with code 1', now(), now(), 'Failed', '2026-09-19 12:00+00');

INSERT INTO engine.aisc_backend_evaluationinput (id, pid, name, description, created_at, value, component_id, evaluation_plugin_id) VALUES
  (60, 'f0ed0000-0000-4000-8000-000000000060', 'model', '', now(), '{}', 6, 701),
  (61, 'f0ed0000-0000-4000-8000-000000000061', 'model', '', now(), '{}', 6, 702),
  (62, 'f0ed0000-0000-4000-8000-000000000062', 'model', '', now(), '{}', 6, 711),
  (63, 'f0ed0000-0000-4000-8000-000000000063', 'model', '', now(), '{}', 6, 721),
  (64, 'f0ed0000-0000-4000-8000-000000000064', 'model', '', now(), '{}', 6, 722),
  (65, 'f0ed0000-0000-4000-8000-000000000065', 'model', '', now(), '{}', 6, 731),
  (66, 'f0ed0000-0000-4000-8000-000000000066', 'model', '', now(), '{}', 6, 741),
  (67, 'f0ed0000-0000-4000-8000-000000000067', 'model', '', now(), '{}', 6, 751);

-- observation.tool = "{package}::{Class} (v{version})" (D8)
INSERT INTO engine.aisc_backend_observation (id, pid, name, description, observer, tool, evaluation_id, created_at) VALUES
  (7001, 'f1eb0000-0000-4000-8000-000000007001', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiteEvaluationPlugin (v0.1.1)', 70, now()),
  (7002, 'f1eb0000-0000-4000-8000-000000007002', 'sr', '', 'engine', 'aisc-plugin-strongreject::StrongRejectPlugin (v0.1.0)', 70, now()),
  (7101, 'f2eb0000-0000-4000-8000-000000007101', 'sr', '', 'engine', 'aisc-plugin-strongreject::StrongRejectPlugin (v0.1.0)', 71, now()),
  (7201, 'f2eb0000-0000-4000-8000-000000007201', 'lb', '', 'engine', 'aisc-plugin-langbite::LangBiteEvaluationPlugin (v0.1.1)', 72, now()),
  (7202, 'f2eb0000-0000-4000-8000-000000007202', 'sr', '', 'engine', 'aisc-plugin-strongreject::StrongRejectPlugin (v0.1.0)', 72, now()),
  (7301, 'f2eb0000-0000-4000-8000-000000007301', 'pf', '', 'engine', 'aisc-plugin-promptfoo::PromptfooPlugin (v0.1.0)', 73, now()),
  (7401, 'f2eb0000-0000-4000-8000-000000007401', 'pf', '', 'engine', 'aisc-plugin-promptfoo::PromptfooPlugin (v0.1.0)', 74, now());

INSERT INTO engine.aisc_backend_measurement (id, pid, name, description, unit, "time", score, error, uncertainty, metric_id, observation_id, created_at, dimensions, direction) VALUES
  -- M_V1 LangBiTe (two groups)
  (7000, gen_random_uuid(), 'LangBiTe Run Success', 'LangBiTe execution finished', NULL, now(), 1.0, NULL, 0, 101, 7001, now(), NULL, NULL),
  (7003, gen_random_uuid(), 'gender | gpt-4o-mini | en_us | prompt | observational', 'Tolerance Evaluation: Failed | Tolerance: 0.8 | Passed: 7/10 | Failed: 3/10', NULL, now(), 0.7, NULL, 0, 102, 7001, now(), NULL, NULL),
  (7004, gen_random_uuid(), 'ageism | gpt-4o-mini | en_us | prompt | observational', 'Tolerance Evaluation: Failed | Tolerance: 0.8 | Passed: 2/4 | Failed: 2/4', NULL, now(), 0.5, NULL, 0, 104, 7001, now(), NULL, NULL),
  (7005, gen_random_uuid(), 'Overall Pass Rate', '', NULL, now(), 0.6, NULL, 0, 106, 7001, now(), NULL, NULL),
  (7006, gen_random_uuid(), 'All Tolerances Passed', '0/2 tolerance checks passed', NULL, now(), 0.0, NULL, 0, 107, 7001, now(), NULL, NULL),
  -- M_V1 StrongREJECT (two jailbreaks)
  (7010, gen_random_uuid(), 'StrongREJECT Harmfulness', 'Mean harmfulness across all jailbreaks (0-1, lower is safer).', NULL, now(), 0.3, NULL, 0, 108, 7002, now(), NULL, NULL),
  (7011, gen_random_uuid(), 'Jailbreak Resistance', '1 - harmfulness. Share the model held the line (higher is safer).', NULL, now(), 0.7, NULL, 0, 109, 7002, now(), NULL, NULL),
  (7012, gen_random_uuid(), 'Worst-Case Jailbreak Harmfulness', 'Most effective jailbreak: aim (lower is safer).', NULL, now(), 0.5, NULL, 0, 110, 7002, now(), NULL, NULL),
  (7013, gen_random_uuid(), 'Baseline Harmfulness (no jailbreak)', 'Harmfulness with no jailbreak applied — the model''s plain refusal behaviour.', NULL, now(), 0.1, NULL, 0, 111, 7002, now(), NULL, NULL),
  (7014, gen_random_uuid(), 'Harmfulness | none', 'Mean StrongREJECT score over 10 prompts (lower is safer).', NULL, now(), 0.1, NULL, 0, 112, 7002, now(), NULL, NULL),
  (7015, gen_random_uuid(), 'Harmfulness | aim', 'Mean StrongREJECT score over 10 prompts (lower is safer).', NULL, now(), 0.5, NULL, 0, 113, 7002, now(), NULL, NULL),
  -- M_V2, evaluation 1: StrongREJECT failed, every summary score 0.0 (R-V2.18)
  (7100, gen_random_uuid(), 'StrongREJECT Harmfulness', 'No score produced', NULL, now(), 0.0, NULL, 0, 108, 7101, now(), NULL, NULL),
  (7101, gen_random_uuid(), 'Jailbreak Resistance', 'Not measured', NULL, now(), 0.0, NULL, 0, 109, 7101, now(), NULL, NULL),
  (7102, gen_random_uuid(), 'Worst-Case Jailbreak Harmfulness', 'No attacked jailbreaks', NULL, now(), 0.0, NULL, 0, 110, 7101, now(), NULL, NULL),
  (7103, gen_random_uuid(), 'Baseline Harmfulness (no jailbreak)', 'No ''none'' baseline run', NULL, now(), 0.0, NULL, 0, 111, 7101, now(), NULL, NULL),
  -- M_V2, evaluation 2: LangBiTe, four groups (one "Not evaluated") and the three summary measurements
  (7200, gen_random_uuid(), 'LangBiTe Run Success', 'LangBiTe execution finished', NULL, now(), 1.0, NULL, 0, 101, 7201, now(), NULL, NULL),
  (7201, gen_random_uuid(), 'gender | gpt-4o-mini | en_us | prompt | observational', 'Tolerance Evaluation: Passed | Tolerance: 0.8 | Passed: 9/10 | Failed: 1/10', NULL, now(), 0.9, NULL, 0, 102, 7201, now(), NULL, NULL),
  (7202, gen_random_uuid(), 'gender | gpt-4o-mini | fr_fr | prompt | observational', 'Tolerance Evaluation: Failed | Tolerance: 0.8 | Passed: 6/10 | Failed: 4/10', NULL, now(), 0.6, NULL, 0, 103, 7201, now(), NULL, NULL),
  (7203, gen_random_uuid(), 'ageism | gpt-4o-mini | en_us | prompt | observational', 'Tolerance Evaluation: Failed | Tolerance: 0.8 | Passed: 3/4 | Failed: 1/4', NULL, now(), 0.75, NULL, 0, 104, 7201, now(), NULL, NULL),
  (7204, gen_random_uuid(), 'religion | gpt-4o-mini | en_us | prompt | observational', 'Tolerance Evaluation: Not evaluated | Tolerance:  | Passed: 1/2 | Failed: 1/2', NULL, now(), 0.5, NULL, 0, 105, 7201, now(), NULL, NULL),
  (7205, gen_random_uuid(), 'Overall Pass Rate', '', NULL, now(), 0.6875, NULL, 0, 106, 7201, now(), NULL, NULL),
  (7206, gen_random_uuid(), 'All Tolerances Passed', '1/4 tolerance checks passed', NULL, now(), 0.0, NULL, 0, 107, 7201, now(), NULL, NULL),
  -- M_V2, evaluation 2: StrongREJECT, four jailbreaks incl. none; mean 0.2, worst pair 0.45
  (7210, gen_random_uuid(), 'StrongREJECT Harmfulness', 'Mean harmfulness across all jailbreaks (0-1, lower is safer).', NULL, now(), 0.2, NULL, 0, 108, 7202, now(), NULL, NULL),
  (7211, gen_random_uuid(), 'Jailbreak Resistance', '1 - harmfulness. Share the model held the line (higher is safer).', NULL, now(), 0.8, NULL, 0, 109, 7202, now(), NULL, NULL),
  (7212, gen_random_uuid(), 'Worst-Case Jailbreak Harmfulness', 'Most effective jailbreak: pair (lower is safer).', NULL, now(), 0.45, NULL, 0, 110, 7202, now(), NULL, NULL),
  (7213, gen_random_uuid(), 'Baseline Harmfulness (no jailbreak)', 'Harmfulness with no jailbreak applied — the model''s plain refusal behaviour.', NULL, now(), 0.05, NULL, 0, 111, 7202, now(), NULL, NULL),
  (7214, gen_random_uuid(), 'Harmfulness | pair', 'Mean StrongREJECT score over 20 prompts (lower is safer).', NULL, now(), 0.45, NULL, 0, 114, 7202, now(), NULL, NULL),
  (7215, gen_random_uuid(), 'Harmfulness | none', 'Mean StrongREJECT score over 20 prompts (lower is safer).', NULL, now(), 0.05, NULL, 0, 112, 7202, now(), NULL, NULL),
  (7216, gen_random_uuid(), 'Harmfulness | aim', 'Mean StrongREJECT score over 20 prompts (lower is safer).', NULL, now(), 0.1, NULL, 0, 113, 7202, now(), NULL, NULL),
  (7217, gen_random_uuid(), 'Harmfulness | base64', 'Mean StrongREJECT score over 20 prompts (lower is safer).', NULL, now(), 0.2, NULL, 0, 115, 7202, now(), NULL, NULL),
  -- M_V2, evaluation 3: Promptfoo with only latency, cost and tests (the rates are absent)
  (7300, gen_random_uuid(), 'mean_latency_ms', 'Average model response time across all tests.', 'ms (lower is better)', now(), 640.0, NULL, 0, 119, 7301, now(), NULL, NULL),
  (7301, gen_random_uuid(), 'total_cost', 'Total API cost across all tests.', 'USD (lower is better)', now(), 0.0, NULL, 0, 120, 7301, now(), NULL, NULL),
  (7302, gen_random_uuid(), 'n_tests', 'Number of test cases run.', 'count', now(), 12, NULL, 0, 121, 7301, now(), NULL, NULL),
  -- M_V2, evaluation 4: Promptfoo, all six
  (7400, gen_random_uuid(), 'pass_rate', 'Share of tests that passed all of their assertions.', 'rate (higher is better)', now(), 0.85, NULL, 0, 116, 7401, now(), NULL, NULL),
  (7401, gen_random_uuid(), 'fail_rate', 'Share of tests that failed at least one assertion.', 'rate (lower is better)', now(), 0.15, NULL, 0, 117, 7401, now(), NULL, NULL),
  (7402, gen_random_uuid(), 'refusal_rate', 'Share of tests where the model refused to answer.', 'rate', now(), 0.1, NULL, 0, 118, 7401, now(), NULL, NULL),
  (7403, gen_random_uuid(), 'mean_latency_ms', 'Average model response time across all tests.', 'ms (lower is better)', now(), 812.4, NULL, 0, 119, 7401, now(), NULL, NULL),
  (7404, gen_random_uuid(), 'total_cost', 'Total API cost across all tests.', 'USD (lower is better)', now(), 0.01234, NULL, 0, 120, 7401, now(), NULL, NULL),
  (7405, gen_random_uuid(), 'n_tests', 'Number of test cases run.', 'count', now(), 40, NULL, 0, 121, 7401, now(), NULL, NULL);

-- artifacts named like the real ones; their content must never reach a report (R-V2.9)
INSERT INTO engine.aisc_backend_artifact (id, pid, name, description, data, storage_container, evaluation_plugin_id, created_at, file_size) VALUES
  (70, gen_random_uuid(), 'strongreject_per_prompt.csv', '', 'HARMFULPROMPTCONTENT', 'bucket', 722, now(), 4096),
  (71, gen_random_uuid(), 'promptfoo_results.json', '', 'HARMFULPROMPTCONTENT', 'bucket', 741, now(), 8192),
  (72, gen_random_uuid(), 'plugin_execution.log', '', 'HARMFULPROMPTCONTENT', 'bucket', 741, now(), 512);

SET session_replication_role = origin;
