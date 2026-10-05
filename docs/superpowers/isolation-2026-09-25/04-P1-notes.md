# Stage 4, WP P1: platform, template 0006..0010, card versions per project database, init files

Date: 2026-09-25. Branch `isolation/2026-09-25`, top-level worktree `~/aisc-isolation` only. Nothing pushed; no
live database or running container touched (every run on throwaway `postgres:14-alpine` containers named
`aisc-t-*`, random ports, `PLATFORM_TEST_DATABASE_URL` always set; none left afterwards). The plan asks for a
section in `04-code-notes.md`; the orchestrator asked for this file instead, so the P1 notes are here.

## Commits (top-level repo)

| commit | content |
|---|---|
| `8c13e87` | templates `0006_project_system.sql` .. `0010_report_composer.sql`, `init/project-databases.sql` (definer function in template1, libraries, guarded core.system block) |
| `a9a0397` | `platform_service/db.py`, `app.py`, `projectdb.py`, `systems.py` (card versions in `project.system`) |
| `d9fe305` | `init/platform-db.sql`, `init/report-roles.sql`, platform migrations 0002..0004 guarded, new `0005_the_composer_reads_members.sql` |
| `a774ba2` | test changes (S-D13, named in the message), old-layout fixture, `scripts/lib/report_bed.py`, new `test_init_after_retire.py` and `test_role_setting.py` |
| `aae72d1` | `Isolation test correction T1`: `platform/tests/isolate_support.py` baseline name `20260925000000_project_database` |
| (this commit) | these notes and the PROGRESS.md line |

## What changed

- **Template.** `0006` makes schema `project` and `project.system` exactly as I1.5 (column order of I1.5, owner
  platform_rw, only-latest trigger, `REVOKE ALL FROM PUBLIC`, `USAGE` + `SELECT, REFERENCES` for the five module
  roles, `USAGE` + `SELECT` for report_ro and dashboard_ro; a missing role is skipped). `0007..0010` give the module
  role CONNECT, create its schema (owner platform_rw, comment), `USAGE, CREATE` to the role, `USAGE` to the two
  readers, and set the role's search_path in that database through the definer function (P1-D1). They raise a
  named error when the function or the role is missing.
- **Definer function** `aisc_setup.apply_role_setting(stmt text)` (P1-D1): created in `template1` by
  `init/project-databases.sql`, owner the superuser, `SECURITY DEFINER`, `SET search_path = pg_catalog`, EXECUTE
  and schema USAGE for platform_rw only. It runs a statement only if it matches
  `^ALTER ROLE (qualification_rw|control_objectives_rw|engine_rw|report_composer_rw) IN DATABASE (project_[0-9a-f]{32}) SET search_path = (qualification|control_objectives|engine|report_composer)$`,
  the role pairs with its own schema, and the database is `current_database()`; else `refused: ...`.
- **Card versions** (`db.py`): `create_version`, `list_versions`, `latest_version`, `get_system(version_pid,
  project_pids)` use `project.system` through `db.project_connection(pid)` (one connection per call, closed;
  `pg_advisory_xact_lock(hashtext('project.system'))` inside the project database). Responses keep their shape
  and key order; `project_id` is the project's pid from `core.project`. `db.ProjectDatabaseGone` (database
  missing, looked up first and also mapped from a connect error) becomes 404 in the three
  `/projects/{project}/system-versions*` routes. `GET /systems/{pid}`: non-uuid 404; scans only the caller's
  projects (all for an admin); `role_or_404` kept as a second check. `db.py` no longer names `core.system`.
- **projectdb.py**: `provision_as(dsn, pid, *, set_role=None, owner=None)` (`provision` calls it unchanged) and
  `install_setup_function(su_conn_to_target, template1_dsn) -> bool` (reads `pg_get_functiondef` from template1;
  no-op when present; raises when template1 lacks it). Both are for P2 and are tested in `test_role_setting.py`.
- **init/platform-db.sql** (fresh volume): only `core.project`, schema `catalogue`, roles (report_composer_rw
  added), CONNECT, `USAGE core`, `SELECT core.project` to the module roles and catalogue_rw (not dashboard_ro),
  platform_rw's rights on core, `form_library` (owner qualification_rw) and `report_library` (owner
  report_composer_rw), search_paths for platform_rw, dashboard_ro (`core`) and catalogue_rw (`catalogue, core`,
  as before). No core.system, no module schemas, no REFERENCES, no default privileges for a module role or
  dashboard_ro.
- **init/project-databases.sql** (every start): the function in template1; `form_library` / `report_library` in
  `platform` when their role exists; the core.system owner line and the composite-key block in one DO block that
  returns when core.system is absent or its comment begins with `retired:` (P1-D3, G4). The literal
  `ALTER TABLE core.system OWNER TO platform_rw` stays (inside `EXECUTE`).
- **init/report-roles.sql**: `SELECT core.project` only for report_ro and report_composer_rw; no core.system, no
  REFERENCES, no default privilege; the guarded `SELECT core.project_member` for the composer kept; the shared
  `report_composer` schema lines gone; `report_library` made if missing; composer search_path
  `report_library, core`.
- **Platform migrations**: 0002's carry-over insert, 0003's steps 1..5, 7, 8 and 0004's block are no-ops without
  core.system and unchanged in effect with it (live applied them already; the runner never re-runs a file).
  0003's step 6 (drop the freeze model) now runs after the guarded block, which is harmless (step 2 ran first).
  New `0005_the_composer_reads_members.sql`.
- **Old-layout fixture** `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql` = `git show
  f01288a:init/platform-db.sql`, byte for byte (G3).
- **`scripts/lib/report_bed.py`** builds the old layout from the fixture and, after `init/report-roles.sql`, adds
  the pre-isolation report-roles lines the new file no longer makes in `platform` (shared `report_composer` schema,
  `SELECT`/`REFERENCES` on core.system, the core default privilege, search_path `report_composer, core`).

## Existing tests changed (S-D13 and T1)

- `platform/tests/core_scratch.py`: `scratch_database(old_layout=False)`; `platform_db_sql_for(dbname, old_layout)`.
- `platform/tests/test_card_versions_migration.py`, `test_card_version_keys.py`: `scratch_database(old_layout=True)`.
- `platform/tests/test_api_system_versions.py`: its three direct SQL uses of `core.system` go to `project.system`
  of the project's database; `rows()` returns `[]` once the database is dropped (S2.5 deletes the project).
- `platform/tests/test_systems.py`: docstring.
- `platform/tests/isolate_support.py`: T1.
- Not in the plan (deviations D-P1-1, D-P1-2 below): `test_project_databases.py::test_nobody_but_the_listed_roles_may_connect`
  and `test_card_version_keys.py::test_0004_adds_the_unique_where_init_did_not`.

## Deviations and decisions (the plan was silent or wrong on these)

- **D-P1-1** `test_project_databases.py::test_nobody_but_the_listed_roles_may_connect` pinned that `engine_rw`
  cannot connect to a project database; 0009 must let it (I2.1). The refused role is now `catalogue_rw`, which
  no template file lists. Same assertion.
- **D-P1-2** `test_0004_adds_the_unique_where_init_did_not` asserted that all pending migrations after 0003 are
  exactly `[0004]`; the plan's new 0005 makes that `[0004, 0005]`. It now applies migrations up to 0004. Same
  assertion.
- **D-P1-3** New test files beyond the plan's list: `platform/tests/test_role_setting.py` (the definer function
  refuses 9 kinds of wrong statement, sets each module's own path, only platform_rw may call it, owner superuser
  and definer; `install_setup_function`; `provision_as` as the superuser gives a platform_rw-owned database with
  every template file). Reason: the function is a new privilege path and P2 relies on the two helpers.
- **D-P1-4** Templates 0007..0010 also raise when their module role is missing (the plan wanted that for
  report_composer_rw; the same for the others keeps the four files one shape). Consequence: a cluster must have
  run `init/platform-db.sql` (or report-roles.sql for the composer role) before a project is provisioned.
- **D-P1-5** `init/platform-db.sql` keeps `ALTER ROLE catalogue_rw IN DATABASE platform SET search_path = catalogue, core`
  (the catalogue stays shared; the old loop set it) but drops catalogue_rw's REFERENCES on core.project and
  dashboard_ro's USAGE and default privileges on `catalogue` (I1.4 lists dashboard_ro with only
  `SELECT core.project_member`).
- **D-P1-6** The composite-key block of project-databases.sql still adds module keys in `platform` while core.system
  is in use and not retired (old layout, before C9); G4's "touches no module schema" holds from retirement on.
  `test_init_after_retire.py` proves nothing changes after C9 and after the drop.
- **D-P1-7** The old-layout bed keeps the pre-isolation core default privilege for report_composer_rw (faithful to
  f01288a), which the plan's list of lines omitted.

## Test counts (throwaway databases; before = branch at `c4f21e9`, after = `aae72d1`)

| suite | before | after |
|---|---|---|
| platform, `--ignore=tests/test_isolate.py` | 32 failed, 287 passed, 2 skipped | 342 passed, 2 skipped (all 32 reds green; +23 new P1 tests) |
| platform `tests/test_isolate.py` (P2's) | 55 failed, 3 passed | 55 failed, 3 passed (P2 turns them green) |
| `scripts/tests/test_fresh_volume.py` | 21 failed, 1 passed | 1 failed, 21 passed (the one is `test_i16_4_post_projects_*`, the Z1 check: needs every module's migrate command) |
| `scripts/tests/test_isolation_unchanged.py` | 4 passed | 4 passed |
| `scripts/tests/test_project_grants.py` | 63 failed | 47 failed, 16 passed (the template parts; the rest wait for the module WPs and V1's report-grants) |
| top-level scripts, pre-existing files (12 files) | 226 passed, 25 failed (02-tests.md) | 218 passed, 33 failed: the 25 known plus 8, see below |
| report composer | 427 passed, 56 failed | 427 passed, 56 failed |
| report renderer (`~/aisc-isolation-report-generator`) | 648 passed, 24 failed | 648 passed, 24 failed |

`test_init_after_retire.py` was checked red against the old `init/project-databases.sql` (3 failed) before being
kept green with the new one.

### The 8 pre-existing scripts tests that turn red, and who owns them

All are harnesses that build the old shared layout from the current init files, or pin grants the design removes.
Each lives in a file another WP owns (G2, V1 section "Existing tests"), so P1 did not edit them:

- `test_card_version_keys_orders.py` (3): builds from the current `init/platform-db.sql` and needs core.system and
  `qualification` in `platform`. V1 pins its trees to f01288a (its plan override).
- `test_guard_frozen.py` (+1, 12 now) and `test_pipeline_chain.py` (+1, 6 now): reference/setup builds from the
  current init files. V1 (G2, I19.2).
- `test_db_consistency.py::test_c2_the_catalogue_is_never_flagged` (+1, 3 now): C2 reports `form_library` and
  `report_library` in `platform` as unknown schemas. V1 rewrites checks and the test.
- `test_report_grants.py::test_d13_composer_role_search_path` (its idempotence test re-runs the new
  report-roles.sql, whose composer search_path is `report_library, core`) and
  `::test_r7_3_3_composer_cannot_reach_projects_or_comments` (0010 now lets the composer connect to project
  databases, I2.1). V1 rewrites the file with R1's final grants (V1 section item 2).

## What wave-1 packages must know

- **Every module suite that builds the pre-isolation shared layout from `init/platform-db.sql` breaks now**: the
  file no longer makes `core.system` or `qualification`, `control_objectives`, `engine` in `platform`. Use the
  old-layout recipe of 03-coding-plan.md section 1.1 (fixture `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql`
  and `git show f01288a:init/report-roles.sql`) to measure a not-yet-converted baseline. Files that read the
  init file today: `apps/control-objectives/tests/isolation_support.py`,
  `apps/control-objectives/tests/test_migration_card_version_of_its_project.py`,
  `apps/backend/aisc_backend/tests/{isolation_support,test_isolation_engine_db}.py`,
  `apps/results-dashboard/tests/{test_project_datasets_db,test_isolation_dashboard_db}.py`,
  `apps/qualification/test/db/throwaway-db.sh`, `apps/report-composer/tests/{conftest,test_migration_keys}.py`
  (the composer ones still pass through `report_bed`).
- A throwaway cluster must run `init/project-databases.sql` (the whole file, with its `\connect template1`)
  before any project database is made, or templates 0007..0010 raise `aisc_setup.apply_role_setting is missing`.
  The module roles must exist too (`init/platform-db.sql`; report-roles.sql for report_composer_rw's password).
- In a project database each module role has: CONNECT, `USAGE, CREATE` on its own schema (owned by platform_rw),
  search_path set to that schema only (not `core`, not `project`: qualify `project.system` in SQL), `USAGE` on
  `project` and `SELECT, REFERENCES` on `project.system`. report_ro and dashboard_ro have `USAGE` on every module
  schema and `project`, `SELECT` on `project.system`; `SELECT` on module tables must come from each module's own
  migrations (I2.6).
- `project.system` has no `project_id`; the latest version is `ORDER BY number DESC LIMIT 1`; only platform_rw
  writes it (use the platform API; tests may insert as platform_rw).
- `platform` after P1 on a fresh volume: module roles have only `CONNECT`, `USAGE core`, `SELECT core.project`,
  `SELECT core.project_member`; qualification_rw owns `form_library`, report_composer_rw owns `report_library`.
- **P2**: use `projectdb.provision_as(su_dsn, pid, set_role="platform_rw", owner="platform_rw")` and, for a database
  made before the function existed (MCAS live), `projectdb.install_setup_function(su_conn, su_dsn)` before it.
- **X1 / C9**: the live `platform` still has the pre-isolation report-roles default privilege
  (`ALTER DEFAULT PRIVILEGES FOR ROLE platform_rw IN SCHEMA core GRANT SELECT ON TABLES TO report_composer_rw`)
  and the old module grants on core; the new init files do not remove them (they only run additive or guarded
  statements), so C9 must revoke them to reach I1.4. C9 must set the `retired:` comment on core.system for the
  guard in project-databases.sql to hold.
- `scripts/tests/test_report_stack.py::test_d6_guard_init_files_do_not_mention_report_roles` stays a known red on
  purpose: the plan puts report_composer_rw and report_library into platform-db.sql and project-databases.sql.
