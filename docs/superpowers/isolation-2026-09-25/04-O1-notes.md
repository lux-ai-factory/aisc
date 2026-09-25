# Stage 4, WP O1: control objectives on one database per project

Date: 2026-09-25. Worktree `apps/control-objectives`, branch `isolation/2026-09-25`. Nothing pushed. Suite runs
used the throwaway `aisc-t-iso-O1-10cf6702` (postgres:14-alpine, random port, new-layout recipe of 03-coding-plan.md
section 1.1), removed at the end.

## Commits

| repo | commit | content |
|---|---|---|
| control-objectives | `8af01ca` | existing tests changed by the design (S-D13, O1.8), new `tests/test_migration_project_database.py`, the two old migration test files removed |
| control-objectives | `3ef8b69` | `projectdb.py`, `migrate_projects.py`, settings, server, access, projects, upstream, `api/app.py`, `db/tables.py`, `db/repository.py`, `alembic/env.py`, baseline `20260926000000_project_database`, README, pyproject (`control-objectives-migrate` script); the six old revisions removed |
| top level | (this commit) | gitlink `apps/control-objectives`, these notes, the PROGRESS line |

Compose (O1.7) is W1's (G1) and was already on the branch: `test_compose_isolation.py -k 'i5_ or i16_4'` gives 10 passed.

## Counts (throwaway only)

| suite | before (committed HEAD 22ba3a2) | after (3ef8b69) |
|---|---|---|
| control-objectives, whole suite | 38 failed, 20 errors, 321 passed, 1 skipped (exactly 02-tests.md) | 372 passed, 1 skipped (`test_chain.py`, CHAIN_JSON unset) |
| ruff `src tests alembic` | 9 findings | 4, all in the baseline and in lines O1 did not write (`baf_llm.py`, `upstream.py` import block, `isolation_support.py`, `test_baf_llm.py`) |

All 58 stage-2 reds are green (30 static, 28 on real project databases), plus the 6 new migration tests.

## What was built (as the plan says unless listed under deviations)

- `projectdb.ProjectDatabases.open(project, caller, write)`: membership (`access.decide`, admin as owner), then the slug
  is resolved to the pid through `core.project`, then the database name is built, then the engine comes from an LRU
  of 20 (pool 2, overflow 0, pre-ping); the first open migrates it under a per-name lock; a missing database is
  `ProjectDatabaseGone`. `create_engine(` appears only in `projectdb.py`.
- The gate (`ProjectAccess`) calls `open` in the threadpool and leaves `request.state.opened`; refusals under
  `/p/{x}/api` are JSON. A `DBAPIError` naming a missing database evicts the engine and answers 404 (I2.5).
- JSON API only at `/p/{project}/api/projects[/{id}[/map|/severity]]`; the old `/api/projects*` are gone. The start
  form answers 409 "The latest version is not in this project's database." when `project.system` lacks the version
  (also on an FK violation at insert).
- `ProjectRecord.project` is the pid of the database it was read from, so the risk mapper resolves its LLM with that
  pid (I5.6). API auth (deny by default, route path, root-path bypass closed), the per-system LLM token path and the
  LLM keys behaviour are unchanged; every `test_api_auth.py` case is kept at the new paths.
- Alembic: one baseline (live names, no `project_id`, FK `fk_project_system_id_project_system` into `project.system`
  CASCADE, reader grants for report_ro and dashboard_ro, none on `alembic_version`). `env.py` takes a passed-in
  connection or `-x url=`, refuses `platform`, takes `pg_advisory_xact_lock(hashtext('aisc_control_objectives.alembic'))`,
  search_path `control_objectives` only, and raises `projectdb.SchemaMissing` when template 0008 has not run.
- `migrate_projects`: exit 0, 1 (platform unreadable), 2 (a permanent failure); skips missing, not-connectable and
  schema-less databases; prints database names and SQLSTATE codes only.

## Existing tests changed (S-D13, named in commit 8af01ca)

conftest (I5.7 refusal before connecting; `project.system` stand-in; `repository` per pid, database dropped on
teardown; `platform_project` is that pid; `system_version` writes `project.system`), `test_api_auth.py` (paths;
W-6 `test_a_page_refuses_an_assessment_of_another_project` rewritten in place on two real databases with the same
assertions, not deleted; `test_build_app_fits_the_gate` patches `server.ProjectDatabases`), `test_repository.py`
(`list()`; `test_listing_shows_one_project_and_not_another` deleted, mirrored by `test_I16_5_a_list_shows_only_...`;
the missing-project case became "a version absent from project.system"), `test_projects.py` and
`test_project_llm.py` (paths), `test_assessment_of_a_version.py` (`project.system`;
`test_s7_6_deleting_the_project_deletes_versions_and_assessments` deleted). Removed:
`test_migration_assessment_of_a_version.py`, `test_migration_card_version_of_its_project.py`, replaced by
`test_migration_project_database.py`. `test_chain.py` left to V1 (it still pins `fk_project_system_id_core_system`
and a repository on `platform`).

## Deviations and decisions

- **D-O1-1** One platform pool per URL per process (`projectdb.platform_engine`), shared by every
  `ProjectDatabases`. With a pool per instance, `test_I17_1_at_most_two_connections_per_project_and_two_to_platform`
  saw 12 platform sessions from the apps built by earlier tests in the same process. One app per process in
  production, so behaviour there is the plan's.
- **D-O1-2** The conftest refuses an unset `CONTROL_OBJECTIVES_TEST_DATABASE_URL` and port 5432 as well (the plan's
  "recommended hardening"); the old default pointed at the running stack. See the incident below.
- **D-O1-3** No shutdown hook (`on_event` is deprecated); `ProjectDatabases.dispose()` exists for callers.
- **D-O1-4** `test_migration_project_database.py` compares create_all and the baseline by constraints (names and
  definitions) and by index definitions without names: create_all names indexes
  `ix_control_objectives_<table>_<column>` (unchanged behaviour), the baseline keeps the live names the move needs.

## Incident (for the orchestrator)

My first baseline run (2026-09-25 about 14:54 to 14:57 UTC) read an env file in a shared scratchpad path that another
agent had overwritten, so `CONTROL_OBJECTIVES_TEST_DATABASE_URL` was unset and the committed conftest fell back to its
default `localhost:5432/control_objectives_test`, **the live cluster**. The pre-O1 suite there dropped and recreated
the leftover database `control_objectives_test` (now empty) and made and dropped scratch
`control_objectives_test_alembic_*` databases. That code path touches no other database: `platform`,
`control_objectives` and the project databases were not written (the isolation tests skipped without the variable).
Read-only checks afterwards: only `control_objectives` and `control_objectives_test` exist with that prefix, and the
latter has no tables. Nothing was repaired live. The contents of `control_objectives_test` before that run are
unknown; 01-specs.md 0.1 lists it as a leftover the user decides on (I15.3). D-O1-2 now makes this impossible.

## What later packages must know

- Env: `DATABASE_URL` = platform (membership), `PROJECT_DATABASE_URL` = template with `{database}` (unset: derived
  from `DATABASE_URL`). One-shot `python -m aisc_control_objectives.migrate_projects` (also `control-objectives-migrate`).
- New alembic head `20260926000000_project_database` (= `isolate_support.NEW_ALEMBIC`); target columns of
  `control_objectives.project` are `id, name, objectives_digest, created_at, updated_at, system_id`.
- The reader grants of I2.6 come from the baseline, so a database migrated before report_ro/dashboard_ro existed
  lacks them: V1's `report-grants.sh` repair is the backstop.
- V1: `tests/test_chain.py` still pins the old shared layout.
