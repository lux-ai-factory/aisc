# Project databases, plan 5: the results dashboard reads each project's own database

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The one Superset instance has one database connection per project, to `project_<hex>`, as `dashboard_ro`. The platform registers that connection when it makes the project, keeps its members in step, and removes it when the project is deleted. Each project gets a default dataset set and dashboard made from code. Only that project's members see any of it, and every request that names a project's dashboard, chart, dataset or connection is checked against membership of that exact project, on the server. Opening step 6 from a project opens that project's dashboard. The shared `AISC Results` connection, and `dashboard_ro`'s reach into the shared `platform` database, go away.

**Architecture:**
1. **Postgres.** `platform/project-template/0005_dashboard.sql` gives `dashboard_ro` CONNECT to the project database, plus SELECT on every module's tables, including ones created later. "Later" is handled by default privileges set per module role for the whole database, with no `IN SCHEMA`, so they also cover a schema whose template file lands after 0005 (the engine's, Plan 4). Only a member of a role may set that role's default privileges. So `platform_rw` becomes a `NOINHERIT` member of the four module roles (`init/project-databases.sql`). That lets it set those defaults while gaining none of the roles' read access. In the shared `platform` database, `dashboard_ro` loses every grant and its search_path that spanned the module schemas.
2. **Registration goes through `aisc_ext`, not Superset's REST API.** The platform calls a small bridge that `aisc_ext` adds to Superset: `PUT` / `DELETE /aisc/bridge/projects/{pid}` and `GET /aisc/bridge/projects`. It authenticates with `Authorization: Bearer $DASHBOARD_BRIDGE_TOKEN`. The bridge then applies the change with Superset's own models, the same way `aisc_ext/results_db.py:56-73` already does. Why not the REST API:
   - Under `AUTH_OAUTH` (`superset_config.py:124-153`), the REST API has no service login. The platform would need the DB-auth admin's password, which is another admin secret spread to a second service.
   - Superset 4.1 has no REST endpoint for editing role permissions. Per-project access is exactly role permissions (`database_access`) plus dashboard roles.
   - One registration would take a dozen CSRF-guarded calls. Through `aisc_ext` it is one transaction.
3. **Membership reaches Superset as per-project roles synced from the platform, plus a server-side membership gate.** The platform pushes a project's whole member list, as Keycloak subjects, whenever the list or the project changes. It also re-pushes every project every 60 s, which repairs anything missed while Superset was down. Superset keeps that list in `aisc_project_member`, and records each person's subject when they sign in (`aisc_user_subject`).
   - **Role `aisc_project_<hex>`.** It holds only `database_access` on that project's connection, and it is the only role on that project's dashboard (`DASHBOARD_RBAC`). Roles are needed because Superset's own filters use them for every list, and its `raise_for_access` uses them for every object.
   - **The gate.** It sits in `raise_for_access` (every dashboard, chart, dataset, chart-data and SQL request) and in `DB_CONNECTION_MUTATOR` (every connection Superset opens). It checks the list above for the exact project the object belongs to, taken from the object's own connection name and never from the client.
   - **Why the list is pushed, not asked per request.** Superset holds no platform token it could send: FAB keeps only the access token (`flask_appbuilder/security/manager.py:588`), and Keycloak access tokens live 300 s (`keycloak/aisc-realm.json:8`). Superset also runs on the host network, outside the backend network the platform lives on.
   - **Adding a member:** the member's next request after the push succeeds. **Removing one:** refused on the next request after the push. If Superset was down at that moment, access is refused within 60 s of it coming back.
4. **Default dataset and dashboard per project.** The bridge looks for `engine.evaluation` and `engine.measurement` in the project database. It makes a dataset for each table it finds, three charts on them, and one dashboard, `project-<hex>`, published to that project's role.
   - On an empty project database (before Plan 4) the dashboard exists, shows a note saying which tables it waits for, and has no charts.
   - After Plan 4 has run, the next push (at most 60 s later) adds the datasets and charts.
5. **Step 6.** The homepage links to `http://localhost:8188/aisc/p/{pid}`. That route sends an anonymous visitor to sign in. It sends a member to `/superset/dashboard/project-<hex>/`. It answers 404 to anyone else, the same answer the platform gives a stranger.

**Tech Stack:** Superset 4.1.1 + Flask-AppBuilder 4.5.0 (`apache/superset:4.1.1`, Python 3.10 in the container), pytest in `apps/results-dashboard/.venv` (pure modules only), Python 3.12 + FastAPI + psycopg 3 (platform), Postgres 14, docker compose.

**Spec:** `docs/superpowers/plans/2026-09-23-project-databases-roadmap.md` (item 5). The decisions given for this plan: one Superset; one connection per project as `dashboard_ro` via `0005_dashboard.sql`, with default privileges; the platform registers and removes the connection; access limited to members; step 6 opens the project's dashboard; a default dataset and dashboard from code, robust to an empty database; the single registration and the search_path both removed; the verify scripts updated. The binding lesson in `.superpowers/sdd/planner-brief.md` ("LESSON FROM PLAN 1'S FINAL REVIEW") applies, as adapted for Superset by the coordinator: every request naming a project's connection, dashboard or dataset is checked server-side against membership of that exact project, and a test asks by id and is refused.

## Global Constraints

- Project database name: `project_` + the pid, lowercased, hyphens removed. Example: pid `3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b` → `project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b`. `tests/test_projects.py` asserts this example, the same one the platform and controls tests assert.
- A pid must match `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (case-insensitive) before any name is built from it. Otherwise it is refused: 404 on the person's route, 422 on the bridge.
- Superset names derived from a pid: connection `project_<hex>`, role `aisc_project_<hex>`, dashboard slug `project-<hex>`. None of them carry the project's name, which is often a customer's. Only the dashboard title does, and only members see it.
- `dashboard_ro` keeps its dev password (`dashboard_ro`), which is already in the compose defaults. The one new secret, `DASHBOARD_BRIDGE_TOKEN`, is generated by `scripts/secrets.sh` into the git-ignored `env.secrets`, and is never printed, logged or committed. With no token configured, the bridge refuses everything. It is never open by default.
- Compose invocation for every step below (constraints.md): `set -a; . ./env.secrets; set +a` once per shell. Then `DC="docker compose -p aisc --env-file env.plugin_downloader -f docker-compose-infra.development.yml -f docker-compose.development.yml"`, and use `$DC up -d …`.
- **HARD RULE.** Never DROP, ALTER or delete rows in any database, schema or project you did not create in the current task.
  - The real project database `project_01399e174b014be9997a7f5e3574ab22` changes only through the platform's own template path (`projectdb.provision`).
  - The `AISC Results` row in Superset's `dbs` is removed only by the code in Task 6, and only after its Step 1 check shows no dataset on it.
  - Throwaway project databases are made and dropped only by the tests and scripts written here, under names they generate.
- No shared schema is dropped (that is plan 6). Revoking `dashboard_ro`'s grants in `platform` is not dropping.
- Nothing is pushed. Commits go to `feat/unified-modules`, and are made inside `apps/results-dashboard` for its files. Stage explicit paths only.
  - `apps/results-dashboard` holds someone else's uncommitted Review-page work: `aisc_ext/comments/api.py`, `aisc_ext/comments/views.py`, hunks in `superset_config.py`, and untracked `aisc_ext/review/`, `scripts/verify_review.py`, `tests/test_review.py`. Stage `superset_config.py` with `git add -p`, taking only this plan's hunks. Never stage, edit or revert those other files.
  - The root holds the qualification-prefill hunks in `docker-compose.development.yml` and `scripts/verify.sh`, plus changed pointers for `apps/backend`, `apps/eval`, `apps/webapp` and `apps/qualification`. Use `git add -p docker-compose.development.yml` for this plan's hunks only. Don't touch `scripts/verify.sh`. Stage no submodule pointer except `apps/results-dashboard`.
- Platform admins (realm role `admin`) are Superset `Admin` and see every project, because the platform already treats an admin as owner of every project (`platform/platform_service/app.py:41-45`). Everyone else sees only the projects they are in.

## Review Focus

1. **A non-member asks for another project's dashboard, chart, chart data, dataset or connection by id** (not through a menu), including when they were given the project's role by hand and the chart data is already cached. Expected: 403/404, before any connection to that database is opened. Pinned in Task 4 (`run_access`) and Task 5 (`run_gate`).
2. **A member is removed while signed in to Superset.** Expected: their very next request is refused. If Superset was down during the removal, the refusal starts within 60 s of Superset coming back. Pinned in Task 4 (`run_membership_change`) and Task 8 (`test_reconciling_…`).
3. **A project database with no engine tables** (before Plan 4). Expected: a connection and a dashboard with a note, no charts and no errors. Charts appear on the next push after the tables exist. Pinned in Task 3 and Task 4.
4. **A table a module creates after the template ran, in a schema whose template file arrives later.** Expected: `dashboard_ro` reads it and cannot write it, and `platform_rw` cannot read it itself. Pinned in Task 2.
5. **The bridge is called with no token, the wrong token, a body that is not a project's state, or a path that is not a pid.** Expected: 401 or 422, and nothing registered. Pinned in Task 4 (`run_bridge_door`).

---

## File map

**Root repo (`~/aisc-install`)**
- Modify `init/project-databases.sql`: `platform_rw` becomes a NOINHERIT member of the module roles, and `dashboard_ro` loses its grants and search_path in `platform`.
- Modify `init/platform-db.sql`: fresh volumes no longer give `dashboard_ro` anything in `platform`.
- Create `platform/project-template/0005_dashboard.sql`.
- Create `platform/platform_service/dashboard.py` (push, forget, reconcile). Modify `platform/platform_service/app.py` (hooks + lifespan).
- Create `platform/tests/test_dashboard_template.py`, `platform/tests/test_dashboard_bridge.py`.
- Modify `docker-compose.development.yml`:
  - `dashboard-migrate`/`dashboard`: drop `AISC_RESULTS_DB_URI`, add `AISC_PROJECT_DB_URI` and `DASHBOARD_BRIDGE_TOKEN`.
  - `platform`: add `DASHBOARD_BRIDGE_URL`, `DASHBOARD_BRIDGE_TOKEN` and `extra_hosts`.
- Modify `scripts/secrets.sh` (adds `DASHBOARD_BRIDGE_TOKEN`, including to an existing `env.secrets`).
- Modify `homepage/project.html` (step 6 opens the project's dashboard).
- Modify `scripts/verify-db-access.sh`, `scripts/verify-one-database.sh`, `scripts/verify-rbac.sh`, `scripts/verify-sso.sh`.

**`apps/results-dashboard`**
- Create `aisc_ext/projects.py` (pure rules), `aisc_ext/project_model.py` (two tables), `aisc_ext/project_sync.py` (applies the rules through Superset), `aisc_ext/bridge.py` (the two doors), `aisc_ext/project_gate.py` (the membership gate), `aisc_ext/visible.py` (dashboards the caller may open).
- Modify `aisc_ext/sso.py`, `aisc_ext/security.py`, `aisc_ext/reviews/api.py`, `aisc_ext/reviews/service.py`, `superset_config.py`.
- Delete `aisc_ext/results_db.py`, `tests/test_results_database.py`.
- Modify `.env.example`, `docker-compose.yml`, `docker-compose.aisc.yml`, `README.md`, `scripts/bootstrap.sh` (the `AISC_RESULTS_DB_URI` mentions).
- Create `tests/test_projects.py`, `scripts/verify_projects.py`, `scripts/verify_projects.sh`. Modify `tests/test_roles.py`, `tests/test_reviews.py`.

---

### Task 1: The dashboard leaves the shared database, and the platform may set up its reads

**Files:**
- Modify: `init/project-databases.sql` (16 lines; insert before `\connect template1`, line 14)
- Modify: `init/platform-db.sql`:
  - line 109-110 (comment on `dashboard_ro`)
  - lines 121-129 (`dashboard_ro` in the core grants)
  - lines 164-167 (the dashboard grants in the module loop)
  - line 177 (the search_path)
  - Match by content: plans 2–4 may shift these lines.
- Test: `scripts/verify-db-access.sh`:
  - section 5, lines 43-52
  - new section 7b before the summary line 71
- Test: `scripts/verify-one-database.sh`, lines 156-164 (the "reads the whole database" loop)

**Interfaces:**
- Produces:
  - `pg_has_role('platform_rw', r, 'MEMBER')` is true for `controls_rw`, `qualification_rw`, `control_objectives_rw` and `engine_rw`.
  - `pg_roles.rolinherit` is false for `platform_rw`.
  - In the `platform` database, `dashboard_ro` has no USAGE on `core`, `qualification`, `control_objectives`, `engine` or `catalogue`, no SELECT on their tables, and no `search_path` setting.

- [ ] **Step 1: Write the failing assertions.** In `scripts/verify-db-access.sh`, replace section 5 (lines 43-52) with:

```bash
echo "5. the dashboard reads nothing in the shared database"
# It reads each project's own database (platform/project-template/0005_dashboard.sql).
for s in core qualification control_objectives engine; do
  case "$s" in
    core) deny dashboard_ro "select count(*) from core.project" "cannot read core";;
    *)    deny dashboard_ro "select count(*) from $s.probe"     "cannot read $s";;
  esac
done
deny dashboard_ro "insert into engine.probe values (2)"                     "cannot write the engine's schema"
deny dashboard_ro "insert into core.project (name, slug) values ('x','y')"  "cannot write core"
deny dashboard_ro "create table core.sneaky (x int)"                        "cannot create tables"
```

Before the final `echo; echo "passed: …` line, add:

```bash
echo "7b. the platform may set up the dashboard's reads for each module, and reads none of it itself"
su_() { docker exec "$PGC" psql -U "${POSTGRES_USER:-aisc-postgres-user}" -d "$DB" -At -c "$1" 2>/dev/null; }
held=$(su_ "select string_agg(r.rolname, ',' order by r.rolname) from pg_roles r
             where r.rolname in ('controls_rw','qualification_rw','control_objectives_rw','engine_rw')
               and pg_has_role('platform_rw', r.oid, 'MEMBER')")
[ "$held" = "control_objectives_rw,controls_rw,engine_rw,qualification_rw" ] \
  && ok "platform_rw is a member of the four module roles" \
  || no "platform_rw is a member of: ${held:-none}"
inherit=$(su_ "select rolinherit from pg_roles where rolname = 'platform_rw'")
[ "$inherit" = "f" ] && ok "and inherits nothing from them (NOINHERIT)" \
  || no "platform_rw inherits its memberships (rolinherit=$inherit)"
path=$(su_ "select coalesce(string_agg(array_to_string(s.setconfig, ','), ';'), '')
              from pg_db_role_setting s join pg_roles r on r.oid = s.setrole
             where r.rolname = 'dashboard_ro'")
[ -z "$path" ] && ok "dashboard_ro has no search_path spanning the modules' schemas" \
  || no "dashboard_ro still sets: $path"
```

In `scripts/verify-one-database.sh`, replace lines 156-164 (the echo and the `for t in …` loop; keep the write check at 166-172) with:

```bash
echo "the dashboard reads nothing in the shared database"
# One connection per project database now; the shared one is not read at all.
for t in engine.project catalogue.tool \
         qualification.qualification control_objectives.project core.project; do
  n=$(docker exec postgres psql "postgresql://dashboard_ro:dashboard_ro@localhost:5432/$PGDB" \
        -At -c "select count(*) from $t" 2>&1 | tail -1)
  case "$n" in
    *"permission denied"*|*"does not exist"*) ok "dashboard_ro cannot read $t" ;;
    *) no "dashboard_ro still reads $t: $n" ;;
  esac
done
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `scripts/verify-db-access.sh; scripts/verify-one-database.sh`
Expected:
- `FAIL dashboard_ro: cannot read core (was ALLOWED)`
- `FAIL platform_rw is a member of: none`
- `FAIL platform_rw inherits its memberships (rolinherit=t)`
- `FAIL dashboard_ro still sets: search_path=core, qualification, control_objectives, engine`
- `FAIL dashboard_ro still reads core.project: 1`

- [ ] **Step 3: The SQL for existing volumes.** In `init/project-databases.sql`, insert before `\connect template1`:

```sql
-- The dashboard's template (platform/project-template/0005_dashboard.sql)
-- sets, in every project database, what dashboard_ro may read of the tables
-- each module makes later. Only a member of a role may set that role's
-- default privileges, so the platform is made one. NOINHERIT keeps it to that:
-- the platform gains none of the modules' reads by it, and would have to SET
-- ROLE, which only that template does.
ALTER ROLE platform_rw NOINHERIT;
GRANT controls_rw, qualification_rw, control_objectives_rw, engine_rw TO platform_rw;

-- The dashboard reads project databases only, one Superset connection each.
-- What it was given in this shared database, and the search_path that spanned
-- every module's schema, are taken back on volumes made before that. Revoking
-- what is not granted changes nothing, so this runs on every start.
DO $dashboard_leaves$
DECLARE
    m record;
BEGIN
    FOR m IN SELECT * FROM (VALUES
        ('core',               NULL),
        ('qualification',      'qualification_rw'),
        ('control_objectives', 'control_objectives_rw'),
        ('engine',             'engine_rw'),
        ('catalogue',          'catalogue_rw')
    ) AS t(schema_name, role_name)
    LOOP
        CONTINUE WHEN to_regnamespace(m.schema_name) IS NULL;
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM dashboard_ro', m.schema_name);
        EXECUTE format('REVOKE USAGE ON SCHEMA %I FROM dashboard_ro', m.schema_name);
        IF m.role_name IS NULL THEN
            -- core's default was set by the superuser for itself (init/platform-db.sql)
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE SELECT ON TABLES FROM dashboard_ro',
                           m.schema_name);
        ELSE
            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE SELECT ON TABLES FROM dashboard_ro',
                           m.role_name, m.schema_name);
        END IF;
    END LOOP;
END
$dashboard_leaves$;
REVOKE CONNECT ON DATABASE platform FROM dashboard_ro;
ALTER ROLE dashboard_ro IN DATABASE platform RESET search_path;
```

`REVOKE CONNECT` removes only the explicit grant. `PUBLIC` keeps CONNECT on `platform` (its ACL reads `=Tc/…`), so `dashboard_ro` can still connect, but it can read nothing there. That is what the checks assert.

- [ ] **Step 4: The SQL for fresh volumes.** In `init/platform-db.sql`:
  - Line 109: the comment becomes `-- the dashboard: reads project databases only (0005_dashboard.sql)`.
  - Lines 121-129: delete `dashboard_ro` from the `GRANT CONNECT`, `GRANT USAGE ON SCHEMA core`, `GRANT SELECT ON ALL TABLES IN SCHEMA core` and `ALTER DEFAULT PRIVILEGES IN SCHEMA core` lists.
  - Lines 164-167: delete the comment `-- the dashboard reads what the module creates, now and later` and the two `EXECUTE` lines naming `dashboard_ro`.
  - Line 177: delete `ALTER ROLE dashboard_ro IN DATABASE platform SET search_path = …;`.
  - Keep `('dashboard_ro')` in the role-creation list (line 110). The role still exists and is used in project databases.

- [ ] **Step 5: Apply and run.**

Run: `$DC up -d postgres-setup && docker wait postgres-setup && scripts/verify-db-access.sh && scripts/verify-one-database.sh`
Expected:
- `docker wait` prints `0`.
- Every new line passes: sections 5 and 7b, and `dashboard_ro cannot read …` five times.
- The write check at `verify-one-database.sh:166-172` still passes, because the error is now `permission denied for schema engine`.
- The Superset registration checks (lines 174-203) still pass, because the `AISC Results` row is still there until Task 6.

- [ ] **Step 6: Commit.**

```bash
git add init/project-databases.sql init/platform-db.sql scripts/verify-db-access.sh scripts/verify-one-database.sh
git commit -m "The dashboard reads nothing shared, and the platform may set up its reads per project"
```

---

### Task 2: The dashboard's template: read every module in the project's database, now and later

**Files:**
- Create: `platform/project-template/0005_dashboard.sql`
- Test: `platform/tests/test_dashboard_template.py`
- Test: `scripts/verify-db-access.sh` (new section 8, after 7b)

**Interfaces:**
- Consumes: `platform_rw` is a NOINHERIT member of the module roles (Task 1). `projectdb.provision`, `projectdb.drop`, `projectdb.TEMPLATE`, `projectdb.TRACKING_TABLE` and `migrate.migrate(conn, directory, table)` (Plan 1, `platform/platform_service/projectdb.py:19-54`).
- Produces, in every project database:
  - `dashboard_ro` has CONNECT.
  - It has USAGE on every schema except `provision`, and SELECT on every table there. That includes tables made later by `platform_rw`, `controls_rw`, `qualification_rw`, `control_objectives_rw` or `engine_rw`, in any schema.
  - It has nothing else.

- [ ] **Step 1: Write the failing tests.** Create `platform/tests/test_dashboard_template.py`:

```python
"""The dashboard's grants in a project's database (0005_dashboard.sql).

The dashboard reads a project's database through one Superset connection, as
dashboard_ro. It has to read what every module makes there, including tables
made after the template ran and schemas whose template file arrives later,
and it must write nothing. The platform, which sets this up, must gain no
reads by doing so.
"""
import uuid

import psycopg
import pytest
from psycopg import errors
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from platform_service.migrate import migrate
from tests.conftest import needs_database


def _as(dsn, role, dbname):
    return psycopg.connect(make_conninfo(dsn, user=role, password=role, dbname=dbname), autocommit=True)


@pytest.fixture
def project_db(client, as_user, unique):
    created = client.post("/projects", json={"name": unique("dash")}, headers=as_user("alice")).json()
    return projectdb.database_name(created["pid"])


@needs_database
def test_the_dashboard_may_connect_to_a_new_project(project_db, dsn):
    with _as(dsn, "dashboard_ro", project_db) as conn:
        assert conn.execute("select 1").fetchone() == (1,)


@needs_database
def test_it_reads_what_a_module_makes_after_the_template(project_db, dsn):
    with _as(dsn, "controls_rw", project_db) as conn:
        conn.execute("create table controls.made_later (x int)")
        conn.execute("insert into controls.made_later values (1)")
    with _as(dsn, "dashboard_ro", project_db) as conn:
        assert conn.execute("select count(*) from controls.made_later").fetchone() == (1,)


@needs_database
def test_it_reads_a_schema_whose_template_arrives_later(project_db, dsn):
    # What the engine's template (Plan 4) does: the platform makes the schema,
    # then the engine's own migrations make tables in it.
    with _as(dsn, "platform_rw", project_db) as conn:
        conn.execute("create schema if not exists engine")
        conn.execute("grant usage, create on schema engine to engine_rw")
        conn.execute(f'grant connect on database "{project_db}" to engine_rw')
    with _as(dsn, "engine_rw", project_db) as conn:
        conn.execute("create table engine.made_later (id int, status text)")
    with _as(dsn, "dashboard_ro", project_db) as conn:
        assert conn.execute("select count(*) from engine.made_later").fetchone() == (0,)


@needs_database
def test_it_writes_nothing(project_db, dsn):
    with _as(dsn, "controls_rw", project_db) as conn:
        conn.execute("create table controls.t (x int)")
    with _as(dsn, "dashboard_ro", project_db) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("insert into controls.t values (1)")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("create table controls.sneaky (x int)")


@needs_database
def test_it_does_not_read_the_templates_bookkeeping(project_db, dsn):
    with _as(dsn, "dashboard_ro", project_db) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("select * from provision.template_migration")


@needs_database
def test_the_platform_gains_no_reads_by_setting_this_up(project_db, dsn):
    with _as(dsn, "controls_rw", project_db) as conn:
        conn.execute("create table controls.private (x int)")
    with _as(dsn, "platform_rw", project_db) as conn:
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("select * from controls.private")


@needs_database
def test_tables_made_before_the_dashboard_template_are_granted_too(dsn, tmp_path):
    """The path every existing project takes: its controls tables exist, then
    0005 is applied by provision() at the platform's next start."""
    pid = str(uuid.uuid4())
    name = projectdb.database_name(pid)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'create database "{name}"')
        only_controls = tmp_path / "template"
        only_controls.mkdir()
        (only_controls / "0001_controls.sql").write_text((projectdb.TEMPLATE / "0001_controls.sql").read_text())
        with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
            migrate(conn, only_controls, projectdb.TRACKING_TABLE)
        with _as(dsn, "controls_rw", name) as conn:
            conn.execute("create table controls.before (x int)")
        projectdb.provision(dsn, pid)  # the rest of the template, 0005 included
        with _as(dsn, "dashboard_ro", name) as conn:
            assert conn.execute("select count(*) from controls.before").fetchone() == (0,)
    finally:
        projectdb.drop(dsn, pid)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_dashboard_template.py -v`
Expected: every test except `test_it_does_not_read_the_templates_bookkeeping` and `test_the_platform_gains_no_reads_by_setting_this_up` FAILS with `psycopg.OperationalError: … permission denied for database "project_…"`. Those two pass already.

- [ ] **Step 3: Write the template.** Create `platform/project-template/0005_dashboard.sql`:

```sql
-- Step 6, the dashboard: this project's database, read-only, every module.
--
-- The dashboard is one Superset for every project, with one connection per
-- project database, as dashboard_ro (apps/results-dashboard/aisc_ext/
-- project_sync.py). This file is what that role may do here: connect, and
-- read every module's tables, now and later. Nothing else. Which Superset user
-- sees which connection is decided in Superset, by one role per project and a
-- membership gate: dashboard_ro itself may connect to every project database.
--
-- "Later" is the point. A module's tables are made by its own role, in its own
-- migrations, after this file ran, and sometimes in a schema whose template
-- file lands after this one (the engine's). So the defaults are set per role
-- for the whole database, with no IN SCHEMA, and hold for any schema that role
-- later makes. Setting another role's defaults takes membership in it:
-- init/project-databases.sql makes platform_rw a NOINHERIT member of each
-- module role for exactly this.
DO $dashboard$
DECLARE
    m record;
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO dashboard_ro', current_database());

    -- what the platform and the modules make from now on
    FOR m IN SELECT * FROM (VALUES
        ('platform_rw'), ('controls_rw'), ('qualification_rw'),
        ('control_objectives_rw'), ('engine_rw')
    ) AS t(role_name)
    LOOP
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT USAGE ON SCHEMAS TO dashboard_ro', m.role_name);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT SELECT ON TABLES TO dashboard_ro', m.role_name);
    END LOOP;

    -- what is already here: every schema but the template's own bookkeeping,
    -- and every table in it, granted by whoever owns it
    FOR m IN
        SELECT n.nspname AS schema_name, pg_get_userbyid(n.nspowner) AS owner
          FROM pg_namespace n
         WHERE n.nspname NOT IN ('provision', 'public', 'information_schema')
           AND n.nspname NOT LIKE 'pg\_%'
    LOOP
        CONTINUE WHEN NOT pg_has_role(m.owner, 'MEMBER');
        EXECUTE format('SET LOCAL ROLE %I', m.owner);
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO dashboard_ro', m.schema_name);
        RESET ROLE;
    END LOOP;
    FOR m IN
        SELECT DISTINCT n.nspname AS schema_name, pg_get_userbyid(c.relowner) AS owner
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND n.nspname NOT IN ('provision', 'public', 'information_schema')
           AND n.nspname NOT LIKE 'pg\_%'
    LOOP
        CONTINUE WHEN NOT pg_has_role(m.owner, 'MEMBER');
        EXECUTE format('SET LOCAL ROLE %I', m.owner);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO dashboard_ro', m.schema_name);
        RESET ROLE;
    END LOOP;
END
$dashboard$;
```

`GRANT SELECT ON ALL TABLES` as one owner only warns about tables another role owns, and the loop visits each owner in turn. `RESET ROLE` returns to `platform_rw` before `migrate()` records the file.

- [ ] **Step 4: Run the tests.**

Run: `uv run --extra dev pytest -v`
Expected: all PASS, including every test in `test_project_databases.py` and `test_project_deletion.py`.

- [ ] **Step 5: Add the end-to-end check.** In `scripts/verify-db-access.sh`, after section 7b and before the summary line, add:

```bash
echo "8. in a project's database the dashboard reads every module, now and later, and writes nothing"
PROBE_PID=$(python3 -c 'import uuid; print(uuid.uuid4())')
PDB=$(docker exec platform python -c "from platform_service import db, projectdb; print(projectdb.provision(db.dsn(), '$PROBE_PID'))" 2>/dev/null | tail -1)
in_db()    { docker exec "$PGC" psql "postgresql://$1:$1@$HOST:5432/$PDB" -v ON_ERROR_STOP=1 -At -c "$2" >/dev/null 2>&1; }
allow_in() { in_db "$1" "$2" && ok "$1: $3" || no "$1: $3 (was refused)"; }
deny_in()  { in_db "$1" "$2" && no "$1: $3 (was ALLOWED)" || ok "$1: $3"; }
case "$PDB" in
  project_*) ok "a throwaway project database, made the platform's way" ;;
  *) no "could not make a project database: ${PDB:-nothing}" ;;
esac
allow_in controls_rw  "create table controls.made_later (x int); insert into controls.made_later values (1)" "a module makes a table after the template ran"
allow_in dashboard_ro "select count(*) from controls.made_later"                   "the dashboard reads it"
deny_in  dashboard_ro "begin; insert into controls.made_later values (2); rollback" "and cannot write it"
deny_in  dashboard_ro "create table controls.sneaky (x int)"                       "nor create tables"
deny_in  dashboard_ro "select count(*) from provision.template_migration"          "nor read the template's bookkeeping"
deny_in  platform_rw  "select count(*) from controls.made_later"                   "the platform, which set this up, cannot read it"
docker exec platform python -c "from platform_service import db, projectdb; projectdb.drop(db.dsn(), '$PROBE_PID')" >/dev/null 2>&1
```

The write attempt runs inside `begin … rollback`, so a failure of this check leaves nothing behind.

- [ ] **Step 6: Apply to the existing projects, and check.** `platform/project-template` is bind-mounted (`docker-compose.development.yml:507`). The template is applied by `provision_all` on the first pool use of a fresh process.

Run: `$DC restart platform && docker exec platform python -c "from platform_service import db; db.pool()" && scripts/verify-db-access.sh`
Expected: every section passes. Then run:

`docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select datname, datacl::text like \$\$%dashboard_ro=c/%\$\$ from pg_database where datname ~ \$\$^project_[0-9a-f]{32}\$\$"'`

Expected: every row ends in `|t`. That includes `project_01399e174b014be9997a7f5e3574ab22` (changed only through `provision`) and the orphan `project_d78463…`, which `provision_all` does not visit because it has no `core.project` row. If the orphan shows `|f`, that is expected: report it, don't touch it.

- [ ] **Step 7: Commit.**

```bash
git add platform/project-template/0005_dashboard.sql platform/tests/test_dashboard_template.py scripts/verify-db-access.sh
git commit -m "A project's database lets the dashboard read every module, now and later, and write nothing"
```

---

### Task 3: One project, one connection: the rules, without Superset

**Files:**
- Create: `apps/results-dashboard/aisc_ext/projects.py`
- Test: `apps/results-dashboard/tests/test_projects.py`

**Interfaces:**
- Produces (pure; no Superset or Flask imports):
  - `class NotAPid(ValueError)`, `class InvalidProjectState(ValueError)`
  - `project_hex(pid) -> str`, `pid_from_hex(hex_: str) -> str`, `is_hex(text: str) -> bool`
  - `database_name(pid) -> str`, `pid_of_database(name: str) -> str | None`, `project_of_database(name: str) -> str | None` (the hex)
  - `role_name(pid) -> str`, `dashboard_slug(pid) -> str`, `dashboard_title(project_name: str) -> str`
  - `connection_uri(pid, template: str) -> str` (raises `ValueError`)
  - `project_state(body) -> {"name": str, "members": dict[str, str]}` (raises `InvalidProjectState`)
  - `token_matches(header: str | None, expected: str | None) -> bool`
  - `role_names_for(subject: str, memberships: Iterable[tuple[str, str]]) -> list[str]`
  - `may_reach(project_hex: str | None, *, is_admin: bool, member_of: set[str], bridge: bool = False) -> bool`
  - `projects_reached(objects: dict) -> set[str]` (duck-typed over Superset's objects)
  - `EXPECTED_TABLES: tuple[tuple[str, str], ...]`
  - `default_charts(present: set[tuple[str, str]]) -> list[dict]`
  - `chart_params(spec: dict, dataset_id: int) -> dict`
  - `dashboard_layout(title: str, chart_ids: list[int]) -> dict`

- [ ] **Step 1: Write the failing tests.** Create `tests/test_projects.py`:

```python
"""One project, one connection, one role, one dashboard: the rules, without Superset.

Every project has a Postgres database of its own, made by the platform. The
dashboard reads each through a connection of its own, and shows it to that
project's members only. These are the names and the checks; project_sync.py
applies them through Superset.
"""
from types import SimpleNamespace

import pytest

from aisc_ext import projects as rules

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
HEX = "3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"
TEMPLATE = "postgresql+psycopg2://dashboard_ro:pw@localhost:5432/{database}"


def test_the_connection_is_named_after_the_database_the_platform_made():
    # Same example as platform/tests/test_project_databases.py and
    # apps/controls/test/unit/projectDb.test.ts: three languages, one rule.
    assert rules.database_name(PID) == "project_" + HEX
    assert rules.database_name(PID.upper()) == "project_" + HEX


@pytest.mark.parametrize("bad", ["", "abc", "../platform", PID + "x", "project_x; drop database platform"])
def test_anything_but_a_pid_is_refused(bad):
    with pytest.raises(rules.NotAPid):
        rules.database_name(bad)


def test_the_hex_goes_back_to_the_pid():
    assert rules.pid_from_hex(HEX) == PID
    assert rules.pid_of_database("project_" + HEX) == PID
    assert rules.project_of_database("project_" + HEX) == HEX
    for other in ("platform", "AISC Results", "project_" + HEX + "0", "project_" + HEX.upper()):
        assert rules.pid_of_database(other) is None
        assert rules.project_of_database(other) is None


def test_role_slug_and_title():
    assert rules.role_name(PID) == "aisc_project_" + HEX
    assert rules.dashboard_slug(PID) == "project-" + HEX
    assert rules.dashboard_title(" MicroCredit Assist Score ") == "MicroCredit Assist Score: results"


def test_the_uri_names_this_project_as_the_read_only_role():
    assert rules.connection_uri(PID, TEMPLATE) == \
        "postgresql+psycopg2://dashboard_ro:pw@localhost:5432/project_" + HEX


def test_a_template_with_nowhere_to_put_the_database_is_refused():
    with pytest.raises(ValueError, match=r"\{database\}"):
        rules.connection_uri(PID, "postgresql+psycopg2://dashboard_ro:pw@localhost:5432/platform")


def test_a_role_that_could_write_is_refused():
    with pytest.raises(ValueError, match="read-only"):
        rules.connection_uri(PID, "postgresql+psycopg2://platform_rw:pw@localhost:5432/{database}")


def test_a_project_state_is_a_name_and_its_members():
    state = rules.project_state({"name": " MCAS ", "members": [
        {"subject": "s1", "role": "owner"}, {"subject": "s2", "role": "viewer"}]})
    assert state == {"name": "MCAS", "members": {"s1": "owner", "s2": "viewer"}}
    assert rules.project_state({"name": "x", "members": []}) == {"name": "x", "members": {}}


@pytest.mark.parametrize("body", [
    None, [], {}, {"name": ""}, {"name": "x", "members": "s1"},
    {"name": "x", "members": [{"subject": "", "role": "viewer"}]},
    {"name": "x", "members": [{"subject": "s1", "role": "admin"}]},
    {"name": "x", "members": ["s1"]},
])
def test_anything_else_is_refused(body):
    with pytest.raises(rules.InvalidProjectState):
        rules.project_state(body)


def test_the_bridge_token():
    assert rules.token_matches("Bearer s3cret", "s3cret")
    assert not rules.token_matches("Bearer wrong", "s3cret")
    assert not rules.token_matches("s3cret", "s3cret")
    assert not rules.token_matches("", "s3cret")
    assert not rules.token_matches(None, "s3cret")
    # No token configured: the door is shut, not open.
    assert not rules.token_matches("Bearer ", "")
    assert not rules.token_matches("Bearer anything", "")
    assert not rules.token_matches("Bearer anything", None)


def test_the_projects_a_person_gets_roles_for():
    rows = [(HEX, "alice"), ("a" * 32, "bob"), ("b" * 32, "alice")]
    assert rules.role_names_for("alice", rows) == ["aisc_project_" + HEX, "aisc_project_" + "b" * 32]
    assert rules.role_names_for("eve", rows) == []


def test_who_may_reach_a_project_database():
    assert rules.may_reach(HEX, is_admin=False, member_of={HEX})
    assert not rules.may_reach(HEX, is_admin=False, member_of={"a" * 32})
    assert not rules.may_reach(HEX, is_admin=False, member_of=set())
    assert rules.may_reach(HEX, is_admin=True, member_of=set())
    assert rules.may_reach(HEX, is_admin=False, member_of=set(), bridge=True)
    assert rules.may_reach(None, is_admin=False, member_of=set())  # not a project's database


def _db(name):
    return SimpleNamespace(database_name=name)


def test_what_a_request_reaches_is_read_from_the_object_not_the_client():
    ds = SimpleNamespace(database=_db("project_" + HEX))
    assert rules.projects_reached({"datasource": ds}) == {HEX}
    assert rules.projects_reached({"chart": SimpleNamespace(datasource=ds)}) == {HEX}
    assert rules.projects_reached({"query_context": SimpleNamespace(datasource=ds)}) == {HEX}
    assert rules.projects_reached({"viz": SimpleNamespace(datasource=ds)}) == {HEX}
    assert rules.projects_reached({"query": SimpleNamespace(database=_db("project_" + HEX))}) == {HEX}
    assert rules.projects_reached({"database": _db("project_" + HEX)}) == {HEX}
    assert rules.projects_reached({"dashboard": SimpleNamespace(slug="project-" + HEX, datasources=[])}) == {HEX}
    assert rules.projects_reached({"dashboard": SimpleNamespace(slug="hand-made", datasources=[ds])}) == {HEX}
    assert rules.projects_reached({"chart": SimpleNamespace(datasource=None)}) == set()
    assert rules.projects_reached({"database": _db("examples")}) == set()
    assert rules.projects_reached({}) == set()


def test_an_empty_project_gets_no_charts_and_says_what_it_waits_for():
    assert rules.default_charts(set()) == []
    layout = rules.dashboard_layout("P: results", [])
    parts = [c for c in layout.values() if isinstance(c, dict)]
    notes = [c for c in parts if c.get("type") == "MARKDOWN"]
    assert len(notes) == 1
    assert "engine.evaluation" in notes[0]["meta"]["code"] and "engine.measurement" in notes[0]["meta"]["code"]
    assert not [c for c in parts if c.get("type") == "CHART"]


def test_the_engine_results_give_three_charts():
    charts = rules.default_charts(set(rules.EXPECTED_TABLES))
    assert [c["key"] for c in charts] == ["evaluations", "evaluations-by-status", "average-score"]
    assert {c["table"] for c in charts} == set(rules.EXPECTED_TABLES)


def test_only_the_charts_whose_table_is_there():
    assert [c["key"] for c in rules.default_charts({("engine", "evaluation")})] == \
        ["evaluations", "evaluations-by-status"]


def test_a_chart_is_tagged_so_it_is_found_again():
    spec = rules.default_charts(set(rules.EXPECTED_TABLES))[0]
    params = rules.chart_params(spec, 42)
    assert params["datasource"] == "42__table"
    assert params["aisc_default"] == "evaluations"
    assert params["viz_type"] == spec["viz_type"]


def test_the_layout_places_every_chart_once_and_names_only_parts_it_has():
    layout = rules.dashboard_layout("P: results", [7, 8, 9])
    parts = {k: v for k, v in layout.items() if isinstance(v, dict)}
    ids = [c["meta"]["chartId"] for c in parts.values() if c.get("type") == "CHART"]
    assert sorted(ids) == [7, 8, 9]
    for part in parts.values():
        for child in part.get("children", []):
            assert child in parts
    assert layout["HEADER_ID"]["meta"]["text"] == "P: results"
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/results-dashboard && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_projects.py`
Expected: collection error, `ImportError: cannot import name 'projects' from 'aisc_ext'`.

- [ ] **Step 3: Implement.** Create `aisc_ext/projects.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""One project, one Superset connection: the names and the rules, without Superset.

Every project has its own Postgres database, project_<pid hex>, made by the
platform. The dashboard reads it through one connection per project, as the
read-only role, and shows it only to that project's members: one Superset role
per project, and a membership check on every object a request reaches. This
module decides the names, the shape of what is registered and who may reach
what; project_sync.py and project_gate.py apply it through Superset.

Kept free of Superset and Flask imports so it unit-tests without the app.
"""
from __future__ import annotations

import hmac
import re
from typing import Iterable

_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HEX = re.compile(r"^[0-9a-f]{32}$")

#: The role every project connection uses. Anything else can write.
READ_ONLY_ROLE = "dashboard_ro"
ROLE_PREFIX = "aisc_project_"
SLUG_PREFIX = "project-"
DATABASE_PREFIX = "project_"
#: The platform's membership roles (platform/platform_service/membership.py:18).
MEMBER_ROLES = ("viewer", "editor", "owner")

#: The execution engine's results, which the default dashboard is drawn from.
#: They reach a project's database with Plan 4; until then the dashboard says
#: what it waits for instead of failing.
EXPECTED_TABLES = (("engine", "evaluation"), ("engine", "measurement"))

EMPTY_NOTE = (
    "### No results yet\n\n"
    "This dashboard reads this project's own database, and nothing else. Its "
    "charts appear once the execution engine has written evaluations here: "
    "it reads `engine.evaluation` and `engine.measurement`."
)
CHARTS_NOTE = "Results of this project only, read from its own database."


class NotAPid(ValueError):
    """Only a project id may name a connection: anything else is refused unread."""


class InvalidProjectState(ValueError):
    """What the platform sent is not a project's name and members."""


def is_hex(text: str) -> bool:
    return bool(_HEX.match(text or ""))


def project_hex(pid) -> str:
    text = str(pid).lower()
    if not _PID.match(text):
        raise NotAPid(f"not a project id: {text!r}")
    return text.replace("-", "")


def pid_from_hex(hex_: str) -> str:
    if not is_hex(hex_):
        raise NotAPid(f"not a project id: {hex_!r}")
    h = hex_
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def database_name(pid) -> str:
    return DATABASE_PREFIX + project_hex(pid)


def project_of_database(name: str) -> str | None:
    """The project hex a connection or database name belongs to, or None."""
    name = name or ""
    if name.startswith(DATABASE_PREFIX) and is_hex(name[len(DATABASE_PREFIX):]):
        return name[len(DATABASE_PREFIX):]
    return None


def pid_of_database(name: str) -> str | None:
    found = project_of_database(name)
    return pid_from_hex(found) if found else None


def role_name(pid) -> str:
    return ROLE_PREFIX + project_hex(pid)


def dashboard_slug(pid) -> str:
    return SLUG_PREFIX + project_hex(pid)


def dashboard_title(project_name: str) -> str:
    return f"{(project_name or '').strip() or 'Project'}: results"


def connection_uri(pid, template: str) -> str:
    template = (template or "").strip()
    if "{database}" not in template:
        raise ValueError("AISC_PROJECT_DB_URI must contain {database}")
    if f"//{READ_ONLY_ROLE}:" not in template and f"//{READ_ONLY_ROLE}@" not in template:
        raise ValueError(
            f"AISC_PROJECT_DB_URI must connect as the read-only role {READ_ONLY_ROLE!r}: "
            "the dashboard reads a project's data and writes none of it."
        )
    return template.replace("{database}", database_name(pid))


def project_state(body) -> dict:
    """The platform's word on one project: its name, and everybody in it."""
    if not isinstance(body, dict):
        raise InvalidProjectState("a project's state is an object")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InvalidProjectState("a project has a name")
    members = body.get("members", [])
    if not isinstance(members, list):
        raise InvalidProjectState("members is a list")
    out: dict[str, str] = {}
    for member in members:
        if not isinstance(member, dict):
            raise InvalidProjectState("a member is an object")
        subject, role = member.get("subject"), member.get("role")
        if not isinstance(subject, str) or not subject.strip():
            raise InvalidProjectState("a member has a subject")
        if role not in MEMBER_ROLES:
            raise InvalidProjectState(f"a member's role is one of {', '.join(MEMBER_ROLES)}")
        out[subject.strip()] = role
    return {"name": name.strip(), "members": out}


def token_matches(header: str | None, expected: str | None) -> bool:
    """Bearer <expected>, compared in constant time. No expected token: no."""
    expected = (expected or "").strip()
    if not expected:
        return False
    header = (header or "").strip()
    if not header.lower().startswith("bearer "):
        return False
    given = header[len("bearer "):].strip()
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


def role_names_for(subject: str, memberships: Iterable[tuple[str, str]]) -> list[str]:
    """The project roles a person holds, from (project hex, subject) rows."""
    return sorted(ROLE_PREFIX + h for h, s in memberships if s == subject)


def may_reach(project_hex: str | None, *, is_admin: bool, member_of: set[str],
              bridge: bool = False) -> bool:
    """May this caller reach this project's database?

    `bridge` is the platform registering the project, which reads the
    database's table list and nothing else. An admin may, as the platform
    lets an admin open any project. Anybody else only when they are in it.
    """
    if project_hex is None:
        return True
    if bridge or is_admin:
        return True
    return project_hex in member_of


def projects_reached(objects: dict) -> set[str]:
    """The projects whose database the objects of one access check belong to.

    Read from the objects themselves (a dashboard's slug and datasets, a
    chart's dataset, a dataset's connection), never from anything a client
    said, so asking for another project's chart by id cannot name this one.
    """
    found: set[str] = set()

    def add(database) -> None:
        h = project_of_database(getattr(database, "database_name", "") or "")
        if h:
            found.add(h)

    def add_datasource(ds) -> None:
        if ds is not None:
            add(getattr(ds, "database", None))

    dashboard = objects.get("dashboard")
    if dashboard is not None:
        slug = getattr(dashboard, "slug", "") or ""
        if slug.startswith(SLUG_PREFIX) and is_hex(slug[len(SLUG_PREFIX):]):
            found.add(slug[len(SLUG_PREFIX):])
        for ds in getattr(dashboard, "datasources", None) or ():
            add_datasource(ds)
    for key in ("chart", "query_context", "viz"):
        holder = objects.get(key)
        if holder is not None:
            add_datasource(getattr(holder, "datasource", None))
    add_datasource(objects.get("datasource"))
    add(objects.get("database"))
    query = objects.get("query")
    if query is not None:
        add(getattr(query, "database", None))
    return found


def _count(label: str) -> dict:
    return {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": label}


def default_charts(present: set[tuple[str, str]]) -> list[dict]:
    """The default charts whose table is in this project's database.

    They name only columns the engine's models have had since before Plan 4
    (evaluation.status, measurement.score), so they need nothing new from it.
    """
    specs = [
        {"key": "evaluations", "table": ("engine", "evaluation"), "name": "Evaluations",
         "viz_type": "big_number_total",
         "params": {"metric": _count("Evaluations"), "subheader": "run in this project",
                    "y_axis_format": "SMART_NUMBER"}},
        {"key": "evaluations-by-status", "table": ("engine", "evaluation"),
         "name": "Evaluations by status", "viz_type": "table",
         "params": {"query_mode": "aggregate", "groupby": ["status"],
                    "metrics": [_count("Evaluations")], "row_limit": 100, "order_desc": True}},
        {"key": "average-score", "table": ("engine", "measurement"), "name": "Average score",
         "viz_type": "big_number_total",
         "params": {"metric": {"expressionType": "SQL", "sqlExpression": "AVG(score)",
                               "label": "Average score"},
                    "subheader": "over every measurement", "y_axis_format": ".3f"}},
    ]
    return [s for s in specs if s["table"] in present]


def chart_params(spec: dict, dataset_id: int) -> dict:
    return {"datasource": f"{dataset_id}__table", "viz_type": spec["viz_type"],
            "aisc_default": spec["key"], **spec["params"]}


def dashboard_layout(title: str, chart_ids: list[int]) -> dict:
    """Superset's position_json: a header, a note, and the charts in one row."""
    layout: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": title}},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-note"],
                    "parents": ["ROOT_ID"]},
        "ROW-note": {"type": "ROW", "id": "ROW-note", "children": ["MARKDOWN-note"],
                     "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "MARKDOWN-note": {"type": "MARKDOWN", "id": "MARKDOWN-note", "children": [],
                          "meta": {"code": CHARTS_NOTE if chart_ids else EMPTY_NOTE,
                                   "width": 12, "height": 20}},
    }
    if chart_ids:
        row = {"type": "ROW", "id": "ROW-charts", "children": [],
               "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for chart_id in chart_ids:
            key = f"CHART-{chart_id}"
            layout[key] = {"type": "CHART", "id": key, "children": [],
                           "meta": {"chartId": chart_id, "width": 4, "height": 50}}
            row["children"].append(key)
        layout["ROW-charts"] = row
        layout["GRID_ID"]["children"].append("ROW-charts")
    return layout
```

- [ ] **Step 4: Run them.**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_projects.py`
Expected: all PASS (37 test cases, counting the parametrized ones).

- [ ] **Step 5: Commit** (inside `apps/results-dashboard`).

```bash
git add aisc_ext/projects.py tests/test_projects.py
git commit -m "The rules of one connection, one role and one dashboard per project"
```

---

### Task 4: Superset keeps one connection, role and dashboard per project, behind a bridge

**Files:**
- Create: `apps/results-dashboard/aisc_ext/project_model.py`, `aisc_ext/project_sync.py`, `aisc_ext/bridge.py`
- Modify: `apps/results-dashboard/superset_config.py`:
  - `FEATURE_FLAGS`, lines 54-72: add `DASHBOARD_RBAC`
  - `FLASK_APP_MUTATOR`: insert after line 183 (`with app.app_context():`)
- Modify: `docker-compose.development.yml` (the `dashboard` service `environment`, lines 444-457)
- Modify: `scripts/secrets.sh` (lines 31-43, plus a new block after line 54)
- Test: create `apps/results-dashboard/scripts/verify_projects.py` and `apps/results-dashboard/scripts/verify_projects.sh`

**Interfaces:**
- Consumes: `aisc_ext.projects` (Task 3); `dashboard_ro` CONNECT and SELECT in project databases (Task 2).
- Produces:
  - `project_sync.ensure_project(pid: str, name: str, members: dict[str, str]) -> dict` → `{"database": str, "role": str, "dashboard": str, "datasets": list[str], "charts": int, "members": int}`. Idempotent.
  - `project_sync.forget_project(pid: str) -> bool`
  - `project_sync.registered_pids() -> list[str]`
  - `project_sync.remember_subject(user, subject: str) -> None`
  - `project_sync.project_roles_for(subject: str) -> list[Role]`
  - `project_sync.present_tables(database) -> set[tuple[str, str]]`
  - HTTP:
    - `PUT /aisc/bridge/projects/{pid}` with body `{"name": str, "members": [{"subject": str, "role": "viewer"|"editor"|"owner"}]}` → 200 `{"result": ensure_project(...)}`, 401 bad or missing token, 422 bad pid or body, 500 registration failed (rolled back).
    - `DELETE /aisc/bridge/projects/{pid}` → 204 (also when absent), 401, 422.
    - `GET /aisc/bridge/projects` → 200 `{"result": [pid, …]}`, 401.
    - `GET /aisc/p/{pid}` → 302 to `/login/?next=…` (anonymous), 302 to `/superset/dashboard/project-<hex>/` (may open), 404 otherwise.
  - Env on `dashboard`: `AISC_PROJECT_DB_URI=postgresql+psycopg2://dashboard_ro:dashboard_ro@localhost:5432/{database}`, `DASHBOARD_BRIDGE_TOKEN`.

- [ ] **Step 1: Write the failing in-container test.** Create `scripts/verify_projects.sh`:

```bash
#!/usr/bin/env bash
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# Per-project dashboards, checked inside the running Superset.
#
#   apps/results-dashboard/scripts/verify_projects.sh
#
# Makes two throwaway project databases the platform's own way (provision(), so
# the whole project template applies, 0005_dashboard.sql included), gives the
# first the engine's two results tables the way the engine's template and
# migrations will once Plan 4 has run, runs verify_projects.py inside the
# dashboard container, and drops both databases afterwards, whatever happens.
# Neither has a core.project row, so the platform never pushes them.
set -uo pipefail
cd "$(dirname "$0")/.."
A=$(python3 -c 'import uuid; print(uuid.uuid4())')
B=$(python3 -c 'import uuid; print(uuid.uuid4())')
provision() { docker exec platform python -c "from platform_service import db, projectdb; print(projectdb.provision(db.dsn(), '$1'))" 2>/dev/null | tail -1; }
drop()      { docker exec platform python -c "from platform_service import db, projectdb; projectdb.drop(db.dsn(), '$1')" >/dev/null 2>&1; }
trap 'drop "$A"; drop "$B"' EXIT
DA=$(provision "$A"); DB_B=$(provision "$B")
case "$DA|$DB_B" in
  project_*"|"project_*) ;;
  *) echo "FAIL could not make the two project databases ($DA, $DB_B)"; exit 1 ;;
esac
as() { docker exec postgres psql "postgresql://$1:$1@localhost:5432/$2" -v ON_ERROR_STOP=1 -Atq -c "$3"; }
has=$(as platform_rw "$DA" "select to_regclass('engine.evaluation') is not null and to_regclass('engine.measurement') is not null")
if [ "$has" != "t" ]; then
  as platform_rw "$DA" "create schema if not exists engine; grant usage, create on schema engine to engine_rw; grant connect on database $DA to engine_rw" || exit 1
  as engine_rw "$DA" "create table engine.evaluation (id bigserial primary key, status varchar(255) not null);
                      create table engine.measurement (id bigserial primary key, score double precision not null);
                      insert into engine.evaluation (status) values ('Done'), ('Done'), ('Failed');
                      insert into engine.measurement (score) values (0.5), (0.7)" || exit 1
fi
docker exec -i -e AISC_VERIFY_PIDS="$A,$B" dashboard python - < scripts/verify_projects.py
```

Create `scripts/verify_projects.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Per-project dashboards, checked inside a running Superset.

    apps/results-dashboard/scripts/verify_projects.sh

The wrapper makes two throwaway project databases and passes their pids in
AISC_VERIFY_PIDS: A has the engine's two results tables, B has none. This
registers both through the code the platform's bridge call runs, builds three
people (alice in A, bob in B, eve in neither) and an admin, and asks
Superset's own test client, by id and not through any menu, for what each may
and may not see. It removes everything it made, whatever the outcome. Exit
status 0 means every check held.
"""
import os
import sys
import uuid

from superset.app import create_app

app = create_app()
TAG = f"zz-verify-projects-{uuid.uuid4().hex[:6]}"
A, B = os.environ["AISC_VERIFY_PIDS"].split(",")
TOKEN = os.environ.get("DASHBOARD_BRIDGE_TOKEN", "")
results = []
ctx = {}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def sub(who):
    return f"{TAG}-sub-{who}"


def people():
    from superset import db, security_manager as sm
    from aisc_ext.project_sync import remember_subject

    viewer, admin = sm.find_role("AiscViewer"), sm.find_role("Admin")
    made = {}
    for who, roles in (("alice", [viewer]), ("bob", [viewer]), ("eve", [viewer]), ("ada", [admin])):
        user = sm.add_user(f"{TAG}-{who}", who.title(), "Verify", f"{TAG}-{who}@example.org",
                           roles, password=uuid.uuid4().hex)
        remember_subject(user, sub(who))
        made[who] = user.id
    db.session.commit()
    return made


def client_for(user_id):
    c = app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return c


def anonymous():
    return app.test_client()


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def chart_data(c, key="A"):
    """One default chart's data, asked the way a dashboard asks, by ids."""
    ds, chart, dash = ctx[key]
    return c.post("/api/v1/chart/data", json={
        "datasource": {"id": ds, "type": "table"},
        "queries": [{"metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "n"}],
                     "columns": [], "row_limit": 10}],
        "form_data": {"slice_id": chart, "dashboardId": dash, "viz_type": "big_number_total"},
        "result_format": "json", "result_type": "full",
    })


def run_registration(ids):
    from superset import db, security_manager as sm
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from aisc_ext import projects as rules
    from aisc_ext.project_sync import ensure_project, registered_pids

    with app.app_context():
        first = ensure_project(A, f"{TAG} A", {sub("alice"): "viewer"})
        again = ensure_project(A, f"{TAG} A", {sub("alice"): "viewer"})
        empty = ensure_project(B, f"{TAG} B", {sub("bob"): "editor"})
        listed = set(registered_pids())
    check("project A gets a connection to its own database", first["database"] == rules.database_name(A), first)
    check("and the engine's results as datasets",
          first["datasets"] == ["engine.evaluation", "engine.measurement"], first["datasets"])
    check("and three default charts", first["charts"] == 3, first)
    check("registering it again adds nothing", again == first, again)
    check("an empty project still gets its dashboard, with no charts",
          empty["charts"] == 0 and empty["datasets"] == [], empty)
    check("both are listed as registered", {A, B} <= listed, listed)

    with app.app_context():
        for pid in (A, B):
            d = db.session.query(Database).filter_by(database_name=rules.database_name(pid)).one()
            check(f"{pid[:8]}: connects as dashboard_ro to its own database, and nothing else",
                  d.sqlalchemy_uri.startswith("postgresql+psycopg2://dashboard_ro:")
                  and d.sqlalchemy_uri.endswith("/" + rules.database_name(pid)), d.sqlalchemy_uri)
            check(f"{pid[:8]}: may write nothing", not d.allow_dml and not d.allow_ctas and not d.allow_cvas)
            role = sm.find_role(rules.role_name(pid))
            held = sorted((p.permission.name, p.view_menu.name) for p in role.permissions)
            check(f"{pid[:8]}: its role reaches its own connection and nothing else",
                  held == [("database_access", d.perm)], held)
            dash = db.session.query(Dashboard).filter_by(slug=rules.dashboard_slug(pid)).one()
            check(f"{pid[:8]}: its dashboard is published to its role only",
                  dash.published and [r.name for r in dash.roles] == [role.name],
                  (dash.published, [r.name for r in dash.roles]))
            ctx[f"db_{pid}"] = d.id
            ctx[f"dash_{pid}"] = dash.id
        dash_a = db.session.query(Dashboard).filter_by(slug=rules.dashboard_slug(A)).one()
        chart = next(s for s in dash_a.slices if s.slice_name == "Evaluations")
        ctx["A"] = (chart.datasource_id, chart.id, dash_a.id)


def run_access(ids):
    from aisc_ext import projects as rules

    a, b, e, x = (client_for(ids[k]) for k in ("alice", "bob", "eve", "ada"))
    slug_a, slug_b = rules.dashboard_slug(A), rules.dashboard_slug(B)
    ds, chart, dash = ctx["A"]

    # -- step 6 -----------------------------------------------------------------
    r = a.get(f"/aisc/p/{A}")
    check("step 6 opens a member's own project dashboard",
          r.status_code == 302 and r.headers.get("Location", "").endswith(f"/superset/dashboard/{slug_a}/"),
          (r.status_code, r.headers.get("Location")))
    check("and not another project's: not found for her", a.get(f"/aisc/p/{B}").status_code == 404)
    check("someone in neither project finds neither",
          e.get(f"/aisc/p/{A}").status_code == 404 and e.get(f"/aisc/p/{B}").status_code == 404)
    check("a path that is not a project is not found", a.get("/aisc/p/abc").status_code == 404)
    r = anonymous().get(f"/aisc/p/{A}")
    check("an anonymous visitor is sent to sign in first",
          r.status_code == 302 and "/login/" in r.headers.get("Location", ""),
          (r.status_code, r.headers.get("Location")))
    check("an admin opens any project's", x.get(f"/aisc/p/{B}").status_code == 302)

    # -- by id, not through a menu ----------------------------------------------
    check("the member opens her dashboard by id", a.get(f"/api/v1/dashboard/{dash}").status_code == 200)
    r = b.get(f"/api/v1/dashboard/{dash}")
    check("a non-member asking for that dashboard by id is refused", r.status_code in (403, 404), r.status_code)
    check("and for its charts", b.get(f"/api/v1/dashboard/{dash}/charts").status_code in (403, 404))
    check("and for its page", b.get(f"/superset/dashboard/{slug_a}/").status_code != 200)
    check("and for its chart by id", b.get(f"/api/v1/chart/{chart}").status_code in (403, 404))
    check("and for its dataset by id", b.get(f"/api/v1/dataset/{ds}").status_code in (403, 404))
    check("and for its connection's schemas",
          b.get(f"/api/v1/database/{ctx[f'db_{A}']}/schemas/").status_code in (403, 404))
    r = chart_data(a)
    check("the member gets her project's chart data", r.status_code == 200, (r.status_code, r.data[:300]))
    r = chart_data(b)
    check("a non-member asking for that chart's data by id is refused", r.status_code == 403,
          (r.status_code, r.data[:300]))
    check("so is someone in no project", chart_data(e).status_code == 403)
    check("an admin reads it", chart_data(x).status_code == 200)

    # -- lists --------------------------------------------------------------------
    def listed(c, what, field):
        r = c.get(f"/api/v1/{what}/?q=(page_size:100)")
        return {row.get(field) for row in (r.json or {}).get("result", [])} if r.status_code == 200 else set()

    check("her dashboards list shows her project's and not the other's",
          slug_a in listed(a, "dashboard", "slug") and slug_b not in listed(a, "dashboard", "slug"))
    check("his shows his and not hers",
          slug_b in listed(b, "dashboard", "slug") and slug_a not in listed(b, "dashboard", "slug"))
    check("someone in no project lists neither", not ({slug_a, slug_b} & listed(e, "dashboard", "slug")))
    check("his charts list has none of project A's", chart not in listed(b, "chart", "id"))
    check("his datasets list has none of project A's", ds not in listed(b, "dataset", "id"))


def run_membership_change(ids):
    from aisc_ext.project_sync import ensure_project

    a = client_for(ids["alice"])
    with app.app_context():
        ensure_project(A, f"{TAG} A", {})
    check("removed from the project, step 6 is not found for her any more",
          a.get(f"/aisc/p/{A}").status_code == 404)
    check("nor its data, on the very next request", chart_data(a).status_code == 403)
    with app.app_context():
        ensure_project(A, f"{TAG} A", {sub("alice"): "viewer"})
    check("added back, it opens again", a.get(f"/aisc/p/{A}").status_code == 302)
    check("and its data is hers again", chart_data(a).status_code == 200)


def run_bridge_door(ids):
    c = anonymous()
    url = f"/aisc/bridge/projects/{A}"
    body = {"name": f"{TAG} A", "members": [{"subject": sub("alice"), "role": "viewer"}]}
    check("the dashboard has a bridge token to check against", bool(TOKEN))
    check("the bridge refuses a call with no token", c.put(url, json=body).status_code == 401)
    check("and one with the wrong token",
          c.put(url, json=body, headers={"Authorization": "Bearer not-it"}).status_code == 401)
    check("and a listing without one", c.get("/aisc/bridge/projects").status_code == 401)
    r = c.put(url, json=body, headers=auth())
    check("the platform's token registers a project, with no CSRF token", r.status_code == 200,
          (r.status_code, r.data[:300]))
    check("a body that is not a project's state is refused",
          c.put(url, json={"name": "x", "members": "all"}, headers=auth()).status_code == 422)
    check("a path that is not a project is refused",
          c.put("/aisc/bridge/projects/abc", json=body, headers=auth()).status_code == 422)
    r = c.get("/aisc/bridge/projects", headers=auth())
    check("the listing names both projects", r.status_code == 200 and {A, B} <= set(r.json.get("result", [])))


def run_forget(ids):
    from superset import db, security_manager as sm
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from aisc_ext import projects as rules

    c = anonymous()
    check("deleting a project removes it from the dashboard",
          c.delete(f"/aisc/bridge/projects/{B}", headers=auth()).status_code == 204)
    with app.app_context():
        gone = (db.session.query(Database).filter_by(database_name=rules.database_name(B)).count() == 0
                and sm.find_role(rules.role_name(B)) is None
                and db.session.query(Dashboard).filter_by(slug=rules.dashboard_slug(B)).count() == 0)
    check("its connection, role and dashboard are gone", gone)
    check("deleting it again is harmless", c.delete(f"/aisc/bridge/projects/{B}", headers=auth()).status_code == 204)
    check("and step 6 of it is not found", client_for(ids["bob"]).get(f"/aisc/p/{B}").status_code == 404)


#: In order. Later tasks insert their phases before run_forget.
PHASES = [run_registration, run_access, run_membership_change, run_bridge_door, run_forget]


def cleanup():
    from superset import db
    from flask_appbuilder.security.sqla.models import User
    from aisc_ext.project_sync import forget_project

    db.session.rollback()
    for pid in (A, B):
        try:
            forget_project(pid)
        except Exception as exc:  # report, and carry on removing the rest
            print(f"cleanup: {pid}: {exc}")
    for user in db.session.query(User).filter(User.username.like(f"{TAG}%")).all():
        db.session.delete(user)
    db.session.commit()
    print("cleanup: done")


def main():
    with app.app_context():
        ids = people()
    try:
        for phase in PHASES:
            phase(ids)
    finally:
        with app.app_context():
            cleanup()
    failed = len(results) - sum(results)
    print(f"\n{sum(results)} passed, {failed} failed")
    sys.exit(0 if results and not failed else 1)


main()
```

`chmod +x scripts/verify_projects.sh`.

- [ ] **Step 2: Run it and watch it fail.**

Run: `apps/results-dashboard/scripts/verify_projects.sh`
Expected: `ModuleNotFoundError: No module named 'aisc_ext.project_sync'` from `people()`, a non-zero exit, and the two databases dropped by the trap. Check the drop: `docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_database where datname like \$\$project\_%\$\$"'` shows the same count as before.

- [ ] **Step 3: The two tables.** Create `aisc_ext/project_model.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Who is in which project, as the platform last said, and who signed in as whom.

In Superset's metadata database. Written only by the platform's bridge call
(members) and by sign-in (subjects). Runtime-only: imports Superset's Model.
"""
from sqlalchemy import Column, ForeignKey, Integer, String

from superset import db  # type: ignore

Model = db.Model


class AiscProjectMember(Model):
    """One project's members, replaced whole each time the platform sends them."""
    __tablename__ = "aisc_project_member"
    project_hex = Column(String(32), primary_key=True)
    subject = Column(String(255), primary_key=True, index=True)
    role = Column(String(16), nullable=False)


class AiscUserSubject(Model):
    """The Keycloak subject a Superset user signed in as. The platform's
    membership is keyed on the subject, and Superset's users on a username."""
    __tablename__ = "aisc_user_subject"
    user_id = Column(Integer, ForeignKey("ab_user.id", ondelete="CASCADE"), primary_key=True)
    subject = Column(String(255), nullable=False, unique=True)
```

- [ ] **Step 4: Apply a project through Superset's models.** Create `aisc_ext/project_sync.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Put one project's connection, role, datasets and dashboard in Superset, or take them out.

What is registered is decided in projects.py. This applies it through
Superset's own models, as results_db.py used to for the one shared
connection. Every call is idempotent, so the platform can send the same
project again whenever it likes, and does, once a minute.

Runtime-only (Superset imports inside the functions).
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager

from sqlalchemy import text

from aisc_ext import projects as rules

log = logging.getLogger(__name__)


def _template() -> str:
    return os.environ.get("AISC_PROJECT_DB_URI", "")


@contextmanager
def as_the_bridge():
    """Mark what follows as the registration reading a table list, which the
    membership gate (project_gate.py) lets through without a signed-in user."""
    from flask import g

    before = getattr(g, "aisc_bridge", False)
    g.aisc_bridge = True
    try:
        yield
    finally:
        g.aisc_bridge = before


def present_tables(database) -> set[tuple[str, str]]:
    """Which of the expected results tables this project's database has, and
    dashboard_ro may read. Empty when it cannot be asked yet."""
    wanted = {f"{s}.{t}": (s, t) for s, t in rules.EXPECTED_TABLES}
    try:
        with database.get_sqla_engine() as engine, engine.connect() as conn:
            rows = conn.execute(text(
                "select n.nspname || '.' || c.relname from pg_class c"
                "  join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname || '.' || c.relname = any(:names)"
                "   and has_schema_privilege(n.oid, 'USAGE')"
                "   and has_table_privilege(c.oid, 'SELECT')"
            ), {"names": list(wanted)}).fetchall()
    except Exception as exc:  # not provisioned yet, or Postgres restarting
        log.warning("AISC project database %s not readable yet: %s", database.database_name, exc)
        return set()
    return {wanted[r[0]] for r in rows}


def _sync_role_holders(role, subjects: set[str]) -> None:
    """Exactly the signed-in people whose subject is in the project hold its role."""
    from superset import db, security_manager as sm
    from aisc_ext.project_model import AiscUserSubject

    for row in db.session.query(AiscUserSubject).all():
        user = db.session.get(sm.user_model, row.user_id)
        if user is None:
            continue
        holds = role in user.roles
        if row.subject in subjects and not holds:
            user.roles.append(role)
        elif row.subject not in subjects and holds:
            user.roles.remove(role)


def ensure_project(pid: str, name: str, members: dict[str, str]) -> dict:
    from superset import db, security_manager as sm
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice
    from aisc_ext.project_model import AiscProjectMember

    hex_ = rules.project_hex(pid)
    dbname = rules.database_name(pid)

    database = db.session.query(Database).filter_by(database_name=dbname).one_or_none()
    if database is None:
        database = Database(database_name=dbname)
        db.session.add(database)
    database.set_sqlalchemy_uri(rules.connection_uri(pid, _template()))
    database.expose_in_sqllab = True
    database.allow_dml = False
    database.allow_ctas = False
    database.allow_cvas = False
    database.allow_file_upload = False
    database.allow_run_async = False
    db.session.flush()  # the id, and database_access via Superset's own after_insert hook

    role = sm.find_role(rules.role_name(pid)) or sm.add_role(rules.role_name(pid))
    access = sm.add_permission_view_menu("database_access", database.perm)
    for pvm in list(role.permissions):
        if pvm is not access:
            role.permissions.remove(pvm)
    if access not in role.permissions:
        role.permissions.append(access)

    with as_the_bridge():
        present = present_tables(database)
        datasets = {}
        for schema, table in sorted(present):
            ds = (db.session.query(SqlaTable)
                  .filter_by(database_id=database.id, schema=schema, table_name=table).one_or_none())
            if ds is None:
                ds = SqlaTable(table_name=table, schema=schema, database=database)
                db.session.add(ds)
                db.session.flush()
                ds.fetch_metadata()
            datasets[(schema, table)] = ds

    ids = [d.id for d in datasets.values()] or [-1]
    existing = {}
    for slc in db.session.query(Slice).filter(Slice.datasource_type == "table",
                                              Slice.datasource_id.in_(ids)):
        key = json.loads(slc.params or "{}").get("aisc_default")
        if key:
            existing[key] = slc
    charts, changed = [], False
    for spec in rules.default_charts(present):
        slc = existing.get(spec["key"])
        if slc is None:
            ds = datasets[spec["table"]]
            slc = Slice(slice_name=spec["name"], viz_type=spec["viz_type"], datasource_type="table",
                        datasource_id=ds.id, params=json.dumps(rules.chart_params(spec, ds.id)))
            db.session.add(slc)
            changed = True
        charts.append(slc)
    db.session.flush()

    slug = rules.dashboard_slug(pid)
    dash = db.session.query(Dashboard).filter_by(slug=slug).one_or_none()
    if dash is None:
        dash = Dashboard(slug=slug)
        db.session.add(dash)
        changed = True
    dash.dashboard_title = rules.dashboard_title(name)
    dash.published = True
    dash.roles = [role]
    if changed:
        # Laid out again only when a default chart arrived, so an admin's own
        # arrangement is not undone every minute.
        dash.slices = charts
        dash.position_json = json.dumps(rules.dashboard_layout(dash.dashboard_title,
                                                               [c.id for c in charts]))

    db.session.query(AiscProjectMember).filter_by(project_hex=hex_).delete()
    for subject, member_role in members.items():
        db.session.add(AiscProjectMember(project_hex=hex_, subject=subject, role=member_role))
    _sync_role_holders(role, set(members))
    db.session.commit()
    return {"database": dbname, "role": role.name, "dashboard": slug,
            "datasets": [f"{s}.{t}" for s, t in sorted(present)],
            "charts": len(charts), "members": len(members)}


def forget_project(pid: str) -> bool:
    """Everything of this project goes: dashboard, its comments and review
    requests, charts, datasets, connection, role, members. True if anything did."""
    from superset import db, security_manager as sm
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice
    from aisc_ext.comments.model import AiscComment
    from aisc_ext.project_model import AiscProjectMember
    from aisc_ext.reviews.model import AiscReviewRequest

    hex_ = rules.project_hex(pid)
    removed = False
    dash = db.session.query(Dashboard).filter_by(slug=rules.dashboard_slug(pid)).one_or_none()
    if dash is not None:
        keys = [str(dash.id), dash.slug]
        db.session.query(AiscComment).filter(AiscComment.dashboard_id.in_(keys)).delete(synchronize_session=False)
        db.session.query(AiscReviewRequest).filter(AiscReviewRequest.dashboard_id.in_(keys)).delete(synchronize_session=False)
        db.session.delete(dash)
        removed = True
    database = db.session.query(Database).filter_by(database_name=rules.database_name(pid)).one_or_none()
    if database is not None:
        tables = db.session.query(SqlaTable).filter_by(database_id=database.id).all()
        ids = [t.id for t in tables] or [-1]
        for slc in db.session.query(Slice).filter(Slice.datasource_type == "table",
                                                  Slice.datasource_id.in_(ids)).all():
            db.session.delete(slc)
        db.session.flush()
        for table in tables:
            db.session.delete(table)
        db.session.flush()
        db.session.delete(database)
        removed = True
    role = sm.find_role(rules.role_name(pid))
    if role is not None:
        db.session.delete(role)
        removed = True
    db.session.query(AiscProjectMember).filter_by(project_hex=hex_).delete()
    db.session.commit()
    return removed


def registered_pids() -> list[str]:
    from superset import db
    from superset.models.core import Database

    names = [n for (n,) in db.session.query(Database.database_name).all()]
    return sorted(p for p in (rules.pid_of_database(n) for n in names) if p)


def remember_subject(user, subject: str) -> None:
    from superset import db
    from aisc_ext.project_model import AiscUserSubject

    db.session.query(AiscUserSubject).filter(AiscUserSubject.subject == subject,
                                             AiscUserSubject.user_id != user.id).delete()
    row = db.session.get(AiscUserSubject, user.id)
    if row is None:
        db.session.add(AiscUserSubject(user_id=user.id, subject=subject))
    else:
        row.subject = subject
    db.session.flush()


def project_roles_for(subject: str) -> list:
    from superset import db, security_manager as sm
    from aisc_ext.project_model import AiscProjectMember

    rows = [(m.project_hex, m.subject)
            for m in db.session.query(AiscProjectMember).filter_by(subject=subject)]
    return [r for r in (sm.find_role(n) for n in rules.role_names_for(subject, rows)) if r]
```

- [ ] **Step 5: The two doors.** Create `aisc_ext/bridge.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Two doors into the dashboard that are not Superset's own.

/aisc/bridge/projects/...: the platform's, server to server. It registers a
project when the project is made, keeps its members in step, and removes it
when the project is deleted. Authorization: Bearer DASHBOARD_BRIDGE_TOKEN,
compared in constant time. With no token configured the door is shut.

/aisc/p/<pid>: a person's, from step 6 of a project. It opens that project's
dashboard if they may, and answers 404 otherwise: the same answer for a
project they are not in as for one that does not exist, as the platform gives.

Runtime-only (Flask and Superset imports).
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

from flask import Blueprint, abort, jsonify, redirect, request

from aisc_ext import projects as rules

log = logging.getLogger(__name__)
bridge = Blueprint("aisc_bridge", __name__)


def _authorised() -> bool:
    return rules.token_matches(request.headers.get("Authorization"),
                               os.environ.get("DASHBOARD_BRIDGE_TOKEN"))


def _refused():
    return jsonify(message="this door takes the platform's bridge token"), 401


@bridge.route("/aisc/bridge/projects", methods=["GET"])
def list_projects():
    if not _authorised():
        return _refused()
    from aisc_ext.project_sync import registered_pids

    return jsonify(result=registered_pids())


@bridge.route("/aisc/bridge/projects/<pid>", methods=["PUT"])
def put_project(pid):
    if not _authorised():
        return _refused()
    try:
        rules.project_hex(pid)
        state = rules.project_state(request.get_json(silent=True))
    except (rules.NotAPid, rules.InvalidProjectState) as exc:
        return jsonify(message=str(exc)), 422
    from superset import db
    from aisc_ext.project_sync import ensure_project

    try:
        done = ensure_project(pid, state["name"], state["members"])
    except Exception:
        db.session.rollback()
        log.exception("AISC project dashboard not registered: %s", rules.database_name(pid))
        return jsonify(message="the project could not be registered; nothing was changed"), 500
    log.debug("AISC project dashboard in step: %s", done["database"])
    return jsonify(result=done), 200


@bridge.route("/aisc/bridge/projects/<pid>", methods=["DELETE"])
def delete_project(pid):
    if not _authorised():
        return _refused()
    try:
        rules.project_hex(pid)
    except rules.NotAPid as exc:
        return jsonify(message=str(exc)), 422
    from superset import db
    from aisc_ext.project_sync import forget_project

    try:
        if forget_project(pid):
            log.info("AISC project dashboard removed: %s", rules.database_name(pid))
    except Exception:
        db.session.rollback()
        log.exception("AISC project dashboard not removed: %s", rules.database_name(pid))
        return jsonify(message="the project could not be removed"), 500
    return "", 204


@bridge.route("/aisc/p/<pid>", methods=["GET"], strict_slashes=False)
def open_project(pid):
    from flask_login import current_user

    if not getattr(current_user, "is_authenticated", False):
        return redirect("/login/?next=" + quote(request.path))
    try:
        slug = rules.dashboard_slug(pid)
    except rules.NotAPid:
        abort(404)
    from superset import db, security_manager as sm
    from superset.models.dashboard import Dashboard

    dash = db.session.query(Dashboard).filter_by(slug=slug).one_or_none()
    if dash is None or not sm.can_access_dashboard(dash):
        abort(404)
    return redirect(f"/superset/dashboard/{slug}/")


def install(app) -> None:
    """Create the two tables, exempt the platform's door from CSRF (it carries
    a bearer token, not a browser session), and mount both doors."""
    from superset import db
    from superset.extensions import csrf
    from aisc_ext.project_model import AiscProjectMember, AiscUserSubject

    AiscProjectMember.__table__.create(bind=db.engine, checkfirst=True)
    AiscUserSubject.__table__.create(bind=db.engine, checkfirst=True)
    csrf.exempt(bridge)
    app.register_blueprint(bridge)
```

The two tables are created with `create(checkfirst=True)`, the same way this extension already creates its comment tables (`superset_config.py:215-216`). The extension has no migration history of its own, and adding one is out of scope.

- [ ] **Step 6: Wire it.** In `superset_config.py`:

(a) In `FEATURE_FLAGS` (lines 54-72), after `"EMBEDDABLE_CHARTS": True,` add:

```python
    # A project's dashboard is shown to the holders of its role only
    # (aisc_ext/project_sync.py), not to everyone who can read one dataset.
    "DASHBOARD_RBAC": True,
```

(b) In `FLASK_APP_MUTATOR`, directly after `with app.app_context():` (line 183), insert:

```python
        # One connection per project, registered by the platform through the
        # bridge (aisc_ext/bridge.py) when it makes the project.
        try:
            from aisc_ext.bridge import install as install_project_bridge

            install_project_bridge(app)
        except Exception as exc:  # the rest of the dashboard still starts
            app.logger.error("AISC project bridge not installed: %s", exc)
```

- [ ] **Step 7: The token and the address template.** In `scripts/secrets.sh`, add `DASHBOARD_BRIDGE_TOKEN=$(rand)` after `DASHBOARD_ADMIN_PASSWORD=$(rand)` (line 41), and change `8 secrets` to `9 secrets` on line 43. After the `fi` on line 54, add:

```bash
# Secrets added after an install was made: appended to its env.secrets, never
# rotating the ones already there.
for name in DASHBOARD_BRIDGE_TOKEN; do
  if ! grep -q "^$name=" "$OUT"; then
    echo "$name=$(rand)" >> "$OUT"
    echo "added $name to $OUT"
  fi
done
```

In `docker-compose.development.yml`, add to the `dashboard` service's `environment` (after `OIDC_CLIENT_SECRET`, line 457):

```yaml
      # One connection per project database, {database} filled in per project
      # (aisc_ext/projects.py). The host's published port: this runs on the
      # host network.
      AISC_PROJECT_DB_URI: postgresql+psycopg2://dashboard_ro:dashboard_ro@localhost:5432/{database}
      # What the platform's calls to /aisc/bridge must carry.
      DASHBOARD_BRIDGE_TOKEN: ${DASHBOARD_BRIDGE_TOKEN:?run scripts/secrets.sh first}
```

- [ ] **Step 8: Deploy and run.**

Run: `scripts/secrets.sh && set -a && . ./env.secrets && set +a && $DC up -d --force-recreate dashboard && sleep 20 && apps/results-dashboard/scripts/verify_projects.sh`
Expected:
- `secrets.sh` prints `added DASHBOARD_BRIDGE_TOKEN to env.secrets` (only on the first run).
- The script ends with `N passed, 0 failed` and exit 0.
- `docker logs dashboard 2>&1 | grep -c "AISC project bridge not installed"` prints `0`.

If `a non-member asking for that chart's data by id is refused` fails with 200, Superset's `DASHBOARD_RBAC` path granted data through the dashboard. Stop and report it: Task 5's gate is what closes that, so don't weaken the check.

- [ ] **Step 9: Commit.**

```bash
(cd apps/results-dashboard && git add aisc_ext/project_model.py aisc_ext/project_sync.py aisc_ext/bridge.py scripts/verify_projects.py scripts/verify_projects.sh \
  && git add -p superset_config.py \
  && git commit -m "One connection, role and dashboard per project, registered through a bridge")
git add scripts/secrets.sh
git add -p docker-compose.development.yml   # only the dashboard environment hunk
git commit -m "The dashboard gets a bridge token and the project database address"
```

For `superset_config.py`, take only the `DASHBOARD_RBAC` hunk and the bridge-install hunk. Leave the Review-page hunks (`AiscReviewView`, `can_threads`, `Review dashboards`) unstaged.

---

### Task 5: Sign-in carries membership, and a gate checks it on every request

**Files:**
- Create: `apps/results-dashboard/aisc_ext/project_gate.py`
- Modify: `apps/results-dashboard/aisc_ext/sso.py`:
  - `class KeycloakSecurityManager`, line 16
  - `oauth_user_info`, lines 17-29
  - `auth_user_oauth`, lines 31-39
- Modify: `apps/results-dashboard/aisc_ext/security.py:25` (`dashboard-editor`)
- Modify: `apps/results-dashboard/superset_config.py`:
  - the OAuth block, lines 123-153
  - a new `DB_CONNECTION_MUTATOR` after line 87 (`PREVENT_UNSAFE_DB_CONNECTIONS`)
- Test: `apps/results-dashboard/tests/test_roles.py:36`, plus a new test in the same file
- Test: `apps/results-dashboard/scripts/verify_projects.py` (a new phase, `run_gate`)

**Interfaces:**
- Consumes: `project_sync.remember_subject`, `project_sync.project_roles_for` (Task 4); `rules.projects_reached`, `rules.may_reach` (Task 3).
- Produces:
  - `project_gate.membership_of(username: str | None) -> tuple[bool, set[str]]` (is_admin, project hexes)
  - `project_gate.refuse_unless_member(objects: dict, username: str | None) -> None` (raises `SupersetSecurityException`)
  - `project_gate.check_connection(database_name: str, username: str | None) -> None`
  - `class ProjectGateMixin` (overrides `raise_for_access`), `class ProjectGatedSecurityManager(ProjectGateMixin, SupersetSecurityManager)`
  - `KeycloakSecurityManager(ProjectGateMixin, SupersetSecurityManager)`; `oauth_user_info` returns `"subject"`
  - `map_keycloak_roles(["dashboard-editor"]) == ["Gamma"]`

- [ ] **Step 1: Write the failing tests.** In `tests/test_roles.py`, change line 36 to:

```python
    assert map_keycloak_roles(["dashboard-editor"]) == ["Gamma"]
```

and append:

```python
def test_no_account_is_mapped_to_a_role_that_reads_every_project():
    """Alpha holds all_database_access: every project's data, whoever is in
    which. An editor edits charts, and sees only the projects they are in."""
    for realm in (["admin"], ["dashboard-admin"], ["dashboard-editor"], ["primary-user"],
                  ["dashboard-viewer"], []):
        mapped = map_keycloak_roles(realm)
        assert "Alpha" not in mapped
        assert mapped == ["Admin"] or "all_database_access" not in mapped
```

In `scripts/verify_projects.py`, add this phase above the `PHASES` line, and insert `run_gate` into `PHASES` just before `run_forget`:

```python
def run_gate(ids):
    from superset import db, security_manager as sm
    from superset.exceptions import SupersetSecurityException
    from aisc_ext import projects as rules
    from aisc_ext.project_gate import check_connection
    from aisc_ext.project_sync import ensure_project

    a, e = client_for(ids["alice"]), client_for(ids["eve"])
    ds, chart, dash = ctx["A"]
    check("warming the cache: alice reads the chart", chart_data(a).status_code == 200)
    with app.app_context():
        eve = db.session.get(sm.user_model, ids["eve"])
        eve.roles.append(sm.find_role(rules.role_name(A)))
        db.session.commit()
    r = chart_data(e)
    check("a role granted by hand does not make someone a member: the data is refused, cache or not",
          r.status_code == 403, (r.status_code, r.data[:300]))
    check("nor the dashboard by id", e.get(f"/api/v1/dashboard/{dash}").status_code in (403, 404))
    check("nor step 6", e.get(f"/aisc/p/{A}").status_code == 404)

    with app.app_context():
        refused = []
        for who in (f"{TAG}-eve", f"{TAG}-bob", None):
            try:
                check_connection(rules.database_name(A), who)
                refused.append(False)
            except SupersetSecurityException:
                refused.append(True)
        check_connection(rules.database_name(A), f"{TAG}-alice")   # raises if it refuses a member
        check_connection(rules.database_name(A), f"{TAG}-ada")     # nor an admin
        check_connection("examples", f"{TAG}-eve")                 # not a project's database
    check("no connection to A's database is opened for a non-member, nor for nobody", all(refused), refused)

    with app.app_context():
        ensure_project(A, f"{TAG} A", {sub("alice"): "viewer", sub("carol"): "viewer"})
        eve = db.session.get(sm.user_model, ids["eve"])
        check("the next push takes the hand-granted role off again",
              rules.role_name(A) not in [r.name for r in eve.roles])
        carol = sm.auth_user_oauth({
            "username": f"{TAG}-carol", "email": f"{TAG}-carol@example.org",
            "first_name": "Carol", "last_name": "Verify",
            "realm_roles": ["primary-user"], "subject": sub("carol"),
        })
        names = sorted(r.name for r in carol.roles) if carol else []
    check("someone added before their first sign-in has the project when they sign in",
          names == sorted(["AiscViewer", rules.role_name(A)]), names)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/results-dashboard && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_roles.py; scripts/verify_projects.sh`
Expected:
- pytest: 2 FAILED. `['Alpha'] == ['Gamma']`, and `assert 'Alpha' not in ['Alpha']`.
- verify: `ImportError: cannot import name 'check_connection' from 'aisc_ext.project_gate'`, or `ModuleNotFoundError: No module named 'aisc_ext.project_gate'`, and exit 1.

- [ ] **Step 3: The gate.** Create `aisc_ext/project_gate.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The membership check on every request that reaches a project's data.

Superset's own check (raise_for_access) asks whether the caller's roles
reach an object. This asks the question the platform decides: is the caller
in the project that object belongs to? The project is read from the object
(its connection's name, its dashboard's slug), never from the request, and
membership from what the platform last sent (aisc_project_member). It runs
at two seams: raise_for_access, which every dashboard, chart, dataset,
chart-data and SQL request passes before any cache or connection, and
DB_CONNECTION_MUTATOR, through which every connection Superset opens passes.
A role granted by hand, a stale role, or a Superset rule that lends a
dataset through a dashboard does not get past it.

Runtime-only (Superset imports inside the functions).
"""
from __future__ import annotations

from types import SimpleNamespace

from aisc_ext import projects as rules

#: raise_for_access's parameters, in order (superset/security/manager.py:2145).
_ARGS = ("dashboard", "chart", "database", "datasource", "query", "query_context",
         "table", "viz", "sql", "catalog", "schema")


def membership_of(username: str | None) -> tuple[bool, set[str]]:
    from superset import db, security_manager as sm
    from aisc_ext.project_model import AiscProjectMember, AiscUserSubject

    user = sm.find_user(username=username) if username else None
    if user is None:
        return False, set()
    is_admin = any(r.name == "Admin" for r in user.roles)
    row = db.session.get(AiscUserSubject, user.id)
    if row is None:
        return is_admin, set()
    hexes = {m.project_hex for m in db.session.query(AiscProjectMember).filter_by(subject=row.subject)}
    return is_admin, hexes


def _bridge_running() -> bool:
    try:
        from flask import g

        return bool(getattr(g, "aisc_bridge", False))
    except RuntimeError:  # outside any app context
        return False


def _refuse() -> None:
    from superset.errors import ErrorLevel, SupersetError, SupersetErrorType
    from superset.exceptions import SupersetSecurityException

    raise SupersetSecurityException(SupersetError(
        error_type=SupersetErrorType.DATASOURCE_SECURITY_ACCESS_ERROR,
        message="This belongs to a project you are not in.",
        level=ErrorLevel.ERROR,
    ))


def refuse_unless_member(objects: dict, username: str | None) -> None:
    reached = rules.projects_reached(objects)
    if not reached:
        return
    bridge = _bridge_running()
    is_admin, member_of = membership_of(username)
    for project_hex in reached:
        if not rules.may_reach(project_hex, is_admin=is_admin, member_of=member_of, bridge=bridge):
            _refuse()


def check_connection(database_name: str, username: str | None) -> None:
    refuse_unless_member({"database": SimpleNamespace(database_name=database_name)}, username)


class ProjectGateMixin:
    """raise_for_access as Superset has it, then: is the caller in the project?"""

    def raise_for_access(self, *args, **kwargs):
        super().raise_for_access(*args, **kwargs)
        from superset.utils.core import get_username

        objects = dict(zip(_ARGS, args))
        objects.update(kwargs)
        refuse_unless_member(objects, get_username())


def _gated_manager():
    from superset.security import SupersetSecurityManager  # type: ignore

    class ProjectGatedSecurityManager(ProjectGateMixin, SupersetSecurityManager):
        """The gate for an install that signs in without Keycloak."""

    return ProjectGatedSecurityManager
```

- [ ] **Step 4: Sign-in, and the editor mapping.** In `aisc_ext/security.py:25`, change `("dashboard-editor", "Alpha"),` to:

```python
    # Gamma, not Alpha: Alpha holds all_database_access, every project's data.
    # An editor edits charts on the projects they are in, and sees no other.
    ("dashboard-editor", "Gamma"),
```

In `aisc_ext/sso.py`, replace line 13 (`from aisc_ext.security import map_keycloak_roles`) with:

```python
from aisc_ext.project_gate import ProjectGateMixin
from aisc_ext.security import map_keycloak_roles
```

Replace line 16 with `class KeycloakSecurityManager(ProjectGateMixin, SupersetSecurityManager):`. In `oauth_user_info` (lines 22-29), add to the returned dict after `"realm_roles": …,`:

```python
            # Keycloak's stable subject: the platform's membership is keyed on it
            "subject": data.get("sub"),
```

Replace `auth_user_oauth` (lines 31-39) with:

```python
    def auth_user_oauth(self, userinfo):
        user = super().auth_user_oauth(userinfo)
        if user is None:
            return None
        desired = map_keycloak_roles(userinfo.get("realm_roles", []))
        roles = [self.find_role(r) for r in desired if self.find_role(r)]
        subject = userinfo.get("subject")
        if subject:
            # The projects this person is in, as the platform last said: a
            # member added before their first sign-in has them from this one.
            from aisc_ext.project_sync import project_roles_for, remember_subject

            remember_subject(user, subject)
            roles += project_roles_for(subject)
        user.roles = roles
        self.update_user(user)
        log.info("Synced %s -> %s, and %d project role(s)", user.username, desired,
                 len(roles) - len(desired))
        return user
```

- [ ] **Step 5: Both seams in the config.** In `superset_config.py`, after `PREVENT_UNSAFE_DB_CONNECTIONS = True` (line 87), add:

```python
# The one place Superset opens a connection to a database. A project's
# database is reached only by that project's members, admins, and the
# platform's registration (aisc_ext/project_gate.py).
def DB_CONNECTION_MUTATOR(uri, params, username, security_manager, source):  # noqa: N802
    from aisc_ext.project_gate import check_connection

    check_connection(uri.database, username)
    return uri, params
```

In the OAuth block, after the `if os.environ.get("AISC_OAUTH") == "1":` block ends (after line 153), add:

```python
else:
    # Without Keycloak the membership gate still stands in front of every
    # project's data (aisc_ext/project_gate.py).
    from aisc_ext.project_gate import _gated_manager  # noqa: E402

    CUSTOM_SECURITY_MANAGER = _gated_manager()
```

- [ ] **Step 6: Run them.**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q && $DC restart dashboard && sleep 20 && scripts/verify_projects.sh`
Expected: pytest all PASS (`tests/test_sso_login.py` is skipped or ignored as in `scripts/verify.sh:63`). The verify script prints `0 failed`, including every `run_gate` line.

- [ ] **Step 7: Commit** (inside `apps/results-dashboard`).

```bash
git add aisc_ext/project_gate.py aisc_ext/sso.py aisc_ext/security.py tests/test_roles.py scripts/verify_projects.py
git add -p superset_config.py   # only DB_CONNECTION_MUTATOR and the else: CUSTOM_SECURITY_MANAGER hunks
git commit -m "Membership reaches Superset at sign-in, and every request is checked against the project it reaches"
```

---

### Task 6: Retire the one shared results connection

**Files:**
- Delete: `apps/results-dashboard/aisc_ext/results_db.py`, `apps/results-dashboard/tests/test_results_database.py`
- Modify: `apps/results-dashboard/aisc_ext/project_sync.py` (add `retire_results_database`)
- Modify: `apps/results-dashboard/superset_config.py:184-189` (the results-database block)
- Modify: `docker-compose.development.yml`: lines 407-408 (`AISC_RESULTS_DB_URI` in `&dashboard-env`) and line 448 (the `dashboard` override)
- Modify:
  - `apps/results-dashboard/.env.example:16`
  - `apps/results-dashboard/docker-compose.yml:20`
  - `apps/results-dashboard/docker-compose.aisc.yml:7`
  - `apps/results-dashboard/README.md:102`
  - `apps/results-dashboard/scripts/bootstrap.sh:42`
- Test: `scripts/verify-one-database.sh:174-203`; `apps/results-dashboard/scripts/verify_projects.py` (a new phase, `run_retired`)

**Interfaces:**
- Produces: `project_sync.retire_results_database(logger) -> str`, returning `"absent"`, `"retired"` or `"kept"`. No `dbs` row reads the shared `platform` database. No `AISC_RESULTS_DB_URI` anywhere.

- [ ] **Step 1: Check what would be removed.** Run:

`docker exec postgres psql -U aisc-postgres-user -d superset -At -c "select (select count(*) from tables t join dbs d on d.id = t.database_id where d.database_name = 'AISC Results'), (select count(*) from dbs where database_name = 'AISC Results')"`

Expected: `0|1`. **If the first number isn't 0, stop and ask the user.** Datasets somebody built by hand on the shared connection would stop working. The code below leaves them in place anyway, but the user decides what happens to them.

- [ ] **Step 2: Write the failing assertions.** In `scripts/verify-one-database.sh`, replace lines 174-203 (from `echo "the dashboard reads THIS install (wave 1)"` through the `docker logs dashboard` case block) with:

```bash
echo "the dashboard reads each project's own database of THIS install, and nothing shared"
# One connection per project, registered by the platform through the
# dashboard's bridge. Each one names this install's Postgres (the dashboard is
# host-networked, so the host's published port) and a project database, as
# dashboard_ro. None names the shared database any more.
reg=$(docker exec postgres psql -U "$PGUSER" -d superset -At -F ' ' \
        -c "select database_name, sqlalchemy_uri from dbs order by id" 2>/dev/null)
ours=$(docker inspect postgres --format '{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}}{{end}}{{end}}' 2>/dev/null)
shared=$(printf '%s\n' "$reg" | grep -c "/$PGDB\$")
[ "$shared" = "0" ] && ok "no connection reads the shared $PGDB database" \
  || no "$shared connection(s) still read $PGDB"
case "$reg" in
  *"AISC Results"*) no "the shared AISC Results connection is still registered" ;;
  *) ok "the shared AISC Results connection is gone" ;;
esac
bad=0
while read -r name uri; do
  [ -z "$name" ] && continue
  case "$name|$uri" in
    project_*"|postgresql+psycopg2://dashboard_ro:"*"@localhost:${ours:-5432}/$name") ;;
    *) bad=$((bad+1)); no "connection $name is not a project database of this install as dashboard_ro: $uri" ;;
  esac
done <<< "$reg"
[ "$bad" = "0" ] && ok "every connection is one project's database, here, as dashboard_ro"
```

In `scripts/verify_projects.py`, add this phase and insert it before `run_forget` in `PHASES`:

```python
def run_retired(ids):
    from superset import db
    from superset.models.core import Database

    with app.app_context():
        left = db.session.query(Database).filter_by(database_name="AISC Results").count()
    check("the shared results connection is gone", left == 0, left)
    check("and nothing reads the shared platform database",
          os.environ.get("AISC_RESULTS_DB_URI") is None)
```

- [ ] **Step 3: Run them and watch them fail.**

Run: `scripts/verify-one-database.sh; apps/results-dashboard/scripts/verify_projects.sh`
Expected:
- `FAIL 1 connection(s) still read platform`
- `FAIL the shared AISC Results connection is still registered`
- `FAIL connection AISC Results is not a project database …`
- `FAIL the shared results connection is gone  [1]`
- `FAIL and nothing reads the shared platform database`

- [ ] **Step 4: Retire it.** Append to `aisc_ext/project_sync.py`:

```python
#: The one shared connection this dashboard registered before project databases.
RETIRED_CONNECTION = "AISC Results"


def retire_results_database(logger) -> str:
    """Remove the shared connection, once nothing is built on it.

    It read the whole platform database, every project at once. Datasets on
    it are somebody's work: they are left in place, and said so, rather than
    deleted with it.
    """
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    old = db.session.query(Database).filter_by(database_name=RETIRED_CONNECTION).one_or_none()
    if old is None:
        return "absent"
    built_on = db.session.query(SqlaTable).filter_by(database_id=old.id).count()
    if built_on:
        logger.error("%s still has %d dataset(s): left in place; move them to a project's "
                     "connection, then delete it by hand", RETIRED_CONNECTION, built_on)
        return "kept"
    db.session.delete(old)
    db.session.commit()
    logger.info("%s retired: the dashboard reads project databases only", RETIRED_CONNECTION)
    return "retired"
```

In `superset_config.py`, delete lines 184-189: the comment `# The results database, from AISC_RESULTS_DB_URI …`, the import of `register_results_database`, and its call. In the `try` block Task 4 added, after `install_project_bridge(app)`, add:

```python
            from aisc_ext.project_sync import retire_results_database

            retire_results_database(app.logger)
```

Delete the old files, and the variable everywhere:

```bash
cd apps/results-dashboard
git rm -q aisc_ext/results_db.py tests/test_results_database.py
```

- `.env.example:16`: replace `AISC_RESULTS_DB_URI=` with `AISC_PROJECT_DB_URI=` and a comment line above it: `# One connection per project database: {database} is filled in per project.` Add `DASHBOARD_BRIDGE_TOKEN=` below, with the comment `# What the platform's calls to /aisc/bridge carry (scripts/secrets.sh in the platform).`
- `docker-compose.yml:20`: replace the line with `AISC_PROJECT_DB_URI: ${AISC_PROJECT_DB_URI:-}` and add `DASHBOARD_BRIDGE_TOKEN: ${DASHBOARD_BRIDGE_TOKEN:-}` below it.
- `docker-compose.aisc.yml:7`: `#   AISC_PROJECT_DB_URI=postgresql+psycopg2://dashboard_ro:<pw>@postgres:5432/{database}`.
- `README.md:102`: `| `AISC_PROJECT_DB_URI` | The address of a project database, with `{database}` where its name goes. The platform registers one connection per project through `/aisc/bridge`; none is typed in the UI. |`, plus a row `| `DASHBOARD_BRIDGE_TOKEN` | The bearer token the platform's bridge calls carry. Unset: the bridge refuses everything. |`.
- `scripts/bootstrap.sh:42`: `  - projects are registered by the platform (one connection each); nothing to register by hand`.

In the root `docker-compose.development.yml`, delete lines 407-408 (the comment `# the platform's own database, through the read-only role` and `AISC_RESULTS_DB_URI: …`) and line 448 (the `dashboard` override of `AISC_RESULTS_DB_URI`).

Check: `grep -rn "AISC_RESULTS_DB_URI\|results_db\|register_results_database" --exclude-dir=.venv --exclude-dir=.git apps/results-dashboard docker-compose.development.yml` prints only `apps/results-dashboard/scripts/verify_review.py:41` (someone else's uncommitted file; see Stopping rule). If `verify_projects.py` shows up, that is fine: it mentions `AISC_RESULTS_DB_URI` only to assert it's absent.

- [ ] **Step 5: Deploy and run.**

Run: `$DC up -d --force-recreate dashboard-migrate dashboard && docker wait dashboard-migrate && sleep 20 && docker logs dashboard 2>&1 | grep "AISC Results retired\|AISC Results still" ; scripts/verify-one-database.sh && apps/results-dashboard/scripts/verify_projects.sh && (cd apps/results-dashboard && PYTHONPATH=. .venv/bin/python -m pytest -q --ignore=tests/test_sso_login.py)`
Expected:
- `docker wait` prints `0`.
- One of the two containers logs `AISC Results retired: the dashboard reads project databases only`. It is whichever booted first; the other finds nothing to retire.
- Every new line passes, `0 failed`, and pytest passes.

- [ ] **Step 6: Commit.**

```bash
(cd apps/results-dashboard && git add aisc_ext/project_sync.py scripts/verify_projects.py .env.example docker-compose.yml docker-compose.aisc.yml README.md scripts/bootstrap.sh \
  && git add -p superset_config.py \
  && git commit -m "Retire the one shared results connection: the dashboard reads project databases only")
git add scripts/verify-one-database.sh
git add -p docker-compose.development.yml   # only the two AISC_RESULTS_DB_URI deletions
git commit -m "No dashboard connection reads the shared database"
```

---

### Task 7: Comments and review requests only on dashboards the caller may open

**Files:**
- Create: `apps/results-dashboard/aisc_ext/visible.py`
- Modify: `apps/results-dashboard/aisc_ext/reviews/service.py` (append `on_dashboards`, `assignable`)
- Modify: `apps/results-dashboard/aisc_ext/reviews/api.py`:
  - imports, lines 9-11
  - `assignees`, lines 27-35
  - `list`, lines 37-55
  - `post`, lines 57-77
  - `patch`, lines 79-98
- Modify: `apps/results-dashboard/superset_config.py` (after line 200, `sm = app.appbuilder.sm`)
- Test: `apps/results-dashboard/tests/test_reviews.py` (append); `scripts/verify_projects.py` (a new phase, `run_reviews`)

**Interfaces:**
- Consumes: the gate (Task 5), through `DashboardDAO.get_by_id_or_slug` → `raise_for_access`.
- Produces:
  - `visible.may_open(id_or_slug) -> Dashboard | None`
  - `visible.dashboards_the_caller_may_open() -> list[str]` (ids and slugs)
  - `visible.scope_to_visible_dashboards(view_cls) -> None`
  - `reviews.service.on_dashboards(rows: list[dict], allowed: set[str]) -> list[dict]`
  - `reviews.service.assignable(people: list[tuple[str, str, set[int], bool]], dashboard_role_ids: set[int]) -> list[dict]`
  - `GET /api/v1/aisc_review_request/assignees` now requires `?dashboard_id=`, and answers 404 when the caller can't open it.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_reviews.py`:

```python
from aisc_ext.reviews.service import assignable, on_dashboards


def test_only_the_requests_on_dashboards_the_caller_may_open():
    rows = [{"id": 1, "dashboard_id": "7"}, {"id": 2, "dashboard_id": "project-abc"}, {"id": 3, "dashboard_id": "9"}]
    assert [r["id"] for r in on_dashboards(rows, {"7", "project-abc"})] == [1, 2]
    assert on_dashboards(rows, set()) == []


def test_who_a_review_can_go_to_is_who_can_open_the_dashboard():
    people = [("alice", "Alice", {10}, False), ("bob", "Bob", {20}, False), ("ada", "Ada", set(), True)]
    assert [p["sub"] for p in assignable(people, {10})] == ["alice", "ada"]
    # a dashboard with no roles of its own: only admins, never everybody
    assert [p["sub"] for p in assignable(people, set())] == ["ada"]
```

In `scripts/verify_projects.py`, add this phase and insert it before `run_forget` in `PHASES`:

```python
def run_reviews(ids):
    from superset import db
    from aisc_ext.comments.model import AiscComment

    a, b = client_for(ids["alice"]), client_for(ids["bob"])
    dash = ctx[f"dash_{A}"]
    marker = f"{TAG}-comment-on-A"
    with app.app_context():
        db.session.add(AiscComment(dashboard_id=str(dash), author_sub=f"{TAG}-alice",
                                   author_name="Alice Verify", body=marker))
        db.session.commit()
    api = "/api/v1/aisc_review_request/"
    body = {"dashboard_id": str(dash), "message": f"{TAG} please review",
            "assignee_type": "category", "assignee_category": "legal"}
    r = a.post(api, json=body)
    check("a member asks for a review on her project's dashboard", r.status_code == 201, (r.status_code, r.data[:300]))
    rid = ((r.json or {}).get("result") or {}).get("id")
    r = b.get(api)
    check("another project's member does not see it listed",
          r.status_code == 200 and all(x.get("id") != rid for x in r.json.get("result", [])))
    check("nor may ask for one on that dashboard, by its id", b.post(api, json=body).status_code == 404)
    check("nor close hers, by its id", b.patch(f"{api}{rid}", json={"action": "done"}).status_code == 404)
    check("nor list who could be asked on it", b.get(f"{api}assignees?dashboard_id={dash}").status_code == 404)
    r = a.get(f"{api}assignees?dashboard_id={dash}")
    subs = {u["sub"] for u in (r.json or {}).get("users", [])}
    check("the people who can be asked are the ones who can open it",
          f"{TAG}-alice" in subs and f"{TAG}-bob" not in subs and f"{TAG}-eve" not in subs, subs)
    check("the comments list shows a member her own project's",
          marker.encode() in a.get("/aisccommentview/list/").data)
    check("and does not show another project's", marker.encode() not in b.get("/aisccommentview/list/").data)
    check("the review requests list does not show another project's",
          b"Alice Verify" not in b.get("/aiscreviewrequestview/list/").data)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd apps/results-dashboard && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_reviews.py; scripts/verify_projects.sh`
Expected:
- pytest: `ImportError: cannot import name 'assignable'`.
- verify: `FAIL another project's member does not see it listed`, `FAIL nor may ask for one … [201]`, `FAIL and does not show another project's`.

- [ ] **Step 3: Implement.** Create `aisc_ext/visible.py`:

```python
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Which dashboards the caller may open, asked the way Superset asks it.

Comments and review requests are about a project's results. One on a
dashboard somebody cannot open is not theirs to read, write or be assigned,
whatever the menu shows. Both answers go through Superset's own access check,
which carries the project membership gate (project_gate.py).
Runtime-only.
"""
from __future__ import annotations


def may_open(id_or_slug):
    """The dashboard when the caller may open it; None when they may not, or
    when there is none (the same answer, so neither leaks the other)."""
    if not id_or_slug:
        return None
    from superset.commands.dashboard.exceptions import (
        DashboardAccessDeniedError, DashboardNotFoundError,
    )
    from superset.daos.dashboard import DashboardDAO

    try:
        return DashboardDAO.get_by_id_or_slug(str(id_or_slug))
    except (DashboardNotFoundError, DashboardAccessDeniedError):
        return None


def dashboards_the_caller_may_open() -> list[str]:
    from superset import security_manager as sm
    from superset.daos.dashboard import DashboardDAO

    out: list[str] = []
    for dash in DashboardDAO.find_all():
        if not sm.can_access_dashboard(dash):
            continue
        out.append(str(dash.id))
        if dash.slug:
            out.append(dash.slug)
    return out


def scope_to_visible_dashboards(view_cls) -> None:
    """A Flask-AppBuilder list of rows keyed by dashboard_id, cut to the ones
    the caller may open. Set before the view is added: FAB reads it then."""
    from flask_appbuilder.models.sqla.filters import FilterInFunction

    view_cls.base_filters = [["dashboard_id", FilterInFunction, dashboards_the_caller_may_open]]
```

Append to `aisc_ext/reviews/service.py`:

```python
def on_dashboards(rows: list[dict], allowed: set[str]) -> list[dict]:
    """Only the requests on dashboards the caller may open."""
    return [r for r in rows if str(r.get("dashboard_id")) in allowed]


def assignable(people, dashboard_role_ids: set[int]) -> list[dict]:
    """Who a review on a dashboard can go to: whoever holds one of its roles,
    and admins. A dashboard with no roles of its own: admins only."""
    return [{"sub": username, "name": name}
            for username, name, role_ids, is_admin in people
            if is_admin or (dashboard_role_ids and role_ids & dashboard_role_ids)]
```

In `aisc_ext/reviews/api.py`:

(a) Replace the import at lines 9-11 with:

```python
from aisc_ext.reviews.service import (
    STAKEHOLDER_GROUPS, assignable, can_resolve, is_for_user, make_request, on_dashboards,
)
from aisc_ext.visible import dashboards_the_caller_may_open, may_open
```

(b) Replace the body of `assignees` (lines 31-35, after the decorators) with:

```python
        """Who a review on this dashboard can go to: the people who can open it,
        and the stakeholder categories. ?dashboard_id= is required."""
        from superset import db
        from flask_appbuilder.security.sqla.models import User

        dashboard = may_open(request.args.get("dashboard_id"))
        if dashboard is None:
            return self.response_404()
        people = [(u.username, u.get_full_name() or u.username, {r.id for r in u.roles},
                   any(r.name == "Admin" for r in u.roles))
                  for u in db.session.query(User).all()]
        return self.response(200, users=assignable(people, {r.id for r in dashboard.roles}),
                             categories=STAKEHOLDER_GROUPS)
```

(c) In `list`, directly after `rows = [r.to_dict() for r in q.order_by(AiscReviewRequest.created_at.desc()).all()]`, add:

```python
        rows = on_dashboards(rows, set(dashboards_the_caller_may_open()))
```

(d) In `post`, directly after `b = request.json or {}`, add:

```python
        if may_open(b.get("dashboard_id")) is None:
            return self.response_404()
```

(e) In `patch`, directly after the `if not row: return self.response_404()` lines, add:

```python
        if may_open(row.dashboard_id) is None:
            return self.response_404()
```

In `superset_config.py`, directly after `sm = app.appbuilder.sm` (line 200), add:

```python
        # A comment or review request is about one project's results: the
        # lists show only those on dashboards the caller may open.
        from aisc_ext.visible import scope_to_visible_dashboards

        scope_to_visible_dashboards(AiscCommentView)
        scope_to_visible_dashboards(AiscReviewRequestView)
```

`aisc_ext/comments/api.py` is not touched. Its uncommitted version (someone else's) already asks `DashboardDAO.get_by_id_or_slug` on every route, and that call now carries the gate.

- [ ] **Step 4: Run them.**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q --ignore=tests/test_sso_login.py && $DC restart dashboard && sleep 20 && scripts/verify_projects.sh`
Expected: all PASS and `0 failed`.

- [ ] **Step 5: Commit** (inside `apps/results-dashboard`).

```bash
git add aisc_ext/visible.py aisc_ext/reviews/service.py aisc_ext/reviews/api.py tests/test_reviews.py scripts/verify_projects.py
git add -p superset_config.py   # only the scope_to_visible_dashboards hunk
git commit -m "Comments and review requests only on dashboards the caller may open"
```

---

### Task 8: The platform registers each project, keeps its members in step, and removes it

**Files:**
- Create: `platform/platform_service/dashboard.py`
- Modify: `platform/platform_service/app.py`:
  - imports, lines 14 and 22
  - `app =`, line 33
  - `add_project`, lines 99-127
  - `remove_project`, lines 134-152
  - `add_project_member`, lines 180-190
  - `set_project_member_role`, lines 193-206
  - `remove_project_member`, lines 209-221
- Modify: `docker-compose.development.yml` (the `platform` service `environment`, lines 508-519, and a new `extra_hosts`)
- Test: `platform/tests/test_dashboard_bridge.py`

**Interfaces:**
- Consumes: the bridge HTTP interface (Task 4). `db.get_project`, `db.members`, `db.list_projects` (`platform/platform_service/db.py:55-72,204-212`). `projectdb.database_name`.
- Produces:
  - `dashboard.bridge() -> Bridge | None`
  - `dashboard.state_of(pid) -> dict | None`
  - `dashboard.push(pid) -> bool`, `dashboard.forget(pid) -> bool`
  - `dashboard.registered() -> set[str] | None`
  - `dashboard.reconcile_once() -> {"pushed": int, "forgotten": int}`
  - `dashboard.start_reconciler(interval: float | None = None) -> threading.Thread | None`
  - Env: `DASHBOARD_BRIDGE_URL` (e.g. `http://host.docker.internal:8188/aisc/bridge`), `DASHBOARD_BRIDGE_TOKEN`, `DASHBOARD_RECONCILE_SECONDS` (default 60).
  - None of these raises. Creating a project, changing its members or deleting it succeeds whether the dashboard is up or not.

- [ ] **Step 1: Write the failing tests.** Create `platform/tests/test_dashboard_bridge.py`:

```python
"""The platform tells the dashboard which projects exist and who is in them.

Against a stand-in for the dashboard's bridge: a local HTTP server that
records what it is sent and checks the token as the real one does.
"""
import json
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from platform_service import dashboard, projectdb
from tests.conftest import needs_database

TOKEN = "bridge-token-for-tests"
PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


@pytest.fixture
def superset(monkeypatch):
    seen, listing = [], []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, code, payload=None):
            raw = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self, code, payload=None):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._answer(401, {"message": "unauthorised"})
            seen.append(SimpleNamespace(method=self.command, path=self.path, body=body))
            self._answer(code, payload)

        def do_PUT(self):
            self._handle(200, {"result": {}})

        def do_DELETE(self):
            self._handle(204)

        def do_GET(self):
            self._handle(200, {"result": list(listing)})

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", f"http://127.0.0.1:{server.server_port}/aisc/bridge")
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    yield SimpleNamespace(seen=seen, listing=listing)
    server.shutdown()


def _puts(superset, pid):
    return [c.body for c in superset.seen if c.method == "PUT" and c.path == f"/aisc/bridge/projects/{pid}"]


def test_nothing_is_sent_when_no_dashboard_is_configured(monkeypatch):
    monkeypatch.delenv("DASHBOARD_BRIDGE_URL", raising=False)
    assert dashboard.bridge() is None
    assert dashboard.push(PID) is False
    assert dashboard.reconcile_once() == {"pushed": 0, "forgotten": 0}


def test_a_bridge_with_no_token_is_not_called(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", "http://127.0.0.1:9/aisc/bridge")
    monkeypatch.delenv("DASHBOARD_BRIDGE_TOKEN", raising=False)
    assert dashboard.bridge() is None


@needs_database
def test_making_a_project_registers_it_with_its_owner(client, as_user, unique, superset):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    assert _puts(superset, created["pid"])[-1] == {
        "name": created["name"], "members": [{"subject": "alice", "role": "owner"}]}


@needs_database
def test_every_change_of_members_sends_the_whole_list(client, as_user, unique, superset):
    slug = unique()
    created = client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice")).json()
    owner = as_user("alice")
    assert client.post(f"/projects/{slug}/members", json={"subject": "bob", "role": "viewer"},
                       headers=owner).status_code == 201
    assert _puts(superset, created["pid"])[-1]["members"] == [
        {"subject": "alice", "role": "owner"}, {"subject": "bob", "role": "viewer"}]
    assert client.put(f"/projects/{slug}/members/bob", json={"role": "editor"}, headers=owner).status_code == 200
    assert {"subject": "bob", "role": "editor"} in _puts(superset, created["pid"])[-1]["members"]
    assert client.delete(f"/projects/{slug}/members/bob", headers=owner).status_code == 204
    assert _puts(superset, created["pid"])[-1]["members"] == [{"subject": "alice", "role": "owner"}]


@needs_database
def test_deleting_a_project_removes_it_from_the_dashboard(client, as_user, unique, superset):
    slug = unique()
    created = client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice")).json()
    admin = as_user("root", roles=("admin",))
    assert client.request("DELETE", f"/projects/{slug}", json={"confirm_name": slug},
                          headers=admin).status_code == 204
    calls = [c.method for c in superset.seen if c.path == f"/aisc/bridge/projects/{created['pid']}"]
    assert calls[-1] == "DELETE"


@needs_database
def test_a_dashboard_that_is_down_stops_nothing(client, as_user, unique, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", f"http://127.0.0.1:{port}/aisc/bridge")
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    slug = unique()
    assert client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice")).status_code == 201
    assert client.post(f"/projects/{slug}/members", json={"subject": "bob"},
                       headers=as_user("alice")).status_code == 201


@needs_database
def test_the_token_is_never_logged(client, as_user, unique, superset, monkeypatch, caplog):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", "a-token-the-dashboard-refuses")
    assert dashboard.push(created["pid"]) is False
    assert "a-token-the-dashboard-refuses" not in caplog.text


@needs_database
def test_reconciling_pushes_every_project_and_forgets_only_what_is_gone(client, as_user, unique, superset, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    gone = str(uuid.uuid4())         # no project and no database: deleted while the dashboard was down
    in_progress = str(uuid.uuid4())  # no project row but a database: somebody's test, left alone
    projectdb.provision(dsn, in_progress)
    try:
        superset.listing.extend([gone, in_progress, created["pid"]])
        superset.seen.clear()
        done = dashboard.reconcile_once()
        assert [c.path for c in superset.seen if c.method == "DELETE"] == [f"/aisc/bridge/projects/{gone}"]
        assert _puts(superset, created["pid"])
        assert done["forgotten"] == 1 and done["pushed"] >= 1
    finally:
        projectdb.drop(dsn, in_progress)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `cd platform && uv run --extra dev pytest tests/test_dashboard_bridge.py -v`
Expected: collection error, `ImportError: cannot import name 'dashboard' from 'platform_service'`.

- [ ] **Step 3: Implement.** Create `platform/platform_service/dashboard.py`:

```python
"""Telling the dashboard which projects exist and who is in them.

The dashboard is one Superset for every project. Each project has a
connection there, to its own database, and only its members see it. The
platform decides who is in a project, so the platform tells the dashboard: a
project's whole member list at a time, whenever the list or the project
changes, and every project once a minute, so a message missed while the
dashboard was down is repaired by the next round.

Never fatal, and nothing here raises. A project is made and a member added
whether or not the dashboard is up. The token is sent, never logged.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("platform.dashboard")


@dataclass(frozen=True)
class Bridge:
    url: str
    token: str
    timeout: float = 5.0


def bridge() -> Bridge | None:
    url = os.environ.get("DASHBOARD_BRIDGE_URL", "").strip().rstrip("/")
    if not url:
        return None
    token = os.environ.get("DASHBOARD_BRIDGE_TOKEN", "").strip()
    if not token:
        log.error("DASHBOARD_BRIDGE_URL is set but DASHBOARD_BRIDGE_TOKEN is not: the dashboard is told nothing")
        return None
    return Bridge(url, token)


def _call(b: Bridge, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{b.url}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {b.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=b.timeout) as response:
        raw = response.read()
        return response.status, (json.loads(raw) if raw else None)


def state_of(pid) -> dict | None:
    from platform_service import db

    project = db.get_project(str(pid))
    if project is None:
        return None
    return {"name": project["name"],
            "members": [{"subject": m["subject"], "role": m["role"]} for m in db.members(str(pid))]}


def push(pid) -> bool:
    b = bridge()
    if b is None:
        return False
    try:
        state = state_of(pid)
        if state is None:
            return forget(pid)
        status, _ = _call(b, "PUT", f"/projects/{pid}", state)
        return status == 200
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("the dashboard was not told about project %s: %s", pid, exc)
        return False


def forget(pid) -> bool:
    b = bridge()
    if b is None:
        return False
    try:
        status, _ = _call(b, "DELETE", f"/projects/{pid}")
        return status in (200, 204)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("the dashboard was not told project %s is gone: %s", pid, exc)
        return False


def registered() -> set[str] | None:
    b = bridge()
    if b is None:
        return None
    try:
        _, body = _call(b, "GET", "/projects")
        return {str(p) for p in (body or {}).get("result", [])}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("could not ask the dashboard what it has: %s", exc)
        return None


def _database_exists(pid) -> bool:
    import psycopg

    from platform_service import db, projectdb

    try:
        name = projectdb.database_name(pid)
    except projectdb.NotAPid:
        return False
    with psycopg.connect(db.dsn(), autocommit=True) as conn:
        return conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone() is not None


def reconcile_once() -> dict:
    from platform_service import db

    if bridge() is None:
        return {"pushed": 0, "forgotten": 0}
    known = {str(p["pid"]) for p in db.list_projects()}
    pushed = sum(1 for pid in sorted(known) if push(pid))
    forgotten = 0
    for pid in sorted((registered() or set()) - known):
        # No project behind it and no database either: a project deleted while
        # the dashboard was down. One whose database is still there is work in
        # progress (a test's), and is left alone.
        if not _database_exists(pid) and forget(pid):
            forgotten += 1
    return {"pushed": pushed, "forgotten": forgotten}


_reconciler: threading.Thread | None = None


def start_reconciler(interval: float | None = None) -> threading.Thread | None:
    global _reconciler
    if bridge() is None or _reconciler is not None:
        return None
    every = float(interval or os.environ.get("DASHBOARD_RECONCILE_SECONDS", "60"))

    def loop() -> None:
        while True:
            try:
                reconcile_once()
            except Exception:  # the platform's own database restarting, say
                log.exception("telling the dashboard every project failed; next round in %ss", every)
            time.sleep(every)

    _reconciler = threading.Thread(target=loop, name="dashboard-reconciler", daemon=True)
    _reconciler.start()
    return _reconciler
```

In `platform/platform_service/app.py`:
- Line 14: `from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException`.
- Add `from contextlib import asynccontextmanager` after line 12.
- Line 22: `from platform_service import dashboard, db, projectdb`.
- Replace line 33 with:

```python
@asynccontextmanager
async def lifespan(_app):
    # Every project told to the dashboard once a minute: what was missed while
    # it was down is repaired by the next round (platform_service/dashboard.py).
    dashboard.start_reconciler()
    yield


app = FastAPI(title="AISC platform", docs_url="/docs", lifespan=lifespan)
```

- `add_project`: its signature becomes `def add_project(body: ProjectIn, background: BackgroundTasks, caller: Caller = Depends(caller_dependency)) -> dict:`. Before the final `return created` (line 127), add `background.add_task(dashboard.push, str(created["pid"]))`.
- `remove_project`: the signature gains `background: BackgroundTasks` after `body`. After `db.delete_project(found["pid"])` (line 152), add `background.add_task(dashboard.forget, str(found["pid"]))`.
- `add_project_member`, `set_project_member_role` and `remove_project_member` each gain `background: BackgroundTasks` after their path/body parameters, and call this helper once they have succeeded. That is just before `return added` / `return changed`, and at the end of `remove_project_member`:

```python
def _tell_the_dashboard(background: BackgroundTasks, slug: str) -> None:
    """After a member change: the project's whole member list, after the response."""
    found = db.get_project(slug)
    if found is not None:
        background.add_task(dashboard.push, str(found["pid"]))
```

Define `_tell_the_dashboard` directly above `add_project_member`. `TestClient` runs background tasks before it returns the response, which is what the tests rely on. A real client gets its response first.

In `docker-compose.development.yml`, in the `platform` service, add under `environment` (after `PLATFORM_BOOTSTRAP_OWNERS`, line 519):

```yaml
      # The dashboard's bridge: which projects exist and who is in them. The
      # dashboard runs on the host network, hence host.docker.internal.
      DASHBOARD_BRIDGE_URL: ${DASHBOARD_BRIDGE_URL:-http://host.docker.internal:${DASHBOARD_PORT:-8188}/aisc/bridge}
      DASHBOARD_BRIDGE_TOKEN: ${DASHBOARD_BRIDGE_TOKEN:?run scripts/secrets.sh first}
```

and after `restart: unless-stopped` for `platform`:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

- [ ] **Step 4: Run the tests.**

Run: `uv run --extra dev pytest -v`
Expected: all PASS, including the membership, project-database, deletion and template tests.

- [ ] **Step 5: Deploy, and check that the real project arrives.**

Run: `$DC up -d --build platform && sleep 70 && docker exec postgres psql -U aisc-postgres-user -d superset -At -c "select database_name from dbs order by 1"`
Expected: one `project_<hex>` row per `core.project` row, including `project_01399e174b014be9997a7f5e3574ab22`. There is no `AISC Results` row.

Then run: `docker logs platform 2>&1 | grep -c "dashboard was not told"`
Expected: `0`. A non-zero count here means the platform can't reach `host.docker.internal:8188`. Check with `docker exec platform python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8188/health', timeout=5).status)"`, which should print `200`.

- [ ] **Step 6: Commit.**

```bash
git add platform/platform_service/dashboard.py platform/platform_service/app.py platform/tests/test_dashboard_bridge.py
git add -p docker-compose.development.yml   # only the platform environment and extra_hosts hunks
git commit -m "The platform registers each project on the dashboard, keeps its members in step, and removes it"
```

---

### Task 9: Step 6 opens the project's dashboard, and the end-to-end checks

**Files:**
- Modify: `homepage/project.html`:
  - line 443, the step-6 card
  - lines 505-515, the `inProject` map
- Test: `scripts/verify-sso.sh` (end of section 4, after line 239)
- Test: `scripts/verify-rbac.sh`:
  - section 6, the `landed` check at lines 220-226
  - a new section 7 before the summary line 237

**Interfaces:**
- Consumes: `GET /aisc/p/{pid}` (Task 4), and the platform's pushes (Task 8).
- Produces: the step-6 card's `href` is `http://localhost:8188/aisc/p/<pid>`.

- [ ] **Step 1: Write the failing assertions.** In `scripts/verify-sso.sh`, after line 239 (the end of section 4), add:

```bash
# Step 6 of a project opens that project's own dashboard, on this same session.
hex=$(printf '%s' "$PROJECT" | tr -d -)
out=$(curl -s -b "$J" -c "$J" --max-time 20 -o /dev/null -w '%{http_code} %{redirect_url}' \
        "http://localhost:8188/aisc/p/$PROJECT")
case "$out" in
  "302 "*"/superset/dashboard/project-$hex/") ok "step 6 opens this project's own dashboard" ;;
  *) no "step 6 of the project gave: $out" ;;
esac
out=$(curl -s -b "$J" --max-time 20 -o /dev/null -w '%{http_code}' \
        "http://localhost:8188/aisc/p/00000000-0000-0000-0000-000000000000")
[ "$out" = "404" ] && ok "and a project the account is not in is not found" \
  || no "a project nobody is in gave $out"
page=$(curl -s -b "$J" --max-time 15 http://localhost:8100/p/x)
case "$page" in
  *"'dashboard-card': 'http://localhost:8188/aisc/p/'"*) ok "the launcher's step 6 goes through that door" ;;
  *) no "the launcher's step 6 does not open the project's dashboard" ;;
esac
```

In `scripts/verify-rbac.sh`, replace the `landed` block (lines 220-226) with:

```bash
landed=$(docker exec postgres psql -U aisc-postgres-user -d superset -At -c \
  "select string_agg(r.name, ',' order by r.name) from ab_user u join ab_user_role ur on ur.user_id = u.id
     join ab_role r on r.id = ur.role_id where u.username = 'user'" 2>/dev/null | tail -1)
case ",${landed:-none}," in
  *,Admin,*|*,Alpha,*|*,Gamma,*) no "an ordinary account is $landed on the dashboard" ;;
  *,AiscViewer,*) ok "an ordinary account is a viewer on the dashboard, plus its projects ($landed)" ;;
  ,none,)         ok "the ordinary account has not signed into the dashboard yet" ;;
  *)              no "an ordinary account is $landed on the dashboard" ;;
esac
```

Before the summary line (237), add:

```bash
echo
echo "7. the dashboard: one connection per project, and only its members"
SS() { docker exec postgres psql -U aisc-postgres-user -d superset -At -c "$1" 2>/dev/null; }
PL() { docker exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"' _ "$1" 2>/dev/null; }
# Projects older than the reconciler's round, so one made a second ago by
# this very suite cannot fail it.
projects=$(PL "select replace(pid::text, '-', '') from core.project where created_at < now() - interval '90 seconds' order by 1")
conns=$(SS "select substr(database_name, 9) from dbs where database_name ~ '^project_[0-9a-f]{32}\$' order by 1")
missing=$(comm -23 <(printf '%s\n' "$projects" | sed '/^$/d') <(printf '%s\n' "$conns" | sed '/^$/d'))
is "every project has its own dashboard connection" "" "$missing"
is "no connection reads the shared platform database" 0 \
   "$(SS "select count(*) from dbs where sqlalchemy_uri like '%/platform'")"
is "each project role reaches its own connection and nothing else" 0 "$(SS "
  select count(*) from ab_role r
   where r.name ~ '^aisc_project_[0-9a-f]{32}\$'
     and ((select count(*) from ab_permission_view_role prv where prv.role_id = r.id) <> 1
          or not exists (
            select 1 from ab_permission_view_role prv
              join ab_permission_view pv on pv.id = prv.permission_view_id
              join ab_permission p on p.id = pv.permission_id
              join ab_view_menu v on v.id = pv.view_menu_id
              join dbs d on v.name = '[' || d.database_name || '].(id:' || d.id || ')'
             where prv.role_id = r.id and p.name = 'database_access'
               and d.database_name = 'project_' || substr(r.name, 14)))")"
is "each project dashboard is published to its own role only" 0 "$(SS "
  select count(*) from dashboards d
   where d.slug ~ '^project-[0-9a-f]{32}\$'
     and (not d.published
          or (select count(*) from dashboard_roles dr where dr.dashboard_id = d.id) <> 1
          or not exists (select 1 from dashboard_roles dr join ab_role r on r.id = dr.role_id
                          where dr.dashboard_id = d.id and r.name = 'aisc_project_' || substr(d.slug, 9)))")"
held=$(SS "select substr(r.name, 14) || ' ' || s.subject from ab_user_role ur
             join ab_role r on r.id = ur.role_id join aisc_user_subject s on s.user_id = ur.user_id
            where r.name ~ '^aisc_project_' order by 1")
members=$(PL "select replace(project_id::text, '-', '') || ' ' || subject from core.project_member order by 1")
extra=$(comm -23 <(printf '%s\n' "$held" | sed '/^$/d' | sort) <(printf '%s\n' "$members" | sed '/^$/d' | sort))
is "nobody holds a project's dashboard role without being in the project" "" "$extra"
if "$(dirname "$0")/../apps/results-dashboard/scripts/verify_projects.sh" > /tmp/verify_projects.$$ 2>&1; then
  ok "per-project dashboards hold inside Superset ($(tail -1 /tmp/verify_projects.$$))"
else
  no "per-project dashboards inside Superset: $(grep '^FAIL' /tmp/verify_projects.$$ | head -3 | tr '\n' ' ')"
fi
rm -f /tmp/verify_projects.$$
```

- [ ] **Step 2: Run them and watch them fail.**

Run: `scripts/verify-sso.sh; scripts/verify-rbac.sh`
Expected:
- `FAIL the launcher's step 6 does not open the project's dashboard`.
- The two `step 6` door checks already pass, because the route exists since Task 4.
- verify-rbac: section 7 passes, and the `landed` line passes. If it fails, record what `landed` was and stop: it means an ordinary account holds Alpha or Gamma.

- [ ] **Step 3: The homepage.** In `homepage/project.html`, change line 443 to:

```html
    <a class="card" id="dashboard-card" href="http://localhost:8188/">
```

In the `inProject` map (lines 507-511), add a fourth entry, and replace the comment above it (lines 505-506) with:

```js
      // Modules that are on the project open inside it: each keeps this
      // project's data in this project's own database, the dashboard included.
      var inProject = {
        'control-objectives-card': 'http://localhost/control-objectives/p/',
        'controls-card': 'http://localhost/controls/p/',
        'qualification-card': 'http://localhost/qualification/p/',
        'dashboard-card': 'http://localhost:8188/aisc/p/'
      };
```

The page is served from a bind mount. Check how Caddy mounts `/srv/homepage` in `docker-compose-infra.development.yml`; a reload of the browser page is enough.

- [ ] **Step 4: Run them.**

Run: `scripts/verify-sso.sh && scripts/verify-rbac.sh`
Expected: `failed: 0` and `0 failed`.

- [ ] **Step 5: Commit.**

```bash
git add homepage/project.html scripts/verify-sso.sh scripts/verify-rbac.sh
git commit -m "Step 6 of a project opens that project's own dashboard"
```

---

### Task 10: End to end

**Files:**
- Modify: nothing new. Bump the `apps/results-dashboard` submodule pointer in the root.

**Interfaces:**
- Consumes: everything above.
- Produces: `scripts/verify.sh` → 0 failed. A walkthrough in which each project's step 6 shows only that project.

- [ ] **Step 1: The whole verdict.**

Run: `scripts/verify.sh`
Expected: `0 failed`. The `results dashboard` module suite is `ok` (`scripts/verify.sh:63`), and the stack checks (`verify-db-access`, `verify-one-database`, `verify-sso`, `verify-rbac`) all pass.

- [ ] **Step 2: Walk through it in the browser.**
  1. As `user` at http://localhost:8100, open the project → step 6, **Dashboard**. You land on "<project name>: results". With no engine tables in the project database yet, it shows the "No results yet" note, naming `engine.evaluation` and `engine.measurement`, and has no charts.
  2. Create a second project on the homepage. Within a minute its step 6 opens its own dashboard, and the first project's isn't listed in Superset's **Dashboards** menu for this account unless it's also in that project.
  3. In a private window, sign in as `admin`. Add `user` to the second project as a viewer, through the platform API as in Plan 1 Task 10 Step 6. Back in `user`'s window, reload Superset's dashboard list: the second project's dashboard is there.
  4. Remove `user` from the second project. Reload: it's gone, and http://localhost:8188/aisc/p/<second pid> answers 404.
  5. As `admin`, delete the second project (Plan 1 Task 11). Run `docker exec postgres psql -U aisc-postgres-user -d superset -At -c "select count(*) from dbs where database_name = 'project_<its hex>'"`. It prints `0`.

- [ ] **Step 3: Commit the pointer.**

```bash
git add apps/results-dashboard
git commit -m "The results dashboard reads each project's own database"
```

---

## Stopping rule and checkpoints

- **Checkpoint after every task:** that task's own test command, plus `scripts/verify.sh --modules`. From Task 4 on, add `apps/results-dashboard/scripts/verify_projects.sh`. A task isn't done until all of them are green.
- **Stop and ask:**
  - if Task 6 Step 1 shows any dataset on `AISC Results`;
  - if Task 4 Step 8 shows a non-member reading chart data before Task 5 (report it; don't weaken the check);
  - if `SET LOCAL ROLE` inside 0005's `DO` block is refused (Task 2 Step 2 turns into a different error than expected);
  - if the platform can't reach `host.docker.internal:8188` (Task 8 Step 5);
  - if any existing test outside this plan starts failing and fixing it would change its assertion.
- **Stop and report, don't fix:** `apps/results-dashboard/scripts/verify_review.py` is someone else's uncommitted file. It builds on the `AISC Results` connection (`:41`), which Task 6 removes, so it fails from then on. Also report the orphan `project_d78463…` database (no `core.project` row) if Task 2 Step 6 shows it without `dashboard_ro`.
- **Done when** `scripts/verify.sh` prints `0 failed`, `apps/results-dashboard/scripts/verify_projects.sh` prints `0 failed`, and the Task 10 Step 2 walkthrough behaves as written. Nothing is pushed.
