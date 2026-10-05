# Stage 4, WP R1: report composer on project and library databases

Date: 2026-09-25/26. Top-level worktree `~/aisc-isolation`, branch `isolation/2026-09-25`. Nothing pushed. No live
database or `aisc` container was touched. Every run used throwaway `aisc-t-*` containers: the beds' own containers
on random ports (`check_dsn_env` refuses 5432 and now also checks `REPORT_COMPOSER_PROJECT_DATABASE_URL`), plus one
recipe container for the move-tool fixture tests, whose credentials were kept only in `scratchpad/R1/` and deleted
afterwards. No container was left at the end.

## Commits (top-level repo)

| commit | content |
|---|---|
| `657f822` | tests and infrastructure (S-D13, listed below) |
| `ea75695` | product code: `migrations/project/0001_project_database.sql`, `migrations/library/0001_presets.sql`, old 0001..0005 moved to `pre_isolation_migrations/`, `projectdb.py` (new), `app.py`, `migrate.py`, `db.py`, `api.py`, `pages.py`, `reports.py`, `records.py`, `presets.py` (docstring), `README.md` |
| (this commit) | these notes and the PROGRESS.md line |

## What changed

- **Two connections (I8.1).** `create_app(*, database_url, project_database_url, renderer, clock)`. The defaults
  come from `REPORT_COMPOSER_DATABASE_URL` and `REPORT_COMPOSER_PROJECT_DATABASE_URL`, and construction never
  connects. `app.state.projects` is a `ProjectDatabases(template, platform_url)`. Each project read or write uses
  `projects.connect(pid)` inside the guarded route, so the guard decides membership before a project database
  opens. Presets use `db.connect(database_url)` on `platform`. The only tables named on `platform` are
  `core.project`, `core.project_member` and `report_library.*`.
- **`projectdb.py`.** `database_name` (the I1.8 pattern, else ValueError), `dsn_for`, and `ProjectDatabases` with
  `dsn`, `exists` (`pg_database` on platform), `mark_migrated`, `forget` and `connect`. `connect` works like this:
  - The first open of a database in this process runs `migrate.migrate_project`, under a per-name thread lock
    and the database's advisory lock 8_190_233_707.
  - Each call gets one connection holding one transaction, closed afterwards. There is no pool.
  - An `OperationalError` at connect time gives 404 if the database is gone (the mark is forgotten), else 503.
    The error text is never parsed.
  - A missing `report_composer` schema, or a template without `{database}`, gives 503.
  - A non-uuid pid gives 404.
- **`migrate.py`.** The generic `migrate(conn, directory, table, *, create_schema=True)` is kept, and the old tests
  still use it. It adds `migrate_library`, `migrate_project` (both with `create_schema=False`, raising
  `SchemaMissing`), `project_databases`, `migrate_everything` (optionally the library first, then every pid of
  `core.project` whose database exists; result per name is `ok` or `failed: <Class>`), and
  `main()`/`python -m report_composer.migrate`. At top level it imports only the standard library and psycopg.
  The literal `8_190_233_707` is kept.
- **Start (lifespan).** It migrates the library first; a failure there is fatal. Then it calls
  `migrate_everything(..., library=False)` and marks each `ok` database as migrated. A database that fails is
  logged with its name and exception class, and is tried again on its first open.
- **`db.py`, `records.py`, `api.py`, `pages.py`, `reports.py`.**
  - No `project_id` column or filter remains. Versions come from `project.system`, and `get_report` joins
    `project.system`.
  - `layout_view(layout, project_pid)` fills `project_id` from the guard.
  - `post_layout` keeps its check order: system, template, preset (a saved preset is read on platform), names.
  - `save_as_preset` reads the layout on the project connection, then inserts on platform, as two steps.
  - The layouts page reads presets on its own platform connection.
- **Migrations (I8.2).** The project baseline is the final shape of 0001..0005 without `project_id` and without
  the preset table. Its tables are `template`, `layout`, `layout_block` and `generated_report`, keeping the live
  column order and the live constraint names. The uniques on (project_id, name) become `template_name_key` and
  `layout_name_key`. Both `system_id` keys point to `project.system(pid)` with NO ACTION. The file is DDL only and
  grants nothing (I2.6). The library file creates `report_library.preset` with `source_project_id uuid` and no key.

## Existing tests changed (S-D13; the reason in every case: the approved design moves the composer's tables into the project databases and presets into `report_library`; no assertion weakened)

- `tests/conftest.py`: `bed` = `build_isolated("composer", modules=False, no_database=frozenset())`; `pdb_of(key)`;
  `make_client` sets and passes the project DSN template; `clean_layouts` truncates in A, B, C, E; docstring.
- `tests/v2_fakes.py`: `clean_presets` on `report_library.preset`; `scalar_json(..., db="platform")`.
- `tests/test_api_layouts.py`: `test_r4_1_3` counts the history in alpha's database. Its owner check became two
  checks: the table `report_composer.layout` is owned by report_composer_rw, and the schema `report_library` is
  owned by report_composer_rw. `test_r3_10` and `test_r3_13` use `pdb_of("A")`.
- `tests/test_api_reports.py`: reads in `pdb_of("A")`; the running-report insert has no `project_id`.
- `tests/test_p2_english_only.py`, `test_v2_layout_settings.py`, `test_v2_pages.py`, `test_v2_reports.py`,
  `test_v2_presets.py` (and its docstring): the same database swap, and presets in `report_library.preset`.
- `tests/test_v2_browser.py`: passes `project_database_url`.
- `tests/test_e2e.py` and `tests/test_e2e_v2.py`: `build_isolated("e2e"/"e2e2", modules=True)`, with the project
  DSN. The stored-report read in `test_e2e_v2` reads mike's database. The plan named echo (`IDS["E"]`), but the
  test's layout is under `/api/p/mike`, so mike's database is where the row is.
- `tests/test_migration_keys.py`: `MIGRATIONS = pre_isolation_migrations`. It has its own module bed,
  `report_bed.build("composer-keys", modules=False)`, where the files are applied with the generic runner as
  report_composer_rw. A local `bed` fixture truncates on platform. Each test takes `migrated` instead of
  `client`, and the assertions are unchanged.
- `tests/test_v2_migration.py`:
  - `mig` runs 0001..0004, inserts the old rows, then runs 0005 with the generic runner. The R-D.1 and R-U2.4
    tests lost their start trigger and kept their assertions.
  - The new fixture `moved` builds an isolated bed and migrates alpha's database. It copies alpha's rows of
    template, layout, layout_block and generated_report by column name, without `project_id`, reading json as
    text, and then starts the new app.
  - The three `test_r_c_3_*` tests use `moved`. The last one's format check reads alpha's database.
- Path only: `platform/tests/isolate_support.py:54`, `scripts/tests/test_db_consistency.py:140` and
  `scripts/tests/test_card_version_keys_orders.py:148,187` now point at `pre_isolation_migrations`.
- Item 13, which the plan marks optional: `REPORT_COMPOSER_PROJECT_DATABASE_URL` was added to
  `report_bed.DSN_ENV_VARS`.
- Item 1 (`no_database`) had already been done by R2.

## Counts

| suite | before | after |
|---|---|---|
| composer, full (red-before on a `git archive` export of `79898be`) | 59 failed, 424 passed (25 + 31 isolation, 3 e2e) | **483 passed, 0 failed** |
| composer, R1's two isolation files | 56 failed | 56 passed |
| renderer (`~/aisc-isolation-report-generator`, `AISC_INSTALL_DIR=~/aisc-isolation`) | 672 passed (R2) | **672 passed** |
| `platform tests/test_isolate.py -k fixture` (recipe throwaway) | 3 passed (P2) | 3 passed |
| scripts: `test_compose_isolation`, `test_db_consistency`, `test_card_version_keys_orders`, `test_report_stack` | see below | 94 passed, 8 failed |

The 8 scripts reds are the same tests P1 recorded as red before R1 (04-P1-notes.md, "The 8 pre-existing scripts
tests"). They are:
- `test_db_consistency` (3): `verify-db-consistency.sh` flags the isolated layout. V1 owns this.
- `test_card_version_keys_orders` (3): the harness builds from the current init files, and qualification's Prisma
  step fails there. V1 pins it to f01288a.
- `test_report_stack` (2): the known `test_d6_*` and `test_final_guard_frozen_passes`.

Every `test_compose_isolation` test is green, including the two R1 cases
`test_i8_1_composer_has_a_project_database_template_and_platform_for_the_library` and
`test_i16_4_...[report-composer]`, because W1 had already wired the compose file.

A `git archive` export cannot run these four files again for a before/after pair, because it has no submodules.
The evidence that R1 did not cause them is the matching test names and failure messages: both point at the
script and at Prisma, never at the composer. The plan's "db_consistency 2 failed" baseline predates P1's
`test_c2` red.

## Deviations and decisions

- **D-R1-1 The compose file is not in the R1 commit.** W1 had already added
  `REPORT_COMPOSER_PROJECT_DATABASE_URL` (G1).
- **D-R1-2 The red-before count was measured on a clean export.** My first baseline run overlapped my first
  edits, so I stopped it by PID. I then ran the suite on a `git archive` of HEAD in `scratchpad/R1/head`, which
  is now removed.
- **D-R1-3** `git mv` staged renames in the shared index. I unstaged them straight away, so the other agent's
  commits could not pick them up, and committed them only with R1's product commit.
- **D-R1-4** `test_e2e_v2` reads mike's database, not echo's (see above).
- **D-R1-5 Extra 503 cases.** A template without `{database}`, or a missing `report_composer` schema, answers
  503 (`unavailable`), not 500.
- **Flagged tests:** none. W-5 (`test_i17_1` reading `pg_stat_activity`) did not flake in the two runs made (R1 files alone, full suite).

## What V1 and X1 must know

- **V1:**
  - The composer's project history is `report_composer.schema_migration`, holding `0001_project_database.sql`
    in each project database. The library history is `report_library.schema_migration`, holding
    `0001_presets.sql` in `platform`. `python -m report_composer.migrate` creates both. The project tables are
    owned by report_composer_rw, and report_ro and dashboard_ro get no SELECT on them (I2.6).
  - `test_report_grants.py` must pin these final grants: the composer has CONNECT and `USAGE, CREATE` on
    `report_composer` in each project database, and on `platform` it has `report_library` (as owner),
    `SELECT core.project` and `SELECT core.project_member`.
  - `test_db_consistency.py` and `test_card_version_keys_orders.py` now read `pre_isolation_migrations/`. Their
    remaining reds are V1's.
- **X1:**
  - C4 must apply the old 0003..0005 from `git show f01288a:apps/report-composer/migrations/<file>`, or from
    `apps/report-composer/pre_isolation_migrations/` (the same bytes). The image no longer ships them.
  - At C7, run the composer's migrate-only step as `python -m report_composer.migrate` with both DSNs.
  - `migrate.main` exits 1 when the library or any project database fails, and its one-shot has
    `restart: "no"` without W1's exit-2 loop. So one broken project database blocks the composer from starting
    (`service_completed_successfully`). The running app itself would skip it and try again on first open. The
    orchestrator decides whether the one-shot should tolerate a failed project.
  - The data move copies `template`, `layout`, `layout_block` and `generated_report` by column name, without
    `project_id`. The column order and constraint names match the live tables, except for the renamed uniques
    `template_name_key` and `layout_name_key`. Presets go to `report_library.preset`, with `source_project_id`
    copied as a plain uuid.
