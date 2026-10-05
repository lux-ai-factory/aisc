# Project databases, plan 4: the execution engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The execution engine (step 4) keeps everything it has for a project in that project's own database: the AI system and its components, the plugins the project uses, evaluations, observations, measurements, artifacts' records, the metric catalogue, and Django's own users and sessions. Nothing of the engine is global any more. It learns the project from a header on every API call, checks that exact project with the platform before opening its database, and never reads the platform's tables.

**Architecture:** Every API call names its project in an `X-AISC-Project` header. The SPA sets it from its `?project=`, and the Celery worker sets it for the run it is working on. An async Django middleware (`aisc_backend/project_door.py`) hands the request to `projectdb.admit()`, the only way into a project database.
- For a person, `admit()` asks the platform's `GET /authz/projects/{pid}` about that exact pid, with the caller's own token, on every request. A stranger gets 404. A viewer who writes gets 403.
- For the worker, `admit()` checks a run ticket instead. The ticket is an HMAC of (pid, evaluation), minted by the backend when an editor started that run.

Only after that check does `admit()` open the project's database. Django gets a connection alias per project database: `connections.settings` is copied with the project's `NAME` filled in, and the new dict replaces the old one. The first request for a project in each process runs `migrate` on that alias, under a per-alias lock and a Postgres advisory lock. A database router sends every query to the alias admitted for the current request, which it reads from a `ContextVar`. With project databases on, the `default` alias is Django's dummy backend, so a query outside an admitted request fails instead of landing somewhere shared.

This approach was chosen over the alternatives:
- **django-tenants** partitions by schema, not by database.
- **A thread-local alias** breaks under uvicorn/ASGI. There, ORM calls run in `sync_to_async` threads that inherit `ContextVar`s but not thread-locals.
- **One process per project** needs one process per project.

The engine's `project` row stays as the root its tables hang off. It carries the platform project's pid as its own and names no other project. `evaluation.system_id` becomes a real foreign key to this database's `project.system`, which Plan 2 creates.

**Tech Stack:** Django 6.0.6 + django-ninja 1.6 + psycopg 3 + httpx, served by uvicorn (ASGI). Celery 5 + requests (apps/eval). React + Vite + vitest (apps/webapp). FastAPI + psycopg (platform). Postgres 14, docker compose.

**Spec:** `docs/superpowers/plans/2026-09-23-project-databases-roadmap.md`, plan 4. Also the planner brief (`.superpowers/sdd/planner-brief.md`), including its binding "Lesson from Plan 1's final review": the pid that is checked is the pid whose database is opened, on every request and in the same code path.

## Before you start (a gate, not a task)

Run these three checks. If any one fails, stop and ask the user. Don't work around it.

1. **Plan 2 has landed.** `ls platform/project-template/0002_system.sql`, then `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d project_01399e174b014be9997a7f5e3574ab22 -Atc "select to_regclass(\$\$project.system\$\$)"'` prints `project.system`. This plan assumes `project.system` has `pid uuid PRIMARY KEY`, the same as `core.system`. Check with `\d project.system` in the same database.
2. **The engine at HEAD imports.** Using `bm` (defined below), run `bm test aisc_backend.tests.test_sample`. It must not stop at `ImportError: cannot import name 'list_openai_models' from 'aisc_plugin_interface'`. On 2026-09-23 it does. `apps/backend` e34fca3 (the merge of Sean's feat/aisystem) imports a function that `shared/plugin-interface` does not have, so the backend suite cannot run at HEAD, and the running container is still the pre-merge image. The user must say which plugin-interface to use.
3. **The baseline.** `bm test aisc_backend.tests.routers aisc_backend.tests.repositories aisc_backend.tests.keycloak aisc_backend.tests.test_sample aisc_backend.tests.test_platform_links aisc_backend.tests.test_every_project_route_is_guarded` ends in `OK`. `cd apps/webapp && npx vitest run && npx tsc -b --noEmit` passes (29 tests on 2026-09-23). Write down both results. "Nothing that passed before fails" in the steps below is measured against them.

## Global Constraints

- **Database name.** A project's database is `project_` plus the project pid, lowercased, with hyphens removed. Example: pid `3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b` → `project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b`. The same example is asserted in `platform/tests/test_project_databases.py` and in `apps/backend/aisc_backend/tests/project_database/test_names_and_routing.py`.
- **The pid rule.** Anything used to build a database name must first match `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (case-insensitive). Otherwise it is refused before anything is connected to. The SPA and the worker apply the same regex before they send a pid.
- **The header.** `X-AISC-Project: <pid>` is on every call to `/api/*` except `/api/docs`, `/api/openapi.json`, `/api/v1/app/app-name`, `/api/v1/me`, `/api/v1/me/admin`, `/api/v1/audit` and `GET /api/v1/plugins`. The worker adds `X-AISC-Run: <evaluation pid>.<hmac>`.
- **The door's answers.** Every one of these is given before the project's database is opened:

  | Case | Answer |
  |---|---|
  | No header | 400 |
  | Header is not a pid | 404 |
  | No token (auth on) | 401 |
  | Platform not answering | 503 |
  | Caller is a stranger | 404 |
  | Viewer on a write | 403 |
  | Worker: wrong or missing shared secret | 401 |
  | Worker: ticket for another project or evaluation | 403 |

- **What counts as a write.** Any method other than GET, HEAD or OPTIONS. The exceptions are the POSTs in `projectdb.READ_POSTS`, which only read (measurement aggregation, dimension keys and values, metric names, plugin config state).
- **A second pid in a path or body.** When a pid in a path or body names a project, it must equal the header's pid, or the answer is 404. `membership.same_project()` enforces this, and a test pins it for each such route.
- **Connections.** The engine opens one connection per project database per request thread (`CONN_MAX_AGE = 0`) and closes it when the request ends.
- **Roles and secrets.** `engine_rw` keeps its name and its dev password (`engine_rw`). No new secret is committed. The run ticket's key is the existing `DJANGO_SECRET_KEY`. `POSTGRES_USER`/`POSTGRES_PASSWORD` are never echoed.
- **Postgres** is 14: `DROP DATABASE … WITH (FORCE)` works.
- **No shared schema is dropped, altered or migrated.** `platform.engine` is abandoned where it stands, at migration 0019. After Task 8 the backend never connects to the `platform` database. Dropping it belongs to Plan 6 and needs the user's go-ahead.
- **HARD RULE** (`.superpowers/sdd/2026-09-23-project-databases-1-controls/constraints.md`). Never DROP, ALTER or delete rows in any database you did not create in this task. The real project database, `project_01399e174b014be9997a7f5e3574ab22`, changes only through the platform's provisioning (Task 1) and the engine's own migrations (Task 8). Integration tests make throwaway databases and drop only those.
- **The deployed image.** The `aisc-backend` image is not rebuilt between Task 4 and Task 8. Tasks 4–7 are tested from the working tree, mounted into throwaway containers, while the running engine stays on its current image and keeps working. Task 8 rebuilds and switches it over. The worker (Task 3) and the SPA (Task 2) deploy early, because what they send is harmless to the current backend.
- **The dashboard.** Superset still reads the shared `engine` schema until Plan 5. After Task 8, new engine results exist only in project databases. That is expected.
- **Object storage.** The S3 buckets stay shared, as they are today. An object is reachable only through a row in the project's database (`membership.for_stored_file`). Splitting the buckets is not part of this plan.
- **Commits.**
  - Nothing is pushed.
  - Commits go to `feat/unified-modules` in `apps/backend`, `apps/eval` and `apps/webapp`.
  - The root gets pointer bumps plus its own files. The root pointers of these three submodules already show `M` because of commits made before this plan (the e34fca3 merges). A bump carries those commits too, which is expected.
  - Stage explicit paths only. `docker-compose.development.yml` and `scripts/verify.sh` have unrelated uncommitted qualification-prefill hunks: use `git add -p` and take only this plan's hunks.
  - This plan does not touch `apps/qualification` or `apps/results-dashboard`. Leave their uncommitted work alone.
- **Line numbers.** They are as of root `c8a2637`, `apps/backend` `e34fca3`, `apps/eval` `e5b1b0a` and `apps/webapp` `429f62c`. Plans 2 and 3 edit some of the same scripts. If a number has moved, find the quoted text.

**Commands used below.** Run them from `/home/listuser/aisc-install`, in a shell where these are defined:

```bash
set -a; . ./env.secrets; set +a
DC="docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml"

# manage.py of the backend's working tree, on sqlite, in a throwaway container
# from the current image. The image's baked plugin packages are older than
# shared/, so the ones in shared/ are installed into the throwaway venv first.
bm() {
  docker run --rm -w /app \
    -v "$PWD/apps/backend/aisc_backend:/app/aisc_backend:ro,z" \
    -v "$PWD/apps/backend/config:/app/config:ro,z" \
    -v "$PWD/shared:/src/shared:ro,z" \
    -e DB_ENGINE=django.db.backends.sqlite3 -e DB_NAME=/tmp/unit.db \
    --entrypoint sh aisc-backend:latest -c \
    'cp -r /src/shared /tmp/shared && uv pip install -q --no-deps /tmp/shared/plugin-manager /tmp/shared/plugin-interface && exec .venv/bin/python manage.py "$@"' sh "$@"
}

# The worker's unit tests on its working tree, in a throwaway container.
ev() {
  docker run --rm -w /w -v "$PWD/apps/eval:/w:ro,z" -e PYTHONPATH=/w \
    --entrypoint /app/.venv/bin/python aisc-eval:latest -m unittest "$@"
}
```

## Review Focus

1. **A header that names a project the caller is not in, or a path or body pid that differs from the header's** (`POST /evaluations/task {"project_pid": B}` with header A). Expected: 404, the platform was asked about A only, B's rows are untouched, and no database is opened for a refusal. Pinned in Task 6 for every mutating route.
2. **A viewer on any write, including one addressed by a child row's id.** Expected: 403 at the door before anything is opened, while the read-only POSTs still work. Pinned in Task 6 by enumerating the API.
3. **A worker call with no secret, a forged ticket, or a ticket for another project or evaluation.** Expected: 401 or 403, and nothing is opened or written. Pinned in Task 6. Task 3 pins that the worker sends the header and ticket on every call.
4. **Four requests opening a brand-new project database at once.** Expected: one migration, and all four wait for it. Pinned in Task 4 (threads). Across processes, the advisory lock is there, and Task 8's live run shows it.
5. **Nothing global.** Expected: an ORM call outside an admitted request fails. Metrics, users and sessions exist per database, and no model has `public` or a link to another project. Pinned in Tasks 4, 5 and 7.

---

## File map

**Root repo (`~/aisc-install`)**
- Create `platform/project-template/0004_engine.sql`: the engine's schema in each project database, `CONNECT` for `engine_rw`, and `REFERENCES` on `project.system`.
- Modify `platform/tests/test_project_databases.py`: the engine may work in its schema, and a module that has no project data may still not connect.
- Modify `docker-compose.development.yml`: `aisc-backend` gets `PROJECT_DATABASES` and `PLATFORM_URL`, loses `DB_NAME` and its startup `migrate`, and depends on a new one-shot `aisc-backend-migrate` service.
- Modify `Caddyfile`: remove `/admin*` and `/static/admin/*`.
- Modify `scripts/verify-one-database.sh`, `scripts/verify-rbac.sh`, `scripts/verify-sso.sh`, `scripts/verify-catalogue-mapping.sh` and `scripts/verify.sh` (the engine backend line).

**`apps/backend`**
- Create `aisc_backend/projectdb.py`: the name rule, per-project aliases, first-use migration, the router, `admit()`, run tickets.
- Create `aisc_backend/project_door.py`: the middleware.
- Create `aisc_backend/management/__init__.py`, `aisc_backend/management/commands/__init__.py`, `aisc_backend/management/commands/migrate_projects.py`.
- Create `aisc_backend/migrations/0022_the_database_is_the_project.py`.
- Create `scripts/test-project-databases.sh`: throwaway project databases for the Postgres tests.
- Modify `config/settings.py` (database block, router, middleware, CORS header, `PLATFORM_URL`, admin/allauth removal), `config/urls.py`.
- Delete `config/jwt.py` and `aisc_backend/admin.py`.
- Modify `aisc_backend/models/project.py`, `aisc_backend/schemas/project.py`, `aisc_backend/repositories/project_repository.py`, `aisc_backend/platform_projects.py`, `aisc_backend/auth/keycloak.py` and `aisc_backend/auth/membership.py`.
- Modify `aisc_backend/routers/project.py`, `aisc_backend/routers/evaluation.py`, `aisc_backend/routers/plugin.py` and `aisc_backend/services/celery_service.py`.
- Tests:
  - Create `aisc_backend/tests/project_database/{__init__.py,test_names_and_routing.py,test_postgres.py,test_door.py,test_nothing_global.py}`.
  - Rewrite `aisc_backend/tests/test_platform_links.py`.
  - Modify `aisc_backend/tests/routers/test_project_membership.py`, `aisc_backend/tests/routers/test_project_router.py` and `aisc_backend/tests/test_every_project_route_is_guarded.py`.

**`apps/eval`**
- Modify `aisc_eval/service/api_client.py` (the run context, and headers on every call) and `aisc_eval/celery_tasks.py` (every task carries the project and ticket).
- Create `tests/test_run_context.py`.

**`apps/webapp`**
- Create `src/platform/projectHeader.ts` and `src/platform/projectHeader.test.ts`.
- Modify `src/platform/currentProject.ts` and its test, `src/main.tsx`, `src/pages/GlobalHome.tsx`, `src/components/TopBar.tsx:166` and `src/components/PluginInstallDialog.tsx:22,59`.

---

### Task 1: Each project database gets the engine's schema

**Files:**
- Create: `platform/project-template/0004_engine.sql`
- Test: `platform/tests/test_project_databases.py` (the test at line 56, plus a new one)

**Interfaces:**
- Consumes: `projectdb.provision()` applying every `platform/project-template/*.sql` in order (Plan 1). `project.system (pid uuid PRIMARY KEY, …)` from `0002_system.sql` (Plan 2).
- Produces: in every project database, `engine_rw` may `CONNECT`, has `USAGE, CREATE` on schema `engine`, and has `USAGE` on schema `project` plus `SELECT, REFERENCES` on `project.system`.

- [ ] **Step 1: Write the failing tests.** In `platform/tests/test_project_databases.py`, replace the body of `test_nobody_but_the_listed_roles_may_connect` (lines 56–59) so that it probes a role that is never given a project database. The catalogue is one for all projects:

```python
@needs_database
def test_nobody_but_the_listed_roles_may_connect(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    # The catalogue is one, for every project: it has no data in any of them.
    with pytest.raises(psycopg.OperationalError):
        _as(dsn, "catalogue_rw", projectdb.database_name(created["pid"]))
```

Add after it:

```python
@needs_database
def test_the_engine_works_in_its_own_schema(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with _as(dsn, "engine_rw", projectdb.database_name(created["pid"])) as conn:
        conn.execute("create table engine.probe (x int)")
        conn.execute("drop table engine.probe")
        # An evaluation names the system it ran against: this project's own.
        may_reference = conn.execute(
            "select has_table_privilege('project.system', 'REFERENCES')"
        ).fetchone()[0]
    assert may_reference is True
```

- [ ] **Step 2: Run them and watch the new one fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_project_databases.py -v`
Expected: `test_the_engine_works_in_its_own_schema` FAILS with `psycopg.OperationalError: … permission denied for database "project_…"`. Every other test passes, including the rewritten `test_nobody_but_the_listed_roles_may_connect`.

- [ ] **Step 3: Write the template.** Create `platform/project-template/0004_engine.sql`:

```sql
-- Step 4, the execution engine: its schema in this project's database, owned
-- by its role.
--
-- Everything the engine keeps for this project lives here: the AI system and
-- its components, the plugins this project uses, evaluations, observations,
-- measurements, the metric catalogue, and Django's own users and sessions. The
-- plugin code itself is shared, on PLUGIN_PATH; which plugins this project
-- uses is recorded here.
DO $grant$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO engine_rw', current_database());
END
$grant$;

CREATE SCHEMA IF NOT EXISTS engine;
GRANT USAGE, CREATE ON SCHEMA engine TO engine_rw;
COMMENT ON SCHEMA engine IS 'Step 4: this project''s AI system, plugins, evaluations and measurements.';

-- An evaluation names the system it ran against, which is this project's own
-- system, in this database (0002_system.sql). A foreign key needs REFERENCES;
-- showing its name needs SELECT. The engine writes neither.
GRANT USAGE ON SCHEMA project TO engine_rw;
GRANT SELECT, REFERENCES ON project.system TO engine_rw;
```

- [ ] **Step 4: Run the tests.**

Run: `cd platform && uv run --extra dev pytest -v`
Expected: every test PASSES.

- [ ] **Step 5: Give the existing projects the new template.** The platform provisions every existing project at its first query after start (`platform/platform_service/db.py:51`, `provision_all()`).

Run: `$DC up -d --build platform && sleep 5 && docker exec platform python -c "from platform_service import db; db.pool()" && docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select has_database_privilege(\$\$engine_rw\$\$, \$\$project_01399e174b014be9997a7f5e3574ab22\$\$, \$\$CONNECT\$\$)"'`
Expected: `t`.

- [ ] **Step 6: Commit** (root).

```bash
git add platform/project-template/0004_engine.sql platform/tests/test_project_databases.py
git commit -m "Every project database has a schema for the engine, and the engine may point at its system"
```

---

### Task 2: The SPA names the project on every API call

**Files:**
- Create: `apps/webapp/src/platform/projectHeader.ts`, `apps/webapp/src/platform/projectHeader.test.ts`
- Modify: `apps/webapp/src/platform/currentProject.ts` (whole file), `apps/webapp/src/platform/currentProject.test.ts` (whole file)
- Modify: `apps/webapp/src/main.tsx` (before `const queryClient`), `apps/webapp/src/pages/GlobalHome.tsx` (whole file), `apps/webapp/src/components/TopBar.tsx:166`, `apps/webapp/src/components/PluginInstallDialog.tsx:22,59`

**Interfaces:**
- Produces:
  - `PROJECT_HEADER = "X-AISC-Project"`
  - `isApiCall(url: string, apiBase: string): boolean`
  - `installProjectHeader(apiBase: string, getProject?: () => string | null, target?: { fetch: typeof fetch }): void`
  - `currentPlatformProject(search?: string, storage?: Storage | null, lasting?: Storage | null): string | null`. It only ever returns a pid.
  - `projectsUrl(apiUrl: string): string`
- The current backend ignores the header, so this deploys now.

Every call in the SPA goes through `fetch` (`grep -rn "fetch(" src`). The one `axios` user, `src/components/UploadFileField.tsx`, is imported nowhere, so nothing but `fetch` needs the header.

- [ ] **Step 1: Write the failing tests.** Create `src/platform/projectHeader.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { installProjectHeader, isApiCall, PROJECT_HEADER } from "./projectHeader";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const API = "http://localhost/api";

function target() {
  const seen: Array<{ url: string; headers: Headers }> = [];
  const t = {
    fetch: vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
      seen.push({ url, headers });
      return new Response("{}");
    }) as unknown as typeof fetch,
  };
  return { t, seen };
}

describe("every call to the engine's API says which project it is for", () => {
  it("adds the project to a call to the API", async () => {
    const { t, seen } = target();
    installProjectHeader(API, () => PID, t);
    await t.fetch(`${API}/v1/projects`);
    expect(seen[0].headers.get(PROJECT_HEADER)).toBe(PID);
  });

  it("keeps the headers the call already had", async () => {
    const { t, seen } = target();
    installProjectHeader(API, () => PID, t);
    await t.fetch(`${API}/v1/plugins`, { method: "POST", headers: { "Content-Type": "application/json" } });
    expect(seen[0].headers.get("Content-Type")).toBe("application/json");
    expect(seen[0].headers.get(PROJECT_HEADER)).toBe(PID);
  });

  it("carries it on a Request object too", async () => {
    const { t, seen } = target();
    installProjectHeader(API, () => PID, t);
    await t.fetch(new Request(`${API}/v1/plugins`, { method: "POST" }));
    expect(seen[0].headers.get(PROJECT_HEADER)).toBe(PID);
  });

  it("leaves every other address alone: the realm and the catalogue get no project", async () => {
    const { t, seen } = target();
    installProjectHeader(API, () => PID, t);
    await t.fetch("http://localhost:8081/realms/aisc/protocol/openid-connect/token");
    await t.fetch("http://localhost:8102/tool/");
    expect(seen.map((s) => s.headers.get(PROJECT_HEADER))).toEqual([null, null]);
  });

  it("sends nothing when no project is known", async () => {
    const { t, seen } = target();
    installProjectHeader(API, () => null, t);
    await t.fetch(`${API}/v1/me`);
    expect(seen[0].headers.get(PROJECT_HEADER)).toBeNull();
  });

  it("knows a call to the API when it sees one", () => {
    expect(isApiCall(`${API}/v1/projects`, API)).toBe(true);
    expect(isApiCall("/api/v1/projects", API)).toBe(true);
    expect(isApiCall("http://localhost/controls/p/x", API)).toBe(false);
    expect(isApiCall("http://localhost/apix", API)).toBe(false);
  });
});
```

Replace `src/platform/currentProject.test.ts` with:

```ts
import { describe, it, expect } from "vitest";
import {
  currentPlatformProject,
  projectForPlatformUrl,
  projectPageUrl,
  projectsUrl,
} from "./currentProject";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const OTHER = "11111111-1111-4111-8111-111111111111";

const store = (): Storage => {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;
};

describe("the platform project the engine was opened from", () => {
  it("is the one in the URL", () => {
    expect(currentPlatformProject(`?project=${PID}`, store(), store())).toBe(PID);
  });

  it("is remembered for the tab, so navigating inside the app keeps it", () => {
    const tab = store();
    currentPlatformProject(`?project=${PID}`, tab, store());
    expect(currentPlatformProject("", tab, store())).toBe(PID);
  });

  it("is remembered for the browser, so an install arriving in a new tab lands in it", () => {
    const lasting = store();
    currentPlatformProject(`?project=${PID}`, store(), lasting);
    expect(currentPlatformProject("", store(), lasting)).toBe(PID);
  });

  it("is the tab's own before the browser's last one", () => {
    const tab = store();
    const lasting = store();
    currentPlatformProject(`?project=${OTHER}`, store(), lasting);
    currentPlatformProject(`?project=${PID}`, tab, store());
    expect(currentPlatformProject("", tab, lasting)).toBe(PID);
  });

  it("is never anything but a project id", () => {
    const tab = store();
    expect(currentPlatformProject("?project=../admin", tab, store())).toBeNull();
    tab.setItem("aisc_platform_project", "abc");
    expect(currentPlatformProject("", tab, store())).toBeNull();
  });

  it("is simply absent when the engine is opened on its own", () => {
    expect(currentPlatformProject("", store(), store())).toBeNull();
  });

  it("survives a browser that refuses storage", () => {
    const hostile = {
      getItem: () => { throw new Error("denied"); },
      setItem: () => { throw new Error("denied"); },
    } as unknown as Storage;
    expect(currentPlatformProject(`?project=${PID}`, hostile, hostile)).toBe(PID);
    expect(currentPlatformProject("", hostile, hostile)).toBeNull();
  });
});

// The header says which project; the database behind it is that project. So
// the list is that project's row, and there is no second project to ask for.
describe("the projects call the engine makes", () => {
  it("asks for this project's row", () => {
    expect(projectsUrl("http://localhost/api/v1")).toBe("http://localhost/api/v1/projects");
  });
});

describe("the engine's row for the project it was opened on", () => {
  it("is asked for by the platform project, not created by a person", () => {
    expect(projectForPlatformUrl("http://localhost/api/v1", PID)).toBe(
      `http://localhost/api/v1/projects/for-platform/${PID}`,
    );
  });

  it("escapes what it puts in the path", () => {
    expect(projectForPlatformUrl("/api/v1", "a/b")).toBe("/api/v1/projects/for-platform/a%2Fb");
  });
});

describe("the way back to the project", () => {
  it("is that project's page on the launcher", () => {
    expect(projectPageUrl("http://localhost:8100/", PID)).toBe(`http://localhost:8100/p/${PID}`);
  });

  it("is the launcher itself when no project is known", () => {
    expect(projectPageUrl("http://localhost:8100/", null)).toBe("http://localhost:8100");
  });

  it("does not care how the launcher URL was written", () => {
    expect(projectPageUrl("http://localhost:8100///", PID)).toBe(`http://localhost:8100/p/${PID}`);
  });
});
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/webapp && npx vitest run src/platform`
Expected: `projectHeader.test.ts` fails with `Failed to resolve import "./projectHeader"`. In `currentProject.test.ts`, "is never anything but a project id", "is remembered for the browser…" and "the projects call…" FAIL.

- [ ] **Step 3: Implement.** Create `src/platform/projectHeader.ts`:

```ts
/**
 * Every call to the engine's API says which project it is for.
 *
 * Each project keeps its tests and results in a database of its own. The
 * backend opens the one this header names, after asking the platform whether
 * the caller is in that project. The page knows the project from the
 * launcher's ?project=; this puts it on every request to the API, so no call
 * in the app can forget it.
 */
import { currentPlatformProject } from "./currentProject";

export const PROJECT_HEADER = "X-AISC-Project";

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/** Is this address the engine's API (absolute, or relative to this origin)? */
export function isApiCall(url: string, apiBase: string): boolean {
  const base = apiBase.replace(/\/+$/, "");
  return url.startsWith(`${base}/`) || url.startsWith("/api/");
}

/** Wrap `target.fetch` so calls to the API carry the current project. */
export function installProjectHeader(
  apiBase: string,
  getProject: () => string | null = () => currentPlatformProject(),
  target: { fetch: typeof fetch } = window,
): void {
  const original = target.fetch.bind(target);
  target.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const project = getProject();
    if (!project || !isApiCall(urlOf(input), apiBase)) return original(input, init);
    if (input instanceof Request && !init) {
      const headers = new Headers(input.headers);
      headers.set(PROJECT_HEADER, project);
      return original(new Request(input, { headers }));
    }
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set(PROJECT_HEADER, project);
    return original(input, { ...init, headers });
  }) as typeof fetch;
}
```

Replace `src/platform/currentProject.ts` with:

```ts
/**
 * The platform project this engine was opened from.
 *
 * The launcher opens each step with the project being worked on. Every project
 * keeps what the engine does for it in its own database, and the backend opens
 * the one named on each call (see projectHeader.ts). Without a project the
 * engine has nothing to open.
 */
const KEY = "aisc_platform_project";
// The last project opened in this browser. An install from the catalogue
// arrives in a new tab, which has no tab storage yet; it lands here.
const LAST = "aisc_last_platform_project";
const PID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function read(storage: Storage | null, key: string): string | null {
  try {
    const found = storage?.getItem(key) ?? null;
    return found && PID.test(found) ? found : null;
  } catch {
    return null;
  }
}

function write(storage: Storage | null, key: string, value: string): void {
  try {
    storage?.setItem(key, value);
  } catch {
    /* private window: the project still works for this page load */
  }
}

/** The project in the URL (`?project=<uuid>`), else this tab's, else this browser's last. */
export function currentPlatformProject(
  search: string = typeof window === "undefined" ? "" : window.location.search,
  storage: Storage | null = typeof window === "undefined" ? null : window.sessionStorage,
  lasting: Storage | null = typeof window === "undefined" ? null : window.localStorage,
): string | null {
  const fromUrl = new URLSearchParams(search).get("project");
  if (fromUrl && PID.test(fromUrl)) {
    write(storage, KEY, fromUrl);
    write(lasting, LAST, fromUrl);
    return fromUrl;
  }
  return read(storage, KEY) ?? read(lasting, LAST);
}

/**
 * Where to ask for this project's row. The header names the project and the
 * database behind it is that project, so there is exactly one to list.
 */
export function projectsUrl(apiUrl: string): string {
  return `${apiUrl}/projects`;
}

/**
 * Where to ask for this service's row for a platform project.
 *
 * There is no workspace to create in the engine. The project was chosen on the
 * launcher, so the engine asks for its own side of it: the first visit makes
 * the row, every visit after finds it, and nobody is asked to name anything.
 */
export function projectForPlatformUrl(apiUrl: string, project: string): string {
  return `${apiUrl}/projects/for-platform/${encodeURIComponent(project)}`;
}

/**
 * The way back to the project page on the launcher, where all six steps are.
 */
export function projectPageUrl(
  launcherUrl: string,
  project: string | null = currentPlatformProject(),
): string {
  const launcher = launcherUrl.replace(/\/+$/, "");
  return project ? `${launcher}/p/${encodeURIComponent(project)}` : launcher;
}
```

In `src/main.tsx`, add after the `import {Toaster} from "react-hot-toast";` line:

```ts
import { installProjectHeader } from './platform/projectHeader'

// Every call to the API names the project it is for. The backend opens that
// project's database, after asking the platform about this caller.
installProjectHeader(`${import.meta.env.VITE_API_URL}/api`)
```

In `src/components/TopBar.tsx:166`, change `apiCall(projectsUrl('', currentPlatformProject()))` to `apiCall(projectsUrl(''))`.

In `src/components/PluginInstallDialog.tsx`, change line 22 to `import { projectsUrl } from '../platform/currentProject';` and line 59 to `fetch(projectsUrl(API_URL))`.

Replace `src/pages/GlobalHome.tsx` with:

```tsx
import { Box, Button, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_VERSION_PREFIX } from "../config";
import { useAuth } from "../context/AuthContext";
import { useProject } from "../context/ProjectContext";
import { currentPlatformProject, projectForPlatformUrl } from "../platform/currentProject";
import "../styles/common.css";
import "./GlobalHome.css";

const API_URL = import.meta.env.VITE_API_URL + API_VERSION_PREFIX;
const LAUNCHER_URL = (import.meta.env.VITE_LAUNCHER_URL as string) || "http://localhost:8100/";

interface Project {
    pid: string;
    name: string;
}

/**
 * Opened without a project.
 *
 * Every project keeps its tests and results in its own database, and the
 * engine opens the one it was sent to from the launcher. There is no list of
 * projects here to choose from.
 */
const NoProject = () => (
    <Box sx={{ width: 1, maxWidth: 900, mx: "auto", px: 2, mt: 4, textAlign: "center" }}>
        <Typography variant="h5" fontWeight={700} gutterBottom>
            Open a project first
        </Typography>
        <Typography variant="body1" color="text.secondary" gutterBottom>
            The execution engine works inside one project at a time. Choose the
            project on the launcher, then open step 4 from there.
        </Typography>
        <Button variant="contained" href={LAUNCHER_URL} sx={{ mt: 2 }}>
            Go to the launcher
        </Button>
    </Box>
);


/**
 * The project the engine was opened on.
 *
 * There is nothing to choose here: the project is chosen once, on the
 * launcher, and opening the engine inside it means working on it. This asks the
 * backend for its own row for that project (made on the first visit, found
 * every time after) and goes straight in.
 */
const OpenTheProject = ({ project }: { project: string }) => {
    const { setProjectUUID, setProjectName } = useProject();
    const navigate = useNavigate();
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        fetch(projectForPlatformUrl(API_URL, project), { method: "POST" })
            .then((res) => {
                if (!res.ok) throw new Error("Could not open this project.");
                return res.json();
            })
            .then((opened: Project) => {
                setProjectUUID(opened.pid);
                setProjectName(opened.name);
                navigate(`/projects/${opened.name}`, { replace: true });
            })
            .catch((err) => setError(err.message));
    }, [project, navigate, setProjectUUID, setProjectName]);

    if (error) {
        return (
            <Typography color="error" sx={{ textAlign: "center", mt: 4 }}>
                {error}
            </Typography>
        );
    }
    return <Typography sx={{ textAlign: "center", mt: 4 }}>Opening the project…</Typography>;
};


/**
 * Home page component
 *
 * Inside a project (opened from the launcher) there is nothing to pick: it goes
 * straight into that project. Without one there is nothing to open.
 */
const GlobalHome = () => {
    const { authenticated } = useAuth();
    const platformProject = currentPlatformProject();

    if (!authenticated) {
        return (
            <Box className="auth-message">
                <Typography variant="h4" fontWeight={700} gutterBottom>
                    AI Assessment Sandbox
                </Typography>
                <Typography variant="body1" color="text.secondary">
                    Please sign in to get started.
                </Typography>
            </Box>
        );
    }

    if (platformProject) return <OpenTheProject project={platformProject} />;

    return <NoProject />;
};

export default GlobalHome;
```

- [ ] **Step 4: Run the suite and the type check.**

Run: `cd apps/webapp && npx vitest run && npx tsc -b --noEmit`
Expected: every test PASSES (the 29 from the baseline plus the new ones, minus the three old `projectsUrl` cases that were replaced). `tsc` prints nothing.

- [ ] **Step 5: Deploy it and check the bundle carries the header.**

Run: `$DC up -d --build aisc-webapp && sleep 3 && docker exec aisc-webapp sh -c 'grep -l "X-AISC-Project" /usr/share/nginx/html/assets/*.js | head -1'`
Expected: one file name under `/usr/share/nginx/html/assets/`.

- [ ] **Step 6: Commit** (inside `apps/webapp`, then the pointer in the root).

```bash
(cd apps/webapp && git add src/platform/projectHeader.ts src/platform/projectHeader.test.ts src/platform/currentProject.ts src/platform/currentProject.test.ts src/main.tsx src/pages/GlobalHome.tsx src/components/TopBar.tsx src/components/PluginInstallDialog.tsx && git commit -m "Every call to the API says which project it is for")
git add apps/webapp && git commit -m "Engine SPA names the project on every API call"
```

---

### Task 3: The worker carries the project and its run ticket on every call

**Files:**
- Modify: `apps/eval/aisc_eval/service/api_client.py` (lines 1–16, and every `headers=headers` at lines 20, 31, 43, 49, 57, 61, 73, 82, 91, 97, 104, 111, 118, 143 and 163)
- Modify: `apps/eval/aisc_eval/celery_tasks.py` (the imports at line 20; the tasks at lines 102–103, 161–162, 237–241, 437–438, 447–448, 467–472; the four signatures inside `run_evaluation`, at lines 188, 207, 222 and 226)
- Test: `apps/eval/tests/test_run_context.py`

**Interfaces:**
- Produces:
  - `api_client.running(project_pid: str | uuid.UUID | None, ticket: str | None)`, a context manager. Inside it, every call sends `X-AISC-Project` and `X-AISC-Run`. With `None` it sends neither, which is what an evaluation queued by the current backend gets.
  - `api_client.PROJECT_HEADER = "X-AISC-Project"` and `api_client.RUN_HEADER = "X-AISC-Run"`.
  - Every task keeps its positional signature and gains `project_pid: str | None = None, ticket: str | None = None`, which it passes to every task it starts.
- Consumes (from Task 6, later): the backend sends `send_task("aisc_eval.celery_tasks.run_evaluation", args=[evaluation_pid], kwargs={"project_pid": …, "ticket": …})`.

The survey says the worker only calls the backend over HTTP. That is confirmed: `grep -rn "psycopg\|django\|sqlalchemy\|DATABASE_URL" apps/eval --include=*.py --include=*.toml` finds nothing, and every call goes through `aisc_eval/service/api_client.py`.

- [ ] **Step 1: Write the failing test.** Create `apps/eval/tests/test_run_context.py`:

```python
"""Every call the worker makes says which project, and on which run's ticket.

Each project has its own database, and the backend opens the one the call
names, after checking the ticket it gave this run for this project. A call that
forgot the project would be refused; one that named the wrong project would be
refused too. So the project is set once per task, and every call carries it.
"""
import unittest
import uuid
from unittest import mock

from aisc_eval import celery_tasks as tasks
from aisc_eval.service import api_client

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
EVALUATION = "5d0c6a1e-2b3f-4c4d-8e9f-0a1b2c3d4e5f"
TICKET = EVALUATION + "." + "ab" * 32


class EveryCallSaysWhichProjectTestCase(unittest.TestCase):
    def test_inside_a_run_a_call_carries_the_project_and_the_ticket(self):
        with mock.patch.object(api_client.requests, "get") as get:
            with api_client.running(PID, TICKET):
                api_client.get_evaluation_inputs(EVALUATION)
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(PID, headers[api_client.PROJECT_HEADER])
        self.assertEqual(TICKET, headers[api_client.RUN_HEADER])

    def test_every_write_the_worker_makes_carries_it(self):
        with mock.patch.object(api_client.requests, "put") as put, \
                mock.patch.object(api_client.requests, "patch") as patch_, \
                mock.patch.object(api_client.requests, "post") as post:
            post.return_value.status_code = 201
            with api_client.running(PID, TICKET):
                api_client.mark_completed(EVALUATION)
                api_client.mark_failed(EVALUATION)
                api_client.mark_plugin_started(EVALUATION, EVALUATION)
                api_client.mark_plugin_failed(EVALUATION, EVALUATION, "x")
                api_client.post_measures(EVALUATION, EVALUATION, [])
                api_client.upload_artifact(EVALUATION, EVALUATION, "a.txt", b"x")
        calls = put.call_args_list + patch_.call_args_list + post.call_args_list
        self.assertEqual(7, len(calls))
        for call in calls:
            self.assertEqual(PID, call.kwargs["headers"][api_client.PROJECT_HEADER])

    def test_outside_a_run_nothing_is_added(self):
        with mock.patch.object(api_client.requests, "get") as get:
            api_client.get_evaluation_inputs(EVALUATION)
        self.assertNotIn(api_client.PROJECT_HEADER, get.call_args.kwargs["headers"])

    def test_a_project_that_is_not_a_pid_is_refused_before_any_call(self):
        with self.assertRaises(ValueError):
            with api_client.running("../platform", TICKET):
                pass

    def test_the_run_ends_with_the_task(self):
        with api_client.running(PID, TICKET):
            pass
        self.assertNotIn(api_client.PROJECT_HEADER, api_client._headers())


class TheRunIsPassedDownTheChainTestCase(unittest.TestCase):
    def _run(self, **run):
        plugin = mock.Mock(package_name="pkg", version="1.0", pid=uuid.uuid4(), plugin_config=None)
        plugin.name = "p"
        evaluation = mock.Mock(evaluation_plugins=[plugin])
        evaluation.project.pid = PID
        seen = {}

        def settings_call(*_args, **_kwargs):
            seen["headers"] = api_client._headers()
            return []

        with mock.patch.object(tasks, "plugin_loader"), \
                mock.patch.object(tasks, "get_evaluation", return_value=evaluation), \
                mock.patch.object(tasks, "get_evaluation_inputs", return_value={}), \
                mock.patch.object(tasks, "get_project_settings_by_pid", side_effect=settings_call), \
                mock.patch.object(tasks, "group"), mock.patch.object(tasks, "chain"), \
                mock.patch.object(type(tasks.celery_app), "backend", new_callable=mock.PropertyMock), \
                mock.patch.object(tasks.install_package, "si") as install, \
                mock.patch.object(tasks.run_plugin, "si") as run_plugin, \
                mock.patch.object(tasks.post_measurements, "s") as post, \
                mock.patch.object(tasks.finalize_evaluation, "si") as finalize:
            tasks.run_evaluation(EVALUATION, **run)
        return seen, (install, run_plugin, post, finalize)

    def test_every_task_the_evaluation_starts_is_given_the_project_and_ticket(self):
        seen, signatures = self._run(project_pid=PID, ticket=TICKET)
        for signature in signatures:
            self.assertEqual(PID, signature.call_args.kwargs["project_pid"])
            self.assertEqual(TICKET, signature.call_args.kwargs["ticket"])
        self.assertEqual(PID, seen["headers"][api_client.PROJECT_HEADER])

    def test_an_evaluation_queued_without_a_project_still_runs(self):
        seen, signatures = self._run()
        self.assertIsNone(signatures[-1].call_args.kwargs["project_pid"])
        self.assertNotIn(api_client.PROJECT_HEADER, seen["headers"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `ev tests.test_run_context -v`
Expected: errors with `AttributeError: module 'aisc_eval.service.api_client' has no attribute 'running'`.

- [ ] **Step 3: Implement the run context.** In `aisc_eval/service/api_client.py`, replace lines 1–16 (the imports and the module-level `headers = {…}`) with:

```python
import contextvars
import re
import uuid
from contextlib import contextmanager
from typing import Any

import requests
from pydantic import BaseModel
from aisc_plugin_interface import Measure

from aisc_eval.data_model.evaluation import Evaluation
from aisc_eval.utils.env import API_URL_PREFIX, INTERNAL_API_KEY
from aisc_eval.utils.logging import get_logger

logger = get_logger()

#: Which project a call is for: the backend opens that project's database.
PROJECT_HEADER = "X-AISC-Project"
#: The ticket the backend gave this run, for this project and this evaluation.
RUN_HEADER = "X-AISC-Run"
_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_run: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("aisc_run", default=None)


@contextmanager
def running(project_pid, ticket):
    """Every call made inside this is for this project, on this run's ticket.

    None is an evaluation queued by a backend that does not send them: its
    calls go out as they always did.
    """
    if project_pid is None:
        yield
        return
    text = str(project_pid).lower()
    if not _PID.match(text):
        raise ValueError(f"not a project id: {text!r}")
    token = _run.set((text, str(ticket or "")))
    try:
        yield
    finally:
        _run.reset(token)


def _headers() -> dict:
    found = {"X-Internal-Secret": INTERNAL_API_KEY}
    run = _run.get()
    if run is not None:
        found[PROJECT_HEADER], found[RUN_HEADER] = run
    return found
```

Then make every call use it:

```bash
cd apps/eval && sed -i 's/headers *= *headers/headers=_headers()/' aisc_eval/service/api_client.py && grep -c 'headers=_headers()' aisc_eval/service/api_client.py
```

Expected: `15`.

- [ ] **Step 4: Carry the run through every task.** In `aisc_eval/celery_tasks.py`, add `running,` to the `from aisc_eval.service.api_client import (…)` list (line 20).

Each task becomes a thin wrapper around its existing body. The body is renamed with a leading underscore and loses its decorator. Apply this to each of the six:

(a) Lines 102–103 become:

```python
@celery_app.task(bind=True)
def install_package(self, package_name: str, version: str, evaluation_pid: uuid.UUID,
                    evaluation_plugin_pids: list[uuid.UUID],
                    project_pid: str | None = None, ticket: str | None = None):
    """Install a package once using uv run to cache dependencies."""
    with running(project_pid, ticket):
        return _install_package(self, package_name, version, evaluation_pid, evaluation_plugin_pids)


def _install_package(self, package_name: str, version: str, evaluation_pid: uuid.UUID, evaluation_plugin_pids: list[uuid.UUID]):
```

(b) Lines 161–162 become the lines below. In the body that follows, the four signatures get the run:
- line 188: `install_package.si(` → append `project_pid=project_pid, ticket=ticket,` after the last positional argument;
- line 207: `run_plugin.si(` → append `project_pid=project_pid, ticket=ticket,` after `evaluation_plugin.pid,`;
- line 222: `post_measurements.s(evaluation_pid, evaluation_plugin.pid)` → `post_measurements.s(evaluation_pid, evaluation_plugin.pid, project_pid=project_pid, ticket=ticket)`;
- line 226: `finalize_evaluation.si(evaluation_pid)` → `finalize_evaluation.si(evaluation_pid, project_pid=project_pid, ticket=ticket)`.

```python
@celery_app.task(bind=True)
def run_evaluation(self, evaluation_pid: uuid.UUID,
                   project_pid: str | None = None, ticket: str | None = None) -> dict:
    with running(project_pid, ticket):
        return _run_evaluation(self, evaluation_pid, project_pid, ticket)


def _run_evaluation(self, evaluation_pid: uuid.UUID, project_pid: str | None, ticket: str | None) -> dict:
```

(c) Lines 237–241 (`run_plugin`'s decorator and signature) become:

```python
@celery_app.task(bind=True)
def run_plugin(self, package_name: str, plugin_name: str, version: str, plugin_config: dict,
               input_components: list[dict], project_settings: list[dict],
               evaluation_pid: uuid.UUID,
               evaluation_plugin_pid: uuid.UUID,
               project_pid: str | None = None, ticket: str | None = None) -> list[dict]:
    with running(project_pid, ticket):
        return _run_plugin(self, package_name, plugin_name, version, plugin_config,
                           input_components, project_settings, evaluation_pid, evaluation_plugin_pid)


def _run_plugin(self, package_name: str, plugin_name: str, version: str, plugin_config: dict,
                input_components: list[dict], project_settings: list[dict],
                evaluation_pid: uuid.UUID,
                evaluation_plugin_pid: uuid.UUID) -> list[dict]:
```

(d) Lines 437–438 become:

```python
@celery_app.task
def post_measurements(measurements_dict: list[dict], evaluation_pid: uuid.UUID, evaluation_plugin_uuid: uuid.UUID,
                      project_pid: str | None = None, ticket: str | None = None):
    with running(project_pid, ticket):
        return _post_measurements(measurements_dict, evaluation_pid, evaluation_plugin_uuid)


def _post_measurements(measurements_dict: list[dict], evaluation_pid: uuid.UUID, evaluation_plugin_uuid: uuid.UUID):
```

(e) Lines 447–448 become:

```python
@celery_app.task
def finalize_evaluation(evaluation_id: uuid.UUID,
                        project_pid: str | None = None, ticket: str | None = None) -> None:
    with running(project_pid, ticket):
        return _finalize_evaluation(evaluation_id)


def _finalize_evaluation(evaluation_id: uuid.UUID) -> None:
```

(f) `handle_error` (line 467 onwards) is wired to nothing today (`grep -rn "link_error\|handle_error" apps` finds only its definition). Give it the same two keyword parameters, and wrap its three-line body in `with running(project_pid, ticket):`, so it is right if it is ever wired.

- [ ] **Step 5: Run the tests.**

Run: `ev tests.test_run_context -v`
Expected: 7 tests, `OK`.

Also run `grep -n "headers=headers\|headers = headers" apps/eval/aisc_eval/service/api_client.py`. Expected: no output.

- [ ] **Step 6: Deploy it.** The current backend sends one positional argument, so `project_pid` is `None` and nothing changes for it.

Run: `$DC up -d --build aisc-eval-worker aisc-eval-flower && sleep 10 && docker exec aisc-eval-worker /app/.venv/bin/python -c "from aisc_eval.service import api_client; print(hasattr(api_client, 'running'))" && docker logs aisc-eval-worker 2>&1 | grep -m1 "ready"`
Expected: `True`, then a line containing `ready`.

- [ ] **Step 7: Commit** (inside `apps/eval`, then the pointer).

```bash
(cd apps/eval && git add aisc_eval/service/api_client.py aisc_eval/celery_tasks.py tests/test_run_context.py && git commit -m "Every call the worker makes says which project, on its run's ticket")
git add apps/eval && git commit -m "Engine worker carries the project on every call"
```

---

### Task 4: One Django database alias per project database, migrated on first use

**Files:**
- Create: `apps/backend/aisc_backend/projectdb.py`
- Modify: `apps/backend/config/settings.py` (the database block, lines 93–121)
- Create: `apps/backend/scripts/test-project-databases.sh`
- Test: `apps/backend/aisc_backend/tests/project_database/__init__.py` (empty), `.../test_names_and_routing.py`, `.../test_postgres.py`

**Interfaces:**
- Produces, in `aisc_backend.projectdb`:
  - `class NotAPid(ValueError)`, `class NoSuchProjectDatabase(Exception)`, `class MigrationFailed(Exception)`
  - `normalise(pid) -> str` (lowercase, validated)
  - `database_name(pid) -> str`
  - `pid_of(database: str) -> str`
  - `@dataclass(frozen=True) class Admission(pid: str, alias: str, role: str | None, admin: bool, may_write: bool, token: str | None = None, evaluation: str | None = None)`
  - `entered(admission: Admission)`, a context manager
  - `current() -> Admission | None`
  - `active_alias() -> str | None`
  - `open_database(pid) -> str`: the alias. `"default"` when project databases are off.
  - `class ProjectRouter`
- Produces, in settings: `PROJECT_DATABASES: bool` (env `PROJECT_DATABASES`, and only with a Postgres `DB_ENGINE`), `PROJECT_DATABASE: dict | None`, `DATABASE_ROUTERS`.
- Produces: `apps/backend/scripts/test-project-databases.sh`. It makes four throwaway project databases: the first three with the whole template, the fourth with `0001_controls.sql` only. It runs `aisc_backend.tests.project_database.test_postgres` against them with `ENGINE_TEST_PIDS`, then drops them.

- [ ] **Step 1: Write the failing unit tests.** Create `aisc_backend/tests/project_database/__init__.py` (empty) and `aisc_backend/tests/project_database/test_names_and_routing.py`:

```python
"""The project database: its name, and where queries go.

The name rule is the platform's (platform/platform_service/projectdb.py), and
the same example is asserted there: two services, one rule. The router sends
every query to the database admitted for the current request, and to none when
nothing was admitted.
"""
from django.db import connections
from django.test import SimpleTestCase, override_settings

from aisc_backend import projectdb
from aisc_backend.models.project import Project

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
POSTGRES = {
    "ENGINE": "django.db.backends.postgresql",
    "USER": "engine_rw", "PASSWORD": "engine_rw", "HOST": "postgres", "PORT": "5432",
    "OPTIONS": {"options": "-c search_path=engine"}, "CONN_MAX_AGE": 0,
}


def admitted(alias):
    return projectdb.Admission(pid=PID, alias=alias, role="viewer", admin=False, may_write=False)


class TheNameTestCase(SimpleTestCase):
    def test_is_named_after_the_pid_as_the_platform_names_it(self):
        self.assertEqual("project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b", projectdb.database_name(PID))
        self.assertEqual("project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b", projectdb.database_name(PID.upper()))

    def test_anything_but_a_pid_is_refused_before_anything_is_built(self):
        for bad in ["", "abc", "../platform", PID + "x", "x'; drop database platform; --",
                    "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"]:
            with self.subTest(bad=bad), self.assertRaises(projectdb.NotAPid):
                projectdb.database_name(bad)

    def test_a_database_name_goes_back_to_its_pid(self):
        self.assertEqual(PID, projectdb.pid_of("project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"))
        for bad in ["platform", "project_x", "project_" + "g" * 32]:
            with self.subTest(bad=bad), self.assertRaises(projectdb.NotAPid):
                projectdb.pid_of(bad)


class RoutingTestCase(SimpleTestCase):
    def test_queries_go_to_the_database_admitted_for_this_request(self):
        router = projectdb.ProjectRouter()
        self.assertIsNone(router.db_for_read(Project))
        with projectdb.entered(admitted("project_x")):
            self.assertEqual("project_x", router.db_for_read(Project))
            self.assertEqual("project_x", router.db_for_write(Project))
            self.assertEqual("project_x", projectdb.current().alias)
        self.assertIsNone(router.db_for_read(Project))
        self.assertIsNone(projectdb.current())

    def test_rows_of_two_databases_are_never_related(self):
        a, b = Project(), Project()
        a._state.db, b._state.db = "project_a", "project_b"
        self.assertFalse(projectdb.ProjectRouter().allow_relation(a, b))

    def test_with_project_databases_off_everything_is_the_default_database(self):
        self.assertEqual("default", projectdb.open_database(PID))
        with self.assertRaises(projectdb.NotAPid):
            projectdb.open_database("../platform")


class RegisteringAnAliasTestCase(SimpleTestCase):
    @override_settings(PROJECT_DATABASE=POSTGRES)
    def test_the_alias_is_the_template_with_this_projects_database(self):
        alias = projectdb.database_name(PID)
        before = connections.settings
        try:
            projectdb._register(alias)
            got = connections.settings[alias]
            self.assertEqual(alias, got["NAME"])
            self.assertEqual("engine_rw", got["USER"])
            self.assertIn("ATOMIC_REQUESTS", got)
            self.assertIn("TEST", got)
            # Copied, not changed in place: a thread already walking the
            # aliases (Django closes them at the end of every request) keeps
            # the dict it started with.
            self.assertIsNot(before, connections.settings)
            self.assertNotIn(alias, before)
            self.assertEqual(before["default"], connections.settings["default"])
        finally:
            projectdb._forget(alias)
        self.assertNotIn(alias, connections.settings)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `bm test aisc_backend.tests.project_database.test_names_and_routing`
Expected: `ImportError: cannot import name 'projectdb' from 'aisc_backend'`, then `FAILED (errors=1)`.

- [ ] **Step 3: Write the Postgres tests and their runner.** Create `aisc_backend/tests/project_database/test_postgres.py`:

```python
"""A project's engine data lives in that project's database, on the real Postgres.

Run by apps/backend/scripts/test-project-databases.sh. That script makes
throwaway project databases the way the platform makes them and passes their
pids in ENGINE_TEST_PIDS. Skipped everywhere else.
"""
import os
import threading
import unittest
import uuid
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connections

from aisc_backend import projectdb
from aisc_backend.models import Metric
from aisc_backend.models.project import Project, ProjectStatus

PIDS = [p for p in os.environ.get("ENGINE_TEST_PIDS", "").split(",") if p]


def inside(pid, alias):
    return projectdb.entered(projectdb.Admission(pid=pid, alias=alias, role="editor", admin=False, may_write=True))


@unittest.skipUnless(len(PIDS) == 4 and settings.PROJECT_DATABASE, "run by scripts/test-project-databases.sh")
class ProjectDatabasesTestCase(unittest.TestCase):
    def test_a_project_database_is_migrated_on_first_use(self):
        alias = projectdb.open_database(PIDS[0])
        self.assertEqual(projectdb.database_name(PIDS[0]), alias)
        with connections[alias].cursor() as cursor:
            cursor.execute("select count(*) from django_migrations where app = 'aisc_backend'")
            self.assertGreater(cursor.fetchone()[0], 0)
            # Django's own users and sessions, and the metric catalogue, are
            # this project's too.
            cursor.execute("select to_regclass('auth_user') is not null,"
                           " to_regclass('django_session') is not null,"
                           " to_regclass('metric') is not null")
            self.assertEqual((True, True, True), cursor.fetchone())

    def test_two_projects_share_nothing(self):
        a = projectdb.open_database(PIDS[0])
        b = projectdb.open_database(PIDS[1])
        with inside(PIDS[0], a):
            Project.objects.create(pid=PIDS[0], name="only in a", status=ProjectStatus.Created)
            Metric.objects.create(name="accuracy", description="", type_spec="float")
        with inside(PIDS[1], b):
            self.assertEqual(0, Project.objects.filter(name="only in a").count())
            self.assertEqual(0, Metric.objects.count())

    def test_outside_a_project_there_is_no_database(self):
        with self.assertRaises(ImproperlyConfigured):
            Project.objects.count()

    def test_first_use_migrates_once_however_many_arrive(self):
        pid, results, errors = PIDS[2], [], []

        def open_it():
            try:
                results.append(projectdb.open_database(pid))
            except Exception as exc:  # collected and asserted below
                errors.append(exc)
            finally:
                connections.close_all()

        with mock.patch.object(projectdb, "_migrate", wraps=projectdb._migrate) as migrate:
            threads = [threading.Thread(target=open_it) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual([], errors)
        self.assertEqual(1, migrate.call_count)
        self.assertEqual({projectdb.database_name(pid)}, set(results))

    def test_a_pid_with_no_database_is_no_project(self):
        pid = str(uuid.uuid4())
        with self.assertRaises(projectdb.NoSuchProjectDatabase):
            projectdb.open_database(pid)
        self.assertNotIn(projectdb.database_name(pid), connections.settings)

    def test_a_database_the_engine_was_not_given_is_no_project(self):
        with self.assertRaises(projectdb.NoSuchProjectDatabase):
            projectdb.open_database(PIDS[3])
```

Create `apps/backend/scripts/test-project-databases.sh` (and `chmod +x` it):

```bash
#!/usr/bin/env bash
# The engine's Postgres tests, against throwaway project databases.
#
#   apps/backend/scripts/test-project-databases.sh [test label]
#
# Makes four databases the way the platform makes them: the first three get the
# whole platform/project-template/, the fourth only 0001_controls.sql, so it is
# a project database the engine was never given. The tests run in a throwaway
# container from the current aisc-backend image with the working tree mounted,
# on the stack's network. Afterwards it drops the four databases it made, and
# nothing else.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
LABEL=${1:-aisc_backend.tests.project_database.test_postgres}
su_sql() {  # su_sql <database>: runs stdin as the superuser, inside the postgres container
  docker exec -i postgres sh -c "psql -U \"\$POSTGRES_USER\" -d $1 -v ON_ERROR_STOP=1 -q"
}
PIDS=(); MADE=()
cleanup() { for db in "${MADE[@]}"; do echo "drop database if exists $db with (force)" | su_sql postgres; done; }
trap cleanup EXIT
for i in 1 2 3 4; do
  pid=$(python3 -c 'import uuid; print(uuid.uuid4())')
  db="project_$(printf '%s' "$pid" | tr -d -)"
  echo "create database $db" | su_sql postgres
  MADE+=("$db"); PIDS+=("$pid")
  if [ "$i" = 4 ]; then
    su_sql "$db" < "$ROOT/platform/project-template/0001_controls.sql"
  else
    for f in "$ROOT"/platform/project-template/*.sql; do su_sql "$db" < "$f"; done
  fi
done
docker run --rm --network aisc_backend -w /app \
  -v "$ROOT/apps/backend/aisc_backend:/app/aisc_backend:ro,z" \
  -v "$ROOT/apps/backend/config:/app/config:ro,z" \
  -v "$ROOT/shared:/src/shared:ro,z" \
  -e PROJECT_DATABASES=true -e DB_ENGINE=django.db.backends.postgresql \
  -e DB_HOST=postgres -e DB_PORT=5432 -e DB_USER=engine_rw -e DB_PASSWORD=engine_rw -e DB_SCHEMA=engine \
  -e ENGINE_TEST_PIDS="$(IFS=,; echo "${PIDS[*]}")" \
  --entrypoint sh aisc-backend:latest -c \
  'cp -r /src/shared /tmp/shared && uv pip install -q --no-deps /tmp/shared/plugin-manager /tmp/shared/plugin-interface && exec .venv/bin/python manage.py test "$0" -v 2' "$LABEL"
```

- [ ] **Step 4: Implement.** Create `aisc_backend/projectdb.py`:

```python
"""The database of one project.

Every project has a database of its own, made by the platform when the project
is made (platform/platform_service/projectdb.py). The engine keeps everything
it has for a project there and nowhere else: the AI system and its components,
the plugins the project uses, evaluations, observations, measurements, the
metric catalogue, and Django's own users and sessions. A query that forgets a
filter still cannot reach another project: it is connected to the wrong place
to do it.

Each project database is a Django connection alias named after the database.
It is added when first needed, and migrated the first time this process opens
it. The router below sends every query to the database admitted for the
current request. With none admitted there is none: the `default` alias is
Django's dummy backend when project databases are on, and the query fails.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.conf import settings
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, OperationalError, connections

logger = logging.getLogger(__name__)

_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_DATABASE = re.compile(r"^project_[0-9a-f]{32}$")
#: pg_advisory_lock key for migrating a project database ("engine").
_MIGRATE_LOCK = 0x656E67696E65


class NotAPid(ValueError):
    """Only a project id may name a database: anything else is refused unread."""


class NoSuchProjectDatabase(Exception):
    """There is no database for this project, or the engine was not given it."""


class MigrationFailed(Exception):
    """A project database could not be brought to this engine's schema."""


def normalise(pid) -> str:
    text = str(pid).strip().lower()
    if not _PID.match(text):
        raise NotAPid(f"not a project id: {text!r}")
    return text


def database_name(pid) -> str:
    return "project_" + normalise(pid).replace("-", "")


def pid_of(database: str) -> str:
    if not _DATABASE.match(database):
        raise NotAPid(f"not a project database: {database!r}")
    return str(uuid.UUID(database.removeprefix("project_")))


@dataclass(frozen=True)
class Admission:
    """What the door decided for this request: which project, and what the
    caller is to it."""

    pid: str
    alias: str
    role: str | None
    admin: bool
    may_write: bool
    token: str | None = field(default=None, repr=False)
    #: For the evaluation worker: the run its ticket was made for.
    evaluation: str | None = None


_active: contextvars.ContextVar[Admission | None] = contextvars.ContextVar("aisc_project", default=None)


@contextmanager
def entered(admission: Admission):
    """Work inside this project's database for the duration.

    A ContextVar rather than a thread-local: under ASGI the ORM runs in the
    threads sync_to_async hands it to, and those inherit the request's context.
    """
    token = _active.set(admission)
    try:
        yield admission
    finally:
        _active.reset(token)


def current() -> Admission | None:
    return _active.get()


def active_alias() -> str | None:
    admission = _active.get()
    return admission.alias if admission is not None and admission.alias else None


_registry_lock = threading.Lock()
_alias_locks: dict[str, threading.Lock] = {}
_migrated: set[str] = set()


def _replace_settings(updated: dict) -> None:
    # Copy-on-write: Django walks every alias at the end of each request
    # (close_old_connections), and a dict that grew under it would raise.
    connections._settings = updated
    connections.__dict__["settings"] = updated


def _register(alias: str) -> None:
    with _registry_lock:
        if alias in connections.settings:
            return
        template = {**settings.PROJECT_DATABASE, "NAME": alias}
        configured = connections.configure_settings({DEFAULT_DB_ALIAS: {}, alias: template})[alias]
        _replace_settings({**connections.settings, alias: configured})


def _forget(alias: str) -> None:
    """Drop an alias whose database is not there, so made-up pids do not pile up."""
    with _registry_lock:
        if alias in connections.settings:
            _replace_settings({k: v for k, v in connections.settings.items() if k != alias})
    try:
        del connections[alias]
    except AttributeError:
        pass


def _migrate(pid: str, alias: str) -> None:
    connection = connections[alias]
    with entered(Admission(pid=pid, alias=alias, role=None, admin=False, may_write=True)):
        with connection.cursor() as cursor:
            # Two engine processes opening the same new project wait for each
            # other here; within a process the per-alias lock already does.
            cursor.execute("SELECT pg_advisory_lock(%s)", [_MIGRATE_LOCK])
        try:
            call_command("migrate", database=alias, interactive=False, verbosity=0)
        except Exception as exc:
            raise MigrationFailed(f"{alias}: {exc}") from exc
        finally:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [_MIGRATE_LOCK])
            except Exception:
                logger.warning("could not release the migration lock on %s; it goes with the connection", alias)


def open_database(pid) -> str:
    """This project's database alias: connected, and migrated the first time.

    Not a way in. A request reaches this only through admit(), which has asked
    about this exact pid first. The one other caller is
    `manage.py migrate_projects`, which serves no request.
    """
    text = normalise(pid)
    if not settings.PROJECT_DATABASE:
        return DEFAULT_DB_ALIAS
    alias = database_name(text)
    _register(alias)
    try:
        connections[alias].ensure_connection()
    except OperationalError as exc:
        _forget(alias)
        raise NoSuchProjectDatabase(alias) from exc
    if alias not in _migrated:
        with _registry_lock:
            lock = _alias_locks.setdefault(alias, threading.Lock())
        with lock:
            if alias not in _migrated:
                _migrate(text, alias)
                _migrated.add(alias)
    return alias


class ProjectRouter:
    """Every query goes to the database admitted for this request.

    None admitted means None here, and Django then uses `default`: the sqlite
    file on a laptop and in the test runner, and with project databases on,
    nothing at all.
    """

    def db_for_read(self, model, **hints):
        return active_alias()

    def db_for_write(self, model, **hints):
        return active_alias()

    def allow_relation(self, obj1, obj2, **hints):
        return obj1._state.db == obj2._state.db

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return None
```

In `config/settings.py`, replace lines 93–121 (from `# Database` to the closing `}` of `DATABASES`) with:

```python
# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# One database per project (aisc_backend/projectdb.py). The platform makes
# `project_<pid hex>` when a project is made and gives this service a schema in
# it; DB_SCHEMA is that schema. PROJECT_DATABASE is the connection to any one of
# them, with NAME filled in per project. With project databases on there is no
# default database at all: a query made outside an admitted request has nowhere
# to go, and fails, rather than landing somewhere shared.
#
# Off (a laptop, the test runner on sqlite) everything is the one default
# database below, as it always was.
DB_SCHEMA = env("DB_SCHEMA", "")
_db_engine = env("DB_ENGINE", "django.db.backends.sqlite3")
PROJECT_DATABASES = env.bool("PROJECT_DATABASES", False) and "postgresql" in _db_engine

PROJECT_DATABASE = (
    {
        "ENGINE": _db_engine,
        "USER": env("DB_USER", ""),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", ""),
        "PORT": env("DB_PORT", ""),
        "OPTIONS": {"options": f"-c search_path={DB_SCHEMA or 'engine'}"},
        # A connection per request thread, closed when the request ends: a pool
        # per project database is what would exhaust max_connections.
        "CONN_MAX_AGE": 0,
    }
    if PROJECT_DATABASES
    else None
)

# A search path is a Postgres idea; the sqlite the test runner builds has no
# schemas and rejects the option outright.
_db_options = (
    {"options": f"-c search_path={DB_SCHEMA},core"}
    if DB_SCHEMA and "postgresql" in _db_engine
    else {}
)

DATABASES = (
    {"default": {}}
    if PROJECT_DATABASES
    else {
        'default': {
            "ENGINE": _db_engine,
            "NAME": env("DB_NAME", BASE_DIR / "db.db"),
            "USER": env("DB_USER", ""),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", ""),
            "PORT": env("DB_PORT", ""),
            "OPTIONS": _db_options,
        }
    }
)
DATABASE_ROUTERS = ["aisc_backend.projectdb.ProjectRouter"]
```

- [ ] **Step 5: Run the unit tests, then the Postgres ones.**

Run: `bm test aisc_backend.tests.project_database.test_names_and_routing`
Expected: 7 tests, `OK`.

Run: `apps/backend/scripts/test-project-databases.sh`
Expected: 6 tests, `OK`. Afterwards, `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -Atc "select count(*) from pg_database where datname like \$\$project\_%\$\$"'` prints the same count it printed before the run.

Run the baseline command from "Before you start". Expected: `OK`, as before. With nothing admitted, the router sends every query to `default`, as today.

- [ ] **Step 6: Commit** (inside `apps/backend`).

```bash
cd apps/backend
git add aisc_backend/projectdb.py config/settings.py scripts/test-project-databases.sh aisc_backend/tests/project_database
git commit -m "One database alias per project database, migrated on first use"
```

---

### Task 5: The database is the project

**Files:**
- Modify: `apps/backend/aisc_backend/models/project.py:19-46` (the `platform_project_id` field and its constraint)
- Create: `apps/backend/aisc_backend/migrations/0022_the_database_is_the_project.py`
- Modify: `apps/backend/aisc_backend/schemas/project.py:8-13`, `apps/backend/aisc_backend/repositories/project_repository.py:13-20`
- Modify: `apps/backend/aisc_backend/platform_projects.py` (whole file), `apps/backend/aisc_backend/auth/keycloak.py` (after line 61), `apps/backend/config/settings.py` (end of file)
- Modify: `apps/backend/aisc_backend/routers/project.py:14,58-140`, `apps/backend/aisc_backend/routers/evaluation.py:72`
- Modify: `apps/backend/aisc_backend/models/evaluation.py:28-31` (the comment on `system_id`)
- Modify: `apps/backend/aisc_backend/auth/membership.py:112,133,251`
- Test: rewrite `apps/backend/aisc_backend/tests/test_platform_links.py`. Modify `tests/routers/test_project_membership.py` (lines 43–46, 191–193, 266–268; drop the unlinked-project test) and `tests/routers/test_project_router.py:48-58`. Extend `tests/project_database/test_postgres.py`.

**Interfaces:**
- Consumes: `project.system (pid uuid PRIMARY KEY)` (Plan 2, granted in Task 1). The platform's `GET /projects/{pid}` → `{"pid", "name", "slug", …}`, which needs a member's token.
- Produces:
  - `Project` has no `platform_project_id`, and its `pid` is unique (`project_pid_unique`). The engine's row carries the platform project's pid as its own.
  - Migration `0022_the_database_is_the_project`. On Postgres it creates `evaluation_system_id_fkey`: `evaluation.system_id` → `project.system(pid)` `ON DELETE SET NULL`.
  - `ProjectRepository.create(name: str, pid=None) -> Project`
  - `platform_project_name(platform_project_id, token: str | None) -> str | None`, over HTTP to `settings.PLATFORM_URL`. There is no SQL left in the file.
  - `keycloak.bearer_of(request) -> str`
  - `POST /api/v1/projects` is gone. `GET /api/v1/projects` takes no query and lists this database's row. `POST /api/v1/projects/for-platform/{pid}` makes or finds the row with that pid.

`Model.public` and its cross-project sharing are already gone. The AISystem merge (`apps/backend` e34fca3, migration `0020_ai_system_and_project_config.py`) folded `Model` into `AIComponent`, which has no `public` field, and every component reaches a project through `AIComponent.system` → `AISystem.project`. Step 1 pins that, so it cannot come back.

- [ ] **Step 1: Write the failing tests.** Replace `aisc_backend/tests/test_platform_links.py` with:

```python
"""The database is the project.

Each project has a database of its own (aisc_backend/projectdb.py). The engine's
`project` row is what its tables hang off: it carries the platform project's pid
as its own, and it names no other project, because there is no other one in
the database to name. Nothing in the engine is shared with another project.

An evaluation names the system it ran against, which is this project's own
`project.system` in the same database. That key exists on Postgres only, and is
checked in tests/project_database/test_postgres.py.
"""
import uuid
import unittest.mock as mock

from django.apps import apps
from django.test import TestCase, override_settings
from ninja.testing import TestAsyncClient

from aisc_backend.auth import keycloak
from aisc_backend.models import AIComponent, AISystem, Evaluation, Project
from aisc_backend.platform_projects import platform_project_name
from aisc_backend.repositories.project_repository import ProjectRepository
from aisc_backend.routers.project import router

project_repository = ProjectRepository()

#: These tests are about the routes, not about Keycloak. The container they run
#: in has AUTH_ENABLED=true; pinned off here so they behave the same anywhere.
_auth_off = None


def setUpModule():
    global _auth_off
    _auth_off = mock.patch.object(keycloak, "AUTH_ENABLED", False)
    _auth_off.start()


def tearDownModule():
    _auth_off.stop()


SIGNED_IN = {"Authorization": "Bearer development"}


class NothingIsSharedBetweenProjectsTestCase(TestCase):
    def test_no_row_names_another_project_or_is_shared_with_one(self):
        for model in apps.get_app_config("aisc_backend").get_models():
            names = {f.name for f in model._meta.get_fields()}
            with self.subTest(model=model.__name__):
                self.assertNotIn("public", names)
                self.assertNotIn("platform_project_id", names)

    def test_every_part_of_the_ai_system_belongs_to_the_project(self):
        self.assertFalse(AISystem._meta.get_field("project").null)
        self.assertFalse(AIComponent._meta.get_field("system").null)

    async def test_an_evaluation_names_the_system_it_ran_against(self):
        project = await project_repository.create("tested", uuid.uuid4())
        system = uuid.uuid4()
        evaluation = await Evaluation.objects.acreate(status="Pending", project=project, system_id=system)
        again = await Evaluation.objects.aget(id=evaluation.id)
        self.assertEqual(system, again.system_id)

    async def test_an_evaluation_without_a_system_is_allowed_but_says_nothing(self):
        project = await project_repository.create("tested", uuid.uuid4())
        evaluation = await Evaluation.objects.acreate(status="Pending", project=project)
        again = await Evaluation.objects.aget(id=evaluation.id)
        self.assertIsNone(again.system_id)


class TheEngineInheritsTheProjectTestCase(TestCase):
    """Opening the engine inside a project makes this database's row the first
    time, with the platform's pid and name, and finds it every time after."""

    async def _resolve(self, pid, name="MCAS"):
        with mock.patch("aisc_backend.routers.project.platform_project_name", return_value=name) as named:
            response = await TestAsyncClient(router).post(f"/for-platform/{pid}", headers=SIGNED_IN)
        self.assertEqual(200, response.status_code, response.content)
        return response.data, named

    async def test_the_first_visit_makes_it_with_the_platforms_pid_and_name(self):
        pid = uuid.uuid4()
        resolved, named = await self._resolve(pid)
        self.assertEqual(str(pid), str(resolved["pid"]))
        self.assertEqual("MCAS", resolved["name"])
        named.assert_called_once_with(pid, "development")

    async def test_every_visit_after_that_finds_the_same_one(self):
        pid = uuid.uuid4()
        first, _ = await self._resolve(pid)
        again, named = await self._resolve(pid)
        self.assertEqual(first["pid"], again["pid"])
        named.assert_not_called()
        self.assertEqual(1, await Project.objects.filter(pid=pid).acount())

    async def test_without_a_name_from_the_platform_it_is_still_made(self):
        pid = uuid.uuid4()
        resolved, _ = await self._resolve(pid, name=None)
        self.assertEqual(f"project-{str(pid)[:8]}", resolved["name"])

    async def test_the_list_is_this_databases_row(self):
        pid = uuid.uuid4()
        await self._resolve(pid)
        response = await TestAsyncClient(router).get("", headers=SIGNED_IN)
        self.assertEqual([str(pid)], [str(p["pid"]) for p in response.data])

    async def test_there_is_no_second_project_to_create(self):
        response = await TestAsyncClient(router).post("", json={"name": "another"}, headers=SIGNED_IN)
        self.assertEqual(405, response.status_code)


class AskingThePlatformForTheNameTestCase(TestCase):
    @override_settings(PLATFORM_URL="http://platform:8000/")
    def test_the_name_comes_from_the_platform_with_the_callers_token(self):
        with mock.patch("aisc_backend.platform_projects.httpx.get") as get:
            get.return_value = mock.Mock(status_code=200, json=mock.Mock(return_value={"name": "MCAS"}))
            self.assertEqual("MCAS", platform_project_name("p-1", "tok"))
        get.assert_called_once_with(
            "http://platform:8000/projects/p-1", headers={"Authorization": "Bearer tok"}, timeout=5.0
        )

    @override_settings(PLATFORM_URL="http://platform:8000")
    def test_no_token_or_no_answer_is_no_name(self):
        with mock.patch("aisc_backend.platform_projects.httpx.get") as get:
            self.assertIsNone(platform_project_name("p-1", None))
            get.assert_not_called()
            get.return_value = mock.Mock(status_code=404)
            self.assertIsNone(platform_project_name("p-1", "tok"))
```

`ninja.testing` answers 405 for a method the path doesn't serve. If it answers 404 instead, assert `assertIn(response.status_code, (404, 405))`. What matters is that nothing is created.

In `tests/project_database/test_postgres.py`, add these imports: `from django.db import IntegrityError, transaction` and `from aisc_backend.models import Evaluation`. Add this test to `ProjectDatabasesTestCase`:

```python
    def test_an_evaluation_names_a_system_of_this_project_only(self):
        alias = projectdb.open_database(PIDS[0])
        with connections[alias].cursor() as cursor:
            cursor.execute("select confrelid::regclass::text from pg_constraint"
                           " where conname = 'evaluation_system_id_fkey'")
            self.assertEqual(("project.system",), cursor.fetchone())
        with inside(PIDS[0], alias):
            project, _ = Project.objects.get_or_create(
                pid=PIDS[0], defaults={"name": "a", "status": ProjectStatus.Created})
            with self.assertRaises(IntegrityError), transaction.atomic(using=alias):
                Evaluation.objects.create(project=project, status="Pending", system_id=uuid.uuid4())
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `bm test aisc_backend.tests.test_platform_links`
Expected: FAILED. `test_no_row_names_another_project…` fails on `Project` (`'platform_project_id' unexpectedly found`). `AskingThePlatform…` fails with `TypeError: platform_project_name() takes 1 positional argument but 2 were given`. `test_there_is_no_second_project_to_create` gets 200.

- [ ] **Step 3: The model and its migration.** In `models/project.py`, replace lines 19–46 (from `class Project(Base):` through the closing `]` of `constraints`) with:

```python
class Project(Base):
    """This project, in its own database.

    The database is the project: the platform made it for this project and it
    holds nothing of any other. This row is what the engine's own tables hang
    off, and it carries the platform project's pid as its own, so a pid on the
    launcher and a pid here are the same thing.
    """
    status = models.CharField(max_length=255, choices=ProjectStatus.choices)

    class Meta:
        db_table = "project"
        constraints = [
            models.UniqueConstraint(fields=("pid",), name="project_pid_unique"),
        ]
```

Create `migrations/0022_the_database_is_the_project.py`:

```python
# The database is the project (aisc_backend/projectdb.py): each project has a
# database of its own, and this migration runs in each of them.
#
# The project row no longer names a platform project: there is one, and it is
# this database's, with its pid. The system an evaluation ran against is this
# project's own `project.system` (platform/project-template/0002_system.sql), in
# this same database, so the key to it is real. It is made on Postgres only;
# the sqlite test database has no `project` schema.

from django.db import migrations, models

LINK_TO_THE_SYSTEM = """
ALTER TABLE evaluation DROP CONSTRAINT IF EXISTS aisc_backend_evaluation_system_id_fkey;
ALTER TABLE evaluation
    ADD CONSTRAINT evaluation_system_id_fkey
    FOREIGN KEY (system_id) REFERENCES project.system (pid)
    ON DELETE SET NULL;
"""

UNLINK = "ALTER TABLE evaluation DROP CONSTRAINT IF EXISTS evaluation_system_id_fkey;"


def link(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LINK_TO_THE_SYSTEM)


def unlink(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNLINK)


class Migration(migrations.Migration):

    dependencies = [
        ("aisc_backend", "0021_ai_system_tables_lose_the_prefix"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="project", name="one_project_per_platform_project"),
        migrations.RemoveField(model_name="project", name="platform_project_id"),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(fields=("pid",), name="project_pid_unique"),
        ),
        migrations.RunPython(link, unlink),
    ]
```

In `models/evaluation.py:28-31`, the comment above `system_id` becomes:

```python
    # The system this evaluation ran against: this project's own system
    # (project.system.pid, in this same database; the key is made in migration
    # 0022 on Postgres). It belongs here rather than on a component, because
    # what is run, and what is reported on, is an evaluation. Null when no
    # system was named.
```

In `schemas/project.py:8-13`, the `ProjectInSchema.Meta` becomes `fields = ["name"]` (plus `fields_optional = "__all__"`), and the comment about the platform project goes. In `repositories/project_repository.py:13-20`, `create` becomes:

```python
    async def create(self, name: str, pid=None) -> Project:
        project = Project(name=name, status=ProjectStatus.Created)
        if pid is not None:
            project.pid = pid
        await project.asave()
        return project
```

- [ ] **Step 4: The name comes from the platform.** Replace `platform_projects.py` with:

```python
"""What the engine asks the platform about a project: its name.

The engine is connected to the project's own database and nothing else, so the
platform's tables are not there to read. The name comes the way every module
gets it: from the platform's API, with the caller's own token.
"""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def platform_project_name(platform_project_id, token: str | None) -> str | None:
    """The platform's name for this project, or None when it cannot be had."""
    base = (getattr(settings, "PLATFORM_URL", "") or "").rstrip("/")
    if not base or not token:
        return None
    try:
        response = httpx.get(
            f"{base}/projects/{platform_project_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("platform unreachable for a project's name: %s", exc)
        return None
    if response.status_code != 200:
        return None
    name = response.json().get("name")
    return name if isinstance(name, str) and name else None
```

At the end of `config/settings.py`, add:

```python

# The platform: who may be in which project, and the project's name. Asked with
# the caller's own token (aisc_backend/projectdb.py, platform_projects.py).
PLATFORM_URL = env("PLATFORM_URL", "")
```

In `auth/keycloak.py`, after `GATEWAY_TOKEN_HEADER = …` (line 61), add:

```python


def bearer_of(request) -> str:
    """The caller's token: from Authorization, or from the gateway's header."""
    header = request.headers.get("Authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return request.headers.get(GATEWAY_TOKEN_HEADER, "").strip()
```

- [ ] **Step 5: The routes.** In `routers/project.py`:
- Change the import at line 14 to `from aisc_backend.platform_projects import platform_project_name`, and add `from aisc_backend.auth.keycloak import KeycloakAuth, bearer_of` (replacing the `KeycloakAuth` import).
- Add `Project` to the `from aisc_backend.models import (…)` list, and `from aisc_backend.models.project import ProjectStatus`.
- Replace lines 58–140, from `@router.post("", response=ProjectOutSchema)` through the end of `get_project_details`, with:

```python
@router.patch("/{pid}", response=ProjectOutSchema)
async def update_project(request, pid: uuid.UUID, data: ProjectInSchema):
    await sync_to_async(membership.for_project_pid)(request, pid, "editor")
    project = await project_repository.get(pid)
    updated = await project_repository.patch(project, data)
    # AUDIT: who renamed which project, and to what
    await sync_to_async(log_action)(
        request, action="update", resource_type="project",
        resource_id=str(pid), metadata={"name": data.name})
    return updated


@router.post("/for-platform/{platform_project_id}", response=ProjectOutSchema)
async def project_for_platform(request, platform_project_id: uuid.UUID):
    """This project's row, made the first time the engine is opened on it.

    The database is the project: the platform made it for this project and it
    holds nothing of any other. The row carries the platform project's pid as
    its own, and the platform's name. Entering the engine inside a project is
    work on it, so it takes an editor.
    """
    await sync_to_async(membership.require)(request, platform_project_id, "editor")
    existing = await Project.objects.filter(pid=platform_project_id).afirst()
    if existing is not None:
        return existing
    name = await sync_to_async(platform_project_name)(platform_project_id, bearer_of(request))
    project, created = await Project.objects.aget_or_create(
        pid=platform_project_id,
        defaults={
            "name": name or f"project-{str(platform_project_id)[:8]}",
            "description": "",
            "status": ProjectStatus.Created,
        },
    )
    if created:
        await sync_to_async(log_action)(
            request, action="create", resource_type="project",
            resource_id=str(project.pid), metadata={"name": project.name})
    return project


@router.get("", response=list[ProjectOutSchema])
async def get_projects(request):
    """This database's project, as a list of one: none before the first visit."""
    found = await project_repository.get_all()
    return await sync_to_async(membership.visible)(request, found)


@router.get("/by-name/{name}", response=ProjectOutSchema)
async def get_project_by_name(request, name):
    return await project_repository.get_one(name=name)


@router.get("/{pid}", response=ProjectDetailsOutSchema)
async def get_project_details(request, pid: uuid.UUID):
    await sync_to_async(membership.for_project_pid)(request, pid)
    return await project_repository.get(pid, True)
```

`aget_or_create` covers two first visits at once. The unique `pid` makes the second insert fail, and Django then fetches the row the first one made.

In `routers/evaluation.py:72`, change `project.platform_project_id` to `project.pid`. In `auth/membership.py`, change `p.platform_project_id` (line 112), `project.platform_project_id` (line 133) and `project.platform_project_id` (line 251) to `.pid`. Membership still reads the platform's table here; Task 6 replaces that. Until then the engine pid *is* the platform pid, so the lookup is the same.

- [ ] **Step 6: The tests that named the link.**
  - `tests/routers/test_project_membership.py`: in the three `setUpTestData` (lines 43–46, 191–193, 266–268), `Project.objects.create(name=…, status=ProjectStatus.Created, platform_project_id=PLATFORM_PROJECT)` becomes `Project.objects.create(pid=PLATFORM_PROJECT, name=…, status=ProjectStatus.Created)`. Delete the `cls.unlinked = …` line and `test_a_project_with_no_platform_link_is_for_admins_only`: a project without a platform link no longer exists. In the two listing tests, drop the `?platform_project_id=…` query from `client.get(…)`.
  - `tests/routers/test_project_router.py:48-58`: delete `test_create_project`, and drop the `ProjectInSchema` import if nothing else uses it.

- [ ] **Step 7: Run everything.**

Run: `bm makemigrations --check --dry-run aisc_backend`
Expected: `No changes detected in app 'aisc_backend'`.

Run: the baseline command from "Before you start", plus `aisc_backend.tests.project_database.test_names_and_routing`.
Expected: `OK`.

Run: `apps/backend/scripts/test-project-databases.sh`
Expected: 7 tests, `OK`.

Run: `grep -rn "platform_project_id\|core\.\(project\|system\)" apps/backend/aisc_backend --include=*.py | grep -v "/migrations/\|/tests/"`
Expected: only three files. `routers/project.py` and `platform_projects.py` name a parameter `platform_project_id`, and `auth/membership.py` still has its docstring and the `role_in_project` SQL. Task 6 removes the membership ones.

- [ ] **Step 8: Commit** (inside `apps/backend`).

```bash
cd apps/backend
git add aisc_backend/models/project.py aisc_backend/models/evaluation.py aisc_backend/migrations/0022_the_database_is_the_project.py aisc_backend/schemas/project.py aisc_backend/repositories/project_repository.py aisc_backend/platform_projects.py aisc_backend/auth/keycloak.py aisc_backend/auth/membership.py aisc_backend/routers/project.py aisc_backend/routers/evaluation.py config/settings.py aisc_backend/tests
git commit -m "The database is the project: the row carries its pid, and an evaluation's system is this project's"
```

---

### Task 6: The door: this pid, checked with the platform, before its database is opened

**Files:**
- Modify: `apps/backend/aisc_backend/projectdb.py` (append)
- Create: `apps/backend/aisc_backend/project_door.py`
- Modify: `apps/backend/config/settings.py` (`MIDDLEWARE`, lines 57–71; add `CORS_ALLOW_HEADERS` after line 180)
- Modify: `apps/backend/aisc_backend/auth/membership.py` (whole file)
- Modify: `apps/backend/aisc_backend/routers/project.py` (the `membership.require` in `project_for_platform`)
- Modify: `apps/backend/aisc_backend/routers/evaluation.py:69-72,130`
- Modify: `apps/backend/aisc_backend/routers/plugin.py:174-177,239-243,281-290`
- Modify: `apps/backend/aisc_backend/services/celery_service.py:18-20`
- Test: create `apps/backend/aisc_backend/tests/project_database/test_door.py`. Modify `tests/test_every_project_route_is_guarded.py` (two tests) and `tests/routers/test_project_membership.py` (delete `MembershipQueryTestCase`).

**Interfaces:**
- Consumes: the platform's `GET {PLATFORM_URL}/authz/projects/{pid}` with `Authorization: Bearer <caller token>` → `{"role": str | None, "admin": bool, "may_write": bool}`. It answers 401 for a token it doesn't accept (`platform/platform_service/app.py:158`).
- Produces, in `aisc_backend.projectdb`:
  - `PROJECT_HEADER = "X-AISC-Project"`, `RUN_HEADER = "X-AISC-Run"`
  - `READ_POSTS: re.Pattern`, `writes(method: str, path: str) -> bool`
  - `class Refused(Exception)` with `.status: int` and `.detail: str`
  - `async fetch_access(pid: str, token: str) -> dict | None`
  - `async admit(request) -> Admission`
  - `run_ticket(pid, evaluation_pid) -> str`
  - `verify_run_ticket(pid, ticket: str) -> str` (returns the evaluation pid; raises `Refused(403)`)
- Produces, in `aisc_backend.project_door`: `NO_PROJECT`, `NO_PROJECT_FOR`, `needs_a_project(method: str, path: str) -> bool` and `ProjectDatabaseMiddleware`.
- Produces, in `aisc_backend.auth.membership`:
  - `role_in_project() -> str | None`
  - `role_for(request) -> str | None`
  - `require(request, needed="viewer")`
  - `same_project(project_pid) -> None`
  - `remember(claims) -> None`
  - The existing `for_project_pid`, `for_evaluation`, `for_component`, `for_plugin`, `for_project_config`, `for_stored_file`, `for_task`, `visible` and `visible_by` keep their names and arguments. `require` loses its pid argument.
- Produces, in `aisc_backend.services.celery_service`: `async run_evaluation(project_pid, evaluation_uuid)`. It sends `args=[evaluation_uuid]`, `kwargs={"project_pid", "ticket"}`, which is what Task 3's worker expects.

The worker has no Keycloak identity, so it cannot be asked about on the platform. Its calls are admitted on a run ticket instead. The ticket is an HMAC of (pid, evaluation), minted only by `run_evaluation`, which runs only after the platform said, for that exact pid, that the person starting the run is an editor. `admit()` checks the ticket against the header's pid and against the evaluation in the path before it opens anything.

- [ ] **Step 1: Write the failing tests.** Create `aisc_backend/tests/project_database/test_door.py`:

```python
"""The door: nothing reaches a project's database without being admitted for THAT project.

These run the whole stack, Django's middleware and then ninja, on the sqlite
test database. The platform is a stub, and opening the database is watched, so
each refusal can be shown to happen before any database is opened, and to
leave every table as it was.
"""
import datetime
import os
import re
import uuid
import unittest.mock as mock

import jwt
from asgiref.sync import sync_to_async
from cryptography.hazmat.primitives.asymmetric import rsa
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import AsyncClient, TestCase

from aisc_backend import project_door, projectdb
from aisc_backend.auth import keycloak
from aisc_backend.models.project import Project, ProjectStatus
from aisc_backend.services import celery_service
from aisc_backend.tests.test_every_project_route_is_guarded import operations_of
from config.urls import api

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
ANY_ID = "00000000-0000-4000-8000-000000000000"
ISSUER = "http://keycloak:8080/realms/aisc"
SECRET = "internal-test-secret"

STRANGER = {"role": None, "admin": False, "may_write": False}
VIEWER = {"role": "viewer", "admin": False, "may_write": False}
EDITOR = {"role": "editor", "admin": False, "may_write": True}
ADMIN = {"role": "owner", "admin": True, "may_write": True}


def filled(path):
    return re.sub(r"\{[^}]+\}", ANY_ID, path)


def routes(internal):
    """Every route that changes something, on the public API or the worker's."""
    found = []
    for method, path, _ in operations_of(api):
        if method == "GET" or path.startswith("/api/v1/internal") != internal:
            continue
        if project_door.needs_a_project(method, path):
            found.append((method, path))
    return found


def rows():
    counts = {m.__name__: m.objects.count() for m in apps.get_app_config("aisc_backend").get_models()}
    counts["User"] = get_user_model().objects.count()
    return counts


class _Door(TestCase):
    def setUp(self):
        self.client = AsyncClient()
        patchers = [mock.patch.object(keycloak, "AUTH_ENABLED", True),
                    mock.patch.dict(os.environ, {"INTERNAL_API_KEY": SECRET})]
        self.platform = mock.AsyncMock(return_value=STRANGER)
        patchers.append(mock.patch.object(projectdb, "fetch_access", self.platform))
        self.opened = mock.Mock(wraps=projectdb.open_database)
        patchers.append(mock.patch.object(projectdb, "open_database", self.opened))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def call(self, method, path, project=A, token="some-token", headers=None, body=None):
        sent = dict(headers or {})
        if project is not None:
            sent[projectdb.PROJECT_HEADER] = project
        if token:
            sent["Authorization"] = f"Bearer {token}"
        if method == "GET":
            return await self.client.get(path, headers=sent)
        return await getattr(self.client, method.lower())(
            path, data=body or {}, content_type="application/json", headers=sent)


class TheDoorTestCase(_Door):
    async def test_a_call_that_names_no_project_is_asked_which(self):
        response = await self.call("GET", "/api/v1/projects", project=None)
        self.assertEqual(400, response.status_code)
        self.platform.assert_not_called()
        self.opened.assert_not_called()

    async def test_a_project_that_is_not_a_pid_is_not_found_and_nothing_is_built(self):
        for bad in ["abc", "../platform", A + "x", "project_x; drop database platform"]:
            with self.subTest(bad=bad):
                self.assertEqual(404, (await self.call("GET", "/api/v1/projects", project=bad)).status_code)
        self.platform.assert_not_called()
        self.opened.assert_not_called()

    async def test_the_platform_is_asked_about_this_pid_with_this_callers_token(self):
        self.platform.return_value = VIEWER
        await self.call("GET", "/api/v1/projects", project=A.upper(), token="tok-1")
        self.platform.assert_awaited_once_with(A, "tok-1")
        self.opened.assert_called_once_with(A)

    async def test_a_stranger_is_told_there_is_no_such_project(self):
        self.assertEqual(404, (await self.call("GET", "/api/v1/projects")).status_code)
        self.opened.assert_not_called()

    async def test_no_token_is_asked_to_sign_in(self):
        self.assertEqual(401, (await self.call("GET", "/api/v1/projects", token=None)).status_code)
        self.platform.assert_not_called()
        self.opened.assert_not_called()

    async def test_the_platform_not_answering_opens_nothing(self):
        self.platform.side_effect = projectdb.Refused(503, "the platform is not answering")
        self.assertEqual(503, (await self.call("GET", "/api/v1/projects")).status_code)
        self.opened.assert_not_called()

    async def test_routes_of_no_project_pass_without_one(self):
        response = await self.call("GET", "/api/v1/app/app-name", project=None)
        self.assertEqual(200, response.status_code)
        self.platform.assert_not_called()


class EveryWriteIsRefusedToWhoMayNotMakeItTestCase(_Door):
    @classmethod
    def setUpTestData(cls):
        Project.objects.create(pid=A, name="A", status=ProjectStatus.Created)

    def test_the_writes_are_the_api_s(self):
        self.assertGreater(len(routes(internal=False)), 15)
        self.assertGreater(len(routes(internal=True)), 4)

    async def test_a_stranger_is_refused_every_write_and_nothing_is_written(self):
        before = await sync_to_async(rows)()
        for method, path in routes(internal=False):
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(404, (await self.call(method, filled(path))).status_code)
        self.opened.assert_not_called()
        self.assertEqual(before, await sync_to_async(rows)())

    async def test_a_viewer_is_refused_every_write_and_nothing_is_written(self):
        self.platform.return_value = VIEWER
        before = await sync_to_async(rows)()
        for method, path in routes(internal=False):
            if projectdb.READ_POSTS.match(filled(path)):
                continue
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(403, (await self.call(method, filled(path))).status_code)
        self.opened.assert_not_called()
        self.assertEqual(before, await sync_to_async(rows)())

    async def test_a_viewer_may_still_make_the_posts_that_only_read(self):
        self.platform.return_value = VIEWER
        response = await self.call("POST", f"/api/v1/evaluations/{ANY_ID}/measurements/metric-names")
        self.assertNotIn(response.status_code, (400, 403))
        self.opened.assert_called_once_with(A)


class TheWorkerIsAdmittedOnItsTicketOnlyTestCase(_Door):
    evaluation = "33333333-3333-4333-8333-333333333333"

    async def worker(self, method, path, project=A, ticket=None, secret=SECRET):
        headers = {"X-Internal-Secret": secret}
        if ticket is not None:
            headers[projectdb.RUN_HEADER] = ticket
        return await self.call(method, path, project=project, token=None, headers=headers)

    async def test_without_the_shared_secret_nothing_is_opened(self):
        ticket = projectdb.run_ticket(A, self.evaluation)
        response = await self.worker("PUT", f"/api/v1/internal/evaluations/{self.evaluation}?status=Done",
                                     ticket=ticket, secret="wrong")
        self.assertEqual(401, response.status_code)
        self.opened.assert_not_called()

    async def test_a_ticket_for_another_project_opens_nothing(self):
        ticket = projectdb.run_ticket(B, self.evaluation)
        response = await self.worker("PUT", f"/api/v1/internal/evaluations/{self.evaluation}?status=Done", ticket=ticket)
        self.assertEqual(403, response.status_code)
        self.opened.assert_not_called()

    async def test_a_ticket_for_another_evaluation_opens_nothing(self):
        ticket = projectdb.run_ticket(A, str(uuid.uuid4()))
        response = await self.worker("PUT", f"/api/v1/internal/evaluations/{self.evaluation}?status=Done", ticket=ticket)
        self.assertEqual(403, response.status_code)
        self.opened.assert_not_called()

    async def test_a_forged_ticket_opens_nothing(self):
        response = await self.worker("PUT", f"/api/v1/internal/evaluations/{self.evaluation}?status=Done",
                                     ticket=f"{self.evaluation}.{'0' * 64}")
        self.assertEqual(403, response.status_code)
        self.opened.assert_not_called()

    async def test_another_projects_settings_are_not_reachable_on_a_ticket(self):
        ticket = projectdb.run_ticket(A, self.evaluation)
        response = await self.worker("GET", f"/api/v1/internal/projects/settings/{B}", ticket=ticket)
        self.assertEqual(403, response.status_code)
        self.opened.assert_not_called()

    async def test_every_write_the_worker_makes_needs_this_projects_ticket(self):
        before = await sync_to_async(rows)()
        for method, path in routes(internal=True):
            ticket = projectdb.run_ticket(B, ANY_ID)
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(403, (await self.worker(method, filled(path), ticket=ticket)).status_code)
        self.opened.assert_not_called()
        self.assertEqual(before, await sync_to_async(rows)())

    async def test_the_right_ticket_is_let_in_and_the_platform_is_not_asked(self):
        ticket = projectdb.run_ticket(A, self.evaluation)
        await self.worker("GET", f"/api/v1/internal/evaluations/{self.evaluation}/plugins/status", ticket=ticket)
        self.opened.assert_called_once_with(A)
        self.platform.assert_not_called()


class _SignedIn(TestCase):
    """A real token, so a request that passes the door goes on through ninja."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @classmethod
    def setUpTestData(cls):
        Project.objects.create(pid=A, name="A", status=ProjectStatus.Created)
        Project.objects.create(pid=B, name="B", status=ProjectStatus.Created)

    def setUp(self):
        signing = mock.Mock(get_signing_key_from_jwt=mock.Mock(return_value=mock.Mock(key=self.key.public_key())))
        self.platform = mock.AsyncMock(return_value=EDITOR)
        for patcher in (mock.patch.object(keycloak, "AUTH_ENABLED", True),
                        mock.patch.object(keycloak, "KEYCLOAK_ISSUER", ISSUER),
                        mock.patch.object(keycloak, "_get_jwks_client", return_value=signing),
                        mock.patch.object(projectdb, "fetch_access", self.platform)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = AsyncClient()

    def token(self, roles=("primary-user",), subject="someone"):
        now = datetime.datetime.now(datetime.timezone.utc)
        return jwt.encode({"sub": subject, "iss": ISSUER, "iat": now,
                           "exp": now + datetime.timedelta(minutes=5),
                           "realm_access": {"roles": list(roles)}}, self.key, algorithm="RS256")

    async def post(self, path, body, roles=("primary-user",)):
        return await self.client.post(path, data=body, content_type="application/json", headers={
            projectdb.PROJECT_HEADER: A, "Authorization": f"Bearer {self.token(roles)}"})


class AnIdInThePathOrBodyNamesThisProjectTestCase(_SignedIn):
    """The pid that was checked is the header's. Another pid in a path or a
    body is refused, and nothing is written in either project."""

    async def test_running_tests_in_another_project_is_refused(self):
        before = await sync_to_async(rows)()
        with mock.patch.object(celery_service.celery, "send_task") as queued:
            response = await self.post("/api/v1/evaluations/task", {"project_pid": B, "plugins_to_run": []})
        self.assertEqual(404, response.status_code)
        queued.assert_not_called()
        self.assertEqual(before, await sync_to_async(rows)())

    async def test_a_setting_for_another_project_is_refused(self):
        before = await sync_to_async(rows)()
        response = await self.post(f"/api/v1/project/settings/{B}",
                                   {"category": "variables", "key": "threshold", "name": "Threshold"})
        self.assertEqual(404, response.status_code)
        self.assertEqual(before, await sync_to_async(rows)())

    async def test_installing_into_another_project_is_refused_even_for_an_admin(self):
        self.platform.return_value = ADMIN
        before = await sync_to_async(rows)()
        response = await self.post("/api/v1/plugins", {"package_name": "x", "version": "1.0", "project_uuid": B},
                                   roles=("admin",))
        self.assertEqual(404, response.status_code)
        self.assertEqual(before, await sync_to_async(rows)())

    async def test_opening_the_engine_on_another_project_is_refused(self):
        before = await sync_to_async(rows)()
        self.assertEqual(404, (await self.post(f"/api/v1/projects/for-platform/{B}", {})).status_code)
        self.assertEqual(before, await sync_to_async(rows)())


class TheProjectsOwnUsersAndTheWorkersTicketTestCase(_SignedIn):
    async def test_a_member_is_remembered_as_this_projects_django_user(self):
        self.platform.return_value = VIEWER
        subject = f"member-{uuid.uuid4()}"
        response = await self.client.get("/api/v1/projects", headers={
            projectdb.PROJECT_HEADER: A, "Authorization": f"Bearer {self.token(subject=subject)}"})
        self.assertEqual(200, response.status_code, response.content)
        self.assertTrue(await get_user_model().objects.filter(username=subject).aexists())

    async def test_running_tests_hands_the_worker_a_ticket_for_this_project_only(self):
        with mock.patch.object(celery_service.celery, "send_task") as send:
            send.return_value = mock.Mock(task_id=str(uuid.uuid4()))
            response = await self.post("/api/v1/evaluations/task", {"project_pid": A, "plugins_to_run": []})
        self.assertEqual(200, response.status_code, response.content)
        sent = send.call_args.kwargs
        self.assertEqual(A, sent["kwargs"]["project_pid"])
        evaluation = str(sent["args"][0])
        self.assertEqual(evaluation, projectdb.verify_run_ticket(A, sent["kwargs"]["ticket"]))
        with self.assertRaises(projectdb.Refused):
            projectdb.verify_run_ticket(B, sent["kwargs"]["ticket"])
```

In `tests/test_every_project_route_is_guarded.py`, add to `EveryProjectRouteIsGuardedTestCase`:

```python
    def test_the_door_stands_in_front_of_every_project_route(self):
        """Membership is asked about the project the door admitted. A project
        route the door let through without admitting one would be asking about
        nothing."""
        from aisc_backend.project_door import needs_a_project

        missed = [f"{method} {path}" for method, path, _ in operations_of(api)
                  if looks_project_scoped(path) and not needs_a_project(method, path)]
        self.assertEqual([], missed)

    def test_only_the_door_opens_a_project(self):
        """A project's database is reached through projectdb.admit(): the door
        calls it, and nothing else enters a project or opens one."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        allowed = {"projectdb.py", "project_door.py", "management/commands/migrate_projects.py"}
        offenders = []
        for path in root.rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            if relative.startswith("tests/") or relative in allowed:
                continue
            text = path.read_text()
            if "entered(" in text or "open_database(" in text:
                offenders.append(relative)
        self.assertEqual([], offenders)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `bm test aisc_backend.tests.project_database.test_door aisc_backend.tests.test_every_project_route_is_guarded`
Expected: `ImportError: cannot import name 'project_door' from 'aisc_backend'` for `test_door`. The two new guard tests error the same way.

- [ ] **Step 3: Implement the check.** Append to `aisc_backend/projectdb.py` (and add `import hashlib`, `import hmac`, `import os`, `from dataclasses import replace`, `import httpx` and `from asgiref.sync import sync_to_async` to its imports):

```python
# ── the door ──────────────────────────────────────────────────────────────────
# A request reaches a project's database only through admit(). It checks the
# pid in the X-AISC-Project header, with the platform for a person and with the
# run ticket for the evaluation worker, and only then opens that database. Any
# other pid a route meets, in its path or its body, must equal this one
# (membership.same_project), or the route answers that there is no such project.

PROJECT_HEADER = "X-AISC-Project"
RUN_HEADER = "X-AISC-Run"
INTERNAL_PREFIX = "/api/v1/internal/"
_SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
#: POSTs that only read: a query too large for a URL. A viewer may make them.
READ_POSTS = re.compile(
    r"^/api/v1/(?:evaluations/[^/]+/measurements/(?:aggregate|dimension-keys|metric-names|dimension-values/[^/]+)"
    r"|projects/[^/]+/measurements/aggregate"
    r"|plugins/[^/]+/config/state)$"
)
_RUN_EVALUATION = re.compile(r"^/api/v1/internal/evaluations/([^/?]+)")
_RUN_SETTINGS = re.compile(r"^/api/v1/internal/projects/settings/([^/?]+)")


class Refused(Exception):
    """An answer the door gives instead of opening anything."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def writes(method: str, path: str) -> bool:
    return method.upper() not in _SAFE and not READ_POSTS.match(path)


async def fetch_access(pid: str, token: str) -> dict | None:
    """What the platform says this caller is to this project; None for a
    sign-in it did not accept. It is asked on every request and never cached,
    so a membership taken away takes effect on the next call."""
    base = (settings.PLATFORM_URL or "").rstrip("/")
    if not base:
        raise Refused(503, "the platform is not configured here (PLATFORM_URL); nothing was opened")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base}/authz/projects/{pid}",
                                        headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        logger.warning("platform authz unreachable: %s", exc)
        raise Refused(503, "the platform is not answering; nothing was opened")
    if response.status_code == 401:
        return None
    if response.status_code != 200:
        raise Refused(503, f"the platform answered {response.status_code}; nothing was opened")
    return response.json()


def run_ticket(pid, evaluation_pid) -> str:
    """The worker's pass for one run: this project, this evaluation, nothing else."""
    project, evaluation = normalise(pid), normalise(evaluation_pid)
    mac = hmac.new(settings.SECRET_KEY.encode(), f"aisc-run:{project}:{evaluation}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{evaluation}.{mac}"


def verify_run_ticket(pid, ticket: str) -> str:
    evaluation, _, _ = (ticket or "").partition(".")
    try:
        expected = run_ticket(pid, evaluation)
    except NotAPid:
        raise Refused(403, "no valid run ticket for this project")
    if not hmac.compare_digest(ticket, expected):
        raise Refused(403, "no valid run ticket for this project")
    return normalise(evaluation)


async def _admit_caller(request, pid: str) -> Admission:
    from aisc_backend.auth import membership
    from aisc_backend.auth.keycloak import bearer_of

    token = bearer_of(request) or None
    if not membership.enforced():
        return Admission(pid=pid, alias="", role=None, admin=False, may_write=True, token=token)
    if not token:
        raise Refused(401, "sign in first")
    answer = await fetch_access(pid, token)
    if answer is None:
        raise Refused(401, "the platform did not accept this sign-in")
    role = answer.get("role")
    if not role:
        # Not 403: a stranger is told what a stranger may know.
        raise Refused(404, "no such project")
    may_write = bool(answer.get("may_write"))
    if writes(request.method, request.path) and not may_write:
        raise Refused(403, "this takes an editor on this project")
    return Admission(pid=pid, alias="", role=role, admin=bool(answer.get("admin")),
                     may_write=may_write, token=token)


def _admit_run(request, pid: str) -> Admission:
    expected = os.environ.get("INTERNAL_API_KEY", "")
    given = request.headers.get("X-Internal-Secret", "")
    if not expected or not hmac.compare_digest(given, expected):
        raise Refused(401, "internal callers only")
    evaluation = verify_run_ticket(pid, request.headers.get(RUN_HEADER, ""))
    named = _RUN_EVALUATION.match(request.path)
    if named and named.group(1).lower() != evaluation:
        raise Refused(403, "this run's ticket is for another evaluation")
    named = _RUN_SETTINGS.match(request.path)
    if named and named.group(1).lower() != pid:
        raise Refused(403, "this run's ticket is for another project")
    return Admission(pid=pid, alias="", role="editor", admin=False, may_write=True, evaluation=evaluation)


async def admit(request) -> Admission:
    """Check THIS pid, then open its database: the one way into a project.

    Every refusal is raised before a connection to the project's database is
    made.
    """
    raw = request.headers.get(PROJECT_HEADER, "")
    if not raw:
        raise Refused(400, f"which project? send the {PROJECT_HEADER} header")
    try:
        pid = normalise(raw)
    except NotAPid:
        raise Refused(404, "no such project")
    if request.path.startswith(INTERNAL_PREFIX):
        admission = _admit_run(request, pid)
    else:
        admission = await _admit_caller(request, pid)
    try:
        alias = await sync_to_async(open_database)(pid)
    except NoSuchProjectDatabase:
        raise Refused(404, "no such project")
    except MigrationFailed as exc:
        logger.error("project database not migrated: %s", exc)
        raise Refused(503, "this project's database could not be brought up to date")
    return replace(admission, alias=alias)
```

- [ ] **Step 4: The door itself.** Create `aisc_backend/project_door.py`:

```python
"""The door: no request reaches a project's database without being admitted.

The SPA names the project in the X-AISC-Project header on every call to the
API (apps/webapp/src/platform/projectHeader.ts), and the evaluation worker does
the same with its run ticket (apps/eval/aisc_eval/service/api_client.py). This
hands the request to projectdb.admit(), which checks that exact pid, and only
then lets it through, with that project's database behind it.

A few routes belong to no project and pass untouched: who the caller is, the
application's name, the audit trail the other modules post to, the list of
installable packages, and the API docs. None of them touches the database.
"""
from __future__ import annotations

from asgiref.sync import markcoroutinefunction
from django.http import JsonResponse

from aisc_backend import projectdb

NO_PROJECT = frozenset({
    "/api/docs", "/api/openapi.json",
    "/api/v1/app/app-name", "/api/v1/me", "/api/v1/me/admin", "/api/v1/audit",
})
NO_PROJECT_FOR = frozenset({("GET", "/api/v1/plugins")})


def needs_a_project(method: str, path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    return path not in NO_PROJECT and (method.upper(), path) not in NO_PROJECT_FOR


class ProjectDatabaseMiddleware:
    async_capable = True
    sync_capable = False

    def __init__(self, get_response):
        self.get_response = get_response
        markcoroutinefunction(self)

    async def __call__(self, request):
        if not needs_a_project(request.method, request.path):
            return await self.get_response(request)
        try:
            admission = await projectdb.admit(request)
        except projectdb.Refused as refusal:
            return JsonResponse({"detail": refusal.detail}, status=refusal.status)
        with projectdb.entered(admission):
            return await self.get_response(request)
```

In `config/settings.py`, in `MIDDLEWARE`, add `'aisc_backend.project_door.ProjectDatabaseMiddleware',` right after `'corsheaders.middleware.CorsMiddleware',` (line 58). It runs after CORS, so a refusal still carries CORS headers, and before sessions, so nothing reads a session outside a project. After `CRSF_TRUSTED_ORIGINS = …` (line 180), add:

```python
# The SPA names its project on every call (aisc_backend/project_door.py).
CORS_ALLOW_HEADERS = (*default_headers, "x-aisc-project")
```

- [ ] **Step 5: Membership reads the door's answer.** Replace `aisc_backend/auth/membership.py` with:

```python
"""A project belongs to the people in it.

A request reaches a project only through the door (project_door.py and
projectdb.admit()). The platform was asked, with the caller's own token, what
the caller is to THAT project, and only then was the project's database opened.
That answer is kept for the request, and this reads it. There is no query
against the platform's tables here: the engine is connected to the project's
own database, where they are not.

What this adds to the door is the finer rule: the role a route needs, and that
a project id met in a path or a body is the one the door checked.

Authentication says who is asking; this says what they are to this project.
"""
from __future__ import annotations

import logging

from ninja.errors import HttpError

from aisc_backend import projectdb
from aisc_backend.auth import keycloak
from aisc_backend.auth.keycloak import get_roles

logger = logging.getLogger(__name__)

#: The realm role that administers the platform. Not a membership: it is not in
#: the project, it may act on any of them.
ADMIN_ROLE = "admin"

#: least to most, as in the platform
_RANK = {"viewer": 0, "editor": 1, "owner": 2}

#: (database alias, subject) pairs that already have a Django user
_remembered: set[tuple[str, str]] = set()


def role_in_project() -> str | None:
    """What the platform told the door this caller is to this request's project."""
    admission = projectdb.current()
    return admission.role if admission else None


def claims_of(request) -> dict | None:
    """The verified claims on this request, or None when auth is off."""
    auth = getattr(request, "auth", None)
    return auth if isinstance(auth, dict) else None


def remember(claims: dict) -> None:
    """This project's Django user for the person behind the token.

    Django's users and sessions live in each project's database, like
    everything else. A person is made a user of a project the first time they
    are seen in it; the token, not the user row, is what signs them in.
    """
    admission = projectdb.current()
    subject = str(claims.get("sub") or "")[:150]
    if admission is None or not subject:
        return
    key = (admission.alias, subject)
    if key in _remembered:
        return
    from django.contrib.auth import get_user_model

    get_user_model().objects.get_or_create(
        username=subject, defaults={"email": str(claims.get("email") or "")[:254]}
    )
    _remembered.add(key)


def role_for(request) -> str | None:
    """This caller's role in this request's project, counting the admin role."""
    claims = claims_of(request)
    if claims is None:
        return None
    role = "owner" if ADMIN_ROLE in get_roles(claims) else role_in_project()
    if role is not None:
        remember(claims)
    return role


def enforced() -> bool:
    """Whether membership is checked at all: only with authentication on.
    Read off the module, so a test that flips the switch flips this too."""
    return keycloak.AUTH_ENABLED


def require(request, needed: str = "viewer") -> str | None:
    """The caller's role, or the refusal: 404 for "not yours", 403 for "not enough"."""
    if not enforced():
        return None
    role = role_for(request)
    if role is None:
        raise HttpError(404, "no such project")
    if _RANK.get(role, -1) < _RANK[needed]:
        raise HttpError(403, f"this takes {needed} on this project")
    return role


def visible(request, rows):
    """All of them, or none: everything in this database is this project's."""
    if not enforced():
        return list(rows)
    return list(rows) if role_for(request) is not None else []


def visible_by(request, rows, project_of=None):
    return visible(request, rows)


def same_project(project_pid) -> None:
    """A project id in a path or a body is the one the door checked, or it
    names nothing. Without this a route could be sent another project's pid
    while the door had checked this one's."""
    admission = projectdb.current()
    if admission is not None and str(project_pid).lower() != admission.pid:
        raise HttpError(404, "no such project")


def _exists_or_404(queryset) -> None:
    if enforced() and not queryset.exists():
        raise HttpError(404, "no such thing")


# ── a route addressed by a row's own id ──────────────────────────────────────
# The row can only be in this database, which is this project. What is left to
# ask is whether it exists, and whether the caller's role is enough.


def for_project_pid(request, project_pid, needed: str = "viewer") -> str | None:
    same_project(project_pid)
    return require(request, needed)


def for_evaluation(request, evaluation_pid, needed: str = "viewer") -> str | None:
    from aisc_backend.models.evaluation import Evaluation

    _exists_or_404(Evaluation.objects.filter(pid=evaluation_pid))
    return require(request, needed)


def for_component(request, component_pid, needed: str = "viewer") -> str | None:
    from aisc_backend.models import AIComponent

    _exists_or_404(AIComponent.objects.filter(pid=component_pid))
    return require(request, needed)


def for_plugin(request, plugin_pid, needed: str = "viewer") -> str | None:
    from aisc_backend.models import Plugin

    _exists_or_404(Plugin.objects.filter(pid=plugin_pid))
    return require(request, needed)


def for_project_config(request, project_pid, config_pid, needed: str = "viewer") -> str | None:
    from aisc_backend.models.project_config import ProjectConfig

    same_project(project_pid)
    _exists_or_404(ProjectConfig.objects.filter(pid=config_pid, project__pid=project_pid))
    return require(request, needed)


def for_stored_file(request, container, file_name: str, needed: str = "viewer") -> str | None:
    """A file in object storage. The buckets are shared; the row that points at
    the object, in this project's database, is what makes it this project's."""
    from aisc_backend.models import AIComponent
    from aisc_backend.models.artifact import Artifact
    from aisc_backend.models.common import StorageContainer

    if container in (StorageContainer.Datasets, StorageContainer.Models):
        _exists_or_404(AIComponent.objects.filter(data=file_name, storage_container=container))
    else:
        _exists_or_404(Artifact.objects.filter(data=file_name))
    return require(request, needed)


def for_task(request, task_pid, needed: str = "viewer") -> str | None:
    from aisc_backend.models.evaluation import Evaluation

    _exists_or_404(Evaluation.objects.filter(task=task_pid))
    return require(request, needed)
```

- [ ] **Step 6: Every pid a route meets is compared with the door's, and the worker gets its ticket.**
- `routers/project.py`, in `project_for_platform`: `membership.require(request, platform_project_id, "editor")` → `membership.for_project_pid(request, platform_project_id, "editor")`.
- `routers/evaluation.py:69-72`: the check moves in front of the lookup:

```python
    # Running tests is work on the project, so it takes an editor. The project
    # in the body must be the one the door admitted.
    await sync_to_async(membership.for_project_pid)(request, data.project_pid, "editor")
    project = await project_repository.get(data.project_pid, True)
```

- `routers/evaluation.py:130`: `celery_service.run_evaluation(evaluation.pid)` → `celery_service.run_evaluation(project.pid, evaluation.pid)`.
- `routers/plugin.py`: in `create_plugins`, `refresh_plugins` and `delete_plugin`, add `await sync_to_async(membership.for_project_pid)(request, data.project_uuid, "editor")` as the first statement after the local `from asgiref.sync import sync_to_async` (lines 175, 240, 282). The body names the project, and it must be the admitted one.
- `services/celery_service.py:18-20` becomes:

```python
async def run_evaluation(project_pid, evaluation_uuid: uuid.UUID):
    """Queue an evaluation. The worker is given the project it belongs to and a
    ticket for this run; its calls back are admitted on that ticket, for this
    project and this evaluation only (projectdb.verify_run_ticket)."""
    return celery.send_task(
        RUN_EVAL_TASK,
        args=[evaluation_uuid],
        kwargs={"project_pid": str(project_pid), "ticket": projectdb.run_ticket(project_pid, evaluation_uuid)},
    )
```

  and gains `from aisc_backend import projectdb`.
- `tests/routers/test_project_membership.py`: delete `class MembershipQueryTestCase` (the raw-SQL queries it tested are gone). Every `as_role` still patches `aisc_backend.auth.membership.role_in_project`, which now takes no arguments; the `mock.patch(…, return_value=role)` calls work unchanged.

- [ ] **Step 7: Run everything.**

Run: `bm test aisc_backend.tests.project_database aisc_backend.tests.routers aisc_backend.tests.repositories aisc_backend.tests.keycloak aisc_backend.tests.test_sample aisc_backend.tests.test_platform_links aisc_backend.tests.test_every_project_route_is_guarded`
Expected: `OK`. `test_door` alone is 24 tests.

Run: `apps/backend/scripts/test-project-databases.sh`
Expected: `OK`.

Run: `grep -rn "core\.\(project\|system\)\|to_regclass" apps/backend/aisc_backend --include=*.py | grep -v "/migrations/\|/tests/"`
Expected: no output. The engine reads nothing of the platform's tables.

- [ ] **Step 8: Commit** (inside `apps/backend`).

```bash
cd apps/backend
git add aisc_backend/projectdb.py aisc_backend/project_door.py aisc_backend/auth/membership.py aisc_backend/routers/project.py aisc_backend/routers/evaluation.py aisc_backend/routers/plugin.py aisc_backend/services/celery_service.py config/settings.py aisc_backend/tests
git commit -m "The door: this pid, checked with the platform, before its database is opened"
```

---

### Task 7: Migrate every project database at start, and nothing global left

**Files:**
- Create: `apps/backend/aisc_backend/management/__init__.py`, `apps/backend/aisc_backend/management/commands/__init__.py` (both empty), `apps/backend/aisc_backend/management/commands/migrate_projects.py`
- Modify: `apps/backend/config/settings.py` (`INSTALLED_APPS` lines 36, 46–49; `MIDDLEWARE` line 68; `AUTHENTICATION_BACKENDS` lines 142–148; delete lines 189–215)
- Modify: `apps/backend/config/urls.py:18,68-69`
- Delete: `apps/backend/config/jwt.py`, `apps/backend/aisc_backend/admin.py`
- Test: create `apps/backend/aisc_backend/tests/project_database/test_nothing_global.py`; extend `test_postgres.py`

**Interfaces:**
- Produces:
  - `manage.py migrate_projects` exits 0 when every project database the engine was given is migrated. It exits 1 when Postgres doesn't answer (retry), and 2 on a permanent failure: project databases off, or a migration that fails.
  - `aisc_backend.management.commands.migrate_projects.project_databases() -> list[str]` lists the databases matching `^project_[0-9a-f]{32}$` where `engine_rw` has `CONNECT`.
  - No `django.contrib.admin`, `allauth` or `ninja_jwt`. `django.contrib.auth`, `contenttypes` and `sessions` stay, migrated in each project database.

The admin and allauth go. Both keep users in `auth_user`, of which there are 0 rows, and neither is how anyone signs in: Keycloak is (`auth/keycloak.py`). `config/jwt.py` refers to `TokenPairOut`, which is defined nowhere. With no default database, `/admin/` and `/_allauth/` would have nowhere to read a user from.

- [ ] **Step 1: Write the failing tests.** Create `aisc_backend/tests/project_database/test_nothing_global.py`:

```python
"""Nothing of the engine is global: not its users, not its sessions, not a console over all projects."""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve


class NothingGlobalIsInstalledTestCase(SimpleTestCase):
    def test_no_admin_console_and_no_second_sign_in(self):
        for app in ("django.contrib.admin", "allauth", "allauth.account", "allauth.headless", "ninja_jwt"):
            with self.subTest(app=app):
                self.assertNotIn(app, settings.INSTALLED_APPS)
        for path in ("/admin/", "/_allauth/browser/v1/auth/session"):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_djangos_own_users_and_sessions_are_kept_in_each_project(self):
        for app in ("django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions"):
            self.assertIn(app, settings.INSTALLED_APPS)


class TheSweepTestCase(SimpleTestCase):
    def test_with_project_databases_off_there_is_nothing_to_sweep(self):
        with self.assertRaises(CommandError) as raised:
            call_command("migrate_projects")
        self.assertEqual(2, raised.exception.returncode)
```

Add to `ProjectDatabasesTestCase` in `test_postgres.py`:

```python
    def test_the_sweep_lists_the_databases_the_engine_was_given(self):
        from aisc_backend.management.commands.migrate_projects import project_databases

        found = project_databases()
        for pid in PIDS[:3]:
            self.assertIn(projectdb.database_name(pid), found)
        self.assertNotIn(projectdb.database_name(PIDS[3]), found)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `bm test aisc_backend.tests.project_database.test_nothing_global`
Expected: FAILED. `django.contrib.admin` is in `INSTALLED_APPS`, `/admin/` resolves, and `CommandError: Unknown command: 'migrate_projects'`.

- [ ] **Step 3: The sweep.** Create `aisc_backend/management/commands/migrate_projects.py`:

```python
"""Bring every project database the engine was given to its schema, then exit.

Runs as the aisc-backend-migrate service before the engine starts. A project
made later is migrated by the engine the first time it is opened
(projectdb.open_database), so this is how a schema change reaches the projects
that already exist. The databases are listed by name and by the grant the
platform's template gave engine_rw (platform/project-template/0004_engine.sql):
a project database the engine was never given is not the engine's to migrate.

Exit 1: Postgres did not answer, try again. Exit 2: permanent; do not retry.
"""
import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from aisc_backend import projectdb


def project_databases() -> list[str]:
    config = settings.PROJECT_DATABASE
    with psycopg.connect(host=config["HOST"] or None, port=config["PORT"] or None,
                         user=config["USER"], password=config["PASSWORD"], dbname="postgres") as conn:
        rows = conn.execute(
            "select datname from pg_database"
            " where datname ~ '^project_[0-9a-f]{32}$' and has_database_privilege(datname, 'CONNECT')"
            " order by datname"
        ).fetchall()
    return [row[0] for row in rows]


class Command(BaseCommand):
    help = "Migrate every project database this engine was given, then exit."

    def handle(self, *args, **options):
        if not settings.PROJECT_DATABASE:
            raise CommandError("project databases are off (PROJECT_DATABASES): nothing to migrate", returncode=2)
        try:
            names = project_databases()
        except psycopg.OperationalError as exc:
            raise CommandError(f"postgres is not answering: {exc}", returncode=1)
        for name in names:
            self.stdout.write(f"[engine] migrating {name}")
            try:
                projectdb.open_database(projectdb.pid_of(name))
            except projectdb.NoSuchProjectDatabase as exc:
                raise CommandError(f"{name} went away while migrating: {exc}", returncode=1)
            except projectdb.MigrationFailed as exc:
                raise CommandError(str(exc), returncode=2)
        self.stdout.write(f"[engine] {len(names)} project database(s) up to date")
```

- [ ] **Step 4: Remove the admin and allauth.** In `config/settings.py`:
- Delete `'django.contrib.admin',` (line 36) and the four lines `'allauth',` … `'ninja_jwt',` (46–49).
- Delete `'allauth.account.middleware.AccountMiddleware',` (line 68).
- Replace `AUTHENTICATION_BACKENDS` (lines 142–148) with `AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']`.
- Delete lines 189–215, from `# --- allauth (headless) ---` through the closing `}` of `NINJA_JWT`.

In `config/urls.py`, delete `from django.contrib import admin` (line 18) and the two `path("admin/", …)`, `path("_allauth/", …)` lines (68–69).

```bash
cd apps/backend && git rm -q config/jwt.py aisc_backend/admin.py
```

- [ ] **Step 5: Run everything.**

Run: `bm test aisc_backend.tests.project_database aisc_backend.tests.routers aisc_backend.tests.repositories aisc_backend.tests.keycloak aisc_backend.tests.test_sample aisc_backend.tests.test_platform_links aisc_backend.tests.test_every_project_route_is_guarded && bm makemigrations --check --dry-run`
Expected: `OK`, then `No changes detected`.

Run: `apps/backend/scripts/test-project-databases.sh`
Expected: `OK`, including `test_the_sweep_lists_the_databases_the_engine_was_given`.

- [ ] **Step 6: Commit** (inside `apps/backend`).

```bash
cd apps/backend
git add aisc_backend/management config/settings.py config/urls.py aisc_backend/tests/project_database
git commit -m "Migrate every project database at start; no admin console or second sign-in over all projects"
```

---

### Task 8: Switch the running engine to project databases

**Files:**
- Modify: `docker-compose.development.yml`:
  - the `aisc-backend` service, lines 24–83: `DB_NAME` at line 36, the Keycloak env at 60–61, `depends_on` at 66–77, the command at 80–83;
  - a new `aisc-backend-migrate` service before line 85.
- Modify: `Caddyfile:53-67`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: `aisc-backend` runs with `PROJECT_DATABASES=true` and `PLATFORM_URL=http://platform:8000`. It has no `DB_NAME` and runs no startup `migrate`, and it starts only after `aisc-backend-migrate` has exited 0. `/admin*` is no longer routed to the engine.

- [ ] **Step 1: Write the failing checks.**

Run: `docker inspect aisc-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -c '^PROJECT_DATABASES=true$'; docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d project_01399e174b014be9997a7f5e3574ab22 -Atc "select coalesce(to_regclass(\$\$engine.project\$\$)::text, \$\$none\$\$)"'`
Expected: `0`, then `none`. The engine isn't on project databases yet, and the real project has no engine tables.

- [ ] **Step 2: Compose.** In `docker-compose.development.yml`, in `aisc-backend.environment`, replace `DB_NAME: ${DB_NAME}` (line 36) with:

```yaml
      # One database per project (apps/backend/aisc_backend/projectdb.py): the
      # engine is told how to reach them, not which one. There is no shared one.
      PROJECT_DATABASES: "true"
```

After `KEYCLOAK_JWKS_URL: …` (line 61), add:

```yaml
      # Who may be in which project, asked on every request about the project
      # that request names, before its database is opened.
      PLATFORM_URL: http://platform:8000
```

Add to `aisc-backend.depends_on` (lines 66–77):

```yaml
      platform:
        condition: service_started
      aisc-backend-migrate:
        condition: service_completed_successfully
```

In `aisc-backend.command` (lines 80–83), delete the line `&& uv run manage.py migrate --noinput `. The command becomes the `uv pip install …` line followed by the `uvicorn` line.

Add this service before the `  #` line that precedes `aisc-eval-worker` (line 85):

```yaml
  # Every project database the engine was given, brought to its schema before
  # the engine starts. A project made later is migrated by the engine the first
  # time it is opened. Exit 2 is permanent (a migration failed): no retry.
  aisc-backend-migrate:
    image: aisc-backend:latest
    pull_policy: never
    container_name: aisc-backend-migrate
    environment:
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_HOST: ${DB_HOST}
      DB_PORT: ${DB_PORT}
      DB_ENGINE: ${DB_ENGINE}
      DB_SCHEMA: ${DB_SCHEMA}
      PROJECT_DATABASES: "true"
      DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY}
    volumes:
      - ./shared:/app/shared:z
    command: >
      sh -c "uv pip install --no-deps -e /app/shared/plugin-manager -e /app/shared/plugin-interface
      && until uv run manage.py migrate_projects; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[engine] waiting for postgres'; sleep 2; done"
    depends_on:
      - postgres
      - platform
    restart: "no"
    networks:
      - backend
```

- [ ] **Step 3: Caddy.** In `Caddyfile`, delete lines 53–67: the comment `# Reverse proxy to aisc-backend, Django Admin section`, the `handle /admin* { … }` block, its static-assets comment, and the `handle /static/admin/* { … }` block. `/admin` then falls through to the SPA like any other unknown path.

- [ ] **Step 4: Rebuild and switch.**

Run: `$DC up -d --build aisc-backend-migrate aisc-backend && docker wait aisc-backend-migrate && docker logs aisc-backend-migrate 2>&1 | grep '^\[engine\]' && docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`
Expected:
- `docker wait` prints `0`.
- The log shows `[engine] migrating project_01399e174b014be9997a7f5e3574ab22` (plus any other project database the platform gave the engine), then `[engine] N project database(s) up to date`.
- Caddy reloads without error.

If it prints `2`, stop and read the log. The likeliest cause is Plan 2's `project.system` missing in a project database.

- [ ] **Step 5: Check it live, in a project of its own.** This makes a throwaway platform project (which gets its own database), opens the engine on it, and deletes it:

```bash
TOK=$(curl -s --max-time 20 -d client_id=aisc-webapp -d grant_type=password -d username=admin -d password=admin \
      http://localhost:8081/realms/aisc/protocol/openid-connect/token | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))')
NAME="engine-switch-$$"
MADE=$(docker exec -e T="$TOK" -e N="$NAME" platform python -c '
import json, os, urllib.request
req = urllib.request.Request("http://localhost:8000/projects", data=json.dumps({"name": os.environ["N"]}).encode(),
      headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["T"]}, method="POST")
print(urllib.request.urlopen(req, timeout=60).read().decode())')
PID=$(printf '%s' "$MADE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pid"])')
SLUG=$(printf '%s' "$MADE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["slug"])')
docker exec -e T="$TOK" -e P="$PID" aisc-backend python -c '
import os, urllib.request, urllib.error
def go(method, path, project=os.environ["P"]):
    headers = {"Authorization": "Bearer " + os.environ["T"]}
    if project: headers["X-AISC-Project"] = project
    req = urllib.request.Request("http://localhost:8000/api/v1" + path, method=method, headers=headers)
    try: r = urllib.request.urlopen(req, timeout=60); print(r.status, r.read().decode()[:100])
    except urllib.error.HTTPError as e: print(e.code, e.read().decode()[:100])
go("POST", "/projects/for-platform/" + os.environ["P"])
go("GET", "/projects")
go("GET", "/projects", project=None)
go("GET", "/projects", project="00000000-0000-4000-8000-000000000000")'
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d project_$(printf '%s' "$PID" | tr -d -) -Atc 'select name from engine.project'"
docker exec -e T="$TOK" -e S="$SLUG" -e N="$NAME" platform python -c '
import json, os, urllib.request
req = urllib.request.Request("http://localhost:8000/projects/" + os.environ["S"], data=json.dumps({"confirm_name": os.environ["N"]}).encode(),
      headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["T"]}, method="DELETE")
print(urllib.request.urlopen(req, timeout=60).status)'
```

Expected:
- `200 {"name": "engine-switch-…", "pid": "<PID>"}`, then `200 [{"name": "engine-switch-…", …}]`.
- `400 {"detail": "which project? …"}`, then `404 {"detail": "no such project"}`.
- `engine-switch-…`, which is the row in the new project's own database.
- `204`.

- [ ] **Step 6: Commit** (root, with `git add -p` for the compose file).

```bash
git add -p docker-compose.development.yml   # only the aisc-backend and aisc-backend-migrate hunks
git add Caddyfile apps/backend
git commit -m "The engine runs on project databases, migrated before it starts"
```

---

### Task 9: The checks say so, and a walk through it

**Files:**
- Modify: `scripts/verify-one-database.sh`:
  - delete line 29;
  - collapse the engine branches at lines 76–85 and 89–97;
  - replace lines 138–155.
- Modify: `scripts/verify-rbac.sh`:
  - `call()` at lines 31–45;
  - move lines 127–132 up;
  - add the project to lines 84–87, 140 and 191–196;
  - add new checks after line 147.
- Modify: `scripts/verify-sso.sh:147,303`
- Modify: `scripts/verify-catalogue-mapping.sh`: line 28; replace lines 83–96; the two install calls; lines 123–127.
- Modify: `scripts/verify.sh:64`

**Interfaces:**
- Consumes: everything above.
- Produces: `scripts/verify.sh` → `0 failed`.

- [ ] **Step 1: Run the verdict and watch it fail.**

Run: `scripts/verify.sh`
Expected failures:
- `verify-one-database.sh`: `the service is not on platform` and `not connecting as engine_rw` for `execution engine`.
- `verify-rbac.sh`: `an ordinary account cannot install: expected 403, got 400`, and the same for the three calls after it; also `the engine shows the project to a member: expected 200, got 400`.
- `verify-sso.sh`: `a session with no token of its own can read the engine's API (400)`.
- `verify-catalogue-mapping.sh`: `could not create a project`.

- [ ] **Step 2: `verify-one-database.sh`.**
- Delete line 29 (`"execution engine|aisc-backend|engine|project|project_id"`).
- In the loop, replace the `if [ "$name" = "execution engine" ]; then … else … fi` at lines 76–85 with its `else` body (lines 83–84), unindented by two spaces. Do the same at lines 89–97, keeping lines 95–96.
- Replace lines 138–155 (from `echo "the engine has no project of its own to choose"` through the `named` check) with:

```bash
echo "the engine keeps each project in that project's own database"
# One database per project (docs/superpowers/plans/2026-09-23-project-databases-4-engine.md).
# The shared engine schema is abandoned where it stands, not read and not migrated.
case "$(docker inspect aisc-backend --format '{{range .Config.Env}}{{println .}}{{end}}')" in
  *PROJECT_DATABASES=true*) ok "the engine is told to use project databases" ;;
  *) no "the engine is not on project databases" ;;
esac
docker inspect aisc-backend --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^DB_NAME=' \
  && no "the engine is still told to use one shared database" || ok "and is told no shared database"
for db in $(psql_ "select datname from pg_database where datname ~ '^project_[0-9a-f]{32}\$'
                     and has_database_privilege('engine_rw', datname, 'CONNECT') order by 1"); do
  n=$(docker exec postgres psql -U "$PGUSER" -d "$db" -At -c \
        "select count(*) from information_schema.tables where table_schema='engine'" 2>&1)
  case "$n" in ''|*[!0-9]*|0) no "$db has no engine tables ($n)" ;; *) ok "$db has the engine's $n tables" ;; esac
  c=$(docker exec postgres psql -U "$PGUSER" -d "$db" -At -c \
        "select count(*) from information_schema.columns
          where table_schema='engine' and table_name='project' and column_name='project_id'" 2>&1)
  [ "$c" = "0" ] && ok "and its project row names no other project" || no "$db still has engine.project.project_id"
done
```

- [ ] **Step 3: `verify-rbac.sh`.**
- `call()` (lines 31–45) gains a sixth argument, the project:

```bash
call() {  # call <container> <url> <method> <token> [body] [project]
  docker exec -e U="$2" -e M="$3" -e T="$4" -e B="${5:-}" -e P="${6:-}" "$1" python -c '
import os, urllib.request, urllib.error
headers = {"Content-Type": "application/json"}
if os.environ["T"]:
    headers["Authorization"] = "Bearer " + os.environ["T"]
if os.environ["P"]:
    headers["X-AISC-Project"] = os.environ["P"]
```

  The rest of `call()` is unchanged.
- Move the `PROJECT=$(docker exec platform python -c "` … `" 2>/dev/null | tail -1)` assignment (lines 127–132) to just before `echo "2. the engine: installing a plugin puts code on the server"` (line 80). Section 2 needs a project the account is in.
- Lines 84–87: append `"$PROJECT"` as the sixth argument of each `call aisc-backend $ENG/plugins… "$INSTALL"`. Leave line 88 (`GET /plugins`) and lines 89–90 (`/audit`) alone: they belong to no project.
- Line 140 becomes `is "the engine shows the project to a member"  200 "$(call aisc-backend $ENG/projects GET "$USER" "" "$PROJECT")"`.
- After `NOBODY=00000000-0000-0000-0000-000000000000` (line 147), add:

```bash
  is "the engine asks which project a call is for"        400 "$(call aisc-backend $ENG/projects GET "$USER")"
  is "and a project that is not a pid is not found"       404 "$(call aisc-backend $ENG/projects GET "$USER" "" "../platform")"
  is "the engine does not open a project nobody is in"    404 "$(call aisc-backend $ENG/projects GET "$USER" "" "$NOBODY")"
```

- Lines 191–196: append `"" "$PROJECT"` to each of the three `call aisc-backend …` calls. Each is still expected to be 404: the id is in no row of this project's database.

- [ ] **Step 4: `verify-sso.sh`.** Line 147 becomes `c=$(curl -s -b "$J" -H "X-AISC-Project: $PROJECT" -o /dev/null -w '%{http_code}' --max-time 20 http://localhost/api/v1/projects)`. At line 303, add `-H "X-AISC-Project: $PROJECT"` after `-H "Authorization: Bearer $TOK"`.

- [ ] **Step 5: `verify-catalogue-mapping.sh`.**
- Line 28 becomes the lines below. `PGDB` is set to the script's own project database once that project is made:

```bash
# Each project is a database of its own; PGDB is this script's once it is made.
PGDB=postgres; PGUSER=${PGUSER:-aisc-postgres-user}
```

- Replace lines 83–96 (from `echo "3. an install through the engine's own endpoint records the entry"` through `mine(){ … }`) with:

```bash
echo "3. an install through the engine's own endpoint records the entry"
# A project of its own, made on the platform like any other. It gets its own
# database, and deleting it afterwards drops that database with everything in it.
NAME="verify-catalogue-mapping-$$"
platform(){  # platform <method> <path> [json body]
  docker exec -e M="$1" -e U="http://localhost:8000$2" -e B="${3:-}" -e T="$TOK" platform python -c '
import os, urllib.request, urllib.error
req = urllib.request.Request(os.environ["U"], method=os.environ["M"], data=os.environ["B"].encode() or None,
      headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["T"]})
try: print(urllib.request.urlopen(req, timeout=60).read().decode() or "{}")
except urllib.error.HTTPError: print("{}")' 2>/dev/null | tail -1; }
MADE=$(platform POST /projects "{\"name\":\"$NAME\"}")
PROJECT=$(printf '%s' "$MADE" | py 'print(d.get("pid",""))')
PSLUG=$(printf '%s' "$MADE" | py 'print(d.get("slug",""))')
PGDB="project_$(printf '%s' "$PROJECT" | tr -d -)"
[ -n "$PROJECT" ] && ok "working in a project of its own ($NAME)" || no "could not create a project"
engine(){ api -H "X-AISC-Project: $PROJECT" "$@"; }
engine --max-time 60 -o /dev/null -X POST "$ENGINE/api/v1/projects/for-platform/$PROJECT"
cleanup(){ [ -n "${PROJECT:-}" ] || return 0
  platform DELETE "/projects/$PSLUG" "{\"confirm_name\":\"$NAME\"}" >/dev/null; }
trap 'cleanup; rm -f "$J" "$T"' EXIT
body(){ printf '{"package_name":"%s","version":"%s","project_uuid":"%s"%s}' "$PKG" "$VER" "$PROJECT" "$1"; }
mine(){ psql_ "select distinct catalogue_slug from engine.plugin"; }
```

- In the two install calls, `OUT=$(api --max-time 180 …` in section 3 and `api --max-time 180 … "$ENGINE/api/v1/plugins" >/dev/null` in section 4, change `api` to `engine`.
- Replace lines 123–127 (section 6) with:

```bash
echo "6. and it leaves nothing behind"
cleanup
LEFT=$(docker exec postgres psql -U "$PGUSER" -d postgres -At -c "select count(*) from pg_database where datname = '$PGDB'")
PROJECT=""
[ "$LEFT" = "0" ] && ok "its own project and its database are gone" || no "its database $PGDB is still there"
```

- [ ] **Step 6: `verify.sh`.** At line 64 (the `engine backend|…` entry), append ` aisc_backend.tests.project_database aisc_backend.tests.test_every_project_route_is_guarded` to the list of test labels. The line runs in the rebuilt container with `DB_ENGINE=sqlite`, which turns project databases off for the suite (`config/settings.py`: `PROJECT_DATABASES` requires Postgres). The Postgres half is `apps/backend/scripts/test-project-databases.sh`, run below.

- [ ] **Step 7: Run the whole verdict.**

Run: `scripts/verify.sh && apps/backend/scripts/test-project-databases.sh`
Expected: the final line of `verify.sh` reports `0 failed`, with `engine backend` and `engine webapp` `ok`. The Postgres suite prints `OK`.

- [ ] **Step 8: Walk through it once in the browser.**
  1. Go to http://localhost:8100, open the project, and choose step 4, Execute tests. The engine opens on the project, under the platform's name for it.
  2. In Settings, add a dataset component. Install a plugin from the catalogue: the install dialog lists this one project. Run an evaluation. It completes, and its measurements show. Along the way, the worker's calls carried the project and the ticket.
  3. On the homepage, create a second project and open its step 4. The engine is empty: no components, no plugins, no evaluations.
  4. Go back to the first project. Everything from step 2 is still there.
  5. Open http://localhost/ without `?project=` in a private window. The engine says "Open a project first" and links to the launcher.
  6. Run `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from engine.evaluation"'`. It prints the same count as before Task 8: nothing new went to the shared schema.

- [ ] **Step 9: Commit** (root, with `git add -p` for `verify.sh`).

```bash
git add scripts/verify-one-database.sh scripts/verify-rbac.sh scripts/verify-sso.sh scripts/verify-catalogue-mapping.sh
git add -p scripts/verify.sh   # only the engine backend line
git commit -m "The checks know the engine lives in each project's database"
```

---

## Stopping rule and checkpoints

- **Checkpoint after every task.** Run that task's own test commands, plus `scripts/verify.sh --modules`. A task isn't done until both are green. From Task 4 on, also run `apps/backend/scripts/test-project-databases.sh`.
- **Stop and ask:**
  - if any check in "Before you start" fails;
  - if a test outside this plan starts failing and the fix would change its assertion;
  - if `aisc-backend-migrate` exits 2;
  - if anything would need a manual change to `project_01399e174b014be9997a7f5e3574ab22`, or to any database or schema this plan didn't create, other than through the platform's provisioning or the engine's own migrations;
  - if the Task 8 Step 5 answers differ from the ones written there.
- **Retries.** At most two fix rounds per task on the same failure. After that, stop and report what is failing.
- **Done when:**
  - `scripts/verify.sh` prints `0 failed`;
  - `apps/backend/scripts/test-project-databases.sh` prints `OK`;
  - the Task 8 Step 5 answers and the Task 9 Step 8 walkthrough behave as written;
  - no shared schema was dropped;
  - nothing was pushed.
