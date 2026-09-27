# Engine deployment modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the execution engine (aisc-backend, aisc-eval, aisc-webapp) from Sean's `master` v1.3.0 and add the Sandbox Configurator's needs as a `configurator` deployment mode, so the same engine runs standalone (Sean) or inside the Configurator (us), and tests are installed through the hosted catalogue in both.

**Architecture:** One switch, `AISC_DEPLOYMENT`, read once per process into a small module per app (`aisc_backend/deployment.py`, `aisc_eval/deployment.py`, `src/deployment.ts`); every behaviour that differs asks that module, never the environment directly. Standalone is Sean's code as it is on `master`. Configurator is the code of our local branch `definitive/2026-09-27`, ported onto `master` and switched on by the mode. The data model is shared: our migrations are appended after Sean's.

**Tech Stack:** Django 5 + django-ninja (async), Celery, React 19 + Vite + MUI, vitest, Django test runner (sqlite and Postgres), docker compose.

**Spec:** `docs/superpowers/specs/2026-09-27-engine-deployment-modes.md` (read it first: its table is the contract for every task).

## Global Constraints

- Mode variable: `AISC_DEPLOYMENT`, values exactly `standalone` and `configurator`, default `standalone`.
- Web app: `VITE_DEPLOYMENT=APP_DEPLOYMENT` in `.env`, substituted by `env.sh` at container start.
- Branch in each engine repo: `feat/deployment-modes`, created from `origin/master` (Sean's v1.3.0). The Configurator source to port from is the local branch `definitive/2026-09-27` of the same repo (in `~/aisc-install/apps/<repo>`, worktree `~/aisc-definitive/apps/<repo>`).
- Nothing standalone does on `master` is removed or changed: every Sean test that passes on `master` passes on `feat/deployment-modes` in standalone mode.
- Sean's frozen files (`aisc_backend/tests/test_frozen_sean_files.py`, `src/wp13Undo.test.ts`) are no longer frozen against e34fca3/429f62c: their reference becomes `origin/master` in standalone mode. Change those guards in Task 1 and say so in the commit.
- Test-first for every behaviour: the failing test is committed with or before its code.
- Prose in docs and commits: no em dashes.
- The hosted catalogue (Méril's `feat/dev-catalogue-staging`) is not changed.
- Nothing is pushed by this plan; pushing needs the user's yes with the repo list.

## Review Focus

1. `AISC_DEPLOYMENT` misspelled or empty (`Configurator `, `config`, ``) must stop the process at start with a message naming the variable and the allowed values, never fall back silently. Test in Task 1 (backend), Task 6 (eval), Task 7 (web app shows a blocking error page).
2. A standalone database upgraded from Sean's `0014_ai_system_and_project_config_squashed` with real rows must keep every row through our appended migrations (table renames included). Test in Task 2 (upgrade test with seeded rows, counted before and after).
3. A database made in one mode opened in the other (configurator engine pointed at a standalone database, or the reverse) must refuse at start, not half-work. Test in Task 3 (the `engine_deployment` marker row).
4. A catalogue link whose `project` the caller is not a member of (or that no longer exists) must show "you are not in this project" in the dialog and install nothing. Test in Task 8.
5. In configurator mode an old web app or a hand-made request without `X-AISC-Project` must keep getting 400 from the door; in standalone the same request must work. Test in Task 4.

---

## File structure

Backend (`apps/backend`, branch from `origin/master`):
- Create `aisc_backend/deployment.py`: the mode, `is_configurator()`, `is_standalone()`, `check_environment()`.
- Modify `config/settings.py`: INSTALLED_APPS, MIDDLEWARE, DATABASES, DATABASE_ROUTERS chosen through `deployment`.
- Port from `definitive/2026-09-27` unchanged, loaded only in configurator: `aisc_backend/project_door.py`, `aisc_backend/projectdb.py`, `aisc_backend/auth/membership.py`, `aisc_backend/platform_projects.py`, `aisc_backend/management/commands/migrate_projects.py`, `aisc_backend/signals/system_stamp.py`, `aisc_backend/repositories/system_version_repository.py`, `config/settings_single_database.py`.
- Port shared (both modes): models and migrations (Task 2), `routers/*` with mode branches (Task 4).
- Tests: `aisc_backend/tests/test_deployment_mode.py` (new), `test_migration_history.py` (new), all of `definitive/2026-09-27`'s tests, run under the mode each belongs to.

Eval (`apps/eval`): create `aisc_eval/deployment.py`; modify `aisc_eval/service/api_client.py`, `aisc_eval/celery_tasks.py`; tests `tests/test_deployment_mode.py`, port `tests/test_run_ticket.py`.

Web app (`apps/webapp`): create `src/deployment.ts`; modify `.env`, `src/api/projectHeader.ts` (port), `src/platform/currentProject.ts` (port), `src/pages/GlobalHome.tsx`, `src/components/TopBar.tsx`, `src/components/LeftBar.tsx`, `src/components/PluginInstallDialog.tsx`, `src/MyApp.tsx`; keep Sean's `src/auth/keycloak.tsx`, `src/components/LoginDialog.*`, `src/pages/CeleryTasks.*`.

Superproject (`~/aisc-definitive`): `docker-compose.development.yml` (mode env), `Caddyfile` (platform project list route), `scripts/tests/test_compose.py`, `.gitmodules`/gitlinks, `docker-compose.engine-standalone.yml` (new), `README.md`.

---

### Task 0: Branches and baselines

**Files:** none changed; records only.

- [ ] **Step 1: Create the branches from Sean's master**

```bash
for r in backend eval webapp; do
  cd ~/aisc-install/apps/$r && git fetch origin && git worktree add ~/engine-modes/$r -b feat/deployment-modes origin/master
done
```

- [ ] **Step 2: Record Sean's own test results on master (the standalone baseline)**

```bash
cd ~/engine-modes/backend && uv sync --all-groups && DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/sean.db uv run python manage.py test aisc_backend 2>&1 | tail -3 > ~/engine-modes/baseline-backend.txt
cd ~/engine-modes/eval && uv sync --all-groups && uv run pytest -q 2>&1 | tail -1 > ~/engine-modes/baseline-eval.txt
cd ~/engine-modes/webapp && npm ci && npx vitest run 2>&1 | grep -E "Tests " > ~/engine-modes/baseline-webapp.txt
```

Expected: three files with counts. Every later task compares its standalone run against these.

- [ ] **Step 3: Record the configurator baseline** (the local branch as it runs today): the counts in `~/aisc-definitive` for the same three commands, into `~/engine-modes/baseline-configurator-*.txt`.

---

### Task 1: The mode, in the backend, refusing bad values

**Files:**
- Create: `aisc_backend/deployment.py`
- Modify: `config/settings.py` (read the mode first thing)
- Modify: `aisc_backend/tests/test_frozen_sean_files.py` (reference becomes `origin/master`)
- Test: `aisc_backend/tests/test_deployment_mode.py`

**Interfaces:**
- Produces: `deployment.STANDALONE = "standalone"`, `deployment.CONFIGURATOR = "configurator"`, `deployment.mode(env: Mapping[str, str] = os.environ) -> str`, `deployment.project_databases(env) -> bool`, `deployment.is_configurator() -> bool`, `deployment.is_standalone() -> bool`, `deployment.check_environment(env, testing=None) -> None` (raises `ImproperlyConfigured`), `settings.AISC_DEPLOYMENT: str`. The backend reaches the platform through its `platform` database alias (`DB_NAME`), not over HTTP: there is no `PLATFORM_URL` for the backend.

- [ ] **Step 1: Write the failing tests**

```python
# aisc_backend/tests/test_deployment_mode.py
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from aisc_backend import deployment


class TheMode(SimpleTestCase):
    def test_default_is_standalone(self):
        self.assertEqual(deployment.mode({}), deployment.STANDALONE)

    def test_the_two_values(self):
        self.assertEqual(deployment.mode({"AISC_DEPLOYMENT": "standalone"}), "standalone")
        self.assertEqual(deployment.mode({"AISC_DEPLOYMENT": "configurator"}), "configurator")

    def test_case_and_spaces_are_forgiven(self):
        self.assertEqual(deployment.mode({"AISC_DEPLOYMENT": " Configurator "}), "configurator")

    def test_anything_else_stops_the_process_naming_the_variable(self):
        for bad in ("config", "", "prod"):
            with self.assertRaisesRegex(ImproperlyConfigured, "AISC_DEPLOYMENT.*standalone.*configurator"):
                deployment.mode({"AISC_DEPLOYMENT": bad})

    def test_configurator_needs_postgres_for_its_project_databases(self):
        with self.assertRaisesRegex(ImproperlyConfigured, "DB_ENGINE.*postgresql"):
            deployment.check_environment({"AISC_DEPLOYMENT": "configurator",
                                          "DB_ENGINE": "django.db.backends.sqlite3"}, testing=False)
        deployment.check_environment({"AISC_DEPLOYMENT": "configurator",
                                      "DB_ENGINE": "django.db.backends.postgresql"}, testing=False)

    def test_the_test_runner_may_run_configurator_on_one_sqlite_database(self):
        deployment.check_environment({"AISC_DEPLOYMENT": "configurator",
                                      "DB_ENGINE": "django.db.backends.sqlite3"}, testing=True)

    def test_project_databases_only_in_configurator_on_postgres(self):
        pg = "django.db.backends.postgresql"
        self.assertFalse(deployment.project_databases({"DB_ENGINE": pg}))
        self.assertTrue(deployment.project_databases({"AISC_DEPLOYMENT": "configurator", "DB_ENGINE": pg}))
        self.assertFalse(deployment.project_databases({"AISC_DEPLOYMENT": "configurator",
                                                       "DB_ENGINE": "django.db.backends.sqlite3"}))
```

Note the empty string: `mode({"AISC_DEPLOYMENT": ""})` must raise (an empty variable is a mistake in a compose file, not a request for the default). Only an absent variable means standalone.

- [ ] **Step 2: Run it and see it fail**

Run: `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend.tests.test_deployment_mode`
Expected: FAIL, `ImportError: cannot import name 'deployment'`.

- [ ] **Step 3: Write the module**

```python
# aisc_backend/deployment.py
"""Where this engine runs: on its own, or inside the Sandbox Configurator.

One switch, AISC_DEPLOYMENT, read once. Every behaviour that differs between the two asks this
module (docs/superpowers/specs/2026-09-27-engine-deployment-modes.md has the list); nothing else
reads the variable.
"""
import os
from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured

STANDALONE = "standalone"
CONFIGURATOR = "configurator"
MODES = (STANDALONE, CONFIGURATOR)


def mode(env: Mapping[str, str] = os.environ) -> str:
    if "AISC_DEPLOYMENT" not in env:
        return STANDALONE
    value = env["AISC_DEPLOYMENT"].strip().lower()
    if value not in MODES:
        raise ImproperlyConfigured(
            f"AISC_DEPLOYMENT must be {STANDALONE} or {CONFIGURATOR}, not {env['AISC_DEPLOYMENT']!r}")
    return value


def _postgres(env: Mapping[str, str]) -> bool:
    return "postgresql" in env.get("DB_ENGINE", "django.db.backends.sqlite3")


def project_databases(env: Mapping[str, str] = os.environ) -> bool:
    """One database per project: the Configurator, on Postgres. Standalone is always one database."""
    return mode(env) == CONFIGURATOR and _postgres(env)


def check_environment(env: Mapping[str, str] = os.environ, testing: bool | None = None) -> None:
    """The Configurator makes a database per project, which takes Postgres. The test runner alone may
    run it on one sqlite database (the configurator unit tests do, as they did before the modes)."""
    if testing is None:
        import sys
        testing = sys.argv[1:2] == ["test"]
    if mode(env) == CONFIGURATOR and not _postgres(env) and not testing:
        raise ImproperlyConfigured(
            f"AISC_DEPLOYMENT is {CONFIGURATOR}: DB_ENGINE must be django.db.backends.postgresql "
            "(one database per project)")


def is_configurator() -> bool:
    from django.conf import settings
    return settings.AISC_DEPLOYMENT == CONFIGURATOR


def is_standalone() -> bool:
    return not is_configurator()
```

In `config/settings.py`, right after the imports:

```python
from aisc_backend import deployment

deployment.check_environment()
AISC_DEPLOYMENT = deployment.mode()
```

- [ ] **Step 4: Point the frozen-file guard at Sean's master**

In `aisc_backend/tests/test_frozen_sean_files.py`, replace the reference commit `e34fca3` by `origin/master` and skip the guard when `settings.AISC_DEPLOYMENT == "configurator"` (the configurator port changes those files on purpose). Commit message says so.

- [ ] **Step 5: Run the new tests and the whole standalone suite**

Run: `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend`
Expected: the new tests PASS; the rest equals `baseline-backend.txt`.

- [ ] **Step 6: Commit**

```bash
git add aisc_backend/deployment.py config/settings.py aisc_backend/tests/test_deployment_mode.py aisc_backend/tests/test_frozen_sean_files.py
git commit -m "Deployment mode: AISC_DEPLOYMENT (standalone by default, or configurator), checked at start"
```

---

### Task 2: One data model: our migrations after Sean's

**Files:**
- Modify: `aisc_backend/models/{ai_system,artifact,evaluation,measure,metric,observation,plugin,project,project_config}.py` (take the `definitive/2026-09-27` versions)
- Create: `aisc_backend/migrations/0015_plugin_catalogue_slug.py` to `0024_the_database_is_the_project.py` (ours, renumbered; see the table)
- Test: `aisc_backend/tests/test_migration_history.py`

**Interfaces:**
- Consumes: Task 1's `deployment`.
- Produces: the shared schema; migration `0023_no_login_of_its_own` whose operations run only in configurator.

Renumbering (ours on `definitive` → new name on this branch; each depends on the one before, the first on Sean's `0014_ai_system_and_project_config_squashed`):

| definitive | this branch |
|---|---|
| 0014_plugin_catalogue_slug | 0015_plugin_catalogue_slug |
| 0015_evaluation_system_id_project_platform_project_id | 0016_evaluation_system_id_project_platform_project_id |
| 0016_one_project_per_platform_project | 0017_one_project_per_platform_project |
| 0017_alter_project_platform_project_id | 0018_alter_project_platform_project_id |
| 0018_alter_artifact_table_alter_dataset_table_and_more | 0019_alter_artifact_table_alter_dataset_table_and_more |
| 0019_alter_derived_table_alter_direct_table | 0020_alter_derived_table_alter_direct_table |
| 0020_ai_system_and_project_config | (dropped: it is Sean's 0014 renamed) |
| 0021_ai_system_tables_lose_the_prefix | 0021_ai_system_tables_lose_the_prefix |
| 0022_parts_belong_to_a_version_of_the_one_system | 0022_parts_belong_to_a_version_of_the_one_system |
| 0023_one_system_per_project_again | (merged into 0022 if it only undoes part of it; else 0022b, see Step 3) |
| 0024_no_login_of_its_own | 0023_no_login_of_its_own (configurator only) |
| 0025_the_database_is_the_project | 0024_the_database_is_the_project |

- [ ] **Step 1: Write the failing tests**

```python
# aisc_backend/tests/test_migration_history.py
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

SEAN_LAST = ("aisc_backend", "0014_ai_system_and_project_config_squashed")


class OneHistory(TransactionTestCase):
    def test_the_graph_has_one_leaf_and_seans_0014_is_in_it(self):
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes("aisc_backend")
        self.assertEqual(len(leaves), 1, leaves)
        self.assertIn(SEAN_LAST, executor.loader.graph.forwards_plan(leaves[0]))

    def test_a_standalone_database_keeps_its_rows_through_our_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate([SEAN_LAST])
        old = executor.loader.project_state([SEAN_LAST]).apps
        Project = old.get_model("aisc_backend", "Project")
        Plugin = old.get_model("aisc_backend", "Plugin")
        project = Project.objects.create(name="MCAS-free example", status="Ready")
        Plugin.objects.create(project=project, package_name="aisc-plugin-langbite", version="0.1.1",
                              display_name="LangBiTe")
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes("aisc_backend"))
        new = executor.loader.project_state(executor.loader.graph.leaf_nodes("aisc_backend")).apps
        self.assertEqual(new.get_model("aisc_backend", "Project").objects.count(), 1)
        self.assertEqual(new.get_model("aisc_backend", "Plugin").objects.count(), 1)

    def test_standalone_keeps_the_login_tables(self):
        # the configurator-only table drop (0023) must not run here
        tables = connection.introspection.table_names()
        self.assertIn("auth_user", tables)
```

Before writing it, read Sean's `0014_ai_system_and_project_config_squashed` and use the exact required fields of `Project` and `Plugin` at that state in the two `create()` calls (on `master` today: `Project.name`, `Project.status`; `Plugin.package_name`, `version`, `display_name`, `project`; re-check them, the test must match the real state).

- [ ] **Step 2: Run it and see it fail**

Run: `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend.tests.test_migration_history`
Expected: FAIL (`auth_user` missing is fine for now; the graph test fails because our models are not yet there).

- [ ] **Step 3: Bring the models and migrations over**

```bash
cd ~/engine-modes/backend
git checkout definitive/2026-09-27 -- aisc_backend/models/
for pair in "0014_plugin_catalogue_slug:0015_plugin_catalogue_slug" \
            "0015_evaluation_system_id_project_platform_project_id:0016_evaluation_system_id_project_platform_project_id" \
            "0016_one_project_per_platform_project:0017_one_project_per_platform_project" \
            "0017_alter_project_platform_project_id:0018_alter_project_platform_project_id" \
            "0018_alter_artifact_table_alter_dataset_table_and_more:0019_alter_artifact_table_alter_dataset_table_and_more" \
            "0019_alter_derived_table_alter_direct_table:0020_alter_derived_table_alter_direct_table" \
            "0021_ai_system_tables_lose_the_prefix:0021_ai_system_tables_lose_the_prefix" \
            "0022_parts_belong_to_a_version_of_the_one_system:0022_parts_belong_to_a_version_of_the_one_system" \
            "0024_no_login_of_its_own:0023_no_login_of_its_own" \
            "0025_the_database_is_the_project:0024_the_database_is_the_project"; do
  src=${pair%%:*}; dst=${pair##*:}
  git show definitive/2026-09-27:aisc_backend/migrations/$src.py > aisc_backend/migrations/$dst.py
done
```

Then fix each file's `dependencies` to the previous new name (the first to Sean's `0014_ai_system_and_project_config_squashed`). For `0023_one_system_per_project_again` on `definitive`: read it together with `0022`; if it only reverses part of `0022`, fold the net effect into `0022` and drop it; otherwise add it as `0022b_one_system_per_project_again` after `0022`. Then run `uv run python manage.py makemigrations --check --dry-run` and expect "No changes detected".

- [ ] **Step 4: Make the login table drop configurator-only**

In `0023_no_login_of_its_own.py`, first line of `forwards`:

```python
    from aisc_backend import deployment
    if deployment.mode() != deployment.CONFIGURATOR:
        return  # standalone keeps Django's accounts, sessions and admin (Sean's login)
```

- [ ] **Step 5: Run the tests and the whole standalone suite**

Run: `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend`
Expected: `test_migration_history` PASSES; everything else equals `baseline-backend.txt` or is a test that pinned the old table names (list them and fix each to the new name, one line per test, in this commit).

- [ ] **Step 6: Commit**

```bash
git add aisc_backend/models aisc_backend/migrations aisc_backend/tests/test_migration_history.py
git commit -m "One data model for both modes: the Configurator's migrations appended after Sean's 0014"
```

---

### Task 3: Configurator machinery, loaded only in configurator

**Files:**
- Port unchanged from `definitive/2026-09-27`: `aisc_backend/project_door.py`, `aisc_backend/projectdb.py`, `aisc_backend/auth/membership.py`, `aisc_backend/platform_projects.py`, `aisc_backend/management/commands/migrate_projects.py`, `aisc_backend/signals/system_stamp.py`, `aisc_backend/signals/__init__.py`, `aisc_backend/repositories/system_version_repository.py`, `config/settings_single_database.py`, and their tests (`test_isolation_*.py`, `test_project_door*.py`, `test_membership*.py`).
- Modify: `config/settings.py` (the configurator block below), `aisc_backend/apps.py` (connect `system_stamp` only in configurator).
- Create: `aisc_backend/migrations/0025_engine_deployment_marker.py` (table `engine_deployment` with one row: the mode the database was made in).
- Test: `aisc_backend/tests/test_deployment_mode.py` (more cases).

**Interfaces:**
- Consumes: `deployment.is_configurator()`.
- Produces: in configurator, `MIDDLEWARE` contains `aisc_backend.project_door.ProjectDoor`, `DATABASE_ROUTERS == ["aisc_backend.projectdb.ProjectDatabaseRouter"]`, `INSTALLED_APPS` without `django.contrib.admin`, `allauth*`, `ninja_jwt*`; in standalone, `master`'s lists exactly. `deployment.assert_database_mode(connection)` raising `ImproperlyConfigured` on a mismatch.

- [ ] **Step 1: Write the failing tests**

```python
# append to aisc_backend/tests/test_deployment_mode.py
from django.test import TestCase, override_settings
from django.conf import settings


class WhatEachModeLoads(SimpleTestCase):
    def test_standalone_is_seans_stack(self):
        self.assertEqual(settings.AISC_DEPLOYMENT, "standalone")
        self.assertIn("django.contrib.admin", settings.INSTALLED_APPS)
        self.assertNotIn("aisc_backend.project_door.ProjectDoor", settings.MIDDLEWARE)
        self.assertEqual(settings.DATABASE_ROUTERS, [])


class TheDatabaseRemembersItsMode(TestCase):
    def test_a_database_made_standalone_refuses_a_configurator_engine(self):
        from django.db import connection
        with override_settings(AISC_DEPLOYMENT="configurator"):
            with self.assertRaisesRegex(ImproperlyConfigured, "made by a standalone engine"):
                deployment.assert_database_mode(connection)
```

And the configurator half as its own settings module test, run with `DJANGO_SETTINGS_MODULE=config.settings` and `AISC_DEPLOYMENT=configurator` on Postgres:

```python
# aisc_backend/tests/test_configurator_settings.py
import os, unittest
from django.conf import settings
from django.test import SimpleTestCase


@unittest.skipUnless(os.environ.get("AISC_DEPLOYMENT") == "configurator", "configurator run only")
class TheConfiguratorStack(SimpleTestCase):
    def test_door_router_and_no_login_of_its_own(self):
        self.assertIn("aisc_backend.project_door.ProjectDoor", settings.MIDDLEWARE)
        self.assertTrue(settings.DATABASE_ROUTERS)
        self.assertNotIn("django.contrib.admin", settings.INSTALLED_APPS)
        self.assertFalse([a for a in settings.INSTALLED_APPS if a.startswith(("allauth", "ninja_jwt"))])
```

- [ ] **Step 2: Run both and see them fail**

Run (standalone): `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend.tests.test_deployment_mode`
Run (configurator): the Postgres command of `docs/superpowers/isolation-2026-09-25/02-tests.md` row "backend isolation DB", with `AISC_DEPLOYMENT=configurator` added, on `aisc_backend.tests.test_configurator_settings`. The configurator unit tests on sqlite: the standalone command with `AISC_DEPLOYMENT=configurator` added.
Expected: FAIL (`assert_database_mode` missing; the configurator stack not wired).

- [ ] **Step 3: Port the files and wire the configurator block**

```bash
cd ~/engine-modes/backend
git checkout definitive/2026-09-27 -- aisc_backend/project_door.py aisc_backend/projectdb.py aisc_backend/auth/membership.py \
  aisc_backend/platform_projects.py aisc_backend/management aisc_backend/signals aisc_backend/repositories/system_version_repository.py \
  config/settings_single_database.py
git checkout definitive/2026-09-27 -- $(git ls-tree -r --name-only definitive/2026-09-27 aisc_backend/tests | grep -E "isolation|project_door|membership")
```

In `config/settings.py`, after `master`'s INSTALLED_APPS/MIDDLEWARE/DATABASES definitions:

```python
if AISC_DEPLOYMENT == deployment.CONFIGURATOR:
    # The Configurator owns projects and sign-in (spec table): no login of our own, one
    # database per project behind the door, memberships from the platform.
    INSTALLED_APPS = [a for a in INSTALLED_APPS
                      if a != "django.contrib.admin" and not a.startswith(("allauth", "ninja_jwt"))]
    MIDDLEWARE = [m for m in MIDDLEWARE if "allauth" not in m] + ["aisc_backend.project_door.ProjectDoor"]
    if deployment.project_databases():
        from aisc_backend.projectdb import configurator_databases  # the definitive branch's alias setup
        DATABASES, DATABASE_ROUTERS, PROJECT_DATABASE_TEMPLATE = configurator_databases(env)
```

`configurator_databases` is the block `definitive/2026-09-27`'s `config/settings.py` computes inline today under `if PROJECT_DATABASES:` (the `platform` alias, `PROJECT_DATABASE_TEMPLATE`, the router): move that block, unchanged, into a function in `projectdb.py` returning `(DATABASES, DATABASE_ROUTERS, PROJECT_DATABASE_TEMPLATE)`, and call it here. `PROJECT_DATABASES` in settings becomes `deployment.project_databases()` (it was `"postgresql" in DB_ENGINE`), so a standalone engine on Postgres stays one database. Also move the `urls.py` admin/allauth paths under `if deployment.is_standalone():`.

`deployment.assert_database_mode(connection)`: reads `engine_deployment.mode` (migration `0025_engine_deployment_marker` writes the current mode on first migrate), raises `ImproperlyConfigured(f"this database was made by a {made} engine; this engine is {now}")` when they differ; called from `aisc_backend/apps.py` `ready()` (skipped under `manage.py migrate` and tests that make their own databases).

- [ ] **Step 4: Run both suites**

Standalone command: all tests; expected equal to `baseline-backend.txt` plus the new ones passing; the isolation tests skip (they are `skipUnless(configurator)`: add that decorator where the ported files lack it).
Configurator command: all tests; expected equal to `baseline-configurator-backend.txt`.

- [ ] **Step 5: Commit**

```bash
git add -A aisc_backend config
git commit -m "Configurator mode: project databases, the door and platform memberships, loaded only there"
```

---

### Task 4: Routers, one behaviour per mode where the spec says so

**Files:**
- Modify: `aisc_backend/routers/{project,plugin,component,evaluation,file,internal,project_config,stats,task}.py`, `aisc_backend/auth/keycloak.py`, `aisc_backend/schemas/{plugin,project}.py`, `aisc_backend/services/celery_service.py`, `aisc_backend/repositories/*` (take `definitive/2026-09-27`'s changes, keeping `master`'s behaviour on the standalone side of each branch).
- Test: `aisc_backend/tests/test_modes_routes.py`

**Interfaces:**
- Consumes: `deployment.is_configurator()`, `membership.require(request, platform_project_id, role)`, `membership.for_project_pid(request, pid, role)`.
- Produces: `POST /api/v1/projects` creates in standalone and answers 403 `{"detail": "projects are made on the Configurator's launcher"}` in configurator; `GET /api/v1/projects` lists every project in standalone and only the door's project in configurator; `POST /api/v1/projects/for-platform/{pid}` exists only in configurator (404 in standalone).

Rule for every router change: where `definitive` added a membership check, write it as

```python
if deployment.is_configurator():
    await sync_to_async(membership.for_project_pid)(request, pid, "editor")
```

and leave `master`'s code as the standalone path. Where `definitive` changed behaviour that is not about projects or sign-in (the AI system versions, catalogue slug, plugin refresh), take it for both modes.

- [ ] **Step 1: Write the failing tests**

```python
# aisc_backend/tests/test_modes_routes.py
import os, unittest
from django.test import TestCase
from ninja.testing import TestAsyncClient

from aisc_backend.routers.project import router as projects_router

CONFIGURATOR = os.environ.get("AISC_DEPLOYMENT") == "configurator"


class StandaloneProjects(TestCase):
    @unittest.skipIf(CONFIGURATOR, "standalone run")
    async def test_a_project_is_made_in_the_engine_and_listed(self):
        client = TestAsyncClient(projects_router)
        made = await client.post("", json={"name": "Loans"})
        self.assertEqual(made.status_code, 200, made.content)
        listed = await client.get("")
        self.assertIn("Loans", [p["name"] for p in listed.json()])

    @unittest.skipIf(CONFIGURATOR, "standalone run")
    async def test_no_project_header_is_needed(self):
        response = await TestAsyncClient(projects_router).get("")
        self.assertEqual(response.status_code, 200)

    @unittest.skipIf(CONFIGURATOR, "standalone run")
    async def test_there_is_no_for_platform_route(self):
        response = await TestAsyncClient(projects_router).post("/for-platform/00000000-0000-0000-0000-000000000001")
        self.assertEqual(response.status_code, 404)


class ConfiguratorProjects(TestCase):
    @unittest.skipUnless(CONFIGURATOR, "configurator run")
    async def test_the_engine_does_not_make_projects(self):
        response = await TestAsyncClient(projects_router).post("", json={"name": "Loans"},
                                                               headers={"X-AISC-Project": "00000000-0000-0000-0000-000000000001"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("launcher", response.json()["detail"])
```

The door's 400 without the header (Review Focus 5) is already pinned by the ported `test_isolation_engine_db.py` `ROUTES` table; run it in configurator mode.

- [ ] **Step 2: Run in both modes and see the new tests fail**

Same two commands as Task 3, on `aisc_backend.tests.test_modes_routes`. Expected: FAIL.

- [ ] **Step 3: Port the router changes with mode branches**

For each router file: `git diff origin/master definitive/2026-09-27 -- <file>`, apply each hunk, and wrap the project/sign-in hunks as in the rule above. In `routers/project.py`, `create_project` becomes:

```python
@router.post("", response=ProjectOutSchema)
async def create_project(request, data: ProjectInSchema):
    if deployment.is_configurator():
        raise HttpError(403, "projects are made on the Configurator's launcher")
    project = await project_repository.create(data.name, None)
    await sync_to_async(log_action)(request, action="create", resource_type="project",
                                    resource_id=str(project.pid), metadata={"name": project.name})
    return project
```

and `for-platform` is registered only `if deployment.is_configurator():` at import. `auth/keycloak.py`: the gateway header (`X-Auth-Request-Access-Token`) is read only in configurator; the 401/403 change (valid token, missing role gives 403) applies to both.

- [ ] **Step 4: Run both full suites**

Expected: standalone equal to baseline plus new; configurator equal to `baseline-configurator-backend.txt` plus new.

- [ ] **Step 5: Commit**

```bash
git add -A aisc_backend
git commit -m "Routes by mode: the engine makes and lists its projects standalone, and follows the platform in the Configurator"
```

---

### Task 5: The first-visit AI system read (the reported 500)

**Files:**
- Modify: `aisc_backend/routers/project.py` (`get_project_aisystem`)
- Test: `aisc_backend/tests/test_one_system_per_project.py` (already red: `test_s1_aisystem_does_not_ask_the_platform`)

**Interfaces:** none new.

- [ ] **Step 1: Run the existing red test**

Run: standalone command on `aisc_backend.tests.test_one_system_per_project`
Expected: 1 error, `SynchronousOnlyOperation` in `response.components`.

- [ ] **Step 2: Fix: read the system with its components after making it**

```python
    def with_components():
        return (AISystem.objects.filter(project=project)
                .prefetch_related("components", "components__source_dataset")
                .afirst())

    system = await with_components()
    if system is None:
        await get_or_create_aisystem(project)
        system = await with_components()
    return system
```

- [ ] **Step 3: Run it in both modes**: PASS.

- [ ] **Step 4: Commit**

```bash
git commit -am "The AI system page on a project's first visit reads the new system with its components"
```

(This file is Sean's; the fix goes to him as part of the same PR.)

---

### Task 6: Eval worker by mode

**Files:**
- Create: `aisc_eval/deployment.py` (same contract as the backend's `mode()`/`check_environment()`, with its own copy: the worker does not import Django settings)
- Modify: `aisc_eval/service/api_client.py`, `aisc_eval/celery_tasks.py` (take `definitive/2026-09-27`'s run ticket and headers, only in configurator)
- Test: `tests/test_deployment_mode.py`, port `tests/test_run_ticket.py`

**Interfaces:**
- Consumes: the backend's `celery_service` sends `platform_pid` and the run ticket only in configurator (Task 4).
- Produces: `api_client.headers(run: Run | None) -> dict[str, str]`: in standalone only `Authorization` (Sean's), in configurator plus `X-AISC-Project`, `X-AISC-Run`, `X-AISC-Evaluation`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_deployment_mode.py
import pytest
from aisc_eval import deployment
from aisc_eval.service import api_client


def test_bad_values_stop_the_worker():
    with pytest.raises(SystemExit, match="AISC_DEPLOYMENT"):
        deployment.mode({"AISC_DEPLOYMENT": "config"})


def test_standalone_headers_name_no_project(monkeypatch):
    monkeypatch.setattr(deployment, "MODE", deployment.STANDALONE)
    assert "X-AISC-Project" not in api_client.headers(None)


def test_configurator_headers_name_the_run(monkeypatch):
    monkeypatch.setattr(deployment, "MODE", deployment.CONFIGURATOR)
    run = api_client.Run(project="00000000-0000-0000-0000-000000000001", evaluation="e", ticket="t")
    h = api_client.headers(run)
    assert h["X-AISC-Project"] == run.project and h["X-AISC-Run"] == "t" and h["X-AISC-Evaluation"] == "e"
```

- [ ] **Step 2: Run**: `uv run pytest -q tests/test_deployment_mode.py`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement**: `deployment.py` as the backend's but raising `SystemExit(message)`; `MODE = mode()` at import; port `Run`, `acting_for`, `headers()` from `definitive/2026-09-27` and return the three headers only when `deployment.MODE == CONFIGURATOR`; the task signatures accept `platform_pid`/ticket as optional (`None` in standalone).

- [ ] **Step 4: Run all eval tests in both modes** (`AISC_DEPLOYMENT` unset, then `configurator`): standalone equals `baseline-eval.txt` plus new; configurator equals `baseline-configurator-eval.txt` plus new.

- [ ] **Step 5: Commit**

```bash
git add aisc_eval tests
git commit -m "Eval worker by mode: the run ticket and project headers only inside the Configurator"
```

---

### Task 7: Web app by mode

**Files:**
- Create: `src/deployment.ts`, `src/deployment.test.ts`
- Modify: `.env` (`VITE_DEPLOYMENT=APP_DEPLOYMENT`), `.env.development` (`VITE_DEPLOYMENT=standalone`), `src/api/projectHeader.ts` (port; header only in configurator), `src/platform/currentProject.ts`, `src/platform/gatewaySession.ts` (port), `src/pages/GlobalHome.tsx`, `src/components/TopBar.tsx`, `src/components/LeftBar.tsx`, `src/context/AuthContext.tsx`, `src/MyApp.tsx`
- Keep from `master`: `src/auth/keycloak.tsx`, `src/components/LoginDialog.*`, `src/pages/CeleryTasks.*`, `src/components/addProjectWizard.tsx` (Sean's full wizard)

**Interfaces:**
- Produces: `deployment(): "standalone" | "configurator"`, `isConfigurator(): boolean`, `canCreateProjects(): boolean` (standalone), `showsLauncher(): boolean` (configurator), `showsCeleryTasks(): boolean` (standalone).

- [ ] **Step 1: Write the failing tests**

```ts
// src/deployment.test.ts
import { describe, it, expect } from "vitest";
import { deploymentFrom } from "./deployment";

describe("the web app's deployment mode", () => {
  it("is standalone when the build says so or says nothing", () => {
    expect(deploymentFrom("standalone")).toBe("standalone");
    expect(deploymentFrom(undefined)).toBe("standalone");
  });
  it("is configurator when env.sh substituted it", () => {
    expect(deploymentFrom(" Configurator ")).toBe("configurator");
  });
  it("refuses anything else, and an unsubstituted placeholder", () => {
    expect(() => deploymentFrom("APP_DEPLOYMENT")).toThrow(/AISC_DEPLOYMENT/);
    expect(() => deploymentFrom("config")).toThrow(/standalone or configurator/);
  });
});
```

Plus, per component, one test each: GlobalHome shows Sean's project list in standalone and `OpenTheProject` in configurator; TopBar shows the launcher link only in configurator; LeftBar shows Celery tasks only in standalone; `apiFetch` adds `X-AISC-Project` only in configurator (`vi.mock("./deployment")` to switch).

- [ ] **Step 2: Run**: `npx vitest run src/deployment.test.ts`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

```ts
// src/deployment.ts
export type Deployment = "standalone" | "configurator";

/** The mode env.sh wrote into the bundle (APP_DEPLOYMENT). Unset in a dev build means standalone. */
export function deploymentFrom(raw: string | undefined): Deployment {
  if (raw === undefined || raw === "") return "standalone";
  const value = raw.trim().toLowerCase();
  if (value === "standalone" || value === "configurator") return value;
  throw new Error(`AISC_DEPLOYMENT must be standalone or configurator, not ${JSON.stringify(raw)}`);
}

const MODE = deploymentFrom(import.meta.env.VITE_DEPLOYMENT as string | undefined);
export const deployment = (): Deployment => MODE;
export const isConfigurator = (): boolean => MODE === "configurator";
export const canCreateProjects = (): boolean => MODE === "standalone";
export const showsLauncher = (): boolean => MODE === "configurator";
export const showsCeleryTasks = (): boolean => MODE === "standalone";
```

`src/MyApp.tsx`: a thrown `deploymentFrom` renders a full-page error with the message (Review Focus 1). Each component's branch uses these functions; `apiFetch` in `projectHeader.ts` adds the header only `if (isConfigurator())`, and in standalone is `fetch` unchanged.

- [ ] **Step 4: Run the whole suite twice** (`VITE_DEPLOYMENT=standalone`, then `configurator`, via `vi.stubEnv` in a `vitest.setup` switch or two `npx vitest run` with the env set). Expected: standalone equals `baseline-webapp.txt` plus new; configurator equals `baseline-configurator-webapp.txt` plus new.

- [ ] **Step 5: Commit**

```bash
git add -A src .env .env.development
git commit -m "Web app by mode: Sean's login, project wizard and tasks page standalone; the launcher's project in the Configurator"
```

---

### Task 8: The catalogue install dialog in both modes

**Files:**
- Modify: `src/components/PluginInstallDialog.tsx`, `src/platform/currentProject.ts`
- Test: `src/components/PluginInstallDialog.modes.test.tsx`

**Interfaces:**
- Consumes: `isConfigurator()`, `currentPlatformProject()`, `projectForPlatformUrl()`, the platform list at `GET /platform/api/projects` (Task 9's Caddy route; returns `[{pid, name, slug}]` for the caller).
- Produces: `rememberLastPlatformProject(pid)` / `lastPlatformProject()` in `currentProject.ts` (browser-wide, `localStorage`, key `aisc_last_platform_project`), written whenever the engine opens on a project.

Behaviour (spec table):
- standalone: Sean's `master` dialog, unchanged (`GET /projects`, dropdown of every engine project).
- configurator: the target is, in order, the link's `?project=`, else `lastPlatformProject()`. It is preselected and named in the dialog ("Install into Demo"). A "change" control lists the caller's platform projects from `/platform/api/projects`. Choosing one calls `POST /projects/for-platform/<pid>` with that project's header, then `POST /plugins`. If the list is empty: "You are in no project yet: create one on the launcher" with the launcher link. If the link's project is not one of the caller's (Review Focus 4): "You are not in this project" and the Install button is disabled.

- [ ] **Step 1: Write the failing tests**

```tsx
// src/components/PluginInstallDialog.modes.test.tsx
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mode = vi.hoisted(() => ({ configurator: true }));
vi.mock("../deployment", () => ({ isConfigurator: () => mode.configurator }));

import PluginInstallDialog from "./PluginInstallDialog";
import { renderWithInstall } from "../pluginCatalogue/testing"; // helper: provides the context with one pending install

const DEMO = { pid: "701ef4b8-057d-4a93-8b30-9b19052c881e", name: "Demo", slug: "demo" };

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/platform/api/projects")) return new Response(JSON.stringify([DEMO]));
    if (url.includes("/projects/for-platform/")) return new Response(JSON.stringify({ pid: "engine-pid", name: "Demo" }));
    return new Response("[]");
  }));
});

describe("configurator", () => {
  it("a link without a project installs into the project last opened, named", async () => {
    localStorage.setItem("aisc_last_platform_project", DEMO.pid);
    renderWithInstall(<PluginInstallDialog />, { uri: "web+aiscplugin://enable?package=aisc-plugin-langbite&version=0.1.1" });
    await waitFor(() => expect(screen.getByText(/Install into Demo/)).toBeTruthy());
  });

  it("with no project anywhere it says so and links to the launcher", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
    renderWithInstall(<PluginInstallDialog />, { uri: "web+aiscplugin://enable?package=x&version=1" });
    await waitFor(() => expect(screen.getByText(/in no project yet/)).toBeTruthy());
  });

  it("a link naming a project the caller is not in disables Install", async () => {
    renderWithInstall(<PluginInstallDialog />, { uri: "web+aiscplugin://enable?package=x&version=1",
                                                 search: "?project=00000000-0000-0000-0000-00000000dead" });
    await waitFor(() => expect(screen.getByText(/not in this project/)).toBeTruthy());
    expect((screen.getByRole("button", { name: /install/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("standalone", () => {
  it("is Sean's dialog: every engine project in the dropdown", async () => {
    mode.configurator = false;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([{ pid: "p1", name: "Loans" }]))));
    renderWithInstall(<PluginInstallDialog />, { uri: "web+aiscplugin://enable?package=x&version=1" });
    await waitFor(() => expect(screen.getByText("Loans")).toBeTruthy());
    mode.configurator = true;
  });
});
```

`renderWithInstall` is a small test helper to create in `src/pluginCatalogue/testing.tsx`: it wraps the dialog in `PluginInstallContext` with one pending install parsed from `uri`, sets `window.history` to `search` when given, and in `MemoryRouter`.

- [ ] **Step 2: Run**: `npx vitest run src/components/PluginInstallDialog.modes.test.tsx`. Expected: FAIL.

- [ ] **Step 3: Implement** the configurator branch in `PluginInstallDialog.tsx` as described, `master`'s code as the standalone branch, and `rememberLastPlatformProject` called in `currentPlatformProject()` whenever a `?project=` is read.

- [ ] **Step 4: Run the whole web app suite in both modes**: as Task 7 Step 4.

- [ ] **Step 5: Commit**

```bash
git add src
git commit -m "Install from the catalogue in both modes: Sean's project list standalone; the project you came from, named, in the Configurator"
```

---

### Task 9: The Configurator wires the mode and the platform list

**Files (superproject `~/aisc-definitive`):**
- Modify: `docker-compose.development.yml` (`AISC_DEPLOYMENT: configurator` on `aisc-backend`, `aisc-backend-migrate`, `aisc-eval-worker`, `aisc-eval-flower`; `APP_DEPLOYMENT: configurator` on `aisc-webapp`)
- Modify: `Caddyfile` (on the engine's site, GET only: `@platformProjects { method GET  path /platform/api/projects }` then `handle @platformProjects { import protect  rewrite * /projects  reverse_proxy platform:8000 }`)
- Create: `docker-compose.engine-standalone.yml` (engine, eval, redis, rabbitmq, postgres, minio, devpi; `AISC_DEPLOYMENT` unset)
- Modify: `scripts/tests/test_compose.py`, `README.md`, gitlinks of `apps/backend`, `apps/eval`, `apps/webapp` to `feat/deployment-modes`
- Test: `scripts/tests/test_compose.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_engine_runs_in_configurator_mode(compose):
    q, cfg = compose
    for name in ("aisc-backend", "aisc-backend-migrate", "aisc-eval-worker", "aisc-eval-flower"):
        assert (cfg["services"][name].get("environment") or {}).get("AISC_DEPLOYMENT") == "configurator", name
    assert cfg["services"]["aisc-webapp"]["environment"].get("APP_DEPLOYMENT") == "configurator"


def test_the_engine_site_serves_the_callers_platform_projects_behind_the_gateway():
    text = (ROOT / "Caddyfile").read_text()
    block = text[text.index("{$CADDY_DOMAIN}:{$CADDY_PORT}"):text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT}")]
    assert "/platform/api/projects" in block and "reverse_proxy platform:8000" in block
    route = block[block.index("/platform/api/projects"):]
    assert route.index("import protect") < route.index("reverse_proxy platform:8000")


def test_the_standalone_compose_names_no_configurator_setting():
    text = (ROOT / "docker-compose.engine-standalone.yml").read_text()
    assert "AISC_DEPLOYMENT: configurator" not in text
    assert "X-AISC-Project" not in text and "platform:8000" not in text
```

- [ ] **Step 2: Run**: `uv run --no-project --with pytest --with pyyaml python -m pytest -q scripts/tests/test_compose.py`. Expected: 3 FAIL.

- [ ] **Step 3: Implement** the compose, Caddy and standalone compose changes; move the three gitlinks.

- [ ] **Step 4: Run** `scripts/tests` in full; expected: the `scripts/tests` counts of the current branch (432 passed, 52 known failures) plus the three new.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.development.yml Caddyfile docker-compose.engine-standalone.yml scripts/tests/test_compose.py README.md apps/backend apps/eval apps/webapp
git commit -m "The Configurator runs the engine in configurator mode, and serves the caller's platform projects to it"
```

---

### Task 10: Proof in both modes

**Files:** none; results recorded in `docs/superpowers/plans/2026-09-27-engine-deployment-modes-results.md`.

- [ ] **Step 1: Configurator from a fresh clone** (as done on 2026-09-27: clone the local repos, `scripts/secrets.sh`, compose up with the downloader file, fresh volumes). Run `scripts/verify.sh --stack`. Expected: all pass except the known I16.5.
- [ ] **Step 2: The catalogue install, by hand in the browser:** launcher → Demo → step 3 (hosted catalogue) → langbite → Install → the dialog reads "Install into Demo" → Install → the engine's Plugins page of Demo lists langbite 0.1.1. Then the same from a link with no project, having opened Demo before: same result. Record screenshots.
- [ ] **Step 3: Standalone:** `docker compose -f docker-compose.engine-standalone.yml up -d --build`; in the engine UI create a project, open the hosted catalogue from "Public Catalogue", install langbite, see the dropdown of engine projects (Sean's dialog), install, run one evaluation to completion.
- [ ] **Step 4: Upgrade:** start Sean's `master` engine on a fresh volume, create a project and install a plugin, then switch the images to `feat/deployment-modes` (standalone) on the same volume: the project and plugin are still there (Review Focus 2, for real).
- [ ] **Step 5: Commit the results file** and report to the user with the counts, then ask before any push (repos: aisc-backend, aisc-eval, aisc-webapp `feat/deployment-modes`; aisc `definitive/2026-09-27` with the new gitlinks).
