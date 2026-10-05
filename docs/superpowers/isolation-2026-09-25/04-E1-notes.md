# Stage 4, WP E1: engine part 1 (aliases, router, migrate_projects, 0025, reader grants, stamp)

Date: 2026-09-25. Worktree `~/aisc-isolation/apps/backend`, branch `isolation/2026-09-25`. Nothing pushed. Every
database run was on one throwaway `postgres:14-alpine` (`aisc-t-iso-E1-*`, random port, new-layout recipe),
removed afterwards; `PLATFORM_TEST_DATABASE_URL` always set. No compose, guard or throwaway-pg file edited (G1, G2).

## Commits

| repo | commit | content |
|---|---|---|
| apps/backend | `922f6dc` | `Isolation test correction T5`: `_seed` closes `connections[alias]` in its `finally` |
| apps/backend | `58fed4c` | `aisc_backend/projectdb.py`, `management/commands/migrate_projects.py` (+ two `__init__.py`), `migrations/0025_the_database_is_the_project.py`, `config/settings.py`, `config/settings_single_database.py`, `auth/membership.py`, `platform_projects.py`, `repositories/system_version_repository.py`, `signals/system_stamp.py`, `repositories/measurement_repository.py`, `Dockerfile` |
| apps/backend | `fe5cdeb` | the three existing tests the design changes (S-D13), see below |
| top-level | (this commit) | these notes, the PROGRESS line, gitlink `apps/backend` |

## What was built (as the plan says, no interface change)

- Settings: on Postgres `default` is the dummy backend, `platform` is core-only (`search_path=core`,
  `CONN_MAX_AGE=0`), `PROJECT_DATABASE_TEMPLATE` has `search_path=engine`, `CONN_MAX_AGE=0`, router
  `aisc_backend.projectdb.ProjectDatabaseRouter`. On sqlite: one database, as before. `config.settings_single_database`
  gives the one-database layout on Postgres (tests and guard `--orders` only).
- `projectdb`: `PID`, `DATABASE`, `admitted`, `admitted_pid` (for E2), `NotAPid`, `NoProjectAdmitted`,
  `NoSuchProjectDatabase`, `SchemaNotProvisioned`, `MigrationFailed`, `enabled`, `normalise`, `database_name`,
  `pid_of`, `alias_for` (copy-on-write registration under a lock, no I/O), `forget`, `ensure` (connect; 3D000/42501
  forgets the alias and raises `NoSuchProjectDatabase`), `open_alias` (ensure, then migrate once per process under a
  per-alias lock; failures not remembered), the router (raises `NoProjectAdmitted` with nothing admitted).
- `migrate_projects`: lists `project_<hex>` databases engine_rw may CONNECT to (pg_database), per database
  `migrate_database(alias)` under `pg_advisory_lock(0x656E67696E65)`: migrate, then the I2.6 reader grants as
  engine_rw; skips unprovisioned databases, prints names and exception types only, exits non-zero on any failure.
- 0025: RunPython, Postgres only, adds `aisc_backend_evaluation_system_id_fkey` to `project.system(pid)` ON DELETE
  SET NULL when the table exists and the key is absent; no `core.` in the file. 0015, 0022, 0023 untouched.
- Membership and name lookup on `connections["platform"]` (falls back to `default` in single mode); new
  `platform_project_exists(pid)` (True without a platform table). Stamp reads `project.system` on the
  `using` alias of the save. Dockerfile CMD runs uvicorn only.

## Existing tests changed (S-D13, commit `fe5cdeb`)

- `test_frozen_sean_files.py`: `config/settings.py` leaves `SEAN_FILES_2026_09_23` (comment names I7.12).
- `test_one_system_per_project.py::test_s1_0023_is_the_leaf`: leaf 0025, and its parent is 0024 (0024's parent
  check kept).
- `test_evaluation_system_stamp.py`: `_make_project_system` (pid, number UNIQUE); `_add_version` ignores the
  project; the other project's row removed from `test_s9_2_highest_number_wins`; `test_s9_3_..._project_system_is_absent`.

## Deviations and flags

- **D-E1-1** `test_s9_3_none_when_project_system_is_absent` also reads the catalog through `sync_to_async`: the old
  test ran a cursor directly in an async test and always raised `SynchronousOnlyOperation` (the known Postgres red
  `s9_3`). Same assertion; it now passes.
- **D-E1-2 (flag, not edited)** `test_isolation_engine_db.py::TheOneShotMigratesEveryProjectDatabase::test_i7_9_no_foreign_key_leaves_the_database`
  is a test bug no code can fix: its query has `LIKE 'core.%'` and `Cluster.rows` passes `params=()`, so psycopg
  rejects `%'` as a placeholder (ProgrammingError). Not in T1..T7, so left as is. Correction for the orchestrator:
  `'core.%%'` (or pass `None` params). Checked by hand on a migrated project database: with `%%` the query returns
  no row, and the only key leaving `engine` is `project.system`.
- `test_project_grants.py -k engine`: 5 passed, 9 fail only on the bed's shared `require` of every module
  (qualification Q1, control-objectives O1 and composer R1 missing); the bed's engine migration succeeded.

## Counts (before = branch at 3e262a7, after = fe5cdeb)

| suite | before | after |
|---|---|---|
| backend sqlite (`manage.py test aisc_backend`) | 203 ran, 54 failures, 5 errors, 40 skipped | 203 ran, 32 failures, 5 errors, 40 skipped; nothing newly red |
| `test_isolation_engine.py` E1 classes (22 tests) | all red | 22 passed |
| backend Postgres, pre-existing suite, superuser (after: `DJANGO_SETTINGS_MODULE=config.settings_single_database`) | 203 ran, 53 failures, 6 errors, 37 skipped | 203 ran, 32 failures, 5 errors, 37 skipped (s9_3 green); nothing newly red |
| `test_isolation_engine_db.py` (engine_rw, deployed settings) | 28 ran, 27 failed, 1 passed | 28 ran: 17 passed, 11 failed = 10 E2 (`TheDoorOnPostgres` 4, `NothingOfAIsReachableUnderB` 5, `ADroppedDatabase.test_i2_5`) + D-E1-2 |
| `scripts/tests/test_guard_frozen.py` | 12 failed, 7 passed | 12 failed, 7 passed (same set) |
| `test_compose_isolation.py -k i7_6` | (W1 done) | 2 passed |
| `test_isolation_harnesses.py -k "i7_12 or i19_2"` | red | 5 failed, 1 passed: V1's (guard-frozen, throwaway-pg, pipeline chain) |
| `makemigrations --check` (G5, sqlite) | clean | clean |

Remaining sqlite and Postgres reds: E2's door, ticket and start-route tests, plus the known reds (F5 ImportError,
`test_g4` now 2 subtests: `routers/plugin.py`, `pyproject.toml`; three keycloak integration; three
`project_config_router`; `s1_aisystem`).

## For V1 (G2)

- G4 (backend) part 1: exclude `config/settings.py` by name (I7.12). Part 2 `backend_allowed`: `config/settings.py`,
  `config/settings_single_database.py`, `aisc_backend/projectdb.py`, `aisc_backend/management/*`,
  `aisc_backend/migrations/0025_the_database_is_the_project.py`, `aisc_backend/auth/membership.py`,
  `aisc_backend/platform_projects.py`, `aisc_backend/repositories/measurement_repository.py`,
  `aisc_backend/repositories/system_version_repository.py`, `aisc_backend/signals/system_stamp.py`, and for E2
  `aisc_backend/services/celery_service.py`, `aisc_backend/project_door.py`. Dockerfile rule: CMD block has no
  `manage.py migrate` other than `migrate_projects`.
- G5: no change needed (verified clean). G1 candidate: `tpg_project_db` + `manage.py migrate_projects` with deployed
  settings (engine_rw, `DB_NAME=platform`, `DB_SCHEMA=engine`). The only G5-style settings variable is the module
  `DJANGO_SETTINGS_MODULE=config.settings_single_database`, for guard `--orders` step E on the candidate tree only.

## What E2 must know

- Admit a request with `token = projectdb.admitted.set(projectdb.open_alias(projectdb.alias_for(pid)))` (and
  `admitted_pid`), then reset both in `finally`. `alias_for` raises `NotAPid` (404); `open_alias` raises
  `NoSuchProjectDatabase` (404; the alias is already forgotten), `SchemaNotProvisioned` (map to 404) or
  `MigrationFailed` (500/503).
- `TheDoorOrder` patches `projectdb.alias_for` and expects it called once, with the pid, only after every check.
- Connections are thread-local and `CONN_MAX_AGE=0`: close `connections[alias]` in the thread that used it at the end
  of the request (the view runs under `sync_to_async`), or `test_i17_1` sees a lingering session (it passes now).
- `membership.role_in_project` lets `DatabaseError` propagate (door answers 503); `platform_projects.platform_project_exists`
  is the "pid with no core.project row is 404" check.
- `ADroppedDatabase.test_i2_5`: first call on C was 500 with no door; after a drop, `open_alias` evicts the alias.
- With nothing admitted every ORM call raises `NoProjectAdmitted` (not an OperationalError), including the
  `membership.for_*` helpers, which must therefore run after admission.
