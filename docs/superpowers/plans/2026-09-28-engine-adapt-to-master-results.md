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

pending (Task 6b)

## Fresh stack

pending (Task 6b)

## End to end

pending (Task 6b)

## Standalone

pending (Task 6b)
