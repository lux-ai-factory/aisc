# Project databases, plan 3: control objectives in each project's database

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The control objectives module (`apps/control-objectives`) keeps everything it does for a project in that project's own database, `project_<pid hex>`. That covers the assessments, their risks, the mappings and runs, and the project's own copy of the control objectives. Its `project` table goes, because the database is the project. It no longer reads `core.*`. It asks the platform who may do what, through `GET /authz/projects/{pid}`.

**Architecture:** The platform already creates a database per project and applies `platform/project-template/*.sql` to it (Plan 1). This plan adds `0003_control_objectives.sql`, which gives `control_objectives_rw` `CONNECT` and a `control_objectives` schema. Inside the module:
1. **The door** (`access.py`) is Starlette middleware in front of every `/p/{x}` path. It answers 404 for any `x` that is not a pid, without asking anyone. It answers 401 without a token. Otherwise it asks the platform's `GET /authz/projects/{pid}` with the caller's token: stranger 404, viewer writing 403, no answer 503. This is the same contract `apps/controls/src/lib/access/projectAccess.ts` uses.
2. **The one helper that hands out a project database** (`db/workspaces.py: ProjectDatabases.open(pid, *, token, write)`) asks the platform again, about that exact pid, with that caller's token. It refuses before connecting to anything. No route reaches a project database any other way. That is the rule; the door only answers early.
3. Once the caller is allowed, the helper opens one SQLAlchemy engine per project database, with at most 2 connections. The first time, it runs Alembic, from one new baseline, and copies the bundled control objectives CSV into the project's own `objective` table. Requests that arrive together share that one migration.
4. A `control-objectives-migrate` one-shot loops over every `^project_[0-9a-f]{32}$` database it may enter, and skips the rest. It exits 2 on a permanent error, which stops the compose retry loop.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 with psycopg 3, Alembic, httpx (the platform call), pytest. The platform side is FastAPI with psycopg 3. Postgres 14, docker compose.

**Spec:** `docs/superpowers/plans/2026-09-23-project-databases-roadmap.md`, item 3: "`control_objectives` schema per project database. Its own `project` table goes, because the database is the project." The user's words: "each project should be fully isolated from the others" and "the only thing that connects them is the homepage". The binding brief is `.superpowers/sdd/planner-brief.md`, including its "LESSON FROM PLAN 1'S FINAL REVIEW".

## Global Constraints

- **Database name:** `project_` + the pid, lowercased, hyphens removed. Example: pid `3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b` becomes `project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b`. This is the same example the platform (`platform/tests/test_project_databases.py:16`) and controls (`apps/controls/test/unit/projectDb.test.ts`) assert.
- **Nothing is built from a non-pid.** Anything used to build a database name must match `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (case-insensitive) first. Otherwise it is refused, and nothing is connected to.
- **Authz happens inside the helper, every time.** Every read or write of a project database goes through `ProjectDatabases.open(pid, token=…, write=…)`. That call asks `GET /authz/projects/{pid}` about that pid, with the caller's token, before connecting. It raises 404 for a stranger, 403 for a viewer writing, and 503 when the platform does not answer. The pid comes only from the URL path. No route takes a pid from a query, a body or a header; the old `?project=` query on `/api/projects` goes. The migrate service is an operator path with no caller and no client-supplied pid, so it opens databases directly.
- **Role and connection limits.** The role keeps its name and dev password (`control_objectives_rw` / `control_objectives_rw`). No new secret is committed. `POSTGRES_USER` / `POSTGRES_PASSWORD` come from the existing env files inside the `postgres` container and are never echoed. The module opens at most 2 connections per project database (`pool_size=2, max_overflow=0`).
- **Nothing shared is dropped.** The shared `control_objectives` schema in the `platform` database (0 rows, survey §2) is abandoned, not dropped: Plan 6 drops it, with the user's go-ahead. Nothing here alters it, and the new migrate service never connects to `platform`. The stale `control_objectives_test` database is left alone too.
- **Plan 2 coordination.** Control objectives does not read the AI system. An assessment copies `system_name` and `qualification_id` from the AI Card the assessor uploads (`db/repository.py:102-103`). So this plan reads neither `core.system` nor Plan 2's `project.system`, grants nothing on schema `project`, and does not depend on `0002_system.sql`. `0003` applies whether or not `0002` exists yet: `platform/platform_service/migrate.py:25-26` applies every unapplied file in name order.
- **Dashboard.** This plan grants nothing to `dashboard_ro` inside project databases; that is Plan 5's work.
- **HARD RULE.** Never DROP, ALTER or delete rows in any database, schema or project you did not create in the current task. The real project's database is `project_01399e174b014be9997a7f5e3574ab22` (project `microcredit-assist-score-mcas`). Touch it only through this module's own migration path: the migrate service, or the app opening it. Do the browser walkthrough in throwaway projects. `project_d78463e031a44b2caf62b25f50043d5f` and `project_203720746a324b4087b97b7f2c5be1e2` have no `core.project` row. Leave them alone: the migrate service must skip them, not "fix" them.
- **Compose, always this invocation.** Never print `env.secrets`.
  `set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build <service>`
- **Git.** Never push, never `git clean`. Commits go to `feat/unified-modules`: in `apps/control-objectives` for module code, and in the root for the template, the compose file, the scripts and the submodule pointer. Stage explicit paths only. The root has unrelated uncommitted work: the prefill hunk in `docker-compose.development.yml`, `scripts/verify.sh`, the `apps/qualification` submodule with its own uncommitted prefill changes, and moved `apps/backend`, `apps/eval`, `apps/webapp` and `apps/results-dashboard` pointers. Use `git add -p docker-compose.development.yml` and stage only your hunks. Never stage those pointers or `scripts/verify.sh`. Never touch `apps/qualification`.
- **No rebuilds in the middle.** Do not rebuild or restart `control-objectives` or `control-objectives-migrate` between Task 4 and Task 8. After Task 4 the image carries the new Alembic history. The old migrate command would then run it against the shared schema and loop on "Can't locate revision". Task 8 changes that command and rebuilds both.
- Do not dispatch subagents.

**Decisions this plan makes** (see the open questions at the end):
- **The table is renamed, not removed.** The `project` table becomes `assessment`, with no project column, so a project can still hold several assessments. A project may name several systems: `core.system` is unique on (project, name, version).
- **Each project owns its copy of the objectives.** A project's control objectives are copied from the CSV once, the first time its database is opened. A newer CSV in a later release reaches only projects that don't have their copy yet, so an old assessment's tiers never shift under it. That was already the intent behind `objectives_digest` (`db/tables.py:196-200`).
- **No objectives outside a project.** `/objectives` had no project in its path and served the shared catalogue. It now redirects to the launcher, like `/`. Each project's objectives are at `/p/{pid}/objectives`, and the JSON API moves under `/p/{pid}/api/…`.
- **Code names stay.** The URLs `/p/{pid}/projects/{id}` and the Python names `ProjectRepository`, `ProjectRecord` and `Projects` keep their names, to keep the change reviewable. Only the table and its foreign-key columns are renamed (`project` to `assessment`, `project_id` to `assessment_id`).

## Review Focus

1. **A write to a pid the caller is not in, or only views, with the door removed.** Expected: 404 or 403, and nothing written, because the helper asks the platform about that exact pid. Pinned in Task 6 (`test_workspaces.py`) and Task 7 (`test_project_scope.py`, every mutation entry point).
2. **A `/p/{x}` path where x is not a pid** (`/p/abc`, `/p/..%2F..%2Fplatform`). Expected: 404 before the platform is asked, and no database name is built. Pinned in Task 2 and Task 9 (`verify-rbac.sh`).
3. **An admin opens a pid that has no database.** The platform answers "owner" for any pid when the caller is an admin (`platform/platform_service/app.py:43-44`). Expected: 404, not 500, and nothing is cached. Pinned in Task 6 and Task 7.
4. **Two requests open a brand-new project database at once.** Expected: one migration and one copy of the objectives, and both requests wait for it. Pinned in Task 5 and Task 6.
5. **A project database this module was never given a place in** (the two orphans, or a database made before 0003). Expected: the page answers 503 and says why. The migrate service skips it, exits 0 and doesn't loop. Pinned in Task 6, Task 7 and Task 8.

---

## File map

**Root repo (`~/aisc-install`)**
- Create `platform/project-template/0003_control_objectives.sql`.
- Modify `platform/tests/test_project_databases.py`: one new test.
- Modify `docker-compose.development.yml`:
  - `control-objectives` gets `PLATFORM_URL` and depends on `platform`, and loses `DATABASE_URL` (line 343).
  - `control-objectives-migrate` gets a new command, the env file and a dependency on `platform` (lines 305-319). The comment at lines 298-304 is updated.
- Modify `scripts/verify-one-database.sh:27` and `scripts/verify-rbac.sh:135-139`.

**`apps/control-objectives`**
- Modify these modules:
  - `src/aisc_control_objectives/access.py`: rewritten to ask the platform.
  - `api/app.py`: Tasks 2, 4 and 7.
  - `server.py`, `settings.py`, `projects.py`.
  - `db/tables.py`, `db/repository.py`.
- Create these modules:
  - `db/project_databases.py`: the name, the URL, and reaching the database.
  - `db/migrations.py`.
  - `db/catalogue.py`: this project's objectives.
  - `db/workspaces.py`: the one helper that hands out a project database.
  - `migrate_projects.py`.
- Migrations: delete the four files in `alembic/versions/`, and create `alembic/versions/20260923120000_project_database.py`. Modify `alembic/env.py`.
- Modify `pyproject.toml` and `uv.lock` (httpx), `env.development` and `README.md`.
- Tests:
  - Rewrite `tests/conftest.py` and `tests/test_project_access.py`.
  - Edit `tests/test_repository.py`, `tests/test_projects.py` and `tests/test_api.py`.
  - Create `tests/test_project_database_name.py`, `tests/test_project_catalogue.py`, `tests/test_workspaces.py`, `tests/test_project_scope.py` and `tests/test_migrate_projects.py`.

---

### Task 1: Every project database gets a place for control objectives

**Files:**
- Create: `platform/project-template/0003_control_objectives.sql`
- Test: `platform/tests/test_project_databases.py` (new test after `test_nobody_but_the_listed_roles_may_connect`, line 56)

**Interfaces:**
- Consumes: `projectdb.provision(base_dsn, pid)`, which applies every template file (Plan 1). `platform_rw` owns each project database.
- Produces: in every project database, `control_objectives_rw` may `CONNECT` and has `USAGE, CREATE` on schema `control_objectives`, and on no other schema. `PUBLIC` has no privileges on the database.

- [ ] **Step 1: Write the failing test.** In `platform/tests/test_project_databases.py`, after `test_nobody_but_the_listed_roles_may_connect`, add:

```python
@needs_database
def test_control_objectives_gets_its_own_schema_and_no_other(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    name = projectdb.database_name(created["pid"])
    with _as(dsn, "control_objectives_rw", name) as conn:
        conn.execute("create table control_objectives.probe (x int)")
        conn.execute("drop table control_objectives.probe")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("create table controls.sneaky (x int)")
    with _as(dsn, "controls_rw", name) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("create table control_objectives.sneaky (x int)")
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_project_databases.py -v -k control_objectives`
Expected: FAIL with `psycopg.OperationalError: connection failed: … permission denied for database "project_…"`.

- [ ] **Step 3: Write the template.** Create `platform/project-template/0003_control_objectives.sql`:

```sql
-- Step 2, control objectives: its schema in this project's database, owned by its role.
--
-- This database is one project. Nothing in it names a project, and nothing
-- outside it can be reached from here: the assessments, their risks and
-- mappings, and this project's own copy of the control objectives all live in
-- this schema. The database name is not known when this file is written, hence
-- the DO block (psycopg does not expand psql variables). The REVOKE repeats
-- 0001's on purpose, so this file does not depend on running after it.
DO $grant$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO control_objectives_rw', current_database());
END
$grant$;

CREATE SCHEMA IF NOT EXISTS control_objectives;
GRANT USAGE, CREATE ON SCHEMA control_objectives TO control_objectives_rw;
COMMENT ON SCHEMA control_objectives IS 'Step 2: this project''s assessments, risks and mappings, and the control objectives they are assessed against.';
```

- [ ] **Step 4: Run the platform suite.**

Run: `cd platform && uv run --extra dev pytest -v`
Expected: every test PASSES, including the new one.

- [ ] **Step 5: Give the existing project its place.** Restart the platform. Then make it provision: `provision_all` runs at the first `pool()` use (Plan 1, Task 2 Step 10).

```bash
set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build platform
docker exec platform python -c "from platform_service import db; db.pool()"
docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d project_01399e174b014be9997a7f5e3574ab22 -Atc "select to_regnamespace(\$\$control_objectives\$\$) is not null, has_database_privilege(\$\$control_objectives_rw\$\$, current_database(), \$\$CONNECT\$\$), (select count(*) from provision.template_migration where name = \$\$0003_control_objectives.sql\$\$)"'
```

Expected: `t|t|1`. The two orphan databases are not in `core.project`, so they are left as they are. That is intended.

- [ ] **Step 6: Commit** (root).

```bash
git add platform/project-template/0003_control_objectives.sql platform/tests/test_project_databases.py
git commit -m "Every project database has a place for control objectives"
```

---

### Task 2: The door asks the platform

**Files:**
- Modify: `apps/control-objectives/src/aisc_control_objectives/access.py` (whole file: `_MEMBERSHIP`/`role_in_project` at lines 83-100 and `access_for` at 106-118 go; `Access` at 44-53, `decide` at 66-80 and `ProjectAccess` at 121-155 change)
- Modify: `apps/control-objectives/src/aisc_control_objectives/api/app.py`
  - the `engine=None` parameter at line 71 and the middleware at lines 76-81
- Modify: `apps/control-objectives/src/aisc_control_objectives/server.py`
  - the `engine=repository.engine` argument at lines 240-242
- Modify: `apps/control-objectives/pyproject.toml` and `uv.lock` (httpx becomes a runtime dependency)
- Modify: `docker-compose.development.yml`
  - `control-objectives.environment`: add `PLATFORM_URL` after line 341
  - `control-objectives.depends_on` at line 363
- Test: rewrite `apps/control-objectives/tests/test_project_access.py`

**Interfaces:**
- Consumes: the platform's `GET /authz/projects/{pid}`, which returns `{"role": str|null, "admin": bool, "may_write": bool}` (`platform/platform_service/app.py:158-171`). It also consumes `aisc_identity.headers.token_from_headers` and `aisc_identity.service.caller_from_headers`.
- Produces:
  - `Access(role: str | None, admin: bool = False, may_write: bool = False)` (frozen dataclass)
  - `decide(method: str, access: Access | None) -> Literal["allow", "not-found", "forbidden", "unavailable"]`
  - `fetch_access(project: str, token: str | None, *, platform_url: str, transport: httpx.BaseTransport | None = None) -> Access | None`: synchronous. `None` means the platform did not answer.
  - `PID: re.Pattern`, the pid rule, case-insensitive
  - `ProjectAccess(app, platform_url: str, transport: httpx.BaseTransport | None = None)`
  - `create_app(..., platform_url: str | None = None, platform_transport=None)`. `None` means no door, for tests of the flow. An empty string still fits a door, which then answers 503 to everything.

- [ ] **Step 1: Write the failing test.** Replace `tests/test_project_access.py` with:

```python
"""Who may be in a project, and who may change it.

This service holds the risk ratings and the mappings for somebody's system.
Who is in a project is the platform's to decide, and this service asks it:
GET {PLATFORM_URL}/authz/projects/{pid}, with the caller's own token, the same
contract the controls app uses (apps/controls/src/lib/access/projectAccess.ts).
It no longer reads core.project_member: a project's database has no core.
"""
from __future__ import annotations

import time

import httpx
import jwt
import pytest

from aisc_control_objectives.access import Access, decide, fetch_access, project_from_path

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
PLATFORM = "http://platform:8000"
VIEWER = {"role": "viewer", "admin": False, "may_write": False}
EDITOR = {"role": "editor", "admin": False, "may_write": True}
ADMIN = {"role": "owner", "admin": True, "may_write": True}
STRANGER = {"role": None, "admin": False, "may_write": False}


class TestWhichProjectARequestIsIn:
    def test_reads_the_project_out_of_the_path(self):
        assert project_from_path(f"/p/{PID}") == PID
        assert project_from_path(f"/p/{PID}/objectives") == PID

    def test_decodes_what_the_url_encoded(self):
        assert project_from_path("/p/a%20b/x") == "a b"

    def test_is_none_outside_a_project(self):
        for path in ("/", "/objectives", "/health", "/static/app.css", "/p/", "/p"):
            assert project_from_path(path) is None, path


class TestWhatTheAnswerMeans:
    viewer = Access(role="viewer")
    editor = Access(role="editor", may_write=True)
    stranger = Access(role=None)

    def test_a_stranger_is_told_the_project_does_not_exist(self):
        assert decide("GET", self.stranger) == "not-found"
        assert decide("POST", self.stranger) == "not-found"

    def test_a_member_may_read(self):
        assert decide("GET", self.viewer) == "allow"
        assert decide("HEAD", self.viewer) == "allow"

    def test_a_viewer_may_not_change_anything(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert decide(method, self.viewer) == "forbidden", method

    def test_an_editor_may(self):
        assert decide("POST", self.editor) == "allow"
        assert decide("DELETE", self.editor) == "allow"

    def test_the_platform_decides_who_may_write(self):
        assert decide("POST", Access(role="editor", may_write=False)) == "forbidden"

    def test_no_answer_at_all_is_never_allowed(self):
        """Failing open would turn a platform that is not there into an open door."""
        assert decide("GET", None) == "unavailable"
        assert decide("POST", None) == "unavailable"

    def test_an_admin_is_what_the_platform_says(self):
        assert decide("DELETE", Access(role="owner", admin=True, may_write=True)) == "allow"


def _subject(token: str) -> str:
    try:
        return jwt.decode(token, options={"verify_signature": False})["sub"]
    except jwt.PyJWTError:
        return token


class FakePlatform:
    """The platform's GET /authz/projects/{pid}, answering per caller."""

    def __init__(self):
        self.answers: dict[str, dict] = {}
        self.asked: list[tuple[str, str | None]] = []
        self.status = 200
        self.down = False
        self.transport = httpx.MockTransport(self._answer)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("authorization", "")
        token = authorization[len("Bearer "):] if authorization.startswith("Bearer ") else None
        self.asked.append((request.url.path, token))
        if self.down:
            raise httpx.ConnectError("the platform is down", request=request)
        subject = _subject(token) if token else ""
        return httpx.Response(self.status, json=self.answers.get(subject, STRANGER))


@pytest.fixture()
def platform() -> FakePlatform:
    return FakePlatform()


class TestAskingThePlatform:
    def _ask(self, platform, token="alice"):
        return fetch_access(PID, token, platform_url=PLATFORM + "/", transport=platform.transport)

    def test_it_asks_about_this_project_as_the_caller(self, platform):
        platform.answers["alice"] = EDITOR
        assert self._ask(platform) == Access(role="editor", admin=False, may_write=True)
        assert platform.asked == [(f"/authz/projects/{PID}", "alice")]

    def test_a_stranger_is_an_answer_too(self, platform):
        assert self._ask(platform, token="mallory") == Access(role=None)

    def test_a_platform_that_refuses_is_no_answer(self, platform):
        platform.status = 500
        assert self._ask(platform) is None

    def test_a_platform_that_is_down_is_no_answer(self, platform):
        platform.down = True
        assert self._ask(platform) is None

    def test_an_answer_that_is_not_json_is_no_answer(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
        assert fetch_access(PID, "alice", platform_url=PLATFORM, transport=transport) is None

    def test_no_platform_to_ask_is_no_answer(self):
        assert fetch_access(PID, "alice", platform_url="") is None


# ── the door itself ──────────────────────────────────────────────────────────
# The tests above say what the answer means. These say that every page and
# every endpoint under /p/{project} actually goes through it.


def _keycloak(monkeypatch):
    """A stand-in for Keycloak: returns a function that signs a token."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "http://keycloak:8080/realms/aisc"
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", issuer)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.setattr(
        "aisc_identity.service.key_for_jwks", lambda url: (lambda _t: key.public_key())
    )

    def token(subject, roles=("primary-user",)):
        return jwt.encode(
            {
                "sub": subject,
                "preferred_username": subject,
                "iss": issuer,
                "exp": int(time.time()) + 300,
                "realm_access": {"roles": list(roles)},
            },
            key,
            algorithm="RS256",
        )

    return token


@pytest.fixture()
def pid() -> str:
    """The project the door is tried on."""
    return PID


@pytest.fixture()
def guarded_app(repository, objectives, monkeypatch, platform):
    """The app with the door fitted, and stand-ins for Keycloak and the platform."""
    from fastapi.testclient import TestClient

    from aisc_control_objectives.api.app import create_app
    from aisc_control_objectives.projects import Projects

    token = _keycloak(monkeypatch)
    app = create_app(
        objectives,
        Projects(repository=repository, catalogue=objectives, mapper=None, model="none"),
        platform_url=PLATFORM,
        platform_transport=platform.transport,
    )
    return TestClient(app), token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_a_stranger_is_told_the_project_does_not_exist(guarded_app, pid):
    client, token = guarded_app
    assert client.get(f"/p/{pid}", headers=_auth(token("nobody"))).status_code == 404


def test_a_member_is_let_in_and_the_platform_was_asked_about_this_project_as_them(
    guarded_app, platform, pid
):
    client, token = guarded_app
    platform.answers["alice"] = VIEWER
    alice = token("alice")
    assert client.get(f"/p/{pid}", headers=_auth(alice)).status_code == 200
    assert platform.asked
    assert set(platform.asked) == {(f"/authz/projects/{pid}", alice)}


def test_the_gateway_token_header_is_the_same_caller(guarded_app, platform, pid):
    client, token = guarded_app
    platform.answers["alice"] = VIEWER
    headers = {"X-Auth-Request-Access-Token": token("alice")}
    assert client.get(f"/p/{pid}", headers=headers).status_code == 200


def test_a_viewer_cannot_change_the_project(guarded_app, platform, pid):
    client, token = guarded_app
    platform.answers["alice"] = VIEWER
    assert client.post(f"/p/{pid}/projects", headers=_auth(token("alice"))).status_code == 403


def test_an_editor_gets_past_the_door(guarded_app, platform, pid):
    """Past it the call answers on its own merits: an upload of `{}` is not an
    AI Card. What matters is that the refusal is no longer about who is asking."""
    client, token = guarded_app
    platform.answers["alice"] = EDITOR
    response = client.post(
        f"/p/{pid}/projects",
        headers=_auth(token("alice")),
        files={"card": ("card.json", b"{}", "application/json")},
        data={"name": "anything"},
    )
    assert response.status_code not in (401, 403, 404)


def test_an_admin_is_let_in_because_the_platform_says_so(guarded_app, platform, pid):
    """This service has no admin rule of its own any more: the platform's answer is the rule."""
    client, token = guarded_app
    platform.answers["root"] = ADMIN
    assert client.get(f"/p/{pid}", headers=_auth(token("root", ("admin",)))).status_code == 200


def test_no_token_is_401_and_the_platform_is_not_asked(guarded_app, platform, pid):
    client, _ = guarded_app
    assert client.get(f"/p/{pid}").status_code == 401
    assert platform.asked == []


@pytest.mark.parametrize(
    "path", ["/p/abc", "/p/mcas/projects", "/p/..%2F..%2Fplatform", f"/p/{PID}x/objectives"]
)
def test_a_path_that_is_not_a_project_is_not_found_and_nobody_is_asked(guarded_app, platform, path):
    client, token = guarded_app
    platform.answers["alice"] = ADMIN
    assert client.get(path, headers=_auth(token("alice"))).status_code == 404
    assert platform.asked == []


def test_a_platform_that_does_not_answer_lets_nobody_in(guarded_app, platform, pid):
    client, token = guarded_app
    platform.down = True
    assert client.get(f"/p/{pid}", headers=_auth(token("alice"))).status_code == 503


def test_the_health_check_stays_open(guarded_app):
    client, _ = guarded_app
    assert client.get("/health").status_code == 200
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_project_access.py -q`
Expected: collection error `ImportError: cannot import name 'fetch_access' from 'aisc_control_objectives.access'`.

- [ ] **Step 3: Make httpx a runtime dependency.**

Run: `cd apps/control-objectives && uv add "httpx>=0.27"`
Expected: `pyproject.toml` lists `httpx>=0.27` under `dependencies`, and `uv.lock` is updated. httpx is already locked, as a dependency of `openai`, so the lock changes only in its dependency lists.

- [ ] **Step 4: Rewrite `access.py`.** Replace the whole file with:

```python
"""May this person be here, and may they change anything.

Signing in happens at the gateway and has already happened by the time a
request arrives. This answers the other question, and does not answer it
itself: a project belongs to the people in it, the platform is the one place
that knows who, and this asks it (GET {PLATFORM_URL}/authz/projects/{pid},
with the caller's own token), exactly as the controls app does
(apps/controls/src/lib/access/projectAccess.ts).

This door answers early, for every path under /p/{pid}. It is not the rule
that protects a project's data: the one helper that opens a project database
(db/workspaces.py) asks the platform again, about the very pid it opens.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, unquote

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from aisc_identity.headers import token_from_headers
from aisc_identity.service import Misconfigured, NotAuthenticated, caller_from_headers

logger = logging.getLogger(__name__)

Verdict = Literal["allow", "not-found", "forbidden", "unavailable"]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Everything to do with one project lives under /p/{pid}.
_PROJECT_PATH = re.compile(r"^/p/([^/]+)")

#: Only a project id opens a project here: it names the project's database.
PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass(frozen=True)
class Access:
    """What the platform said about one caller and one project."""

    #: viewer, editor, owner, or None for somebody who is not in the project
    role: str | None
    #: the realm role that administers the platform, which is not a membership
    admin: bool = False
    #: the platform's own answer to "may they change it"
    may_write: bool = False


def project_from_path(path: str) -> str | None:
    """The project a path is inside, or None if it is not inside one."""
    found = _PROJECT_PATH.match(path or "")
    return unquote(found.group(1)) if found else None


def decide(method: str, access: Access | None) -> Verdict:
    """What to do about a request, given what the platform said.

    None means the question could not be answered, and then nobody gets in:
    failing open would turn a platform that is not there into an open door.
    """
    if access is None:
        return "unavailable"
    if access.role is None:
        # Not 403: the project's name is often a customer's, and 403 would
        # confirm it exists.
        return "not-found"
    if method.upper() in SAFE_METHODS:
        return "allow"
    return "allow" if access.may_write else "forbidden"


def fetch_access(
    project: str,
    token: str | None,
    *,
    platform_url: str,
    transport: httpx.BaseTransport | None = None,
) -> Access | None:
    """Ask the platform what this caller is to this project. None: no answer."""
    base = (platform_url or "").rstrip("/")
    if not base:
        return None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(transport=transport, timeout=5.0) as client:
            response = client.get(
                f"{base}/authz/projects/{quote(project, safe='')}", headers=headers
            )
        if response.status_code != 200:
            return None
        body = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("the platform did not answer about project %s", project)
        return None
    if not isinstance(body, dict):
        return None
    return Access(
        role=body.get("role") or None,
        admin=bool(body.get("admin")),
        may_write=bool(body.get("may_write")),
    )


class ProjectAccess(BaseHTTPMiddleware):
    """Every page and endpoint under /p/{pid} goes through this.

    A middleware rather than a dependency per route: a route added later is
    covered by having been added, instead of by somebody remembering.
    """

    def __init__(self, app, platform_url: str, transport: httpx.BaseTransport | None = None):
        super().__init__(app)
        self._platform_url = platform_url
        self._transport = transport

    async def dispatch(self, request, call_next):
        project = project_from_path(request.url.path)
        if project is None:
            return await call_next(request)
        if not PID.match(project):
            # Not a project id, so not a project: its database could not even
            # be named. Nobody is asked about it.
            return PlainTextResponse("No such project.", status_code=404)
        try:
            caller_from_headers(request.headers)
        except NotAuthenticated as exc:
            return PlainTextResponse(f"Sign in first: {exc}", status_code=401)
        except Misconfigured as exc:
            return PlainTextResponse(str(exc), status_code=500)

        access = await run_in_threadpool(
            fetch_access,
            project,
            token_from_headers(request.headers),
            platform_url=self._platform_url,
            transport=self._transport,
        )
        verdict = decide(request.method, access)
        if verdict == "allow":
            return await call_next(request)
        if verdict == "not-found":
            return PlainTextResponse("No such project.", status_code=404)
        if verdict == "forbidden":
            return PlainTextResponse(
                "You can read this project but not change it.", status_code=403
            )
        return PlainTextResponse(
            "The platform is not answering, so who may be here cannot be established.",
            status_code=503,
        )
```

- [ ] **Step 5: Fit it in the app and the server.**

In `api/app.py`, replace the `engine=None,` parameter (line 71) with:

```python
    platform_url: str | None = None,
    platform_transport=None,
```

Replace lines 76-81, the comment and the `if engine is not None:` block, with:

```python
    # Who may be in a project, and who may change it: the platform says. Added
    # before CORS so that CORS stays the outermost middleware and a refusal
    # still carries its headers. None means no door, for tests of the flow; an
    # empty string still fits one, which then refuses everything with 503.
    if platform_url is not None:
        app.add_middleware(ProjectAccess, platform_url=platform_url, transport=platform_transport)
```

In `server.py`, replace lines 240-242, the comment and `engine=repository.engine,`, with:

```python
        # Who is in which project: asked of the platform, with the caller's token.
        platform_url=os.environ.get("PLATFORM_URL", ""),
```

- [ ] **Step 6: Run the tests.**

Run: `cd apps/control-objectives && uv run pytest -q`
Expected: all PASS. The two old `role_in_project` tests are gone with the function. `conftest.py`'s `project_member` fixture is now unused; Task 4 removes it.

- [ ] **Step 7: Tell the service where the platform is.** In `docker-compose.development.yml`, under `control-objectives.environment`, after the `LAUNCHER_URL:` line (line 341), add:

```yaml
      # Who is in which project: asked of the platform on every request inside
      # one, with the caller's token, as controls does.
      PLATFORM_URL: http://platform:8000
```

Replace its `depends_on` (lines 363-365) with:

```yaml
    depends_on:
      control-objectives-migrate:
        condition: service_completed_successfully
      platform:
        condition: service_started
```

- [ ] **Step 8: Rebuild and check the door on the running stack.**

```bash
set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build control-objectives
scripts/verify-rbac.sh 2>&1 | grep -i "control objectives\|nobody is in\|anonymous"
```

Expected: `control objectives lets a member in (200)`, `and asks an anonymous caller who they are (401)` and `a project nobody is in is not found (404)` all PASS. `control-objectives-migrate` runs the old `alembic upgrade head` on the shared schema and finds nothing to do. That is still the old image history, so it is safe here.

- [ ] **Step 9: Commit.**

```bash
(cd apps/control-objectives && git add src/aisc_control_objectives/access.py src/aisc_control_objectives/api/app.py src/aisc_control_objectives/server.py pyproject.toml uv.lock tests/test_project_access.py && git commit -m "The door asks the platform who may be in a project")
git add -p docker-compose.development.yml   # only the PLATFORM_URL and depends_on hunks
git commit -m "Control objectives asks the platform who is in a project"
```

---

### Task 3: A project database's name, and where it is

**Files:**
- Create: `apps/control-objectives/src/aisc_control_objectives/db/project_databases.py`
- Modify: `apps/control-objectives/src/aisc_control_objectives/settings.py` (whole file, 29 lines)
- Test: `apps/control-objectives/tests/test_project_database_name.py`

**Interfaces:**
- Produces:
  - `class NotAPid(ValueError)`
  - `database_name(pid: str | UUID) -> str` (raises `NotAPid`)
  - `database_url(pid: str | UUID, template: str) -> str` (raises `ValueError` when the template has no `{database}`)
  - `settings.project_database_url(env: Mapping[str, str] | None = None) -> str`: reads `PROJECT_DATABASE_URL` and names the `postgresql+psycopg` driver. The default is `postgresql+psycopg://control_objectives_rw:control_objectives_rw@localhost:5432/{database}`.

- [ ] **Step 1: Write the failing test.** Create `tests/test_project_database_name.py`:

```python
"""A project's database is named after its pid, as the platform names it."""
import pytest

from aisc_control_objectives.db.project_databases import NotAPid, database_name, database_url
from aisc_control_objectives.settings import project_database_url

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
TEMPLATE = "postgresql+psycopg://control_objectives_rw:pw@postgres:5432/{database}"


def test_the_database_is_named_after_the_pid():
    # The same example is asserted in platform/tests/test_project_databases.py
    # and apps/controls/test/unit/projectDb.test.ts: three places, one rule.
    assert database_name(PID) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"
    assert database_name(PID.upper()) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


@pytest.mark.parametrize(
    "bad", ["", "abc", "../platform", PID + "x", "project_x; drop database platform"]
)
def test_anything_but_a_pid_is_refused(bad):
    with pytest.raises(NotAPid):
        database_name(bad)


def test_the_template_is_filled():
    assert database_url(PID, TEMPLATE) == (
        "postgresql+psycopg://control_objectives_rw:pw@postgres:5432/"
        "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"
    )


def test_a_template_with_nowhere_to_put_the_database_is_refused():
    with pytest.raises(ValueError, match=r"\{database\}"):
        database_url(PID, "postgresql+psycopg://x@y/platform")


def test_the_configured_template_names_the_driver_sqlalchemy_needs():
    env = {"PROJECT_DATABASE_URL": "postgresql://u:p@postgres:5432/{database}"}
    assert project_database_url(env) == "postgresql+psycopg://u:p@postgres:5432/{database}"


def test_a_configured_template_without_a_place_for_the_database_is_refused():
    with pytest.raises(ValueError, match=r"\{database\}"):
        project_database_url({"PROJECT_DATABASE_URL": "postgresql://u:p@postgres:5432/platform"})
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_project_database_name.py -q`
Expected: `ModuleNotFoundError: No module named 'aisc_control_objectives.db.project_databases'`.

- [ ] **Step 3: Implement.** Create `src/aisc_control_objectives/db/project_databases.py`:

```python
"""A project's own database: its name, and how this service reaches it.

Every project has a database of its own, made by the platform when the project
is made (platform/platform_service/projectdb.py). This service keeps a
project's assessments, and the control objectives they are assessed against,
in that project's database and nowhere else, so a query that forgets to filter
still cannot reach another project.

The pid becomes part of a connection string, so it is checked here, whatever
checked it before.
"""

from __future__ import annotations

import re
from uuid import UUID

_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class NotAPid(ValueError):
    """Only a project id may name a database: anything else is refused unread."""


def database_name(pid: str | UUID) -> str:
    text = str(pid).lower()
    if not _PID.match(text):
        raise NotAPid(f"not a project id: {text!r}")
    return "project_" + text.replace("-", "")


def database_url(pid: str | UUID, template: str) -> str:
    """The URL of this project's database: `template` with its name in `{database}`."""
    if "{database}" not in template:
        raise ValueError("PROJECT_DATABASE_URL must contain {database}")
    return template.replace("{database}", database_name(pid))
```

Replace `settings.py` with:

```python
"""Where the databases are.

Every project has a database of its own. `PROJECT_DATABASE_URL` says how to
reach one: a URL with `{database}` where the project's database name goes
(db/project_databases.py fills it in). The driver is named explicitly
(`postgresql+psycopg`) because SQLAlchemy still defaults `postgresql://` to
psycopg2, which is not what is installed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: The shared platform database, as before. Only `database_url()` still reads
#: it, until the service stops using it (Task 7).
DEFAULT_URL = (
    "postgresql+psycopg://control_objectives_rw:control_objectives_rw"
    "@localhost:5432/platform"
)

DEFAULT_PROJECT_DATABASE_URL = (
    "postgresql+psycopg://control_objectives_rw:control_objectives_rw"
    "@localhost:5432/{database}"
)


def _with_driver(url: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    # Prisma-style query strings (?schema=public) mean nothing to SQLAlchemy.
    return url.split("?", 1)[0]


def database_url(env: Mapping[str, str] | None = None) -> str:
    """The database to use, with the driver SQLAlchemy needs."""
    return _with_driver((env or os.environ).get("DATABASE_URL") or DEFAULT_URL)


def project_database_url(env: Mapping[str, str] | None = None) -> str:
    """How to reach one project's database, with `{database}` still to fill."""
    url = (env or os.environ).get("PROJECT_DATABASE_URL") or DEFAULT_PROJECT_DATABASE_URL
    if "{database}" not in url:
        raise ValueError(
            "PROJECT_DATABASE_URL must contain {database}, where the project's database name goes"
        )
    return _with_driver(url)
```

- [ ] **Step 4: Run it.**

Run: `uv run pytest tests/test_project_database_name.py -q`
Expected: all 10 PASS. Then `uv run pytest -q`: all PASS.

- [ ] **Step 5: Commit** (inside `apps/control-objectives`).

```bash
git add src/aisc_control_objectives/db/project_databases.py src/aisc_control_objectives/settings.py tests/test_project_database_name.py
git commit -m "A project database is named after its pid, as the platform names it"
```

---

### Task 4: The data layer without a project

**Files:**
- Modify: `apps/control-objectives/src/aisc_control_objectives/db/tables.py` (whole file)
- Delete: `apps/control-objectives/alembic/versions/20260914171611_projects_graphs_risks_runs.py`, `20260914191531_drop_the_profile_run_and_the_answer.py`, `20260921220000_an_assessment_belongs_to_a_project.py`, `20260922100000_the_project_link_is_named_project_id.py`
- Create: `apps/control-objectives/alembic/versions/20260923120000_project_database.py`
- Modify: `apps/control-objectives/alembic/env.py` (whole file)
- Create: `apps/control-objectives/src/aisc_control_objectives/db/migrations.py`
- Modify: `apps/control-objectives/src/aisc_control_objectives/db/repository.py`
  - imports at 16-18, `ProjectRecord` at 33-49, `__init__`/`engine`/`reopened`/`create_all` at 52-88
  - `create` at 92-109, `list` at 200-209
  - the renames through 111-289
- Modify: `apps/control-objectives/src/aisc_control_objectives/projects.py` (`create` at 65-76, `list` at 109-111)
- Modify: `apps/control-objectives/src/aisc_control_objectives/api/app.py` (lines 128, 149, 164-166, 283 and 290)
- Modify: `apps/control-objectives/src/aisc_control_objectives/server.py:226`
- Test: rewrite `apps/control-objectives/tests/conftest.py`. Edit `tests/test_repository.py`.

**Interfaces:**
- Consumes: `database_name`, `database_url` (Task 3). `platform/project-template/0003_control_objectives.sql` (Task 1). The tests apply it themselves.
- Produces:
  - Tables in schema `control_objectives`: `assessment`, `graph`, `risk`, `mapped_objective`, `mapping_run`, `objective`, `catalogue` and `alembic_version`. There is no `project` table, no `project_id` column, and no key outside the schema.
  - `migrations.migrate_database(engine: Engine) -> None`: Alembic `upgrade head` on that engine, one at a time per database (advisory lock).
  - `repository.project_engine(url: str) -> Engine`: `pool_size=2, max_overflow=0`.
  - `ProjectRepository(engine: Engine, objectives_digest: str = "")`. `.engine`, `.create(name, ontology, jsonld)`, `.list()`, and `get`/`rate`/`save_mapping_run`/`replace_ontology`/`delete`/`orphan_rows` are unchanged. `ProjectRecord` loses `project`.
  - `Projects.create(name, jsonld, raw)` and `Projects.list()`.
  - Test helpers in `tests/conftest.py`:
    - `PROJECT_DATABASE_URL`, `su(sql=None, database="postgres", script=None) -> str` and `has_database() -> bool`
    - `make_project_database(provisioned: bool = True) -> str` (a pid) and `project_url(pid) -> str`
    - fixtures `postgres`, `project_pid`, `fresh_project`, `repository` and `platform_project`

- [ ] **Step 1: Write the test support.** Replace `tests/conftest.py` with:

```python
"""Shared fixtures: the frozen AI Card, the catalogue, and project databases.

Every project has a database of its own, so the suite makes its own:
throwaway `project_<hex>` databases, created the way the platform creates them
(as the superuser, inside the postgres container, applying
platform/project-template/0003_control_objectives.sql), and dropped at the end
of the run. It drops only the databases it made. The service is tested
connecting as its real role, control_objectives_rw, which is what proves the
template's grants.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from functools import cache
from pathlib import Path

import pytest
from sqlalchemy import text

from aisc_control_objectives.control_objectives import load_control_objectives
from aisc_control_objectives.db.migrations import migrate_database
from aisc_control_objectives.db.project_databases import database_name, database_url
from aisc_control_objectives.db.repository import ProjectRepository, project_engine

FIXTURES = Path(__file__).parent / "fixtures"
#: This module's per-project template, from the platform (the repo root is three up).
TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "platform" / "project-template" / "0003_control_objectives.sql"
)
PROJECT_DATABASE_URL = os.environ.get(
    "CONTROL_OBJECTIVES_TEST_PROJECT_DATABASE_URL",
    "postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:5432/{database}",
)
_made: list[str] = []


def su(sql: str | None = None, database: str = "postgres", script: str | None = None) -> str:
    """Run SQL as the Postgres superuser, inside the postgres container.

    The superuser's name and password never leave the container: psql reads
    POSTGRES_USER there, and nothing is echoed. `database` is always a name
    this suite made or `postgres`, never input.
    """
    command = ["docker", "exec", "-i"]
    if sql is not None:
        command += ["-e", f"SQL={sql}"]
    psql = f'psql -U "$POSTGRES_USER" -d {database} -v ON_ERROR_STOP=1 -At'
    command += ["postgres", "sh", "-c", psql + (' -c "$SQL"' if sql is not None else "")]
    done = subprocess.run(command, input=script, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"psql as the superuser failed: {done.stderr.strip()}")
    return done.stdout.strip()


@cache
def has_database() -> bool:
    if not TEMPLATE.is_file():
        return False
    try:
        return su("SELECT 1") == "1"
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return False


def make_project_database(provisioned: bool = True) -> str:
    """A throwaway project database. Returns its pid.

    provisioned: the platform applied this module's template to it. Otherwise
    it is a project database this module was never given a place in: PUBLIC
    may not connect (as template 0001 leaves every project database), and
    there is no control_objectives schema.
    """
    pid = str(uuid.uuid4())
    name = database_name(pid)
    su(f"CREATE DATABASE {name}")
    _made.append(name)
    if provisioned:
        su(database=name, script=TEMPLATE.read_text())
    else:
        su(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC")
    return pid


def project_url(pid: str) -> str:
    return database_url(pid, PROJECT_DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def _drop_only_the_databases_this_run_made():
    yield
    for name in _made:
        su(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture()
def postgres():
    if not has_database():
        pytest.skip(
            "needs the running postgres container and "
            "platform/project-template/0003_control_objectives.sql"
        )


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def mcas_graph():
    """The MCAS system's filled AIRO graph, as its qualification exports it."""
    from aisc_control_objectives.models.ontology import Ontology

    return Ontology.from_jsonld(json.loads((FIXTURES / "mcas.ontology.jsonld").read_text()))


@pytest.fixture(scope="session")
def objectives():
    return load_control_objectives()


@pytest.fixture(scope="session")
def project_pid() -> str:
    """One migrated project database for the suite. Tests empty it after themselves."""
    if not has_database():
        pytest.skip("needs the running postgres container")
    pid = make_project_database()
    engine = project_engine(project_url(pid))
    try:
        migrate_database(engine)
    finally:
        engine.dispose()
    return pid


@pytest.fixture()
def fresh_project(postgres) -> str:
    """A project database of one's own for one test: provisioned, not migrated."""
    return make_project_database()


@pytest.fixture()
def repository(project_pid, objectives):
    """A repository on the suite's project database, emptied afterwards."""
    engine = project_engine(project_url(project_pid))
    yield ProjectRepository(engine, objectives_digest=objectives.digest)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE control_objectives.assessment CASCADE"))
    engine.dispose()


@pytest.fixture()
def platform_project(project_pid, repository) -> str:
    """The project a test works in: the suite's project database."""
    return project_pid
```

- [ ] **Step 2: Rewrite the repository tests onto it.** In `tests/test_repository.py`:
  1. Delete every `project=platform_project, ` argument to `repository.create(`. For example, `repository.create(project=platform_project, name="MCAS", …)` becomes `repository.create(name="MCAS", …)`.
  2. Replace `repository.list(platform_project)` (line 128) with `repository.list()`.
  3. Replace the whole `class TestOneDatabase` (from line 168 to the end of the file) with:

```python
class TestTheDatabaseIsTheProject:
    """This service's tables are in the project's own database: nothing in
    them names a project, and nothing points outside this schema."""

    def test_its_tables_are_these_and_none_is_called_project(self, repository):
        from sqlalchemy import inspect

        inspector = inspect(repository.engine)
        assert set(inspector.get_table_names(schema="control_objectives")) == {
            "alembic_version", "assessment", "graph", "risk", "mapped_objective",
            "mapping_run", "objective", "catalogue",
        }
        assert inspector.get_table_names(schema="public") == []

    def test_no_column_names_a_project(self, repository):
        from sqlalchemy import inspect

        inspector = inspect(repository.engine)
        for table in inspector.get_table_names(schema="control_objectives"):
            names = {c["name"] for c in inspector.get_columns(table, schema="control_objectives")}
            assert "project_id" not in names, table

    def test_no_key_points_outside_this_schema(self, repository):
        from sqlalchemy import text

        with repository.engine.connect() as connection:
            outside = connection.execute(text(
                "SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.confrelid"
                " WHERE c.contype = 'f'"
                "   AND c.connamespace = 'control_objectives'::regnamespace"
                "   AND r.relnamespace <> 'control_objectives'::regnamespace"
            )).scalar()
        assert outside == 0

    def test_two_projects_share_nothing(self, repository, ontology, graph_json, objectives):
        from conftest import make_project_database, project_url

        from aisc_control_objectives.db.migrations import migrate_database
        from aisc_control_objectives.db.repository import ProjectRepository, project_engine

        other_engine = project_engine(project_url(make_project_database()))
        migrate_database(other_engine)
        other = ProjectRepository(other_engine, objectives_digest=objectives.digest)
        try:
            mine = repository.create(name="mine", ontology=ontology, jsonld=graph_json)
            assert [record.id for record in repository.list()] == [mine.id]
            assert other.list() == []
            assert other.get(mine.id) is None
        finally:
            other_engine.dispose()
```

- [ ] **Step 3: Run them and watch them fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_repository.py -q`
Expected: `ModuleNotFoundError: No module named 'aisc_control_objectives.db.migrations'`, raised from `conftest.py`.

- [ ] **Step 4: The tables.** Replace `db/tables.py` with:

```python
"""The tables of one project's control objectives, in that project's database.

A table per real thing, `JSONB` only where nothing queries inside, cascading
deletes from the assessment, and `created_at`/`updated_at` on the root. Two
ideas worth keeping from `KnowledgeGraph`:

- **The uploaded graph is kept as the bytes that were uploaded**, not as a
  re-serialisation of the parse, so the file someone was given and the row are
  the same document.
- **It carries a digest**, its identity, so re-uploading the same graph is a
  no-op rather than a silent rebuild.

The database is the project: nothing here names one, and nothing points
outside this schema. The control objectives an assessment is scored against
are here too (`objective`, `catalogue`): this project's own copy.

What is *not* here: scores and tiers. They are a pure function of the
catalogue, the ratings and the mapping, so storing them would only let them go
stale. `objectives_digest` records which catalogue an assessment was made
against.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: This service's schema in each project database, made by the platform
#: (platform/project-template/0003_control_objectives.sql).
SCHEMA = "control_objectives"


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Assessment(Base):
    """One system being assessed in this project. The aggregate everything else hangs off.

    It was called `project` while every project shared one database, and it
    carried the platform project it belonged to. The database is the project
    now, so that column is gone, and the name is left to the project.
    """

    __tablename__ = "assessment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    system_name: Mapped[str] = mapped_column(Text, default="")
    #: From the graph, so a corrected re-export finds its assessment.
    qualification_id: Mapped[str] = mapped_column(Text, default="", index=True)
    #: Which of this project's catalogues this was assessed against.
    objectives_digest: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    graph: Mapped[Graph | None] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )
    risks: Mapped[list[Risk]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan",
        order_by="Risk.position", lazy="selectin",
    )
    mapping_run: Mapped[MappingRunRow | None] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )


class Graph(Base):
    """The uploaded AIRO graph: the bytes, and what they are."""

    __tablename__ = "graph"

    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE"), primary_key=True
    )
    #: Exactly what was uploaded. An export serves these bytes back.
    jsonld: Mapped[str] = mapped_column(Text, nullable=False)
    #: sha256 of the bytes: the graph's identity.
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    risks: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assessment: Mapped[Assessment] = relationship(back_populates="graph")


class Risk(Base):
    """One AIRO chain, flattened, with the assessor's severity on it."""

    __tablename__ = "risk"
    __table_args__ = (UniqueConstraint("assessment_id", "risk_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE"), index=True
    )
    #: The graph's own node id ("risk2").
    risk_id: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    short_label: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    vulnerability: Mapped[str] = mapped_column(Text, default="")
    consequence: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    stakeholder: Mapped[str] = mapped_column(Text, default="")
    control: Mapped[str] = mapped_column(Text, default="")
    follow_up_control: Mapped[str] = mapped_column(Text, default="")
    areas: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    vair_terms: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    provenance: Mapped[str] = mapped_column(Text, default="form")
    #: The assessor's 1-5. The irreplaceable part: a model did not produce it.
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="risks")
    mapped: Mapped[list[MappedObjectiveRow]] = relationship(
        back_populates="risk", cascade="all, delete-orphan", lazy="selectin"
    )


class MappedObjectiveRow(Base):
    """One objective a risk was mapped to, and the quote that supports it."""

    __tablename__ = "mapped_objective"
    __table_args__ = (UniqueConstraint("risk_row_id", "objective_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_row_id: Mapped[int] = mapped_column(
        ForeignKey("risk.id", ondelete="CASCADE"), index=True
    )
    #: "R1.1". No foreign key: a mapping is checked against the catalogue
    #: when it is made (risk_mapping.run_controls), and kept as it was made.
    objective_id: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")

    risk: Mapped[Risk] = relationship(back_populates="mapped")


class MappingRunRow(Base):
    """How the second agentic workflow went. The mappings themselves are rows
    on the risks; this is the record of the run that bought them."""

    __tablename__ = "mapping_run"

    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE"), primary_key=True
    )
    findings: Mapped[list] = mapped_column(JSONB, default=list)
    stops: Mapped[dict] = mapped_column(JSONB, default=dict)   # risk id -> its own stop
    stop: Mapped[str] = mapped_column(Text, default="clean")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(Text, default="")
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assessment: Mapped[Assessment] = relationship(back_populates="mapping_run")


class Objective(Base):
    """One control objective of this project's catalogue: a row of the CSV it
    was copied from, verbatim (control_objectives.COLUMNS)."""

    __tablename__ = "objective"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    macro_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    legal_basis: Mapped[str] = mapped_column(Text, nullable=False)
    sub_requirement_label: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    assessment_mode: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, default="")
    standards_grounding: Mapped[str] = mapped_column(Text, default="")
    grounding_tier_flag: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Catalogue(Base):
    """Which CSV this project's objectives were copied from, and when.

    One row once the copy is made, none before: its presence is what says the
    project has its objectives.
    """

    __tablename__ = "catalogue"
    __table_args__ = (CheckConstraint("id = 1", name="catalogue_one_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    copied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
```

- [ ] **Step 5: One baseline instead of the history.**

```bash
cd apps/control-objectives
git rm -q alembic/versions/20260914171611_projects_graphs_risks_runs.py alembic/versions/20260914191531_drop_the_profile_run_and_the_answer.py alembic/versions/20260921220000_an_assessment_belongs_to_a_project.py alembic/versions/20260922100000_the_project_link_is_named_project_id.py
```

Create `alembic/versions/20260923120000_project_database.py`:

```python
"""the database is the project

Every project has a database of its own, and this is the whole of this
service's schema in one, from empty. The history before it built tables in the
one shared database and pointed them at core.project, which a project database
does not have, so it is replaced rather than continued. The shared schema it
built is left as it is: retiring it is a separate plan.

Revision ID: 5d3c9e1a7b20
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5d3c9e1a7b20"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessment",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("system_name", sa.Text(), nullable=False),
        sa.Column("qualification_id", sa.Text(), nullable=False),
        sa.Column("objectives_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessment_qualification_id", "assessment", ["qualification_id"])
    op.create_table(
        "graph",
        sa.Column("assessment_id", sa.String(length=32), nullable=False),
        sa.Column("jsonld", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("risks", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assessment_id"),
    )
    op.create_table(
        "mapping_run",
        sa.Column("assessment_id", sa.String(length=32), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stops", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stop", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assessment_id"),
    )
    op.create_table(
        "risk",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assessment_id", sa.String(length=32), nullable=False),
        sa.Column("risk_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("short_label", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("vulnerability", sa.Text(), nullable=False),
        sa.Column("consequence", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("stakeholder", sa.Text(), nullable=False),
        sa.Column("control", sa.Text(), nullable=False),
        sa.Column("follow_up_control", sa.Text(), nullable=False),
        sa.Column("areas", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("vair_terms", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "risk_id"),
    )
    op.create_index("ix_risk_assessment_id", "risk", ["assessment_id"])
    op.create_table(
        "mapped_objective",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("risk_row_id", sa.Integer(), nullable=False),
        sa.Column("objective_id", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["risk_row_id"], ["risk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("risk_row_id", "objective_id"),
    )
    op.create_index("ix_mapped_objective_risk_row_id", "mapped_objective", ["risk_row_id"])
    op.create_table(
        "objective",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("macro_requirement", sa.Text(), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=False),
        sa.Column("sub_requirement_label", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("assessment_mode", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("standards_grounding", sa.Text(), nullable=False),
        sa.Column("grounding_tier_flag", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "catalogue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="catalogue_one_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("catalogue")
    op.drop_table("objective")
    op.drop_index("ix_mapped_objective_risk_row_id", table_name="mapped_objective")
    op.drop_table("mapped_objective")
    op.drop_index("ix_risk_assessment_id", table_name="risk")
    op.drop_table("risk")
    op.drop_table("mapping_run")
    op.drop_table("graph")
    op.drop_index("ix_assessment_qualification_id", table_name="assessment")
    op.drop_table("assessment")
```

Replace `alembic/env.py` with:

```python
"""Alembic's entry point, for one project database at a time.

The service migrates a project's database the first time it opens it, and the
control-objectives-migrate service migrates every one at start; both hand the
connection over in `config.attributes["connection"]` (db/migrations.py). Run
by hand, it migrates the one database DATABASE_URL names.

The schema is made by the platform (platform/project-template/0003_control_objectives.sql);
this role may not make schemas, so a database without it is refused, naming
why. Migrations run with `search_path` set to the schema, so an unqualified
`op.create_table` lands in it, and the version table lives there too. An
advisory lock makes two migrators of the same database take turns.
"""

from alembic import context
from sqlalchemy import create_engine, text

from aisc_control_objectives.db.tables import SCHEMA, Base
from aisc_control_objectives.settings import database_url

target_metadata = Base.metadata

#: Any constant will do; it only has to be the same for every migrator.
_LOCK = 0x636F6D6967


def _migrate(connection) -> None:
    exists = connection.execute(
        text("SELECT to_regnamespace(:s) IS NOT NULL"), {"s": SCHEMA}
    ).scalar()
    if not exists:
        raise RuntimeError(
            f"schema {SCHEMA} is missing: the platform has not provisioned this "
            "database for control objectives (platform/project-template/0003_control_objectives.sql)"
        )
    connection.execute(text(f"SET search_path TO {SCHEMA}"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK})
        context.run_migrations()


def run_migrations_online() -> None:
    given = context.config.attributes.get("connection")
    if given is not None:
        _migrate(given)
        return
    engine = create_engine(database_url())
    with engine.begin() as connection:
        _migrate(connection)


run_migrations_online()
```

Create `src/aisc_control_objectives/db/migrations.py`:

```python
"""Bring one project database to this service's schema.

Alembic, handed the connection, so the service and the migrate service run the
same migrations the same way, and neither needs a URL in the environment.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

#: The repository root: /app in the image, where alembic.ini and alembic/ are copied.
ROOT = Path(__file__).resolve().parents[3]


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


def migrate_database(engine: Engine) -> None:
    """`alembic upgrade head` on this engine's database, in one transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
```

- [ ] **Step 6: The repository and the service lose the project argument.**

In `db/repository.py`:
- Replace lines 16-18 (the imports) with:

```python
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
```

- In `ProjectRecord`, delete lines 37-38 (`#: The platform project…` and `project: str`).
- Replace lines 52-88 (`__init__` through `create_all`) with:

```python
def project_engine(url: str) -> Engine:
    """An engine on one project database. Two connections at most: there is a
    pool per project, and Postgres allows 100 connections in all (the roadmap's
    known costs)."""
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=0)


class ProjectRepository:
    """One project's assessments, in that project's database."""

    def __init__(self, engine: Engine, objectives_digest: str = ""):
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._objectives_digest = objectives_digest

    @property
    def engine(self) -> Engine:
        """The connections to this project's database: used to migrate it, and
        to give it its own copy of the control objectives."""
        return self._engine

    def reopened(self) -> ProjectRepository:
        """A second repository on a new engine to the same database: what a restart would give."""
        return ProjectRepository(
            project_engine(self._engine.url.render_as_string(hide_password=False)),
            self._objectives_digest,
        )
```

- Replace `create` (lines 92-109) with:

```python
    def create(self, name: str, ontology: Ontology, jsonld: str) -> ProjectRecord:
        """A new assessment in this project. There is no project argument: this
        database is the project."""
        with self._sessions.begin() as session:
            project = tables.Assessment(
                id=uuid.uuid4().hex[:12],
                name=name,
                system_name=ontology.system_name,
                qualification_id=ontology.qualification_id,
                objectives_digest=self._objectives_digest,
            )
            session.add(project)
            self._attach_card(session, project, ontology, jsonld)
            session.flush()
            return self._to_record(project)
```

- Replace `list` (lines 200-209) with:

```python
    def list(self) -> list[ProjectRecord]:
        """Every assessment in this project, newest first. Another project's
        are in another database."""
        with self._sessions() as session:
            rows = session.scalars(
                select(tables.Assessment).order_by(tables.Assessment.updated_at.desc())
            ).all()
            return [self._to_record(row) for row in rows]
```

- Apply these renames everywhere else in the file:
  - `tables.Project` becomes `tables.Assessment`.
  - `tables.Risk.project_id` becomes `tables.Risk.assessment_id`.
  - `tables.MappingRunRow.project_id` becomes `tables.MappingRunRow.assessment_id`.
  - `project_id=project.id` in the `tables.Graph(` and `tables.Risk(` constructors (lines 232 and 241) becomes `assessment_id=project.id`.
  - `project_id=project_id,` in the `tables.MappingRunRow(` constructor (line 177) becomes `assessment_id=project_id,`.
  - In `_to_record`, delete the line `project=project.project_id,` (line 283).
  - In `orphan_rows`, `tables.Risk.project_id.in_(select(tables.Project.id))` becomes `tables.Risk.assessment_id.in_(select(tables.Assessment.id))`.

Check: `grep -n "project_id\b\|tables\.Project\b\|core" src/aisc_control_objectives/db/repository.py` shows only method parameters named `project_id` (the assessment id the routes pass).

In `projects.py`, replace `create` (lines 65-76) with:

```python
    def create(self, name: str, jsonld: str, raw: object) -> ProjectView:
        """Take the AI Card. Its risks are what the assessor rates next."""
        ontology = Ontology.from_jsonld(raw)
        record = self._repository.create(
            name=name or ontology.system_name, ontology=ontology, jsonld=jsonld,
        )
        return self.view(record.id)
```

Replace `list` (lines 109-111) with:

```python
    def list(self) -> list[ProjectView]:
        """The assessments of this project: the only ones in its database."""
        return [self._derive(record) for record in self._repository.list()]
```

In `api/app.py`, make the routes fit the new signatures. Task 7 rewrites this file.
- Line 128: `len(projects.list(project))` becomes `len(projects.list())`.
- Line 149: `projects.list(project)` becomes `projects.list()`.
- Lines 164-166: `projects.create(project=project, name=name, jsonld=…, raw=raw)` becomes `projects.create(name=name, jsonld=raw_bytes.decode("utf-8"), raw=raw)`.
- Line 283: `projects.create(project=project, name=name, jsonld=json.dumps(card), raw=card)` becomes `projects.create(name=name, jsonld=json.dumps(card), raw=card)`.
- Line 290: `projects.list(project)` becomes `projects.list()`.

In `server.py:226`, replace `ProjectRepository(database_url(), objectives_digest=objectives.digest)` with `ProjectRepository(project_engine(database_url()), objectives_digest=objectives.digest)`. Change the import at line 154 to `from aisc_control_objectives.db.repository import ProjectRepository, project_engine`. The service is not rebuilt until Task 8.

- [ ] **Step 7: Run everything.**

Run: `cd apps/control-objectives && uv run pytest -q`
Expected: all PASS, including the four new `TestTheDatabaseIsTheProject` tests. `test_projects.py`, `test_api.py` and `test_project_access.py` pass unchanged: they still pass `?project=`, which the app now ignores. Task 7 removes it.

Then: `grep -rn "core\.\|project_member\|CORE_PROJECT_DDL" src tests alembic`. Expected: no output.

The suite no longer creates `control_objectives_test`. Do not drop that database: this task did not make it. Report that it exists.

- [ ] **Step 8: Commit** (inside `apps/control-objectives`).

```bash
git add alembic src/aisc_control_objectives/db src/aisc_control_objectives/projects.py src/aisc_control_objectives/api/app.py src/aisc_control_objectives/server.py tests/conftest.py tests/test_repository.py
git commit -m "The database is the project: one baseline, an assessment table, no project column"
```

---

### Task 5: Each project's own control objectives

**Files:**
- Create: `apps/control-objectives/src/aisc_control_objectives/db/catalogue.py`
- Test: `apps/control-objectives/tests/test_project_catalogue.py`

**Interfaces:**
- Consumes: tables `objective` and `catalogue` (Task 4). `control_objectives.COLUMNS` (`control_objectives.py:23-34`). `ControlObjectiveCatalogue(objectives, digest)`.
- Produces:
  - `seed_catalogue(engine: Engine, catalogue: ControlObjectiveCatalogue, source_name: str) -> bool`. It returns `True` when it copied now, and `False` when the project already had its copy, in which case nothing is written. It holds an `EXCLUSIVE` lock on `catalogue`, so concurrent callers copy once.
  - `load_catalogue(engine: Engine) -> tuple[ControlObjectiveCatalogue, str]`: the objectives and the source file name. It raises `LookupError` before the copy exists.

- [ ] **Step 1: Write the failing test.** Create `tests/test_project_catalogue.py`:

```python
"""A project's own control objectives.

Nothing but the homepage connects projects, so a project does not read a
catalogue shared with the others: it is given its own copy, and keeps it.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import make_project_database, project_url
from sqlalchemy import func, select

from aisc_control_objectives.control_objectives import ControlObjectiveCatalogue
from aisc_control_objectives.db import tables
from aisc_control_objectives.db.catalogue import load_catalogue, seed_catalogue
from aisc_control_objectives.db.migrations import migrate_database
from aisc_control_objectives.db.repository import project_engine

SOURCE = "ai_act_control_objectives.csv"


def _migrated(pid):
    engine = project_engine(project_url(pid))
    migrate_database(engine)
    return engine


@pytest.fixture()
def engine(fresh_project):
    engine = _migrated(fresh_project)
    yield engine
    engine.dispose()


def _count(engine) -> int:
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(tables.Objective)).scalar()


def test_before_it_is_given_its_copy_a_project_has_no_objectives(engine):
    with pytest.raises(LookupError):
        load_catalogue(engine)


def test_a_project_is_given_the_bundled_objectives(engine, objectives):
    assert seed_catalogue(engine, objectives, SOURCE) is True
    loaded, source = load_catalogue(engine)
    assert [o.model_dump() for o in loaded] == [o.model_dump() for o in objectives]
    assert loaded.digest == objectives.digest
    assert source == SOURCE
    assert len(loaded.macro_requirements()) == 11


def test_giving_it_again_changes_nothing(engine, objectives):
    seed_catalogue(engine, objectives, SOURCE)
    assert seed_catalogue(engine, objectives, SOURCE) is False
    assert _count(engine) == 50


def test_two_at_once_copy_it_once(engine, objectives):
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: seed_catalogue(engine, objectives, SOURCE), range(4)))
    assert results.count(True) == 1
    assert _count(engine) == 50


def test_a_newer_csv_does_not_rewrite_a_project_that_has_its_copy(engine, objectives):
    """An old assessment's tiers must not shift because a release shipped a new CSV."""
    seed_catalogue(engine, objectives, SOURCE)
    newer = ControlObjectiveCatalogue([objectives.by_id("R1.1")], digest="f" * 64)
    assert seed_catalogue(engine, newer, "newer.csv") is False
    loaded, source = load_catalogue(engine)
    assert len(loaded) == 50
    assert loaded.digest == objectives.digest
    assert source == SOURCE


def test_one_project_s_copy_is_not_another_s(engine, objectives):
    seed_catalogue(engine, objectives, SOURCE)
    other = _migrated(make_project_database())
    try:
        with pytest.raises(LookupError):
            load_catalogue(other)
    finally:
        other.dispose()
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_project_catalogue.py -q`
Expected: `ModuleNotFoundError: No module named 'aisc_control_objectives.db.catalogue'`.

- [ ] **Step 3: Implement.** Create `src/aisc_control_objectives/db/catalogue.py`:

```python
"""The control objectives a project is assessed against, kept in the project.

Nothing but the homepage connects projects, so a project does not read a
catalogue shared with the others. It gets its own copy, from the CSV bundled
with this service (or CONTROL_OBJECTIVES_FILE), the first time its database is
opened. After that the copy is the project's: a newer CSV in a later release
reaches projects that have no copy yet, and an existing project keeps the
objectives its assessments were made against.
"""

from __future__ import annotations

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Engine

from aisc_control_objectives.control_objectives import COLUMNS, ControlObjectiveCatalogue
from aisc_control_objectives.db import tables
from aisc_control_objectives.models.control_objective import ControlObjective

#: The objective's own fields, in the CSV's order: what is copied and read back.
FIELDS: tuple[str, ...] = tuple(COLUMNS.values())


def seed_catalogue(engine: Engine, catalogue: ControlObjectiveCatalogue, source_name: str) -> bool:
    """Give this project its copy, unless it has one. True when it was given now."""
    with engine.begin() as connection:
        # Two first requests, or the service and the migrate service, copy once.
        connection.execute(text(f"LOCK TABLE {tables.SCHEMA}.catalogue IN EXCLUSIVE MODE"))
        if connection.execute(select(tables.Catalogue.id)).first() is not None:
            return False
        connection.execute(
            insert(tables.Objective),
            [{field: getattr(objective, field) for field in FIELDS} for objective in catalogue],
        )
        connection.execute(
            insert(tables.Catalogue).values(
                id=1, digest=catalogue.digest, source_name=source_name
            )
        )
        return True


def load_catalogue(engine: Engine) -> tuple[ControlObjectiveCatalogue, str]:
    """This project's objectives, and the file they were copied from."""
    columns = [tables.Objective.__table__.c[field] for field in FIELDS]
    with engine.connect() as connection:
        head = connection.execute(
            select(tables.Catalogue.digest, tables.Catalogue.source_name)
        ).first()
        if head is None:
            raise LookupError("this project has not been given its control objectives yet")
        rows = connection.execute(select(*columns)).mappings().all()
    objectives = [ControlObjective(**dict(row)) for row in rows]
    return ControlObjectiveCatalogue(objectives, digest=head.digest), head.source_name
```

- [ ] **Step 4: Run it.**

Run: `uv run pytest tests/test_project_catalogue.py -q`
Expected: all 6 PASS. Then `uv run pytest -q`: all PASS.

- [ ] **Step 5: Commit** (inside `apps/control-objectives`).

```bash
git add src/aisc_control_objectives/db/catalogue.py tests/test_project_catalogue.py
git commit -m "Each project has its own copy of the control objectives, and keeps it"
```

---

### Task 6: The one helper that hands out a project database

**Files:**
- Modify: `apps/control-objectives/src/aisc_control_objectives/db/project_databases.py` (append)
- Create: `apps/control-objectives/src/aisc_control_objectives/db/workspaces.py`
- Test: `apps/control-objectives/tests/test_workspaces.py`

**Interfaces:**
- Consumes:
  - from Task 2: `access.decide`, `access.Access`
  - from Task 3: `database_name`, `database_url`
  - from Task 4: `migrate_database`, `project_engine`, `ProjectRepository`
  - from Task 5: `seed_catalogue`, `load_catalogue`
- Produces, in `db/project_databases.py`:
  - `class NoSuchProject(LookupError)`, `class NotProvisioned(RuntimeError)`
  - `reachable(template: str, name: str) -> bool | None`, which asks the `postgres` maintenance database. `None` means no such database; `False` means this role may not connect.
  - `is_provisioned(engine: Engine) -> bool`: the `control_objectives` schema exists, and this role may create in it.
- Produces, in `db/workspaces.py`:
  - `Authorise = Callable[[str, str | None], Access | None]`
  - `class NotAMember(LookupError)`, `class ReadOnly(PermissionError)`, `class AccessUnknown(RuntimeError)`
  - `@dataclass(frozen=True) ProjectWorkspace(pid: str, repository: ProjectRepository, catalogue: ControlObjectiveCatalogue, source_name: str)`
  - `ProjectDatabases(template: str, seed: ControlObjectiveCatalogue, seed_name: str, *, authorise: Authorise, migrate: Callable[[Engine], None] = migrate_database)`
    - `.open(pid: str, *, token: str | None, write: bool) -> ProjectWorkspace`
      - Before anything is connected, it raises `NotAPid`, `AccessUnknown`, `NotAMember` or `ReadOnly`.
      - After the checks, it raises `NoSuchProject` or `NotProvisioned`.
    - `.dispose() -> None`

- [ ] **Step 1: Write the failing test.** Create `tests/test_workspaces.py`:

```python
"""Opening a project's database: asked of the platform, then opened once.

ProjectDatabases.open is the one way to a project's database. It asks the
platform about that very pid, with the caller's token, every time, and refuses
before connecting; only then is the database migrated and given its
objectives, once per process.
"""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import PROJECT_DATABASE_URL, make_project_database

from aisc_control_objectives.access import Access
from aisc_control_objectives.control_objectives import ControlObjectiveCatalogue
from aisc_control_objectives.db.migrations import migrate_database
from aisc_control_objectives.db.project_databases import NoSuchProject, NotAPid, NotProvisioned
from aisc_control_objectives.db.workspaces import (
    AccessUnknown,
    NotAMember,
    ProjectDatabases,
    ReadOnly,
)

SOURCE = "ai_act_control_objectives.csv"
OWNER = Access(role="owner", may_write=True)
VIEWER = Access(role="viewer")
STRANGER = Access(role=None)
#: Nothing listens here: a helper that tried to connect would fail with OperationalError.
UNREACHABLE = "postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:1/{database}"


@pytest.fixture()
def made():
    opened = []

    def make(seed, *, authorise=lambda pid, token: OWNER, migrate=migrate_database,
             template=PROJECT_DATABASE_URL):
        databases = ProjectDatabases(template, seed, SOURCE, authorise=authorise, migrate=migrate)
        opened.append(databases)
        return databases

    yield make
    for databases in opened:
        databases.dispose()


# ── who may open it ──────────────────────────────────────────────────────────


def test_the_platform_is_asked_about_this_pid_with_this_token_every_time(made, objectives, fresh_project):
    asked = []
    databases = made(objectives, authorise=lambda pid, token: asked.append((pid, token)) or OWNER)
    databases.open(fresh_project, token="alice", write=False)
    databases.open(fresh_project, token="bob", write=True)
    assert asked == [(fresh_project, "alice"), (fresh_project, "bob")]


def test_a_stranger_is_refused_before_anything_is_connected(made, objectives):
    migrated = []
    databases = made(objectives, authorise=lambda pid, token: STRANGER,
                     migrate=migrated.append, template=UNREACHABLE)
    with pytest.raises(NotAMember):
        databases.open(str(uuid.uuid4()), token="mallory", write=False)
    with pytest.raises(NotAMember):
        databases.open(str(uuid.uuid4()), token="mallory", write=True)
    assert migrated == []


def test_a_viewer_is_refused_a_write_before_anything_is_connected(made, objectives):
    databases = made(objectives, authorise=lambda pid, token: VIEWER, template=UNREACHABLE)
    with pytest.raises(ReadOnly):
        databases.open(str(uuid.uuid4()), token="val", write=True)


def test_a_viewer_may_read(made, objectives, fresh_project):
    databases = made(objectives, authorise=lambda pid, token: VIEWER)
    assert databases.open(fresh_project, token="val", write=False).repository.list() == []
    with pytest.raises(ReadOnly):
        databases.open(fresh_project, token="val", write=True)


def test_no_answer_from_the_platform_lets_nobody_in(made, objectives):
    databases = made(objectives, authorise=lambda pid, token: None, template=UNREACHABLE)
    with pytest.raises(AccessUnknown):
        databases.open(str(uuid.uuid4()), token="alice", write=False)


def test_anything_but_a_pid_is_refused_before_the_platform_is_asked(made, objectives):
    asked = []
    databases = made(objectives, authorise=lambda pid, token: asked.append(pid) or OWNER,
                     template=UNREACHABLE)
    for bad in ("", "abc", "../platform", "project_x; drop database platform"):
        with pytest.raises(NotAPid):
            databases.open(bad, token="alice", write=False)
    assert asked == []


# ── opening it ───────────────────────────────────────────────────────────────


def test_opening_a_project_gives_it_its_tables_and_its_objectives(made, objectives, fresh_project):
    workspace = made(objectives).open(fresh_project, token=None, write=False)
    assert workspace.pid == fresh_project
    assert len(workspace.catalogue) == 50
    assert workspace.source_name == SOURCE
    assert workspace.repository.list() == []
    assert workspace.repository.engine.pool.size() == 2


def test_opening_it_again_is_the_same_workspace(made, objectives, fresh_project):
    databases = made(objectives)
    first = databases.open(fresh_project, token=None, write=False)
    assert databases.open(fresh_project.upper(), token=None, write=True) is first


def test_two_requests_at_once_migrate_it_once(made, objectives, fresh_project):
    calls = []

    def slow(engine):
        calls.append(1)
        time.sleep(0.3)
        migrate_database(engine)

    databases = made(objectives, migrate=slow)
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(lambda _: databases.open(fresh_project, token=None, write=False), range(2))
    assert calls == [1]
    assert a is b


def test_a_failed_opening_is_tried_again(made, objectives, fresh_project):
    attempts = []

    def flaky(engine):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the database is starting")
        migrate_database(engine)

    databases = made(objectives, migrate=flaky)
    with pytest.raises(RuntimeError, match="starting"):
        databases.open(fresh_project, token=None, write=False)
    assert len(databases.open(fresh_project, token=None, write=False).catalogue) == 50
    assert len(attempts) == 2


def test_a_pid_with_no_database_is_no_such_project(made, objectives, postgres):
    """An admin is an owner of any pid, so the platform says yes; there is still no project."""
    databases = made(objectives)
    missing = str(uuid.uuid4())
    with pytest.raises(NoSuchProject):
        databases.open(missing, token="root", write=False)
    with pytest.raises(NoSuchProject):
        databases.open(missing, token="root", write=False)


def test_a_database_without_a_place_for_this_module_is_not_provisioned(made, objectives, postgres):
    pid = make_project_database(provisioned=False)
    with pytest.raises(NotProvisioned):
        made(objectives).open(pid, token=None, write=False)


def test_a_project_keeps_the_objectives_it_was_given(made, objectives, fresh_project):
    made(objectives).open(fresh_project, token=None, write=False)
    newer = ControlObjectiveCatalogue([objectives.by_id("R1.1")], digest="f" * 64)
    assert len(made(newer).open(fresh_project, token=None, write=False).catalogue) == 50
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_workspaces.py -q`
Expected: `ImportError: cannot import name 'NoSuchProject' from 'aisc_control_objectives.db.project_databases'`.

- [ ] **Step 3: Reaching a project database.** In `db/project_databases.py`, add these imports after `from uuid import UUID`:

```python
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
```

Then append to the end of the file:

```python
# ── reaching it ──────────────────────────────────────────────────────────────

#: This service's schema in every project database (db/tables.py).
_SCHEMA = "control_objectives"


class NoSuchProject(LookupError):
    """There is no database for this pid, so there is no such project."""


class NotProvisioned(RuntimeError):
    """The project's database exists, but has no place for this module yet:
    the platform has not applied platform/project-template/0003_control_objectives.sql to it."""


def reachable(template: str, name: str) -> bool | None:
    """None: no such database. False: this role may not connect to it. True: it may.

    Asked of the maintenance database, which every role may connect to, so a
    missing database is a clean answer rather than a failed connection.
    """
    maintenance = create_engine(template.replace("{database}", "postgres"), poolclass=NullPool)
    try:
        with maintenance.connect() as connection:
            row = connection.execute(
                text("SELECT has_database_privilege(datname, 'CONNECT')"
                     " FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).first()
    finally:
        maintenance.dispose()
    return None if row is None else bool(row[0])


def is_provisioned(engine: Engine) -> bool:
    """This database has this module's schema, and this role may create in it."""
    with engine.connect() as connection:
        return bool(connection.execute(
            text("SELECT CASE WHEN to_regnamespace(:schema) IS NULL THEN false"
                 " ELSE has_schema_privilege(:schema, 'CREATE') END"),
            {"schema": _SCHEMA},
        ).scalar())
```

- [ ] **Step 4: The helper.** Create `db/workspaces.py`:

```python
"""A project's workspace: its database, opened for one caller.

This is the one place a project database is handed out. It asks the platform
about that very project, with the caller's own token, every time, before it
connects to anything (GET /authz/projects/{pid}, access.fetch_access). A pid
that reached a route is never trusted because a middleware looked at a URL:
the door in access.py answers early, this is the rule.

Once allowed, the database is opened, migrated and given its own copy of the
control objectives, once per process. Requests that arrive together share
that. A failure is not remembered, so the next request tries again.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from aisc_control_objectives.access import Access, decide
from aisc_control_objectives.control_objectives import ControlObjectiveCatalogue
from aisc_control_objectives.db.catalogue import load_catalogue, seed_catalogue
from aisc_control_objectives.db.migrations import migrate_database
from aisc_control_objectives.db.project_databases import (
    NoSuchProject,
    NotProvisioned,
    database_name,
    database_url,
    is_provisioned,
    reachable,
)
from aisc_control_objectives.db.repository import ProjectRepository, project_engine

#: (pid, the caller's token or None) -> what the platform says, or None when it did not answer.
Authorise = Callable[[str, str | None], Access | None]


class NotAMember(LookupError):
    """The platform says this caller is not in this project: to them it does not exist."""


class ReadOnly(PermissionError):
    """The caller may read this project and not change it."""


class AccessUnknown(RuntimeError):
    """The platform did not answer, so nobody gets in."""


@dataclass(frozen=True)
class ProjectWorkspace:
    """One project, opened: its assessments and its own control objectives."""

    pid: str
    repository: ProjectRepository
    catalogue: ControlObjectiveCatalogue
    source_name: str


class ProjectDatabases:
    def __init__(
        self,
        template: str,
        seed: ControlObjectiveCatalogue,
        seed_name: str,
        *,
        authorise: Authorise,
        migrate: Callable[[Engine], None] = migrate_database,
    ):
        if "{database}" not in template:
            raise ValueError("PROJECT_DATABASE_URL must contain {database}")
        self._template = template
        self._seed = seed
        self._seed_name = seed_name
        self._authorise = authorise
        self._migrate = migrate
        self._open: dict[str, ProjectWorkspace] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def open(self, pid: str, *, token: str | None, write: bool) -> ProjectWorkspace:
        """This project's workspace, for this caller, or the reason why not."""
        name = database_name(pid)                      # NotAPid: nothing asked, nothing built
        pid = str(pid).lower()
        verdict = decide("POST" if write else "GET", self._authorise(pid, token))
        if verdict == "unavailable":
            raise AccessUnknown(name)
        if verdict == "not-found":
            raise NotAMember(name)
        if verdict == "forbidden":
            raise ReadOnly(name)
        return self._workspace(pid, name)

    def _workspace(self, pid: str, name: str) -> ProjectWorkspace:
        found = self._open.get(name)
        if found is not None:
            return found
        with self._guard:
            lock = self._locks.setdefault(name, threading.Lock())
        with lock:
            found = self._open.get(name)
            if found is not None:
                return found
            may_enter = reachable(self._template, name)
            if may_enter is None:
                raise NoSuchProject(name)
            if not may_enter:
                raise NotProvisioned(name)
            engine = project_engine(database_url(pid, self._template))
            try:
                if not is_provisioned(engine):
                    raise NotProvisioned(name)
                self._migrate(engine)
                seed_catalogue(engine, self._seed, self._seed_name)
                catalogue, source_name = load_catalogue(engine)
            except BaseException:
                engine.dispose()
                raise
            workspace = ProjectWorkspace(
                pid=pid,
                repository=ProjectRepository(engine, objectives_digest=catalogue.digest),
                catalogue=catalogue,
                source_name=source_name,
            )
            self._open[name] = workspace
            return workspace

    def dispose(self) -> None:
        for workspace in self._open.values():
            workspace.repository.engine.dispose()
        self._open.clear()
```

- [ ] **Step 5: Run it.**

Run: `uv run pytest tests/test_workspaces.py -q`
Expected: all 13 PASS. Then `uv run pytest -q`: all PASS.

- [ ] **Step 6: Commit** (inside `apps/control-objectives`).

```bash
git add src/aisc_control_objectives/db/project_databases.py src/aisc_control_objectives/db/workspaces.py tests/test_workspaces.py
git commit -m "One helper hands out a project database, and asks the platform first, every time"
```

---

### Task 7: Every page reads its own project's database

**Files:**
- Modify: `apps/control-objectives/src/aisc_control_objectives/api/app.py` (whole file)
- Modify: `apps/control-objectives/src/aisc_control_objectives/server.py`
  - the docstring env list at lines 131-139, the imports at 151-157, and `build_app` at 212-243
- Modify: `apps/control-objectives/src/aisc_control_objectives/settings.py`
  - `DEFAULT_URL` and `database_url` from Task 3
- Modify: `apps/control-objectives/tests/conftest.py`
  - add `databases`, `other_project`, `FixedDatabases`, `FakeMapper` and `SOURCE`
  - replace `platform_project`
- Modify: `apps/control-objectives/tests/test_projects.py`, `tests/test_api.py`
- Modify: `apps/control-objectives/tests/test_project_access.py` (the `pid` and `guarded_app` fixtures, and one new test)
- Test: create `apps/control-objectives/tests/test_project_scope.py`

**Interfaces:**
- Consumes: `ProjectDatabases.open(pid, *, token, write)` (Task 6), `token_from_headers`, `fetch_access` and `ProjectAccess` (Task 2).
- Produces:
  - `create_app(databases, *, mapper_for=lambda catalogue: NoMapper(), model="", base_config=None, root_path="", cors_origins=None, platform_url=None, platform_transport=None) -> FastAPI`, where `databases` has `.open(pid, *, token, write) -> ProjectWorkspace`.
  - These routes read the project database (`write=False`):
    - pages: `GET /p/{pid}`, `/p/{pid}/objectives`, `/p/{pid}/projects`, `/p/{pid}/projects/{id}`
    - API: `GET /p/{pid}/api/control-objectives[?mode=]`, `/p/{pid}/api/control-objectives/{objective_id}`, `/p/{pid}/api/macro-requirements`, `/p/{pid}/api/projects`, `/p/{pid}/api/projects/{id}`
  - These routes write to it (`write=True`):
    - pages: `POST /p/{pid}/projects`, `/p/{pid}/projects/{id}/map`, `/p/{pid}/projects/{id}/severity`
    - API: `POST /p/{pid}/api/projects`, `/p/{pid}/api/projects/{id}/card`, `/p/{pid}/api/projects/{id}/map`, `/p/{pid}/api/projects/{id}/severity`, and `DELETE /p/{pid}/api/projects/{id}`
  - `GET /` and `GET /objectives` redirect (307) to the launcher. `GET /health` and `GET /api/config` are unchanged.
  - Refusals:
    - 404 "No such project." for `NotAPid`, `NotAMember` and `NoSuchProject`
    - 403 for `ReadOnly`
    - 503 for `AccessUnknown`, `NotProvisioned` and SQLAlchemy `OperationalError`
  - `settings.database_url()` now raises `RuntimeError` without `DATABASE_URL`. Only the hand-run Alembic CLI uses it.

- [ ] **Step 1: Test support.** In `tests/conftest.py`:
  - Add these imports: `from aisc_control_objectives.access import Access`, `from aisc_control_objectives.db.workspaces import ProjectDatabases, ProjectWorkspace`, and `from aisc_control_objectives.risk_mapping import MappedObjective, Mapping`.
  - Replace the `platform_project` fixture with the block below, and append the rest:

```python
SOURCE = "ai_act_control_objectives.csv"
OWNER = Access(role="owner", may_write=True)


def owner_everywhere(pid: str, token: str | None) -> Access:
    """A platform that makes every caller an owner: for tests of the flow, not
    of who may do it (test_project_scope.py and test_project_access.py do that)."""
    return OWNER


class FakeMapper:
    """Maps each MCAS risk to three fixed objectives: the flow, not a model's judgement."""

    BY_RISK = {
        "risk0": ["R3.1", "R5.1", "R2.5"],
        "risk1": ["R5.1", "R5.2", "R5.3"],
        "risk2": ["R1.1", "R1.4", "R1.2"],
        "risk3": ["R4.1", "R4.3", "R2.2"],
        "risk4": ["R2.3", "R3.6", "R3.1"],
    }

    def propose(self, risk, findings=()):
        quote = risk.text[:30]
        return Mapping(
            risk_id=risk.id,
            objectives=[
                MappedObjective(objective_id=oid, quote=quote, rationale="because")
                for oid in self.BY_RISK.get(risk.id, [])
            ],
        )


class FixedDatabases:
    """One workspace for any pid, checked the way the service checks it: for
    the catalogue pages, which need no database of their own in a test."""

    def __init__(self, workspace: ProjectWorkspace):
        self.workspace = workspace

    def open(self, pid: str, *, token: str | None, write: bool) -> ProjectWorkspace:
        database_name(pid)
        return self.workspace


@pytest.fixture(scope="session")
def databases(objectives):
    databases = ProjectDatabases(PROJECT_DATABASE_URL, objectives, SOURCE, authorise=owner_everywhere)
    yield databases
    databases.dispose()


@pytest.fixture()
def platform_project(project_pid, databases):
    """The project a test works in, opened as the service opens it, and emptied afterwards."""
    yield project_pid
    engine = databases.open(project_pid, token=None, write=True).repository.engine
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE control_objectives.assessment CASCADE"))


@pytest.fixture()
def other_project(fresh_project) -> str:
    """A second project, with a database of its own."""
    return fresh_project
```

- [ ] **Step 2: Write the failing scope test.** Create `tests/test_project_scope.py`:

```python
"""Every read and write of a project's database asks the platform about that project.

The door (access.py) looks at the URL first. It is not what protects a
project's data: the one helper that opens a project database
(db/workspaces.py: ProjectDatabases.open) asks the platform about the very pid
it opens, with the caller's token, and refuses before connecting. These tests
take the door away to prove the helper holds on its own, for every entry point
that writes.
"""
from __future__ import annotations

import json

import pytest
from conftest import PROJECT_DATABASE_URL, SOURCE, FakeMapper
from fastapi.testclient import TestClient

from aisc_control_objectives.access import Access
from aisc_control_objectives.api.app import create_app
from aisc_control_objectives.config import RunConfig
from aisc_control_objectives.db.workspaces import ProjectDatabases

ROLES = {"owner-token": Access(role="owner", may_write=True), "viewer-token": Access(role="viewer")}
OWNER = {"Authorization": "Bearer owner-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
STRANGER = {"Authorization": "Bearer stranger-token"}


def by_token(pid: str, token: str | None) -> Access:
    return ROLES.get(token or "", Access(role=None))


@pytest.fixture()
def graph_text(fixtures_dir) -> str:
    return (fixtures_dir / "mcas.ontology.jsonld").read_text()


@pytest.fixture()
def scoped(objectives, platform_project, databases, graph_text):
    """The app with no door, on a platform that knows an owner and a viewer.
    The project already holds one assessment, rated."""
    guarded = ProjectDatabases(PROJECT_DATABASE_URL, objectives, SOURCE, authorise=by_token)
    client = TestClient(create_app(guarded, mapper_for=lambda catalogue: FakeMapper(),
                                   base_config=RunConfig()))
    created = client.post(f"/p/{platform_project}/api/projects?name=kept",
                          json=json.loads(graph_text), headers=OWNER)
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    client.post(f"/p/{platform_project}/api/projects/{aid}/severity", json={"risk2": 5}, headers=OWNER)
    repository = databases.open(platform_project, token=None, write=False).repository
    yield client, aid, repository
    guarded.dispose()


def _state(repository) -> list:
    return [
        (r.id, r.digest, dict(r.severity.ratings), r.mapping_run is not None)
        for r in repository.list()
    ]


def _write(client, which: str, pid: str, aid: str, graph_text: str, headers: dict):
    card = json.loads(graph_text)
    calls = {
        "upload a card on the page": lambda: client.post(
            f"/p/{pid}/projects", headers=headers, follow_redirects=False,
            files={"card": ("card.json", graph_text.encode(), "application/json")},
            data={"name": "sneaky"}),
        "map on the page": lambda: client.post(
            f"/p/{pid}/projects/{aid}/map", headers=headers, follow_redirects=False),
        "rate on the page": lambda: client.post(
            f"/p/{pid}/projects/{aid}/severity", headers=headers, follow_redirects=False,
            data={"risk2": "1"}),
        "create through the API": lambda: client.post(
            f"/p/{pid}/api/projects?name=sneaky", json=card, headers=headers),
        "replace the card": lambda: client.post(
            f"/p/{pid}/api/projects/{aid}/card", json=card, headers=headers),
        "map through the API": lambda: client.post(
            f"/p/{pid}/api/projects/{aid}/map", headers=headers),
        "rate through the API": lambda: client.post(
            f"/p/{pid}/api/projects/{aid}/severity", json={"risk2": 1}, headers=headers),
        "delete": lambda: client.delete(f"/p/{pid}/api/projects/{aid}", headers=headers),
    }
    return calls[which]()


WRITES = [
    "upload a card on the page", "map on the page", "rate on the page",
    "create through the API", "replace the card", "map through the API",
    "rate through the API", "delete",
]


@pytest.mark.parametrize("which", WRITES)
def test_a_stranger_writes_nothing(scoped, platform_project, graph_text, which):
    client, aid, repository = scoped
    before = _state(repository)
    response = _write(client, which, platform_project, aid, graph_text, STRANGER)
    assert response.status_code == 404, response.text
    assert _state(repository) == before


@pytest.mark.parametrize("which", WRITES)
def test_a_viewer_writes_nothing(scoped, platform_project, graph_text, which):
    client, aid, repository = scoped
    before = _state(repository)
    response = _write(client, which, platform_project, aid, graph_text, VIEWER)
    assert response.status_code == 403, response.text
    assert _state(repository) == before


@pytest.mark.parametrize("which", WRITES)
def test_an_owner_may(scoped, platform_project, graph_text, which):
    """The refusals above are about who is asking, not about the request."""
    client, aid, _ = scoped
    response = _write(client, which, platform_project, aid, graph_text, OWNER)
    assert response.status_code in (200, 201, 204, 303), response.text


def _reads(pid: str, aid: str) -> list[str]:
    return [
        f"/p/{pid}", f"/p/{pid}/objectives", f"/p/{pid}/projects", f"/p/{pid}/projects/{aid}",
        f"/p/{pid}/api/projects", f"/p/{pid}/api/projects/{aid}",
        f"/p/{pid}/api/control-objectives", f"/p/{pid}/api/control-objectives/R1.1",
        f"/p/{pid}/api/macro-requirements",
    ]


def test_a_stranger_reads_nothing(scoped, platform_project):
    client, aid, _ = scoped
    for path in _reads(platform_project, aid):
        assert client.get(path, headers=STRANGER).status_code == 404, path


def test_a_viewer_reads_everything(scoped, platform_project):
    client, aid, _ = scoped
    for path in _reads(platform_project, aid):
        assert client.get(path, headers=VIEWER).status_code == 200, path
```

- [ ] **Step 3: Move the flow tests onto the new routes.** Line numbers below refer to each file as it was before this step.

In `tests/test_projects.py`:
- Delete the `class FakeMapper` (lines 20-37) and the `from aisc_control_objectives.risk_mapping import MappedObjective, Mapping` import. Add `from conftest import FakeMapper, make_project_database`.
- Replace the `client` fixture (lines 40-43) with:

```python
@pytest.fixture()
def client(databases):
    return TestClient(create_app(databases, mapper_for=lambda catalogue: FakeMapper(),
                                 model="fake/model", base_config=RunConfig()))
```

- Remove `from aisc_control_objectives.projects import Projects`.
- In `_start` (line 54): `f"/api/projects?project={project}&name={name}"` becomes `f"/p/{project}/api/projects?name={name}"`.
- Everywhere else:
  - `f"/api/projects?project={platform_project}&` becomes `f"/p/{platform_project}/api/projects?`
  - `f"/api/projects?project={platform_project}"` becomes `f"/p/{platform_project}/api/projects"`
  - `f"/api/projects/{` becomes `f"/p/{platform_project}/api/projects/{`
  - Add `platform_project` to the parameters of any test or fixture that uses it and lacks it.
- In `test_every_page_carries_the_navigation`, replace the last three lines (from `# and outside one…`) with:

```python
        # and outside one there is nothing to navigate: the launcher chooses the project
        assert client.get("/objectives", follow_redirects=False).status_code == 307
```

- Lines 202 and 208: `client.get("/objectives")` becomes `client.get(f"/p/{platform_project}/objectives")`.
- Replace `test_the_catalogue_still_reads_without_a_project` (lines 280-283) with:

```python
    def test_outside_a_project_there_are_no_objectives_to_read(self, client):
        """Each project has its own copy, in its own database."""
        response = client.get("/objectives", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"].startswith("http")
        assert client.get("/api/control-objectives").status_code == 404
        assert client.get("/api/projects").status_code == 404
```

- Append:

```python
class TestEachProjectIsItsOwn:
    def test_an_assessment_in_one_project_is_not_in_another(self, client, graph, platform_project, other_project):
        mine = _start(client, graph, platform_project)
        assert client.get(f"/p/{other_project}/api/projects").json() == []
        assert client.get(f"/p/{other_project}/api/projects/{mine['id']}").status_code == 404
        assert client.get(f"/p/{other_project}/projects/{mine['id']}").status_code == 404
        assert client.delete(f"/p/{other_project}/api/projects/{mine['id']}").status_code == 404
        assert client.get(f"/p/{platform_project}/api/projects/{mine['id']}").status_code == 200

    def test_each_project_has_its_own_objectives(self, client, platform_project, other_project):
        for pid in (platform_project, other_project):
            assert client.get(f"/p/{pid}/objectives").text.count('class="co-obj"') == 50

    def test_a_pid_with_no_database_is_no_such_project(self, client, postgres):
        import uuid

        assert client.get(f"/p/{uuid.uuid4()}").status_code == 404

    def test_a_path_that_is_not_a_pid_is_no_such_project(self, client):
        assert client.get("/p/mcas").status_code == 404

    def test_a_project_without_a_place_for_this_module_says_so(self, client, postgres):
        response = client.get(f"/p/{make_project_database(provisioned=False)}")
        assert response.status_code == 503
        assert "no place for control objectives" in response.text
```

In `tests/test_api.py`:
- Replace the `client` fixture (lines 18-26) with:

```python
PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


@pytest.fixture()
def client(objectives):
    """The catalogue half needs no database: its objectives come in the workspace."""
    from conftest import FixedDatabases

    from aisc_control_objectives.db.workspaces import ProjectWorkspace

    workspace = ProjectWorkspace(PID, None, objectives, "ai_act_control_objectives.csv")
    return TestClient(create_app(FixedDatabases(workspace), base_config=RunConfig()))
```

- `"/api/control-objectives` becomes `f"/p/{PID}/api/control-objectives`, and `"/api/macro-requirements"` becomes `f"/p/{PID}/api/macro-requirements"`. Lines 38-75 are the lines that change; `/api/config` stays.
- Line 90: `client.get("/objectives")` becomes `client.get(f"/p/{PID}/objectives")`.
- In `test_markup_is_escaped_not_injected` (lines 149-181), change the parameter `repository` to `objectives`. Replace the `app = create_app(…)` call and the `get` that follows it with:

```python
        from conftest import FixedDatabases

        from aisc_control_objectives.db.workspaces import ProjectWorkspace

        app = create_app(
            FixedDatabases(ProjectWorkspace(PID, None, catalogue, "x.csv")),
            base_config=RunConfig(),
        )
        page = TestClient(app).get(f"/p/{PID}/objectives").text
```

  Also drop its now-unused `NoMapper`/`Projects` imports.

In `tests/test_project_access.py`, replace the `pid` and `guarded_app` fixtures with the versions below, and append the admin test:

```python
@pytest.fixture()
def pid(platform_project) -> str:
    """A project that has a database, so a member let through reaches it."""
    return platform_project


@pytest.fixture()
def guarded_app(objectives, monkeypatch, platform):
    """The app with the door fitted, stand-ins for Keycloak and the platform, and
    a helper that asks the same stand-in platform about the pid it opens."""
    from conftest import PROJECT_DATABASE_URL, SOURCE
    from fastapi.testclient import TestClient

    from aisc_control_objectives.api.app import create_app
    from aisc_control_objectives.db.workspaces import ProjectDatabases

    token = _keycloak(monkeypatch)
    databases = ProjectDatabases(
        PROJECT_DATABASE_URL, objectives, SOURCE,
        authorise=lambda project, caller: fetch_access(
            project, caller, platform_url=PLATFORM, transport=platform.transport),
    )
    app = create_app(databases, platform_url=PLATFORM, platform_transport=platform.transport)
    yield TestClient(app), token
    databases.dispose()


def test_an_admin_is_told_when_a_project_does_not_exist(guarded_app, platform, postgres):
    """The platform makes an admin an owner of any pid; the database says there is no such project."""
    import uuid

    client, token = guarded_app
    platform.answers["root"] = ADMIN
    missing = str(uuid.uuid4())
    assert client.get(f"/p/{missing}", headers=_auth(token("root", ("admin",)))).status_code == 404
```

- [ ] **Step 4: Run them and watch them fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_project_scope.py tests/test_projects.py tests/test_api.py tests/test_project_access.py -q`
Expected: FAIL. `create_app()` gets a `ProjectDatabases` where it expects a catalogue, so the failures are `TypeError: create_app() missing 1 required positional argument: 'projects'` or `AttributeError`, and `404 != 201` on the `/p/{pid}/api/…` paths.

- [ ] **Step 5: Rewrite the app.** Replace `api/app.py` with:

```python
"""The service — app factory.

One project at a time, and each project in its own database:

    /                              the way in: the launcher, where projects are chosen
    /p/{pid}                       this project's two halves
    /p/{pid}/objectives            this project's control objectives, as a reference
    /p/{pid}/projects              the systems being assessed in it
    /p/{pid}/projects/{id}         the AI Card · rank its risks · map · tiers
    /p/{pid}/api/...               the JSON API, mirroring the pages

Every route that touches a project's data gets it through one dependency,
which opens the project's database through ProjectDatabases.open: that asks
the platform about this very pid, with the caller's token, before connecting.
The pid comes from the path and nowhere else.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any, Literal, Protocol

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from aisc_identity.headers import token_from_headers

from aisc_control_objectives.access import ProjectAccess
from aisc_control_objectives.config import RunConfig
from aisc_control_objectives.control_objectives import ControlObjectiveCatalogue
from aisc_control_objectives.db.project_databases import NoSuchProject, NotAPid, NotProvisioned
from aisc_control_objectives.db.workspaces import (
    AccessUnknown,
    NotAMember,
    ProjectWorkspace,
    ReadOnly,
)
from aisc_control_objectives.models.control_objective import ControlObjective, MacroRequirement
from aisc_control_objectives.models.ontology import Ontology
from aisc_control_objectives.projects import Projects
from aisc_control_objectives.rendering import (
    STATIC,
    render_home_page,
    render_objectives_page,
    render_project_page,
    render_projects_page,
)

#: Filter over the assessment mode. A paired ("Control + Test") objective
#: answers to both, so the partitions overlap rather than splitting the set.
ModeFilter = Literal["control", "test"]

CARD_WANTED = (
    "is not an AI Card. Download the AI Card from the system's page in the "
    "qualification app: either ai-card.json, or ontology.jsonld."
)

NOT_PROVISIONED = (
    "This project has no place for control objectives yet: its database was made "
    "before this module was added to it. Restarting the platform gives it one."
)


class NoMapper:
    """Stand-in when no mapper is wired: every risk maps to nothing, and the
    page says so rather than pretending the risks were read."""

    def propose(self, risk, findings=()):
        from aisc_control_objectives.risk_mapping import Mapping

        return Mapping(risk_id=risk.id)


#: Where projects are chosen. One place, before any module is entered.
LAUNCHER_URL = os.environ.get("LAUNCHER_URL", "http://localhost:8100/")


class Databases(Protocol):
    """ProjectDatabases in the service; a stand-in in tests."""

    def open(self, pid: str, *, token: str | None, write: bool) -> ProjectWorkspace: ...


def create_app(
    databases: Databases,
    *,
    mapper_for: Callable[[ControlObjectiveCatalogue], Any] = lambda catalogue: NoMapper(),
    model: str = "",
    base_config: RunConfig | None = None,
    root_path: str = "",
    cors_origins: list[str] | None = None,
    platform_url: str | None = None,
    platform_transport=None,
) -> FastAPI:
    config = base_config or RunConfig()
    app = FastAPI(title="AISC Control Objectives", root_path=root_path)

    # The door: answers early for every /p/{pid} path. Added before CORS so
    # that CORS stays the outermost middleware and a refusal still carries its
    # headers. None means no door, for tests of the flow; an empty string
    # still fits one, which then refuses everything with 503.
    if platform_url is not None:
        app.add_middleware(ProjectAccess, platform_url=platform_url, transport=platform_transport)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    _register_refusals(app)

    def opener(write: bool):
        def open_workspace(project: str, request: Request) -> ProjectWorkspace:
            return databases.open(project, token=token_from_headers(request.headers), write=write)

        return open_workspace

    reading = Depends(opener(write=False))
    writing = Depends(opener(write=True))

    def projects_in(workspace: ProjectWorkspace) -> Projects:
        return Projects(
            workspace.repository, workspace.catalogue, mapper_for(workspace.catalogue), model=model
        )

    _register_pages(app, reading, writing, projects_in, root_path)
    _register_objective_api(app, reading, config)
    _register_project_api(app, reading, writing, projects_in)
    return app


def _register_refusals(app: FastAPI) -> None:
    """What each reason for not opening a project's database answers."""

    async def no_such_project(request, exc):
        return PlainTextResponse("No such project.", status_code=404)

    async def read_only(request, exc):
        return PlainTextResponse("You can read this project but not change it.", status_code=403)

    async def not_answering(request, exc):
        return PlainTextResponse(
            "The platform is not answering, so who may be here cannot be established.",
            status_code=503,
        )

    async def not_provisioned(request, exc):
        return PlainTextResponse(NOT_PROVISIONED, status_code=503)

    async def database_down(request, exc):
        return PlainTextResponse("This project's database is not answering just now.", status_code=503)

    for error, handler in (
        (NotAPid, no_such_project),
        (NotAMember, no_such_project),
        (NoSuchProject, no_such_project),
        (ReadOnly, read_only),
        (AccessUnknown, not_answering),
        (NotProvisioned, not_provisioned),
        (OperationalError, database_down),
    ):
        app.add_exception_handler(error, handler)


def _view_or_404(projects: Projects, project_id: str):
    view = projects.view(project_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"Unknown project {project_id}")
    return view


def _register_pages(app, reading, writing, projects_in, root_path):
    """The pages, and the forms that post to them."""

    @app.get("/", include_in_schema=False)
    def no_project() -> RedirectResponse:
        """Reached without a project. The project is chosen once, on the
        launcher, and every module then works inside it."""
        return RedirectResponse(url=LAUNCHER_URL, status_code=307)

    @app.get("/objectives", include_in_schema=False)
    def no_project_objectives() -> RedirectResponse:
        """Each project has its own control objectives, in its own database, so
        outside a project there are none to show."""
        return RedirectResponse(url=LAUNCHER_URL, status_code=307)

    @app.get("/p/{project}", include_in_schema=False, response_class=HTMLResponse)
    def project_home_page(project: str, workspace: ProjectWorkspace = reading) -> HTMLResponse:
        return HTMLResponse(
            render_home_page(
                workspace.catalogue, len(workspace.repository.list()),
                root_path=root_path, project=project,
            )
        )

    @app.get("/p/{project}/objectives", include_in_schema=False, response_class=HTMLResponse)
    def project_objectives_page(project: str, workspace: ProjectWorkspace = reading) -> HTMLResponse:
        return HTMLResponse(
            render_objectives_page(
                workspace.catalogue, source_name=workspace.source_name,
                root_path=root_path, project=project,
            )
        )

    @app.get("/p/{project}/projects", include_in_schema=False, response_class=HTMLResponse)
    def projects_page(project: str, workspace: ProjectWorkspace = reading) -> HTMLResponse:
        return HTMLResponse(
            render_projects_page(projects_in(workspace).list(), root_path=root_path, project=project)
        )

    @app.post("/p/{project}/projects", include_in_schema=False)
    async def create_project_form(
        project: str, request: Request, workspace: ProjectWorkspace = writing
    ):
        form = await request.form()
        upload: UploadFile = form["card"]
        name = str(form.get("name") or "").strip()
        raw_bytes = upload.file.read()
        try:
            raw = json.loads(raw_bytes)
        except ValueError:
            return PlainTextResponse("The uploaded file is not valid JSON.", status_code=400)
        if not Ontology.looks_like_one(raw):
            return PlainTextResponse(f"That file {CARD_WANTED}", status_code=400)
        view = projects_in(workspace).create(name=name, jsonld=raw_bytes.decode("utf-8"), raw=raw)
        return RedirectResponse(
            url=f"{root_path}/p/{project}/projects/{view.record.id}", status_code=303
        )

    @app.get("/p/{project}/projects/{project_id}", include_in_schema=False,
             response_class=HTMLResponse)
    def project_page(project: str, project_id: str,
                     workspace: ProjectWorkspace = reading) -> HTMLResponse:
        view = _view_or_404(projects_in(workspace), project_id)
        return HTMLResponse(
            render_project_page(view, workspace.catalogue, root_path=root_path, project=project)
        )

    @app.post("/p/{project}/projects/{project_id}/map", include_in_schema=False)
    def map_form(project: str, project_id: str, workspace: ProjectWorkspace = writing):
        """The one agentic step, on a button: it costs a model call per risk."""
        projects = projects_in(workspace)
        _view_or_404(projects, project_id)
        projects.map_risks_of(project_id)
        return RedirectResponse(url=f"{root_path}/p/{project}/projects/{project_id}", status_code=303)

    @app.post("/p/{project}/projects/{project_id}/severity", include_in_schema=False)
    async def rate_form(project: str, project_id: str, request: Request,
                        workspace: ProjectWorkspace = writing):
        projects = projects_in(workspace)
        view = _view_or_404(projects, project_id)
        form = await request.form()
        try:
            ratings = {
                risk.id: int(form[risk.id])
                for risk in view.record.ontology.risks
                if form.get(risk.id)
            }
            projects.rate(project_id, ratings)
        except ValueError as exc:
            return PlainTextResponse(f"Invalid rating: {exc}", status_code=400)
        return RedirectResponse(url=f"{root_path}/p/{project}/projects/{project_id}", status_code=303)


def _register_objective_api(app, reading, config):
    """This project's control objectives, and the service's own settings."""

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config", response_model=RunConfig)
    def get_config() -> RunConfig:
        return config

    @app.get("/p/{project}/api/control-objectives", response_model=list[ControlObjective])
    def list_control_objectives(
        project: str,
        mode: ModeFilter | None = Query(
            None, description="Keep only objectives assessed by a control or by a test"
        ),
        workspace: ProjectWorkspace = reading,
    ) -> list[ControlObjective]:
        objectives = workspace.catalogue
        if mode == "control":
            return objectives.requiring_control()
        if mode == "test":
            return objectives.requiring_test()
        return objectives.objectives

    @app.get("/p/{project}/api/control-objectives/{objective_id}", response_model=ControlObjective)
    def get_control_objective(project: str, objective_id: str,
                              workspace: ProjectWorkspace = reading) -> ControlObjective:
        objective = workspace.catalogue.by_id(objective_id)
        if objective is None:
            raise HTTPException(status_code=404, detail=f"Unknown objective {objective_id}")
        return objective

    @app.get("/p/{project}/api/macro-requirements", response_model=list[MacroRequirement])
    def list_macro_requirements(project: str,
                                workspace: ProjectWorkspace = reading) -> list[MacroRequirement]:
        return workspace.catalogue.macro_requirements()


def _register_project_api(app, reading, writing, projects_in):
    """One assessed system: its graph, its ranking, its mapping, its tiers."""

    def payload(view) -> dict:
        record = view.record
        return {
            "id": record.id,
            "name": record.name,
            "system_name": record.system_name,
            "qualification_id": record.qualification_id,
            "digest": record.digest,
            "objectives_digest": record.objectives_digest,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "risks": [risk.model_dump() for risk in record.ontology.risks],
            "severity": record.severity.model_dump(),
            "mapping_run": record.mapping_run.model_dump() if record.mapping_run else None,
            "priorities": [p.model_dump() for p in view.priorities],
            "mapped": view.mapped,
        }

    def _card_or_422(raw: object) -> None:
        if not Ontology.looks_like_one(raw):
            raise HTTPException(status_code=422, detail=f"that body {CARD_WANTED}")

    @app.post("/p/{project}/api/projects", status_code=201)
    def create_project(project: str, card: Any = Body(...), name: str = Query(""),
                       workspace: ProjectWorkspace = writing) -> dict:
        """Upload a system's AI Card. Its risks are what gets ranked next."""
        _card_or_422(card)
        return payload(projects_in(workspace).create(name=name, jsonld=json.dumps(card), raw=card))

    @app.get("/p/{project}/api/projects")
    def list_projects(project: str, workspace: ProjectWorkspace = reading) -> list[dict]:
        return [payload(view) for view in projects_in(workspace).list()]

    @app.get("/p/{project}/api/projects/{project_id}")
    def get_project(project: str, project_id: str, workspace: ProjectWorkspace = reading) -> dict:
        return payload(_view_or_404(projects_in(workspace), project_id))

    @app.post("/p/{project}/api/projects/{project_id}/card")
    def replace_card(project: str, project_id: str, card: Any = Body(...),
                     workspace: ProjectWorkspace = writing) -> dict:
        """A corrected AI Card for a system already under assessment."""
        projects = projects_in(workspace)
        _view_or_404(projects, project_id)
        _card_or_422(card)
        return payload(projects.replace_card(project_id, jsonld=json.dumps(card), raw=card))

    @app.post("/p/{project}/api/projects/{project_id}/map")
    def map_risks(project: str, project_id: str, workspace: ProjectWorkspace = writing) -> dict:
        projects = projects_in(workspace)
        _view_or_404(projects, project_id)
        return payload(projects.map_risks_of(project_id))

    @app.post("/p/{project}/api/projects/{project_id}/severity")
    def rate(project: str, project_id: str, ratings: dict[str, int] = Body(...),
             workspace: ProjectWorkspace = writing) -> dict:
        projects = projects_in(workspace)
        _view_or_404(projects, project_id)
        try:
            return payload(projects.rate(project_id, ratings))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/p/{project}/api/projects/{project_id}", status_code=204)
    def delete_project(project: str, project_id: str, workspace: ProjectWorkspace = writing) -> None:
        projects = projects_in(workspace)
        _view_or_404(projects, project_id)
        projects.delete(project_id)
```

`map_risks` now checks `_view_or_404` first. Before, an unknown id reached `repository.get()`, which returned `None`, and failed on `.ontology` with a 500.

- [ ] **Step 6: Compose it in the server.** In `server.py`:
- Replace the imports at lines 151-157 with:

```python
from aisc_control_objectives.access import fetch_access
from aisc_control_objectives.api.app import create_app
from aisc_control_objectives.config import RunConfig
from aisc_control_objectives.control_objectives import default_csv_path, load_control_objectives
from aisc_control_objectives.db.workspaces import ProjectDatabases
from aisc_control_objectives.risk_mapping import RiskMapper
from aisc_control_objectives.settings import project_database_url
```

- Replace `build_app` (lines 212-243) with:

```python
def build_app():
    _load_dotenv()

    config_file = os.environ.get(
        "CONTROL_OBJECTIVES_CONFIG_FILE", str(_repo_root() / "control-objectives.toml")
    )
    config = RunConfig.load(os.environ, config_file)

    objectives_file, source_name = objectives_source(os.environ)
    # What each project's own copy of the objectives starts as. Read here, so a
    # malformed CSV stops the service at start, naming the row.
    seed = load_control_objectives(objectives_file)

    cors_env = os.environ.get("CONTROL_OBJECTIVES_CORS_ORIGINS", "").strip()
    cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()] or None
    complete = _build_completer(config)
    platform_url = os.environ.get("PLATFORM_URL", "")
    databases = ProjectDatabases(
        project_database_url(),
        seed,
        source_name,
        # The platform is asked about the very project each request opens,
        # with that caller's own token.
        authorise=lambda pid, token: fetch_access(pid, token, platform_url=platform_url),
    )
    return create_app(
        databases,
        mapper_for=lambda catalogue: RiskMapper(complete=complete, catalogue=catalogue),
        model=f"{config.provider}/{config.model}",
        base_config=config,
        root_path=os.environ.get("CONTROL_OBJECTIVES_ROOT_PATH", ""),
        cors_origins=cors_origins,
        platform_url=platform_url,
    )
```

- In the module docstring's `Env:` list (lines 131-139), add:

```
  PROJECT_DATABASE_URL                 a project database's URL, {database} where its name goes
  PLATFORM_URL                         the platform, asked who may be in a project
```

In `settings.py`, delete `DEFAULT_URL` and its comment, and replace `database_url` with:

```python
def database_url(env: Mapping[str, str] | None = None) -> str:
    """One project database, for running Alembic by hand
    (`DATABASE_URL=… alembic upgrade head`). The service itself reaches every
    project through PROJECT_DATABASE_URL."""
    url = (env or os.environ).get("DATABASE_URL")
    if not url:
        raise RuntimeError("set DATABASE_URL to the one project database to migrate")
    return _with_driver(url)
```

- [ ] **Step 7: Run everything.**

Run: `cd apps/control-objectives && uv run pytest -q`
Expected: all PASS. That includes the 26 in `test_project_scope.py`: 8 stranger, 8 viewer, 8 owner and 2 read tests. It also includes `TestEachProjectIsItsOwn` and the admin test.

Then: `grep -rn "?project=\|Query(\.\.\., description=\"The platform project" src tests`. Expected: no output.

- [ ] **Step 8: Commit** (inside `apps/control-objectives`).

```bash
git add src/aisc_control_objectives/api/app.py src/aisc_control_objectives/server.py src/aisc_control_objectives/settings.py tests/conftest.py tests/test_projects.py tests/test_api.py tests/test_project_access.py tests/test_project_scope.py
git commit -m "Every page reads its own project's database, and every write asks the platform about that project"
```

---

### Task 8: Migrate every project database at start

**Files:**
- Create: `apps/control-objectives/src/aisc_control_objectives/migrate_projects.py`
- Modify: `apps/control-objectives/src/aisc_control_objectives/settings.py` (it receives `objectives_source`)
- Modify: `apps/control-objectives/src/aisc_control_objectives/server.py` (`objectives_source` at lines 164-170 moves out)
- Modify: `apps/control-objectives/env.development`, `apps/control-objectives/README.md` (lines 42, 164, 205 and 213)
- Modify: `docker-compose.development.yml`
  - the comment at 298-304
  - `control-objectives-migrate` at 305-319
  - `control-objectives` `DATABASE_URL` at 343
- Test: `apps/control-objectives/tests/test_migrate_projects.py`

**Interfaces:**
- Consumes: `project_engine`, `migrate_database`, `seed_catalogue`, `is_provisioned` and `project_database_url`. The platform-made `project_*` databases (Task 1).
- Produces:
  - `migrate_projects.project_databases(template: str) -> list[tuple[str, bool]]`: each name, with whether this role may connect.
  - `migrate_projects.migrate_all(template: str, seed: ControlObjectiveCatalogue, seed_name: str, only: set[str] | None = None) -> tuple[list[str], list[str]]`: returns (migrated, skipped).
  - `migrate_projects.main(env: Mapping[str, str] | None = None) -> int`: exit 0 when done, 1 when Postgres is not reachable (retry), 2 when misconfigured (stop).
  - `settings.objectives_source(env) -> tuple[Path | None, str]` (moved; `server.objectives_source` still resolves).

- [ ] **Step 1: Write the failing test.** Create `tests/test_migrate_projects.py`:

```python
"""Every project database at start: migrated, given its objectives, or skipped.

The tests pass `only`, so the run touches the databases they made and no other.
"""
from conftest import PROJECT_DATABASE_URL, make_project_database, project_url

from aisc_control_objectives import migrate_projects
from aisc_control_objectives.db.catalogue import load_catalogue
from aisc_control_objectives.db.project_databases import database_name
from aisc_control_objectives.db.repository import project_engine

SOURCE = "ai_act_control_objectives.csv"


def test_every_project_it_may_enter_is_migrated_and_given_its_objectives(postgres, objectives):
    ready = make_project_database()
    closed = make_project_database(provisioned=False)
    only = {database_name(ready), database_name(closed)}
    migrated, skipped = migrate_projects.migrate_all(PROJECT_DATABASE_URL, objectives, SOURCE, only=only)
    assert migrated == [database_name(ready)]
    assert skipped == [database_name(closed)]
    engine = project_engine(project_url(ready))
    try:
        assert len(load_catalogue(engine)[0]) == 50
    finally:
        engine.dispose()


def test_running_it_again_changes_nothing(postgres, objectives):
    ready = make_project_database()
    only = {database_name(ready)}
    migrate_projects.migrate_all(PROJECT_DATABASE_URL, objectives, SOURCE, only=only)
    assert migrate_projects.migrate_all(PROJECT_DATABASE_URL, objectives, SOURCE, only=only) == (
        [database_name(ready)], [],
    )
    engine = project_engine(project_url(ready))
    try:
        assert len(load_catalogue(engine)[0]) == 50
    finally:
        engine.dispose()


def test_a_template_with_nowhere_to_put_the_database_is_permanent():
    assert migrate_projects.main({"PROJECT_DATABASE_URL": "postgresql://x@y/platform"}) == 2


def test_postgres_not_answering_is_worth_retrying():
    env = {"PROJECT_DATABASE_URL": "postgresql://a:b@127.0.0.1:1/{database}"}
    assert migrate_projects.main(env) == 1
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/control-objectives && uv run pytest tests/test_migrate_projects.py -q`
Expected: `ImportError: cannot import name 'migrate_projects' from 'aisc_control_objectives'`.

- [ ] **Step 3: Move `objectives_source` where the migrate service can import it without the web app.** `server.py` imports the door, which needs `aisc_identity`, and that package is not mounted in the migrate container.
- Cut `objectives_source` (lines 164-170) from `server.py` and paste it at the end of `settings.py`.
- Add `from pathlib import Path` and `from aisc_control_objectives.control_objectives import default_csv_path` to the imports of `settings.py`.
- In `server.py`, import it back: `from aisc_control_objectives.settings import objectives_source, project_database_url`. Delete `default_csv_path` from its `control_objectives` import if nothing else uses it.
- `tests/test_server.py` calls `server.objectives_source`, which still resolves.

- [ ] **Step 4: Implement.** Create `src/aisc_control_objectives/migrate_projects.py`:

```python
"""Bring every project database to this service's schema, then exit.

Runs as the control-objectives-migrate service at start. A project made later
is migrated by the service the first time it is opened (db/workspaces.py), so
this is for a schema change reaching the projects that already exist.

A database this module was never given a place in (the platform has not
applied its template to it) is skipped and named, not waited on.

Exit codes: 0 done; 1 Postgres not reachable yet, so the compose loop retries;
2 misconfigured, and retrying cannot help.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from aisc_control_objectives.control_objectives import (
    ControlObjectiveCatalogue,
    load_control_objectives,
)
from aisc_control_objectives.db.catalogue import seed_catalogue
from aisc_control_objectives.db.migrations import migrate_database
from aisc_control_objectives.db.project_databases import is_provisioned
from aisc_control_objectives.db.repository import project_engine
from aisc_control_objectives.settings import objectives_source, project_database_url

_PROJECT_DATABASE = r"^project_[0-9a-f]{32}$"


def _say(message: str) -> None:
    print(f"[control-objectives] {message}", flush=True)


def project_databases(template: str) -> list[tuple[str, bool]]:
    """Every project database on the server, and whether this role may connect to it."""
    engine = create_engine(template.replace("{database}", "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT datname, has_database_privilege(datname, 'CONNECT')"
                     " FROM pg_database WHERE datname ~ :pattern ORDER BY datname"),
                {"pattern": _PROJECT_DATABASE},
            ).all()
    finally:
        engine.dispose()
    return [(row[0], bool(row[1])) for row in rows]


def migrate_all(
    template: str,
    seed: ControlObjectiveCatalogue,
    seed_name: str,
    only: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    migrated: list[str] = []
    skipped: list[str] = []
    for name, may_connect in project_databases(template):
        if only is not None and name not in only:
            continue
        if not may_connect:
            _say(f"skipping {name}: not provisioned for control objectives")
            skipped.append(name)
            continue
        engine = project_engine(template.replace("{database}", name))
        try:
            if not is_provisioned(engine):
                _say(f"skipping {name}: not provisioned for control objectives")
                skipped.append(name)
                continue
            _say(f"migrating {name}")
            migrate_database(engine)
            seed_catalogue(engine, seed, seed_name)
            migrated.append(name)
        finally:
            engine.dispose()
    return migrated, skipped


def main(env: Mapping[str, str] | None = None) -> int:
    env = env or os.environ
    try:
        template = project_database_url(env)
        path, source_name = objectives_source(env)
        seed = load_control_objectives(path)
    except ValueError as exc:
        print(f"[control-objectives] {exc}", file=sys.stderr)
        return 2
    try:
        migrated, skipped = migrate_all(template, seed, source_name)
    except OperationalError as exc:
        print(f"[control-objectives] postgres is not answering: {exc.orig}", file=sys.stderr)
        return 1
    _say(f"{len(migrated)} project database(s) up to date, {len(skipped)} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run it.**

Run: `uv run pytest tests/test_migrate_projects.py -q`
Expected: all 4 PASS. Then `uv run pytest -q`: all PASS.

- [ ] **Step 6: Point the services at project databases.** In `apps/control-objectives/env.development`, append:

```ini

# Every project has its own database, made by the platform. {database} is
# filled with that project's, from the /p/{pid} path, after the platform has
# said the caller may be in it (src/aisc_control_objectives/db/workspaces.py).
# At most two connections per project database (db/repository.py).
PROJECT_DATABASE_URL=postgresql://control_objectives_rw:control_objectives_rw@postgres:5432/{database}
```

In `docker-compose.development.yml`:
- Replace the comment block at lines 298-304 with:

```yaml
  # ── AI Act control objectives (apps/control-objectives submodule) ──
  # Reads the AI Card the qualification app exports, ranks that system's risks
  # and maps them onto the control objectives. Keeps each project's
  # assessments, and that project's own copy of the objectives, in the
  # project's own database (schema control_objectives, made by
  # platform/project-template/0003_control_objectives.sql).
```

- Replace the `control-objectives-migrate` service (lines 305-319) with:

```yaml
  control-objectives-migrate:
    build: apps/control-objectives/
    image: aisc-control-objectives:latest
    pull_policy: never
    container_name: control-objectives-migrate
    # Every project database, not one shared one: each gets this service's
    # tables and its own copy of the control objectives. A database the
    # platform has not provisioned for this module is skipped, not waited on;
    # exit 2 is a configuration error, which retrying cannot fix.
    command: >
      sh -c "until python -m aisc_control_objectives.migrate_projects; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[control-objectives] waiting for postgres'; sleep 2; done"
    env_file: apps/control-objectives/env.development
    depends_on:
      - postgres
      - platform
    restart: "no"
    networks:
      - backend
```

- In `control-objectives.environment`, delete the `DATABASE_URL:` line (line 343). `PROJECT_DATABASE_URL` comes from its existing `env_file`.

- [ ] **Step 7: README.** In `apps/control-objectives/README.md`:
- Line 42, `export DATABASE_URL=postgresql://user:password@localhost:5432/control-objectives`, becomes:

```bash
export PROJECT_DATABASE_URL='postgresql://control_objectives_rw:control_objectives_rw@localhost:5432/{database}'
export PLATFORM_URL=http://localhost:8000
```

- Line 43, `alembic upgrade head`, becomes `python -m aisc_control_objectives.migrate_projects`.
- Line 164 (the `DATABASE_URL` row) becomes the two rows:

```
| `PROJECT_DATABASE_URL` | `…@localhost:5432/{database}` | a project's own database; `{database}` is filled from the `/p/{pid}` path |
| `PLATFORM_URL` | none: every project page answers 503 | the platform, asked who may be in a project, about the very project opened |
```

- Line 205 becomes: `They run against a **real Postgres**, not SQLite, because testing on a different engine from production is how you find out \`text[]\` does not exist on the day you deploy. Each run makes throwaway project databases through \`docker exec postgres\`, the way the platform makes them, and drops only those; the service connects to them as \`control_objectives_rw\`. Point \`CONTROL_OBJECTIVES_TEST_PROJECT_DATABASE_URL\` elsewhere if 127.0.0.1:5432 is not right for your machine.`
- Line 213: `-e DATABASE_URL=...` becomes `-e PROJECT_DATABASE_URL=... -e PLATFORM_URL=...`.

- [ ] **Step 8: Rebuild both, and check.**

```bash
set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build control-objectives-migrate control-objectives
docker wait control-objectives-migrate
docker logs control-objectives-migrate 2>&1 | tail -5
docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d project_01399e174b014be9997a7f5e3574ab22 -Atc "select (select count(*) from control_objectives.objective), (select count(*) from control_objectives.assessment), (select version_num from control_objectives.alembic_version)"'
```

Expected:
- `docker wait` prints `0`.
- The log shows `migrating project_01399e174b014be9997a7f5e3574ab22`, and a `skipping …: not provisioned for control objectives` line for each of the two orphan databases.
- The last log line is `1 project database(s) up to date, 2 skipped`.
- The query prints `50|0|5d3c9e1a7b20`.

**If the real project is skipped, stop:** Task 1 Step 5 did not provision it. Do not grant anything by hand.

- [ ] **Step 9: Commit.**

```bash
(cd apps/control-objectives && git add src/aisc_control_objectives/migrate_projects.py src/aisc_control_objectives/settings.py src/aisc_control_objectives/server.py env.development README.md tests/test_migrate_projects.py && git commit -m "Migrate every project database at start, and give each its objectives")
git add -p docker-compose.development.yml   # only the control-objectives and control-objectives-migrate hunks
git commit -m "Control objectives migrates project databases, not the shared one"
```

---

### Task 9: Prove it end to end

**Files:**
- Modify: `scripts/verify-one-database.sh:27`, `scripts/verify-rbac.sh:135-139`

**Interfaces:**
- Consumes: everything above.
- Produces: `scripts/verify.sh` reports 0 failed.

- [ ] **Step 1: Write the failing assertions.** In `scripts/verify-rbac.sh`, replace lines 135-139, the five control objectives lines ending with the `/objectives` check, with:

```bash
  CO="http://localhost:8090"
  is "control objectives lets a member in"       200 "$(call control-objectives $CO/p/$PROJECT GET "$USER")"
  is "and asks an anonymous caller who they are" 401 "$(call control-objectives $CO/p/$PROJECT GET '')"
  is "a project nobody is in is not found"       404 "$(call control-objectives $CO/p/00000000-0000-0000-0000-000000000000 GET "$USER")"
  is "a path that is not a project is not found" 404 "$(call control-objectives $CO/p/abc GET "$USER")"
  is "the objectives are read inside a project"  200 "$(call control-objectives $CO/p/$PROJECT/objectives GET "$USER")"
  is "and are served nowhere outside one"        404 "$(call control-objectives $CO/api/control-objectives GET "$USER")"
  is "nor are the assessments"                   404 "$(call control-objectives $CO/api/projects GET "$USER")"
  echo "control objectives keeps a project's data in that project's database"
  PDB="project_$(echo "$PROJECT" | tr -d -)"
  n=$(docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d $PDB -Atc 'select count(*) from control_objectives.objective'" 2>&1)
  is "the project has its own 50 control objectives" 50 "$n"
```

`call` follows redirects through urllib, so the 307 on `/objectives` is not checked here. It is pinned in `test_projects.py` instead.

In `scripts/verify-one-database.sh`, delete line 27 (`"control objectives|control-objectives|control_objectives|project|project_id"`). The module is no longer on the `platform` database. Plan 1 removed controls from `MODULES` the same way. Leave line 132, the old standalone database check, and line 158. The shared `control_objectives.project` table is abandoned, not dropped, so `dashboard_ro` can still read it until Plan 6.

- [ ] **Step 2: Run the rbac check.**

Run: `scripts/verify-rbac.sh`
Expected: every control objectives line PASSES, since Tasks 2-8 are deployed. If `nor are the assessments` fails with 200 or 422, the old ungated `/api/projects` is still being served. That means Task 7 was not deployed: rebuild `control-objectives` and rerun.

- [ ] **Step 3: Run the whole verdict.**

Run: `scripts/verify.sh`
Expected: the final line reports `0 failed`. `control objectives` is listed as `ok`, not `skip`.

- [ ] **Step 4: Walk through it once in the browser, in two throwaway projects.** Nothing here writes to the real project.
  1. Sign in at http://localhost:8100 as `admin`. Create a project named `co-walk-a` and another named `co-walk-b`.
  2. Open `co-walk-a`, then step 2, Control objectives. The page says "No systems under assessment yet". **Control objectives** lists 50 objectives in 11 requirements.
  3. Go to **Projects**, upload `apps/control-objectives/tests/fixtures/mcas.ontology.jsonld` and name it "walk". You land on its page with 5 risks. Rate one risk 5 and save: the tiers move.
  4. Open `co-walk-b`, then Control objectives. There are no systems under assessment, and it has 50 objectives of its own.
  5. In the address bar, take `co-walk-a`'s assessment URL and swap in `co-walk-b`'s pid. The answer is `No such project.` (the assessment id is unknown there) or the page's 404.
  6. In a private window, sign in as `user`, who is in neither project, and open `co-walk-a`'s control objectives URL: `No such project.`
  7. Back as `admin`, delete both projects with **Delete this project…** (Plan 1, Task 11). Then run `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_database where datname like \$\$project\_%\$\$"'`: it prints the count from before step 1.

- [ ] **Step 5: Commit** (root).

```bash
git add scripts/verify-one-database.sh scripts/verify-rbac.sh
git add apps/control-objectives   # the submodule pointer only
git commit -m "Control objectives lives in each project's database, and asks the platform about each one"
```

Stage exactly these paths. Leave these untouched: `apps/backend`, `apps/eval`, `apps/webapp`, `apps/results-dashboard` and `apps/qualification`, whose pointers have moved; `scripts/verify.sh`; and the prefill hunk.

---

## Stopping rule and checkpoints

- **Checkpoint after every task:** that task's own test command, plus `scripts/verify.sh --modules`. A task isn't done until both are green. Deployment checkpoints are after Task 1 (Step 5 query), Task 2 (`verify-rbac.sh`), Task 8 (migrate logs and the `50|0|5d3c9e1a7b20` query) and Task 9 (`verify.sh`).
- **Stop and ask the user if:**
  - the migrate service skips `project_01399e174b014be9997a7f5e3574ab22` after Task 1;
  - the platform refuses to apply `0003` (for example, a permission error in `provision_all`);
  - an existing test outside this plan starts failing and fixing it would change what it asserts;
  - Plan 2's `0002_system.sql` has landed and grants, revokes or creates anything in schema `control_objectives`;
  - anything seems to need dropping or altering in a database, schema or project this task didn't create. That includes the shared `control_objectives` schema, `control_objectives_test` and the two orphan project databases.
- **Stop and report** if one task's fix loop passes 3 attempts without green tests. Don't widen the task to make it pass.
- **Done when:**
  - `scripts/verify.sh` prints `0 failed`;
  - the Task 9 walkthrough behaves exactly as written, and its two throwaway projects are deleted;
  - `cd apps/control-objectives && uv run pytest -q` is green with `test_project_scope.py`'s 26 tests present;
  - nothing is pushed.

## Open questions for the user

1. The `project` table becomes `assessment` with no project column, which keeps several assessments per project. A project can hold several systems. Should it be one assessment per project instead?
2. A project copies the bundled objectives CSV once and keeps that copy, so a newer CSV reaches only new projects. Is that the rule you want, or should existing projects be updated too? Updating would change old assessments' tiers.
3. An assessment only copies `system_name` from the uploaded card. Should it point at Plan 2's `project.system` instead? That would add a dependency on `0002`.
