# Stage 6: implementation report

Inputs: RULES.md, 05-coding-plan.md (amendments B1 to B3 binding). All test runs used throwaway
postgres:14-alpine containers (names `aisc-t-*`, random ports, removed on exit). Nothing was pushed;
the live stack and its databases were not touched.

## Progress (one line per checkpoint, amendment B3)

- 0 preflight: every repo on feat/unified-modules, plugin-manager clean. Baselines in the stage-6 scratchpad (`baseline/`): BE-sqlite 36 failures + 4 errors; Q-unit red only on the new test files; CAT 6 failed / 55 passed; WEB 10 failed / 30 passed; CTL 11 failed / 94 passed / 7 skipped; DASH 36 failed / 74 passed.
- A (engine undo, webapp undo): backend `4f8c9e0` "One AI system per project again, as at Sean's merge"; webapp `3a6856e` "The AI system settings are Sean's again; no version banner". BE-sqlite 6 failures + 5 errors, BE-pg 10 failures + 5 errors: F5 set (7) + WP9 tests (group B) + 1 new red, `test_s1_aisystem_does_not_ask_the_platform` (see Needs the user, N1). WEB: only the 7 WP8 dialog tests red (group I), tsc 0. Guard G1..G5 PASS; `test_guard_frozen.py -k "s0_ or s1_1 or s1_4 or s1_6 or g2 or g3 or g4 or s9_1"` 14 passed.
- B (test stamp, WP9): backend `b73921b` "A test records the AI card version that was the latest when it started". All WP9 tests green except `test_s9_3_none_when_core_system_is_absent` on Postgres (N2, a sync cursor call inside an async test). BE-sqlite 3 failures + 5 errors, BE-pg 3 failures + 6 errors (F5 set + N1 + N2). With `DJANGO_ALLOW_ASYNC_UNSAFE=true` both N1 and N2 pass, which shows the code under test is right. Guard PASS; `test_guard_frozen.py -k s9_4` 1 passed.
- C (platform card versions, WP2; fresh-DB order fix): top level `b077617` "Card versions are rows of core.system, numbered per project", `9ff3672` "The engine no longer needs the platform's address" (only the PLATFORM_URL hunk; the prefill hunks stay unstaged); qualification `f5de508` "The one-card-per-version migration also runs where the platform already moved on" (B1 fallback, see N3). PLAT 93 passed, 6 failed (all `test_dashboard_bridge.py`, group J). TOP `-k "wp2 or s6a_compose_config"` 2 passed. Guard PASS.
- D (qualification: save = next version, WP3): qualification `840e71e` "Saving the AI card makes the next card version, and only the latest changes". Q-unit 397 passed, 18 failed (only `engineComponents` and `systemVersionOntologyRoute`, groups F and G), tsc 0. Q-db 12 of 13 green; `S3.3 the migration file refuses cards pointing at versions missing from core.system` red because of its own fixture (N4); the same script with the project key also dropped raises the expected message. Four freeze-era tests rewritten per F8 (cases about drafts, freeze and CardExistsError deleted). The `fill` route is a read-only GET of the filler's run state, so it got no 403 (nothing to refuse). Guard PASS.
- E (migration orders, WP4): no commit needed. `guard-frozen.sh --orders` S4.1 to S4.4 PASS; `test_guard_frozen.py -k s4_` 4 passed.
- F (card agent deployed, components by AIRO, WP6): top level `1a6886d` "The card agent runs beside qualification, and qualification can reach it"; qualification `d8ee5d2` "A card links the engine's components through AIRO, and shows drift", `8103837` "The AIRO graph carries the engine components a card links". TOP `-k s6a` 3 passed. Q-unit 409 passed, 6 failed (only `systemVersionOntologyRoute`, group G), tsc 0. Q-py ontology 182 passed, 3 failed (N5: three "every schema property is used" tests that 05 F4 said to report, not edit). Q-py agents 99 passed, 1 failed (`test_controls.py::...test_each_flag_is_one_the_builder_accepts`: `rdflib` is not in the agents requirements, independent of this run); `test_a_failed_run_says_so_rather_than_vanishing` green. Guard PASS. Two deviations named: the compose build uses a new `services/agents/Dockerfile.stack` (see T1), and `toExport` adds `engineComponents` only when the card links some (so the existing exporter key-list test and S6.1 both hold).
- G (control objectives from the latest version's card, WP7): qualification `b03e69c` "Control objectives can read the AI card of one version"; control-objectives `c72cfdf` "An assessment is of the latest saved AI card version, read from qualification"; top level `b473b98` "Control objectives knows where qualification and the platform are". CO 241 passed, 0 failed (the new version and migration files all green; `test_projects.py`, `test_repository.py` and `test_project_access.py::test_an_editor_gets_past_the_door` rewritten per F8, 4 upload cases deleted). Q-unit 415 passed, 0 failed. httpx moved to the runtime dependencies, `uv lock --offline` (2 lines of uv.lock). Guard PASS.
- H (answers carry the version, WP10; dashboard grant, WP11): controls `9611c00` "Each answer carries the AI card version it was answered under", `7b3b3c6` "The dashboard may read this project's controls, and only read them". CTL (only the F1-safe paths) 112 passed, 0 failed, 0 skipped. Guard PASS.
- I (one-click install, WP8): catalogue `762e1b2` "Tests and controls install with the same button, into the project the catalogue came from"; webapp `a936401` "The install dialog opens on the catalogue's project and says when a test is already there". CAT 61 passed, 0 failed (ToolDetailModal.test label fix per 05 I2); catalogue tsc still 81 errors, all in test files, none new. WEB 40 passed, 0 failed, tsc 0. Guard PASS (G4 webapp PASS).
- J (dashboard, WP11): top level `ac8556d` "A project's dashboard is made with the project and removed before its database" (template 0002, bridge calls, compose), `d138aab` "The dashboard reaches a project's database from the host network"; results-dashboard `74564d7` "One dashboard per project, readable only by its members, with the version on every row" (only this change's hunks of superset_config.py; W4's hunks and files stay unstaged). PLAT 99 passed, 0 failed. DASH 110 passed, 0 failed (run on a bare throwaway container: the DB test applies the init files itself). `scripts/pipeline_chain/test_dashboard_queries.py` 3 red because of the test helper (N6); with the one-flag fix applied transiently they pass (3 passed), then reverted. Guard PASS.
- K (pipeline chain, WP12): top level `77b4247`, qualification `25fbe0b`, backend `1c71318`, control-objectives `975ace4`, controls `05a6912` ("The pipeline chain step of <module>"). As committed, `scripts/test-pipeline-chain.sh` stops at step 4 (N7: the engine step also loads the F5 ImportError module) and would stop at step 8 (N6). With both test-infrastructure one-liners applied transiently: CHAIN PASS (steps 1 to 8), and all five `--break` runs print "BREAK <link> OK" at the consuming step (2, 3, 8, 8, 3); the patches were then reverted. Checked first that vitest's `-t chain_stepN` never runs the hooks of the F1 files (a scratch suite whose beforeAll/afterAll write marker files: no marker), so steps 5 and 7 cannot reach the live `postgres`.
- Integration check: done (results below). Guard PASS, guard --orders PASS, no `aisc-t-*` container left, plugin-manager clean.

## Status per group

| group | status | commits (all local, on feat/unified-modules, none pushed) |
|---|---|---|
| A engine and webapp undo | green except N1 | backend `4f8c9e0`; webapp `3a6856e` |
| B test stamp | green except N2 | backend `b73921b` |
| C platform card versions | green | top `b077617`, `9ff3672`; qualification `f5de508` (B1 fallback, N3) |
| D save = next version | green except N4 | qualification `840e71e` |
| E migration orders | green | none needed |
| F card agent, components by AIRO | green except N5 | top `1a6886d`; qualification `d8ee5d2`, `8103837` |
| G control objectives from the latest card | green | qualification `b03e69c`; control-objectives `c72cfdf`; top `b473b98` |
| H answer stamps, dashboard grant | green | controls `9611c00`, `7b3b3c6` |
| I one-click install | green | catalogue `762e1b2`; webapp `a936401` |
| J dashboard | green except N6 | top `ac8556d`, `d138aab`; results-dashboard `74564d7` |
| K pipeline chain | implemented; red as committed only because of N6 and N7 | top `77b4247`; qualification `25fbe0b`; backend `1c71318`; control-objectives `975ace4`; controls `05a6912` |
| L other sessions' work | skipped (B2) | none; their files untouched and unstaged |

## Final test counts (integration check, each DB suite on its own throwaway container)

| suite | passed | failed / errors | skipped | remaining failures, and 05's expected list |
|---|---|---|---|---|
| BE-sqlite | 114 | 3 failures, 5 errors | 13 | F5 (7, expected: 3 Keycloak, 3 Sean's project_config_router, 1 test_integration ImportError) + N1 `test_s1_aisystem_does_not_ask_the_platform` (NOT on 05's list) |
| BE-pg | 117 | 3 failures, 6 errors | 9 | F5 (7, expected) + N1 + N2 `test_s9_3_none_when_core_system_is_absent` (both NOT on 05's list) |
| PLAT | 99 | 0 | 2 (chain) | none |
| Q-unit | 415, tsc 0 | 0 | 14 (DB file, chain) | none |
| Q-db | 12 | 1 | 0 | N4 (NOT on 05's list) |
| Q-py ontology | 182 | 3 | 0 | N5 (05 F4 said to report these) |
| Q-py prefill | 73 | 0 | 0 | none (other session's untracked files, run as they are) |
| Q-py agents | 99 | 1 | 0 | `test_controls.py::...test_each_flag_is_one_the_builder_accepts`: `rdflib` missing from the agents requirements; independent of this run (NOT on 05's list) |
| CO | 241 | 0 | 1 (chain) | none |
| CTL (F1-safe paths only) | 112 | 0 | 0 | none |
| CAT | 61 | 0 | 0 | none; `tsc --noEmit` still 81 errors, all in test files (expected) |
| catalogue backend | 101 | 0 | 0 | none |
| WEB | 40, tsc 0 | 0 | 0 | none |
| DASH (`--ignore` test_sso_login) | 110 | 0 | 0 | none (on a bare container: the DB test applies init itself) |
| TOP (scripts/tests + scripts/pipeline_chain) | 28 | 6 | 0 | `test_dashboard_queries.py` x3 (N6); `test_pipeline_chain.py` full chain, `--break engine_stamp`, `--break controls_stamp` (N7, then N6). NOT on 05's list |
| GUARD | G1..G5 PASS; --orders S4.1..S4.4 PASS | | | |

Proof that N6 and N7 are the only obstacles for the chain: with both one-line fixes applied in the working tree and then reverted, `scripts/test-pipeline-chain.sh` printed CHAIN PASS and every `--break <link>` printed "BREAK <link> OK" at the consuming step.

## Needs the user

- **N1 (backend, Sean's frozen route).** `test_one_system_per_project.py::AISystemRouteIsE34fca3::test_s1_aisystem_does_not_ask_the_platform` errors: `GET /projects/{pid}/aisystem` on a project that has no AISystem yet goes through e34fca3's `get_or_create_aisystem`, which returns an unprefetched system, and the schema's `get_components` then queries in async context: `SynchronousOnlyOperation ... response.components`. The bug is in Sean's `routers/project.py` (frozen, byte-identical to e34fca3); the sibling test that creates a component first passes. It passes with `DJANGO_ALLOW_ASYNC_UNSAFE=true`. Options: accept it as a known e34fca3 bug; or allow the test fixture to create a component first (test change); or allow a fix in Sean's route. Not decided here.
- **N2 (backend, test bug).** `test_evaluation_system_stamp.py::LatestSystemPid::test_s9_3_none_when_core_system_is_absent` calls `connection.cursor()` directly inside an `async def` test, which Django refuses (`SynchronousOnlyOperation` at line 122 of the test). The code under test is right: the test passes with `DJANGO_ALLOW_ASYNC_UNSAFE=true`. Fix: wrap that probe in `sync_to_async`, or make the test sync like its siblings. Needs your yes to edit the test.
- **N3 (B1 fallback, qualification migration edited).** B1's first try (0003 keeps `core.ai_system_version`) contradicts the spec'd platform tests `test_s2_6_on_a_fresh_database_0003_succeeds_and_core_system_is_empty` and `test_s2_7_on_the_live_shape_every_pid_is_kept_and_mcas_is_number_1`, which assert `to_regclass('core.ai_system')` and `to_regclass('core.ai_system_version')` are both NULL after 0003 (and the frozen function gone). So 0003 drops them, and the applied qualification migration `20260923180000_one_ai_card_per_system_version` was edited as 05 C5 says: its FK statement runs only when `core.ai_system_version` exists (commit `f5de508`). On the live DB this file's checksum now differs from what `_prisma_migrations` recorded; Prisma 5.22 `migrate deploy` accepts that (checked by stage 5), but `prisma migrate dev`/`status` will report it as modified. Your call whether to keep this or change the two tests instead.
- **N4 (qualification, test fixture).** `test/db/cardVersions.db.test.ts::S3.3 the migration file refuses cards pointing at versions missing from core.system` inserts a card with a random `project_id` after dropping only the system FK, so `Qualification_project_id_fkey` fails before the migration runs: `ERROR: insert or update on table "qualification" violates foreign key constraint "Qualification_project_id_fkey"`. Running the same script with that FK also dropped gives exactly the expected `cards point at system versions missing from core.system: <pid>`. Fix: drop `"Qualification_project_id_fkey"` in the fixture too (or insert the project). Needs your yes to edit the test.
- **N5 (ontology, 05 F4 said stop and report).** After adding `AIModel`, `Data` and the four `hasComponent` sub-properties, three "every schema property is used" tests fail because their fixtures link no engine components: `test_build.py::test_a_full_qualification_exercises_all_nineteen_properties`, `test_example_mcas.py::test_it_exercises_all_nineteen_properties`, `test_roundtrip.py::test_the_rebuilt_graph_keeps_every_airo_relation` (missing: hasModel, hasTrainingData, hasTestingData, hasValidationData). `test_mapping.py::test_every_property_in_the_schema_has_a_form_source` was made green by implementation (four `FORM_MAPPING` entries whose source is the card page's component links, `card:engineComponents`). Options: give those fixtures `engineComponents` (not the MCAS example file: `test_s6_1_without_engine_components_the_graph_is_unchanged` needs it without), or exclude the sub-properties from those three checks.
- **N6 (test helper).** `scripts/pipeline_chain/throwaway.py::Throwaway.psql` runs psql without `-tA`, so `rows()` parses the "(1 row)" footer as JSON: `json.decoder.JSONDecodeError: Expecting value`. All three `test_dashboard_queries.py` tests, and chain step 8, fail on it. Fix: add `"-tA"` after `"-q"` in that call (verified: 3 passed, and the full chain passes).
- **N7 (chain driver).** Step 4 runs `manage.py test aisc_backend --tag chain -k chain_step4`; the F5 ImportError module `tests.integration.test_integration` is a `_FailedTest` that no tag or `-k` filters out, so step 4 always ends `FAILED (errors=1)` although the chain test itself passes. Fix: `manage.py test aisc_backend.tests.test_chain --tag chain -k chain_step$n` in `scripts/test-pipeline-chain.sh` (verified with N6: CHAIN PASS and all five breaks OK).
- **N8 (live stack, when you restart).** `init/project-databases.sql` now ends with `ALTER TABLE core.system OWNER TO platform_rw` (A2); platform 0003 refuses to run until that line has run as the superuser.
- **Group L (B2).** The prefill work in apps/qualification and the review-page work in apps/results-dashboard (and their compose / verify.sh hunks) are still uncommitted, as found. `scripts/verify-rbac.sh`'s `/systems` call (WP15) and the top-level submodule pointers were not touched.
- **Manual checks of 04 (not runnable here):** UI of the card pages (read-only banner, ComponentsPanel Link/Unlink, drift banner, Versions list), CO start button and read-only page, submission "answered under vN", the install dialog in a browser, the dashboard in a live Superset (the `SupersetStore` and `ProjectBridgeApi` code is runtime-only and untested), the card agent with an LLM key.

## Taste calls and deviations (named)

- T1: the stack builds the card agent from `apps/qualification/services/agents` (the test pins that context) with a new `Dockerfile.stack` and the ontology prompts as a named build context; the existing `Dockerfile` stays for the app's own compose. Checked with a scratch `docker buildx build` (image removed afterwards).
- T2: `qualification-agents` gets both `LLM_SERVICE_URL` and `BAF_LLM_BASE_URL` (05 F1).
- T3: the platform reaches the dashboard at `http://host.docker.internal:${DASHBOARD_PORT:-8188}` with `extra_hosts: host-gateway`: the dashboard runs with `network_mode: host` on port 8188, not 8088. The dashboard gets `AISC_PROJECT_DB_HOSTPORT: localhost:5432` for the per-project connection (default `postgres:5432`, which the tests pin); `DASHBOARD_BRIDGE_TOKEN` is read from the environment on both sides and never written to a file.
- T4: `toExport` adds `engineComponents` only when a card links at least one, so the existing exporter key-list test and S6.1 both hold.
- T5: provision_all registers every project with the bridge on its first run after a start, and retries failed registrations every RETRY_SECONDS.
- T6: the qualification `fill` route is a read-only GET of the filler's state, so it got no 403.
- T7: migration 0023 flushes Django's deferred SQL before renaming (the FK and index of `AIComponent.system` are otherwise made after the rename), and uses a plain cursor for SQL containing `%`.

## Runbook for the live stack (NOT executed)

Order matters: 0003 needs the ownership line; the qualification WP3 migration needs 0003's `number`; 0023 re-points the engine's key at `core.system`.

1. Back up first: `docker exec postgres pg_dump -U "$POSTGRES_USER" -Fc platform > ~/aisc-backup-platform-$(date +%F).dump`, and each `project_<hex>` database likewise.
2. Stop the writers only (not postgres): `docker compose -p aisc -f docker-compose.development.yml stop platform aisc-backend aisc-eval-worker qualification-web control-objectives controls-web dashboard`.
3. Ownership (A2): `docker exec -i postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 < init/project-databases.sql` (or start `postgres-setup`, which runs it).
4. Rebuild the changed images: `docker compose -p aisc -f docker-compose.development.yml build platform aisc-backend qualification-migrate qualification-web qualification-agents control-objectives controls-web aisc-webapp catalogue-frontend dashboard`.
5. Platform 0003: `docker compose -p aisc ... up -d platform` (it migrates core at the first query, then applies template 0002 to every project database and registers each project with the dashboard bridge). Check: `SELECT name FROM core.schema_migration` lists `0003_card_versions_in_core_system.sql`; MCAS is `number` 1.
6. Qualification: `docker compose -p aisc ... up qualification-migrate` (applies `20260923210000_card_versions_point_at_core_system`; the edited `20260923180000` is already recorded, see N3).
7. Engine: `docker compose -p aisc ... run --rm aisc-backend python manage.py migrate` (applies 0023). Check with `scripts/guard-frozen.sh` logic: engine schema equals e34fca3.
8. Control objectives: `docker compose -p aisc ... run --rm control-objectives alembic upgrade head` (4d2a9c1e7b60; it refuses if an assessment has no card version or two share one: fix by hand, assessments are never deleted).
9. Controls: starting `controls-web` migrates every project database on open (`20260923210000`, `20260923210100`).
10. Set `DASHBOARD_BRIDGE_TOKEN` in the env file (both platform and dashboard read it), then `up -d` the rest, including the new `qualification-agents`.
11. Verify: save a card (v2 appears in `/projects/{p}/system-versions`), start an evaluation (its `system_id` is the latest version), answer a control (stamp shown), open the project dashboard as a member and as a non-member.
