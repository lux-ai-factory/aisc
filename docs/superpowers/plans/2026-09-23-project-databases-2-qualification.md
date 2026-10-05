# Project databases, plan 2: qualification, and the system under assessment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project's qualifications, their answers, risks and knowledge graphs live in that project's own database. So does the AI system they describe: `core.system` becomes `project.system` in each project database. The platform names systems there and stops writing the shared table.

**Architecture:** This reuses Plan 1's mechanisms unchanged:
- The platform's template (`platform/project-template/`) gains two files. `0002_system.sql` creates schema `project` with table `system`: `core.system`'s columns and identity rules, minus `project_id`. `0003_qualification.sql` creates schema `qualification`, grants it to `qualification_rw`, and lets that role read and reference `project.system`.
- The platform's `/projects/{slug}/systems` and `/systems/{pid}` endpoints connect to the project's database to read and write `project.system`. The response shape stays the same, and `project_id` is filled from `core.project`.
- The qualification app gets the project pid from the `/p/{pid}` path. Its middleware refuses a path that is not a pid before it asks the platform anything. The app opens one Prisma client per project database and migrates it on first use.
- **The only way into a project database is `projectDbFor(pid, { write })`.** It asks the platform's `GET /authz/projects/{pid}`, for that exact pid and with the caller's own token. It refuses with 404 for a stranger, 403 for a viewer's write, and 503 when the platform is silent, and it does all of this before it connects. The repository calls it for every read and write, so a pid that arrives as a bound server-action argument, a body or a header is checked just like the path's pid. The middleware check stays, as the first door.
- The seven download routes carry no project today, so they move under `/p/{pid}/api/qualifications/{id}/…`. The middleware already guards that path, so `qualificationAccess.ts` goes.
- `qualification.system_id` becomes a real foreign key to `project.system(pid)` inside the same database.
- `qualification-migrate` migrates every project database that `qualification_rw` may connect to.
- The sidecars:
  - `qualification-llm`, `-pdf`, `-ontology` and `-prefill` hold no database connection and do not change. The end-to-end check asserts this for the first three.
  - The filler (`services/agents`) calls the app back by qualification id, so it learns the project too.

**Tech Stack:** Python 3.12 + FastAPI + psycopg 3 (platform), Next.js 15 + Prisma 5 + vitest (qualification), FastAPI + pytest (filler sidecar), Postgres 14, docker compose.

**Spec:** `docs/superpowers/plans/2026-09-23-project-databases-roadmap.md` (plan 2: "`qualification` schema per project. `core.system` moves into the project database as `project.system`, and the platform stops writing it."). Also the user's words: "each project should be fully isolated from the others so everything from step 1 qualification to step 6 visualise is fully related to a project and nothing else".

## Global Constraints

- **Project database name:** `project_` + the pid, lowercased, with hyphens removed. Example: pid `3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b` → `project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b`, asserted in the TypeScript tests exactly as in `platform/tests/test_project_databases.py:16-22`.
- **Pid check first:** anything that builds a database name must first match `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (case-insensitive). Anything else is refused and nothing is connected to.
- **Roles and passwords:** roles keep their names and dev passwords (`qualification_rw` / `qualification_rw`). No new secret is committed. `POSTGRES_USER` / `POSTGRES_PASSWORD` stay inside the `postgres` container (`docker exec postgres sh -c 'psql -U "$POSTGRES_USER" …'`) and are never echoed. Never print `env.secrets`.
- **Connections:** qualification opens at most 2 connections per project database (`connection_limit=2`).
- **Access rules:** a stranger gets 404, a viewer gets 403 on any write, and the platform not answering gets 503, exactly as `decide()` in `apps/qualification/src/server/access/projectAccess.ts:84-93` already decides. Nothing in this plan adds an access rule of its own.
- **Binding (lesson from Plan 1's final review):** never trust a project id from the client just because the middleware checked the one in the URL path.
  - Every read or write of a project database checks that pid with the platform inside `projectDbFor`, which is the code path that opens the database.
  - `prismaFor` and `new PrismaClient` appear in `src/` only inside `src/lib/projectDb.ts`. Task 5 greps for this.
  - The two operator scripts, `scripts/migrate-projects.mjs` and `scripts/seed_mcas.mjs`, are run in the container by whoever deploys, and no request can reach them.
  - Each mutation entry point has a test that calls it with a pid the caller is not in, and one where they are only a viewer, and asserts that nothing was written. The entry points are:
    - saving a qualification;
    - patching an ontology node, and resetting the patch;
    - `PUT …/extracted`;
    - the knowledge-graph write a page view makes.
  - Each request now asks the platform once per database open. That is accepted, and nothing caches the answer.
- **No shared schema is dropped:** `qualification.*` and `core.system` stay in the `platform` database, abandoned and unwritten. Dropping them is the final plan's job and needs the user's go-ahead. No data is copied: the shared `qualification` schema has 0 rows. `core.system` has 1 row, MCAS v1.2.0 from the seed, and nothing references it (`engine.evaluation.system_id` is set on 0 rows). Task 1 Step 1 re-checks both counts.
- **HARD RULE:** never DROP, ALTER or delete rows in any database, schema or project you did not create yourself in the current task. The real project's database is `project_01399e174b014be9997a7f5e3574ab22` (project `microcredit-assist-score-mcas`). It changes only through the platform's template runner and qualification's own `prisma migrate deploy`; other read-only `SELECT`s on it are fine. Tests make throwaway `project_<random>` databases and drop only those.
- **Compose invocation, always:** `set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build <service>`.
- **Commits:** local only, on `feat/unified-modules`. Never push, never `git clean`.
  - Commit submodule changes inside `apps/qualification`. The root repo commits `platform/`, `scripts/`, the compose file, and the submodule pointer.
- **Leave the prefill work alone.** `apps/qualification` has uncommitted prefill work that is not part of this plan:
  - modified `next.config.ts` and `src/app/p/[project]/qualify/new/QualifyForm.tsx`;
  - untracked `services/prefill/`, `src/app/p/[project]/qualify/new/DocumentUpload.tsx` and `prefill-actions.ts`, `src/data/prefillFields.json`, `src/lib/prefillChoice.ts` and `prefillFlow.ts`, `src/server/services/PrefillClient.ts`, and `test/unit/{DocumentUpload,PrefillClient,formUpload,nextConfig,prefillChoice,prefillFields,prefillFlow}.test.ts(x)`.

  In `apps/qualification`, never run `git add -A`, `git add .`, `git add src`, `git add test` or `git commit -a`: stage the explicit paths each task lists. Before every commit there, `git diff --cached --name-only` must list none of those files, and `git status --short` afterwards must still show all of them. None of this plan's tasks edits a prefill file.

  The root has uncommitted prefill hunks too, in `docker-compose.development.yml` (the `qualification-prefill` service and `PREFILL_URL`) and `scripts/verify.sh` (the `qualification prefill` line). Stage the compose file with `git add -p`, taking only this plan's hunk. This plan does not edit `scripts/verify.sh`.
- **Standalone mode:** the standalone files `apps/qualification/docker-compose.yml` and `docker-compose.development.yml` are not updated. From here on, qualification runs inside the platform, which makes its databases.
- **Template numbering:** this plan uses `0002_system.sql` and `0003_qualification.sql`. Later plans start at `0004`.

## Review Focus

1. **`/qualification/p/abc/…`, `/p/<slug>/…` or `/p/..%2F../…`.** Expected: 404 from the middleware, with no platform call and no database name built. Pinned in Task 4 (unit) and Task 10 (`verify-rbac.sh`).
2. **A member of project A posts to A's page, but with project B's pid as the bound argument, or calls a route with it.**
   - Expected: `projectDbFor` asks the platform about B, and refuses before connecting: 404 if the caller is not in B, 403 if they are only a viewer. Nothing is written.
   - A's qualification id opened under B is 404, because B's database does not have it.
   - A qualification of another project's system is refused by the foreign key.

   Pinned in Task 4 (unit) and Task 5 (integration, one test per mutation entry point).
3. **Registering a system.**
   - It is written to `project.system` in that project's database, and no row goes to `core.system`.
   - The same name and version registered twice, or unversioned twice, is one row.
   - `/systems/{pid}` finds a system only among the caller's projects.

   Pinned in Task 1.
4. **A project database made before this plan (template `0001` only).** Expected: after the platform restarts, it gets `0002` and `0003`, and `qualification-migrate` then migrates it. A database the platform has not yet granted to `qualification_rw` is skipped, so the migrate service does not loop on it. Pinned in Tasks 2 and 9.
5. **The uncommitted prefill work.** Expected: it is still uncommitted and unchanged after every task. Checked at every commit (Global Constraints).

---

## File map

**Root repo (`~/aisc-install`)**
- Create `platform/project-template/0002_system.sql` (schema `project`, table `system`) and `platform/project-template/0003_qualification.sql` (schema `qualification`, the grants for `qualification_rw`).
- Modify `platform/platform_service/db.py`:
  - add `project_connection`;
  - rewrite `list_systems`, `get_system` and `register_system` onto the project database.
- Modify `platform/platform_service/app.py` (`systems`, `register_system`, `system`) and the docstring of `platform/platform_service/systems.py`.
- Create `platform/tests/test_project_systems.py`. Extend `platform/tests/test_project_databases.py`.
- Modify `docker-compose.development.yml`: the `qualification-migrate` command and its `depends_on`.
- Modify `scripts/verify-one-database.sh` (qualification leaves `MODULES` and gets its own section) and `scripts/verify-rbac.sh` (paths that are not projects, and the downloads).

**`apps/qualification`**
- Modify `prisma/schema.prisma`: `Qualification` loses `projectId`.
- Replace `prisma/migrations/2026*` with one baseline, `20260923140000_project_database`. It adds a foreign key to `project.system`.
- Create `src/lib/projectId.ts` and `src/lib/projectDb.ts`. `projectDb.ts` holds `projectDbFor`, the one way into a project database, which asks the platform about that pid first. Delete `src/lib/prisma.ts`.
- Modify `src/middleware.ts` (refuse a non-pid before asking the platform).
- Modify `src/server/repositories/QualificationRepository.ts`, `src/server/services/{QualificationService,OntologyService,KnowledgeGraphStore,FillerClient,PlatformClient}.ts` and `src/app/p/[project]/qualify/new/actions.ts`.
- Modify `src/app/p/[project]/qualify/[id]/{page,FillStatus}.tsx`.
- Move `src/app/api/qualifications/**` to `src/app/p/[project]/api/qualifications/**`. Delete its `system-card.pdf` alias and `src/server/access/qualificationAccess.ts`.
- Modify `scripts/seed_mcas.mjs`. Create `scripts/migrate-projects.mjs`.
- Modify `env.development`.
- Modify `services/agents/{service.py,agent.py,fill/clients.py}` and their tests.
- Tests:
  - create `test/unit/projectDb.test.ts`, `test/unit/middleware.test.ts` and `test/integration/project-database.test.ts`;
  - rewrite `test/unit/qualificationScope.test.ts`;
  - update `test/unit/{KnowledgeGraphStore,FillStatus,FillerTrigger,seedMcas}.test.ts(x)`.

---

### Task 1: The platform keeps a project's systems in the project's database

**Files:**
- Create: `platform/project-template/0002_system.sql`
- Modify: `platform/platform_service/db.py` (imports at lines 8-14; the systems block at lines 112-163: `list_systems` 117-126, `get_system` 129-135, `register_system` 138-163)
- Modify: `platform/platform_service/app.py` (import at line 30; `systems` 231-236; `register_system` docstring 243-249; `system` 261-272)
- Modify: `platform/platform_service/systems.py` (module docstring, lines 1-12)
- Test: `platform/tests/test_project_systems.py`

**Interfaces:**
- Consumes:
  - `projectdb.database_name(pid)` and `projectdb.provision(base_dsn, pid)` (`platform/platform_service/projectdb.py:24-44`);
  - `db.get_project(identifier)` (`db.py:63-72`), `db.projects_for(subject)` (`db.py:193-201`) and `db.list_projects()` (`db.py:55-60`);
  - `projects.looks_like_pid(value)` (`projects.py:70-71`).
- Produces:
  - In every project database, table `project.system(pid uuid PK default gen_random_uuid(), name text not null, version text, provider text, description text, created_at timestamptz, updated_at timestamptz)`. It has `UNIQUE (name, version)` and the unique index `system_identity_idx ON (name, coalesce(version, ''))`. It is owned by `platform_rw`, the database owner, and written only by the platform. **The engine plan (Plan 4) will consume `project.system`**, pointing `evaluation.system_id` at it in its own template file. That plan's template file grants `engine_rw` its privileges; this one grants nothing to `engine_rw`.
  - `db.project_connection(pid) -> ContextManager[psycopg.Connection]`, with `dict_row` rows. It connects as `platform_rw` to `projectdb.database_name(pid)`.
  - `db.list_systems(project: str) -> list[dict] | None` (None means no such project).
  - `db.get_system(project_pid, pid: str) -> dict | None`.
  - `db.register_system(project: str, name: str, version: str | None, provider: str | None, description: str | None) -> dict | None`.
  - The HTTP responses keep their shape: `{pid, project_id, name, version, provider, description, created_at, updated_at}`. `project_id` comes from `core.project` and is not stored.
  - `GET /systems/{pid}` looks only in the databases of the caller's projects, every project for an admin. A pid that is not a uuid gets 404.
  - `core.system` is no longer written by anything.

- [ ] **Step 1: Confirm the starting point.**

Run:
```bash
for q in "select count(*) from core.system" "select count(*) from qualification.qualification" "select count(*) from engine.evaluation where system_id is not null"; do
  docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"$q\""
done
```
Expected: `1`, `0`, `0`. **If the second or third is not 0, stop and ask the user.** Something now points at a shared system row, and this plan would orphan it.

- [ ] **Step 2: Write the failing tests.** Create `platform/tests/test_project_systems.py`:

```python
"""The system under assessment lives in its project's own database.

The platform names it, exactly as before: same identity, same response. What
changed is where it is kept. core.system is abandoned: nothing writes it any
more, and removing it is a later plan's job.
"""
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database

pytestmark = needs_database


def _in_project(dsn, pid, query, params=()):
    with psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(pid))) as conn:
        return conn.execute(query, params).fetchall()


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("sys")}, headers=as_user("alice"))
    assert made.status_code == 201, made.text
    return made.json()


def _name(client, as_user, project, **body):
    made = client.post(f"/projects/{project['slug']}/systems", json=body, headers=as_user("alice"))
    assert made.status_code == 201, made.text
    return made.json()


def test_naming_a_system_writes_it_in_the_projects_own_database(client, as_user, project, dsn):
    system = _name(client, as_user, project, name="MCAS", version="1.2.0", provider="Creditum")
    assert system["project_id"] == project["pid"]
    rows = _in_project(dsn, project["pid"], "select pid::text, name, version, provider from project.system")
    assert rows == [(system["pid"], "MCAS", "1.2.0", "Creditum")]


def test_nothing_is_written_to_the_shared_table_any_more(client, as_user, project, dsn):
    _name(client, as_user, project, name="MCAS")
    with psycopg.connect(dsn) as conn:
        left = conn.execute(
            "select count(*) from core.system where project_id = %s", (project["pid"],)
        ).fetchone()[0]
    assert left == 0


def test_the_same_system_named_twice_is_one_system(client, as_user, project, dsn):
    first = _name(client, as_user, project, name="MCAS")
    again = _name(client, as_user, project, name="  MCAS ", version="")
    assert first["pid"] == again["pid"]
    assert _in_project(dsn, project["pid"], "select count(*) from project.system") == [(1,)]


def test_a_second_naming_keeps_what_the_first_said_unless_told_otherwise(client, as_user, project):
    _name(client, as_user, project, name="MCAS", version="1", provider="Creditum", description="scores loans")
    again = _name(client, as_user, project, name="MCAS", version="1")
    assert (again["provider"], again["description"]) == ("Creditum", "scores loans")


def test_two_projects_may_each_have_a_system_of_the_same_name(client, as_user, unique):
    a = client.post("/projects", json={"name": unique("a")}, headers=as_user("alice")).json()
    b = client.post("/projects", json={"name": unique("b")}, headers=as_user("alice")).json()
    in_a = _name(client, as_user, a, name="MCAS")
    in_b = _name(client, as_user, b, name="MCAS")
    assert in_a["pid"] != in_b["pid"]
    listed = client.get(f"/projects/{b['slug']}/systems", headers=as_user("alice")).json()
    assert [s["pid"] for s in listed] == [in_b["pid"]]


def test_a_system_is_found_by_its_id_inside_its_project_only(client, as_user, project):
    system = _name(client, as_user, project, name="MCAS")
    assert client.get(f"/systems/{system['pid']}", headers=as_user("alice")).json()["name"] == "MCAS"
    assert client.get(f"/systems/{system['pid']}", headers=as_user("mallory")).status_code == 404
    admin = as_user("root", roles=("admin",))
    assert client.get(f"/systems/{system['pid']}", headers=admin).status_code == 200


def test_an_id_that_is_not_a_uuid_is_not_found(client, as_user):
    assert client.get("/systems/not-a-uuid", headers=as_user("alice")).status_code == 404
```

- [ ] **Step 3: Run them and watch them fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_project_systems.py -v`
Expected:
- The first test FAILS with `psycopg.errors.UndefinedTable: relation "project.system" does not exist`.
- `test_nothing_is_written_to_the_shared_table_any_more` FAILS (`assert 1 == 0`).
- `test_an_id_that_is_not_a_uuid_is_not_found` FAILS with a 500 (`invalid input syntax for type uuid`).

- [ ] **Step 4: Write the template.** Create `platform/project-template/0002_system.sql`:

```sql
-- The AI system under assessment, in this project's own database.
--
-- It was core.system in the shared platform database: one table for every
-- project, with a project_id column. This database is the project, so that
-- column goes and everything else stays. Identity is still the name and the
-- version, with an unversioned system being one system. The platform still
-- writes it, and only the platform: it owns this database. The modules read
-- it where their own template file grants it (0003_qualification.sql, and the
-- engine's file in a later plan).
CREATE SCHEMA IF NOT EXISTS project;
COMMENT ON SCHEMA project IS 'What this project assesses, named by the platform: its AI systems.';

CREATE TABLE IF NOT EXISTS project.system (
    pid         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    version     text,
    provider    text,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);
-- NULLs are distinct in a UNIQUE constraint, so the one above would let the
-- same unversioned system be registered twice. This index is what makes it
-- one system. (NULLS NOT DISTINCT says it in one word, from Postgres 15.)
CREATE UNIQUE INDEX IF NOT EXISTS system_identity_idx
    ON project.system (name, coalesce(version, ''));

COMMENT ON TABLE project.system IS 'The AI system under assessment: qualification describes it, the engine tests it.';
```

- [ ] **Step 5: Read and write it in the project's database.** In `db.py`, replace the imports at lines 8-14 with:

```python
import os
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from platform_service import projectdb
from platform_service.migrate import migrate
from platform_service.projects import looks_like_pid
```

In `provision_all` (lines 101-109), delete the local line `from platform_service import projectdb`: it is imported at the top now, and `projectdb` imports only `migrate`, so there is no cycle.

Replace the whole systems block (lines 112-163, from `# ── systems` down to the end of `register_system`) with:

```python
# ── systems ──────────────────────────────────────────────────────────────────
# The system under assessment, kept in its project's own database
# (project-template/0002_system.sql). Written only here: one writer is what
# keeps the name meaning one thing. project_id is not stored there, because the
# database is the project; it is put back into what these return so the API
# answers as it always has.

_SYSTEM = "pid, name, version, provider, description, created_at, updated_at"


@contextmanager
def project_connection(pid):
    """A connection to this project's own database, as the platform."""
    conninfo = make_conninfo(dsn(), dbname=projectdb.database_name(pid))
    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        yield conn


def list_systems(project: str) -> list[dict] | None:
    """The systems of this project, or None when there is no such project."""
    found = get_project(project)
    if found is None:
        return None
    with project_connection(found["pid"]) as conn:
        rows = conn.execute(f"select {_SYSTEM} from project.system order by name, version").fetchall()
    return [{**row, "project_id": found["pid"]} for row in rows]


def get_system(project_pid, pid: str) -> dict | None:
    """The system with this id in this project's database, or None."""
    with project_connection(project_pid) as conn:
        row = conn.execute(f"select {_SYSTEM} from project.system where pid = %s", (pid,)).fetchone()
    return {**row, "project_id": project_pid} if row else None


def register_system(
    project: str, name: str, version: str | None, provider: str | None,
    description: str | None,
) -> dict | None:
    """The system with this name and version in this project, making it if it
    is new. Registering the same system twice is the same system, not a second
    one, so a module may call this every time it starts work. Returns None when
    there is no such project."""
    found = get_project(project)
    if found is None:
        return None
    with project_connection(found["pid"]) as conn:
        row = conn.execute(
            "insert into project.system (name, version, provider, description)"
            " values (%s, %s, %s, %s)"
            " on conflict (name, (coalesce(version, ''))) do update"
            "    set provider = coalesce(excluded.provider, project.system.provider),"
            "        description = coalesce(excluded.description, project.system.description),"
            "        updated_at = now()"
            f" returning {_SYSTEM}",
            (name, version, provider, description),
        ).fetchone()
    return {**row, "project_id": found["pid"]}
```

- [ ] **Step 6: The endpoints.** In `app.py`, change line 30 to:

```python
from platform_service.projects import InvalidProject, looks_like_pid, normalise_name, slug_for, validate_slug
```

Replace `systems` (lines 231-236) with:

```python
@app.get("/projects/{slug}/systems")
def systems(slug: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    role_or_404(slug, caller)
    found = db.list_systems(slug)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no project {slug!r}")
    return found
```

In `register_system`'s docstring (lines 243-249), after "…the same system.", add the sentence: `It is kept in the project's own database, as project.system.`

Replace `system` (lines 261-272) with:

```python
@app.get("/systems/{pid}")
def system(pid: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """A system by its own id.

    A system lives in its project's database, so this looks in the databases of
    the projects this caller is in (every project, for an admin) and nowhere
    else: an id is never a way into a project the caller is not in.
    """
    if not looks_like_pid(pid):
        raise HTTPException(status_code=404, detail=f"no system {pid}")
    visible = db.list_projects() if caller.has_role(ADMIN_ROLE) else db.projects_for(caller.subject)
    for project in visible:
        found = db.get_system(project["pid"], pid)
        if found is not None:
            return found
    raise HTTPException(status_code=404, detail=f"no system {pid}")
```

In `systems.py`, replace the sentence on lines 5-6, "`core.system` is that name, written here and read by every module.", with: "`project.system`, in each project's own database, is that name: written by the platform, read by the modules it is granted to."

- [ ] **Step 7: Run the platform suite.**

Run: `cd platform && uv run --extra dev pytest -v`
Expected: every test PASSES. That includes `test_project_systems.py` and the system tests in `test_api_membership.py:87-135`, which now go through the project database. New projects get `0002` through `projectdb.provision` in `add_project` (`app.py:111-112`).

- [ ] **Step 8: Commit.**

```bash
git add platform/project-template/0002_system.sql platform/platform_service/db.py platform/platform_service/app.py platform/platform_service/systems.py platform/tests/test_project_systems.py
git commit -m "A project's systems live in the project's own database"
```

---

### Task 2: The project template makes qualification's schema

**Files:**
- Create: `platform/project-template/0003_qualification.sql`
- Test: `platform/tests/test_project_databases.py` (append)

**Interfaces:**
- Consumes: `project.system` (Task 1). The template runner, `migrate(conn, directory, table)` (`platform/platform_service/migrate.py:16-47`), tracked in `provision.template_migration`.
- Produces:
  - In every project database, `qualification_rw` has `CONNECT` on the database and `USAGE, CREATE` on schema `qualification`.
  - It has `USAGE` on schema `project` and `SELECT, REFERENCES` on `project.system`, and nothing more: it cannot write that table.
  - `controls_rw` gets no access to `project.system`.

- [ ] **Step 1: Write the failing tests.** Append to `platform/tests/test_project_databases.py`:

```python
@needs_database
def test_qualification_makes_its_tables_in_its_own_schema(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with _as(dsn, "qualification_rw", projectdb.database_name(created["pid"])) as conn:
        conn.execute("create table qualification.probe (x int)")
        # A qualification points at one of this project's systems, by key.
        conn.execute("create table qualification.probe_fk (s uuid references project.system (pid))")
        conn.execute("drop table qualification.probe_fk, qualification.probe")


@needs_database
def test_qualification_reads_the_systems_and_cannot_name_one(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    client.post(f"/projects/{created['slug']}/systems", json={"name": "MCAS"}, headers=as_user("alice"))
    with _as(dsn, "qualification_rw", projectdb.database_name(created["pid"])) as conn:
        assert conn.execute("select count(*) from project.system").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into project.system (name) values ('sneaky')")


@needs_database
def test_controls_cannot_read_the_systems(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with _as(dsn, "controls_rw", projectdb.database_name(created["pid"])) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select count(*) from project.system")


@needs_database
def test_a_database_made_before_these_files_gets_them_on_the_next_provision(client, as_user, unique, dsn):
    """What happens to the projects that existed before this plan: their
    database has 0001 only, and the next provision brings the rest."""
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(make_conninfo(dsn, dbname=name), autocommit=True) as conn:
        conn.execute("drop schema qualification cascade")
        conn.execute("drop schema project cascade")
        conn.execute("delete from provision.template_migration where name <> '0001_controls.sql'")
    projectdb.provision(dsn, created["pid"])
    with _as(dsn, "qualification_rw", name) as conn:
        assert conn.execute("select to_regclass('project.system')").fetchone()[0] == "project.system"
        conn.execute("create table qualification.probe (x int)")
```

The fourth test changes only the throwaway database the test itself created (named `pytest-…`, and dropped by `conftest.py:95-112`).

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_project_databases.py -v`
Expected: the first, second and fourth new tests FAIL with `psycopg.OperationalError: … permission denied for database "project_…"`. `test_controls_cannot_read_the_systems` PASSES already: `controls_rw` has no `USAGE` on schema `project`.

- [ ] **Step 3: Write the template.** Create `platform/project-template/0003_qualification.sql`:

```sql
-- Step 1, qualification: its schema in this project's database, owned by its role.
--
-- The database name is not known when this file is written, hence the DO
-- block (psycopg does not expand psql variables). 0001 already revoked
-- CONNECT from PUBLIC.
DO $grant$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO qualification_rw', current_database());
END
$grant$;

CREATE SCHEMA IF NOT EXISTS qualification;
GRANT USAGE, CREATE ON SCHEMA qualification TO qualification_rw;
COMMENT ON SCHEMA qualification IS 'Step 1: this project''s qualifications, their answers, risks and knowledge graphs.';

-- A qualification describes one of this project's systems and says so with a
-- foreign key. So it reads the system table and may reference it, but only
-- the platform names a system (0002_system.sql).
GRANT USAGE ON SCHEMA project TO qualification_rw;
GRANT SELECT, REFERENCES ON project.system TO qualification_rw;
```

- [ ] **Step 4: Run the platform suite.**

Run: `cd platform && uv run --extra dev pytest -v`
Expected: every test PASSES. `test_nobody_but_the_listed_roles_may_connect` (engine_rw is refused) still passes.

- [ ] **Step 5: Bring the existing project databases up to date.** This goes through the platform's own template runner (`provision_all`, `db.py:101-109`), which is the only way the real project database changes here.

```bash
set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build platform
sleep 5; docker exec platform python -c "from platform_service import db; db.pool()"
docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d project_01399e174b014be9997a7f5e3574ab22 -Atc "select name from provision.template_migration order by name"'
```
Expected: `0001_controls.sql`, `0002_system.sql`, `0003_qualification.sql`.

From here until Task 9 is deployed, saving a new qualification in the running stack fails. The running qualification app still keys `system_id` to `core.system`, while the platform now returns `project.system` ids. Nobody uses it meanwhile: it has 0 rows.

- [ ] **Step 6: Commit.**

```bash
git add platform/project-template/0003_qualification.sql platform/tests/test_project_databases.py
git commit -m "Every project database has a qualification schema, and qualification may point at its systems"
```

---

### Task 3: Qualification's schema without a project column, as one baseline

**Files:**
- Modify: `apps/qualification/prisma/schema.prisma` (model `Qualification`, lines 12-18 and 46)
- Delete: all 13 directories under `apps/qualification/prisma/migrations/`, from `20260430105826_add_qualification` to `20260922110000_one_naming_convention` (`migration_lock.toml` stays)
- Create: `apps/qualification/prisma/migrations/20260923140000_project_database/migration.sql`

**Interfaces:**
- Consumes: `project.system` (Task 1) and the grants of `0003_qualification.sql` (Task 2).
- Produces:
  - The Prisma `Qualification` model has no `projectId`. `systemId` (`system_id uuid`) stays.
  - One migration creates the whole qualification schema in an empty project database, with the foreign key `qualification_system_id_fkey` → `project.system(pid) ON DELETE CASCADE`.
  - The old migrations referenced `core.project` and `core.system`, which a project database does not have.

- [ ] **Step 1: Edit the schema.** In `prisma/schema.prisma`, replace lines 12-18 (the comment, `projectId` and `systemId`) with:

```prisma
  // The system it describes, in this project's own database: a uuid of
  // project.system, which only the platform writes. The engine's tests and the
  // dashboard's results point at the same row. The foreign key is made in the
  // migration, since Prisma cannot model a key into a schema this app only
  // reads. There is no project column: the database is the project.
  systemId          String                @map("system_id") @db.Uuid
```

Delete `@@index([projectId])` (line 46). Keep `@@index([systemId])`.

- [ ] **Step 2: Replace the history with a baseline.**

```bash
cd apps/qualification
git rm -r -q prisma/migrations/2026*
mkdir -p prisma/migrations/20260923140000_project_database
npx prisma migrate diff --from-empty --to-schema-datamodel prisma/schema.prisma --script > prisma/migrations/20260923140000_project_database/migration.sql
cat >> prisma/migrations/20260923140000_project_database/migration.sql <<'SQL'

-- The system a qualification describes is one of this project's, named by the
-- platform in project.system (platform/project-template/0002_system.sql).
-- Same database, so a real key: a qualification of another project's system,
-- or of none, is refused here rather than trusted. Prisma cannot model a key
-- into a schema this app only reads, so it is made here.
ALTER TABLE "qualification"
  ADD CONSTRAINT "qualification_system_id_fkey"
  FOREIGN KEY ("system_id") REFERENCES "project"."system"("pid") ON DELETE CASCADE;
SQL
npx prisma generate
```

Expected: `migration.sql` contains `CREATE TABLE "qualification"`, `"qualification_risk"`, `"knowledge_graph"` and `"qualification_answer"`, plus the added key.

Check: `grep -c 'project_id\|core\.' prisma/migrations/20260923140000_project_database/migration.sql` prints `0`.

- [ ] **Step 3: Prove the baseline applies to an empty project database made from the real template.**

```bash
PID=$(python3 -c "import uuid; print(uuid.uuid4())"); DB="project_$(echo $PID | tr -d -)"
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c 'create database $DB'"
for f in 0002_system.sql 0003_qualification.sql; do
  docker exec -i postgres sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -v ON_ERROR_STOP=1 -q" < ../../platform/project-template/$f
done
DATABASE_URL="postgresql://qualification_rw:qualification_rw@127.0.0.1:5432/$DB?schema=qualification" npx prisma migrate deploy
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -Atc \"select confrelid::regclass from pg_constraint where conname = 'qualification_system_id_fkey'\""
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c 'drop database $DB with (force)'"
```
Expected: `1 migration found … All migrations have been successfully applied.`, then `project.system`. The throwaway database is dropped at the end.

- [ ] **Step 4: Commit** (inside `apps/qualification`, explicit paths only).

```bash
git add prisma/schema.prisma prisma/migrations
git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "The database is the project: one baseline, no project column, and a real key to its system"
```

The app does not build between this commit and Task 5. Tasks 3–5 go to one reviewer together.

---

### Task 4: One way into a project's database, checked for that pid, and a door that refuses what is not a project

**Files:**
- Create: `apps/qualification/src/lib/projectId.ts`, `apps/qualification/src/lib/projectDb.ts`
- Modify: `apps/qualification/src/middleware.ts` (lines 12-14 imports, line 26 after `if (!project)`)
- Test: `apps/qualification/test/unit/projectDb.test.ts`, `apps/qualification/test/unit/middleware.test.ts`

**Interfaces:**
- Produces:
  - `PROJECT_ID: RegExp` and `isProjectId(value: string): boolean` (`src/lib/projectId.ts`). They are edge-safe, so the middleware may import them.
  - `projectDatabaseName(pid: string): string` (throws `NotAProject`).
  - `projectDatabaseUrl(pid: string, template?: string): string`.
  - `prismaFor(pid: string, deps?: { migrate: (url: string) => Promise<void> }): Promise<PrismaClient>`. It connects without checking anything, so it is used only by `projectDbFor`.
  - **`projectDbFor(pid: string, intent: { write: boolean }, deps?: { access?: (pid: string) => Promise<Access | null>; open?: (pid: string) => Promise<PrismaClient> }): Promise<PrismaClient>`.** By default it asks `fetchAccess(pid, await callerToken(), { platformUrl: process.env.PLATFORM_URL })` and maps the answer with `decide(write ? "POST" : "GET", access)`. It throws `ProjectAccessError` before `open` is called.
  - `class ProjectAccessError extends Error { status: 404 | 403 | 503 }`.
  - `migrateProjectDatabase(url: string): Promise<void>`.
  - `class NotAProject extends Error`.
  - Env `PROJECT_DATABASE_URL`, for example `postgresql://qualification_rw:qualification_rw@postgres:5432/{database}?schema=qualification&connection_limit=2`.
  - The middleware answers 404 for `/p/{x}` when `x` is not a pid, without calling the platform.

- [ ] **Step 1: Write the failing tests.** Create `test/unit/projectDb.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { PrismaClient } from "@prisma/client";
import {
  NotAProject,
  ProjectAccessError,
  prismaFor,
  projectDatabaseName,
  projectDatabaseUrl,
  projectDbFor,
} from "@/lib/projectDb";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const TEMPLATE = "postgresql://qualification_rw:pw@postgres:5432/{database}?schema=qualification";

describe("the project database", () => {
  it("is named after the pid, as the platform names it", () => {
    // Same example as platform/tests/test_project_databases.py.
    expect(projectDatabaseName(PID)).toBe("project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b");
    expect(projectDatabaseName(PID.toUpperCase())).toBe("project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b");
  });

  it.each(["", "abc", "../platform", `${PID}x`, "x'; drop database platform; --"])(
    "refuses %j before building anything",
    (bad) => {
      expect(() => projectDatabaseName(bad)).toThrow(NotAProject);
    },
  );

  it("fills the template", () => {
    expect(projectDatabaseUrl(PID, TEMPLATE)).toBe(
      "postgresql://qualification_rw:pw@postgres:5432/project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b?schema=qualification",
    );
  });

  it("refuses a template with nowhere to put the database", () => {
    expect(() => projectDatabaseUrl(PID, "postgresql://x@y/platform")).toThrow(/\{database\}/);
  });
});

describe("prismaFor", () => {
  beforeEach(() => {
    vi.stubEnv("PROJECT_DATABASE_URL", TEMPLATE);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("migrates a project's database once, however many requests arrive at once", async () => {
    const pid = "11111111-1111-4111-8111-111111111111";
    const migrate = vi.fn(() => new Promise<void>((r) => setTimeout(r, 20)));
    const [a, b] = await Promise.all([prismaFor(pid, { migrate }), prismaFor(pid, { migrate })]);
    expect(migrate).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });

  it("tries again after a migration that failed, with a new client", async () => {
    const pid = "22222222-2222-4222-8222-222222222222";
    const disconnect = vi.spyOn(PrismaClient.prototype, "$disconnect");
    const migrate = vi.fn().mockRejectedValueOnce(new Error("db starting")).mockResolvedValue(undefined);
    await expect(prismaFor(pid, { migrate })).rejects.toThrow("db starting");
    expect(disconnect).toHaveBeenCalledTimes(1);
    await expect(prismaFor(pid, { migrate })).resolves.toBeDefined();
    expect(migrate).toHaveBeenCalledTimes(2);
    disconnect.mockRestore();
  });

  it("gives two projects two clients", async () => {
    const migrate = vi.fn(async () => {});
    const a = await prismaFor("33333333-3333-4333-8333-333333333333", { migrate });
    const b = await prismaFor("44444444-4444-4444-8444-444444444444", { migrate });
    expect(a).not.toBe(b);
  });
});

// The one way in. Whatever the URL said, the pid handed here is the one asked
// about, with the caller's own token, before any connection is made.
describe("projectDbFor", () => {
  const client = {} as PrismaClient;
  const as = (role: string | null, may_write = false) => async () => ({ role, admin: false, may_write });

  it("asks the platform about exactly this pid, then opens it", async () => {
    const access = vi.fn(as("viewer"));
    const open = vi.fn(async () => client);
    await expect(projectDbFor(PID, { write: false }, { access, open })).resolves.toBe(client);
    expect(access).toHaveBeenCalledWith(PID);
    expect(open).toHaveBeenCalledWith(PID);
  });

  it("tells a stranger the project is not there, and opens nothing", async () => {
    const open = vi.fn(async () => client);
    await expect(projectDbFor(PID, { write: false }, { access: as(null), open })).rejects.toMatchObject({ status: 404 });
    await expect(projectDbFor(PID, { write: true }, { access: as(null), open })).rejects.toMatchObject({ status: 404 });
    expect(open).not.toHaveBeenCalled();
  });

  it("lets a viewer read and refuses them a write, opening nothing", async () => {
    const open = vi.fn(async () => client);
    await expect(projectDbFor(PID, { write: true }, { access: as("viewer"), open })).rejects.toMatchObject({ status: 403 });
    expect(open).not.toHaveBeenCalled();
    await expect(projectDbFor(PID, { write: false }, { access: as("viewer"), open })).resolves.toBe(client);
  });

  it("lets an editor write", async () => {
    const open = vi.fn(async () => client);
    await expect(projectDbFor(PID, { write: true }, { access: as("editor", true), open })).resolves.toBe(client);
  });

  it("opens nothing when the platform does not answer", async () => {
    const open = vi.fn(async () => client);
    await expect(projectDbFor(PID, { write: false }, { access: async () => null, open })).rejects.toBeInstanceOf(ProjectAccessError);
    await expect(projectDbFor(PID, { write: false }, { access: async () => null, open })).rejects.toMatchObject({ status: 503 });
    expect(open).not.toHaveBeenCalled();
  });

  it("does not even ask about something that is not a pid", async () => {
    const access = vi.fn(as("owner", true));
    await expect(projectDbFor("microcredit-assist-score-mcas", { write: false }, { access })).rejects.toMatchObject({ status: 404 });
    expect(access).not.toHaveBeenCalled();
  });

  it("asks the platform with the caller's token by default", async () => {
    vi.stubEnv("PLATFORM_URL", "http://platform:8000");
    const fetchMock = vi.fn(async () => Response.json({ role: null, admin: false, may_write: false }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(projectDbFor(PID, { write: false })).rejects.toMatchObject({ status: 404 });
    expect(String(fetchMock.mock.calls[0][0])).toBe(`http://platform:8000/authz/projects/${PID}`);
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });
});
```


Create `test/unit/middleware.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "@/middleware";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

// Only a pid names a project's database. Anything else under /p/ is not a
// project, and the door says so without asking the platform or building a name.
describe("the door to a project's pages", () => {
  it.each(["abc", "microcredit-assist-score-mcas", "..%2F..", `${PID}x`])(
    "answers /p/%s with 404 and asks nobody",
    async (bad) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      vi.stubEnv("PLATFORM_URL", "http://platform:8000");
      const res = await middleware(new NextRequest(`http://qualification/p/${bad}/qualifications`));
      expect(res?.status).toBe(404);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("asks the platform about a pid, and lets a member in", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ role: "viewer", admin: false, may_write: false }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("PLATFORM_URL", "http://platform:8000");
    const res = await middleware(new NextRequest(`http://qualification/p/${PID}/qualifications`));
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toBe(`http://platform:8000/authz/projects/${PID}`);
    expect(res?.status).toBe(200);
  });
});
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/qualification && npx vitest run test/unit/projectDb.test.ts test/unit/middleware.test.ts`
Expected: `projectDb.test.ts` FAILS with `Failed to resolve import "@/lib/projectDb"`. In `middleware.test.ts`, the four 404 cases FAIL: the middleware calls `fetch` and answers 503.

- [ ] **Step 3: Implement.** Create `src/lib/projectId.ts`:

```ts
/**
 * A project id, as the platform makes them.
 *
 * The only thing that may name a project's database. Pure, with no imports,
 * so the middleware (edge runtime) and the database layer share one rule.
 */
export const PROJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isProjectId(value: string): boolean {
  return PROJECT_ID.test(value);
}
```

Create `src/lib/projectDb.ts`:

```ts
/**
 * The database of one project.
 *
 * Every project has a database of its own, made by the platform when the
 * project is made. This app keeps a project's qualifications there and nowhere
 * else, so a query that forgets to filter still cannot reach another project.
 *
 * The pid comes from the /p/{pid} path, which the middleware has already
 * checked with the platform. It is validated again here because it becomes
 * part of a connection string.
 */
import { PrismaClient } from "@prisma/client";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { isProjectId } from "@/lib/projectId";
import { decide, fetchAccess, type Access } from "@/server/access/projectAccess";
import { callerToken } from "@/server/services/callerToken";

const run = promisify(execFile);

export class NotAProject extends Error {}

/** Refused before connecting: the status says why, as the middleware would. */
export class ProjectAccessError extends Error {
  constructor(
    readonly status: 404 | 403 | 503,
    message: string,
  ) {
    super(message);
    this.name = "ProjectAccessError";
  }
}

type AccessOf = (pid: string) => Promise<Access | null>;

const askPlatform: AccessOf = async (pid) =>
  fetchAccess(pid, await callerToken(), { platformUrl: process.env.PLATFORM_URL ?? "" });

/**
 * The client for this project's database, for this caller: the only way in.
 *
 * A pid can arrive from the client in many places: a bound server-action
 * argument, a body, a header. The middleware checked the one in the URL path,
 * which need not be this one. So this asks the platform what the caller is to
 * THIS pid, with their own token, and refuses before any connection is made:
 * 404 for a stranger, 403 for a viewer's write, 503 when the platform is
 * silent. Every read and write in this app goes through here, via the
 * repository.
 */
export async function projectDbFor(
  pid: string,
  { write }: { write: boolean },
  deps: { access?: AccessOf; open?: (pid: string) => Promise<PrismaClient> } = {},
): Promise<PrismaClient> {
  if (!isProjectId(pid)) throw new ProjectAccessError(404, "No such project.");
  const access = await (deps.access ?? askPlatform)(pid);
  switch (decide(write ? "POST" : "GET", access)) {
    case "not-found":
      throw new ProjectAccessError(404, "No such project.");
    case "forbidden":
      throw new ProjectAccessError(403, "You can read this project but not change it.");
    case "unavailable":
      throw new ProjectAccessError(503, "The platform is not answering, so who may be here cannot be established.");
    case "allow":
      return (deps.open ?? ((p: string) => prismaFor(p)))(pid);
  }
}

export function projectDatabaseName(pid: string): string {
  if (!isProjectId(pid)) throw new NotAProject(`not a project id: ${JSON.stringify(pid)}`);
  return `project_${pid.toLowerCase().replace(/-/g, "")}`;
}

export function projectDatabaseUrl(
  pid: string,
  template: string = process.env.PROJECT_DATABASE_URL ?? "",
): string {
  if (!template.includes("{database}")) {
    throw new Error("PROJECT_DATABASE_URL must contain {database}");
  }
  return template.replace("{database}", projectDatabaseName(pid));
}

/** Bring one project database to this app's schema. */
export async function migrateProjectDatabase(url: string): Promise<void> {
  await run("npx", ["prisma", "migrate", "deploy"], {
    env: { ...process.env, DATABASE_URL: url },
  });
}

type Entry = { client: PrismaClient; ready: Promise<void> };
const store = globalThis as unknown as { projectDatabases?: Map<string, Entry> };
const open = (store.projectDatabases ??= new Map<string, Entry>());

/**
 * The client for this project's database, migrated before its first use.
 * Requests that arrive together share one migration. One that failed is
 * forgotten and its client closed, so the next request tries again.
 */
export async function prismaFor(
  pid: string,
  deps: { migrate: (url: string) => Promise<void> } = { migrate: migrateProjectDatabase },
): Promise<PrismaClient> {
  const url = projectDatabaseUrl(pid);
  let entry = open.get(url);
  if (!entry) {
    const ready = deps.migrate(url);
    const created: Entry = { client: new PrismaClient({ datasources: { db: { url } } }), ready };
    entry = created;
    open.set(url, created);
    ready.catch(() => {
      if (open.get(url) === created) open.delete(url);
      created.client.$disconnect().catch(() => {});
    });
  }
  await entry.ready;
  return entry.client;
}
```

In `src/middleware.ts`, add `import { isProjectId } from "@/lib/projectId";` after the import on line 14. After line 26 (`if (!project) return NextResponse.next();`), add:

```ts
  // Only a pid names a project's database. A slug, or anything else, is not a
  // project here: say so before asking anyone, and before any name is built.
  if (!isProjectId(project)) return new NextResponse("No such project.", { status: 404 });
```

- [ ] **Step 4: Run them.**

Run: `npx vitest run test/unit/projectDb.test.ts test/unit/middleware.test.ts test/unit/projectAccess.test.ts`
Expected: all PASS: 18 in `projectDb.test.ts`, 5 in `middleware.test.ts`, and the existing `projectAccess.test.ts` unchanged.

`prismaFor` is defined further down the module than `projectDbFor`. That is fine, because it is called only at run time.

- [ ] **Step 5: Commit** (inside `apps/qualification`).

```bash
git add src/lib/projectId.ts src/lib/projectDb.ts src/middleware.ts test/unit/projectDb.test.ts test/unit/middleware.test.ts
git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "One way into a project's database, asked of the platform for that pid"
```

---

### Task 5: Every read and write goes to the project's own database, downloads included

**Files:**
- Modify: `src/server/repositories/QualificationRepository.ts` (whole file, lines 1-168)
- Modify: `src/server/services/QualificationService.ts` (lines 36-40)
- Modify: `src/server/services/OntologyService.ts` (lines 48, 63, 80-84, 95, 98)
- Modify: `src/server/services/KnowledgeGraphStore.ts` (`save` 132-154, `document` 163-177, `deliver` 184-203)
- Modify: `src/server/services/PlatformClient.ts` (header comment, lines 1-10)
- Modify: `src/app/p/[project]/qualify/new/actions.ts` (the `catch` at lines 109-117)
- Move: `src/app/api/qualifications/` → `src/app/p/[project]/api/qualifications/`
- Delete: `src/app/api/qualifications/[id]/system-card.pdf/route.ts`, `src/server/access/qualificationAccess.ts`, `src/lib/prisma.ts`
- Modify (after the move): the `route.ts` of `ai-card.json`, `ai-card.pdf`, `ontology.jsonld`, `ontology.ttl`, `extracted` and `fill`
- Modify: `src/app/p/[project]/qualify/[id]/page.tsx` (lines 110-112)
- Modify: `env.development` (lines 5-10, 22-23)
- Test: rewrite `test/unit/qualificationScope.test.ts`. Update `test/unit/KnowledgeGraphStore.test.ts`. Create `test/integration/project-database.test.ts`.

All paths are inside `apps/qualification`.

**Interfaces:**
- Consumes: `projectDbFor(pid, { write })` and `ProjectAccessError` (Task 4). The schema has no `projectId` (Task 3).
- Produces:
  - `type ClientFor = (project: string, intent: { write: boolean }) => Promise<PrismaClient>`.
  - `new QualificationRepository(clientFor: ClientFor = projectDbFor)`. Every method takes `project` first, and every method opens the database through `clientFor`, so the platform is asked about that pid each time.
    - These open it with `{ write: true }`: `create(project, input)` (input has no `projectId`), `saveKnowledgeGraph(project, data)`, `saveOntologyPatch(project, id, patch)`, `saveOntologyExtracted(project, id, extracted)` and `saveSystemCard(project, id, json)`.
    - These open it with `{ write: false }`: `find(project, id, opts?: { write?: boolean })`, `list(project)`, `cardSummary(project, id, opts?: { write?: boolean })` and `knowledgeGraph(project, qualificationId)`. Passing `{ write: true }` to `find` or `cardSummary` refuses a viewer before a write that is about to follow.
  - `OntologyService.patchNode` and `resetPatch` read with `{ write: true }`, so a viewer or a stranger is refused before any build or save. `PUT …/extracted` does the same with `cardSummary`.
  - `ProjectAccessError` becomes a status or a message where it can reach the user:
    - `PUT …/extracted` and `GET …/extracted` answer `err.status`;
    - `submitQualification` returns `{ error: err.message }`;
    - the ontology actions already return `{ ok: false, error }`;
    - `KnowledgeGraphStore.save` swallows it, as it swallows every error. So a viewer's page view stores no graph and still shows one.
  - `KnowledgeGraphStore.save(project, qualificationId, built)`, `document(project, qualificationId, built, format)` and `deliver(project, qualificationId, format, build)`.
  - `QualificationService.createFromForm(project, formData)`, `list(project)` and `get(project, id)` keep their signatures. `OntologyService.build/patchNode/resetPatch(projectId, qualificationId, …)` keep theirs.
  - The download and filler routes are `GET /p/{pid}/api/qualifications/{id}/{ai-card.json|ai-card.pdf|ontology.jsonld|ontology.ttl|extracted|fill}` and `PUT …/extracted`. The middleware gates them: a viewer reads, and only a writer may `PUT`.
  - `/api/qualifications/**` no longer exists, and neither does `…/system-card.pdf`.

- [ ] **Step 1: Write the failing unit tests.** Replace `test/unit/qualificationScope.test.ts` with:

```ts
import { describe, it, expect, vi } from "vitest";

// A qualification belongs to one project, and it lives in that project's
// database. The project picks the database, so an id from another project is
// simply not there to be found, and nothing filters by project because
// nothing of another project's is present to filter out.

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const SYSTEM = "5f1b0000-0000-4000-8000-000000000001";

function fakeProjects() {
  const asked: string[] = [];
  const intents: boolean[] = [];
  const calls: Record<string, unknown>[] = [];
  const record = async (args: Record<string, unknown>) => {
    calls.push(args);
    return null;
  };
  const client = {
    qualification: {
      findUnique: vi.fn(record),
      findFirst: vi.fn(record),
      findMany: vi.fn(async (args: Record<string, unknown>) => {
        calls.push(args);
        return [];
      }),
      create: vi.fn(async (args: Record<string, unknown>) => {
        calls.push(args);
        return { id: "q1" };
      }),
      update: vi.fn(async (args: Record<string, unknown>) => {
        calls.push(args);
        return {};
      }),
    },
    knowledgeGraph: {
      findUnique: vi.fn(record),
      upsert: vi.fn(async (args: Record<string, unknown>) => {
        calls.push(args);
        return {};
      }),
    },
  };
  const clientFor = async (project: string, intent: { write: boolean }) => {
    asked.push(project);
    intents.push(intent.write);
    return client as never;
  };
  return { asked, intents, calls, client, clientFor };
}

describe("every way into the database says whether it will write", () => {
  it("reads ask to read and writes ask to write, so a viewer is refused only the writes", async () => {
    const { QualificationRepository } = await import("@/server/repositories/QualificationRepository");
    const { intents, clientFor } = fakeProjects();
    const repo = new QualificationRepository(clientFor);
    await repo.find(PID, "q1");
    await repo.list(PID);
    await repo.cardSummary(PID, "q1");
    await repo.knowledgeGraph(PID, "q1");
    expect(intents).toEqual([false, false, false, false]);
    intents.length = 0;
    await repo.find(PID, "q1", { write: true });
    await repo.cardSummary(PID, "q1", { write: true });
    await repo.saveOntologyPatch(PID, "q1", {});
    await repo.saveOntologyExtracted(PID, "q1", {});
    await repo.saveSystemCard(PID, "q1", {});
    await repo.saveKnowledgeGraph(PID, { qualificationId: "q1", digest: "d", turtle: "t", jsonld: "{}", nodes: 1, triples: 1 });
    expect(intents).toEqual([true, true, true, true, true, true]);
  });

  it("uses the checked way in by default", async () => {
    const source = await import("node:fs").then((fs) =>
      fs.readFileSync("src/server/repositories/QualificationRepository.ts", "utf8"),
    );
    expect(source).toMatch(/clientFor: ClientFor = projectDbFor/);
    expect(source).not.toMatch(/prismaFor/);
  });
});

describe("the repository reads the project's own database", () => {
  it("find() opens the project's database and asks it for the id alone", async () => {
    const { QualificationRepository } = await import("@/server/repositories/QualificationRepository");
    const { asked, calls, clientFor } = fakeProjects();
    await new QualificationRepository(clientFor).find(PID, "qual-1");
    expect(asked).toEqual([PID]);
    expect(calls[0].where).toEqual({ id: "qual-1" });
  });

  it("cardSummary() does too", async () => {
    const { QualificationRepository } = await import("@/server/repositories/QualificationRepository");
    const { asked, calls, clientFor } = fakeProjects();
    await new QualificationRepository(clientFor).cardSummary(PID, "qual-1");
    expect(asked).toEqual([PID]);
    expect(calls[0].where).toEqual({ id: "qual-1" });
  });

  it("list() lists what that database holds", async () => {
    const { QualificationRepository } = await import("@/server/repositories/QualificationRepository");
    const { asked, calls, clientFor } = fakeProjects();
    await new QualificationRepository(clientFor).list(PID);
    expect(asked).toEqual([PID]);
    expect(calls[0].where).toBeUndefined();
  });

  it("create() writes no project column", async () => {
    const { QualificationRepository } = await import("@/server/repositories/QualificationRepository");
    const { calls, clientFor } = fakeProjects();
    await new QualificationRepository(clientFor).create(PID, {
      systemId: SYSTEM, systemName: "MCAS", systemVersion: "1", company: "C", description: "d",
      targetUseCase: "t", targetUsers: "u", intendedDeployers: "", targetSystemTags: [], sectorTags: [],
      marketFormTags: [], localityTags: [], answers: [], risks: [],
    });
    const data = calls[0].data as Record<string, unknown>;
    expect(data.systemId).toBe(SYSTEM);
    expect(data).not.toHaveProperty("projectId");
  });
});

describe("a qualification is saved in the project it was made in", () => {
  it("names the system on the platform and stores its id, in that project", async () => {
    const { QualificationService } = await import("@/server/services/QualificationService");
    const repo = { create: vi.fn(async () => ({ id: "q1" })) };
    const parser = {
      parse: () => ({
        systemName: "MCAS", systemVersion: "1", company: "C", description: "d", targetUseCase: "t",
        targetUsers: "u", intendedDeployers: "", targetSystemTags: [], sectorTags: [],
        marketFormTags: [], localityTags: [], answers: [], risks: [],
      }),
    };
    const platform = {
      registerSystem: vi.fn(async () => ({ pid: SYSTEM, project_id: PID, name: "MCAS", version: "1" })),
    };
    await new QualificationService(repo as never, parser as never, platform as never).createFromForm(PID, new FormData());
    expect(platform.registerSystem).toHaveBeenCalledWith(PID, expect.objectContaining({ name: "MCAS" }));
    const [project, input] = repo.create.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(project).toBe(PID);
    expect(input.systemId).toBe(SYSTEM);
    expect(input).not.toHaveProperty("projectId");
  });
});

describe("the save action says why a project refused it", () => {
  it("returns the refusal to the form rather than throwing", async () => {
    vi.resetModules();
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    vi.doMock("@/server/services/QualificationService", async () => {
      const { ProjectAccessError } = await import("@/lib/projectDb");
      return {
        qualificationService: {
          createFromForm: async () => {
            throw new ProjectAccessError(403, "You can read this project but not change it.");
          },
        },
      };
    });
    const { submitQualification } = await import("@/app/p/[project]/qualify/new/actions");
    await expect(submitQualification(PID, undefined, new FormData())).resolves.toEqual({
      error: "You can read this project but not change it.",
    });
    vi.doUnmock("@/server/services/QualificationService");
    vi.doUnmock("next/navigation");
  });
});
```

In `test/unit/KnowledgeGraphStore.test.ts`:
- Add `const P = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";` after the imports (after line 6).
- In `fakeRepo` (lines 17-27), change the two functions to take the project first: `knowledgeGraph: vi.fn(async (_project: string, id: string) => rows.get(id) ?? null)` and `saveKnowledgeGraph: vi.fn(async (_project: string, row: Record<string, unknown>) => { … })`, with the same bodies.
- Then add `P, ` as the first argument of every `store.save(`, `store.document(` and `store.deliver(` call: `sed -i -E 's/store\.(save|document|deliver)\(/store.\1(P, /g' test/unit/KnowledgeGraphStore.test.ts`.
- Add this test inside the first `describe` block, after "keeps systems apart":

```ts
  it("reads and writes in the project it was asked about", async () => {
    await store.save(P, "q1", built("abc"));
    expect(repo.knowledgeGraph).toHaveBeenCalledWith(P, "q1");
    expect(repo.saveKnowledgeGraph).toHaveBeenCalledWith(P, expect.objectContaining({ qualificationId: "q1" }));
  });
```

- [ ] **Step 2: Write the failing integration test.** Create `test/integration/project-database.test.ts`:

```ts
import { describe, it, expect, beforeAll, beforeEach, afterAll, vi } from "vitest";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

import { execSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { ProjectAccessError, projectDatabaseName } from "@/lib/projectDb";
import { qualificationRepository } from "@/server/repositories/QualificationRepository";
import { QualificationService } from "@/server/services/QualificationService";
import { ontologyService } from "@/server/services/OntologyService";
import { patchOntologyNode, resetOntology } from "@/app/p/[project]/qualify/[id]/ontology-actions";
import { GET as aiCardJson } from "@/app/p/[project]/api/qualifications/[id]/ai-card.json/route";
import { PUT as putExtracted } from "@/app/p/[project]/api/qualifications/[id]/extracted/route";

// Two project databases, made from the platform's own template files, and
// dropped afterwards. Needs PROJECT_DATABASE_URL pointing at 127.0.0.1. The SQL
// runs inside the postgres container as its superuser, from the container's
// own env, so no password is handled here.
//
// The platform and the ontology service are stood in for at the fetch level:
// `roles` says what the caller is to each pid, and every way into a project
// database asks it about the pid it was handed, not about a URL.
const hasDb = Boolean(process.env.PROJECT_DATABASE_URL);
const TEMPLATE = new URL("../../../../platform/project-template/", import.meta.url);
const PLATFORM = "http://platform.test";
const ONTOLOGY = "http://ontology.test";

const roles = new Map<string, "owner" | "viewer" | null>();
const BUILT = {
  view: { counts: { nodes: 1, triples: 1 } },
  turtle: "@prefix ex: <x> .",
  jsonld: "{}",
  problems: [],
  digest: "d1",
};

function standIns() {
  vi.stubEnv("PLATFORM_URL", PLATFORM);
  vi.stubEnv("ONTOLOGY_SERVICE_URL", ONTOLOGY);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL) => {
      const u = String(url);
      const authz = /\/authz\/projects\/([^/]+)$/.exec(u);
      if (authz) {
        const role = roles.get(decodeURIComponent(authz[1])) ?? null;
        return Response.json({ role, admin: false, may_write: role === "owner" });
      }
      if (u === `${ONTOLOGY}/build`) return Response.json(BUILT);
      return new Response(`not stood in for: ${u}`, { status: 500 });
    }),
  );
}

const psql = (db: string, sql: string) =>
  execSync(`docker exec -i postgres sh -c 'psql -U "$POSTGRES_USER" -d ${db} -v ON_ERROR_STOP=1 -q -At'`, {
    input: sql,
  }).toString().trim();

function makeProject(): { pid: string; system: string; db: string } {
  const pid = randomUUID();
  const system = randomUUID();
  const db = projectDatabaseName(pid);
  execSync(`docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q -c "create database ${db}"'`);
  for (const file of ["0002_system.sql", "0003_qualification.sql"]) {
    psql(db, readFileSync(new URL(file, TEMPLATE), "utf8"));
  }
  psql(db, `insert into project.system (pid, name) values ('${system}', 'MCAS');`);
  return { pid, system, db };
}

const input = (systemId: string) => ({
  systemId, systemName: "MCAS", systemVersion: "v1", company: "Creditum", description: "Scores loans",
  targetUseCase: "Retail credit", targetUsers: "Applicants", intendedDeployers: "Banks",
  targetSystemTags: [], sectorTags: [], marketFormTags: [], localityTags: [], answers: [], risks: [],
});

const OUTSIDERS = [
  ["not in the project", null, 404],
  ["only a viewer", "viewer", 403],
] as const;

describe.skipIf(!hasDb)("a project's qualifications live in its own database", () => {
  let a: ReturnType<typeof makeProject>;
  let b: ReturnType<typeof makeProject>;
  let inA: string;
  let inB: string;

  beforeAll(async () => {
    a = makeProject();
    b = makeProject();
    standIns();
    roles.set(a.pid, "owner");
    roles.set(b.pid, "owner");
    ({ id: inA } = await qualificationRepository.create(a.pid, input(a.system)));
    ({ id: inB } = await qualificationRepository.create(b.pid, input(b.system)));
  }, 120_000);

  beforeEach(() => {
    standIns();
    roles.set(a.pid, "owner");
    roles.set(b.pid, "owner");
  });

  afterAll(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    for (const p of [a, b]) {
      execSync(`docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q -c "drop database if exists ${p.db} with (force)"'`);
    }
  });

  it("a qualification saved in one project is not in the other", async () => {
    expect((await qualificationRepository.list(a.pid)).map((q) => q.id)).toEqual([inA]);
    expect((await qualificationRepository.list(b.pid)).map((q) => q.id)).toEqual([inB]);
    expect(await qualificationRepository.find(b.pid, inA)).toBeNull();
  }, 60_000);

  it("the database refuses a qualification of a system this project does not have", async () => {
    await expect(qualificationRepository.create(b.pid, input(a.system))).rejects.toThrow(/foreign key|system_id_fkey/i);
  }, 60_000);

  it("a download of one project's qualification is not found through the other", async () => {
    const res = await aiCardJson(new Request("http://q/"), { params: Promise.resolve({ project: b.pid, id: inA }) });
    expect(res.status).toBe(404);
  }, 60_000);

  it("a pid with no database fails rather than reading somewhere else", async () => {
    const nowhere = randomUUID();
    roles.set(nowhere, "owner");
    await expect(qualificationRepository.list(nowhere)).rejects.toThrow();
  }, 60_000);

  it("a stranger's read is refused before anything is opened", async () => {
    roles.set(b.pid, null);
    await expect(qualificationRepository.list(b.pid)).rejects.toMatchObject({ status: 404 });
  }, 60_000);

  // One test per way a qualification is changed. The pid is the one handed to
  // the entry point, as a bound argument or a route param would hand it over.

  it.each(OUTSIDERS)("saving a qualification, by someone %s, writes nothing", async (_who, role, status) => {
    roles.set(b.pid, role);
    const parser = { parse: () => input(b.system) };
    const platform = { registerSystem: async () => ({ pid: b.system, project_id: b.pid, name: "MCAS", version: "v1" }) };
    const service = new QualificationService(qualificationRepository, parser as never, platform as never);
    const refused = await service.createFromForm(b.pid, new FormData()).catch((e) => e);
    expect(refused).toBeInstanceOf(ProjectAccessError);
    expect(refused.status).toBe(status);
    expect(psql(b.db, "select count(*) from qualification.qualification")).toBe("1");
  }, 60_000);

  it.each(OUTSIDERS)("patching a node, by someone %s, writes nothing", async (_who, role) => {
    roles.set(b.pid, role);
    const result = await patchOntologyNode(b.pid, inB, "node-1", { label: "renamed" });
    expect(result.ok).toBe(false);
    expect(psql(b.db, `select ontology_patch is null from qualification.qualification where id = '${inB}'`)).toBe("t");
  }, 60_000);

  it.each(OUTSIDERS)("resetting the corrections, by someone %s, writes nothing", async (_who, role) => {
    roles.set(b.pid, role);
    const result = await resetOntology(b.pid, inB);
    expect(result.ok).toBe(false);
    expect(psql(b.db, `select ontology_at is null from qualification.qualification where id = '${inB}'`)).toBe("t");
  }, 60_000);

  it.each(OUTSIDERS)("publishing a draft, by someone %s, writes nothing", async (_who, role, status) => {
    roles.set(b.pid, role);
    const req = new Request("http://q/", { method: "PUT", body: JSON.stringify({ techniques: [] }) });
    const res = await putExtracted(req, { params: Promise.resolve({ project: b.pid, id: inB }) });
    expect(res.status).toBe(status);
    expect(psql(b.db, `select ontology_extracted is null from qualification.qualification where id = '${inB}'`)).toBe("t");
  }, 60_000);

  it("a viewer's page view shows the graph and stores none; an owner's stores it", async () => {
    roles.set(b.pid, "viewer");
    await expect(ontologyService.build(b.pid, inB)).resolves.toMatchObject({ digest: "d1" });
    expect(psql(b.db, "select count(*) from qualification.knowledge_graph")).toBe("0");
    roles.set(b.pid, null);
    await expect(ontologyService.build(b.pid, inB)).rejects.toMatchObject({ status: 404 });
    roles.set(b.pid, "owner");
    await ontologyService.build(b.pid, inB);
    expect(psql(b.db, "select count(*) from qualification.knowledge_graph")).toBe("1");
  }, 60_000);
});
```

- [ ] **Step 3: Run both and watch them fail.**

Run: `cd apps/qualification && PROJECT_DATABASE_URL='postgresql://qualification_rw:qualification_rw@127.0.0.1:5432/{database}?schema=qualification&connection_limit=2' npx vitest run test/unit/qualificationScope.test.ts test/unit/KnowledgeGraphStore.test.ts test/integration/project-database.test.ts`

Expected:
- `qualificationScope.test.ts` FAILS: `Cannot read properties of undefined (reading 'findFirst')`. The repository still treats its argument as a client.
- `KnowledgeGraphStore.test.ts` FAILS: `P` is taken as the qualification id.
- The integration file fails to import: `Failed to resolve import "@/app/p/[project]/api/qualifications/[id]/ai-card.json/route"`.

- [ ] **Step 4: The repository.** Replace `src/server/repositories/QualificationRepository.ts` with:

```ts
import type {
  PrismaClient,
  Prisma,
  Qualification,
  QualificationAnswer,
  QualificationRisk,
} from "@prisma/client";
import { projectDbFor } from "@/lib/projectDb";
import type { RiskInput } from "@/server/forms/QualificationFormParser";

export type AnswerInput = {
  toolId: string;
  questionId: string;
  answer: string;
};

export type CreateQualificationInput = {
  /** The system it describes, as named by the platform (a uuid of project.system). */
  systemId: string;
  systemName: string;
  systemVersion: string;
  company: string;
  description: string;
  targetUseCase: string;
  targetUsers: string;
  intendedDeployers: string;
  targetSystemTags: string[];
  sectorTags: string[];
  marketFormTags: string[];
  localityTags: string[];
  answers: AnswerInput[];
  risks: RiskInput[];
};

export type QualificationWithAnswers = Qualification & {
  answers: QualificationAnswer[];
  risks: QualificationRisk[];
};

/** The way into a project's database, for this caller, saying whether it will
 *  write. Injected, so the rules can be tested without one. */
export type ClientFor = (project: string, intent: { write: boolean }) => Promise<PrismaClient>;

/** A read that a write is about to follow: refuse a viewer before the work. */
export type ReadFor = { write?: boolean };

/**
 * A project's qualifications, in that project's own database.
 *
 * Every method takes the project first, because the project is what picks the
 * database, and every one opens it through projectDbFor, which asks the
 * platform what the caller is to THAT project before connecting. Nothing
 * filters by project: an id out of a URL that belongs to another project is not
 * in this database to be found.
 */
export class QualificationRepository {
  constructor(private readonly clientFor: ClientFor = projectDbFor) {}

  async create(project: string, input: CreateQualificationInput): Promise<{ id: string }> {
    const db = await this.clientFor(project, { write: true });
    const { answers, risks, ...rest } = input;
    return db.qualification.create({
      data: {
        ...rest,
        answers: { create: answers },
        risks: { create: risks },
      },
      select: { id: true },
    });
  }

  /** One qualification of this project, or null. */
  async find(project: string, id: string, opts: ReadFor = {}): Promise<QualificationWithAnswers | null> {
    const db = await this.clientFor(project, { write: opts.write ?? false });
    return db.qualification.findUnique({
      where: { id },
      include: { answers: true, risks: { orderBy: { position: "asc" } } },
    });
  }

  /** The qualifications of this project: everything its database holds. */
  async list(project: string): Promise<QualificationWithAnswers[]> {
    const db = await this.clientFor(project, { write: false });
    return db.qualification.findMany({
      orderBy: { createdAt: "desc" },
      include: { answers: true, risks: { orderBy: { position: "asc" } } },
    });
  }

  /** Everything an AI card needs that is not in the graph: the facts the
   *  form collects, plus the generated prose if any exists. */
  async cardSummary(
    project: string,
    id: string,
    opts: ReadFor = {},
  ): Promise<
    | (Pick<
        Qualification,
        | "id"
        | "systemName"
        | "systemVersion"
        | "company"
        | "description"
        | "targetUseCase"
        | "targetUsers"
        | "targetSystemTags"
        | "sectorTags"
      > & {
        systemCardJson: Prisma.JsonValue | null;
      })
    | null
  > {
    const db = await this.clientFor(project, { write: opts.write ?? false });
    return db.qualification.findUnique({
      where: { id },
      select: {
        id: true,
        systemCardJson: true,
        systemName: true,
        systemVersion: true,
        company: true,
        description: true,
        targetUseCase: true,
        targetUsers: true,
        targetSystemTags: true,
        sectorTags: true,
      },
    });
  }

  /** The knowledge graph kept for this system, if one has been built. */
  async knowledgeGraph(project: string, qualificationId: string) {
    const db = await this.clientFor(project, { write: false });
    return db.knowledgeGraph.findUnique({ where: { qualificationId } });
  }

  /** Keep this system's graph, replacing whatever was there. */
  async saveKnowledgeGraph(
    project: string,
    data: Omit<Prisma.KnowledgeGraphUncheckedCreateInput, "id" | "builtAt">,
  ) {
    const db = await this.clientFor(project, { write: true });
    const { qualificationId, ...rest } = data;
    return db.knowledgeGraph.upsert({
      where: { qualificationId },
      create: { qualificationId, ...rest },
      update: { ...rest, builtAt: new Date() },
    });
  }

  async saveOntologyPatch(project: string, id: string, patch: Prisma.InputJsonValue): Promise<Qualification> {
    const db = await this.clientFor(project, { write: true });
    return db.qualification.update({
      where: { id },
      data: { ontologyPatch: patch, ontologyAt: new Date() },
    });
  }

  async saveOntologyExtracted(
    project: string,
    id: string,
    extracted: Prisma.InputJsonValue,
  ): Promise<Qualification> {
    const db = await this.clientFor(project, { write: true });
    return db.qualification.update({
      where: { id },
      data: { ontologyExtracted: extracted, ontologyAt: new Date() },
    });
  }

  async saveSystemCard(project: string, id: string, json: Prisma.InputJsonValue): Promise<Qualification> {
    const db = await this.clientFor(project, { write: true });
    return db.qualification.update({
      where: { id },
      data: { systemCardJson: json, systemCardAt: new Date() },
    });
  }
}

export const qualificationRepository = new QualificationRepository();
```

- [ ] **Step 5: The services.**
  - `QualificationService.ts`, lines 36-40: replace them with `return this.repo.create(project, { ...parsed, systemId: system.pid });`.
  - `OntologyService.ts`, line 48: change it to `await this.graphs.save(projectId, qualificationId, built);`.
  - `OntologyService.ts`, lines 80-84: change them to `await this.repo.saveOntologyPatch(projectId, qualificationId, patch as unknown as Prisma.InputJsonValue); await this.graphs.save(projectId, qualificationId, built);`, on two lines.
  - `OntologyService.ts`, line 98: change it to `await this.repo.saveOntologyPatch(projectId, qualificationId, {});`.
  - `OntologyService.ts`, line 63 (`patchNode`) and line 95 (`resetPatch`): add a third argument `{ write: true }` to `this.repo.find(projectId, qualificationId)`. A viewer or a stranger is then refused before any build or save, and both actions already turn the error into `{ ok: false, error }` (`ontology-actions.ts:44-49, 61-66`).
  - `qualify/new/actions.ts`: add `import { ProjectAccessError } from "@/lib/projectDb";`, and in the `catch` (lines 109-117) add this before `throw err;`:

    ```ts
        // The pid is a bound argument, so it is the client's to send: the way
        // into the database asked the platform about it, and this is the answer.
        if (err instanceof ProjectAccessError) return { error: err.message };
    ```
  - `KnowledgeGraphStore.ts`:
    - In `save` (line 132), `document` (line 163) and `deliver` (line 184), add a first parameter `project: string,`.
    - Change each `this.repo.knowledgeGraph(qualificationId)` (lines 137, 169, 196) to `this.repo.knowledgeGraph(project, qualificationId)`.
    - Change `this.repo.saveKnowledgeGraph({` (line 140) to `this.repo.saveKnowledgeGraph(project, {`.
    - Change `this.document(qualificationId, built, format)` (line 192) to `this.document(project, qualificationId, built, format)`.
  - `PlatformClient.ts`: in the header comment (lines 1-10), replace "One database, and one writer for what every module shares." and "That name lives in `core.system`, which only the platform writes, and this is how it is asked for." with: "That name is `project.system`, in the project's own database, which only the platform writes; this is how it is asked for."

- [ ] **Step 6: Move the downloads inside the project, and remove the id-only door.**

```bash
mkdir -p "src/app/p/[project]/api"
git mv src/app/api/qualifications "src/app/p/[project]/api/qualifications"
git rm -q "src/app/p/[project]/api/qualifications/[id]/system-card.pdf/route.ts" src/server/access/qualificationAccess.ts src/lib/prisma.ts
```

The `system-card.pdf` alias is dropped: it kept `/api/qualifications/{id}/system-card.pdf` links working, and that path no longer exists at all.

In each moved `route.ts` under `src/app/p/[project]/api/qualifications/[id]/`, make these edits. Line numbers are those of the files before the move.

- `ai-card.json/route.ts`, `ai-card.pdf/route.ts`, `ontology.jsonld/route.ts` and `ontology.ttl/route.ts`:
  - delete the `import { qualificationForCaller } …` line (line 2);
  - change `{ params }: { params: Promise<{ id: string }> }` to `{ params }: { params: Promise<{ project: string; id: string }> }`;
  - change `const { id } = await params;` to `const { project, id } = await params;`;
  - delete the three comment lines that follow it and the two lines `const project = await qualificationForCaller(id);` / `if (!project) return new NextResponse("Not found", { status: 404 });`.

  The middleware has already let this caller into this project; the `cardSummary` 404 just below is the "no such qualification" answer.
- `ontology.jsonld/route.ts:33-37` and `ontology.ttl/route.ts:27-31`: change `knowledgeGraphStore.deliver(\n      id,` to `knowledgeGraphStore.deliver(\n      project,\n      id,`.
- `extracted/route.ts`: replace the file with:

```ts
import { NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { qualificationRepository } from "@/server/repositories/QualificationRepository";
import { toExport } from "@/server/services/QualificationExporter";
import { ontologyService } from "@/server/services/OntologyService";
import { parseExtracted } from "@/server/forms/ExtractedParser";
import { ProjectAccessError } from "@/lib/projectDb";

type Params = { params: Promise<{ project: string; id: string }> };

/** Refused on the way into the project's database: say so with its status. */
function refused(err: unknown): NextResponse {
  if (err instanceof ProjectAccessError) return new NextResponse(err.message, { status: err.status });
  throw err;
}

// What the filler reads: the form in the same export shape the ontology service
// is given, plus whatever draft is already stored. Inside the project's path,
// so the middleware has already asked the platform who the caller is.
export async function GET(_req: Request, { params }: Params) {
  const { project, id } = await params;
  const q = await qualificationRepository.find(project, id).catch(refused);
  if (q instanceof NextResponse) return q;
  if (!q) return new NextResponse("Not found", { status: 404 });
  return NextResponse.json({
    ...toExport(q),
    extracted: q.ontologyExtracted ?? null,
  });
}

// Where the filler publishes its reviewed draft.
//
// PUT because a run replaces the whole draft, so re-running is idempotent.
// Reviewer corrections live in `ontologyPatch` and are applied after this at
// build time, so a re-run cannot overwrite an edit. A PUT is a write: the way
// into the database refuses a stranger (404) or a viewer (403) for THIS pid
// before anything is read or written, whatever the middleware let through.
export async function PUT(req: Request, { params }: Params) {
  const { project, id } = await params;
  const exists = await qualificationRepository.cardSummary(project, id, { write: true }).catch(refused);
  if (exists instanceof NextResponse) return exists;
  if (!exists) return new NextResponse("Not found", { status: 404 });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Body is not JSON." }, { status: 400 });
  }

  const parsed = parseExtracted(body);
  if (!parsed.ok) {
    return NextResponse.json({ error: parsed.error }, { status: 422 });
  }

  await qualificationRepository.saveOntologyExtracted(project, id, parsed.value);
  // Rebuild so the stored knowledge graph reflects this draft.
  try {
    await ontologyService.build(project, id);
  } catch {
    // The draft is stored; the next build will pick it up.
  }
  // The card is built on read, so the page has to be told its input changed.
  revalidatePath(`/p/${project}/qualify/${id}`);

  const counts = {
    techniques: parsed.value.techniques?.length ?? 0,
    components: parsed.value.components?.length ?? 0,
    flagged: Object.keys(parsed.value.flags ?? {}).length,
  };
  return NextResponse.json({ ok: true, ...counts });
}
```

- `fill/route.ts`: replace lines 1-18 (the imports through the closing `}` of the access check) with the block below, and keep the rest of the file unchanged:

```ts
import { NextResponse } from "next/server";
import { qualificationRepository } from "@/server/repositories/QualificationRepository";

// The filler's run state, for the card to poll.
//
// Proxied because the filler is internal: reachable by service name inside the
// compose network, not from a browser. With no filler configured the answer is
// "idle".
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ project: string; id: string }> },
) {
  const { project, id } = await params;
  // Only a run state, but it still says whether this qualification exists.
  if (!(await qualificationRepository.cardSummary(project, id))) {
    return new NextResponse("Not found", { status: 404 });
  }
```

In `src/app/p/[project]/qualify/[id]/page.tsx`, replace lines 110-112 with:

```tsx
                pdf: `${basePath}/p/${project}/api/qualifications/${q.id}/ai-card.pdf`,
                json: `${basePath}/p/${project}/api/qualifications/${q.id}/ai-card.json`,
                jsonld: `${basePath}/p/${project}/api/qualifications/${q.id}/ontology.jsonld`,
```

- [ ] **Step 7: Point the app at project databases.** In `env.development`, replace lines 5-10 (the comment block and `DATABASE_URL=`) with:

```ini
# Every project has its own database, made by the platform. {database} is
# filled with that project's, from the /p/{pid} path; see src/lib/projectDb.ts.
PROJECT_DATABASE_URL=postgresql://qualification_rw:qualification_rw@postgres:5432/{database}?schema=qualification&connection_limit=2
```

Replace the comment on lines 22-23 with:

```ini
# Where the platform names projects and systems. A qualification describes a
# system, and only the platform writes project.system, so this is how it is named.
```

- [ ] **Step 8: Type-check, then run everything.**

Run: `npx tsc --noEmit && PROJECT_DATABASE_URL='postgresql://qualification_rw:qualification_rw@127.0.0.1:5432/{database}?schema=qualification&connection_limit=2' npx vitest run`
Expected:
- No type errors.
- All unit tests PASS, including the prefill ones, which are untouched.
- The 14 integration tests PASS: five on isolation, eight on the four mutation entry points (a stranger and a viewer each, with nothing written), and one on a viewer's page view storing no graph.

`FillStatus` and `FillerClient` still use the id-only filler URLs; Task 6 changes them.

If `tsc` reports errors only in prefill files, this plan did not cause them: report them and do not fix them.

Also run `grep -rn "@/lib/prisma\|qualificationForCaller\|projectId:" src test`. Expected: no output.

And `grep -rln "prismaFor\|new PrismaClient" src`. Expected: exactly `src/lib/projectDb.ts`. Nothing else in the app opens a project database without asking the platform.

- [ ] **Step 9: Commit** (inside `apps/qualification`).

```bash
git add prisma src/lib/prisma.ts src/server/access/qualificationAccess.ts src/server/repositories/QualificationRepository.ts \
  src/server/services/QualificationService.ts src/server/services/OntologyService.ts src/server/services/KnowledgeGraphStore.ts \
  src/server/services/PlatformClient.ts src/app/api "src/app/p/[project]/api" "src/app/p/[project]/qualify/[id]/page.tsx" \
  "src/app/p/[project]/qualify/new/actions.ts" \
  env.development test/unit/qualificationScope.test.ts test/unit/KnowledgeGraphStore.test.ts test/integration/project-database.test.ts
git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "Every qualification is read and written in its project's own database, checked for that pid, downloads included"
```

---

### Task 6: The card's filler status and the filler request carry the project

**Files:**
- Modify: `apps/qualification/src/app/p/[project]/qualify/[id]/FillStatus.tsx` (props at lines 17-21, the fetch at line 38, and the effect's dependency list)
- Modify: `apps/qualification/src/app/p/[project]/qualify/[id]/page.tsx` (line 64)
- Modify: `apps/qualification/src/server/services/FillerClient.ts` (lines 13-17, 28-30)
- Modify: `apps/qualification/src/app/p/[project]/qualify/new/actions.ts` (line 123)
- Modify: `apps/qualification/src/app/p/[project]/api/qualifications/[id]/fill/route.ts` (the proxied URL)
- Test: `apps/qualification/test/unit/FillStatus.test.tsx`, `apps/qualification/test/unit/FillerTrigger.test.ts`

**Interfaces:**
- Consumes: the routes under `/p/{pid}/api/qualifications/{id}/` (Task 5).
- Produces:
  - `<FillStatus project={string} qualificationId={string} />` polls `${NEXT_PUBLIC_BASE_PATH}/p/{pid}/api/qualifications/{id}/fill`. The base path is also a fix: the old relative `/api/…` never reached this app behind `/qualification`.
  - `FillerClient.request(project: string, qualificationId: string): Promise<boolean>` posts `{AGENT_SERVICE_URL}/fill/{pid}/{id}`, and `requestFill(project, qualificationId)` does the same.
  - The fill route proxies `GET {AGENT_SERVICE_URL}/fill/{pid}/{id}`.

- [ ] **Step 1: Write the failing tests.** In `test/unit/FillStatus.test.tsx`:
  - Add `const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";` after line 7.
  - Replace every `<FillStatus qualificationId="q1" />` with `<FillStatus project={PID} qualificationId="q1" />`: `sed -i 's|<FillStatus qualificationId="q1" />|<FillStatus project={PID} qualificationId="q1" />|g' test/unit/FillStatus.test.tsx`.
  - Add this test inside the `describe`:

```tsx
  it("asks inside the project, where the app's own route is", async () => {
    const fetchMock = withStates("idle");
    await act(async () => {
      render(<FillStatus project={PID} qualificationId="q1" />);
    });
    expect(fetchMock.mock.calls[0][0]).toBe(`/p/${PID}/api/qualifications/q1/fill`);
  });
```

In `test/unit/FillerTrigger.test.ts`:
- Add `const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";` after line 2.
- Replace every `client.request("q1")` with `client.request(PID, "q1")`: `sed -i 's/client\.request("q1")/client.request(PID, "q1")/g' test/unit/FillerTrigger.test.ts`.
- Change the expected URL on line 13 from `"http://agents:8012/fill/q1"` to `` `http://agents:8012/fill/${PID}/q1` ``.

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/qualification && npx vitest run test/unit/FillStatus.test.tsx test/unit/FillerTrigger.test.ts`
Expected:
- The new FillStatus test FAILS: it gets `/api/qualifications/q1/fill`.
- The FillerTrigger URL test FAILS: it gets `http://agents:8012/fill/3f2b8c1e-…`, because the pid lands where the id was.

- [ ] **Step 3: Implement.**
  - `FillStatus.tsx`:
    - Change the props (lines 17-21) to `{ project, qualificationId }: { project: string; qualificationId: string }`.
    - Change the fetch URL (line 38) to `` `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/p/${encodeURIComponent(project)}/api/qualifications/${qualificationId}/fill` ``.
    - Add `project` to the `useEffect` dependency array, next to `qualificationId`.
  - `page.tsx`, line 64: change it to `<FillStatus project={project} qualificationId={q.id} />`.
  - `FillerClient.ts`:
    - `request(project: string, qualificationId: string)`, with the URL `` `${this.serviceUrl}/fill/${encodeURIComponent(project)}/${qualificationId}` ``;
    - `export async function requestFill(project: string, qualificationId: string)`, returning `new FillerClient().request(project, qualificationId)`.
  - `qualify/new/actions.ts`, line 123: change it to `await requestFill(project, id);`.
  - `fill/route.ts`: change `` `${serviceUrl}/fill/${id}` `` to `` `${serviceUrl}/fill/${encodeURIComponent(project)}/${id}` ``.

- [ ] **Step 4: Run them.**

Run: `npx tsc --noEmit && npx vitest run`
Expected: no type errors, and every test PASSES.

- [ ] **Step 5: Commit** (inside `apps/qualification`).

```bash
git add "src/app/p/[project]/qualify/[id]/FillStatus.tsx" "src/app/p/[project]/qualify/[id]/page.tsx" src/server/services/FillerClient.ts \
  "src/app/p/[project]/qualify/new/actions.ts" "src/app/p/[project]/api/qualifications/[id]/fill/route.ts" \
  test/unit/FillStatus.test.tsx test/unit/FillerTrigger.test.ts
git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "The filler is asked about a qualification of a project"
```

`actions.ts` is in `qualify/new/`, next to the prefill files. Only `actions.ts` is staged there: `QualifyForm.tsx` and `prefill-actions.ts` stay unstaged.

---

### Task 7: The filler sidecar reads and publishes inside the project

**Files:**
- Modify: `apps/qualification/services/agents/service.py` (docstring line 8; `_run` 42-61; `start` 64-79; `status` 82-87)
- Modify: `apps/qualification/services/agents/agent.py` (`fill_one` 25-40; `main` 64-79)
- Modify: `apps/qualification/services/agents/fill/clients.py` (`qualification` 58-67, `publish` 70-76)
- Test: `apps/qualification/services/agents/tests/test_service.py`, `apps/qualification/services/agents/tests/test_clients.py`

**Interfaces:**
- Consumes:
  - the app routes `GET|PUT /p/{pid}/api/qualifications/{id}/extracted` (Task 5);
  - `POST|GET /fill/{pid}/{id}` from the app (Task 6).
- Produces:
  - `POST /fill/{project}/{qualification_id}` returns 202, and `GET /fill/{project}/{qualification_id}` returns the run, or 404 when there is none. A run record carries `"project"` and `"qualification"`, keyed by `"{project}/{qualification_id}"`.
  - `fill_one(project: str, qualification_id: str, dry_run: bool = False) -> dict`.
  - `clients.qualification(project: str, qualification_id: str) -> dict` and `clients.publish(project: str, qualification_id: str, extracted: dict) -> dict`.
  - The CLI is `python agent.py --project <pid> --qualification <id>`.
  - Known and unchanged: the filler sends no platform token, so the app's middleware refuses its calls. It is not deployed in the platform stack (no `AGENT_SERVICE_URL` in `docker-compose.development.yml` or `env.development`). This task keeps its URLs right, and nothing more.

- [ ] **Step 1: Write the failing tests.** In `tests/test_service.py`:
  - add `P = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"` after `import service`;
  - change `fake_fill(qualification_id: str)` (line 21) to `fake_fill(project: str, qualification_id: str)`, appending `(project, qualification_id)`;
  - change `boom(qualification_id: str)` (line 62) to `boom(project: str, qualification_id: str)`;
  - change `"/fill/q1"`, `"/fill/q2"` and `"/fill/never-heard-of-it"` to `f"/fill/{P}/q1"`, `f"/fill/{P}/q2"` and `f"/fill/{P}/never-heard-of-it"`;
  - change the expectations `== ["q1"]` and `== ["q1", "q1"]` to `== [(P, "q1")]` and `== [(P, "q1"), (P, "q1")]`;
  - change `service.RUNS["q1"] = {` (line 75) to `service.RUNS[f"{P}/q1"] = {`;
  - add this test:

```python
def test_the_same_id_in_two_projects_is_two_runs(client):
    client.post(f"/fill/{P}/q1")
    client.post("/fill/11111111-1111-4111-8111-111111111111/q1")
    assert client.runs == [(P, "q1"), ("11111111-1111-4111-8111-111111111111", "q1")]
    assert client.get(f"/fill/{P}/q1").json()["project"] == P
```

In `tests/test_clients.py`, replace `test_publishing_puts_to_the_app` (lines 47-50) with:

```python
P = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


def test_publishing_puts_to_the_app_inside_the_project(sent):
    clients.publish(P, "q1", {"techniques": []})
    assert sent[0]["url"].endswith(f"/p/{P}/api/qualifications/q1/extracted")
    assert sent[0]["method"] == "PUT"


def test_reading_asks_the_app_inside_the_project(sent):
    clients.qualification(P, "q1")
    assert sent[0]["url"].endswith(f"/p/{P}/api/qualifications/q1/extracted")
    assert sent[0]["method"] == "GET"
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/qualification && docker run --rm -v "$PWD:/w" -w /w/services/agents python:3.12-slim sh -lc 'pip install -q -r requirements.txt pytest httpx && python -m pytest -q tests/test_service.py tests/test_clients.py'`
Expected: FAIL. The `/fill/{P}/q1` routes give 404, and `publish()` takes 2 positional arguments but 3 were given.

- [ ] **Step 3: Implement.** In `fill/clients.py`, add `from urllib.parse import quote` next to the `urllib` import, and replace `qualification` and `publish` with:

```python
def _extracted_url(project: str, qualification_id: str) -> str:
    """Where the app keeps one qualification's draft: inside its project."""
    return f"{APP_URL}/p/{quote(project, safe='')}/api/qualifications/{qualification_id}/extracted"


def qualification(project: str, qualification_id: str) -> dict:
    """The saved form, in the export shape the builder reads."""
    req = request.Request(_extracted_url(project, qualification_id))
    try:
        with request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read().decode("utf-8"))
    except (error.HTTPError, OSError) as exc:
        raise ServiceError(f"cannot read qualification {qualification_id}: {exc}")


def publish(project: str, qualification_id: str, extracted: dict) -> dict:
    """Write the reviewed draft where the card reads it from."""
    return _post(_extracted_url(project, qualification_id), extracted, method="PUT")
```

In `agent.py`:
- Change `fill_one` to `def fill_one(project: str, qualification_id: str, dry_run: bool = False) -> dict:`.
- Change its first line to `qualification = clients.qualification(project, qualification_id)`.
- Change the `publish=` argument to `publish=(lambda qid, payload: None) if dry_run else (lambda qid, payload: clients.publish(project, qid, payload)),`.
- In `main`, add `parser.add_argument("--project", help="the project (pid) the qualification belongs to")` before `--qualification`.
- Change `if args.qualification:` to:

```python
    if args.qualification:
        if not args.project:
            parser.error("--qualification needs --project: a qualification lives in its project's database")
        fill_one(args.project, args.qualification, dry_run=args.dry_run)
        return 0
```

In `service.py`, change line 8 of the docstring to "The state stays readable at GET /fill/{project}/{id}, …". Replace `_run`, `start` and `status` with:

```python
def _key(project: str, qualification_id: str) -> str:
    """One qualification of one project: ids are only unique inside a project."""
    return f"{project}/{qualification_id}"


def _run(project: str, qualification_id: str) -> None:
    """One run, with its outcome recorded either way."""
    key = _key(project, qualification_id)
    with _LOCK:
        RUNS[key] |= {"state": "running"}
    try:
        result = fill_one(project, qualification_id)
    except Exception as exc:  # the app must be able to read why
        with _LOCK:
            RUNS[key] |= {"state": "failed", "error": str(exc), "finished": _now()}
        return
    with _LOCK:
        RUNS[key] |= {"state": "done", "result": result, "finished": _now()}


@app.post("/fill/{project}/{qualification_id}", status_code=202)
def start(project: str, qualification_id: str, background: BackgroundTasks) -> dict[str, Any]:
    """Start a run, unless one is already in flight for this qualification."""
    key = _key(project, qualification_id)
    with _LOCK:
        current = RUNS.get(key)
        in_flight = current and current["state"] in {"queued", "running"}
        if not in_flight:
            RUNS[key] = {
                "project": project,
                "qualification": qualification_id,
                "state": "queued",
                "started": _now(),
                "finished": None,
            }
    if not in_flight:
        background.add_task(_run, project, qualification_id)
    return RUNS[key]


@app.get("/fill/{project}/{qualification_id}")
def status(project: str, qualification_id: str) -> dict[str, Any]:
    run = RUNS.get(_key(project, qualification_id))
    if run is None:
        raise HTTPException(status_code=404, detail="no run for that qualification")
    return run
```

- [ ] **Step 4: Run the filler's suite.**

Run: `docker run --rm -v "$PWD:/w" -w /w/services/agents python:3.12-slim sh -lc 'pip install -q -r requirements.txt pytest httpx && python -m pytest -q'`
Expected: every test PASSES, including `test_workflow.py`, which calls `run_fill` with its own `publish` and is unchanged.

- [ ] **Step 5: Commit** (inside `apps/qualification`).

```bash
git add services/agents/service.py services/agents/agent.py services/agents/fill/clients.py services/agents/tests/test_service.py services/agents/tests/test_clients.py
git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "The filler reads and publishes a qualification inside its project"
```

---

### Task 8: The MCAS seed writes into the project's own database

**Files:**
- Modify: `apps/qualification/scripts/seed_mcas.mjs` (the `seedMcas` create data, lines 245-250; the script block, lines 273-285; a new exported `projectDatabaseUrl`)
- Test: `apps/qualification/test/unit/seedMcas.test.ts`

**Interfaces:**
- Consumes: `POST /projects/{project}/systems` → `{pid, project_id, …}` (Task 1: `project_id` is still returned).
- Produces:
  - `projectDatabaseUrl(pid: string, template?: string): string`, in `seed_mcas.mjs`. It follows the same rule and example as `src/lib/projectDb.ts`: a script cannot import the TypeScript module.
  - `seedMcas(prisma, { force, project, platform })` no longer writes `projectId`.
  - Running `node scripts/seed_mcas.mjs <project>` names the system first, then opens `projectDatabaseUrl(project_id)`.

- [ ] **Step 1: Write the failing test.** Append to `test/unit/seedMcas.test.ts`:

```ts
import { projectDatabaseUrl } from "../../scripts/seed_mcas.mjs";

describe("where the seed writes", () => {
  const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
  const TEMPLATE = "postgresql://qualification_rw:pw@postgres:5432/{database}?schema=qualification";

  it("is the project's own database, named as the platform names it", () => {
    expect(projectDatabaseUrl(PID, TEMPLATE)).toBe(
      "postgresql://qualification_rw:pw@postgres:5432/project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b?schema=qualification",
    );
  });

  it.each(["", "mcas", `${PID}x`])("is refused for %j, which is not a project id", (bad) => {
    expect(() => projectDatabaseUrl(bad, TEMPLATE)).toThrow(/not a project id/);
  });

  it("needs somewhere to put the database", () => {
    expect(() => projectDatabaseUrl(PID, "postgresql://x@y/platform")).toThrow(/\{database\}/);
  });
});
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/qualification && npx vitest run test/unit/seedMcas.test.ts`
Expected: FAIL, `projectDatabaseUrl is not a function`.

- [ ] **Step 3: Implement.** In `seed_mcas.mjs`, add after `MCAS_ID` (line 160):

```js
const PID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * The project's own database, where its qualifications live. The same rule as
 * src/lib/projectDb.ts, which a script cannot import.
 */
export function projectDatabaseUrl(pid, template = process.env.PROJECT_DATABASE_URL ?? "") {
  if (!template.includes("{database}")) throw new Error("PROJECT_DATABASE_URL must contain {database}");
  if (!PID.test(pid)) throw new Error(`not a project id: ${JSON.stringify(pid)}`);
  return template.replace("{database}", `project_${pid.toLowerCase().replace(/-/g, "")}`);
}
```

In `seedMcas`:
- change `const { projectId, systemId } = platform ?? (await systemForProject(project));` (line 227) to `const { systemId } = platform ?? (await systemForProject(project));`;
- delete `projectId,` from the create data (line 248).

Replace the script block (lines 273-285) with:

```js
// Only when run as a script: importing this module must not touch a database.
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const project = process.argv[2] || process.env.SEED_PROJECT || "";
  console.log(`Seeding MCAS qualification into project ${project || "<none given>"}`);
  // The system is named first, and the platform's answer says which project
  // (by pid) that is: its database is where the qualification goes.
  systemForProject(project)
    .then(async (platform) => {
      const prisma = new PrismaClient({
        datasources: { db: { url: projectDatabaseUrl(platform.projectId) } },
      });
      try {
        await seedMcas(prisma, { force: process.env.SEED_FORCE === "1", platform });
      } finally {
        await prisma.$disconnect();
      }
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
```

`systemForProject` still returns `{ projectId, systemId }` (line 206), and its existing test is unchanged. The seed runs after `qualification-migrate` has migrated that database (Task 9).

- [ ] **Step 4: Run it.**

Run: `npx vitest run test/unit/seedMcas.test.ts test/unit/seed.test.ts`
Expected: all PASS.

- [ ] **Step 5: Commit** (inside `apps/qualification`).

```bash
git add scripts/seed_mcas.mjs test/unit/seedMcas.test.ts
git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "The MCAS seed writes into the project's own database"
```

---

### Task 9: Migrate every project database at start

**Files:**
- Create: `apps/qualification/scripts/migrate-projects.mjs`
- Modify: `docker-compose.development.yml` (the `qualification-migrate` service: `command` at line 262-263 and `depends_on` at lines 265-266 of the working tree, which includes the uncommitted prefill hunk above it)

**Interfaces:**
- Consumes:
  - `PROJECT_DATABASE_URL` (Task 5, from `env_file: apps/qualification/env.development`);
  - the `project_%` databases, with `CONNECT` granted to `qualification_rw` by `0003_qualification.sql` (Task 2).
- Produces:
  - After `qualification-migrate` exits 0, every project database granted to `qualification_rw` is at the qualification baseline.
  - A database without that grant is skipped: the platform has not provisioned it for qualification yet, and the web app migrates it on first open.
  - Exit 2 means `PROJECT_DATABASE_URL` is misconfigured, and the compose loop stops on it.

- [ ] **Step 1: Write the script.** Create `apps/qualification/scripts/migrate-projects.mjs`:

```js
// Bring every project database this app is granted to its schema, then exit.
//
// Runs as the qualification-migrate service at start. A project made later is
// migrated by the web app the first time it is opened (src/lib/projectDb.ts),
// so this is for schema changes reaching the projects that already exist.
//
// Exit 2 is a misconfiguration no retry will fix: the compose loop stops on it.
import { execFileSync } from "node:child_process";
import { PrismaClient } from "@prisma/client";

const template = process.env.PROJECT_DATABASE_URL ?? "";
if (!template.includes("{database}")) {
  console.error("PROJECT_DATABASE_URL must contain {database}");
  process.exit(2);
}

// Only the databases the platform has granted this app. One it has not yet
// brought up to its template (platform/project-template/0003_qualification.sql)
// has nothing here to migrate, and waiting on it would hold every other
// project's qualification page shut.
const catalog = new PrismaClient({ datasources: { db: { url: template.replace("{database}", "postgres") } } });
const rows = await catalog.$queryRaw`
  select datname from pg_database
   where datname ~ '^project_[0-9a-f]{32}$'
     and has_database_privilege(datname, 'CONNECT')
   order by datname`;
await catalog.$disconnect();

for (const { datname } of rows) {
  console.log(`[qualification] migrating ${datname}`);
  execFileSync("npx", ["prisma", "migrate", "deploy"], {
    stdio: "inherit",
    env: { ...process.env, DATABASE_URL: template.replace("{database}", datname) },
  });
}
console.log(`[qualification] ${rows.length} project database(s) up to date`);
```

`qualification_rw` may connect to the `postgres` maintenance database, because PUBLIC has `CONNECT` there by default. It uses the Prisma client already in the image, so no new dependency is added.

- [ ] **Step 2: Change the migrate service.** In `docker-compose.development.yml`, in the `qualification-migrate` service, replace:

```yaml
    command: >
      sh -c "until npx prisma migrate deploy; do echo '[qualification] waiting for postgres'; sleep 2; done"
    env_file: apps/qualification/env.development
    depends_on:
      - postgres
```

with:

```yaml
    # Every project database granted to qualification, not one shared one.
    command: >
      sh -c "until node scripts/migrate-projects.mjs; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[qualification] waiting for postgres'; sleep 2; done"
    env_file: apps/qualification/env.development
    depends_on:
      - postgres
      - platform
```

`qualification-web` needs no compose change: it reads `PROJECT_DATABASE_URL` through its existing `env_file`, and it sets no `DATABASE_URL` of its own. The sidecar services (`qualification-llm`, `-pdf`, `-ontology`, `-prefill`) are not touched.

- [ ] **Step 3: Rebuild and check.** The real project database gets qualification's schema here, through qualification's own `prisma migrate deploy`.

```bash
set -a; . ./env.secrets; set +a; docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build qualification-migrate qualification-web
docker wait qualification-migrate && docker logs qualification-migrate 2>&1 | tail -3
```
Expected: `0`, then `[qualification] migrating project_01399e174b014be9997a7f5e3574ab22` and `[qualification] 1 project database(s) up to date`. Orphaned `project_*` databases with no `core.project` row were never provisioned with `0003`, so they are skipped.

- [ ] **Step 4: Commit** (the script in `apps/qualification`; the compose hunk in the root, with `git add -p`).

```bash
(cd apps/qualification && git add scripts/migrate-projects.mjs \
  && (git diff --cached --name-only | grep -E 'prefill|DocumentUpload|formUpload|nextConfig|QualifyForm|next\.config' && echo "STOP: prefill work staged" || git commit -m "Migrate every project database granted to qualification, at start"))
git add -p docker-compose.development.yml   # only the qualification-migrate hunk; answer n to the qualification-prefill service and PREFILL_URL hunks
git diff --cached docker-compose.development.yml | grep -c prefill   # must print 0
git commit -m "Qualification migrates project databases, not the shared one"
```

---

### Task 10: Prove it end to end, and bump the submodule

**Files:**
- Modify: `scripts/verify-one-database.sh` (`MODULES`, line 28; a new section after the `REFERENCE` loop, which ends at line 129)
- Modify: `scripts/verify-rbac.sh` (after line 153)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `scripts/verify.sh` reports `0 failed`.
  - No shared schema is dropped: `qualification.*` and `core.system` stay in `platform`, and the final plan retires them.

- [ ] **Step 1: Write the failing end-to-end assertions.** In `scripts/verify-rbac.sh`, after line 153 (`is "and not for a project nobody is in" 404 …qualification…`), add:

```bash
  QUAL="qualification-web:3000/qualification"
  is "a qualification path that is not a project is not found" 404 "$(page $QUAL/p/abc/qualifications "$USER")"
  is "nor is one named by its slug"                   404 "$(page $QUAL/p/microcredit-assist-score-mcas/qualifications "$USER")"
  is "a download for a qualification that is not there is not found" 404 \
     "$(page $QUAL/p/$PROJECT/api/qualifications/no-such-id/ai-card.json "$USER")"
  is "and is not found for a project nobody is in"    404 "$(page $QUAL/p/$NOBODY/api/qualifications/no-such-id/ai-card.json "$USER")"
  is "the old download path outside a project is gone" 404 "$(page $QUAL/api/qualifications/no-such-id/ai-card.json "$USER")"
```

The member's download check opens the real project's database through the app, and migrates it if needed. It only reads a qualification that is not there.

In `scripts/verify-one-database.sh`, delete line 28 (`"qualification|qualification-web|qualification|qualification|project_id"`). After line 129 (the end of the `REFERENCE` loop), add:

```bash
echo "qualification lives in each project's own database"
qenv=$(docker inspect qualification-web --format '{{range .Config.Env}}{{println .}}{{end}}')
case "$(printf '%s\n' "$qenv" | grep '^PROJECT_DATABASE_URL=')" in
  *qualification_rw*"{database}"*) ok "the web app opens a project's own database, as qualification_rw" ;;
  *) no "the web app is not configured per project" ;;
esac
printf '%s\n' "$qenv" | grep -q '^DATABASE_URL=' && no "it still names a shared DATABASE_URL" \
  || ok "and names no shared database"
for hex in $(psql_ "select replace(pid::text, '-', '') from core.project"); do
  pdb="project_$hex"
  inp(){ docker exec postgres psql -U "$PGUSER" -d "$pdb" -At -c "$1" 2>&1; }
  [ "$(inp "select to_regclass('qualification.qualification') is not null")" = "t" ] \
    && ok "$pdb has its qualification tables" || no "$pdb has no qualification table"
  fk=$(inp "select confrelid::regclass::text from pg_constraint
             where conrelid = 'qualification.qualification'::regclass and contype = 'f'")
  [ "$fk" = "project.system" ] && ok "and a qualification points at this project's own systems" \
    || no "the qualification's key points at '${fk:-nothing}'"
  [ "$(inp "select count(*) from information_schema.columns
             where table_schema = 'qualification' and column_name = 'project_id'")" = "0" ] \
    && ok "and carries no project column: the database is the project" \
    || no "a qualification table still names a project"
done
for c in qualification-llm qualification-pdf qualification-ontology; do
  n=$(docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | grep -cE '^(DATABASE_URL|PROJECT_DATABASE_URL|DB_NAME)=')
  [ "$n" = "0" ] && ok "$c holds no database connection" || no "$c has a database configured"
done
```

These are read-only `SELECT`s on the project databases.

The other checks that mention `qualification` stay as they are:
- the dashboard's read of `qualification.qualification` (line 158);
- the lower-case and timezone checks (lines 231, 241);
- `system_id` on exactly two tables (lines 262-266).

They read the abandoned shared schema, which is still there, and they are retired with it in the final plan.

- [ ] **Step 2: Run them.**

Run: `scripts/verify-rbac.sh; scripts/verify-one-database.sh`
Expected:
- Before Tasks 5–9 are deployed, the slug and old-path checks FAIL: the old app serves both.
- After Task 9's rebuild, every new line PASSES. The `qualification` block that was in `MODULES` is gone, and nothing that passed before fails.

- [ ] **Step 3: Run the whole verdict.**

Run: `scripts/verify.sh`
Expected: the final line reports `0 failed`. The `platform` and `qualification` module suites are `ok`, not `skip`.

- [ ] **Step 4: Walk through it once in the browser**, in a throwaway project, so the real one is not written to.
  1. On http://localhost:8100, as `admin`, create a project named `qualification walkthrough`, then open it → step 1, Qualification. "Compiled qualifications" is empty.
  2. Open **Start a qualification** with `?example=mcas` appended to the URL → **Save**. You land on the qualification's page, and the card tab shows the graph.
  3. **Download JSON**: the file downloads. Its URL is `/qualification/p/<pid>/api/qualifications/<id>/ai-card.json`.
  4. Open the real project (MicroCredit Assist Score) → step 1: its list does not show the walkthrough's qualification.
  5. Check where the system went (read-only):

     ```bash
     docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d project_<walkthrough hex> -Atc "select name, version from project.system"'
     docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from core.system"'
     ```

     Expected: `MicroCredit Assist Score (MCAS)|v1.2.0`, then `1`, which is unchanged.
  6. Back on the walkthrough project → **Delete this project…** → type its name → Delete. Its database is dropped by the platform.

- [ ] **Step 5: Commit, and bump the submodule pointer.**

```bash
git add scripts/verify-one-database.sh scripts/verify-rbac.sh
git add apps/qualification   # the pointer only: the submodule's uncommitted prefill work is not part of it
git status --short apps/qualification   # the submodule is committed; its prefill files stay uncommitted inside it
git commit -m "Qualification lives in each project's database, and so does the system it describes"
```

---

## Stopping rule and checkpoints

- **Checkpoint after every task:** run that task's own test command, then `scripts/verify.sh --modules`. A task is not done until both are green. After each commit in `apps/qualification`, also run `git -C apps/qualification status --short`: it must still list the prefill entries named in Global Constraints.
- **Stop and ask the user if:**
  - Task 1 Step 1 shows any qualification row, or an `engine.evaluation` with a `system_id`;
  - a prefill file appears in `git diff --cached`;
  - a test this plan did not write starts failing, and the fix would change its assertion;
  - `tsc` fails in a file this plan does not touch;
  - `qualification-migrate` loops (it neither exits 0 nor 2) for more than 2 minutes after the platform restart in Task 2.
- **Done when:** `scripts/verify.sh` prints `0 failed`, and the Task 10 Step 4 walkthrough behaves as written. Nothing is pushed, and no shared schema is dropped.
