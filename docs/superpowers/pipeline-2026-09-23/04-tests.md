# Stage 4: tests first (TDD)

Inputs: RULES.md and 03-specs.md (with amendments A1, A2). No implementation, migration or product
change was written. Every rule of the required packages WP0 to WP13 has at least one test, except the
ones listed under "Rules not turned into automated tests". Tests name their rule (`s2_4`, `S3.3`,
`# S9.2`). Every DB test ran on a throwaway `postgres:14-alpine` container named `aisc-t-*` on a
kernel-picked port, removed afterwards; none remains. The live DB was never a target.

## Status summary

| repo | new tests | failing as expected | already passing | commit (local, feat/unified-modules, not pushed) |
|---|---|---|---|---|
| aisc-install (scripts/: guard, WP0, WP4, WP6a, WP12) | 33 | 19 | 14 | `aa0c7b6` |
| aisc-install (platform/: WP2, WP11 platform side) | 36 | 34 | 2 | `aa9554e` |
| apps/backend (WP1, WP9) | 29 (sqlite) / 25 (Postgres) | all but 3 | 3 | `2e718cd` |
| apps/qualification (WP3, WP5, WP6, WP7 route) | 36 vitest + 9 ontology + 4 prefill + DB file | 36 + 9 + DB schema checks | WP5 S5.1 to S5.4, S3.4, one S3.5 case, 2 DB tests | `4440c4e` |
| apps/control-objectives (WP7) | 25 | 24 | 1 (S7.3) | `4e33a0e` |
| apps/controls (WP10, S8.3, WP11 grants) | 17 | 16 | 1 (S8.3) | `b4d9f01` |
| apps/catalogue (WP8) | 9 | 6 | 3 | `8496538` |
| apps/webapp (WP8, WP13) | 11 | 10 | 1 | `363757e` |
| apps/results-dashboard (WP11) | 36 | 36 | 0 | `f8b84b2` |

All failures were checked to be for the missing feature (missing migration, route, module, column or
revert), not a syntax, import or fixture error. Behaviour DB tests in qualification, dashboard and
the chain fail at fixture setup on `core.system.number`, which is the missing WP2 0003: that is the
intended dependency, not a fixture bug. Other people's uncommitted files (apps/qualification,
apps/results-dashboard, top-level docker-compose.development.yml and scripts/verify.sh) were left
unstaged and unmodified.

## Commands per repo (throwaway DB only)

Common throwaway DB (used by every DB suite; each suite below either does this itself or expects it):

```
NAME=aisc-t-$(openssl rand -hex 4); PW=$(openssl rand -hex 12)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
trap "docker rm -f $NAME" EXIT
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user \
  -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine
docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < init/platform-db.sql
docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < init/project-databases.sql
[ "$PORT" != 5432 ] || exit 1
```

The host has no psql or pg_dump; every helper runs them with `docker exec` inside the throwaway
container and refuses port 5432 or a container not named `aisc-t-*`.

| repo | command |
|---|---|
| aisc-install scripts/ (guard, orders, compose, chain) | from the repo root: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests scripts/pipeline_chain` (makes its own containers, about 4 min). Guard alone: `scripts/guard-frozen.sh [--reference-only] [--orders] [--only G3,G4]`. Chain: `scripts/test-pipeline-chain.sh [--break <link>]` |
| platform | from `platform/`: `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` (`PLATFORM_TEST_SUPERUSER_URL` is new; the migration tests skip without it) |
| apps/backend, sqlite | `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src DB_ENGINE=django.db.backends.sqlite3 DB_NAME=$SCRATCH/t.db .venv/bin/python manage.py test aisc_backend` |
| apps/backend, Postgres | `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=aisc-postgres-user DB_PASSWORD=$PW DB_HOST=127.0.0.1 DB_PORT=$PORT .venv/bin/python manage.py test --noinput aisc_backend` (superuser, because Django creates `test_platform`) |
| apps/qualification, unit | `npx vitest run && npx tsc --noEmit` (the DB file skips itself) |
| apps/qualification, DB | `test/db/throwaway-db.sh` (starts and removes its own container, applies init, platform migrations, `prisma migrate deploy`, runs `vitest run test/db`) |
| apps/qualification, Python | from apps/qualification: `docker run --rm -v $PWD:/w -e PYTHONDONTWRITEBYTECODE=1 -e PREFILL_FIELDS_PATH=/w/src/data/prefillFields.json -w /w/services/<ontology\|prefill> python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"` |
| apps/control-objectives | `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q` |
| apps/controls | `CONTROLS_TEST_PG_CONTAINER=$NAME PROJECT_DATABASE_URL='postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls&connection_limit=2' npx vitest run test/unit test/integration/answer-stamps.test.ts test/integration/dashboard-grants.test.ts test/integration/install-once-throwaway.test.ts` (ONLY these files; see hazard below) |
| apps/catalogue/frontend | `npx vitest run` (no DB) |
| apps/webapp | `npx vitest run` and `npx tsc -b --noEmit` (no DB) |
| apps/results-dashboard | `AISC_DASHBOARD_TEST_PG_CONTAINER=$NAME PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py` (DB tests skip without the variable; the fixture seeds the container itself) |

## Findings for stage 5 (read before implementing)

1. **Live-DB hazard in controls.** The pre-existing controls integration tests (install.test.ts,
   submission-lifecycle.test.ts, project-scope.test.ts, action-access.test.ts,
   project-database.test.ts) run `docker exec postgres psql ...`, i.e. CREATE/DROP DATABASE in the
   LIVE container, whenever `PROJECT_DATABASE_URL` is set. 03's `npx vitest run` command would
   therefore write to the live server. They were not run. Run only the files above, or move those
   tests onto `test/integration/throwawayDb.ts` first.
2. **Spec bug in WP11 SQL.** 03 11a says `WHERE p.platform_project_id = '<pid>'`; the engine column is
   `engine.project.project_id` (Django attribute `platform_project_id`, `db_column="project_id"`).
   The dashboard and chain DB tests use the real column.
3. **Backend venv.** The backend `.venv` holds a stale aisc-plugin-interface 0.2.6, so `config/urls.py`
   does not import; every backend command needs `PYTHONPATH=.../shared/plugin-interface/src` (or a
   `uv sync`). The guard sets it too.
4. **0023 needs reverse operations.** The S1.2 test migrates 0023 back to 0022 (a no-op reverse for
   RunPython and RunSQL is enough).
5. **S1.5 cannot be fully green from WP1 alone.** Baseline already has 3 errors in Sean's
   `test_project_config_router` (SynchronousOnlyOperation, file identical to e34fca3), 3 Keycloak
   integration failures (need a live Keycloak) and 1 import error in `tests/integration/test_integration`.
   Check: the failing set must not grow after WP1.
6. **Guard allowed set under A1.** G4 backend allows 0022 (kept), `0023_*`,
   `repositories/system_version_repository.py`, `signals/*`, `apps.py` (signal registration) and new
   tests; every Sean file of 2026-09-23 must be byte-identical to e34fca3. The G1/G2 reference also runs
   platform 0002, because qualification at e112001 references `core.ai_system_version`.
7. **The stamp must work from sync ORM and the async `/task` route** (tests use both).
8. **Old tests to rewrite with the feature**: qualification cardSubmission, PlatformClient,
   cardVersions, seedMcas tests (freeze model); control-objectives tests that upload a card
   (test_projects.py, test_repository.py, test_project_access.py::test_an_editor_gets_past_the_door);
   catalogue ToolDetailModal.test.tsx ("Enable plugin" label); platform test_ai_system.py and
   test_api_ai_system.py (to delete, WP2).
9. **Names the tests pin where 03 was silent** (stage 5 may rename, but must then update the tests):
   qualification `src/domain/cardComponents.ts` (`defaultProperty`, `propertyOptions`,
   `componentDrift` returning `{removed, added, changed}`), `EngineClient(baseUrl, fetchImpl,
   callerToken).components(pid)`, Prisma `CardComponent` fields; dashboard
   `register_project(pid, slug, name, *, store, controls_password)`, `unregister_project(pid, *, store)`,
   `engine_results_sql`, `controls_answers_sql`, `authorize_bridge`, `security.roles_for_login`;
   platform bridge call sends `X-AISC-Bridge-Token`. WP12 chain contract: tests named
   `chain_step<N>`, ids shared through `$CHAIN_JSON` (see the scripts section below).
10. **Environment variables introduced by tests**: `PLATFORM_TEST_SUPERUSER_URL`,
    `QUALIFICATION_TEST_DATABASE_URL` / `_ADMIN_URL` / `_PSQL` (set by throwaway-db.sh),
    `CONTROLS_TEST_PG_CONTAINER`, `AISC_DASHBOARD_TEST_PG_CONTAINER`, `CHAIN_*`.

## Rules not turned into automated tests (manual checks)

| rule | why | manual check |
|---|---|---|
| S1.5 (fully green) | baseline failures independent of WP1 (finding 5) | compare the failing set before and after WP1; it must not grow |
| S3.2, S3.6 (answers stay in the form) | client-side React state; tests only prove the action returns an error instead of redirecting | stop the platform, press Save on `/p/{project}/system/edit`, see the message and every typed field still filled |
| S3.3 (UI) | server components needing platform and Prisma | non-latest `/qualify/{id}` shows "vN, kept as it was" with a link and no edit/fill/patch/component controls; `/system` "No AI card yet"; `/qualifications` lists vN, created_by, created_at highest first |
| S3.8 | baseline counts, not a behaviour | vitest 385 passed plus the new tests, tsc clean; prefill untracked files unmodified (`git status`) |
| S5.1 (only chosen fields change) | covered by the other session's untracked prefillFlow.test.ts and test_merge.py, which pass today but are not committed | upload a document with some fields typed and try both "fill empty only" and "replace" |
| S6.2, S6.3 (banner and panel text), Link/Unlink, suggestions | UI; the logic is tested through `componentDrift` and `EngineClient` | on the card page against a throwaway engine: delete, add and re-upload a component and read the banner; stop the engine and read "The engine did not answer" |
| S6.5 | needs the deployed agents service and an LLM; the degrade path is covered by the existing services/agents/tests/test_service.py::test_a_failed_run_says_so_rather_than_vanishing (passing) | Fill with and without an LLM key after 6a |
| WP6a (service starts) | starting containers against the stack is forbidden; only `config -q` on scratch copies is automated | after the next user-approved restart, check that qualification-agents is healthy |
| S8.1 end to end, S8.2 row count | real new tab and the backend write; unit tests stub both | from the launcher open the catalogue for P, install a test: one tab, P preselected, one `engine.plugin` row with `catalogue_slug` (read-only SELECT); install again: still one row |
| S10 UI labels | page rendering | "answered under vN", "not stamped", header versions on the submission page, and "not stamped" on an old project DB |
| S11.2, S11.3, S11.5 end to end | need a live Superset | member opens `/superset/dashboard/aisc-<hex>/` and posts a comment (201); non-member gets 403/404 and `POST /api/v1/chart/data` returns no rows; after `DELETE /projects/<slug>` the datasets, connection, role and dashboard are gone |
| S11.7 | `scripts/verify_review.py` and tests/test_review.py are the other session's uncommitted W4 work | run them after W4 is committed; unit baseline 74 passed, 6 skipped holds today |
| S13.3 | baseline counts | after WP13: webapp vitest 0 failures (SystemVersionBanner test deleted), `tsc -b` 0 errors |

## Rule to test detail, per repo

The tables below are the forks' records, unchanged except for heading levels.


### A1: top-level repo (guard, test bed, orders, compose, chain)

| rule | file::test | repo | status |
|---|---|---|---|
| S0.1 | scripts/tests/test_guard_frozen.py::test_s0_1_no_container_remains_after_success | top-level | already passing |
| S0.1 | scripts/tests/test_guard_frozen.py::test_s0_1_no_container_remains_after_failure | top-level | already passing |
| S0.1 | scripts/tests/test_guard_frozen.py::test_s0_1_no_container_remains_after_a_signal | top-level | already passing |
| S0.2 | scripts/tests/test_guard_frozen.py::test_s0_2_two_reference_dumps_are_byte_identical | top-level | already passing |
| S0.3 | scripts/tests/test_guard_frozen.py::test_s0_3_scripts_never_target_the_hosts_5432 | top-level | already passing |
| S1.1 (G1) | scripts/tests/test_guard_frozen.py::test_s1_1_engine_schema_equals_e34fca3 | top-level | failing as expected (MISSING 0023, platform 0003, WP3 prisma; engine diff 70 lines) |
| S1.4 (G4 backend, G5) | scripts/tests/test_guard_frozen.py::test_s1_4_backend_part_of_g4_and_g5 | top-level | failing as expected (e144bc9/a38dbb4 not reverted) |
| S1.6 | scripts/tests/test_guard_frozen.py::test_s1_6_one_ai_system_per_engine_project | top-level | failing as expected (engine.ai_system dropped by 0022) |
| G2 | scripts/tests/test_guard_frozen.py::test_g2_airo_tables_unchanged | top-level | already passing |
| G3 | scripts/tests/test_guard_frozen.py::test_g3_vendored_airo_vair_files | top-level | already passing |
| G4 webapp / S13.2 | scripts/tests/test_guard_frozen.py::test_g4_webapp_seans_files_identical_to_429f62c | top-level | failing as expected (AISystemSettings.tsx, e36fed4) |
| G4 eval/plugin-interface/plugin-manager | scripts/tests/test_guard_frozen.py::test_g4_eval_plugin_interface_plugin_manager_untouched | top-level | already passing |
| S9.1 (A1) | scripts/tests/test_guard_frozen.py::test_s9_1_seans_evaluation_files_are_byte_identical_to_e34fca3[routers/evaluation.py, models/evaluation.py] | top-level | failing as expected (both differ via e144bc9 until WP1 revert) |
| S9.4 | scripts/tests/test_guard_frozen.py::test_s9_4_g1_and_g5_after_the_stamp | top-level | failing as expected |
| S4.1 | scripts/tests/test_guard_frozen.py::test_s4_1_every_order_gives_the_reference_engine_schema | top-level | failing as expected (MISSING the 3 migrations) |
| S4.2 | scripts/tests/test_guard_frozen.py::test_s4_2_core_and_qualification_schema_identical_across_orders | top-level | failing as expected |
| S4.3 | scripts/tests/test_guard_frozen.py::test_s4_3_mcas_card_and_version_survive_every_order | top-level | failing as expected (core.system.number missing) |
| S4.4 | scripts/tests/test_guard_frozen.py::test_s4_4_unowned_core_system_fails_only_at_0003_then_recovers | top-level | failing as expected |
| WP6a | scripts/tests/test_compose.py::test_s6a_compose_config_is_valid | top-level | already passing |
| WP6a | scripts/tests/test_compose.py::test_s6a_qualification_agents_service | top-level | failing as expected (no service) |
| WP6a | scripts/tests/test_compose.py::test_s6a_qualification_web_reaches_the_agents | top-level | failing as expected (no AGENT_SERVICE_URL; port 8012 from agents Dockerfile) |
| WP2 compose | scripts/tests/test_compose.py::test_wp2_aisc_backend_has_no_platform_url | top-level | failing as expected (PLATFORM_URL still on aisc-backend) |
| S12.1 | scripts/tests/test_pipeline_chain.py::test_s12_1_the_full_chain_passes | top-level | failing as expected (step 1: MISSING chain test chain_step1) |
| S12.2 | scripts/tests/test_pipeline_chain.py::test_s12_2_each_break_fails_at_the_step_that_consumes_it[x5 links] | top-level | failing as expected (fails at step 1, not the consuming step) |
| S12.3 | scripts/tests/test_pipeline_chain.py::test_s12_3_no_container_remains | top-level | already passing |
| S12 (arg check) | scripts/tests/test_pipeline_chain.py::test_s12_unknown_link_is_refused | top-level | already passing |
| S12.1 / S11.1 step 8 | scripts/pipeline_chain/test_dashboard_queries.py::test_s12_1_engine_results_carry_the_version_of_the_evaluation | top-level | failing as expected (core.system.number, WP2) |
| S12.1 / S11.1 step 8 | scripts/pipeline_chain/test_dashboard_queries.py::test_s12_1_controls_answers_carry_the_version_they_were_answered_under | top-level | failing as expected (WP2; then WP10 columns, WP11 dashboard_ro CONNECT) |
| S11.4 | scripts/pipeline_chain/test_dashboard_queries.py::test_s11_4_engine_results_never_return_another_projects_rows | top-level | failing as expected (WP2) |

### Commands (repo root /home/listuser/aisc-install)
- All top-level tests: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests scripts/pipeline_chain` (about 4 minutes; every DB is a throwaway postgres:14-alpine on a kernel-picked 127.0.0.1 port, removed on exit).
- Guard: `scripts/guard-frozen.sh` (G1-G5), `--only G3,G4`, `--reference-only`, `--orders` (WP4). `GUARD_SOURCE=worktree` checks uncommitted trees; `GUARD_OUT=<dir>` keeps dumps and diffs.
- Chain: `scripts/test-pipeline-chain.sh [--break qualification_fk|co_fk|engine_stamp|controls_stamp|card_component]`.
- Shared helper: `scripts/lib/throwaway-pg.sh` (bash) and `scripts/pipeline_chain/throwaway.py` (Python); psql/pg_dump run via `docker exec` inside the throwaway container.

### Commit
- top-level `aa0c7b6` "Tests first: frozen guard (G1-G5, orders), test bed, compose rules and pipeline chain" (9 new files under scripts/). Nothing else staged.

### Contract for the other modules' chain tests (WP12)
Step N runs the module's tests selected by name `chain_step<N>`: pytest `-m chain -k chain_step<N>` (platform steps 1 and 6, control-objectives step 3), vitest `-t chain_step<N>` (qualification step 2, controls steps 5 and 7), Django `manage.py test aisc_backend --tag chain -k chain_step4`. Env: CHAIN_JSON (shared ids: project_pid, v1_pid, v2_pid, card_v1_id, assessment_v1_id, plugin_id, evaluation_pid, checklist_id, submission_id; the script adds project_db), CHAIN_PORT, CHAIN_SU_DSN, CHAIN_CONTAINER, CHAIN_BREAK, plus the module's usual test DSN variable pointed at the throwaway DB. A step with no matching test fails as MISSING. Consuming step per break: qualification_fk 2, card_component 3, co_fk 3, engine_stamp 8, controls_stamp 8. The engine chain step must also write one observation and measurement so step 8 has a row.

### Deviations and notes
- G1/G2 reference DB also runs platform 0002, because qualification at e112001 references core.ai_system_version; 0002 touches no engine table.
- G4 backend allowed set, under A1: 0022 (kept), 0023_*, repositories/system_version_repository.py, signals/*, apps.py (signal registration), aisc_backend/tests/* (new tests). Sean's files (computed from `git log --author=seanblevins` of 2026-09-23 up to e34fca3, incl. his 3 tests) must be byte-identical.
- The guard puts `shared/plugin-interface/src` and `shared/plugin-manager/src` on PYTHONPATH: the backend .venv holds an older aisc_plugin_interface without `list_openai_models`, so e34fca3 does not import otherwise (the image builds from ../../shared since dfe4120).
- pg_dump 14 prints a random `\restrict` key per run; the helper drops it (and the version banner) so S0.2 dumps are byte-identical.
- 03 11a's engine query says `p.platform_project_id`; the engine column (e34fca3 dump) is `engine.project.project_id`, so step 8 uses that. The WP11 bridge must use the same.
- The WP4 live-shape fixture takes init/ and platform 0001/0002 from top-level ad6262f (core.system owned by the superuser) and engine from backend dfe4120 (0022).

### Not automated
- WP6a "docker compose config" is automated on scratch copies with dummy values for the `:?` secrets (env.secrets is never read); actually starting qualification-agents is manual (not allowed against the stack).

### A2: platform (WP2, platform side of WP11)

Repo: top-level `aisc-install` (platform/). Commit: `aa9554e` "Tests first: platform card versions in core.system (WP2) and dashboard bridge calls (WP11)" (5 files under platform/tests only).

| rule | file::test | repo | status |
|---|---|---|---|
| D1/A2 | platform/tests/test_card_versions_migration.py::test_d1_project_databases_sql_gives_core_system_to_platform_rw | aisc-install | failing as expected (line absent from init/project-databases.sql) |
| D1/A2 | platform/tests/test_card_versions_migration.py::test_d1_running_the_platform_part_twice_makes_platform_rw_the_owner | aisc-install | failing as expected (owner stays aisc-postgres-user) |
| S2.6 | platform/tests/test_card_versions_migration.py::test_s2_6_on_a_fresh_database_0003_succeeds_and_core_system_is_empty | aisc-install | failing as expected (0003 missing) |
| S2.6 | platform/tests/test_card_versions_migration.py::test_s2_6_constraints_after_0003 | aisc-install | failing as expected (no system_project_number_key) |
| S2.6 | platform/tests/test_card_versions_migration.py::test_s2_6_number_must_be_positive | aisc-install | failing as expected (no number column) |
| S2.6 (grants kept) | platform/tests/test_card_versions_migration.py::test_s2_6_grants_on_core_system_are_kept | aisc-install | failing as expected (0003 not applied; grant asserts pass today) |
| S2.7 | platform/tests/test_card_versions_migration.py::test_s2_7_on_the_live_shape_every_pid_is_kept_and_mcas_is_number_1 | aisc-install | failing as expected (0003 missing) |
| S2.8 | platform/tests/test_card_versions_migration.py::test_s2_8_without_ownership_0003_fails_with_the_guard_message_and_is_not_recorded | aisc-install | failing as expected (no guard raise) |
| S2.4 | platform/tests/test_card_versions_migration.py::test_s2_4_the_trigger_refuses_changes_to_an_older_version_and_to_number_or_project | aisc-install | failing as expected (no number column / trigger) |
| S2.1 | platform/tests/test_api_system_versions.py::test_s2_1_two_saves_make_versions_1_and_2_even_with_identical_name_and_version | aisc-install | failing as expected (route 404) |
| S2.1 | platform/tests/test_api_system_versions.py::test_s2_1_the_project_may_be_named_by_its_pid | aisc-install | failing as expected |
| S2.1 | platform/tests/test_api_system_versions.py::test_s2_1_an_empty_name_is_422 | aisc-install | failing as expected (404 not 422) |
| S2.1 | platform/tests/test_api_system_versions.py::test_s2_1_the_list_is_highest_number_first | aisc-install | failing as expected |
| S2.1 | platform/tests/test_api_system_versions.py::test_s2_1_systems_pid_answers_with_number_and_created_by | aisc-install | failing as expected |
| S2.2 | platform/tests/test_api_system_versions.py::test_s2_2_a_viewer_may_read_but_not_save | aisc-install | failing as expected (404 not 403) |
| S2.2 | platform/tests/test_api_system_versions.py::test_s2_2_a_stranger_gets_404_everywhere | aisc-install | failing as expected |
| S2.2 | platform/tests/test_api_system_versions.py::test_s2_2_an_unknown_project_is_404 | aisc-install | already passing (vacuously: route absent answers 404) |
| S2.3 | platform/tests/test_api_system_versions.py::test_s2_3_concurrent_saves_get_1_and_2_without_duplicate_or_gap | aisc-install | failing as expected |
| S2.4 | platform/tests/test_api_system_versions.py::test_s2_4_version_1_cannot_change_once_2_exists_and_2_can | aisc-install | failing as expected |
| S2.5 | platform/tests/test_api_system_versions.py::test_s2_5_deleting_the_project_deletes_its_versions | aisc-install | failing as expected |
| S2.9 | platform/tests/test_api_system_versions.py::test_s2_9_latest_is_the_highest_number | aisc-install | failing as expected |
| S2.9 / "POST /projects creates no system row" | platform/tests/test_api_system_versions.py::test_s2_9_a_new_project_has_no_version_and_latest_is_null | aisc-install | failing as expected |
| WP2 removed routes | platform/tests/test_api_system_versions.py::test_wp2_the_old_system_routes_are_gone[5 params] | aisc-install | failing as expected (routes answer 200/201) |
| WP2 removed routes | platform/tests/test_api_system_versions.py::test_wp2_the_old_version_routes_are_gone | aisc-install | failing as expected |
| WP2 compose | platform/tests/test_compose_engine_env.py::test_wp2_aisc_backend_has_no_platform_url | aisc-install | failing as expected (PLATFORM_URL still on aisc-backend) |
| WP11 template | platform/tests/test_dashboard_bridge.py::test_wp11_the_dashboard_may_connect_to_a_project_database_and_use_its_controls_schema | aisc-install | failing as expected (dashboard_ro: permission denied for database) |
| WP11 template | platform/tests/test_dashboard_bridge.py::test_wp11_the_dashboard_still_writes_nothing_in_a_project_database | aisc-install | failing as expected (cannot connect yet) |
| S11.5 (platform) | platform/tests/test_dashboard_bridge.py::test_s11_5_making_a_project_registers_it_with_the_dashboard_bridge | aisc-install | failing as expected (no bridge call) |
| S11.5 (platform) | platform/tests/test_dashboard_bridge.py::test_s11_5_deleting_a_project_unregisters_it_before_its_database_is_dropped | aisc-install | failing as expected |
| S11.5 (platform) | platform/tests/test_dashboard_bridge.py::test_s11_5_a_bridge_that_is_down_does_not_stop_making_or_deleting_a_project | aisc-install | already passing (no call is made today) |
| S11.5 (platform, 5 s timeout) | platform/tests/test_dashboard_bridge.py::test_s11_5_a_bridge_that_hangs_is_given_up_on_after_about_5_seconds | aisc-install | failing as expected (bridge not called) |
| S11.5 (platform, retry) | platform/tests/test_dashboard_bridge.py::test_s11_5_a_failed_registration_is_retried_by_provision_all | aisc-install | failing as expected |

Helper (not a test): `platform/tests/core_scratch.py` makes a scratch database per migration test (CREATE DATABASE as superuser, init/platform-db.sql with psql meta-commands stripped and `DATABASE platform` renamed), applies platform migrations up to a given file as platform_rw, drops it afterwards. Refuses port 5432.

### Command

Throwaway DB prepared as 03 section 0 (postgres:14-alpine, both init files via `docker exec -i <c> psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < init/...`), then from `platform/`:

```
PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform \
PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform \
uv run --extra dev pytest -q -p no:cacheprovider
```

`PLATFORM_TEST_SUPERUSER_URL` is new (the migration tests skip without it). Result on the run: 34 failed (all new, all for the missing feature), 86 passed (84 baseline, unchanged, plus 2 new already passing). Container `aisc-t-platform-26c6cae6` removed.

### Notes

- The API tests need the ownership line to have run on the test DB before 0003 (section 0 already runs init/project-databases.sql), otherwise 0003's guard stops `pool()` and every DB test errors.
- Bridge tests assume the platform sends `X-AISC-Bridge-Token: $DASHBOARD_BRIDGE_TOKEN` (the bridge 401s otherwise, S11.6); the request body is not asserted.
- The existing test_ai_system.py / test_api_ai_system.py still pass today and are left for the implementation to delete.
- Not automated: nothing in this scope; S2.3 concurrency is tested with two threads, which exercises the advisory lock only if the implementation serialises inside one DB transaction (it should).

### apps/backend (fork B): WP1 and WP9

Commit: `2e718cd` on apps/backend feat/unified-modules, "Tests first: one system per project again (WP1) and the evaluation stamp from core.system (WP9)". Files:
- aisc_backend/tests/test_one_system_per_project.py
- aisc_backend/tests/test_migration_0023_data.py
- aisc_backend/tests/test_frozen_sean_files.py
- aisc_backend/tests/test_evaluation_system_stamp.py

| rule | file::test | repo | status |
|---|---|---|---|
| S1.2 | test_migration_0023_data.py::Migration0023MovesPartsBackOntoTheSystem.test_s1_2_every_part_keeps_its_pid_and_joins_its_project_s_one_system | apps/backend | failing as expected (0023 missing), sqlite and Postgres |
| S1.3 | test_one_system_per_project.py::Migration0023Exists.test_s1_3_0023_applied_on_sqlite_without_core | apps/backend | failing as expected (0023 not applied) |
| WP1 data (0023 after 0022, 0022 kept) | test_one_system_per_project.py::Migration0023Exists.test_s1_0023_depends_on_0022, test_s1_0023_is_the_leaf | apps/backend | failing as expected |
| WP1 models = e34fca3 | test_one_system_per_project.py::ModelStateIsE34fca3.test_s1_aisystem_model_is_back_on_table_ai_system, test_s1_component_belongs_to_the_system, test_s1_component_has_no_version_fields, test_s1_no_system_version_parts_model | apps/backend | failing as expected |
| S1.6 | test_one_system_per_project.py::OneSystemPerProject.test_s1_6_second_system_for_a_project_is_refused | apps/backend | failing as expected (no AISystem model) |
| WP1 interface GET aisystem | test_one_system_per_project.py::AISystemRouteIsE34fca3.test_s1_aisystem_shape_and_one_stable_system, test_s1_aisystem_does_not_ask_the_platform | apps/backend | failing as expected (extra `version` key, null pid; 503 with platform down) |
| WP1 interface POST task, no 503 | test_one_system_per_project.py::EvaluationTaskWithoutThePlatform.test_s1_no_503_when_the_platform_is_down | apps/backend | failing as expected (503) |
| WP1 interface POST task, no "outside the version" | test_one_system_per_project.py::EvaluationTaskWithoutThePlatform.test_s1_no_rejection_of_inputs_outside_the_version | apps/backend | failing as expected (400) |
| S1.5 (Sean's tests restored) | test_frozen_sean_files.py::SeanFilesAreE34fca3.test_s1_5_sean_tests_are_e34fca3 | apps/backend | failing as expected (2 of Sean's 3 test files differ from e34fca3) |
| S1.5 (suite green) | full suite command below | apps/backend | failing now: baseline has 3 ERRORs in Sean's test_project_config_router (SynchronousOnlyOperation), 3 keycloak integration FAILs (need a live Keycloak) and 1 import ERROR in tests/integration/test_integration; see note |
| S9.1 (per A1) | test_frozen_sean_files.py::SeanFilesAreE34fca3.test_s9_1_evaluation_router_is_e34fca3, test_s9_1_evaluation_model_is_e34fca3 | apps/backend | failing as expected (e144bc9 changed both; WP1 revert restores) |
| G4 backend (Sean's files) | test_frozen_sean_files.py::SeanFilesAreE34fca3.test_g4_every_sean_file_is_e34fca3 | apps/backend | failing as expected (12 of 28 files differ) |
| WP9 interface | test_evaluation_system_stamp.py::LatestSystemPid.test_s9_latest_system_pid_is_an_async_function | apps/backend | failing as expected (module missing) |
| S9.2 | test_evaluation_system_stamp.py::LatestSystemPid.test_s9_2_highest_number_wins | apps/backend | failing as expected on Postgres; skipped on sqlite |
| S9.2 | test_evaluation_system_stamp.py::EvaluationCarriesTheLatestVersion.test_s9_2_new_evaluation_gets_the_latest_version_and_keeps_it | apps/backend | failing as expected on Postgres (system_id None); skipped on sqlite |
| S9.2 | test_evaluation_system_stamp.py::EvaluationCarriesTheLatestVersion.test_s9_2_started_through_the_route | apps/backend | failing as expected on Postgres (503 from 0022 code); skipped on sqlite |
| S9.2 (explicit stamp kept) | test_evaluation_system_stamp.py::EvaluationCarriesTheLatestVersion.test_s9_2_an_explicit_system_id_is_kept | apps/backend | already passing (Postgres) |
| S9.3 | test_evaluation_system_stamp.py::LatestSystemPid.test_s9_3_none_for_no_platform_project, test_s9_3_none_on_sqlite, test_s9_3_none_when_core_system_is_absent, test_s9_3_none_when_the_project_has_no_version | apps/backend | failing as expected (module missing) |
| S9.3 | test_evaluation_system_stamp.py::EvaluationCarriesTheLatestVersion.test_s9_3_route_without_a_version_starts_with_null | apps/backend | failing as expected (503) |
| S9.3 | test_evaluation_system_stamp.py::EvaluationCarriesTheLatestVersion.test_s9_3_no_version_gives_null (Postgres), test_s9_3_sqlite_gives_null (sqlite) | apps/backend | already passing |
| S1.1, S1.4, S9.4 | scripts/guard-frozen.sh (G1, G4, G5), other fork | top-level | see guard part |

Commands (from apps/backend):
- sqlite unit suite: `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src DB_ENGINE=django.db.backends.sqlite3 DB_NAME=$SCRATCH/t.db .venv/bin/python manage.py test aisc_backend`
- Postgres (throwaway): `docker run --rm -d --name aisc-t-backend-$HEX -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine`; `docker exec -i aisc-t-backend-$HEX psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 < init/platform-db.sql` (same for init/project-databases.sql); check `$PORT != 5432`; then `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=aisc-postgres-user DB_PASSWORD=$PW DB_HOST=127.0.0.1 DB_PORT=$PORT .venv/bin/python manage.py test --noinput aisc_backend`; `docker rm -f aisc-t-backend-$HEX`. The superuser is used because Django creates `test_platform`; no DB_SCHEMA, so tables go to `public` and the S9 tests create a minimal `core.system (pid, project_id, number)` inside the test transaction.

Notes:
- Env issue (not a product change): the backend `.venv` holds a stale non-editable aisc-plugin-interface 0.2.6 without `list_openai_models`, so `config/urls.py` fails to import. Every command above prepends `PYTHONPATH=/home/listuser/aisc-install/shared/plugin-interface/src`. A `uv sync` would also fix it (pyproject points at the editable path).
- New sqlite result: 29 tests, 33 failures (subtests counted), 7 skipped (Postgres-only). Postgres result: 25 tests, 20 failures, 3 skipped (sqlite-only), 2 passing. All failures are assertion failures naming the missing feature; none is an import, syntax or fixture error.
- S1.2's test migrates back from 0023 to 0022 on an empty table, so 0023 must have reverse operations (noop reverse for RunPython and RunSQL is enough). Flag for stage 5.
- S1.5 cannot be fully green from WP1 alone: Sean's `test_project_config_router` (byte-identical to e34fca3) already errors with SynchronousOnlyOperation, and the keycloak integration tests need a running Keycloak. Manual check: compare the failing set before and after WP1; it must not grow.
- Signal design (A1) is not pinned beyond behaviour: the tests create evaluations through the sync ORM and through the async `/task` route, so the stamp must work in both contexts.

### Fork C: apps/qualification (WP3, WP5, WP6, WP7 route)

Repo: apps/qualification, branch feat/unified-modules. Commit: `4440c4e` "Tests first: card versions in core.system, only-latest edits, engine components by AIRO, per-version JSON-LD route, prefill rules". Others' 16 uncommitted/untracked files (prefill W3, QualifyForm.tsx, next.config.ts) left untouched and unstaged.

Files committed:
- test/unit/cardVersionsInCoreSystem.test.ts
- test/unit/onlyLatestCardChanges.test.ts
- test/unit/seedMcasVersions.test.ts
- test/unit/engineComponents.test.ts
- test/unit/systemVersionOntologyRoute.test.ts
- test/unit/prefillOnEditPage.test.ts
- test/db/cardVersions.db.test.ts (DB-gated, skips without env)
- test/db/throwaway-db.sh (test infra: starts postgres:14-alpine `aisc-t-qual-<hex>` on a free port, applies init/platform-db.sql, init/project-databases.sql, every platform/migrations/*.sql as platform_rw, `prisma migrate deploy` as qualification_rw, runs `vitest run test/db`, removes the container on exit; refuses 5432)
- services/ontology/tests/test_engine_components.py
- services/prefill/tests/test_no_term_literal.py (inside the untracked services/prefill dir; only this file is committed)

| rule | file::test | repo | status |
|---|---|---|---|
| S3.1 | test/unit/cardVersionsInCoreSystem.test.ts::S3.1 createVersion POSTs the identity to /projects/{project}/system-versions | qualification | failing as expected (createVersion is not a function) |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 listVersions GETs /projects/{project}/system-versions | qualification | failing as expected |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 latestVersion GETs .../system-versions/latest, and null when there is none | qualification | failing as expected |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 the freeze-era methods are gone | qualification | failing as expected (aiSystem still defined) |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 the next card is always the version after the latest | qualification | already passing |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 a latest version left without a card (a failed save) is skipped | qualification | already passing |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 the domain no longer mentions frozen versions | qualification | failing as expected |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 each save makes one core.system version, then the card pointing at it; nothing is frozen | qualification | failing as expected (calls versionForNewCard, freeze) |
| S3.1 | cardVersionsInCoreSystem.test.ts::S3.1 CardExistsError is gone | qualification | failing as expected |
| S3.1 | test/db/cardVersions.db.test.ts::S3.1 one card per version: the unique index on system_id stays | qualification | already passing (DB) |
| S3.2 | cardVersionsInCoreSystem.test.ts::S3.2 the second save starts from the first card: answers, tags and risks in order | qualification | failing as expected (startingPoint still calls aiSystem) |
| S3.3 | cardVersionsInCoreSystem.test.ts::S3.3 only the latest version's card is current; an older one is not, even when the latest has no card | qualification | failing as expected |
| S3.3 | test/unit/onlyLatestCardChanges.test.ts::S3.3 a patch on the v1 card, with v2 the latest, is refused and writes nothing | qualification | failing as expected (patch is saved) |
| S3.3 | onlyLatestCardChanges.test.ts::S3.3 a reset of the v1 card is refused and writes nothing | qualification | failing as expected |
| S3.3 | onlyLatestCardChanges.test.ts::S3.3 aimed at the v1 card, it is 403 and nothing is stored (PUT extracted) | qualification | failing as expected (200) |
| S3.3 | test/db/cardVersions.db.test.ts::S3.3 has card_is_latest(uuid) and the three only-latest triggers | qualification | failing as expected (DB, none exist) |
| S3.3 | cardVersions.db.test.ts::S3.3 the migration file refuses cards pointing at versions missing from core.system | qualification | failing as expected (migration file missing) |
| S3.3 | cardVersions.db.test.ts::S3.3 card_is_latest says which version is the latest | qualification | failing as expected (fixture: core.system.number missing, WP2 0003) |
| S3.3 | cardVersions.db.test.ts::S3.3 an UPDATE of the v1 card raises once v2 exists | qualification | failing as expected (same, WP2 dependency) |
| S3.3 | cardVersions.db.test.ts::S3.3 inserting or updating an answer of the v1 card raises | qualification | failing as expected (same) |
| S3.3, S6.4 | cardVersions.db.test.ts::S3.3 linking a component on the v1 card raises (S6.4) | qualification | failing as expected (same) |
| S3.3, S3.4 | cardVersions.db.test.ts::S3.3/S3.4 the latest card and its answers and components still change in place | qualification | failing as expected (same) |
| WP3 step 6 | cardVersions.db.test.ts::WP3 step 6 card_component has the columns, the unique pair and the component index | qualification | failing as expected (table missing) |
| WP3 step 6 | cardVersions.db.test.ts::WP3 step 6 card_component refuses a property that is not one of the five | qualification | failing as expected (WP2 dependency) |
| S3.4 | onlyLatestCardChanges.test.ts::S3.4 a patch on the latest card edits it in place and makes no version | qualification | already passing |
| S3.4 | onlyLatestCardChanges.test.ts::S3.4 aimed at the latest card, it is stored in place and no version is made | qualification | already passing |
| S3.5 | test/unit/seedMcasVersions.test.ts::S3.5 names MCAS's version with one POST to /system-versions | qualification | failing as expected |
| S3.5 | seedMcasVersions.test.ts::S3.5 there is nothing to freeze any more | qualification | failing as expected |
| S3.5 | seedMcasVersions.test.ts::S3.5 a project that already has its card gets no version | qualification | already passing |
| S3.5 | seedMcasVersions.test.ts::S3.5 an empty project gets v1 and the card points at it, with one platform call | qualification | failing as expected |
| S3.6 | cardVersionsInCoreSystem.test.ts::S3.6 an unreachable platform is reported, not swallowed | qualification | failing as expected |
| S3.6 | cardVersionsInCoreSystem.test.ts::S3.6 when the platform is unreachable, nothing is stored | qualification | failing as expected |
| S3.6 | cardVersionsInCoreSystem.test.ts::S3.6 shows 'The platform did not answer; nothing was saved' and does not redirect | qualification | failing as expected (old message) |
| S3.7 | cardVersions.db.test.ts::S3.7 qualification.system_id references core.system(pid) ON DELETE CASCADE | qualification | failing as expected (points at core.ai_system_version) |
| S3.7 | cardVersions.db.test.ts::S3.7 no DELETE trigger on the answers, so the project cascade is never blocked | qualification | already passing |
| S3.7 | cardVersions.db.test.ts::S3.7 deleting the project removes its cards, answers, risks, graphs and components | qualification | failing as expected (WP2 dependency) |
| S5.1 | test/unit/prefillOnEditPage.test.ts::S5.1 the edit page renders the form that carries the upload control | qualification | already passing (with the uncommitted W3 files in the tree) |
| S5.1 | prefillOnEditPage.test.ts::S5.1 a document can propose exactly the 21 mapped fields | qualification | already passing (same) |
| S5.1 | prefillOnEditPage.test.ts::S5.1 the prefill field list shared with the service has the same 21 fields | qualification | already passing (same) |
| S5.2 | prefillOnEditPage.test.ts::S5.2 is refused with 'Pick at least one market form' | qualification | already passing |
| S5.2 | prefillOnEditPage.test.ts::S5.2 the save action returns the message instead of redirecting | qualification | already passing |
| S5.3 | services/prefill/tests/test_no_term_literal.py::test_s5_3_an_unmatched_affected_is_left_empty | qualification | already passing |
| S5.3 | test_no_term_literal.py::test_s5_3_unmatched_impact_areas_are_left_out | qualification | already passing |
| S5.3 | test_no_term_literal.py::test_s5_3_the_literal_no_term_never_appears_in_a_risk_row | qualification | already passing |
| S5.4 | test_no_term_literal.py::test_s5_4_the_prefill_proposes_no_tags | qualification | already passing |
| S5.4 | prefillOnEditPage.test.ts::S5.4 no tag picker is prefillable | qualification | already passing |
| S5.4 | prefillOnEditPage.test.ts::S5.4 what the form holds, as sent to the prefill, carries no tags | qualification | already passing |
| S5.5 | existing suites | qualification | already passing: prefill Python 73 passed (69 existing + 4 new); vitest 385 passed with 36 expected failures (all in the new files); tsc clean |
| S6.1 | services/ontology/tests/test_engine_components.py::test_s6_1_linked_components_are_airo_edges_from_the_system | qualification | failing as expected |
| S6.1 | test_engine_components.py::test_s6_1_each_component_node_is_typed_by_the_property_range | qualification | failing as expected |
| S6.1 | test_engine_components.py::test_s6_1_each_component_node_carries_its_name_and_object_name | qualification | failing as expected |
| S6.1 | test_engine_components.py::test_s6_1_the_jsonld_parses_back_to_the_same_triples | qualification | failing as expected |
| S6.1 | test_engine_components.py::test_s6_1_other_component_types_map_to_their_range | qualification | failing as expected |
| S6.1 | test_engine_components.py::test_s6_1_without_engine_components_the_graph_is_unchanged | qualification | already passing (regression guard) |
| S6.1 | test_engine_components.py::test_s6_1_schema_has_the_component_sub_properties[4 params] | qualification | failing as expected (not in schema.PROPERTIES) |
| S6.1 | test/unit/engineComponents.test.ts::S6.1 model and llm are hasModel; dataset is hasTestingData; ... | qualification | failing as expected (module missing) |
| S6.1 | engineComponents.test.ts::S6.1 a dataset is also offered as training or validation data | qualification | failing as expected |
| S6.1 | engineComponents.test.ts::S6.1 toExport gains engineComponents from the card_component rows | qualification | failing as expected |
| S6.2 | engineComponents.test.ts::S6.2 no drift / removed / added / changed / changes nothing it was given (5 tests) | qualification | failing as expected (module missing) |
| S6.3 | engineComponents.test.ts::S6.3 an unreachable engine says 'The engine did not answer' | qualification | failing as expected |
| S6.4 | see S3.3 DB test "linking a component on the v1 card raises" | qualification | failing as expected |
| S6.6 | engineComponents.test.ts::S6.6 reads the engine project by platform pid, then its aisystem, with the caller's token | qualification | failing as expected |
| S6.6 | engineComponents.test.ts::S6.6 a stranger (the engine lists no project for them) gets no components | qualification | failing as expected |
| S6.6 | engineComponents.test.ts::S6.6 it uses AISC_BACKEND_URL by default and never writes to the engine | qualification | failing as expected |
| S7.3 | test/unit/systemVersionOntologyRoute.test.ts::S7.3 the route file exists | qualification | failing as expected |
| S7.3 | systemVersionOntologyRoute.test.ts::S7.3 a non-member gets 404 | qualification | failing as expected |
| S7.3 | systemVersionOntologyRoute.test.ts::S7.3 a version whose card belongs to another project is 404 | qualification | failing as expected |
| S7.3 | systemVersionOntologyRoute.test.ts::S7.3 a version with no card is 404 | qualification | failing as expected |
| S7.3 | systemVersionOntologyRoute.test.ts::S7.3 the builder being down is 502 | qualification | failing as expected |
| S7.5 | systemVersionOntologyRoute.test.ts::S7.5 a member gets the card's JSON-LD, the very bytes the store delivers | qualification | failing as expected |

### Commands
- Unit suite (no DB): `cd apps/qualification && npx vitest run && npx tsc --noEmit` (the test/db file skips itself without the env).
- DB suite: `cd apps/qualification && test/db/throwaway-db.sh` (starts and removes its own container; `KEEP=1` leaves it up and prints `QUALIFICATION_TEST_DATABASE_URL`, `QUALIFICATION_TEST_ADMIN_URL`, `QUALIFICATION_TEST_PSQL`). The test file refuses any DSN on :5432.
- Python: `docker run --rm -v $PWD:/w -e PYTHONDONTWRITEBYTECODE=1 -e PREFILL_FIELDS_PATH=/w/src/data/prefillFields.json -w /w/services/<ontology|prefill> python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"` from apps/qualification (the whole app must be mounted: airo_min looks for src/data/airo_vocab.json three levels up).
- Results at write time: vitest 36 failed (all new, all missing feature) / 385 passed / 13 skipped; tsc clean; ontology 9 failed / 176 passed; prefill 73 passed; DB file 4 catalog failures + fixture failure `column "number" of relation "system" does not exist` (WP2 0003 not yet written) + 2 passed.

### Assumptions to confirm (names 03 did not fix)
- Drift and property helpers live in `src/domain/cardComponents.ts` as `defaultProperty(type)`, `propertyOptions(type)`, `componentDrift(linkedRows, engineComponents)` returning `{removed, added, changed}`.
- `EngineClient(baseUrl, fetchImpl, callerToken)` with `components(platformProjectPid)`; rejects with "The engine did not answer".
- Prisma `CardComponent` fields: `componentPid, airoProperty, name, componentType, objectName, linkedAt`, reachable as `qualification.components`.
- The per-version JSON-LD route is called with the project pid in `{project}`; card lookup by `systemId` via `prisma.qualification.findUnique|findFirst`.
- S3.3 "403" for server actions: the ontology actions return `{ok:false, error}` matching /403|not the latest|kept as it was|read-only/; the extracted PUT returns HTTP 403.
- Behaviour DB tests need platform 0003 (`core.system.number`) applied before the qualification migration; throwaway-db.sh applies every platform migration first.
- Existing tests that pin the old freeze model (test/unit/cardSubmission.test.ts, PlatformClient.test.ts, cardVersions.test.ts, seedMcas.test.ts) will fail once WP3 lands; stage 5 must rewrite them, they were not touched here.

### Manual or not automated
- S3.2/S3.6 "the answers stay in the form" after an error: client-side React state; the test proves the action returns an error rather than redirecting. Manual: on /p/{project}/system/edit, stop the platform, press Save, check the message and that every typed field is still filled.
- S3.3 UI parts: `/p/{project}/qualify/{id}` for a non-latest card shows "vN, kept as it was" with a link to the latest and no edit, fill, patch or component controls; `/p/{project}/system` "No AI card yet"; `/qualifications` lists vN, created_by, created_at highest first. Manual browser check (server components needing the platform and Prisma).
- S3.8: baseline only (vitest/tsc counts above; the prefill files were not modified).
- S5.1 "only the chosen fields change" when picking "fill empty only" or "replace": covered by the existing untracked tests (prefillFlow.test.ts, test_merge.py) of the W3 author; manual check: upload a document on the edit page with some fields typed, pick each option.
- S6.2 banner, S6.3 panel text on the page, "Link"/"Unlink" upsert and the "suggestions" list: UI; the logic is covered through componentDrift/EngineClient; manual check on the card page against a throwaway engine.
- S6.5 (agents service deployed, LLM fills techniques; no key degrades): needs the compose service (6a) and an LLM; the degrade path is covered by the existing services/agents/tests/test_service.py::test_a_failed_run_says_so_rather_than_vanishing (already passing). Manual: `docker compose config -q` on a scratch copy, then a Fill with and without LLM key.
- G2 (AIRO tables unchanged) and G3 (vendored hashes) belong to the guard script (fork A); services/ontology/tests/test_vendored.py stays green (it passed in the ontology run).

### Fork D: control-objectives (WP7) and controls (WP10, S8.3, WP11 grant)

### control-objectives (apps/control-objectives)

T = tests/test_assessment_of_a_version.py, M = tests/test_migration_assessment_of_a_version.py

| rule | file::test | repo | status |
|---|---|---|---|
| S7.1 | T::test_s7_1_starting_twice_on_v1_opens_the_same_assessment | apps/control-objectives | failing as expected (form start with no file: 500 today, not 303) |
| S7.2 | T::test_s7_2_v2_gets_its_own_assessment_and_v1s_is_left_as_it_was | apps/control-objectives | failing as expected |
| S7.2 | T::test_s7_2_map_and_severity_on_a_non_latest_assessment_are_409 | apps/control-objectives | failing as expected |
| S7.2 | T::test_s7_2_the_pages_say_which_version_and_whether_it_is_read_only | apps/control-objectives | failing as expected |
| S7.3 | T::test_s7_3_a_stranger_cannot_start_or_open_an_assessment | apps/control-objectives | already passing (middleware 404s; no upstream call made) |
| S7.4 | T::test_s7_4_the_risks_stored_are_the_cards_risks_by_text_and_position | apps/control-objectives | failing as expected |
| S7.5 | T::test_s7_5_the_graph_is_the_served_bytes_and_its_digest_is_their_sha256 | apps/control-objectives | failing as expected |
| S7.6 | T::test_s7_6_deleting_the_version_deletes_its_assessment | apps/control-objectives | failing as expected |
| S7.6 | T::test_s7_6_deleting_the_project_deletes_versions_and_assessments | apps/control-objectives | failing as expected |
| S7.6 | M::test_s7_6_after_the_migration_deleting_the_version_deletes_the_assessment | apps/control-objectives | failing as expected (revision missing) |
| S7.7 | T::test_s7_7_a_new_catalogue_changes_the_digest_of_new_assessments_only | apps/control-objectives | failing as expected |
| WP7 409 no version | T::test_no_version_yet_is_409_and_nothing_is_stored | apps/control-objectives | failing as expected |
| WP7 409 no card | T::test_a_version_without_a_card_is_409_and_nothing_is_stored | apps/control-objectives | failing as expected |
| WP7 502 | T::test_an_upstream_that_is_down_is_502_and_nothing_is_stored[platform,qualification] | apps/control-objectives | failing as expected |
| WP7 Authorization forwarded | T::test_the_callers_authorization_is_what_reaches_both_upstreams | apps/control-objectives | failing as expected |
| WP7 upload leaves the page | T::test_the_projects_page_has_a_start_button_and_no_upload | apps/control-objectives | failing as expected |
| WP7 routes removed | T::test_the_json_upload_routes_are_removed | apps/control-objectives | failing as expected (201 today) |
| WP7 upstream.py | T::test_upstream_latest_version_returns_the_platforms_row, ..._is_none_when_there_is_none, test_upstream_card_jsonld_returns_the_bytes_as_served | apps/control-objectives | failing as expected (module missing) |
| WP7 data 1,2,4,5 | M::test_s7_data_backfills_the_latest_version_and_drops_the_old_link | apps/control-objectives | failing as expected (Can't locate revision 4d2a9c1e7b60) |
| WP7 data 3 (NULL) | M::test_s7_data_refuses_an_assessment_with_no_version | apps/control-objectives | failing as expected (revision does not exist yet) |
| WP7 data 3 (duplicate) | M::test_s7_data_refuses_two_assessments_on_one_version | apps/control-objectives | failing as expected |
| WP7 data revision chain | M::test_the_revision_follows_the_live_head | apps/control-objectives | failing as expected (head is 3b91d0e7a52c) |

Fixture change: tests/conftest.py `CORE_PROJECT_DDL` gains `core.system (pid, project_id, number)`, teardown drops it, new `system_version(project, number)` fixture. The existing 220 tests stay green.

Interface assumptions pinned by the tests (implementer, note): upstream URLs are read from `PLATFORM_URL` / `QUALIFICATION_URL` at call or app-creation time, not at import; `latest_version(project, token)` and `card_jsonld(project, system_pid, token)` take the incoming Authorization header value (e.g. `Bearer x`) and forward it verbatim; the start form takes no file; 409 body contains "No AI card for the latest version yet"; pages contain "Assessment of vN" and "read-only: vM is the latest". Existing tests that upload a card (tests/test_projects.py, test_repository.py, test_project_access.py::test_an_editor_gets_past_the_door) will need updating in WP7 because the upload routes go.

Command:
```
cd apps/control-objectives
CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test uv run --extra dev pytest -q
```
(The fixture drops and recreates `control_objectives_test` and `control_objectives_test_alembic` on that server; it needs the superuser. Result now: 220 old pass, 24 new fail, 1 new already passes.)

Commit: control-objectives `4e33a0e` "Tests first: an assessment is of one system version (WP7, S7.1-S7.7)" (tests/conftest.py, tests/test_assessment_of_a_version.py, tests/test_migration_assessment_of_a_version.py).

### controls (apps/controls)

S = test/integration/answer-stamps.test.ts, U = test/unit/systemVersion.test.ts, G = test/integration/dashboard-grants.test.ts, I = test/integration/install-once-throwaway.test.ts

| rule | file::test | repo | status |
|---|---|---|---|
| WP10 data | S::the migration 20260923210000_answers_carry_the_system_version is there | apps/controls | failing as expected |
| WP10 data | S::the three stamp columns exist, nullable, with no foreign key | apps/controls | failing as expected |
| S10.1 | S::S10.1: A answered under v1, then B under v2: A keeps v1, B gets v2 | apps/controls | failing as expected (column system_version_pid does not exist) |
| S10.1 | S::S10.1: a changed answer is restamped with the version latest now | apps/controls | failing as expected |
| S10.1 | U::S10.1: returns the platform's latest version as {pid, number}; asks with the caller's token; is null when the project has no version yet | apps/controls | failing as expected (module @/lib/systemVersion missing) |
| S10.2 | S::S10.2: with the platform down the save succeeds, and new answers are unstamped | apps/controls | failing as expected |
| S10.2 | U::S10.2: is null, and warns, when the platform errors; is null when the platform is not there at all; gives up after 3 s and is null | apps/controls | failing as expected |
| S10.3 | S::S10.3: saving again with no change changes no stamp and no answered_at | apps/controls | failing as expected |
| S10.4 | S::S10.4: gains the stamp columns when first opened, and its old answers are unstamped | apps/controls | failing as expected (DB migrated with only the pre-WP10 migration, then opened through prismaFor) |
| S10.5 | S::S10.5: amending a closed submission keeps each copied answer's stamp | apps/controls | failing as expected |
| S8.3 | I::S8.3: the first install makes one row with catalogueId, the second says already installed | apps/controls | already passing |
| WP11 data (controls grant) | G::the migration 20260923210100_dashboard_reads_controls is there | apps/controls | failing as expected |
| WP11 data (controls grant) | G::dashboard_ro can SELECT every controls table after migrating, and nothing more | apps/controls | failing as expected (permission denied for table checklist) |
| WP11 data (default privileges) | G::a table controls_rw makes later is readable too (default privileges) | apps/controls | failing as expected (permission denied) |

New helper `test/integration/throwawayDb.ts`: runs superuser SQL in the container named by `CONTROLS_TEST_PG_CONTAINER` (must start `aisc-t-`), makes project DBs by applying `platform/project-template/0001_controls.sql`, and refuses to run when `PROJECT_DATABASE_URL` is on :5432. The new integration tests skip without both variables.

Command:
```
cd apps/controls
CONTROLS_TEST_PG_CONTAINER=aisc-t-<hex> \
PROJECT_DATABASE_URL='postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls&connection_limit=2' \
npx vitest run test/unit test/integration/answer-stamps.test.ts test/integration/dashboard-grants.test.ts test/integration/install-once-throwaway.test.ts
```
The throwaway server needs init/platform-db.sql and init/project-databases.sql applied (roles controls_rw, dashboard_ro, platform_rw). Without the env vars, `npx vitest run` gives 94 passed, 6 failed (the new unit tests), 62 skipped.

HAZARD (flag for the pipeline): the pre-existing integration tests (install.test.ts, submission-lifecycle.test.ts, project-scope.test.ts, action-access.test.ts, project-database.test.ts) run `docker exec postgres psql ...`, i.e. CREATE/DROP DATABASE in the LIVE `postgres` container, whenever `PROJECT_DATABASE_URL` is set. So 03's command "`npx vitest run` with PROJECT_DATABASE_URL set to the throwaway DB" would write to the live server. I did not run them. Run only the files listed above, or switch those tests to throwawayDb.ts first.

Commit: controls `b4d9f01` "Tests first: answers carry the system version, dashboard reads controls, install once (WP10, WP11, S8.3)" (test/integration/throwawayDb.ts, answer-stamps.test.ts, dashboard-grants.test.ts, install-once-throwaway.test.ts, test/unit/systemVersion.test.ts).

### Manual checks (not automated)
- WP10 UI: the submission page shows "answered under vN" per answer, "not stamped" when NULL, and the distinct versions in its header. Manual: answer under v1, save v2, answer another, open the submission page and read the labels; open an old project DB's submission and see "not stamped".
- WP7 UI wording beyond the asserted strings (layout of the "Start assessment" button). Covered only by string checks.
- S8.3 "already installed" message on the install page: covered by the existing unit test test/unit/installPage.test.ts; the DB half is automated above.

Throwaway container `aisc-t-co-fa0cc9` (postgres:14-alpine) was removed at the end; none remains.

### Fork E: catalogue (WP8) and webapp (WP8, WP13)

| rule | file::test | repo | status |
|---|---|---|---|
| S8.4 | frontend/src/crossSite/wp8OneClickInstall.test.tsx::S8.4 opens <targetEnv>/receiver?project=<pid>&uri=<enable URI> for a uuid project | apps/catalogue | failing as expected (no project param) |
| S8.4 | ...wp8OneClickInstall.test.tsx::S8.4 drops a project that is not a uuid | apps/catalogue | already passing (project never sent today) |
| S8.4 | ...wp8OneClickInstall.test.tsx::S8.4 never opens a non-http(s) targetEnv, falls back to the custom protocol | apps/catalogue | failing as expected (opens javascript:... today) |
| S8.4 | ...wp8OneClickInstall.test.tsx::S8.4 rejects a scheme-relative targetEnv too | apps/catalogue | failing as expected |
| S8.4 | ...wp8OneClickInstall.test.tsx::S8.4 without a handshake still fires the custom protocol (already built) | apps/catalogue | already passing |
| S8.1 | ...wp8OneClickInstall.test.tsx::S8.1 a test entry offers 'Install into a project…' | apps/catalogue | failing as expected (label is "Enable plugin") |
| S8.1 | ...wp8OneClickInstall.test.tsx::S8.1 a control entry offers 'Install into a project…' (already built) | apps/catalogue | already passing |
| S8.1 | ...wp8OneClickInstall.test.tsx::S8.1 both buttons carry the same style | apps/catalogue | failing as expected |
| S8.1 | ...wp8OneClickInstall.test.tsx::S8.1 clicking install on a test opens one tab on the webapp receiver with the project | apps/catalogue | failing as expected |
| S8.1 | src/components/PluginInstallDialog.wp8.test.tsx::S8.1 loads the workspaces of the catalogue project (already built) | apps/webapp | already passing (proves the harness renders the open dialog) |
| S8.1 | ...PluginInstallDialog.wp8.test.tsx::S8.1 preselects the one workspace of the project | apps/webapp | failing as expected |
| S8.1 | ...PluginInstallDialog.wp8.test.tsx::S8.1 with no workspace yet, asks for the project row and preselects it | apps/webapp | failing as expected (no POST for-platform) |
| S8.1 | ...PluginInstallDialog.wp8.test.tsx::S8.1 one Install click posts the plugin for that workspace with the catalogue slug | apps/webapp | failing as expected (button disabled: no preselection) |
| S8.1 | ...PluginInstallDialog.wp8.test.tsx::S8.1 keeps the ?project= of /receiver before stripping the URL | apps/webapp | failing as expected (sessionStorage not set) |
| S8.2 | ...PluginInstallDialog.wp8.test.tsx::S8.2 says "Already installed in <name>" and offers "Open plugins" when the same version is there | apps/webapp | failing as expected |
| S8.2 | ...PluginInstallDialog.wp8.test.tsx::S8.2 a different version is not "already installed" | apps/webapp | failing as expected (depends on preselection) |
| S8.5 | ...PluginInstallDialog.wp8.test.tsx::S8.5 the engine's 403 reads 'Installing a test takes the admin role' | apps/webapp | failing as expected (fails first on preselection, then on the message) |
| S13.1 | src/wp13Undo.test.ts::S13.1 no file under src mentions "frozen" | apps/webapp | failing as expected (SystemVersionBanner.tsx + test) |
| S13.2 | src/wp13Undo.test.ts::S13.2 AISystemSettings.tsx is byte-identical to Sean's 429f62c | apps/webapp | failing as expected (e36fed4 hunk, 4+/2-) |
| S13.2 | src/wp13Undo.test.ts::S13.2 SystemVersionBanner is gone | apps/webapp | failing as expected |
| S13.3 | whole suite: `npx vitest run` + `npx tsc -b --noEmit` | apps/webapp | baseline recorded (see below) |

### Commands
- Catalogue: `cd apps/catalogue/frontend && npx vitest run` (no DB). Result now: 9 files, 61 tests, 6 failed (all in the new file), 55 passed. `npx tsc --noEmit`: 81 errors, all pre-existing (0 from the new file).
- Webapp: `cd apps/webapp && npx vitest run` (no DB). Result now: 9 files, 43 tests, 10 failed (all in the two new files), 33 passed. Baseline before the new files: 7 files, 33 passed. `npx tsc -b --noEmit`: 0 errors (also 0 with `-p tsconfig.app.json`).
- S13.3 check after WP13: vitest must show 0 failures with SystemVersionBanner.test.tsx deleted (baseline 33 minus that file's tests plus the 10 new ones passing), and tsc stays at 0.

### Commits (local, feat/unified-modules, not pushed)
- apps/catalogue `8496538` Tests first: one-click install carries the project, same button for tests and controls (S8.1, S8.4). File: frontend/src/crossSite/wp8OneClickInstall.test.tsx
- apps/webapp `363757e` Tests first: install dialog preselects the catalogue project, webapp undo of e36fed4 (S8.1, S8.2, S8.5, S13.1, S13.2). Files: src/components/PluginInstallDialog.wp8.test.tsx, src/wp13Undo.test.ts

### Notes for the implementer
- The existing ToolDetailModal.test.tsx test "offers the enable once the index has a version" looks for a link named "Enable plugin"; S8.1 renames it, so that existing test must be updated with the rename.
- `dispatchInstall` is called with a third argument through `as any` so the tests compile before the signature changes.
- No Sean file was touched.

### Not automatable here (manual checks)
- S8.1 end to end: from the launcher, open the catalogue for project P, click "Install into a project…" on a test: exactly one new tab opens on the webapp, P's workspace is preselected, one "Install" click gives an `engine.plugin` row with `catalogue_slug = <slug>` (check with a read-only SELECT). This covers real window opening and the backend write, which the unit tests only stub.
- S8.2 backend reuse (no second `engine.plugin` row) is the engine's `create_plugins` behaviour. The webapp test only covers the "Already installed" message. The row count belongs to the backend suite.
- S8.3 (controls) is outside this fork (controls repo).

### apps/results-dashboard (WP11), fork F

Repo: apps/results-dashboard, branch feat/unified-modules. Commit f8b84b2 "Tests first: per-project dashboard bridge, role sync and stamped datasets (WP11)" (3 new files only; the 6 uncommitted W4 files of others left untouched and unstaged).

Test contract chosen (taste call, the spec names the functions but not how to unit-test them without Superset, which is not installed in the venv): `aisc_ext/projects.py` exposes `register_project(pid, slug, name, *, store, controls_password)`, `unregister_project(pid, *, store)` over a small store (`upsert(kind, key, spec)`, `delete(kind, key)`, `items(kind)`; kinds database, dataset, role, dashboard; every spec tagged `aisc_project: <pid>`), plus `engine_results_sql(pid)`, `controls_answers_sql()`, `project_role_name(pid)`, `MEMBER_PROJECTS_SQL`, `authorize_bridge(headers, env) -> 401 | None`. `aisc_ext/security.py` gains `roles_for_login(realm_roles, member_project_pids)`. The Superset-backed store and the FAB BaseApi are runtime-only.

| rule | file::test | repo | status |
|---|---|---|---|
| 11a names | tests/test_projects.py::test_s11_names_are_derived_from_the_pid | results-dashboard | failing as expected (no aisc_ext.projects) |
| 11a | tests/test_projects.py::test_s11_project_role_name_helper | results-dashboard | failing as expected |
| S11.1 | tests/test_projects.py::test_s11_1_engine_dataset_is_on_the_results_connection_and_carries_the_version | results-dashboard | failing as expected |
| S11.1 | tests/test_projects.py::test_s11_1_controls_dataset_carries_the_answer_stamp | results-dashboard | failing as expected |
| S11.4 | tests/test_projects.py::test_s11_4_engine_dataset_filters_on_this_project_only | results-dashboard | failing as expected |
| S11.4 | tests/test_projects.py::test_s11_4_a_pid_that_is_not_a_uuid_never_reaches_the_sql (4 params) | results-dashboard | failing as expected |
| 11a | tests/test_projects.py::test_s11_controls_connection_reads_the_projects_own_database_as_dashboard_ro | results-dashboard | failing as expected |
| S11.3 | tests/test_projects.py::test_s11_3_the_project_role_reads_its_two_datasets_and_nothing_else | results-dashboard | failing as expected |
| S11.2 | tests/test_projects.py::test_s11_2_the_dashboard_is_for_the_project_role_and_has_both_charts | results-dashboard | failing as expected |
| S11.2/S11.3 | tests/test_projects.py::test_s11_2_dashboard_rbac_is_switched_on | results-dashboard | failing as expected (no DASHBOARD_RBAC flag in superset_config.py) |
| 11a idempotent | tests/test_projects.py::test_s11_register_is_idempotent | results-dashboard | failing as expected |
| 11a | tests/test_projects.py::test_s11_everything_registered_is_tagged_with_the_project | results-dashboard | failing as expected |
| S11.5 | tests/test_projects.py::test_s11_5_unregister_removes_every_object_of_the_project | results-dashboard | failing as expected |
| S11.5 | tests/test_projects.py::test_s11_5_unregister_leaves_other_projects_alone | results-dashboard | failing as expected |
| S11.5 | tests/test_projects.py::test_s11_5_unregister_of_an_unknown_project_is_a_no_op | results-dashboard | failing as expected |
| S11.6 | tests/test_project_bridge.py::test_s11_6_no_token_is_401 | results-dashboard | failing as expected |
| S11.6 | tests/test_project_bridge.py::test_s11_6_wrong_token_is_401 | results-dashboard | failing as expected |
| S11.6 | tests/test_project_bridge.py::test_s11_6_right_token_passes | results-dashboard | failing as expected |
| S11.6 | tests/test_project_bridge.py::test_s11_6_an_unconfigured_bridge_refuses_everyone | results-dashboard | failing as expected |
| S11.6 | tests/test_project_bridge.py::test_s11_6_the_comparison_is_constant_time | results-dashboard | failing as expected |
| S11.6 | tests/test_project_bridge.py::test_s11_6_bridge_api_resource_name | results-dashboard | failing as expected (no BaseApi with resource_name "aisc_project") |
| 11b, S11.2 | tests/test_project_bridge.py::test_s11_2_a_member_gets_the_project_role_on_top_of_the_realm_role | results-dashboard | failing as expected (no roles_for_login) |
| 11b, S11.3 | tests/test_project_bridge.py::test_s11_3_a_non_member_gets_no_project_role | results-dashboard | failing as expected |
| 11b | tests/test_project_bridge.py::test_s11_2_one_role_per_project_membership | results-dashboard | failing as expected |
| 11b | tests/test_project_bridge.py::test_s11_2_the_admin_keeps_admin | results-dashboard | failing as expected |
| 11b | tests/test_project_bridge.py::test_s11_2_membership_is_read_from_core_project_member | results-dashboard | failing as expected |
| 11b | tests/test_project_bridge.py::test_s11_2_the_sso_manager_uses_the_membership | results-dashboard | failing as expected |
| S11.1 (DB) | tests/test_project_datasets_db.py::test_s11_1_engine_results_carries_the_evaluations_version | results-dashboard | failing as expected (core.system.number missing: WP2) |
| S11.4 (DB) | tests/test_project_datasets_db.py::test_s11_4_engine_results_never_returns_another_projects_rows | results-dashboard | failing as expected (WP2) |
| S11.1 (DB) | tests/test_project_datasets_db.py::test_s11_1_controls_answers_carries_the_answers_version | results-dashboard | failing as expected (submission_answer stamp columns missing: WP10) |
| D5 (DB) | tests/test_project_datasets_db.py::test_s11_dashboard_ro_may_connect_to_the_project_database | results-dashboard | failing as expected (WP10 columns; then 0002_dashboard.sql CONNECT/USAGE) |
| D5 (DB) | tests/test_project_datasets_db.py::test_s11_dashboard_ro_reads_but_never_writes_controls | results-dashboard | failing as expected (then the controls SELECT-grant migration) |
| 11b (DB) | tests/test_project_datasets_db.py::test_s11_2_member_projects_sql_as_dashboard_ro | results-dashboard | failing as expected (WP2 seed, then MEMBER_PROJECTS_SQL) |
| S11.7 | existing suite | results-dashboard | baseline 74 passed (includes the untracked tests/test_review.py of W4); now 74 passed, 30 failed (new), 6 skipped (DB tests without the env var) |

Commands:
- Unit (no DB): `cd apps/results-dashboard && PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py` (the DB tests skip).
- With the throwaway DB (the venv has no Postgres driver, so the tests run SQL via `docker exec psql` in the container, over its local socket, as the named role; they refuse any container not named `aisc-t-*`):
```
NAME=aisc-t-dash-$(openssl rand -hex 4); PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
trap "docker rm -f $NAME" EXIT
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user -e POSTGRES_PASSWORD=$(openssl rand -hex 12) -e POSTGRES_DB=platform postgres:14-alpine
until docker exec $NAME psql -U aisc-postgres-user -d platform -c 'select 1' >/dev/null 2>&1; do sleep 1; done
AISC_DASHBOARD_TEST_PG_CONTAINER=$NAME PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py
```
The DB fixture applies init/platform-db.sql, init/project-databases.sql, every platform/migrations/*.sql (as platform_rw), a reduced copy of the frozen engine tables (as engine_rw), creates project_<hex> owned by platform_rw, applies platform/project-template/*.sql and every apps/controls/prisma/migrations/*/migration.sql (as controls_rw), then seeds. Verified: container removed afterwards, none left.

Finding for stage 5: the spec's dataset SQL says `WHERE p.platform_project_id = '<pid>'`, but `engine.project`'s column is `project_id` (Django `db_column="project_id"`, attribute `platform_project_id`). The SQL must use `p.project_id`; the DB tests use the real column name and will catch it.

Not automatable here (manual):
- S11.2 in a live Superset: sign in as a member of P, open /superset/dashboard/aisc-<hex>/, see the line and table charts, post a chart comment (POST /api/v1/aisc_comment/ returns 201).
- S11.3 in a live Superset: sign in as a non-member, open the same dashboard (403/404), and POST /api/v1/chart/data for either dataset (403, no rows).
- S11.5 end to end: DELETE /projects/<slug> on the platform, then check in Superset that the two datasets, the "AISC Controls <slug>" connection, the role and the dashboard are gone.
- S11.7 `scripts/verify_review.py` and tests/test_review.py belong to the other session's uncommitted W4 work (11c); not run or modified here. They count inside the 74 baseline.
