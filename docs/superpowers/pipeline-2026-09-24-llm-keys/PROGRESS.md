# Progress

| stage | output | status |
|---|---|---|
| 1 specs | 01-specs.md | done |
| 2 tests | 02-tests.md + test files | done |
| 3 plan | 03-coding-plan.md | pending |
| 4 code | commits | pending |
| 5 verify until green | 05-report.md | pending |

## Stage 1 notes (specs)

- Wrote 01-specs.md: sections 0 (findings), 1 data model (project-template 0005_llm.sql, schema `llm`,
  tables `provider` and `system_choice`), 2 platform API (admin-only routes under /projects/{slug}/llm,
  live model listers per provider, internal resolve route with X-AISC-Service-Token), 3 shared
  `baf_llm.py` (identical copy in A and B plus parity test), 4 page `homepage/llm.html`, 5 security,
  6 compose/env/Caddy wiring (not applied), 7 decisions D1-D11 and risks R1-R5, 8 test map.
- Key decisions: system ids card_agent / risk_mapper; base URL on the provider row; fail closed once a
  project is known; models route answers 200 with `error`; model need not be in the live list; A gets the
  pid as `?project=` from qualification-web (small TS change in FillerClient and createFromForm).
- Open for later stages: stage 4 edits homepage/project.html on top of the user's uncommitted edit and must
  not commit it; scripts/secrets.sh must only be tested on a scratch copy (it rewrites env.runtime).
- No product code or tests written. Nothing run against the live stack.

## Stage 2 notes (tests)

- Wrote failing tests for every ID S1.1 to S6.7 (map in 02-tests.md section 2); no product code.
- Files: platform/tests/{llm_support.py, test_llm_catalogue.py, test_llm_store.py, test_api_llm.py};
  scripts/tests/test_llm_keys.py and 4 tests appended to scripts/tests/test_compose.py;
  apps/qualification services/agents/tests/{fake_http.py, test_baf_llm.py, test_project_llm.py} and S3.8
  blocks appended to test/unit/FillerTrigger.test.ts and test/unit/cardVersionsInCoreSystem.test.ts;
  apps/control-objectives tests/{fake_http.py, test_baf_llm.py, test_project_llm.py}.
- Commits (local, not pushed): apps/qualification 226618c, apps/control-objectives 97ad187, top-level: the
  commit that adds this note (platform tests, scripts tests, 02-tests.md, PROGRESS.md). Submodule pointers
  NOT bumped at top level; stage 4 records them with the code.
- Red counts (new tests): platform 147 (100 failed + 47 errors), A 45, B 46, qualification-web 5, top-level 21.
  One guard per suite is already green. Every pre-existing test still passes (platform 110, A 100, B 250,
  vitest 19, compose 4). Throwaway container aisc-t-llmkeys-1be7c433 removed.
- Pinned interfaces T1 to T11 and gaps G1 to G9 in 02-tests.md sections 5 and 6. Most important for stage 4:
  `llm_catalogue.MODELS_URL` dict + `list_models(provider, api_key=, base_url=)`; env read per request;
  A's service must call `fill_one(qid)` without a `project` keyword when none is given (existing fakes);
  `Projects(mapper_for=...)`; ValueError or ResolveError from mapper_for -> 502.
- Run A's suite from a scratch cwd with `--with rdflib` (root-owned application.log in the agents dir,
  pre-existing). The throwaway recipe also applies init/inspector-role.sql and init/report-roles.sql.
- The host runs a real ollama on :11434; the tests never reach it (env cleared, closed ports).
- homepage/project.html untouched (user's uncommitted edit); S4.2 test is working-tree only.
