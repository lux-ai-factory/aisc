# Stage 4, WP E2: engine part 2 (the door, the run ticket, the worker, the SPA header)

Date: 2026-09-25. Worktrees `~/aisc-isolation/apps/{backend,eval,webapp}`, branch `isolation/2026-09-25`. Nothing
pushed. Every database run used one throwaway `postgres:14-alpine` (`aisc-t-iso-E2-*`, random port, never 5432,
new-layout recipe), with credentials only in the E2 scratchpad folder. Each run script checked the port against the
container before it started. The container was removed afterwards, and `docker ps -a --filter name=aisc-t-` is
empty. `PLATFORM_TEST_DATABASE_URL` was always set. No compose, env, guard or throwaway-pg file was edited (G1, G2),
the `aisc` stack was not touched, and the webapp `node_modules` link was not modified.

## Commits

| repo | commit | content |
|---|---|---|
| apps/backend | `10005c9` | `Isolation test correction T6`: the `CONTROLS` row reads `/api/v1/evaluations/{evaluation_pid}/plugins/status` |
| apps/backend | `6e31f06` | new `aisc_backend/tests/test_isolation_result_route.py` (open issue 7, see below) |
| apps/backend | `18e670c` | `aisc_backend/project_door.py` (new), `aisc_backend/projectdb.py` (`run_ticket`, `ticket_is_valid`), `aisc_backend/services/celery_service.py`, `config/settings.py` (middleware, `CORS_ALLOW_HEADERS`) |
| apps/eval | `e0d6d42` | `aisc_eval/service/api_client.py` (`Run`, `acting_for`, `headers()`), `aisc_eval/celery_tasks.py` (new signatures) |
| apps/webapp | `77b4346` | `Isolation test correction T7`: one tagged `sessionStorage` line in each of Sean's two tests |
| apps/webapp | `a6e46dd` | `src/api/projectHeader.ts` (new), `apiFetch(` in the 22 `fetch(` callers, `apiAxios.put` in `UploadFileField.tsx`, launcher link in `GlobalHome` |
| top-level | (this commit) | these notes, the PROGRESS line, the gitlinks `apps/backend apps/eval apps/webapp` (the backend gitlink also picks up the orchestrator's T8 commit `c2a9eeb`) |

## What was built

- **The door** (`ProjectDoor`, async only, right after `CorsMiddleware`). It follows the plan's order table exactly
  (400, 404, then the worker's 401/403 or the person's 401/503/404/403, then `alias_for`, then the core.project check
  (404/503), then `open_alias` (404/503), then admission and the same-project checks (404), then the view).
  `keycloak.AUTH_ENABLED`, `keycloak.verify_token`, `membership.role_in_project`, `projectdb.alias_for` and
  `platform_projects.platform_project_exists` are read off their modules at call time. The `finally` block resets
  both ContextVars. It also closes the project alias and `platform` in `sync_to_async` (thread-sensitive, which is
  the thread the view used). Refusals are `{"detail": ...}`. The door names nothing in `core`.
- **Same-project checks**: every check in the plan's list. The JSON bodies of `/plugins` (POST, DELETE),
  `/plugins/refresh` and `/evaluations/task` are checked before the view. The door parses only those JSON routes and
  never parses multipart. A body that does not parse falls through to the view's 422.
- **Ticket**: `projectdb.run_ticket(p, e)` is the hex HMAC-SHA256 of `normalise(p).normalise(e)` with `SECRET_KEY`.
  `ticket_is_valid` uses `compare_digest`. `X-Internal-Secret` is compared with `compare_digest` against
  `os.environ["INTERNAL_API_KEY"]`, read at call time. When that variable is unset, every internal call is 401.
- **Dispatch**: `celery_service.run_evaluation(evaluation_uuid)` keeps its signature. It takes the platform pid from
  `admitted_pid`, or else from the evaluation's engine project (409 when that has none). It then sends
  `run_evaluation(platform_pid, evaluation_pid, ticket)`, all lower-case strings, with no DSN.
- **Worker**: every task body runs inside `api_client.acting_for(Run(...))`. `headers()` is built at call time and
  sends the secret, `X-AISC-Project`, `X-AISC-Run` and `X-AISC-Evaluation`. Every `.si`/`.s` carries `platform_pid`
  and `ticket`. `env.py`, `celery_app.py` and `env.development` are untouched, and the worker never reads
  `DJANGO_SECRET_KEY`.
- **SPA**: `projectHeader.ts` is the only module under `src/` that calls the network. `apiFetch` adds
  `X-AISC-Project` to every call, keeping the caller's headers in the same shape (record, `Headers` or array). With
  no valid current project, an API route that needs a project throws `NoCurrentProject` without calling `fetch`. The
  project-less routes still go out, and URLs outside the API pass through unchanged. `apiAxios` applies the same rule
  through an interceptor. With no project, `GlobalHome` shows a link to the launcher. `gatewaySession.ts` is unchanged.

## Open issue 7 (the live leak) is closed, and a test proves it

`GET /api/v1/plugins/{evaluation_plugin_pid}/evaluations/{evaluation_uuid}/result` (frozen `routers/plugin.py`,
byte-identical) makes no membership call. Two tests pin the fix:

- the `ROUTES` row of `test_isolation_engine_db.py`: A's run under B's header answers 404 (before E2 it answered 500
  after reading A's row);
- the new `test_isolation_result_route.py` (its own two-project world; the plugin loader is faked so a member gets
  200). The owner of A reads the result (200). mallory has a valid token and knows both uuids but is not in A: with no
  header she gets 400, with A's header 404 (stranger), with her own B's header 404 (A's rows are not in B's
  database). On the E1 tree it failed 4 of 4; after E2 it passes 4 of 4.

As an extra (beyond the plan's list), the door also requires that the evaluation named in that route's path exists in
the admitted database. The live stack stays exposed until cutover: the orchestrator should tell the user (plan
section 5, issue 7).

## Deviations

- **E2-D1** A new test file (`test_isolation_result_route.py`), as the dispatch asked for a test of the leak. It
  imports only helper functions (`_seed`, `_migrate_projects`, `SKIP_REASON`) from `test_isolation_engine_db.py`,
  never its test classes, and it cleans up its own cluster.
- **E2-D2** On one database (sqlite, `settings_single_database`) the door does not call `open_alias` (that would
  migrate `default`). It closes only `project_<hex>` aliases and `platform`, so Django TestCase transactions are left
  alone.
- **E2-D3** A `DatabaseError` out of `alias_for` answers 503. The plan does not say; `TheDoorOrder`'s spy raises one
  and checks only that the door opened.
- **E2-D4** `scripts/guard-frozen.sh` is not edited (plan override G2). The top-level commit holds only the gitlinks
  and these docs, and the G4 input for V1 is below.
- **E2-D5** These notes are in `04-E2-notes.md` (as the other WPs did), not in `04-code-notes.md`.

## Flags: tests I believe are wrong (not edited; the orchestrator decides)

Each was checked with a scratch probe (not committed) on the same throwaway, using the corrected call.

- **D-E2-1** `NothingOfAIsReachableUnderB.test_i16_5_the_same_reads_under_a_find_the_object` (row
  `/api/v1/evaluations/{evaluation_pid}`) and `test_i7_3_the_worker_reads_its_own_evaluation`. Without `?include=plugin`
  both routes answer 500 in the frozen code, and on the live stack too: `EvaluationDetailOutSchema` reads
  `get_evaluation_plugins`, and `evaluation_repository.get_including` (frozen) does not prefetch it, so the async view
  raises `SynchronousOnlyOperation`. The SPA and the worker always send `include`. Probe under A: user 500 without,
  200 with `?include=plugin`; worker 500 without, 200 with `?include=project,plugin` (what the worker sends).
  Correction: add those queries to the two paths.
- **D-E2-2** `test_i7_2_listings_under_b_hold_nothing_of_a` reads `e["pid"]`, but `EvaluationByStatusResponseSchema`
  answers `evaluation_pid`, so the test gets a KeyError. Probe: 200, one row, B's own evaluation present, A's absent.
  Correction: `e["evaluation_pid"]`.
- **D-E2-3** `isolation_support.ApiCaller.call`, multipart body with POST (row
  `POST /api/v1/internal/evaluations/{evaluation_pid}/artifacts`). It passes pre-encoded bytes with
  `content_type=MULTIPART_CONTENT`, and Django's client `post` then re-encodes them (`AttributeError: 'bytes' object
  has no attribute 'items'`). PUT is not affected. Probe with a proper multipart POST under B: 404. Correction: for
  POST, pass the field dict (with the file) and no `content_type`.
- **D-E2-4** `apps/webapp/src/wp13Undo.test.ts` "S13.2 AISystemSettings.tsx is byte-identical to Sean's 429f62c" is
  now red. The plan's swap list includes `AISystemSettings.tsx`, and the plan did not list this test (only T7). Leaving
  the file on raw `fetch(` would break I7.4 and the one-network-module scan. Correction (the same idea as T7 and G4):
  compare after `apiFetch(` -> `fetch(`, dropping the one `projectHeader` import line and lines tagged
  `// I7.4 (isolation)`. After that normalisation, all 7 of Sean's files and his 2 tests match 429f62c byte for byte
  (checked).

## Counts

| suite | before | after |
|---|---|---|
| backend sqlite (`manage.py test aisc_backend`) | 203 ran, 29 failures, 5 errors, 46 skipped | 207 ran, 2 failures, 5 errors, 50 skipped (the 4 new DB tests skip); nothing newly red |
| `test_isolation_engine.py` | 35 ran: `TheDoorOrder` 15 of 17 rows, `TheWorkersTicket` 8, the plugin-install exemption and the start route red | 35 ran, OK |
| backend Postgres pre-existing suite (superuser, `config.settings_single_database`) | 207 ran, 27 failures, 5 errors, 51 skipped (E1 tree in a git-less copy) | 207 ran, 2 failures, 5 errors, 47 skipped; the 2 are the known `test_g4` subtests (they skip in the git-less copy); nothing newly red |
| `test_isolation_engine_db.py` (engine_rw, deployed settings) | 28 ran: 18 passed, 10 red (84 subtest failures, 1 error) | 28 ran: 24 passed, 4 red, all flagged D-E2-1..3 (`ROUTES` 67 of 68 rows 404; `TheDoorOnPostgres` 4, `ADroppedDatabase` 2, I7.5 green) |
| `test_isolation_result_route.py` | 4 failed | 4 passed |
| eval (`pytest --noconftest tests --ignore=tests/test_basic_integration.py`) | 6 passed, 10 failed, 1 error | 15 passed, 1 failed, 1 error (both known: `test_build_project_settings_excludes_secrets`, `test_get_evaluation` fixture) |
| webapp `npx vitest run` | 9 files, 47 tests: 42 passed, 5 failed (I7.4, 3 + 2) | 46 passed, 1 failed (D-E2-4) |
| webapp `npx tsc -b --noEmit` (and `-p tsconfig.app.json`) | clean | clean |
| `makemigrations --check` | clean | clean |
| `scripts/tests/test_guard_frozen.py` | 12 failed, 7 passed (E1) | 13 failed, 6 passed: the one added red is `test_g4_webapp_seans_files_identical_to_429f62c`, which V1's webapp rule turns green |
| `GUARD_SOURCE=worktree scripts/guard-frozen.sh --only G4` | FAIL | FAIL, as expected until V1: backend lists, webapp Sean's 9 files, `apps/eval has 2 commits after e5b1b0a` |

## For V1 (G2: G4 input)

- **Backend `backend_allowed`**: E1's list plus `aisc_backend/project_door.py` and
  `aisc_backend/services/celery_service.py`. `aisc_backend/projectdb.py` and `config/settings.py` were already on it.
  No `config/urls.py` or `routers/*.py` byte was changed by E1 or E2. The other names the guard prints now (`admin.py`,
  `0024`, `config/jwt.py`, `config/urls.py`, `routers/plugin.py`, `pyproject.toml`) were already different before
  isolation.
- **Webapp rule**: for each of Sean's 7 files, apply `sed 's/apiFetch(/fetch(/g'`, then delete the one import line.
  The line is exactly `import { apiFetch } from "./projectHeader";` in `src/api/api.tsx`,
  `import { apiFetch } from "../api/projectHeader";` in `src/components/AISystemSettings.tsx`, `src/pages/*.tsx`, and
  `import { apiFetch } from "../../api/projectHeader";` in `src/components/plugin/*.tsx` (always line 1, double
  quotes). Delete also any line ending `// I7.4 (isolation)` (the two tests). The result is byte-identical to 429f62c
  (verified). The same normalisation fixes D-E2-4 if the orchestrator agrees.
- **Eval rule**: the files changed between e5b1b0a and HEAD are exactly `aisc_eval/service/api_client.py`,
  `aisc_eval/celery_tasks.py` and `tests/test_run_ticket.py` (commits 7f7de02, e0d6d42).

## For X1 (cutover)

- The backend, the worker and the SPA must be deployed together. The old SPA sends no header, so every project route
  answers 400. The old worker's one-argument `run_evaluation` raises TypeError. A message queued in the old format
  fails, so the broker should be empty of runs at the switch (C2: no `Pending`/`Processing` evaluations, N8).
- `INTERNAL_API_KEY` must be set in the backend's environment (read at call time; unset means every internal call is
  401). The same variable must reach the worker. Tickets are minted and checked in the backend with its
  `DJANGO_SECRET_KEY`.
- The gateway and Caddy must pass `X-AISC-Project` through to the backend. CORS now allows `x-aisc-project`.
- An end-to-end check for C12: the result route of an evaluation of A, called by a non-member with A's header, answers
  404.

## For Z1

- Expected reds after E2, until the orchestrator decides: D-E2-1 (2 tests), D-E2-2, D-E2-3 (1 `ROUTES` subtest),
  D-E2-4. The guard tests `test_g4_webapp_*` and `test_g4_eval_*` stay red until V1 applies the rules above. The known
  backend reds are F5 ImportError, `test_g4` (2 subtests), `s1_aisystem` and three `project_config_router`. The known
  eval reds are 1 failure and 1 error.
- T6 and T7 are made. T5 (E1) and T8 (orchestrator) are already on the backend branch.
