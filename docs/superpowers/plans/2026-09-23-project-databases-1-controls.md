# Project databases, plan 1: controls installed from the catalogue

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each project gets its own Postgres database, created by the platform. The controls app keeps its data in it. A checklist shows up in a project's controls only after it was installed there from the catalogue in one click.

**Architecture:** The platform service creates `project_<pid hex>` when a project is created. It applies a small SQL template that creates one schema per module and grants it to that module's role. The controls app derives the project database from the `/p/{pid}` path, which its middleware has already checked with the platform. It keeps one Prisma client per project database and migrates each one on first use. There is one catalogue, hosted online, and it knows no projects. Installing a checklist is a browser hop, like the engine's plugin install:
1. The catalogue links to this platform's `/controls/install?slug=…`. It learned that address from the launcher's `#env=` handshake.
2. That page lists the projects the caller may change, and the caller picks one. The project they came from is preselected.
3. They land on `/controls/p/{pid}/install?slug=…`, which previews the checklist.
4. Its Install button is a server action, so the middleware requires a writer. It fetches the package from the catalogue's new `GET /control/{slug}/export` (at `CATALOGUE_URL`, with the bridge token when one is set) and stores it in that project's database.

**Tech Stack:** Python 3.12 + FastAPI + psycopg 3 (platform), Next.js 15 + Prisma 5 + vitest (controls), FastAPI + SQLAlchemy + pytest (catalogue backend), React + Vite + vitest (catalogue frontend), Postgres 14, docker compose.

**Spec:** `docs/superpowers/plans/2026-09-23-project-databases-roadmap.md`, plus the user's words: "each project should be fully isolated from the others so everything from step 1 qualification to step 6 visualise is fully related to a project and nothing else" and "the only thing that connects them is the homepage".

## Global Constraints

- Project database name: `project_` + the project pid, lowercased, hyphens removed (32 hex chars). Example: pid `3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b` → `project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b`. The same example is asserted in the Python and in the TypeScript tests.
- Anything used to build a database name must match `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (case-insensitive) first. Otherwise it is refused, and nothing is connected to.
- Module roles keep their names and dev passwords (`controls_rw` / `controls_rw`). No new secret is committed. `POSTGRES_USER` / `POSTGRES_PASSWORD` come from the existing env files and are never echoed.
- Postgres is 14 (`postgres:14-alpine`): `DROP DATABASE … WITH (FORCE)` works, and `public` schema ACLs come from `template1`.
- Controls opens at most 2 connections per project database (`connection_limit=2`).
- A stranger gets 404 and a viewer gets 403, exactly as `src/lib/access/projectAccess.ts` already decides. The install page adds no access rule of its own.
- Re-installing a checklist that the project already has changes nothing and says "Already installed". Rationale: `installChecklist` replaces questions, and `submission_answer` cascades on question delete, so a re-install would silently erase answers.
- Nothing is pushed. Commits go to `feat/unified-modules` in each submodule, and the root repo only bumps submodule pointers. Stage explicit paths only: the root has unrelated uncommitted work (`docker-compose.development.yml` prefill service, `scripts/verify.sh`, `apps/qualification`).

## Review Focus

1. **A `/p/{x}` path where x is not a uuid** (`/controls/p/..%2F..`, `/controls/p/abc`). Expected: 404 from the middleware, and no database name is built. Pinned in Task 4 (unit) and Task 10 (`verify-rbac.sh`).
2. **Two requests opening a brand-new project at the same moment.** Expected: one migration, and both requests wait for it. Pinned in Task 4.
3. **Catalogue down or slug unknown while installing.** Expected: the install page says so, and nothing is written. Pinned in Task 7.
4. **Installing the same checklist twice in a project, after it has been answered.** Expected: "Already installed", and the answers stay. Pinned in Task 7.
5. **Creating a project while provisioning fails** (for example Postgres refuses `CREATE DATABASE`). Expected: 503, and no project row is left without a database. Pinned in Task 2.
6. **Someone who may change no project presses Install in the catalogue** (only viewer memberships, or none). Expected: the chooser says there is no project they can install into and who can change that. It doesn't show an empty dropdown or a project they can't write to. Pinned in Task 8.
7. **An owner who isn't an admin, or an admin who mistypes the name, tries to delete a project.** Expected: 403 or 422, and the project and its database are untouched. Pinned in Task 11.

---

## File map

**Root repo (`~/aisc-install`)**
- Create `init/project-databases.sql`: superuser, idempotent. Gives `platform_rw` CREATEDB and removes `CREATE` on `public` from `template1`.
- Modify `docker-compose-infra.development.yml`: mount the file above for fresh volumes, and add a one-shot `postgres-setup` service for existing volumes.
- Modify `docker-compose.development.yml`: `platform` depends on `postgres-setup`. Controls gets `PROJECT_DATABASE_URL`, `CATALOGUE_URL` and `CATALOGUE_TOKEN`. `controls-migrate` migrates every project database and stops seeding.
- Create `platform/platform_service/projectdb.py`: the database name, provisioning and teardown.
- Create `platform/project-template/0001_controls.sql`: the per-project SQL template. Plans 2–6 add a file each.
- Modify `platform/platform_service/migrate.py`: take a directory and a tracking table.
- Modify `platform/platform_service/db.py` and `app.py`: provision on create, roll back on failure, provision existing projects at startup.
- Create `platform/tests/test_project_databases.py`. Modify `platform/tests/conftest.py` (drop test databases).
- Modify `homepage/project.html`: the catalogue handshake carries the project and the controls address. Admins get a Delete button that asks for the project's name.
- Modify `scripts/verify-db-access.sh`, `scripts/verify-one-database.sh` and `scripts/verify-rbac.sh`.

**`apps/controls`**
- Modify `prisma/schema.prisma`: `Submission` loses `projectId`, because the database is the project.
- Replace `prisma/migrations/2026*` with one baseline `20260923120000_project_database`.
- Create `src/lib/projectDb.ts`. Delete `src/lib/prisma.ts`.
- Modify every file that imported `@/lib/prisma` (list in Task 5).
- Move `src/app/sources/**` to `src/app/p/[project]/sources/**`.
- Delete `src/app/api/catalogue/**`.
- Create `src/lib/cataloguePackage.ts` and `src/app/p/[project]/install/{page.tsx,InstallForm.tsx,actions.ts}`.
- Create `src/lib/writableProjects.ts` and `src/app/install/{page.tsx,actions.ts}`: the project chooser.
- Create `scripts/migrate-projects.mjs`.
- Tests: `test/unit/projectDb.test.ts`, `test/unit/cataloguePackage.test.ts`, `test/integration/project-database.test.ts`, `test/integration/install.test.ts`. Rewrite `test/integration/project-scope.test.ts` and `submission-lifecycle.test.ts` onto `prismaFor`.

**`apps/catalogue`**
- Create `backend/controls_export.py` (ported) and `backend/controls_bridge.py` (the router, behind the existing bridge token). Modify `backend/main_api.py` (include the router).
- Create `backend/tests/test_controls_export.py`.
- Modify `frontend/src/crossSite/connect.ts` (payload fields), `frontend/src/components/catalogue/ToolDetailModal.tsx` (the controls button).
- Create `frontend/src/crossSite/controlsInstall.ts` and its test.

---

### Task 1: Let the platform create databases

**Files:**
- Create: `init/project-databases.sql`
- Modify: `docker-compose-infra.development.yml` (the `postgres` service at line 101, plus a new `postgres-setup` service)
- Modify: `docker-compose.development.yml` (`platform` service `depends_on`, line 510)
- Test: `scripts/verify-db-access.sh`

**Interfaces:**
- Produces: `platform_rw` has `rolcreatedb = true`. New databases have no `CREATE` on `public` for `PUBLIC`.

- [ ] **Step 1: Write the failing assertions.** Append before the summary lines at the end of `scripts/verify-db-access.sh`:

```bash
echo "7. the platform service makes project databases, and nobody else does"
probe="probe_db_$$"
allow platform_rw "create database $probe" "can create a database"
allow platform_rw "drop database $probe"   "and drop the one it made"
deny  controls_rw "create database ${probe}_x" "a module cannot create a database"
deny  engine_rw   "create database ${probe}_y" "nor can the engine"
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `scripts/verify-db-access.sh`
Expected: `FAIL platform_rw: can create a database (was refused)`

- [ ] **Step 3: Write the setup SQL.** Create `init/project-databases.sql`:

```sql
-- Project databases: one per project, made by the platform service.
--
-- Runs as the superuser, and is safe to run again: on a fresh volume from
-- docker-entrypoint-initdb.d, and on an existing one from the postgres-setup
-- service, which runs it on every start.
--
-- CREATEDB is the whole of what the platform is given. It owns the databases it
-- makes and nothing else; the module roles are granted into each one by the
-- template it applies (platform/project-template/).
ALTER ROLE platform_rw CREATEDB;

-- New databases are copies of template1. On Postgres 14 its public schema lets
-- every role create tables, which would give each module a second, unowned place
-- to write in every project database.
\connect template1
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

- [ ] **Step 4: Wire it into compose.** In `docker-compose-infra.development.yml`, under `postgres.volumes`, after the `05-platform-db.sql` line:

```yaml
      # Lets the platform make one database per project. After the platform DB,
      # because it alters the platform's role.
      - ./init/project-databases.sql:/docker-entrypoint-initdb.d/06-project-databases.sql:ro,Z
```

In the same file, add this service after `postgres`:

```yaml
  # The same grants on a volume that already exists: initdb scripts only run on
  # an empty one. Idempotent, so it runs on every start and then exits.
  postgres-setup:
    image: postgres:14-alpine
    container_name: postgres-setup
    environment:
      PGHOST: postgres
      PGUSER: ${POSTGRES_USER}
      PGPASSWORD: ${POSTGRES_PASSWORD}
      PGDATABASE: ${POSTGRES_DB}
    volumes:
      - ./init/project-databases.sql:/setup/project-databases.sql:ro,Z
    command: >
      sh -c "until pg_isready -q; do sleep 1; done && psql -v ON_ERROR_STOP=1 -f /setup/project-databases.sql"
    depends_on:
      - postgres
    restart: "no"
    networks:
      - backend
```

In `docker-compose.development.yml`, change the `platform` service's `depends_on` to:

```yaml
    depends_on:
      postgres:
        condition: service_started
      postgres-setup:
        condition: service_completed_successfully
```

- [ ] **Step 5: Apply it and run the assertions.**

Run: `docker compose --env-file env.development -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d postgres-setup && docker wait postgres-setup && scripts/verify-db-access.sh`
Expected: `docker wait` prints `0`. All four new lines PASS, and nothing that passed before fails.

- [ ] **Step 6: Commit.**

```bash
git add init/project-databases.sql docker-compose-infra.development.yml docker-compose.development.yml scripts/verify-db-access.sh
git commit -m "Let the platform make a database per project, and nobody else"
```

Note that `docker-compose.development.yml` has unrelated uncommitted changes (the prefill service). Use `git add -p docker-compose.development.yml` and stage only the `platform` `depends_on` hunk.

---

### Task 2: The platform creates a project's database with the project

**Files:**
- Create: `platform/platform_service/projectdb.py`
- Create: `platform/project-template/0001_controls.sql`
- Modify: `platform/platform_service/migrate.py`
- Modify: `platform/platform_service/db.py` (`create_project` at line 72, `pool()` at line 36; add `delete_project`)
- Modify: `platform/platform_service/app.py` (`add_project` at line 101)
- Modify: `platform/Dockerfile` (copy `project-template/`), `docker-compose.development.yml` (mount it, like `migrations`)
- Test: `platform/tests/test_project_databases.py`, `platform/tests/conftest.py`

**Interfaces:**
- Consumes: `platform_rw` CREATEDB (Task 1).
- Produces:
  - `projectdb.database_name(pid: str | UUID) -> str` (raises `projectdb.NotAPid`)
  - `projectdb.provision(base_dsn: str, pid) -> str` (idempotent; returns the database name)
  - `projectdb.drop(base_dsn: str, pid) -> None`
  - `migrate.migrate(conn, directory: Path = MIGRATIONS, table: str = "core.schema_migration") -> list[str]`
  - `db.delete_project(pid) -> None`
  - Every project in `core.project` has a database named `database_name(pid)`, where `controls_rw` may `CONNECT` and create in schema `controls`.

- [ ] **Step 1: Write the failing tests.** Create `platform/tests/test_project_databases.py`:

```python
"""One database per project, made by the platform when the project is made.

The name rule is tested without a database. The rest runs against the real
Postgres, like the membership tests, and skips when there is none.
"""
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


def test_the_database_is_named_after_the_pid():
    # The same example is asserted in apps/controls/test/unit/projectDb.test.ts:
    # two languages, one rule.
    assert projectdb.database_name(PID) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"
    assert projectdb.database_name(PID.upper()) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


@pytest.mark.parametrize("bad", ["", "abc", "../platform", PID + "x", "project_x; drop database platform"])
def test_anything_but_a_pid_is_refused(bad):
    with pytest.raises(projectdb.NotAPid):
        projectdb.database_name(bad)


def _as(dsn, role, dbname):
    return psycopg.connect(make_conninfo(dsn, user=role, password=role, dbname=dbname), autocommit=True)


@needs_database
def test_making_a_project_makes_its_database(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(dsn) as conn:
        assert conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone()
    with _as(dsn, "controls_rw", name) as conn:
        conn.execute("create table controls.probe (x int)")
        conn.execute("drop table controls.probe")


@needs_database
def test_two_projects_share_nothing(client, as_user, unique, dsn):
    a = client.post("/projects", json={"name": unique("a")}, headers=as_user("alice")).json()
    b = client.post("/projects", json={"name": unique("b")}, headers=as_user("alice")).json()
    with _as(dsn, "controls_rw", projectdb.database_name(a["pid"])) as conn:
        conn.execute("create table controls.only_in_a (x int)")
    with _as(dsn, "controls_rw", projectdb.database_name(b["pid"])) as conn:
        found = conn.execute("select to_regclass('controls.only_in_a')").fetchone()[0]
    assert found is None


@needs_database
def test_nobody_but_the_listed_roles_may_connect(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with pytest.raises(psycopg.OperationalError):
        _as(dsn, "engine_rw", projectdb.database_name(created["pid"]))


@needs_database
def test_provisioning_twice_changes_nothing(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    assert projectdb.provision(dsn, created["pid"]) == projectdb.database_name(created["pid"])


@needs_database
def test_a_project_whose_database_cannot_be_made_is_not_made(client, as_user, unique, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise psycopg.OperationalError("simulated: no database for you")

    monkeypatch.setattr(projectdb, "provision", refuse)
    slug = unique()
    response = client.post("/projects", json={"name": slug}, headers=as_user("alice"))
    assert response.status_code == 503
    assert client.get(f"/projects/{slug}", headers=as_user("alice")).status_code == 404
```

`engine_rw` is refused in the test above because the Plan 1 template grants `CONNECT` only to `controls_rw`. Plans 3–5 add the other roles.

- [ ] **Step 2: Make the test cleanup drop test databases.** In `platform/tests/conftest.py`, replace the body of `_leave_the_database_as_we_found_it` after `import psycopg` with:

```python
    from platform_service import projectdb

    with psycopg.connect(DSN) as conn:
        pids = [r[0] for r in conn.execute(
            "SELECT pid FROM core.project WHERE slug LIKE %s", (TEST_PREFIX + "%",)
        ).fetchall()]
        # members and systems follow their project: both are ON DELETE CASCADE.
        conn.execute("DELETE FROM core.project WHERE slug LIKE %s", (TEST_PREFIX + "%",))
        conn.commit()
    for pid in pids:
        projectdb.drop(DSN, pid)
```

- [ ] **Step 3: Run the tests and watch them fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_project_databases.py -v`
Expected: collection error `ImportError: cannot import name 'projectdb'`.

- [ ] **Step 4: Generalise the migration runner.** In `platform/platform_service/migrate.py`, replace `pending` and `migrate` with:

```python
def pending(applied: set[str], directory: Path = MIGRATIONS) -> list[Path]:
    return [f for f in sorted(directory.glob("*.sql")) if f.name not in applied]


def migrate(conn, directory: Path = MIGRATIONS, table: str = "core.schema_migration") -> list[str]:
    """Apply what has not been applied. Returns the names it ran.

    `directory` and `table` let the same runner apply the per-project template
    (platform/project-template/) to a project database, which has no core.
    """
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        schema = table.split(".")[0]
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {r["name"] if isinstance(r, dict) else r[0]
                   for r in conn.execute(f"SELECT name FROM {table}").fetchall()}
        ran = []
        for path in pending(applied, directory):
            logger.info("applying %s", path.name)
            conn.execute(path.read_text())
            conn.execute(f"INSERT INTO {table} (name) VALUES (%s)", (path.name,))
            ran.append(path.name)
        return ran
```

`table` is never user input: it's one of the two constants in this plan.

- [ ] **Step 5: Write the template.** Create `platform/project-template/0001_controls.sql`:

```sql
-- Step 5, controls: its schema in this project's database, owned by its role.
--
-- This database is one project. Nothing in it names a project, and nothing
-- outside it can be reached from here. The database name is not known when
-- this file is written, hence the DO block (psycopg does not expand psql
-- variables).
DO $grant$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO controls_rw', current_database());
END
$grant$;

CREATE SCHEMA IF NOT EXISTS controls;
GRANT USAGE, CREATE ON SCHEMA controls TO controls_rw;
COMMENT ON SCHEMA controls IS 'Step 5: this project''s checklists, submissions and answers.';
```

- [ ] **Step 6: Write `projectdb.py`.** Create `platform/platform_service/projectdb.py`:

```python
"""A database per project: its name, making it, and removing it.

The database is the project. Every module keeps its data for a project in that
project's database, so a query that forgets to filter still cannot reach
another project: it is connected to the wrong place to do it.
"""
from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

from platform_service.migrate import migrate

TEMPLATE = Path(__file__).resolve().parent.parent / "project-template"
TRACKING_TABLE = "provision.template_migration"
_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class NotAPid(ValueError):
    """Only a project id may name a database: anything else is refused unread."""


def database_name(pid: str | UUID) -> str:
    text = str(pid).lower()
    if not _PID.match(text):
        raise NotAPid(f"not a project id: {text!r}")
    return "project_" + text.replace("-", "")


def provision(base_dsn: str, pid: str | UUID) -> str:
    """Make this project's database if it is missing, and bring its template
    up to date. Safe to call again: that is how existing projects get theirs."""
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            try:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            except errors.DuplicateDatabase:
                pass  # another instance made it between the check and here
    with psycopg.connect(make_conninfo(base_dsn, dbname=name)) as conn:
        migrate(conn, TEMPLATE, TRACKING_TABLE)
    return name


def drop(base_dsn: str, pid: str | UUID) -> None:
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
```

- [ ] **Step 7: Provision on create, and undo the project if that fails.** In `db.py`, add:

```python
def delete_project(pid) -> None:
    with pool().connection() as conn:
        conn.execute("delete from core.project where pid = %s", (pid,))


def provision_all() -> None:
    """Every project has its database: the ones made before there were any get
    theirs here, at the first query after start."""
    from platform_service import projectdb

    with pool().connection() as conn:
        pids = [r["pid"] for r in conn.execute("select pid from core.project").fetchall()]
    for pid in pids:
        projectdb.provision(dsn(), pid)
```

In `pool()`, after `bootstrap_owners(bootstrap_subjects())`, add `provision_all()`. `provision_all` calls `pool()`, which by then returns the pool that was just set, so this doesn't recurse.

In `app.py`, import `from platform_service import db, projectdb` (replacing `from platform_service import db`). Replace the final `try` in `add_project` with:

```python
    try:
        created = db.create_project(name, slug, body.description, caller.subject, caller.email)
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"a project {slug!r} already exists")
    try:
        projectdb.provision(db.dsn(), created["pid"])
    except Exception:
        # A project without its database is a project every module fails on.
        # Better not to have made it.
        db.delete_project(created["pid"])
        raise HTTPException(status_code=503, detail="the project's database could not be made; nothing was created")
    return created
```

- [ ] **Step 8: Ship the template in the image and the dev mount.** In `platform/Dockerfile`, next to the line that copies `migrations`, add `COPY project-template /app/project-template`. In `docker-compose.development.yml`, under `platform.volumes`, add:

```yaml
      # what every new project database starts with, one file per module
      - ./platform/project-template:/app/project-template:ro,z
```

`TEMPLATE` resolves to `/app/project-template` inside the container, because `platform_service` sits in `/app`. That's the same way `MIGRATIONS` resolves.

- [ ] **Step 9: Run the tests.**

Run: `cd platform && uv run --extra dev pytest -v`
Expected: every test PASSES, including the existing membership and project tests.

- [ ] **Step 10: Restart the platform and check the existing project got its database.**

Run: `docker compose --env-file env.development -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build platform && sleep 5 && docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select datname from pg_database where datname like \$\$project\_%\$\$"'`
Expected: one row, `project_<hex>` for the one existing project. If it's missing, make one request first (`curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8100/api/projects` returns a redirect, so use `docker exec platform python -c "from platform_service import db; db.pool()"`), then rerun the query.

- [ ] **Step 11: Commit.**

```bash
git add platform/platform_service/projectdb.py platform/platform_service/migrate.py platform/platform_service/db.py platform/platform_service/app.py platform/project-template platform/tests platform/Dockerfile
git add -p docker-compose.development.yml   # only the platform volume hunk
git commit -m "A project is made with its own database, or not at all"
```

---

### Task 3: Controls' schema without a project column, as one baseline

**Files:**
- Modify: `apps/controls/prisma/schema.prisma` (model `Submission`)
- Delete: `apps/controls/prisma/migrations/20260601164609_init_checklist`, `20260622110000_add_catalogue_id`, `20260921230000_submission_belongs_to_a_project`, `20260922100000_the_project_link_is_named_project_id`, `20260922110000_one_naming_convention`
- Create: `apps/controls/prisma/migrations/20260923120000_project_database/migration.sql`

**Interfaces:**
- Produces: the Prisma `Submission` model has no `projectId`. One migration creates the whole controls schema in an empty project database. The old ones referenced `core.project`, which a project database doesn't have.

- [ ] **Step 1: Edit the schema.** In `prisma/schema.prisma`, delete from `model Submission` the comment block above `projectId`, the `projectId … @db.Uuid` line, and `@@index([projectId])`. Replace the `Checklist.catalogueId` comment with:

```prisma
  // Slug of the catalogue control this was installed from. Unique: this
  // database is one project, so a checklist is installed in it at most once.
```

- [ ] **Step 2: Replace the migration history with a baseline.**

```bash
cd apps/controls
git rm -r -q prisma/migrations/20260601164609_init_checklist prisma/migrations/20260622110000_add_catalogue_id prisma/migrations/20260921230000_submission_belongs_to_a_project prisma/migrations/20260922100000_the_project_link_is_named_project_id prisma/migrations/20260922110000_one_naming_convention
mkdir -p prisma/migrations/20260923120000_project_database
npx prisma migrate diff --from-empty --to-schema-datamodel prisma/schema.prisma --script > prisma/migrations/20260923120000_project_database/migration.sql
```

Expected: `migration.sql` contains `CREATE TABLE "checklist"`, `"checklist_question"`, `"source"`, `"submission"`, `"submission_answer"`, and the unique index on `"catalogueId"`. It contains no `project_id` and no `core.`.

Check: `grep -c "core\.\|project_id" prisma/migrations/20260923120000_project_database/migration.sql` prints `0`.

- [ ] **Step 3: Prove the baseline applies to an empty project database.**

```bash
PID=$(python3 -c "import uuid; print(uuid.uuid4())"); DB="project_$(echo $PID | tr -d -)"
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c 'create database $DB'"
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -c 'create schema controls; grant usage, create on schema controls to controls_rw; grant connect on database $DB to controls_rw'"
DATABASE_URL="postgresql://controls_rw:controls_rw@127.0.0.1:5432/$DB?schema=controls" npx prisma migrate deploy
docker exec postgres sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c 'drop database $DB with (force)'"
```

Expected: `1 migration found … All migrations have been successfully applied.`

- [ ] **Step 4: Commit** (inside `apps/controls`).

```bash
git add prisma/schema.prisma prisma/migrations
git commit -m "The database is the project: one baseline, and no project column"
```

The app doesn't build between this commit and Task 5. Tasks 3–5 go to one reviewer together.

---

### Task 4: One Prisma client per project database

**Files:**
- Create: `apps/controls/src/lib/projectDb.ts`
- Test: `apps/controls/test/unit/projectDb.test.ts`

**Interfaces:**
- Produces:
  - `projectDatabaseName(pid: string): string` (throws `NotAProject`)
  - `projectDatabaseUrl(pid: string, template?: string): string`
  - `prismaFor(pid: string, deps?: { migrate: (url: string) => Promise<void> }): Promise<PrismaClient>`
  - `migrateProjectDatabase(url: string): Promise<void>`
  - `class NotAProject extends Error`
  - Env `PROJECT_DATABASE_URL`, for example `postgresql://controls_rw:controls_rw@postgres:5432/{database}?schema=controls&connection_limit=2`

- [ ] **Step 1: Write the failing test.** Create `test/unit/projectDb.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  NotAProject,
  prismaFor,
  projectDatabaseName,
  projectDatabaseUrl,
} from "@/lib/projectDb";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const TEMPLATE = "postgresql://controls_rw:pw@postgres:5432/{database}?schema=controls";

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
      "postgresql://controls_rw:pw@postgres:5432/project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b?schema=controls",
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

  it("migrates a project's database once, however many requests arrive at once", async () => {
    const pid = "11111111-1111-4111-8111-111111111111";
    const migrate = vi.fn(() => new Promise<void>((r) => setTimeout(r, 20)));
    const [a, b] = await Promise.all([prismaFor(pid, { migrate }), prismaFor(pid, { migrate })]);
    expect(migrate).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });

  it("tries again after a migration that failed", async () => {
    const pid = "22222222-2222-4222-8222-222222222222";
    const migrate = vi.fn().mockRejectedValueOnce(new Error("db starting")).mockResolvedValue(undefined);
    await expect(prismaFor(pid, { migrate })).rejects.toThrow("db starting");
    await expect(prismaFor(pid, { migrate })).resolves.toBeDefined();
    expect(migrate).toHaveBeenCalledTimes(2);
  });

  it("gives two projects two clients", async () => {
    const migrate = vi.fn(async () => {});
    const a = await prismaFor("33333333-3333-4333-8333-333333333333", { migrate });
    const b = await prismaFor("44444444-4444-4444-8444-444444444444", { migrate });
    expect(a).not.toBe(b);
  });
});
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/controls && npx vitest run test/unit/projectDb.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/projectDb"`.

- [ ] **Step 3: Implement.** Create `src/lib/projectDb.ts`:

```ts
/**
 * The database of one project.
 *
 * Every project has a database of its own, made by the platform when the
 * project is made. This app keeps a project's checklists and submissions there
 * and nowhere else, so a query that forgets to filter still cannot reach
 * another project.
 *
 * The pid comes from the /p/{pid} path, which the middleware has already
 * checked with the platform. It is validated again here because it becomes
 * part of a connection string.
 */
import { PrismaClient } from "@prisma/client";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);
const PID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export class NotAProject extends Error {}

export function projectDatabaseName(pid: string): string {
  if (!PID.test(pid)) throw new NotAProject(`not a project id: ${JSON.stringify(pid)}`);
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
 * Requests that arrive together share one migration; one that failed is
 * forgotten, so the next request tries again.
 */
export async function prismaFor(
  pid: string,
  deps: { migrate: (url: string) => Promise<void> } = { migrate: migrateProjectDatabase },
): Promise<PrismaClient> {
  const url = projectDatabaseUrl(pid);
  let entry = open.get(url);
  if (!entry) {
    const ready = deps.migrate(url);
    entry = { client: new PrismaClient({ datasources: { db: { url } } }), ready };
    open.set(url, entry);
    ready.catch(() => open.delete(url));
  }
  await entry.ready;
  return entry.client;
}
```

- [ ] **Step 4: Run it.**

Run: `npx vitest run test/unit/projectDb.test.ts`
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit** (inside `apps/controls`).

```bash
git add src/lib/projectDb.ts test/unit/projectDb.test.ts
git commit -m "One client per project database, migrated on first use"
```

---

### Task 5: Every page reads its own project's database

**Files:**
- Modify (replace `import { prisma } from "@/lib/prisma"` with `prismaFor`):
  `src/lib/submissions.ts`,
  `src/app/p/[project]/page.tsx`,
  `src/app/p/[project]/checklists/page.tsx`,
  `src/app/p/[project]/checklists/[id]/fill/{page,actions}.ts(x)`,
  `src/app/p/[project]/checklists/[id]/review/{page,actions}.ts(x)` and `ReviewForm.tsx`,
  `src/app/p/[project]/submissions/archived/page.tsx`,
  `src/app/p/[project]/submissions/[id]/{page,actions}.ts(x)`,
  `src/app/p/[project]/submissions/[id]/report/route.ts`
- Move: `src/app/sources/` → `src/app/p/[project]/sources/` (`page.tsx`, `new/page.tsx`, `new/actions.ts`, `new/NewSourceForm.tsx`)
- Modify: `src/components/SiteHeader.tsx:36` (the Sources link goes inside the project)
- Delete: `src/lib/prisma.ts`, `src/app/api/catalogue/install/route.ts`, `src/app/api/catalogue/installed/route.ts`
- Modify: `env.development`, and `docker-compose.development.yml` (`controls-web`)
- Test: create `test/integration/project-database.test.ts`. Rewrite `test/integration/project-scope.test.ts` and `test/integration/submission-lifecycle.test.ts`.

**Interfaces:**
- Consumes: `prismaFor(pid)` (Task 4). The schema has no `projectId` (Task 3).
- Produces: `submissionsOfProject(project)`, `submissionOfProject(project, id)` and `archivedCountOfProject(project)` keep their signatures. `saveReviewedQuestions(project, checklistId, prev, formData)` and `createSource(project, prev, formData)` gain `project` as their first argument.

- [ ] **Step 1: Write the failing isolation test.** Create `test/integration/project-database.test.ts`:

```ts
import { describe, it, expect, beforeAll, afterAll, vi } from "vitest";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    const err = new Error("NEXT_REDIRECT") as Error & { redirectUrl: string };
    err.redirectUrl = url;
    throw err;
  },
}));

import { execSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { prismaFor, projectDatabaseName } from "@/lib/projectDb";
import { submitForm } from "@/app/p/[project]/checklists/[id]/fill/actions";
import { submissionsOfProject } from "@/lib/submissions";

// Two project databases, made the way the platform makes them, and dropped
// afterwards. Needs PROJECT_DATABASE_URL (pointing at 127.0.0.1) and
// PG_SUPERUSER_URL, a superuser DSN on the platform database used only to
// create and drop the two databases.
const hasDb = Boolean(process.env.PROJECT_DATABASE_URL && process.env.PG_SUPERUSER_URL);
const su = (sql: string, db = "platform") =>
  execSync(`psql "${process.env.PG_SUPERUSER_URL!.replace(/\/platform/, `/${db}`)}" -v ON_ERROR_STOP=1 -Atc "${sql}"`);

function makeProject(): string {
  const pid = randomUUID();
  const db = projectDatabaseName(pid);
  su(`create database ${db}`);
  su(`grant connect on database ${db} to controls_rw`, db);
  su(`create schema controls; grant usage, create on schema controls to controls_rw`, db);
  return pid;
}

describe.skipIf(!hasDb)("a project's controls live in its own database", () => {
  let a: string;
  let b: string;

  beforeAll(() => {
    a = makeProject();
    b = makeProject();
  }, 60_000);

  afterAll(() => {
    for (const pid of [a, b]) su(`drop database if exists ${projectDatabaseName(pid)} with (force)`);
  });

  it("a checklist in one project is not in the other", async () => {
    const dbA = await prismaFor(a);
    const dbB = await prismaFor(b);
    const source = await dbA.source.create({ data: { name: "S", slug: "s" } });
    await dbA.checklist.create({
      data: { title: "Only in A", sourceId: source.id, controlTopic: "T", questions: { create: [{ order: 1, text: "Q?" }] } },
    });
    expect(await dbA.checklist.count()).toBe(1);
    expect(await dbB.checklist.count()).toBe(0);
  }, 60_000);

  it("an answered checklist is listed only in its own project", async () => {
    const dbA = await prismaFor(a);
    const checklist = await dbA.checklist.findFirstOrThrow({ include: { questions: true } });
    const fd = new FormData();
    fd.set("label", "first go");
    fd.set(`answer_${checklist.questions[0].id}`, "yes");
    await submitForm(a, checklist.id, undefined, fd).catch(() => undefined); // redirects on success
    expect(await submissionsOfProject(a)).toHaveLength(1);
    expect(await submissionsOfProject(b)).toHaveLength(0);
  }, 60_000);

  it("a checklist id from one project is not found through the other", async () => {
    const dbA = await prismaFor(a);
    const checklist = await dbA.checklist.findFirstOrThrow();
    const fd = new FormData();
    fd.set("label", "sneaky");
    expect(await submitForm(b, checklist.id, undefined, fd)).toEqual({ error: "Checklist not found." });
  }, 60_000);
});
```

Check the form field name in `src/lib/checklistForm.ts` (`parseAnswers`) before running. If it isn't `answer_<questionId>`, use the prefix `parseAnswers` reads.

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/controls && PROJECT_DATABASE_URL='postgresql://controls_rw:controls_rw@127.0.0.1:5432/{database}?schema=controls&connection_limit=2' PG_SUPERUSER_URL="postgresql://$(grep ^POSTGRES_USER= ../../env.secrets | cut -d= -f2):$(grep ^POSTGRES_PASSWORD= ../../env.secrets | cut -d= -f2)@127.0.0.1:5432/platform" npx vitest run test/integration/project-database.test.ts`

Expected: the test file fails to compile or run. `submitForm` and `submissionsOfProject` still import the deleted global client, and they pass `projectId`, which no longer exists.

If `POSTGRES_USER`/`POSTGRES_PASSWORD` are not in `env.secrets`, find them in `env.development` the same way. Don't print them.

- [ ] **Step 3: Convert the data layer.** Apply one mechanical rule to every file listed above:
  1. Replace `import { prisma } from "@/lib/prisma";` with `import { prismaFor } from "@/lib/projectDb";`.
  2. In each exported function that already takes `project` (or gets it from `await params`), add `const prisma = await prismaFor(project);` as its first statement.
  3. Delete every `projectId: project` and `projectId: …` from `where` and `data` objects, and `projectId: true` from `select`s.
  4. Where a variable's `.projectId` built a URL (`inProject(sub.projectId)` in `submissions/[id]/actions.ts:64,82,126`), use `inProject(project)`.

`src/lib/submissions.ts` then reads:

```ts
/**
 * Answered checklists, read in the project's own database.
 *
 * The database is the project, so nothing here filters by project: there is
 * nothing of another project's in it to filter out.
 */
import { prismaFor } from "@/lib/projectDb";

export async function submissionsOfProject(project: string) {
  const prisma = await prismaFor(project);
  return prisma.submission.findMany({
    where: { archivedAt: null, nextVersion: { is: null } },
    orderBy: { updatedAt: "desc" },
    include: {
      checklist: {
        select: { title: true, controlTopic: true, source: { select: { id: true, name: true } } },
      },
      answers: { select: { score: true } },
      _count: { select: { answers: true } },
    },
  });
}

export async function submissionOfProject(project: string, id: string) {
  const prisma = await prismaFor(project);
  return prisma.submission.findUnique({
    where: { id },
    include: {
      checklist: { include: { questions: { orderBy: { order: "asc" } }, source: { select: { name: true } } } },
      answers: true,
    },
  });
}

export async function archivedCountOfProject(project: string) {
  const prisma = await prismaFor(project);
  return prisma.submission.count({ where: { archivedAt: { not: null } } });
}
```

`saveReviewedQuestions`: change the signature to `(project: string, checklistId: string, _prev: SaveState, formData: FormData)`. In `ReviewForm.tsx`, bind it the way `FillForm.tsx` binds `submitForm`: `saveReviewedQuestions.bind(null, project, checklistId)`. Pass `project` from `review/page.tsx` as a prop.

- [ ] **Step 4: Move sources inside the project.**

```bash
mkdir -p "src/app/p/[project]/sources"
git mv src/app/sources/page.tsx "src/app/p/[project]/sources/page.tsx"
git mv src/app/sources/new "src/app/p/[project]/sources/new"
```

In the moved files, apply the Step 3 rule. `createSource` becomes `(project: string, _prev: CreateState, formData: FormData)`, and `NewSourceForm` binds it with `createSource.bind(null, project)`. Every `redirect`/`revalidatePath` to `/sources` becomes `/p/${project}/sources`. In `SiteHeader.tsx:36`:

```tsx
          <a href={`${basePath}/p/${encodeURIComponent(project)}/sources`}>Sources</a>
```

Render the Sources link only when `project` is set: the header already receives `project` from `p/[project]/layout.tsx`.

- [ ] **Step 5: Remove the old global client and the unauthenticated install API.**

```bash
git rm -q src/lib/prisma.ts src/app/api/catalogue/install/route.ts src/app/api/catalogue/installed/route.ts
```

`src/lib/installChecklist.ts` stays: Task 7 uses it. It already takes a `PrismaClient` argument.

- [ ] **Step 6: Point the app at project databases.** In `env.development`, replace the `DATABASE_URL=` line and the comment block above it with:

```ini
# Every project has its own database, made by the platform. {database} is
# filled with that project's, from the /p/{pid} path; see src/lib/projectDb.ts.
PROJECT_DATABASE_URL=postgresql://controls_rw:controls_rw@postgres:5432/{database}?schema=controls&connection_limit=2
```

The controls app no longer reads the old shared database at all: its `migrate` service changes in Task 6.

- [ ] **Step 7: Rewrite the two old integration suites onto `prismaFor`.** In `test/integration/project-scope.test.ts` and `submission-lifecycle.test.ts`:
  - Replace the `import { prisma }` with the `makeProject()` / `su()` helpers from Step 1, copied in.
  - `hasDb` becomes the same check as in Step 1.
  - In `beforeAll`, make the project database(s) and get `const prisma = await prismaFor(project)`.
  - Delete every `projectId` field.
  - Delete the `core.project` insert/delete, because the platform tables are no longer involved.

  `project-scope.test.ts` asserted "a submission for a project the database doesn't have is refused". That's now "a submission through a pid with no database fails". Assert that `submitForm(randomUUID(), …)` rejects.

- [ ] **Step 8: Type-check, then run everything.**

Run: `npx tsc --noEmit && npx vitest run` (with the two env vars from Step 2)
Expected: no type errors. All unit and integration tests PASS, including the three new isolation tests.

Also run `grep -rn "@/lib/prisma\|projectId" src test`. Expected: no output.

- [ ] **Step 9: Commit** (inside `apps/controls`).

```bash
git add -A src test env.development
git commit -m "Every page reads its own project's database, and sources move into the project"
```

---

### Task 6: Migrate every project database at start, and stop seeding

**Files:**
- Create: `apps/controls/scripts/migrate-projects.mjs`
- Modify: `docker-compose.development.yml` (the `controls-migrate` command at line 166, and the `controls-web` env)

**Interfaces:**
- Consumes: `PROJECT_DATABASE_URL`, and the `project_%` databases made by the platform (Task 2).
- Produces: after `controls-migrate` exits 0, every existing project database is at the controls baseline. The 17 example checklists are no longer loaded anywhere.

- [ ] **Step 1: Write the script.** Create `scripts/migrate-projects.mjs`:

```js
// Bring every project database to this app's schema, then exit.
//
// Runs as the controls-migrate service at start. A project made later is
// migrated by the web app the first time it is opened (src/lib/projectDb.ts),
// so this is for schema changes reaching the projects that already exist.
import { execFileSync } from "node:child_process";
import pg from "pg";

const template = process.env.PROJECT_DATABASE_URL ?? "";
if (!template.includes("{database}")) {
  console.error("PROJECT_DATABASE_URL must contain {database}");
  process.exit(2);
}
const catalog = new pg.Client({ connectionString: template.replace("{database}", "postgres").split("?")[0] });
await catalog.connect();
const { rows } = await catalog.query(
  "select datname from pg_database where datname ~ '^project_[0-9a-f]{32}$' order by datname",
);
await catalog.end();

for (const { datname } of rows) {
  console.log(`[controls] migrating ${datname}`);
  execFileSync("npx", ["prisma", "migrate", "deploy"], {
    stdio: "inherit",
    env: { ...process.env, DATABASE_URL: template.replace("{database}", datname) },
  });
}
console.log(`[controls] ${rows.length} project database(s) up to date`);
```

`controls_rw` can connect to the `postgres` maintenance database (PUBLIC has `CONNECT` there by default) and read `pg_database`. If `pg` isn't in `package.json`, add it with `npm install pg@^8` and commit the lockfile with it.

- [ ] **Step 2: Change the migrate service.** In `docker-compose.development.yml`, replace the `controls-migrate` `command` with:

```yaml
    # Every project database, not one shared one. No seed: a project's
    # checklists are the ones installed into it from the catalogue.
    command: >
      sh -c "until node scripts/migrate-projects.mjs; do echo '[controls] waiting for postgres'; sleep 2; done"
```

Give `controls-migrate` and `controls-web` `PROJECT_DATABASE_URL` through their existing `env_file: apps/controls/env.development`, which Task 5 already updated. Add `platform` to `controls-migrate`'s `depends_on`, so the existing projects have their databases before it lists them. Remove the `DATABASE_URL` override from both services if one is set there.

- [ ] **Step 3: Rebuild and check.**

Run: `docker compose --env-file env.development -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build controls-migrate controls-web && docker wait controls-migrate && docker logs controls-migrate 2>&1 | tail -3`
Expected: `0`, then `[controls] migrating project_…` and `[controls] 1 project database(s) up to date`.

Then open http://localhost/controls/p/<the project's pid>/checklists in a browser. Expected: the library loads, is empty, and shows no seeded checklists.

- [ ] **Step 4: Commit** (the script inside `apps/controls`; the compose hunk in the root with `git add -p`).

```bash
(cd apps/controls && git add scripts/migrate-projects.mjs package.json package-lock.json && git commit -m "Migrate every project database at start, and seed none")
git add -p docker-compose.development.yml   # only the controls-migrate hunk
git commit -m "Controls migrates project databases, not the shared one"
```

---

### Task 7: The catalogue exports a control, and controls installs it into one project

**Files:**
- Create: `apps/catalogue/backend/controls_export.py` (ported), `apps/catalogue/backend/controls_bridge.py`
- Modify: `apps/catalogue/backend/main_api.py:59` (include the router)
- Test: `apps/catalogue/backend/tests/test_controls_export.py`
- Create: `apps/controls/src/lib/cataloguePackage.ts`, `apps/controls/src/app/p/[project]/install/{page.tsx,InstallForm.tsx,actions.ts}`
- Modify: `apps/controls/src/lib/installChecklist.ts` (already-installed is a no-op)
- Test: `apps/controls/test/unit/cataloguePackage.test.ts`, `apps/controls/test/integration/install.test.ts`
- Modify: `docker-compose.development.yml` (`controls-web` gets `CATALOGUE_URL` and `CATALOGUE_TOKEN`)

**Interfaces:**
- Produces (catalogue): `GET /control/{slug}/export` → `{meta: {...}, questions: [...]}` in the `InstallPackage` shape of `src/lib/installChecklist.ts:9`. 404 when the slug is unknown or not a control. It sits behind `require_bridge_token`, like `install-info`: open when `CATALOGUE_BRIDGE_TOKEN` is unset, otherwise it needs `Authorization: Bearer <token>`. That is how a platform reaches the online catalogue server-to-server.
- Produces (controls):
  - `fetchCataloguePackage(slug: string, opts?: { baseUrl?: string; fetchImpl?: typeof fetch }): Promise<{ ok: true; pkg: unknown } | { ok: false; reason: string }>`
  - `installChecklist(prisma, pkg)` returns `{ checklistId, catalogueId, created: boolean }`. When the `catalogueId` is already present, `created` is `false` and nothing is written.
  - The page `/p/{pid}/install?slug={slug}`: GET previews, POST (server action) installs.

- [ ] **Step 1: Write the catalogue's failing test.** Create `backend/tests/test_controls_export.py`:

```python
"""A catalogue control, served as the package the controls app installs."""
from types import SimpleNamespace

import controls_export as ce


def _q(order, text, article=None, category=None):
    return SimpleNamespace(order=order, text=text, article=article, category=category)


def _control(metadata=None, questions=None, **tool):
    md = dict(provider="AESIA", link="https://aesia.example/guides", control_topic="Accuracy",
              country_ids=[], regulation_ids=[], source_updated_at=None)
    md.update(metadata or {})
    base = dict(slug="accuracy-checklist", name="Accuracy_Checklist", description="Accuracy checklist by AESIA")
    base.update(tool)
    return SimpleNamespace(metadata=SimpleNamespace(**md), questions=questions or [], **base)


def test_mapping_carries_every_field_and_orders_questions():
    pkg = ce.build_checklist_package(_control(questions=[_q(2, "second", "Article 15", "MG02"), _q(1, "first", "Article 15", "MG01")]))
    assert pkg["meta"] == {
        "catalogueId": "accuracy-checklist", "title": "Accuracy_Checklist", "sourceName": "AESIA",
        "sourceUrl": "https://aesia.example/guides", "controlTopic": "Accuracy",
        "description": "Accuracy checklist by AESIA", "countryIds": [], "regulationIds": ["ai-act"],
        "sourceUpdatedAt": None,
    }
    assert pkg["questions"] == [
        {"text": "first", "article": "Article 15", "category": "MG01"},
        {"text": "second", "article": "Article 15", "category": "MG02"},
    ]


def test_control_topic_falls_back_to_the_name():
    assert ce.build_checklist_package(_control(metadata={"control_topic": "  "}))["meta"]["controlTopic"] == "Accuracy_Checklist"


def test_a_seeded_control_is_exported(client, seed_files):
    slug = seed_files["controls"][0]["slug"]
    response = client.get(f"/control/{slug}/export")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["catalogueId"] == slug
    assert len(body["questions"]) > 0


def test_a_test_is_not_a_control(client, seed_files):
    assert client.get(f"/control/{seed_files['tools'][0]['slug']}/export").status_code == 404


def test_an_unknown_slug_is_404(client):
    assert client.get("/control/no-such-control/export").status_code == 404


def test_the_hosted_catalogue_asks_for_its_bridge_token(monkeypatch, client, seed_files):
    slug = seed_files["controls"][0]["slug"]
    monkeypatch.setenv("CATALOGUE_BRIDGE_TOKEN", "s3cret-for-tests")
    assert client.get(f"/control/{slug}/export").status_code == 401
    ok = client.get(f"/control/{slug}/export", headers={"Authorization": "Bearer s3cret-for-tests"})
    assert ok.status_code == 200
```

If `seed_files["tools"][0]` happens to carry the `control` tag, pick the first tool whose `kind(tool) != "control"`, using the `kind` helper in `tests/conftest.py:83`.

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/catalogue/backend && uv run pytest tests/test_controls_export.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'controls_export'`.

- [ ] **Step 3: Port the exporter and add the route.**

```bash
cd apps/catalogue
git show origin/feat/catalogue-controls-sync:backend/controls_export.py > backend/controls_export.py
```

In `backend/controls_export.py`, replace `is_control` with the version below, since `Tool.tags` is a relationship on this branch:

```python
def is_control(tool) -> bool:
    """A catalogue entry is a control iff it carries the 'control' type tag."""
    return any(getattr(t, "slug", None) == CONTROL_TAG_SLUG for t in (tool.tags or []))
```

Create `backend/controls_bridge.py`:

```python
"""Catalogue -> controls: a control, as the package the controls app installs.

Read-only. The controls app of a platform fetches this server-side when a
project installs a control, and stores it in that project's own database. The
catalogue is one, hosted online, and knows no projects: which project gets it
is chosen on the platform, in controls.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import controls_export
from catalogue_bridge import require_bridge_token
from database import get_db
from sql_alchemy import Tool

# Same door as install-info: a platform calls this server-to-server, with the
# bridge token when the hosted catalogue sets one.
router = APIRouter(tags=["controls-bridge"], dependencies=[Depends(require_bridge_token)])


@router.get("/control/{slug}/export")
def export_control(slug: str, database: Session = Depends(get_db)) -> dict:
    tool = database.query(Tool).filter(Tool.slug == slug).first()
    if tool is None or not controls_export.is_control(tool):
        raise HTTPException(status_code=404, detail=f"no control {slug!r}")
    return controls_export.build_checklist_package(tool)
```

In `main_api.py`, next to `app.include_router(catalogue_bridge_router)` (line 59):

```python
from controls_bridge import router as controls_bridge_router  # noqa: E402
app.include_router(controls_bridge_router)
```

- [ ] **Step 4: Run the catalogue suite.**

Run: `uv run pytest -q -p no:cacheprovider`
Expected: all PASS, including `test_write_needs_admin.py`, which enumerates routes. The new route is a GET, so it needs no entry in `OPEN_WRITES`.

- [ ] **Step 5: Commit** (inside `apps/catalogue`).

```bash
git add backend/controls_export.py backend/controls_bridge.py backend/main_api.py backend/tests/test_controls_export.py
git commit -m "Serve a control as the package controls installs"
```

- [ ] **Step 6: Write controls' failing tests.** Create `apps/controls/test/unit/cataloguePackage.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { fetchCataloguePackage } from "@/lib/cataloguePackage";

const ok = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

describe("fetchCataloguePackage", () => {
  it("asks the catalogue for the control's package", async () => {
    const fetchImpl = ok({ meta: { catalogueId: "accuracy-checklist" }, questions: [] });
    const got = await fetchCataloguePackage("accuracy-checklist", { baseUrl: "http://cat:8000/", fetchImpl });
    expect(fetchImpl).toHaveBeenCalledWith("http://cat:8000/control/accuracy-checklist/export", expect.anything());
    expect(got).toEqual({ ok: true, pkg: { meta: { catalogueId: "accuracy-checklist" }, questions: [] } });
  });

  it("says so when the catalogue has no such control", async () => {
    const got = await fetchCataloguePackage("nope", { baseUrl: "http://cat:8000", fetchImpl: ok({ detail: "x" }, 404) });
    expect(got).toEqual({ ok: false, reason: "The catalogue has no control called “nope”." });
  });

  it("says so when the catalogue cannot be reached", async () => {
    const fetchImpl = vi.fn(async () => { throw new TypeError("fetch failed"); });
    const got = await fetchCataloguePackage("x", { baseUrl: "http://cat:8000", fetchImpl });
    expect(got).toEqual({ ok: false, reason: "The catalogue is not answering. Nothing was installed." });
  });

  it("sends the bridge token when there is one, and nothing when there is not", async () => {
    const fetchImpl = ok({ meta: {}, questions: [] });
    await fetchCataloguePackage("x", { baseUrl: "https://catalogue.example", token: "t0k", fetchImpl });
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({ headers: { Authorization: "Bearer t0k" } });
    await fetchCataloguePackage("x", { baseUrl: "https://catalogue.example", token: "", fetchImpl });
    expect(fetchImpl.mock.calls[1][1]).toMatchObject({ headers: {} });
  });

  it("says the catalogue refused this platform when the token is wrong", async () => {
    const got = await fetchCataloguePackage("x", { baseUrl: "https://catalogue.example", token: "bad", fetchImpl: ok({}, 401) });
    expect(got).toEqual({ ok: false, reason: "The catalogue refused this platform: check CATALOGUE_TOKEN. Nothing was installed." });
  });

  it.each(["", "../admin", "a b", "x/y"])("refuses the slug %j without asking", async (slug) => {
    const fetchImpl = vi.fn();
    expect((await fetchCataloguePackage(slug, { baseUrl: "http://cat:8000", fetchImpl })).ok).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
```

Create `apps/controls/test/integration/install.test.ts`. Copy the `hasDb`, `su`, `makeProject` helpers and the `next/*` mocks from `test/integration/project-database.test.ts`, then:

```ts
import { installChecklist } from "@/lib/installChecklist";
import { prismaFor } from "@/lib/projectDb";

const pkg = {
  meta: { catalogueId: "accuracy-checklist", title: "Accuracy", sourceName: "AESIA", controlTopic: "Accuracy" },
  questions: [{ text: "first" }, { text: "second" }],
};

describe.skipIf(!hasDb)("installing a control into a project", () => {
  let a: string;
  let b: string;
  beforeAll(() => { a = makeProject(); b = makeProject(); }, 60_000);
  afterAll(() => { for (const pid of [a, b]) su(`drop database if exists ${projectDatabaseName(pid)} with (force)`); });

  it("puts it in that project only", async () => {
    const result = await installChecklist(await prismaFor(a), pkg);
    expect(result.created).toBe(true);
    expect(await (await prismaFor(a)).checklist.count()).toBe(1);
    expect(await (await prismaFor(b)).checklist.count()).toBe(0);
  }, 60_000);

  it("installing it again changes nothing and keeps the answers", async () => {
    const db = await prismaFor(a);
    const checklist = await db.checklist.findFirstOrThrow({ include: { questions: true } });
    const sub = await db.submission.create({
      data: { checklistId: checklist.id, label: "answered", answers: { create: [{ questionId: checklist.questions[0].id, score: 4 }] } },
    });
    const again = await installChecklist(db, { ...pkg, questions: [{ text: "replaced" }] });
    expect(again).toEqual({ checklistId: checklist.id, catalogueId: "accuracy-checklist", created: false });
    expect(await db.submissionAnswer.count({ where: { submissionId: sub.id } })).toBe(1);
    expect((await db.question.findMany({ where: { checklistId: checklist.id } })).map((q) => q.text)).toEqual(["first", "second"]);
  }, 60_000);

  it("the other project can install the same control for itself", async () => {
    expect((await installChecklist(await prismaFor(b), pkg)).created).toBe(true);
  }, 60_000);
});
```

- [ ] **Step 7: Run them and watch them fail.**

Run (with the env vars from Task 5 Step 2): `cd apps/controls && npx vitest run test/unit/cataloguePackage.test.ts test/integration/install.test.ts`
Expected: the unit file fails, `Failed to resolve import "@/lib/cataloguePackage"`. The integration test "installing it again changes nothing" FAILS: the current code replaces the questions and deletes the answer.

- [ ] **Step 8: Implement `fetchCataloguePackage`.** Create `src/lib/cataloguePackage.ts`:

```ts
/**
 * A control from the catalogue, as the package installChecklist stores.
 *
 * There is one catalogue, hosted online. It is fetched server-side, never by
 * the browser: the page the button sits on only ever sends the slug.
 */
const SLUG = /^[a-z0-9]+(?:[-_][a-z0-9]+)*$/i;

export type Fetched = { ok: true; pkg: unknown } | { ok: false; reason: string };

export async function fetchCataloguePackage(
  slug: string,
  opts: { baseUrl?: string; token?: string; fetchImpl?: typeof fetch } = {},
): Promise<Fetched> {
  if (!SLUG.test(slug)) return { ok: false, reason: "That is not the name of a catalogue control." };
  const base = (opts.baseUrl ?? process.env.CATALOGUE_URL ?? "").replace(/\/+$/, "");
  const token = opts.token ?? process.env.CATALOGUE_TOKEN ?? "";
  if (!base) return { ok: false, reason: "This install does not know where the catalogue is." };
  let response: Response;
  try {
    response = await (opts.fetchImpl ?? fetch)(`${base}/control/${encodeURIComponent(slug)}/export`, {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    return { ok: false, reason: "The catalogue is not answering. Nothing was installed." };
  }
  if (response.status === 404) return { ok: false, reason: `The catalogue has no control called “${slug}”.` };
  if (response.status === 401 || response.status === 403) {
    return { ok: false, reason: "The catalogue refused this platform: check CATALOGUE_TOKEN. Nothing was installed." };
  }
  if (!response.ok) return { ok: false, reason: "The catalogue is not answering. Nothing was installed." };
  return { ok: true, pkg: await response.json() };
}
```

- [ ] **Step 9: Make re-install a no-op.** In `src/lib/installChecklist.ts`, replace the part of `installChecklist` from `const source = await prisma.source.upsert(` to the end of the function with:

```ts
  // Already in this project: leave it exactly as it is. Replacing its questions
  // would cascade into the answers already given to them.
  const existing = await prisma.checklist.findUnique({
    where: { catalogueId: data.checklist.catalogueId },
    select: { id: true },
  });
  if (existing) return { checklistId: existing.id, catalogueId: data.checklist.catalogueId, created: false };

  const checklistId = await prisma.$transaction(async (tx) => {
    const source = await tx.source.upsert({
      where: { name: data.source.name },
      update: { url: data.source.url ?? undefined },
      create: { name: data.source.name, slug: slugify(data.source.name), url: data.source.url },
    });
    const created = await tx.checklist.create({
      data: {
        ...data.checklist,
        sourceId: source.id,
        questions: { create: data.questions },
      },
      select: { id: true },
    });
    return created.id;
  });

  return { checklistId, catalogueId: data.checklist.catalogueId, created: true };
```

Update the header comment's sentence about re-install to: "Installing a control the project already has changes nothing."

- [ ] **Step 10: The install page.** Create `src/app/p/[project]/install/actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";
import { fetchCataloguePackage } from "@/lib/cataloguePackage";
import { installChecklist } from "@/lib/installChecklist";
import { prismaFor } from "@/lib/projectDb";

export type InstallState = { error?: string } | undefined;

/** A POST, so the middleware has already asked the platform for a writer. */
export async function installFromCatalogue(project: string, slug: string, _prev: InstallState): Promise<InstallState> {
  const fetched = await fetchCataloguePackage(slug);
  if (!fetched.ok) return { error: fetched.reason };
  let result;
  try {
    result = await installChecklist(await prismaFor(project), fetched.pkg);
  } catch (err) {
    return { error: `The catalogue sent a control this app cannot read: ${(err as Error).message}` };
  }
  redirect(`/p/${encodeURIComponent(project)}/checklists/${result.checklistId}/fill?installed=${result.created ? "new" : "already"}`);
}
```

Create `src/app/p/[project]/install/InstallForm.tsx`:

```tsx
"use client";

import { useActionState } from "react";
import { installFromCatalogue, type InstallState } from "./actions";

export default function InstallForm({ project, slug }: { project: string; slug: string }) {
  const [state, formAction, pending] = useActionState<InstallState, FormData>(
    installFromCatalogue.bind(null, project, slug),
    undefined,
  );
  return (
    <form action={formAction} className="qf-form">
      {state?.error && <div className="error">{state.error}</div>}
      <button type="submit" className="btn btn-primary" disabled={pending}>
        {pending ? "Installing…" : "Install into this project"}
      </button>
    </form>
  );
}
```

Match `className`s to whatever `FillForm.tsx`'s submit button uses. Check its bottom lines.

Create `src/app/p/[project]/install/page.tsx`:

```tsx
import Link from "next/link";
import { fetchCataloguePackage } from "@/lib/cataloguePackage";
import { parseInstallPackage } from "@/lib/installChecklist";
import { prismaFor } from "@/lib/projectDb";
import InstallForm from "./InstallForm";

/** What installing this control would add to this project. A GET, so any
 *  member may look; the button is a server action, so only a writer may press it. */
export default async function InstallPage({
  params,
  searchParams,
}: {
  params: Promise<{ project: string }>;
  searchParams: Promise<{ slug?: string }>;
}) {
  const { project } = await params;
  const slug = (await searchParams).slug?.trim() ?? "";
  const library = `/p/${encodeURIComponent(project)}/checklists`;

  const fetched = await fetchCataloguePackage(slug);
  if (!fetched.ok) {
    return (
      <main className="page">
        <header className="page-header"><h1>Install a control</h1></header>
        <div className="error">{fetched.reason}</div>
        <p><Link href={library}>Back to this project&apos;s checklists</Link></p>
      </main>
    );
  }

  let parsed;
  try {
    parsed = parseInstallPackage(fetched.pkg);
  } catch (err) {
    return (
      <main className="page">
        <header className="page-header"><h1>Install a control</h1></header>
        <div className="error">The catalogue sent a control this app cannot read: {(err as Error).message}</div>
        <p><Link href={library}>Back to this project&apos;s checklists</Link></p>
      </main>
    );
  }

  const prisma = await prismaFor(project);
  const already = await prisma.checklist.findUnique({
    where: { catalogueId: parsed.checklist.catalogueId },
    select: { id: true },
  });

  return (
    <main className="page">
      <header className="page-header">
        <h1>{parsed.checklist.title}</h1>
        <p>
          <strong>{parsed.source.name}</strong> · {parsed.checklist.controlTopic} ·{" "}
          {parsed.questions.length} questions
        </p>
        {parsed.checklist.description && <p>{parsed.checklist.description}</p>}
      </header>
      {already ? (
        <p>
          Already installed in this project.{" "}
          <Link href={`${library}/${already.id}/fill`}>Open it</Link>
        </p>
      ) : (
        <InstallForm project={project} slug={slug} />
      )}
    </main>
  );
}
```

In `checklists/[id]/fill/page.tsx`, add `searchParams: Promise<{ installed?: string }>` to the props. After `const { project, id } = await params;` add `const installed = (await searchParams).installed;`. As the first child of `<header className="page-header">`, add:

```tsx
        {installed === "new" && <p className="notice">Installed from the catalogue.</p>}
        {installed === "already" && <p className="notice">This project already had it; nothing changed.</p>}
```

If `globals.css` has no `.notice`, use the class the submissions page uses for its success banner (`grep -rn "className=\"success\|notice\|banner" src/app`).

- [ ] **Step 11: Give controls the catalogue's address.** In `docker-compose.development.yml`, under `controls-web.environment`, add:

```yaml
      # The catalogue: one, hosted online. In this dev stack its local copy
      # stands in for it. Server-side only: the install page fetches a control's
      # package here.
      CATALOGUE_URL: ${CATALOGUE_URL:-http://catalogue-backend:8000}
      # The hosted catalogue's bridge token, when it sets one. Empty locally.
      CATALOGUE_TOKEN: ${CATALOGUE_BRIDGE_TOKEN:-}
```

- [ ] **Step 12: Run controls' tests.**

Run: `npx tsc --noEmit && npx vitest run` (with the env vars)
Expected: all PASS.

- [ ] **Step 13: Commit.**

```bash
(cd apps/controls && git add src/lib/cataloguePackage.ts src/lib/installChecklist.ts "src/app/p/[project]/install" "src/app/p/[project]/checklists/[id]/fill/page.tsx" test && git commit -m "Install a control from the catalogue into this project, once")
git add -p docker-compose.development.yml   # only the CATALOGUE_URL / CATALOGUE_TOKEN hunk
git commit -m "Controls can reach the catalogue from the server"
```

---

### Task 8: Choose the project to install into

**Files:**
- Create: `apps/controls/src/lib/writableProjects.ts`
- Create: `apps/controls/src/app/install/page.tsx`, `apps/controls/src/app/install/actions.ts`
- Test: `apps/controls/test/unit/writableProjects.test.ts`, `apps/controls/test/unit/chooseProject.test.ts`

**Interfaces:**
- Consumes: the platform's `GET /projects`, which returns the caller's projects with `role`, or every project without `role` for an admin (`platform/platform_service/app.py:88`). `callerToken()` (`src/lib/access/callerToken.ts`). The page `/p/{pid}/install?slug=…` (Task 7).
- Produces:
  - `writableProjects(token: string | null, opts: { platformUrl: string; fetchImpl?: typeof fetch }): Promise<ProjectChoice[] | null>`, where `type ProjectChoice = { pid: string; name: string }`. `null` means the platform did not answer.
  - `chooseProject(slug: string, _prev: ChooseState, formData: FormData): Promise<ChooseState>`, which redirects to `/p/{pid}/install?slug={slug}`.
  - The page `/install?slug={slug}&project={pid?}`. It's the one address the catalogue links to (Task 9). `project` only preselects.

The chooser is outside `/p/`, so the middleware doesn't check it. It only reads the caller's own project list, and the project page it sends them to is checked as usual. Listing a project here gives no access to it.

- [ ] **Step 1: Write the failing tests.** Create `test/unit/writableProjects.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { writableProjects } from "@/lib/writableProjects";

const reply = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const C = "33333333-3333-4333-8333-333333333333";

describe("writableProjects", () => {
  it("lists the projects this person may change, and not the ones they may only read", async () => {
    const fetchImpl = reply([
      { pid: A, name: "Alpha", role: "owner" },
      { pid: B, name: "Beta", role: "viewer" },
      { pid: C, name: "Gamma", role: "editor" },
    ]);
    const got = await writableProjects("tok", { platformUrl: "http://platform:8000/", fetchImpl });
    expect(fetchImpl).toHaveBeenCalledWith("http://platform:8000/projects", expect.objectContaining({ headers: { Authorization: "Bearer tok" } }));
    expect(got).toEqual([{ pid: A, name: "Alpha" }, { pid: C, name: "Gamma" }]);
  });

  it("gives an admin every project: the platform lists them without a role", async () => {
    const got = await writableProjects("tok", { platformUrl: "http://p", fetchImpl: reply([{ pid: A, name: "Alpha" }]) });
    expect(got).toEqual([{ pid: A, name: "Alpha" }]);
  });

  it("is null when the platform does not answer, so nothing is guessed", async () => {
    expect(await writableProjects("tok", { platformUrl: "http://p", fetchImpl: reply({}, 503) })).toBeNull();
    const down = vi.fn(async () => { throw new TypeError("fetch failed"); });
    expect(await writableProjects("tok", { platformUrl: "http://p", fetchImpl: down })).toBeNull();
    expect(await writableProjects("tok", { platformUrl: "", fetchImpl: reply([]) })).toBeNull();
  });
});
```

Create `test/unit/chooseProject.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    const err = new Error("NEXT_REDIRECT") as Error & { redirectUrl: string };
    err.redirectUrl = url;
    throw err;
  },
}));

import { chooseProject } from "@/app/install/actions";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const form = (project: string) => { const fd = new FormData(); fd.set("project", project); return fd; };

describe("chooseProject", () => {
  it("goes to that project's install page for this control", async () => {
    await expect(chooseProject("accuracy-checklist", undefined, form(PID))).rejects.toMatchObject({
      redirectUrl: `/p/${PID}/install?slug=accuracy-checklist`,
    });
  });

  it.each(["", "abc", "../admin"])("refuses %j as a project", async (bad) => {
    expect(await chooseProject("accuracy-checklist", undefined, form(bad))).toEqual({ error: "Choose a project." });
  });
});
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/controls && npx vitest run test/unit/writableProjects.test.ts test/unit/chooseProject.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/writableProjects"` and `"@/app/install/actions"`.

- [ ] **Step 3: Implement.** Create `src/lib/writableProjects.ts`:

```ts
/**
 * The projects this person may install into: the ones they may change.
 *
 * Asked of the platform, which is the one place that knows who is in what.
 * An admin's list comes without roles, because an admin may act on every
 * project.
 */
export type ProjectChoice = { pid: string; name: string };

const WRITERS = new Set(["editor", "owner"]);

export async function writableProjects(
  token: string | null,
  opts: { platformUrl: string; fetchImpl?: typeof fetch },
): Promise<ProjectChoice[] | null> {
  const platformUrl = opts.platformUrl.replace(/\/+$/, "");
  if (!platformUrl) return null;
  try {
    const response = await (opts.fetchImpl ?? fetch)(`${platformUrl}/projects`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
    if (!response.ok) return null;
    const rows = (await response.json()) as Array<{ pid: string; name: string; role?: string }>;
    return rows
      .filter((r) => r.role === undefined || WRITERS.has(r.role))
      .map((r) => ({ pid: r.pid, name: r.name }));
  } catch {
    return null;
  }
}
```

Create `src/app/install/actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";

const PID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ChooseState = { error?: string } | undefined;

/** Only a redirect. The project page it leads to asks the platform whether this
 *  person may change it, as every project page does. */
export async function chooseProject(slug: string, _prev: ChooseState, formData: FormData): Promise<ChooseState> {
  const project = String(formData.get("project") ?? "");
  if (!PID.test(project)) return { error: "Choose a project." };
  redirect(`/p/${encodeURIComponent(project)}/install?slug=${encodeURIComponent(slug)}`);
}
```

Create `src/app/install/ChooseForm.tsx`:

```tsx
"use client";

import { useActionState } from "react";
import { chooseProject, type ChooseState } from "./actions";
import type { ProjectChoice } from "@/lib/writableProjects";

export default function ChooseForm({ slug, projects, preselect }: { slug: string; projects: ProjectChoice[]; preselect: string | null }) {
  const [state, formAction, pending] = useActionState<ChooseState, FormData>(chooseProject.bind(null, slug), undefined);
  return (
    <form action={formAction} className="qf-form">
      {state?.error && <div className="error">{state.error}</div>}
      <label>
        Install into
        <select name="project" defaultValue={preselect ?? projects[0].pid}>
          {projects.map((p) => <option key={p.pid} value={p.pid}>{p.name}</option>)}
        </select>
      </label>
      <button type="submit" className="btn btn-primary" disabled={pending}>Continue</button>
    </form>
  );
}
```

Create `src/app/install/page.tsx`:

```tsx
import { callerToken } from "@/lib/access/callerToken";
import { writableProjects } from "@/lib/writableProjects";
import ChooseForm from "./ChooseForm";

/** The one address the catalogue links to. The catalogue is one, hosted
 *  online, and knows no projects: which one gets the control is chosen here. */
export default async function ChoosePage({ searchParams }: { searchParams: Promise<{ slug?: string; project?: string }> }) {
  const sp = await searchParams;
  const slug = sp.slug?.trim() ?? "";
  const projects = await writableProjects(await callerToken(), { platformUrl: process.env.PLATFORM_URL ?? "" });
  const launcher = process.env.LAUNCHER_URL ?? "/";

  let body: React.ReactNode;
  if (!slug) body = <div className="error">No control was named. Start from the catalogue.</div>;
  else if (projects === null) body = <div className="error">The platform is not answering, so your projects cannot be listed. Nothing was installed.</div>;
  else if (projects.length === 0) {
    body = (
      <p>
        You cannot change any project, so there is none to install into. An owner of a project can make you an
        editor of it, or you can <a href={launcher}>create a project</a>.
      </p>
    );
  } else {
    const preselect = projects.some((p) => p.pid === sp.project) ? sp.project! : null;
    body = <ChooseForm slug={slug} projects={projects} preselect={preselect} />;
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Install a control</h1>
        {slug && <p>From the catalogue: <strong>{slug}</strong></p>}
      </header>
      {body}
    </main>
  );
}
```

`PLATFORM_URL` and `LAUNCHER_URL` are already in the controls environment (`docker-compose.development.yml:186`, `env.development`). A `project` that isn't in the caller's writable list is ignored rather than preselected.

- [ ] **Step 4: Run the tests.**

Run: `npx tsc --noEmit && npx vitest run test/unit/writableProjects.test.ts test/unit/chooseProject.test.ts`
Expected: all PASS.

- [ ] **Step 5: Commit** (inside `apps/controls`).

```bash
git add src/lib/writableProjects.ts src/app/install test/unit/writableProjects.test.ts test/unit/chooseProject.test.ts
git commit -m "Choose which project a control from the catalogue goes into"
```

---

### Task 9: The catalogue's button, and the launcher tells it where this platform is

**Files:**
- Modify: `homepage/project.html` (the handshake payload, around line 503)
- Modify: `apps/catalogue/frontend/src/crossSite/connect.ts` (`HandshakePayload`)
- Create: `apps/catalogue/frontend/src/crossSite/controlsInstall.ts`, `apps/catalogue/frontend/src/crossSite/controlsInstall.test.ts`
- Modify: `apps/catalogue/frontend/src/components/catalogue/ToolDetailModal.tsx` (actions row, line 616)

**Interfaces:**
- Consumes: the chooser `/install?slug=…&project=…` (Task 8).
- Produces: `HandshakePayload` gains `controls?: string` (this platform's controls address) and `project?: string` (the pid it was opened from, used only to preselect). `controlsInstallUrl(payload: HandshakePayload | null, slug: string): string | null`.

The catalogue is one, hosted online, and serves many platforms. It learns *which platform* to send an install to from the handshake, the same way the engine's plugin install learns `url`. The platform's chooser then decides *which project*.

- [ ] **Step 1: Write the failing test.** Create `frontend/src/crossSite/controlsInstall.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { controlsInstallUrl } from "./controlsInstall";

const PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b";
const payload = { url: "http://localhost", expires: Date.now() + 1000, controls: "http://localhost/controls/" };

describe("controlsInstallUrl", () => {
  it("sends the control to this platform's project chooser", () => {
    expect(controlsInstallUrl(payload, "accuracy-checklist")).toBe(
      "http://localhost/controls/install?slug=accuracy-checklist",
    );
  });

  it("preselects the project the catalogue was opened from", () => {
    expect(controlsInstallUrl({ ...payload, project: PID }, "x")).toBe(
      `http://localhost/controls/install?slug=x&project=${PID}`,
    );
  });

  it("drops a project that is not a pid, and still offers the chooser", () => {
    expect(controlsInstallUrl({ ...payload, project: "../admin" }, "x")).toBe("http://localhost/controls/install?slug=x");
  });

  it("offers nothing when no platform opened the catalogue", () => {
    expect(controlsInstallUrl(null, "x")).toBeNull();
    expect(controlsInstallUrl({ ...payload, controls: undefined }, "x")).toBeNull();
  });

  it("encodes the slug", () => {
    expect(controlsInstallUrl(payload, "a b")).toContain("slug=a%20b");
  });
});
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd apps/catalogue/frontend && npx vitest run src/crossSite/controlsInstall.test.ts`
Expected: FAIL, cannot resolve `./controlsInstall`.

- [ ] **Step 3: Implement.** In `connect.ts`, add to `HandshakePayload`:

```ts
  /** Where the opening platform's controls app lives, e.g.
   *  http://localhost/controls. A control is sent there, and that platform
   *  asks which of its projects gets it. */
  controls?: string;
  /** The project the catalogue was opened from, if any: only preselected in
   *  the platform's chooser, never decided here. */
  project?: string;
```

Create `controlsInstall.ts`:

```ts
import type { HandshakePayload } from "./connect";

const PID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The opening platform's page that asks which project gets this control, or
 *  null when no platform opened the catalogue and so there is nowhere to send it. */
export function controlsInstallUrl(payload: HandshakePayload | null, slug: string): string | null {
  if (!payload?.controls) return null;
  const base = payload.controls.replace(/\/+$/, "");
  const project = payload.project && PID.test(payload.project) ? `&project=${encodeURIComponent(payload.project)}` : "";
  return `${base}/install?slug=${encodeURIComponent(slug)}${project}`;
}
```

- [ ] **Step 4: Show it on a control.** In `connect.ts`, next to `getBackUrl`, add:

```ts
/** The whole handshake this catalogue was opened with, or null. */
export function getHandshake(): HandshakePayload | null {
  return readPayload();
}
```

In `CrossSiteContext.tsx`:
- Import `getHandshake` and `type HandshakePayload`.
- Add `handshake: HandshakePayload | null;` to `CrossSiteState`.
- Add `const [handshake, setHandshake] = useState<HandshakePayload | null>(null);`.
- In the mount effect, after `setBackUrl(getBackUrl());`, add `setHandshake(getHandshake());`.
- Add `handshake` to the memo value and its dependency list.

In `ToolDetailModal.tsx`, import `useCrossSite` from `../../crossSite/CrossSiteContext` and `controlsInstallUrl` from `../../crossSite/controlsInstall`. Next to `const coordinates = …`, add:

```tsx
  const { handshake } = useCrossSite();
  const installIntoControls = controlsInstallUrl(handshake, tool.slug);
```

Then replace the `{coordinates ? (…) : (…)}` block in the actions row with:

```tsx
          {isControls ? (
            installIntoControls ? (
              <a style={styles.actionBtn(false)} href={installIntoControls}>
                Install into a project…
              </a>
            ) : (
              <span style={{ color: "#6b7280", fontSize: 13, alignSelf: "center" }}>
                Open the catalogue from your platform to install this control.
              </span>
            )
          ) : coordinates ? (
            <InstallPluginButton pkg={coordinates.pkg} version={coordinates.version} slug={coordinates.slug} />
          ) : (
            <span style={{ color: "#6b7280", fontSize: 13, alignSelf: "center" }}>
              {installInfoError
                || (installInfo ? (installInfo.reason ?? "Not installable here.") : "Checking the package index…")}
            </span>
          )}
```

If `actionBtn(false)` renders a button style for an anchor badly, use the same inline style `InstallPluginButton` uses for its anchor. If `ToolDetailModal` tests render the modal without a `CrossSiteProvider`, wrap them in one.

- [ ] **Step 5: The launcher tells the catalogue where this platform's controls are.** In `homepage/project.html`, the project is loaded into `p` by the earlier script. Store it: after `var meta = …` add `window.aiscProject = p.pid;`. In the catalogue handshake payload (around line 503), add two fields:

```js
                        project: window.aiscProject,
                        controls: 'http://localhost/controls',
```

- [ ] **Step 6: Run the frontend tests.**

Run: `npx vitest run`
Expected: all PASS, including the existing `ToolDetailModal.test.tsx` and `ToolCard.test.tsx`. If a `ToolDetailModal` test renders a control and expected `InstallPluginButton`, update it: a control now shows "Install into a project…" or the "Open the catalogue from your platform" hint.

- [ ] **Step 7: Commit.**

```bash
(cd apps/catalogue && git add frontend/src/crossSite frontend/src/components/catalogue/ToolDetailModal.tsx && git commit -m "A control is sent to the opening platform, which asks for the project")
git add homepage/project.html
git commit -m "The launcher tells the catalogue where this platform's controls are"
```

---

### Task 10: Retire controls from the shared database, and prove it end to end

**Files:**
- Modify: `scripts/verify-one-database.sh` (lines 28, 133, 158, 232, 242), `scripts/verify-db-access.sh` (lines 36, 43–44, 47, 64), `scripts/verify-rbac.sh` (after line 149)
- Create: `init/retire-shared-controls.sql`

**Interfaces:**
- Consumes: everything above.
- Produces: `scripts/verify.sh` → 0 failed. No `controls` schema in the `platform` database.

- [ ] **Step 1: Write the failing end-to-end assertions.** In `scripts/verify-rbac.sh`, after line 149 (inside the `if [ -n "$PROJECT" ]` block), add:

```bash
  CTRL="controls-web:3000/controls/p"
  is "a path that is not a project is not found"  404 "$(page $CTRL/abc/checklists "$USER")"
  is "the install page previews for a member"     200 "$(page "$CTRL/$PROJECT/install?slug=accuracy-checklist" "$USER")"
  is "and is not found for a project nobody is in" 404 "$(page "$CTRL/$NOBODY/install?slug=accuracy-checklist" "$USER")"
  is "the project chooser opens for anyone signed in" 200 "$(page "controls-web:3000/controls/install?slug=accuracy-checklist" "$USER")"
  echo "the controls schema no longer lives in the shared database"
  left=$(docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_namespace where nspname = \$\$controls\$\$"')
  is "no shared controls schema" 0 "$left"
```

`is` compares its second and third arguments and prints its first. It's defined at the top of `verify-rbac.sh`. The viewer→403 check on the install POST needs a server-action request, which `wget` can't build. Task 7's middleware reuse covers it (`decide()` is unit-tested in `test/unit/projectAccess.test.ts`), so it isn't repeated here.

- [ ] **Step 2: Run it and watch it fail.**

Run: `scripts/verify-rbac.sh`
Expected: `no shared controls schema` FAILS (expected 0, got 1). The page checks pass if Tasks 5–7 are deployed.

- [ ] **Step 3: Check what will be dropped.** This removes the shared `controls` schema and everything in it.

Run: `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select (select count(*) from controls.checklist), (select count(*) from controls.submission)"'`
Expected: `17|0`. **If the submission count isn't 0, stop and ask the user.** Those are answered checklists that would be lost.

- [ ] **Step 4: Drop it.** Create `init/retire-shared-controls.sql`:

```sql
-- Controls keeps each project's data in that project's database now (see
-- platform/project-template/0001_controls.sql). What is left here is the 17
-- example checklists that were seeded into the shared schema, and no answers.
DROP SCHEMA IF EXISTS controls CASCADE;
```

Run it once as the superuser. After the user has confirmed in Step 3:

`docker exec -i postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < init/retire-shared-controls.sql`

On a fresh volume the schema is never created: remove `CREATE SCHEMA controls;`, its `COMMENT`, and every `controls` / `controls_rw` grant on the `controls` schema from `init/platform-db.sql`. Keep the `controls_rw` role itself.

- [ ] **Step 5: Update the one-database checks.**
  - `verify-one-database.sh:28`: delete the `controls|controls-web|…` line from `MODULES`.
  - Line 133: `for gone in control_objectives qualification; do` (controls is gone for a different reason, and Step 1 checks that).
  - Line 158: delete `controls.checklist` from the dashboard's list.
  - Lines 232 and 242: delete `'controls',` from both `table_schema in (…)` lists.
  - `verify-db-access.sh`: delete line 36 (`allow controls_rw … controls.probe`), line 43 (`deny controls_rw …`) and line 44 (`deny engine_rw "create table controls.sneaky …"`). Delete `controls` from the `for s in …` list on line 47, and `controls.probe` from the cleanup on line 64. Keep `controls_rw` in the "reads the core" loop on line 26 for now: the role still exists. Plan 7 retires that.

- [ ] **Step 6: Run the whole verdict.**

Run: `scripts/verify.sh`
Expected: the final line reports `0 failed`. The `controls` and `catalogue backend`/`catalogue frontend` module suites are `ok`, not `skip`.

Adding someone to a project as a viewer (walkthrough step 8) is done through the platform API: `POST /api/projects/{slug}/members` with `{"subject": "<user's Keycloak id>", "role": "viewer"}`, as the owner. The two seeded ids are in `docker-compose.development.yml:509`.

- [ ] **Step 7: Walk through it once in the browser.**
  1. http://localhost:8100 → open the project → step 5, Controls: the library is empty.
  2. Create a second project on the homepage. Its step 5 library is empty too.
  3. Back in the first project → step 3, Catalogue → open a control (for example *Accuracy_Checklist*) → **Install into a project…**
  4. The chooser lists both projects, with the first one preselected → **Continue**.
  5. The preview shows the title and question count → **Install into this project** → you land on the fill page with "Installed from the catalogue."
  6. The first project's step 5 library has exactly that one checklist. The second project's library is still empty.
  7. Open the catalogue again, install the same control, and choose the **second** project this time. Both libraries now have it, as two independent copies.
  8. Sign in as `user` in a private window. Add `user` to the first project as a **viewer** only, then press Install in the catalogue. The chooser shows neither project, and says there's none they can install into.

- [ ] **Step 8: Commit.**

```bash
git add scripts/verify-one-database.sh scripts/verify-db-access.sh scripts/verify-rbac.sh init/retire-shared-controls.sql init/platform-db.sql
git add apps/controls apps/catalogue   # submodule pointers
git commit -m "Controls lives in each project's database, and is gone from the shared one"
```

---

### Task 11: Only an admin deletes a project, by typing its name

**Files:**
- Modify: `platform/platform_service/app.py` (new `DELETE /projects/{slug}`)
- Modify: `homepage/project.html` (a Delete button for admins, a confirmation dialog, and the scope note)
- Test: `platform/tests/test_project_deletion.py`

**Interfaces:**
- Consumes: `projectdb.drop(base_dsn, pid)`, `db.delete_project(pid)` and `db.get_project(slug)` (Task 2). `GET /authz/projects/{slug}` → `{admin: bool, …}` (`app.py:117`).
- Produces: `DELETE /projects/{slug}` with body `{"confirm_name": "<the project's exact name>"}`:
  - 204: deleted, database included.
  - 404: unknown project, or a caller who isn't in it.
  - 403: a member who isn't an admin, owners included.
  - 422: the name doesn't match exactly (case and spaces count).

  The project's database is dropped first and its row second. A failure in between leaves a project with no database (which `provision_all` recreates empty on restart), never data with no project.

- [ ] **Step 1: Write the failing tests.** Create `platform/tests/test_project_deletion.py`:

```python
"""Deleting a project: only an admin, and only by typing its name.

It drops the project's database, which is everything every module holds for
it, so the rule is strict and the tests check the database is really gone.
"""
import psycopg

from platform_service import projectdb
from tests.conftest import needs_database


def _db_exists(dsn, pid):
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "select 1 from pg_database where datname = %s", (projectdb.database_name(pid),)
        ).fetchone() is not None


def _delete(client, slug, name, headers):
    return client.request("DELETE", f"/projects/{slug}", json={"confirm_name": name}, headers=headers)


@needs_database
def test_an_admin_who_types_the_name_deletes_the_project_and_its_database(client, as_user, unique, dsn):
    slug = unique()
    created = client.post("/projects", json={"name": f"Name {slug}", "slug": slug}, headers=as_user("alice")).json()
    assert _db_exists(dsn, created["pid"])
    admin = as_user("root", roles=("admin",))
    assert _delete(client, slug, f"Name {slug}", admin).status_code == 204
    assert client.get(f"/projects/{slug}", headers=admin).status_code == 404
    assert not _db_exists(dsn, created["pid"])


@needs_database
def test_a_name_that_is_nearly_right_deletes_nothing(client, as_user, unique, dsn):
    slug = unique()
    created = client.post("/projects", json={"name": f"Name {slug}", "slug": slug}, headers=as_user("alice")).json()
    admin = as_user("root", roles=("admin",))
    for wrong in (f"name {slug}", f"Name {slug} ", slug, ""):
        assert _delete(client, slug, wrong, admin).status_code == 422
    assert _db_exists(dsn, created["pid"])


@needs_database
def test_an_owner_who_is_not_an_admin_cannot_delete(client, as_user, unique, dsn):
    slug = unique()
    created = client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice")).json()
    assert _delete(client, slug, slug, as_user("alice")).status_code == 403
    assert _db_exists(dsn, created["pid"])


@needs_database
def test_a_stranger_is_told_nothing(client, as_user, unique):
    slug = unique()
    client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice"))
    assert _delete(client, slug, slug, as_user("mallory")).status_code == 404


@needs_database
def test_an_unknown_project_is_404_even_for_an_admin(client, as_user):
    assert _delete(client, "pytest-no-such-project", "x", as_user("root", roles=("admin",))).status_code == 404
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_project_deletion.py -v`
Expected: FAIL. The first test gets 405 Method Not Allowed.

- [ ] **Step 3: Implement.** In `app.py`, after `add_project`:

```python
class DeleteProjectIn(BaseModel):
    confirm_name: str


@app.delete("/projects/{slug}", status_code=204)
def remove_project(slug: str, body: DeleteProjectIn, caller: Caller = Depends(caller_dependency)) -> None:
    """Delete a project and everything every module holds for it.

    Only an admin, and only by typing the project's name exactly: this drops the
    project's database, and there is no undo. The database goes first, so a
    failure halfway leaves a project with no data rather than data with no
    project.
    """
    if not caller.has_role(ADMIN_ROLE):
        role_or_404(slug, caller)  # a stranger is told nothing
        raise HTTPException(status_code=403, detail="only an admin deletes a project")
    found = db.get_project(slug)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no project {slug!r}")
    if body.confirm_name != found["name"]:
        raise HTTPException(status_code=422, detail="type the project's name exactly to delete it")
    projectdb.drop(db.dsn(), found["pid"])
    db.delete_project(found["pid"])
```

- [ ] **Step 4: Run the platform suite.**

Run: `uv run --extra dev pytest -v`
Expected: all PASS.

- [ ] **Step 5: The homepage.** In `homepage/project.html`:

(a) Replace the text of `<p class="note" id="scope-note">` with:

```html
      Every step below opens on this project, and keeps what it does for this
      project in this project's own database. Nothing here is shared with any
      other project.
```

(b) After that `<p>`, add:

```html
    <p id="danger" hidden>
      <button type="button" class="newbtn ghost" id="delete-open">Delete this project…</button>
    </p>
    <dialog class="new" id="delete-dialog">
      <form method="dialog" id="delete-form">
        <h2>Delete this project</h2>
        <p>This deletes the project and everything every step holds for it: its
          database is dropped, and there is no undo.</p>
        <p>Type <b id="delete-name"></b> to confirm.</p>
        <input id="delete-input" autocomplete="off" spellcheck="false"/>
        <p class="err" id="delete-err"></p>
        <button type="button" class="newbtn ghost" id="delete-cancel">Cancel</button>
        <button type="submit" class="newbtn" id="delete-confirm" disabled>Delete</button>
      </form>
    </dialog>
```

(c) In the script, inside the `.then(function (p) { … })` that fills in `project-name`, after `window.aiscProject = p.pid;` (added in Task 9), add:

```js
      fetch('/api/authz/projects/' + encodeURIComponent(slug), {credentials: 'same-origin'})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (a) {
          if (!a || !a.admin) return;          // only an admin sees it at all
          var dlg = document.getElementById('delete-dialog');
          var input = document.getElementById('delete-input');
          var go = document.getElementById('delete-confirm');
          var err = document.getElementById('delete-err');
          document.getElementById('delete-name').textContent = p.name;
          document.getElementById('danger').hidden = false;
          document.getElementById('delete-open').onclick = function () {
            input.value = ''; go.disabled = true; err.textContent = ''; dlg.showModal(); input.focus();
          };
          document.getElementById('delete-cancel').onclick = function () { dlg.close(); };
          input.oninput = function () { go.disabled = input.value !== p.name; };
          document.getElementById('delete-form').onsubmit = function (e) {
            e.preventDefault();
            if (input.value !== p.name) return;
            go.disabled = true;
            fetch('/api/projects/' + encodeURIComponent(slug), {
              method: 'DELETE', credentials: 'same-origin',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({confirm_name: input.value})
            }).then(function (r) {
              if (r.status === 204) { window.location.href = '/'; return; }
              return r.json().then(function (d) { err.textContent = d.detail || ('Refused: ' + r.status); go.disabled = false; });
            }).catch(function () { err.textContent = 'The platform is not answering. Nothing was deleted.'; go.disabled = false; });
          };
        });
```

The button stays disabled until the typed text equals the name exactly, and the server checks it again. Hiding the button from non-admins is a courtesy; the 403 is the rule.

- [ ] **Step 6: Check it in the browser.**
  1. As `admin`, open a throwaway project → **Delete this project…** → type the name with one letter wrong: Delete stays disabled → fix it → Delete → you're back on the project list without it.
  2. As `user`, open a project you own: no Delete button.
  3. Run `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_database where datname like \$\$project\_%\$\$"'`: the count went down by one.

- [ ] **Step 7: Commit.**

```bash
git add platform/platform_service/app.py platform/tests/test_project_deletion.py homepage/project.html
git commit -m "Only an admin deletes a project, and only by typing its name"
```

---

## Stopping rule and checkpoints

- **Checkpoint after every task:** that task's own test command, plus `scripts/verify.sh --modules`. A task isn't done until both are green.
- **Stop and ask** if Task 10 Step 3 shows any submission, if any existing test outside this plan starts failing and the fix would change its assertion, or if `CREATE DATABASE` is refused after Task 1.
- **Done when** `scripts/verify.sh` prints `0 failed`, and the Task 10 Step 7 and Task 11 Step 6 walkthroughs behave as written. Nothing is pushed.
