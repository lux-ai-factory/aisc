# Engine adapted to Sean's master: results

Plan: `docs/superpowers/plans/2026-09-28-engine-adapt-to-master.md`, Task 6. Superproject branch
`definitive/2026-09-27`; engine worktrees `/home/listuser/engine-modes/apps/{backend,eval,webapp}`,
branch `feat/deployment-modes` (backend a73695c, eval 0302352, webapp 0bc2844).

## Left of the diff to master

Test files are left out (`':!*test*'`). Every file not named below as Sean's is one we added.
The guard checks the same thing file by file: `scripts/guard-frozen.sh` G4 against
`scripts/guard-frozen-intended.txt`, and G1 for the schema (Sean's master plus a written list of
additions).

### backend

`git diff --stat origin/master HEAD -- . ':!*test*'` at backend `a73695c`, origin/master `1b1efe9`:

```
 aisc_backend/apps.py                                            |  55 ++++
 aisc_backend/auth/membership.py                                 | 173 ++++++++++++
 aisc_backend/deployment.py                                      | 130 +++++++++
 aisc_backend/management/__init__.py                             |   0
 aisc_backend/management/commands/__init__.py                    |   0
 aisc_backend/management/commands/migrate_projects.py            | 146 ++++++++++
 aisc_backend/migrations/0015_plugin_catalogue_slug.py           |  18 ++
 .../0016_evaluation_system_id_project_platform_project_id.py    |  66 +++++
 .../migrations/0017_one_project_per_platform_project.py         |  29 ++
 .../migrations/0018_alter_project_platform_project_id.py        |  27 ++
 aisc_backend/migrations/0019_no_login_of_its_own.py             |  51 ++++
 aisc_backend/migrations/0020_the_database_is_the_project.py     |  44 +++
 aisc_backend/migrations/0021_engine_deployment_marker.py        |  39 +++
 aisc_backend/models/evaluation.py                               |   6 +
 aisc_backend/models/plugin.py                                   |   8 +
 aisc_backend/models/project.py                                  |  26 ++
 aisc_backend/platform_projects.py                               |  53 ++++
 aisc_backend/project_door.py                                    | 402 ++++++++++++++++++++++++++++
 aisc_backend/projectdb.py                                       | 270 +++++++++++++++++++
 aisc_backend/repositories/measurement_repository.py             |   6 +-
 aisc_backend/repositories/project_repository.py                 |   3 +-
 aisc_backend/repositories/system_version_repository.py          |  50 ++++
 aisc_backend/routers/platform_project.py                        |  48 ++++
 aisc_backend/routers/plugin.py                                  |  11 +
 aisc_backend/schemas/plugin.py                                  |   3 +-
 aisc_backend/services/celery_service.py                         |  37 ++-
 aisc_backend/signals/__init__.py                                |   1 +
 aisc_backend/signals/system_stamp.py                            |  22 ++
 config/settings.py                                              |  39 +++
 config/urls.py                                                  |  21 +-
 30 files changed, 1774 insertions(+), 10 deletions(-)
```

Sean's files still modified, and why:

- `aisc_backend/apps.py`: the database-mode check at start (a database of the other mode is refused) and, in configurator, the stamp signal loaded.
- `aisc_backend/models/evaluation.py`: `system_id`, the AI system version an evaluation ran against (nullable).
- `aisc_backend/models/plugin.py`: `catalogue_slug`, the catalogue entry a plugin was installed from (nullable).
- `aisc_backend/models/project.py`: `platform_project_id` (column `project_id`, nullable) and the constraint `one_project_per_platform_project`.
- `aisc_backend/repositories/measurement_repository.py`: asks the vendor of the queryset's own database, not `default` (a dummy backend when every project has its own database).
- `aisc_backend/repositories/project_repository.py`: `create()` takes an optional `platform_project_id`.
- `aisc_backend/routers/plugin.py`: records `catalogue_slug` on install. The only router of Sean's still modified (the membership and admin checks moved into the door).
- `aisc_backend/schemas/plugin.py`: the optional `catalogue_slug` field of the install schema.
- `aisc_backend/services/celery_service.py`: Sean's `run_evaluation(evaluation_pid)` in both modes; configurator adds the run (project, evaluation, ticket) in the Celery message headers.
- `config/settings.py`: reads the mode; in configurator, the door middleware, one database per project, and no login apps (0019 dropped their tables).
- `config/urls.py`: the admin and allauth routes standalone only; the platform project router in configurator only.

### eval

`git diff --stat origin/master HEAD -- . ':!*test*'` at eval `0302352`, origin/master `511432b`:

```
 aisc_eval/celery_app.py         |  4 ++--
 aisc_eval/celery_tasks.py       | 37 ++++++++++++++++++++++++++-----------
 aisc_eval/deployment.py         | 48 ++++++++++++++++++++++++++++++++++++++++++++++++
 aisc_eval/run_context.py        | 38 ++++++++++++++++++++++++++++++++++++++
 aisc_eval/service/api_client.py | 55 +++++++++++++++++++++++++++++++++++++------------------
 5 files changed, 151 insertions(+), 31 deletions(-)
```

Sean's files still modified, and why:

- `aisc_eval/celery_app.py`: Méril's `feat/dev-catalogue-staging` (Celery task limits of 400/405 minutes for long first plugin runs); identical to his branch.
- `aisc_eval/celery_tasks.py`: Méril's `feat/dev-catalogue-staging` (online install from the index, the index always passed, a placeholder `API_KEY_OPENAI`) plus one import line (`from aisc_eval import run_context`, which registers the run header handlers). Checked: `git diff origin/feat/dev-catalogue-staging HEAD -- aisc_eval/celery_tasks.py` is that one line.
- `aisc_eval/service/api_client.py`: `headers()` read at call time; in configurator the door's project, evaluation and run headers, from the run context.

### webapp

`git diff --stat origin/master HEAD -- . ':!*test*'` at webapp `0bc2844`, origin/master `ab9f19d`:

```
 .env                                         |   2 +
 .env.development                             |   2 +
 Dockerfile                                   |   5 +
 src/DeploymentGate.tsx                       |  26 +++++
 src/MyApp.tsx                                |   4 +-
 src/api/installProjectHeader.ts              |  14 +++
 src/api/projectHeader.ts                     | 137 +++++++++++++++++++++++++
 src/components/LeftBar.tsx                   |   4 +-
 src/components/PluginInstallDialog.tsx       | 255 ++++++++++++++++++++++++++++++++++++++++++++++-
 src/components/TopBar.tsx                    |  54 +++++++---
 src/context/AuthContext.tsx                  |  31 +++++-
 src/deployment.ts                            |  30 ++++++
 src/main.tsx                                 |   8 ++
 src/pages/GlobalHome.tsx                     | 110 ++++++++++++++++++--
 src/pages/Plugins.tsx                        |  46 +++++++--
 src/platform/currentProject.ts               | 131 ++++++++++++++++++++++++
 src/platform/gatewaySession.ts               |  43 ++++++++
 src/pluginCatalogue/PluginInstallContext.tsx |  14 ++-
 src/pluginCatalogue/installUri.ts            |  30 ++++++
 19 files changed, 906 insertions(+), 40 deletions(-)
```

Sean's files still modified, and why:

- The six with gated logic, as planned:
  - `src/MyApp.tsx`: the Tasks route standalone only.
  - `src/components/LeftBar.tsx`: the Tasks link standalone only.
  - `src/components/TopBar.tsx`: the launcher's project in configurator, Sean's wizard standalone.
  - `src/components/PluginInstallDialog.tsx`: installs into the project you came from (configurator), Sean's list standalone.
  - `src/pages/GlobalHome.tsx`: the launcher's project in configurator (none without one), Sean's list of every project standalone.
  - `src/pages/Plugins.tsx`: in configurator the catalogue is the only place tests are found, Sean's package index standalone.
- Beyond the six (these differ from the plan's expectation, see the note below):
  - `src/main.tsx`: `DeploymentGate` around the app, and the project-header wrapper installed before render in configurator (Task 5 made this change on purpose).
  - `src/context/AuthContext.tsx`: the gateway's session in configurator, Sean's Keycloak login standalone.
  - `src/pluginCatalogue/PluginInstallContext.tsx`: in configurator, reads the platform project a catalogue link names before the URL is stripped.
  - `src/pluginCatalogue/installUri.ts`: `catalogueSlugOf()`, the catalogue entry of an install link (feeds `catalogue_slug`).
  - `.env`, `.env.development`: the `VITE_DEPLOYMENT` and `VITE_LAUNCHER_URL` placeholders and development values.
  - `Dockerfile`: `ENV APP_DEPLOYMENT=standalone` by default.

Note on the expectation. The backend and eval match it: no router of Sean's except `plugin.py`
(`catalogue_slug`), and `celery_tasks.py` differs from master only by Méril's commits plus one
import line. The web app has the six gated files and seven more of Sean's files, listed above:
`main.tsx` (changed by Task 5 on purpose), three source files with gated logic of their own
(`AuthContext.tsx`, `PluginInstallContext.tsx`, `installUri.ts`), and three build files
(`.env`, `.env.development`, `Dockerfile`). The plan's "six" counts only the files Task 5
touched for `fetch`/`axios`. Whether the other seven stay is a decision for the pull request note.

## Suites

Task 6 step 1, run by the controller at backend `a73695c`, eval `0302352`, webapp `0bc2844`,
superproject `6341485`, against the Task 0 baselines (`~/engine-modes/baseline-adapt-*`):

| Suite | Command (short) | Baseline (Task 0) | Task 6 | New failures |
|---|---|---|---|---|
| backend, sqlite, standalone | `manage.py test aisc_backend` | 242 ran, 3 failed, 4 errors, 121 skipped | 256 ran, the same 7 failing ids | 0 |
| backend, sqlite, configurator | same, `AISC_DEPLOYMENT=configurator` | 242 ran, 3 failed, 4 errors, 49 skipped | 256 ran, the same 7 failing ids | 0 |
| backend, Postgres 15 (throwaway) | `test_isolation_engine_db`, `test_isolation_result_route` | (new in this plan) | 34 OK | 0 |
| eval, standalone | `pytest tests/test_deployment_mode.py tests/test_run_ticket.py tests/test_run_context.py` | 9 passed, 8 skipped | 16 passed, 8 skipped | 0 |
| eval, configurator | same, `AISC_DEPLOYMENT=configurator` | (new) | 19 passed, 5 skipped | 0 |
| webapp | `npx vitest run`; `npx tsc --noEmit -p tsconfig.app.json` | 75/75 | 81/81; type check clean | 0 |
| results-dashboard | `pytest --continue-on-collection-errors` | 130 passed, 10 skipped, 1 collection error (test_sso_login needs Superset) | the same | 0 |
| report renderer | `pytest -q` on the isolated bed | 642 passed | 673 passed (after Task 6d, `dev` at `ceb8eb5`) | 0 |
| scripts/tests | `pytest scripts/tests` | 461 passed, 50 failed | 475 passed, 47 failed | 0 (3 fixed: G1 x2, `test_final_guard_frozen_passes`) |

The 47 remaining scripts/tests failures and the 7 backend ids are the baseline's, none of them new.
The counts after the final fix wave are in `.superpowers/sdd/2026-09-28-engine-adapt-to-master/final-fix-report.md`.

## Fresh stack

- A fresh clone, `~/aisc-adapt`, of superproject `9b7473d` with the local submodules and the report
  renderer at `be70243`, built with `build --pull --no-cache` as compose project `aisc-adapt` on new
  volumes. The old `aisc` stack was stopped with its volumes kept (10 volumes, for the user to decide).
- Every container came up. The project Proof (`728ae880-58ee-44ef-8139-664b804de937`) was made through
  the platform API as `user`.
- `scripts/verify.sh --stack` gave only expected differences: I16.5 (known), verify-rbac's audit
  answer 403 -> 401 (adapt item 3, Sean's 401), verify-sso's bundle grep (Sean's standalone Keycloak
  client is in the one bundle, unconfigured in configurator), and report_composer not migrated for a
  project made after its one-shot (existing lazy behaviour; after rerunning `report-composer-migrate`,
  verify-project-databases reported I16.5 only).
- Task 6c fixed the two verify expectations (`11d161e`); on the fresh stack verify-sso then gave
  60 passed, 0 failed, and verify-rbac 40 passed, 0 failed.
- Later the stack took `9926037` (secrets.sh added only `DASHBOARD_BRIDGE_TOKEN`, every existing value
  unchanged, file mode 600; report renderer rebuilt; platform and dashboard recreated) and
  results-dashboard `14b1fb1` (dashboard recreated).

## End to end

Evidence: `.superpowers/sdd/2026-09-28-engine-adapt-to-master/task-6b-e2e-report.md`. Calls were made
from inside the network with `X-AISC-Project` of Proof and Keycloak tokens that were never printed or
kept on disk.

1. **Engine row, plugin install, project plugins: proven.** `POST /projects/for-platform/<Proof>` as
   `user` made the engine project; `POST /plugins` as `admin` installed `data-monitor 0.3.1` (two
   plugins, enabled; `catalogue_slug` null because the call was direct); two dataset components made.
2. **Evaluation: proven.** After the host disk was freed (the first attempt stopped on MinIO's full
   disk), both uploads answered 200, the plugin config was saved, and evaluation `c5d2385d` ran to
   Done with 11 measurements.
3. **Door and run headers: proven.** The worker's 11 internal calls for that evaluation all answered
   200 or 201, with no 400, 401 or 403, through the chain run_evaluation -> install_package ->
   run_plugin -> post_measurements -> finalize_evaluation; each task carried the `aisc_run` header
   naming the platform pid and the evaluation.
4. **Project database under Sean's table names: proven.** In `project_728ae880...`:
   `engine.aisc_backend_*` hold 1 evaluation, 11 measurements, 1 observation, 8 metrics, 2 plugins and
   2 components.
5. **Dashboard and report: proven after fixes.** A second run, evaluation `675767d8`, was stamped with
   card version 1. The composer made a layout and report `7e166004` (status done); its PDF (23,447
   bytes) names the evaluation and lists the metric rows. Through the gateway, as the project's
   member, the dashboard's chart data returned the metric rows of both evaluations (8 rows first, 16
   after the second run), and the project dashboard is listed and opens (200).

Defects found on the way:

| Id | What | Status |
|---|---|---|
| D1 | The renderer built from report-generator `dev`, which lacked isolation/2026-09-25 and read `core.system`: every report call failed | fixed: isolation merged into `dev` locally (`ceb8eb5`, Task 6d, Ruling 11); not on GitHub yet |
| D2 | `DASHBOARD_BRIDGE_TOKEN` never generated, so the dashboard bridge refused every project (401) | fixed: secrets.sh generates it and adds missing secrets to an existing env.secrets; compose requires it (`9926037`, Ruling 12) |
| D3 | The per-project dashboard was created unpublished with no owners, so its member saw none | fixed: published on creation and re-registration (results-dashboard `14b1fb1`..`24a5d6d`, Ruling 13); proven for the member, a non-member not tried live |
| D4 | The controls-answers dataset has 0 columns in Superset, so the controls chart errors | open, pre-existing, controls side (Ruling 14), for the user |
| F1 | The eval worker's DEBUG log printed the run ticket | fixed in the final fix wave: the development compose runs the worker at `--loglevel=info` |
| F2 | `GET /api/v1/evaluations/<pid>` without `?include=` answers 500 (SynchronousOnlyOperation) | open, Sean's master code, to report upstream; the web app always passes `include` |
| F3 | The bridge's charts are saved without `query_context`, so the chart data GET route answers 400 | open, pre-existing, dashboard side (Ruling 14); the UI is unaffected |
| F4 | No supported re-register of an existing project short of a platform restart | open, pre-existing (Ruling 14) |

## Standalone

Run as compose project `aisc-standalone` (the web app on 18080 through a scratchpad override, since
8080 was taken), then stopped with its volumes kept.

Proven:

- The backend migrates Sean's chain, auth tables included; the database holds `aisc_backend_*`,
  `auth_user` and `engine_deployment`.
- With a bearer (Sean's `HttpBearer` wants the header even with `AUTH_ENABLED=False`, as on master):
  `GET /projects` 200 `[]`, `POST /projects` made a project, `POST /plugins` enabled data-monitor from
  Sean's local list, and `for-platform` answers 404 (not mounted).
- The Celery message equals master's, by unit test (`test_celery_dispatch.py`) and by code
  (`celery_service.py`).

Not proven:

- **No evaluation ran in standalone**: no standalone run crossed the worker.
- **No Keycloak** in the standalone compose, so its web app cannot sign in (a design decision for the
  user: add a realm, or document the bearer-only use).
- **devpi-standalone** exits on a fresh volume (root login 401), so the worker could not install a
  plugin there; see the final fix report, item 16.
