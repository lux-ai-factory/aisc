# Engine: adapt to Sean's master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the seven places where the configurator work changed Sean's logic instead of adapting to it, while every configurator feature keeps working and standalone stays exactly Sean's `master`.

**Architecture:** Configurator behaviour moves out of Sean's files into the pieces that are ours: the project door (all authorization), a new router file (the platform-project route), a start-up request wrapper in the web app (the project header), and Celery signal handlers in the eval worker (the run context travels in message headers). Sean's table names come back, and our readers (dashboard, report renderer, platform tools, scripts) use them.

**Tech Stack:** Django 5 + django-ninja (async), Celery 5.6 + RabbitMQ, React 19 + Vite + vitest, PostgreSQL 15, bash/pytest scripts in the superproject.

**Spec:** `docs/superpowers/specs/2026-09-27-engine-deployment-modes.md` (what each mode decides). This plan changes none of it; it changes where the configurator side lives. The audit it implements is in this plan's "The seven items" below (agreed with the user on 2026-09-28).

## The seven items (the audit, 2026-09-28)

1. All engine tables were renamed (`aisc_backend_plugin` -> `plugin`, migrations 0019-0021), in standalone too. Keep Sean's names; our readers adapt.
2. About 40 `if deployment.is_configurator(): membership...` lines inside Sean's route functions. The door already refuses strangers (404), viewers writing (403), and confines every query to the project's database. Move the only non-redundant checks (stored files, Celery task status) and the configurator rules (no project creation, installs need admin) into the door; Sean's routers go back to master.
3. A verified token without the role became 403 instead of Sean's 401, in both modes. Restore 401.
4. `fetch` -> `apiFetch` / `axios` -> `apiAxios` in ~22 of Sean's web app files. Install one request wrapper at start-up, configurator only; Sean's files go back to master.
5. Standalone eval messages carry two trailing `None` arguments. Fixed by 6.
6. Sean's Celery task signatures changed (`run_evaluation(*args)`, extra parameters). The run context travels in Celery message headers instead; signatures go back to Méril's tip (`96a8ec7`).
7. Dead code in Sean's `config/settings.py` (`DB_SCHEMA`, `_single_database()`). Delete.

## Global Constraints

- `master` of every repo stays untouched. Work on `feat/deployment-modes` in the worktrees `~/engine-modes/apps/{backend,eval,webapp}`; superproject `~/aisc-definitive` branch `definitive/2026-09-27` (gitlinks bumped at the end of each engine task); results-dashboard is the submodule `~/aisc-definitive/apps/results-dashboard`; report renderer is `~/aisc-report-generator` branch `dev`.
- Standalone must equal Sean's `master`: same API statuses, same Celery message arguments, same tables. Additions allowed only where the spec needs them (the three nullable columns, our migrations' tables, the mode marker).
- Méril's seven eval commits (`8b0586c`..`96a8ec7`) stay as he wrote them.
- Every configurator feature keeps working: project databases, the door, memberships, the launcher's project, the catalogue install dialog, the installed-only Plugins page, run tickets, the AI system stamp, `for-platform`.
- Test first (TDD) for every change; nothing is pushed; no em dashes in prose or comments.
- Fresh volumes only: databases made by the earlier branch (tables already renamed) are not upgraded. The virgin environment the user asked for makes this free.
- Controller runs full suites itself; implementers keep each foreground command under 9 minutes.

## Review Focus

1. A request that carries only the gateway's session (header `X-Auth-Request-Access-Token`, no `Authorization`) must still be accepted by Sean's `KeycloakAuth` in configurator (the door copies it). Test in Task 3.
2. Tasks published by other tasks (the chained `post_measurements`, the chord callback `finalize_evaluation`) run on other workers and must still carry the run ticket. Tested against a real RabbitMQ in Task 4.
3. A stored file or Celery task of project B, asked for with project A's header, is 404, not served. Test in Task 3.
4. The web app wrapper must not add `X-AISC-Project` to anything that is not the engine API (the catalogue, MinIO, Keycloak). Test in Task 5.
5. A database migrated only to Sean's `0014` (his master) upgrades cleanly to this branch in standalone. Test in Task 1.

---

### Task 0: Baselines

**Files:** none; results into `~/engine-modes/baseline-adapt-*.txt`.

- [ ] **Step 1: Record every suite at the current heads** (backend `637a05d`, eval `90d7b60`, webapp `7897925`, superproject `e1395a9`):

```bash
cd ~/engine-modes/apps/backend && DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend 2>&1 | tail -4 > ~/engine-modes/baseline-adapt-backend-standalone.txt
cd ~/engine-modes/apps/backend && AISC_DEPLOYMENT=configurator DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend 2>&1 | tail -4 > ~/engine-modes/baseline-adapt-backend-configurator.txt
cd ~/engine-modes/apps/eval && uv run --with onnxruntime pytest -q --noconftest tests/test_deployment_mode.py tests/test_run_ticket.py 2>&1 | tail -2 > ~/engine-modes/baseline-adapt-eval.txt
cd ~/engine-modes/apps/webapp && npx vitest run 2>&1 | grep -E "Test Files|Tests " > ~/engine-modes/baseline-adapt-webapp.txt
cd ~/aisc-report-generator && uv run pytest -q 2>&1 | tail -2 > ~/engine-modes/baseline-adapt-report.txt
cd ~/aisc-definitive/apps/results-dashboard && uv run pytest -q 2>&1 | tail -2 > ~/engine-modes/baseline-adapt-dashboard.txt
```

The superproject `scripts/tests` baseline is `.superpowers/sdd/2026-09-27-engine-deployment-modes/scripts-tests-after-local-index.log` (461 passed, 50 failed); the controller reruns it at the end of Tasks 2 and 6.

Expected: six files with counts. If a command above does not match how a suite runs (read its README), record the command that works in the file's first line.

---

### Task 1: Sean's table names (backend)

**Files:**
- Modify: `aisc_backend/models/{ai_system,artifact,evaluation,measure,metric,observation,plugin,project,project_config}.py` (remove every `db_table` we added; `Project.Meta` keeps only its `constraints`)
- Delete: `aisc_backend/migrations/0019_alter_artifact_table_alter_dataset_table_and_more.py`, `0020_alter_derived_table_alter_direct_table.py`, `0021_ai_system_tables_lose_the_prefix.py`, `0022_parts_belong_to_a_version_of_the_one_system.py` (a no-op kept only for numbering)
- Rename: `0023_no_login_of_its_own.py` -> `0019_no_login_of_its_own.py`, `0024_the_database_is_the_project.py` -> `0020_the_database_is_the_project.py`, `0025_engine_deployment_marker.py` -> `0021_engine_deployment_marker.py` (fix each `dependencies`)
- Modify: SQL inside the migrations that names a short table (at least `0020_the_database_is_the_project.py`: `ALTER TABLE evaluation` -> `ALTER TABLE aisc_backend_evaluation`); anything in `aisc_backend/` that references the old migration names (`grep -rn "002[2-5]_" aisc_backend config`)
- Test: `aisc_backend/tests/test_seans_table_names.py`; update the tests that pinned the short names (`grep -rln "lose_the_prefix\|db_table\|\"plugin\"\|'plugin'" aisc_backend/tests`)

**Interfaces:**
- Produces: every engine table named as on `master` (`aisc_backend_<model name in lower case>`), in the `engine` schema in configurator. The migration chain is `0014_ai_system_and_project_config_squashed` -> `0015_plugin_catalogue_slug` -> `0016_...` -> `0017_...` -> `0018_alter_project_platform_project_id` -> `0019_no_login_of_its_own` -> `0020_the_database_is_the_project` -> `0021_engine_deployment_marker`.
- The short-name -> Sean-name map Task 2 uses (confirm each against the deleted `AlterModelTable` operations before deleting them, and put the confirmed map in the task report): `ai_component`->`aisc_backend_aicomponent`, `ai_system`->`aisc_backend_aisystem`, `artifact`->`aisc_backend_artifact`, `dataset`->`aisc_backend_dataset`, `derived`->`aisc_backend_derived`, `direct`->`aisc_backend_direct`, `evaluation`->`aisc_backend_evaluation`, `evaluation_input`->`aisc_backend_evaluationinput`, `evaluation_plugin`->`aisc_backend_evaluationplugin`, `measurement`->`aisc_backend_measurement`, `metric`->`aisc_backend_metric`, `metric_category`->`aisc_backend_metriccategory`, `model`->`aisc_backend_model`, `observation`->`aisc_backend_observation`, `plugin`->`aisc_backend_plugin`, `plugin_config`->`aisc_backend_pluginconfig`, `plugin_config_project_config`->`aisc_backend_pluginconfigprojectconfig`, `project`->`aisc_backend_project`, `project_config`->`aisc_backend_projectconfig`.

- [ ] **Step 1: Write the failing test**

```python
# aisc_backend/tests/test_seans_table_names.py
"""The engine keeps Sean's table names (adapt plan 2026-09-28, item 1): our migrations add
columns and tables, they rename none of his."""
from django.apps import apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations import AlterModelTable
from django.test import TestCase


class SeansTableNames(TestCase):
    def test_every_model_keeps_the_default_table_name(self):
        for model in apps.get_app_config("aisc_backend").get_models():
            expected = f"aisc_backend_{model._meta.model_name}"
            self.assertEqual(model._meta.db_table, expected, model.__name__)

    def test_the_migrated_database_has_his_tables(self):
        tables = set(connection.introspection.table_names())
        for name in ("aisc_backend_plugin", "aisc_backend_project", "aisc_backend_evaluation",
                     "aisc_backend_measurement", "aisc_backend_pluginconfig"):
            self.assertIn(name, tables)
        for short in ("plugin", "project", "evaluation", "measurement", "plugin_config"):
            self.assertNotIn(short, tables)

    def test_no_migration_renames_a_table(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        for (app, name), migration in loader.disk_migrations.items():
            if app != "aisc_backend":
                continue
            renames = [op for op in migration.operations if isinstance(op, AlterModelTable)]
            self.assertEqual(renames, [], name)

    def test_the_chain_after_seans_0014(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        ours = sorted(n for a, n in loader.disk_migrations if a == "aisc_backend" and n > "0014")
        self.assertEqual(ours, [
            "0015_plugin_catalogue_slug",
            "0016_evaluation_system_id_project_platform_project_id",
            "0017_one_project_per_platform_project",
            "0018_alter_project_platform_project_id",
            "0019_no_login_of_its_own",
            "0020_the_database_is_the_project",
            "0021_engine_deployment_marker",
        ])
```

- [ ] **Step 2: Run it to see it fail**

Run: `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend.tests.test_seans_table_names`
Expected: FAIL in all four (short `db_table`s, `AlterModelTable` in 0019-0021, the chain).

- [ ] **Step 3: Implement**: remove the `db_table` lines (and a `Meta` that held nothing else); delete the four migrations; rename the three and set their `dependencies` (`0019_no_login_of_its_own` depends on `("aisc_backend", "0018_alter_project_platform_project_id")`, and so on); fix the short table names in migration SQL; fix every reference to the old migration names in `aisc_backend/` and `config/`.

- [ ] **Step 4: Run the test, then check the models and migrations agree**

Run: `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py test aisc_backend.tests.test_seans_table_names && DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/t.db uv run python manage.py makemigrations aisc_backend --check --dry-run`
Expected: 4 passed; `No changes detected`.

- [ ] **Step 5: Review Focus 5, the upgrade from Sean's master, as a test**

```python
# in aisc_backend/tests/test_seans_table_names.py
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class UpgradeFromSeansMaster(TransactionTestCase):
    def test_a_database_at_his_0014_upgrades(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("aisc_backend", "0014_ai_system_and_project_config_squashed")])
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes("aisc_backend"))
        self.assertIn("aisc_backend_plugin", connection.introspection.table_names())
```

Run it; expected PASS.

- [ ] **Step 6: Update the tests that pinned short names** (they now assert the opposite of item 1; each keeps its intent with Sean's names), then run the full backend suite in both modes (the Task 0 commands). Expected: no new failure against `baseline-adapt-backend-*.txt`.

- [ ] **Step 7: Commit**

```bash
git add -A aisc_backend && git commit -m "Keep Sean's table names: no migration renames his tables (adapt item 1)"
```

---

### Task 2: Our readers use Sean's table names (superproject, results-dashboard, report renderer)

**Files:**
- Modify (production): `apps/results-dashboard/aisc_ext/projects.py`; `platform/platform_service/isolate/ownership.py`; `scripts/db_consistency/checks.py`; `scripts/verify-project-databases.sh`; `scripts/verify-one-database.sh`; `scripts/report-grants.sh`; `scripts/lib/report_bed_isolated.py`; `scripts/lib/report_bed.py`; `scripts/test-pipeline-chain.sh`; `scripts/guard-frozen.sh` (comment); `~/aisc-report-generator/report_renderer/data/engine.py`
- Modify (fixtures and tests): `scripts/tests/fixtures/isolation/live_shape.sql`, `scripts/tests/fixtures/report/{schema_engine,seed_tools,seed_platform}.sql`, `platform/tests/isolate_support.py`, `platform/tests/test_isolate.py`, `scripts/tests/test_{db_consistency,project_grants,isolation_harnesses,report_grants,verify_project_databases,isolation_fixture}.py`, `scripts/pipeline_chain/test_dashboard_queries.py`, `apps/results-dashboard/tests/test_isolation_dashboard*.py`, `apps/connectors/tests/test_admin_connectors.py`, the report renderer's tests and fixtures
- Create: `scripts/tests/test_engine_table_names.py`

**Interfaces:**
- Consumes: Task 1's confirmed map (task-1 report). Column names are unchanged, including `project_id` on the project table (0018).

- [ ] **Step 1: Write the failing test**

```python
# scripts/tests/test_engine_table_names.py
"""Our readers use Sean's engine table names (adapt plan 2026-09-28, item 1)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORT = ("ai_component", "ai_system", "artifact", "dataset", "derived", "direct", "evaluation",
         "evaluation_input", "evaluation_plugin", "measurement", "metric", "metric_category",
         "model", "observation", "plugin", "plugin_config", "plugin_config_project_config",
         "project", "project_config")
PATTERN = re.compile(r"\bengine\.(" + "|".join(sorted(SHORT, key=len, reverse=True)) + r")\b(?!_)")
READERS = [
    "apps/results-dashboard/aisc_ext/projects.py",
    "platform/platform_service/isolate/ownership.py",
    "scripts/db_consistency/checks.py",
    "scripts/verify-project-databases.sh",
    "scripts/verify-one-database.sh",
    "scripts/report-grants.sh",
    "scripts/lib/report_bed_isolated.py",
    "scripts/lib/report_bed.py",
    "scripts/test-pipeline-chain.sh",
]
REPORT = Path.home() / "aisc-report-generator" / "report_renderer" / "data" / "engine.py"


def test_no_reader_names_a_short_engine_table():
    found = {f: PATTERN.findall((ROOT / f).read_text()) for f in READERS}
    if REPORT.exists():
        found[str(REPORT)] = PATTERN.findall(REPORT.read_text())
    assert {f: m for f, m in found.items() if m} == {}
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --no-project --with pytest python -m pytest -q scripts/tests/test_engine_table_names.py`
Expected: FAIL listing every reader.

- [ ] **Step 3: Rename in every file listed above** with the map, reading each hit (only `engine.<short>` table references change; column names, aliases and `engine.django_*` do not). A mechanical start, then read the diff:

```bash
# one sed expression per map entry, longest names first, e.g.:
sed -i -E 's/\bengine\.plugin_config_project_config\b/engine.aisc_backend_pluginconfigprojectconfig/g; s/\bengine\.plugin_config\b/engine.aisc_backend_pluginconfig/g; s/\bengine\.plugin\b/engine.aisc_backend_plugin/g' FILE
```

Unqualified short names inside SQL that runs with `search_path=engine` (for example `FROM evaluation e` in the report renderer) change too: grep each file for `FROM|JOIN|INTO|UPDATE|TABLE` followed by a short name.

- [ ] **Step 4: Run the test and each touched suite**

Run: `uv run --no-project --with pytest python -m pytest -q scripts/tests/test_engine_table_names.py`; then the report renderer suite and the dashboard suite (Task 0 commands). Expected: PASS; no new failure against the baselines.

- [ ] **Step 5: Commit, in each repo**

```bash
cd ~/aisc-report-generator && git add -A && git commit -m "Engine tables by Sean's names (aisc_backend_*)"
cd ~/aisc-definitive/apps/results-dashboard && git add -A && git commit -m "Engine tables by Sean's names (aisc_backend_*)"
cd ~/aisc-definitive && git add -A scripts platform apps/connectors apps/results-dashboard && git commit -m "Readers use Sean's engine table names (adapt item 1)"
```

The controller then reruns the full `scripts/tests` suite (compare failing ids with the baseline log).

---

### Task 3: All configurator authorization in the door; Sean's routers, `keycloak.py` and settings back to master (backend)

**Files:**
- Modify: `aisc_backend/project_door.py`, `aisc_backend/auth/membership.py` (remove what is no longer called; `claims_of` also reads the door's claims)
- Create: `aisc_backend/routers/platform_project.py` (the `for-platform` route, moved verbatim from `project.py`)
- Modify: `config/urls.py` (mount it in configurator only), `config/settings.py` (delete `DB_SCHEMA` and `_single_database()`)
- Restore to `origin/master`: `aisc_backend/routers/{component,evaluation,file,project_config,stats,task}.py`, `aisc_backend/auth/keycloak.py`; `aisc_backend/routers/project.py` and `aisc_backend/routers/plugin.py` to master plus only the `catalogue_slug` hunks in `plugin.py` (a new feature) and nothing in `project.py`
- Test: `aisc_backend/tests/test_door_owns_authorization.py`, `aisc_backend/tests/test_seans_files_unchanged.py`

**Interfaces:**
- Consumes: `membership.require(request, platform_project_id, needed="viewer")`, `membership.for_stored_file(request, container, file_name, needed="viewer")`, `membership.for_task(request, task_pid, needed="viewer")` (they raise `ninja.errors.HttpError`).
- Produces (door rules, configurator only, in this order after the existing steps 1-4): `POST /api/v1/projects` -> 403 `projects are made on the Configurator's launcher`; `POST|DELETE /api/v1/plugins` and `POST /api/v1/plugins/refresh` without the realm role `admin` -> 403 `this needs the 'admin' role`; after admission (step 8): `GET /api/v1/files/(dataset|model|artifact)/<name>` -> `membership.for_stored_file`, `GET /api/v1/tasks/<pid>/status` (and Sean's `/api/v1/tasks<pid>/status`) -> `membership.for_task`, an `HttpError` turned into the same JSON refusal the door gives. `project_door.bearer_from_gateway(request) -> None` copies `X-Auth-Request-Access-Token` into `Authorization: Bearer ...` when `Authorization` is absent; the door stores the claims it verified on `request.aisc_claims`.

- [ ] **Step 1: Write the failing tests**

```python
# aisc_backend/tests/test_seans_files_unchanged.py
"""Sean's files the configurator no longer edits (adapt plan 2026-09-28, items 2, 3, 7)."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNCHANGED = [
    "aisc_backend/routers/component.py", "aisc_backend/routers/evaluation.py",
    "aisc_backend/routers/file.py", "aisc_backend/routers/project_config.py",
    "aisc_backend/routers/stats.py", "aisc_backend/routers/task.py",
    "aisc_backend/routers/project.py", "aisc_backend/auth/keycloak.py",
]


def _master(path: str) -> str | None:
    r = subprocess.run(["git", "show", f"origin/master:{path}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


class SeansFilesUnchanged(unittest.TestCase):
    def test_each_file_equals_master(self):
        if _master("manage.py") is None:
            self.skipTest("no git history here (a built image)")
        for path in UNCHANGED:
            self.assertEqual((ROOT / path).read_text(), _master(path), path)

    def test_settings_keep_no_dead_single_database_code(self):
        text = (ROOT / "config" / "settings.py").read_text()
        self.assertNotIn("_single_database", text)
        self.assertNotIn("DB_SCHEMA", text)
```

```python
# aisc_backend/tests/test_door_owns_authorization.py
"""The door holds every configurator rule (adapt plan 2026-09-28, item 2). DoorCase: auth on,
membership stubbed, no database; each refusal here happens before a database is opened."""
import json
import uuid
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from aisc_backend.tests.isolation_support import configurator_only
from aisc_backend.tests.test_isolation_engine import A_PID, DoorCase


@configurator_only
class TheDoorsOwnRules(DoorCase):
    def test_no_project_is_made_in_the_engine(self):
        with self.as_role("owner"):
            r = self.call("POST", "/api/v1/projects",
                          {"X-AISC-Project": A_PID, "Authorization": self.bearer(("admin",))}, {"name": "x"})
        self.assertEqual((r.status_code, json.loads(r.content)["detail"]),
                         (403, "projects are made on the Configurator's launcher"))

    def test_installing_removing_refreshing_take_admin(self):
        body = {"package_name": "p", "version": "1", "project_uuid": str(uuid.uuid4())}
        for method, path in (("POST", "/api/v1/plugins"), ("DELETE", "/api/v1/plugins"),
                             ("POST", "/api/v1/plugins/refresh")):
            with self.as_role("editor"):
                r = self.call(method, path, {"X-AISC-Project": A_PID, "Authorization": self.bearer()}, body)
            self.assertEqual((r.status_code, json.loads(r.content)["detail"]),
                             (403, "this needs the 'admin' role"), (method, path))

    def test_a_stranger_gets_nothing_about_a_file_or_a_task(self):
        # pins today's door (strangers are 404 before any route); may pass before the change
        for path in ("/api/v1/files/dataset/x.csv", "/api/v1/files/artifact/y.zip",
                     f"/api/v1/tasks/{uuid.uuid4()}/status"):
            with self.as_role(None):
                r = self.call("GET", path, {"X-AISC-Project": A_PID, "Authorization": self.bearer()})
            self.assertEqual(r.status_code, 404, path)


@configurator_only
class TheGatewaySessionIsABearer(SimpleTestCase):
    def test_the_gateway_token_is_copied_when_no_authorization_is_sent(self):
        from aisc_backend import project_door
        request = RequestFactory().get("/api/v1/projects", HTTP_X_AUTH_REQUEST_ACCESS_TOKEN="tok")
        project_door.bearer_from_gateway(request)
        self.assertEqual(request.META["HTTP_AUTHORIZATION"], "Bearer tok")

    def test_an_authorization_sent_is_left_alone(self):
        from aisc_backend import project_door
        request = RequestFactory().get("/api/v1/projects", HTTP_AUTHORIZATION="Bearer mine",
                                       HTTP_X_AUTH_REQUEST_ACCESS_TOKEN="tok")
        project_door.bearer_from_gateway(request)
        self.assertEqual(request.META["HTTP_AUTHORIZATION"], "Bearer mine")


class SeansMissingRoleAnswer(DoorCase):
    """Item 3: a verified token that lacks the role is Sean's 401, in both modes."""
    def test_a_role_guarded_route_answers_401(self):
        from aisc_backend.auth.keycloak import require_role
        from ninja.testing import TestClient
        from ninja import Router
        router = Router()
        @router.get("/x", auth=require_role("admin"))
        def x(request):
            return {"ok": True}
        r = TestClient(router).get("/x", headers={"Authorization": self.bearer(("primary-user",))})
        self.assertEqual(r.status_code, 401)
```

The two cross-project cases of Review Focus 3 need real project databases: add them to `TheDoorOnPostgres` in `aisc_backend/tests/test_isolation_engine_db.py`, with its two-project setup: a dataset file and a Celery task id recorded in project B's database, asked for with project A's header, answer 404; the same file asked for with B's header as a viewer, 200.

Rewrite, in `aisc_backend/tests/test_modes_routes.py`, the classes that pinned what this task removes: `TheGatewayHeader` (the constant now lives in the door; `keycloak.py` is master's), `AMissingRoleIsForbidden` (401 now, item 3), `InstallingAPlugin` (the admin rule is the door's: assert it through `DoorCase`), `ConfiguratorProjects.test_the_engine_does_not_make_projects` (the door's 403). `StartingARun` is Task 4's.

- [ ] **Step 2: Run them to see them fail**

Run (Postgres, as the existing isolation tests run; find their command in `aisc_backend/tests/README*` or the configurator baseline): `AISC_DEPLOYMENT=configurator ... manage.py test aisc_backend.tests.test_door_owns_authorization aisc_backend.tests.test_seans_files_unchanged`
Expected: FAIL (routers differ from master; the door has none of the new rules).

- [ ] **Step 3: Implement**
  1. Door: the rules above, with these patterns:

```python
_FILE_PATH = re.compile(r"^/api/v1/files/(dataset|model|artifact)/([^/]+)$")
_TASK_PATH = re.compile(r"^/api/v1/tasks/?([^/]+)/status$")
_ADMIN_ROUTES = {("POST", "/api/v1/plugins"), ("DELETE", "/api/v1/plugins"), ("POST", "/api/v1/plugins/refresh")}
_CONTAINERS = {"dataset": StorageContainer.Datasets, "model": StorageContainer.Models, "artifact": StorageContainer.Artifacts}
```

  and `bearer_from_gateway(request) -> None`, called first in the door, which sets `request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"` from `X-Auth-Request-Access-Token` when no `Authorization` was sent (the constant `GATEWAY_TOKEN_HEADER` moves from `keycloak.py` into the door; `_bearer` then reads `Authorization` only).
  2. `platform_project.py`: `router = Router(tags=["project"])`, `@router.post("/{platform_project_id}", response=ProjectOutSchema)` with `project_for_platform`'s body unchanged; `config/urls.py`: `if deployment.is_configurator(): v1_router.add_router("/projects/for-platform", platform_project_router)` before the `/projects` router.
  3. `git checkout origin/master -- <each UNCHANGED file>`; `plugin.py` from master, then re-apply only the `catalogue_slug` field, its save, and its audit metadata.
  4. `membership.py`: `claims_of` returns `request.aisc_claims` when `request.auth` is not a dict; delete the functions nothing calls any more (`for_component`, `for_plugin`, `for_evaluation`, `for_project_pid`, `for_project_config`, `visible`, `visible_by`) and their tests.
  5. `settings.py`: delete `DB_SCHEMA` and `_single_database()`.

- [ ] **Step 4: Run the two new test files, then both full backend suites** (Task 0 commands, plus the Postgres isolation tests). Expected: new tests pass; the ported isolation tests (stranger 404, viewer write 403 on every route family) still pass through the door; no new failure against the baselines. A ported test that asserted a route-level check now passes through the door or is rewritten to assert the door's answer; list each rewrite in the report.

- [ ] **Step 5: Commit**

```bash
git add -A aisc_backend config && git commit -m "Configurator authorization lives in the door; Sean's routers, keycloak.py and settings back to master (adapt items 2, 3, 7)"
```

---

### Task 4: The run context in Celery headers; Sean's task signatures back (eval + backend dispatch)

**Files:**
- Create: `aisc_eval/run_context.py`
- Restore: `aisc_eval/celery_tasks.py` to Méril's tip (`git show 96a8ec7:aisc_eval/celery_tasks.py`), plus one import line
- Modify: `aisc_eval/service/api_client.py` (its run headers come from `run_context.current()`; keep Méril's changes)
- Modify (backend): `aisc_backend/services/celery_service.py` (configurator: `args=[evaluation_uuid]` and the run in `headers`)
- Test: `tests/test_run_context.py` (eval), update `tests/test_run_ticket.py`; backend `aisc_backend/tests/test_celery_dispatch.py`

**Interfaces:**
- Produces: header name `aisc_run`, value `{"project": "<platform pid>", "evaluation": "<evaluation pid>", "ticket": "<ticket>"}`; `run_context.current() -> dict | None`; `run_context.run_of(request) -> dict | None`. Standalone never sets the header, so nothing changes there.

```python
# aisc_eval/run_context.py
"""The run a task acts for (configurator only), carried in the Celery message headers, so
Sean's task signatures stay his (adapt plan 2026-09-28, items 5 and 6). The backend puts it
on run_evaluation; every task published while a task runs inherits it; the api_client reads
it for the X-AISC-Project, X-AISC-Evaluation and X-AISC-Run headers the door checks."""
from contextvars import ContextVar

from celery.signals import before_task_publish, task_postrun, task_prerun

HEADER = "aisc_run"
_current: ContextVar[dict | None] = ContextVar(HEADER, default=None)


def run_of(request) -> dict | None:
    value = getattr(request, HEADER, None)
    if value is None:
        value = (getattr(request, "headers", None) or {}).get(HEADER)
    return value if isinstance(value, dict) else None


def current() -> dict | None:
    return _current.get()


@task_prerun.connect
def _enter(task=None, **_):
    _current.set(run_of(task.request) if task is not None else None)


@task_postrun.connect
def _leave(**_):
    _current.set(None)


@before_task_publish.connect
def _forward(headers=None, **_):
    run = _current.get()
    if run is not None and headers is not None and HEADER not in headers:
        headers[HEADER] = run
```

- [ ] **Step 1: Spike first (5 minutes, no commit)**: with the stack's RabbitMQ (or `docker run --rm -d -p 5673:5672 rabbitmq:3`), a two-task Celery app that sends `send_task("t1", headers={"aisc_run": {...}})`, where `t1` chains `t2` and `t2` records `run_of(self.request)`. Confirm where the header arrives (`self.request.aisc_run` or `self.request.headers`) and that `t2` inherits it through `_forward`. Write the answer in the report; `run_of` keeps both paths either way.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_run_context.py
import inspect
import uuid
from types import SimpleNamespace

from aisc_eval import celery_tasks, run_context


def test_seans_signatures_are_back():
    assert list(inspect.signature(celery_tasks.run_evaluation.run).parameters) == ["evaluation_pid"]
    assert "platform_pid" not in inspect.signature(celery_tasks.install_package.run).parameters
    assert "ticket" not in inspect.signature(celery_tasks.install_package.run).parameters


def test_run_of_reads_the_header_either_way():
    run = {"project": str(uuid.uuid4()), "evaluation": str(uuid.uuid4()), "ticket": "t"}
    assert run_context.run_of(SimpleNamespace(aisc_run=run)) == run
    assert run_context.run_of(SimpleNamespace(headers={"aisc_run": run})) == run
    assert run_context.run_of(SimpleNamespace(headers=None)) is None


def test_a_task_published_inside_a_run_inherits_it():
    run = {"project": "p", "evaluation": "e", "ticket": "t"}
    token = run_context._current.set(run)
    try:
        headers = {}
        run_context._forward(headers=headers)
        assert headers == {"aisc_run": run}
    finally:
        run_context._current.reset(token)


def test_standalone_publishes_no_header():
    headers = {}
    run_context._forward(headers=headers)
    assert headers == {}
```

Rewrite `StartingARun` in `aisc_backend/tests/test_modes_routes.py` to the same assertions, or move it here. Backend (`aisc_backend/tests/test_celery_dispatch.py`): with `celery.send_task` patched, standalone `run_evaluation_task(evaluation_uuid)` is called with exactly `args=[evaluation_uuid]` and no `headers` (item 5: equals master); configurator is called with `args=[evaluation_uuid]` and `headers={"aisc_run": {"project": ..., "evaluation": ..., "ticket": projectdb.run_ticket(...)}}`.

- [ ] **Step 3: Run them to see them fail**

Run: `uv run --with onnxruntime pytest -q --noconftest tests/test_run_context.py` (eval) and the backend test.
Expected: FAIL (module missing; signatures differ; dispatch sends the ticket as arguments).

- [ ] **Step 4: Implement**: create `run_context.py`; restore `celery_tasks.py` to `96a8ec7` and add `from aisc_eval import run_context  # noqa: F401  (registers the run header handlers)`; in `api_client.py` build the three door headers from `run_context.current()` (none when it is `None`) and remove `acting_for`/`Run` if nothing else uses them; in `celery_service.py` configurator branch `return celery.send_task(RUN_EVAL_TASK, args=[evaluation_uuid], headers={"aisc_run": {...}})`, standalone untouched.

- [ ] **Step 5: Run the tests, the eval tests of Task 0 (updated `test_run_ticket.py` asserts the same door headers now come from the context), and the backend suites.** Expected: pass; no new failure against the baselines.

- [ ] **Step 6: Review Focus 2, for real**: the spike app from Step 1 turned into `tests/test_run_context_broker.py`, skipped unless `AISC_TEST_BROKER_URL` is set: `run_evaluation`-like task -> chain -> chord callback, each recording `run_context.current()`; all three equal the header sent. Run it with the broker URL set. Expected: PASS.

- [ ] **Step 7: Commit** (eval, then backend, then bump both gitlinks in the superproject)

```bash
cd ~/engine-modes/apps/eval && git add -A && git commit -m "The run context travels in Celery headers; Sean's task signatures back (adapt items 5, 6)"
cd ~/engine-modes/apps/backend && git add -A && git commit -m "Configurator dispatch: the run in Celery headers, arguments as on master"
```

---

### Task 5: One request wrapper at start-up; Sean's web app files back to master (webapp)

**Files:**
- Create: `src/api/installProjectHeader.ts`
- Modify: `src/api/projectHeader.ts` (`apiFetch` becomes `projectFetch(base, input, init)`; the axios interceptor becomes an exported function), `src/main.tsx` (install before render, configurator only)
- Restore to `origin/master`: `src/api/api.tsx`, `src/components/{AISystemSettings,EvaluationProgressList,GenericTextDataGrid,SummaryTable,UploadFileField}.tsx`, `src/components/plugin/{CSVDataGridChart,ConfigHistory,PluginConfigForm,PluginEvaluationForm}.tsx`, `src/pages/{PluginEvaluationMeasurements,PluginEvaluations,PluginEvaluationsTasks,PluginStartEvaluation,PluginsConfig,Settings,StartEvaluation}.tsx`
- Modify: `src/components/{LeftBar,TopBar,PluginInstallDialog}.tsx`, `src/MyApp.tsx`, `src/pages/{GlobalHome,Plugins}.tsx`: `apiFetch` -> `fetch`, `apiAxios` -> `axios`, keeping their gated configurator logic
- Test: `src/api/installProjectHeader.test.ts`, `src/seansFilesUnchanged.test.ts`; update tests that imported `apiFetch`

**Interfaces:**
- Produces: `installProjectHeader(target: typeof globalThis = globalThis): () => void` (returns the uninstall), which wraps `target.fetch` and adds the axios default-instance interceptor; `projectFetch(base: typeof fetch, input: RequestInfo | URL, init?: RequestInit): Promise<Response>` with today's `apiFetch` rules (caller-named project wins, else the current platform project, else `NoCurrentProject` for project routes, project-less routes untouched, non-API URLs untouched).

```ts
// src/api/installProjectHeader.ts
import axios from "axios";
import { projectFetch, projectHeaderInterceptor } from "./projectHeader";

/** Configurator only: every engine API call names the open project (X-AISC-Project), without
 *  Sean's components knowing (adapt plan 2026-09-28, item 4). */
export function installProjectHeader(target: typeof globalThis = globalThis): () => void {
  const original = target.fetch.bind(target);
  target.fetch = ((input: RequestInfo | URL, init?: RequestInit) => projectFetch(original, input, init)) as typeof fetch;
  const id = axios.interceptors.request.use(projectHeaderInterceptor);
  return () => {
    target.fetch = original;
    axios.interceptors.request.eject(id);
  };
}
```

```ts
// src/main.tsx, before createRoot(...)
import { installProjectHeader } from './api/installProjectHeader'
import { isConfigurator } from './deployment'
try { if (isConfigurator()) installProjectHeader() } catch { /* a bad mode: DeploymentGate shows it */ }
```

- [ ] **Step 1: Write the failing tests**

```ts
// src/api/installProjectHeader.test.ts
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios from 'axios';

vi.mock('../deployment', async (orig) => ({ ...(await orig<typeof import('../deployment')>()), isConfigurator: () => true }));
import { installProjectHeader } from './installProjectHeader';

const PID = '9f2afa73-a818-4a27-b01d-f9f7773838c2';
const API = `${import.meta.env.VITE_API_URL ?? ''}/api/v1`;
let seen: { url: string; header: string | null }[] = [];
let uninstall: () => void = () => {};

beforeEach(() => {
  seen = [];
  sessionStorage.setItem('aisc_platform_project', PID);
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    seen.push({ url: String(input), header: new Headers(init?.headers).get('X-AISC-Project') });
    return new Response('{}', { status: 200 });
  }));
  uninstall = installProjectHeader(globalThis);
});
afterEach(() => { uninstall(); vi.unstubAllGlobals(); sessionStorage.clear(); });

describe('the start-up wrapper', () => {
  it('names the open project on an engine API call made with plain fetch', async () => {
    await fetch(`${API}/projects/abc`);
    expect(seen[0].header).toBe(PID);
  });
  it('leaves other hosts alone (Review Focus 4)', async () => {
    await fetch('https://sandboxconfigurator.aifactory.lu/api/api/tool/');
    await fetch('http://localhost:9000/bucket/object');
    expect(seen.map((s) => s.header)).toEqual([null, null]);
  });
  it('lets a caller-named project win', async () => {
    const other = '5b0c1d2e-3f40-4a5b-8c6d-7e8f90a1b2c3';
    await fetch(`${API}/plugins`, { method: 'POST', headers: { 'X-AISC-Project': other } });
    expect(seen[0].header).toBe(other);
  });
  it('adds the header on the default axios instance too', async () => {
    const config = await (axios.interceptors.request as any).handlers.at(-1).fulfilled({ url: `${API}/components/x/data`, headers: {} });
    expect(new Headers(config.headers as any).get('X-AISC-Project') ?? config.headers.get?.('X-AISC-Project')).toBe(PID);
  });
});
```

```ts
// src/seansFilesUnchanged.test.ts
import { describe, it, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const UNCHANGED = [
  'src/api/api.tsx', 'src/components/AISystemSettings.tsx', 'src/components/EvaluationProgressList.tsx',
  'src/components/GenericTextDataGrid.tsx', 'src/components/SummaryTable.tsx', 'src/components/UploadFileField.tsx',
  'src/components/plugin/CSVDataGridChart.tsx', 'src/components/plugin/ConfigHistory.tsx',
  'src/components/plugin/PluginConfigForm.tsx', 'src/components/plugin/PluginEvaluationForm.tsx',
  'src/pages/PluginEvaluationMeasurements.tsx', 'src/pages/PluginEvaluations.tsx', 'src/pages/PluginEvaluationsTasks.tsx',
  'src/pages/PluginStartEvaluation.tsx', 'src/pages/PluginsConfig.tsx', 'src/pages/Settings.tsx', 'src/pages/StartEvaluation.tsx',
];
const master = (p: string) => { try { return execFileSync('git', ['show', `origin/master:${p}`], { encoding: 'utf8' }); } catch { return null; } };

describe("Sean's files the configurator no longer edits", () => {
  it.skipIf(master('package.json') === null)('each equals master', () => {
    for (const p of UNCHANGED) expect(readFileSync(p, 'utf8'), p).toBe(master(p));
  });
  it('no source file outside src/api imports apiFetch or apiAxios', () => {
    const files = execFileSync('git', ['ls-files', 'src'], { encoding: 'utf8' }).split('\n')
      .filter((f) => /\.tsx?$/.test(f) && !f.startsWith('src/api/') && !/\.test\.tsx?$/.test(f));
    const users = files.filter((f) => /\b(apiFetch|apiAxios)\b/.test(readFileSync(f, 'utf8')));
    expect(users).toEqual([]);
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/api/installProjectHeader.test.ts src/seansFilesUnchanged.test.ts`
Expected: FAIL (module missing; files differ; 22 files import `apiFetch`).

- [ ] **Step 3: Implement**: `projectFetch` and `projectHeaderInterceptor` in `projectHeader.ts` (today's rules; accept `Request` and `URL` inputs by reading their URL); `installProjectHeader.ts`; `main.tsx`; `git checkout origin/master -- <each UNCHANGED file>`; the six gated files swap back to `fetch`/`axios`.

- [ ] **Step 4: Run the whole suite and the type check**

Run: `npx vitest run && npx tsc --noEmit -p .`

> Note (final review, 2026-09-28): `-p .` reads `tsconfig.json`, which has `"files": []` and only
> references, so it checks nothing. The type check of the web app is
> `npx tsc --noEmit -p tsconfig.app.json` (0 errors at 0bc2844).
Expected: all pass; tests that imported `apiFetch` now install the wrapper (or call `projectFetch`) and keep their assertions; no new failure against `baseline-adapt-webapp.txt`.

- [ ] **Step 5: Commit**

```bash
git add -A src && git commit -m "One project-header wrapper installed at start (configurator); Sean's files back to master (adapt item 4)"
```

---

### Task 6: Proof on a fresh stack

**Files:** results into `docs/superpowers/plans/2026-09-28-engine-adapt-to-master-results.md` (superproject).

- [ ] **Step 1: Gitlinks and suites**: bump `apps/backend`, `apps/eval`, `apps/webapp`, `apps/results-dashboard` in the superproject; the controller runs every Task 0 suite and `scripts/tests`, and diffs failing ids against the baselines. Expected: 0 new failures.
- [ ] **Step 2: What is left of the diff to master**: for each engine repo, `git diff --stat origin/master HEAD -- . ':!*test*'`, and for each of Sean's files still modified, one line on why (for the pull request note). Expected: no router file of Sean's except `plugin.py` (`catalogue_slug`); no web app file of Sean's except the six with gated logic.
- [ ] **Step 3: Fresh stack**: stop the running `aisc` stack and remove its volumes (the user's go for the virgin environment covers this), bring the clone up on fresh volumes as the README says, run `scripts/verify.sh --stack` after creating a project. Expected: as before this plan (known I16.5 only).
- [ ] **Step 4: The user's path, end to end**: launcher -> project -> catalogue -> install langbite -> Plugins lists it -> run one evaluation to completion (it crosses install_package -> run_plugin -> post_measurements -> finalize_evaluation, so the Celery headers are proven for real) -> results appear in the dashboard and in a rendered report (Sean's table names end to end).
- [ ] **Step 5: Standalone smoke**: `docker compose --env-file env.engine-standalone -f docker-compose.engine-standalone.yml up -d --build`; create a project in the engine UI, enable a plugin from its list, run one evaluation. Expected: as on master.
- [ ] **Step 6: Commit the results file**; report counts to the user; ask before any push.
