# Stage 4, WP D1: the results dashboard reads each project from its own database

Date: 2026-09-25. Branch `isolation/2026-09-25`, submodule worktree `apps/results-dashboard` only, plus
the gitlink, these notes and the PROGRESS line in the top-level repo. Nothing pushed. No live database, no
running container and no Superset touched (the stack's Superset was never called). Every database run was on a
throwaway `postgres:14-alpine` named `aisc-t-iso-dash-*` on a random port, removed afterwards. The plan asks
for a section in `04-code-notes.md`; the orchestrator asked for this file instead.

## Commits

| repo | commit | content |
|---|---|---|
| apps/results-dashboard | `7ff4999` | code, config text, S-D13 test changes, new `tests/test_isolation_d1.py` |
| top-level | (the commit with this file) | gitlink `apps/results-dashboard`, these notes, the PROGRESS line |

The plan's top-level commit also held `docker-compose.development.yml`. Under G1 that is W1's file, and W1
already committed the dashboard lines (`215bb95`: `AISC_MEMBERSHIP_DB_URI` on `dashboard`, nothing left in
`&dashboard-env`, `AISC_PROJECT_DB_HOSTPORT: localhost:5432`). D1 did not touch any top-level compose or env file.

## What changed (apps/results-dashboard)

- `aisc_ext/projects.py`: `engine_results_sql()` takes no argument and returns the plan's SQL (no `engine.project`
  join, `LEFT JOIN project.system`, no `WHERE`, no trailing semicolon). `register_project` puts
  `engine_results_<hex>` on `AISC Controls <slug>`; a dataset that still sits on `AISC Results` is moved in place
  by the upsert and keeps its id. Only `READ_ONLY_ROLE` is imported from `results_db`. The docstrings name the
  project connection and `AISC_MEMBERSHIP_DB_URI`.
- `aisc_ext/results_db.py`: `registration_for` and `register_results_database` removed. Kept: `READ_ONLY_ROLE`,
  and `RESULTS_DB_NAME = "AISC Results"`, documented as the retired name. Added: `MEMBERSHIP_ENV`,
  `membership_uri(env=None)` (strips, `None` when blank, `ValueError` with "read-only" unless the DSN connects as
  dashboard_ro; the message never contains the DSN), and `remove_results_connection(*, store=None) -> int` (plan
  override; see below).
- `aisc_ext/sso.py` `_member_projects`: `membership_uri(os.environ)`; `ValueError` is logged, then `[]`;
  `create_engine(uri, poolclass=NullPool)`, `engine.dispose()` in `finally`. No `AISC_RESULTS_DB_URI`,
  `superset.models.core` or `Database(` in the file. The gateway calls it unchanged.
- `superset_config.py`: the registration import and call are gone; `_install_extension(app)` stays inside
  `app_context`. A comment says analytics connections use Superset's default engines without a persistent pool
  (checked in the 4.1.1 source: `Database._get_sqla_engine(nullpool=True)` by default). The comment contains no
  `QueuePool` and no `pool_size`.
- `docker-compose.yml`: `AISC_MEMBERSHIP_DB_URI: ${AISC_MEMBERSHIP_DB_URI:-}` replaces the results DSN, plus
  `AISC_PROJECT_DB_HOSTPORT: ${AISC_PROJECT_DB_HOSTPORT:-postgres:5432}` (see D-D1-3).
- `.env.example`, `docker-compose.aisc.yml` (comment), `README.md` (env table), `scripts/bootstrap.sh` ("Next:"
  text): the membership DSN (dashboard_ro on `platform`), and project connections made by the bridge from
  `AISC_PROJECT_DB_HOSTPORT`.
- `scripts/verify_review.py`: no `RESULTS_DB_NAME`. It takes the first `Database` (by id) whose `extra` carries
  `aisc_project` and exits with a clear message when there is none.

### `remove_results_connection` (for X1 at C12)

`remove_results_connection()` with no argument runs on Superset's metadata database (`superset.db.engine`, so it
needs an app context: `superset shell` or a script that pushes one), in one transaction. It:

1. finds the `dbs` row named `AISC Results`, and returns 0 if there is none;
2. refuses with `RuntimeError` ("... still has N dataset(s) on it: re-register every project first ...") when any
   `tables` row has that `database_id`;
3. reads every foreign key of the metadata database (SQLAlchemy inspector) and takes the tables with a
   single-column foreign key to `dbs(id)`;
4. deletes those tables' rows for that id so that a table that references another of them goes first
   (Superset 4.1: `table_schema` before `tab_state` before `query`), then the `dbs` row, and returns the number
   of rows deleted.

What it does not delete: Superset's permission rows for the connection (`ab_view_menu` names such as
`[AISC Results].(id:1)` and their `ab_permission_view*` rows). They have no foreign key to `dbs`, grant access to
nothing once the connection is gone, and are outside the plan's rule; X1 may leave them. A table that references
one of the dependents but not `dbs` itself (for example the columns of a dataset) is not followed: step 2
guarantees there is no dataset, and a foreign key violation on anything else rolls back the whole transaction
and raises, so nothing is half-deleted.

Tested on an FK-enforcing fake (`tests/test_isolation_d1.py`, 5 tests), and checked once by hand with
SQLAlchemy 1.4.54 and psycopg2 on a throwaway Postgres with the Superset shapes of `dbs`, `tables`,
`saved_query`, `query`, `tab_state`, `table_schema`: it refused while a dataset sat on the connection, then
removed 5 rows, left the project connection and its rows alone, and returned 0 on a second run. That probe is
not a committed test, because the suite's venv has no SQLAlchemy.

## Existing tests changed (S-D13, as the plan says)

- `tests/test_projects.py`: module docstring; `test_s11_1_engine_dataset_is_on_the_results_connection_and_carries_the_version`
  renamed to `..._on_the_project_connection_...`, asserts `AISC Controls mcas` and
  `left join project.system s on s.pid = e.system_id` (column assertions kept);
  `test_s11_4_engine_dataset_filters_on_this_project_only` now asserts no pid, no `where`, no `project_id`;
  `test_s11_4_a_pid_that_is_not_a_uuid_never_reaches_the_sql` keeps its 4 cases and asserts `ValueError` from
  `register_project` and `project_role_name`.
- `tests/test_results_database.py`: retargeted to `membership_uri` / `AISC_MEMBERSHIP_DB_URI` (tests 1 to 3 keep
  their intent); test 4 (`..._the_name_is_stable_...`) deleted, its counterpart is
  `test_isolation_dashboard.py::test_i10_2_results_db_registers_nothing_named_aisc_results`.
- `tests/test_project_datasets_db.py`: exported names `CONTAINER`, `ENGINE_DDL`, `ROOT`, `psql` unchanged.
  `_seed_platform` applies the two init files only when `to_regnamespace('core') IS NULL`, keeps the platform
  migrations and the `core.project` rows P and Q, and no longer makes engine tables or `core.system` in
  `platform`. `_seed_controls` became `_seed_project(db, versions, eval_version, *, answer_version=None)` (see
  D-D1-2) for P's and Q's databases. `Seeded.missing` keys are `platform` and `project`. The two engine tests run
  `engine_results_sql()` in the project databases as dashboard_ro. S11.2 and the controls tests are unchanged
  apart from the fixture.

## Deviations and decisions (the plan was wrong or silent)

- **D-D1-1 No permission refresh in `SupersetStore._upsert_dataset`.** The plan asked for
  `found.perm = found.get_perm()` (and `schema_perm`) after `found.database = database`. In Superset 4.1.1
  (`superset/security/manager.py`, `dataset_before_update` and `_update_dataset_perm`), a change of `database_id`
  already renames the dataset's view menu from `target.perm` to the new name (so every role that held it keeps
  it) and rewrites `tables.perm` and the `perm` of every chart on the dataset. With the plan's refresh, the old and
  new names are equal when the hook runs: it finds no view menu under the new name, inserts a fresh one, and
  returns before updating the charts. Their `slices.perm` would then stay on `[AISC Results]...`, and Superset's
  chart list filters on that column. So the upsert leaves `perm` alone, with a comment saying why, and
  `test_a_moved_dataset_keeps_its_old_permission_names_for_supersets_rename_hook` pins that. It passed before the
  change too: it guards against someone adding the refresh later, it is not a red.
  `register_project` upserts the role after the datasets, and the session expires on commit, so the role is given
  the renamed permission.
- **D-D1-2** `_seed_project` has one extra keyword, `answer_version`: only P gets a controls answer (stamped V2),
  and the engine project's `project_id` is taken from the database name.
- **D-D1-3** `docker-compose.yml` (the dashboard's standalone compose) also passes `AISC_PROJECT_DB_HOSTPORT`, with
  the default `postgres:5432`, so the variable `.env.example` documents reaches the container. The default must
  not be empty: an empty value would override the code's `postgres:5432` fallback and give a URI with no host.
- **D-D1-4** The fixture creates `controls."_prisma_migrations"` (Prisma's own definition) before it replays the
  controls migrations with psql. C1's new `20260926000100_readers_read_the_listed_tables` revokes the readers'
  SELECT on that table, which Prisma always makes before it applies a migration. Without the stand-in, 5
  controls/engine DB tests went red as soon as C1's files appeared in the controls worktree. The stand-in is
  `IF NOT EXISTS` and works with or without C1's files.
- **D-D1-5** Beyond the plan's list, `tests/test_isolation_d1.py` (7 tests) covers `remove_results_connection`, the
  perm guard and `verify_review.py`.

## Test counts

Suite: `apps/results-dashboard`, `AISC_DASHBOARD_TEST_PG_CONTAINER=<bare throwaway> PYTHONPATH=. uv run --no-project
--with pytest python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py` (never `test_sso_login.py`).

| state | result |
|---|---|
| before (branch at `9e0d018`, after P1 on the top level) | 15 failed, 119 passed (134) |
| after (`7ff4999`) | **140 passed, 0 failed** |
| after, without a container (quick loop) | 130 passed, 10 skipped |

The 15 reds before: the 10 stage-2 unit reds of `test_isolation_dashboard.py`; 2 of the 4 in
`test_isolation_dashboard_db.py` (the two grant tests there already passed once P1's templates existed); 3 in
`test_project_datasets_db.py`, where the old fixture failed on `CREATE SCHEMA core` after the isolation module had
initialised the cluster (as the plan predicted). The plan expected 133. The difference is +7 from
`test_isolation_d1.py` (140 = 110 baseline - 1 deleted + 24 stage-2 + 7).

Top level: `scripts/tests/test_compose_isolation.py -k "i10_2 or (i16_4 and dashboard)"`: 3 passed (W1's compose
lines; read-only `docker compose config` on a copy).

## What later packages must know

- **X1 (C12):** delete `AISC Results` with `remove_results_connection()` inside the dashboard image with an app
  context (`superset shell`, or `python -c` with `create_app()` and `app.app_context()`). Run it only after C11
  has re-registered every project (the platform's `provision_all` on its first query). It raises if any dataset is
  still on the connection, so it doubles as the "no dataset uses it" check. It prints nothing; the caller prints
  the count it returns. Its permission rows stay (see above).
- **Stage 5 rehearsal:** check that a project created at runtime gets a working `engine_results_<hex>`. The upsert
  runs `fetch_metadata()` on the project connection, which needs the engine tables and dashboard_ro's SELECT on
  them (E1's `migrate_projects` grants). Errors are not swallowed, so the platform's retry
  (`db._unregistered`, `provision_all`) registers it later.
- **At cutover:** a pre-isolation `engine_results_<hex>` moves from `AISC Results` to the project connection in
  place (same id; charts keep working). Superset's hook renames its permission, so the project role and the charts
  follow without a manual step.
- **E1/V1:** the dataset reads `engine.measurement`, `observation`, `evaluation`, `metric` and `project.system` as
  dashboard_ro in the project database, so these must be in dashboard_ro's reader grants (I2.6 lists them; the
  dataset no longer needs `engine.project`).
- **V1 (I16.4):** the dashboard's only `platform` DSN is `AISC_MEMBERSHIP_DB_URI`. The Superset metadata DSN
  (`SUPERSET_DB_URI`, database `superset`) is the other one and is expected.
- The dashboard's fixture reads the controls migrations straight from `apps/controls/prisma/migrations`, so a
  controls migration that needs `project.system` rows or `_prisma_migrations` must keep working on a psql replay
  in that order. It does today, with C1's files.
