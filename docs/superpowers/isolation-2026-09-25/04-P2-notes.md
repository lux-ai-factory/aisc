# WP P2 notes: the move tool, `python -m platform_service.isolate`

Date: 2026-09-25 (work begun by a first P2 agent, which was interrupted before its last suite run;
finished, reviewed module by module against the plan and re-measured by a second P2 agent). Branch `isolation/2026-09-25`, top-level worktree `~/aisc-isolation`. Nothing pushed. No
edit in `~/aisc-install`, no contact with the running stack or the live databases. Every test ran on P2's own
throwaway clusters (ports checked by a runner script before each run; credentials only in the private folder
`<scratchpad>/P2/`). Both containers were removed at the end.

## What was built

`platform/platform_service/isolate/` (package; `python -m platform_service.isolate` and `import` both work):

| file | contents |
|---|---|
| `__init__.py`, `__main__.py` | `main(argv) -> int` |
| `cli.py` | argparse (intermixed, so `verify-dump --all f1 f2` works), `Run` (snapshot, classification, placement, plan, copy, verify, coverage), `provision` |
| `catalog.py` | `Table`/`Column`/`Fk`, `read_tables` from `pg_class`/`pg_attribute`/`pg_constraint`/`pg_get_serial_sequence`, `classify`, the constant sets (the only hand-written knowledge) |
| `ownership.py` | `load_keys` (keys and FK columns as text, one snapshot), `place` (roots, owned fixpoint, needed per project with identifying children and rule L, conflicts, unowned) |
| `rowtext.py` | the settings, the exact checksum formula of I12.10, per-key md5, key filters |
| `copy.py` | per-target compare / plan / write / verify, COPY TO piped into COPY FROM, FK anti-join, sequences |
| `preconditions.py` | old heads, new heads, templates, column coverage, active sessions (head lists copied, not imported) |
| `verify.py` | `verify-dump` (restore database made and dropped, `core.project` and the trigger function prepared, the file holding `core.system` restored first) |
| `report.py` | report JSON (mode 600 by `os.open` + `fchmod`), human summary, `redact`, `describe` (errors by class, sqlstate, constraint, table; never the message or detail) |

`platform/Dockerfile`: `postgresql-client`, and the base pinned to `python:3.12-slim-bookworm` (see D-P2-6).

Safety properties, and where they are enforced:
- The source connection is `REPEATABLE READ READ ONLY` for the whole run (the server refuses any write through
  it); it only runs SELECT and COPY TO; it ends in ROLLBACK.
- Target connections for plan, dry run, verify and report are `READ ONLY` transactions ending in ROLLBACK.
- A project is copied in one transaction (`session_replication_role = replica`), committed only after the FK
  anti-join over every FK of the target database, the per-table count and checksum over the copied keys, and the
  sequences. Any exception or refusal rolls it back; the run stops there (G8).
- Every refusal the tool can find without writing (unclassified table, conflicts, unknown project, heads,
  templates, coverage, sessions, `target not empty and not equal` for every selected target and for the library)
  is found in a read-only pass before the first write.
- The only write to `platform` is the library copy (`form_library.*`, `report_library.preset`).
- stdout and stderr hold pids, table names, counts, statuses, reasons; the report adds keys and md5s.

## Tests

Command (from `platform/`, P2's throwaway, new-layout recipe):
`PLATFORM_TEST_DATABASE_URL=... PLATFORM_TEST_SUPERUSER_URL=... uv run --extra dev pytest -q -p no:cacheprovider tests/test_isolate.py`

| suite | before P2 | after P2 |
|---|---|---|
| `tests/test_isolate.py` | 55 failed, 3 passed (re-measured: the package hidden by a `sitecustomize` on PYTHONPATH; all 55 `ModuleNotFoundError`) | 54 passed, 4 failed (578 s); the 4 are exactly T8 (3) and T9 below |
| platform, `--ignore=tests/test_isolate.py` | 342 passed, 2 skipped | 342 passed, 2 skipped (unchanged) |
| whole platform suite | 345 passed, 55 failed, 2 skipped | 396 passed, 4 failed, 2 skipped |

The failure texts were checked: T9 fails on its own setup INSERT (`UniqueViolation` on
`aisc_backend_evaluationi_evaluation_plugin_id_nam_5415cb96_uniq`); T8's three show `xact_commit` moved by exactly 1
per target for plan and dry run and by 2 for the second copy. Measured independently on a throwaway PG14 (autovacuum
off): a bare `psycopg.connect().close()` moves `xact_commit` by 1, and connect + read-only SELECTs + ROLLBACK also by 1,
so the three tests cannot pass for any tool that reads the targets.

### The 4 tests that stay red, and why no tool can turn them green (flagged for the orchestrator)

- **T8 (new) `test_I12_8_a_second_copy_is_already_done_and_writes_nothing` and
  `test_I12_12_plan_and_dry_run_compute_everything_and_write_nothing[argv0, argv1]`** assert that
  `pg_stat_database.xact_commit` of each target does not move. It moves by one for every session that connects to
  the database: the backend's startup transaction is counted as a commit (measured on PG14: a bare
  `psycopg.connect(...).close()` or `psql -c ''` moves it; a session that only runs `SELECT 1` and ROLLBACK moves
  it by exactly one). The tool must read the target to plan (the test itself asserts `already_present == 1` for
  the seeded form), so the assertion cannot hold. Measured with the tool: plan and dry run move it by exactly 1
  per target (one read-only connection), a second copy by 2 (check pass and write pass); both equal the count of
  connections, i.e. no transaction of the tool commits. Every other assertion of the three tests passes (checked
  by running the same steps without the xact comparison: digests unchanged, statuses, counts, sequences,
  `unowned`, no refusals). Suggested correction: compare `tup_inserted + tup_updated + tup_deleted` of
  `pg_stat_database` (or keep xact_commit but allow one per connection). While measuring this the tool was found
  to commit one extra implicit transaction per connection: psycopg sent `DEALLOCATE ALL` after the ROLLBACK
  because it had auto-prepared a repeated statement. It wrote nothing, but it was a statement outside the
  read-only transaction; fixed with `prepare_threshold=None` (commit e3a897a).
- **T9 (new) `test_I12_4_a_row_owned_by_two_projects_aborts_before_any_write`**: the test's own setup INSERT
  fails before the tool runs: `engine.evaluation_input` has the unique constraint
  `aisc_backend_evaluationi_evaluation_plugin_id_nam_5415cb96_uniq (evaluation_plugin_id, name)` and the new row
  repeats `(1, 'i')` of row 1. Suggested correction: name the new row `'i2'`. Checked by a script with that one
  change (test file untouched): the tool refuses with `owned by two projects` on `engine.evaluation_input`, naming
  both projects, and no target changes.

## Decisions (the plan was silent or wrong)

- **D-P2-1 Every refusal found read-only comes first.** The plan aborts a project with `target not empty and not
  equal` when its write transaction finds it. The tool checks every selected target and the library in the
  read-only pass first and refuses the whole run before any write (the write transaction checks again). Reason:
  "every refusal before any write" (plan, copy subcommand); a library seed that differs no longer leaves projects
  copied and the library refused.
- **D-P2-2 Conflicts are global.** Placement and conflicts are computed over every project in `core.project`,
  also for `--project` runs, and any conflict refuses the run. Reason: I12.4 says conflicts abort the whole run.
- **D-P2-3 Identifying-child rule, "any".** An identifying child (a FK whose columns are inside the PK) is needed
  when any such FK references a copied row. For B this also copies the default form's version and its questions
  (through `cq1 -> dq1`); they are equal to B's seed, so nothing changes in the result. "All FKs" would deadlock
  (`form_version_question` is how a version reaches its questions).
- **D-P2-4 Sequence rule made exact.** The target takes the source's `(last_value, is_called)` unless the target
  maximum is at or past the source's next value (`last_value + 1` when called, else `last_value`); then
  `(max, true)`. The plan's "max(...)" would give `(1, false)` for a source `(1, false)` with a target row 1 and
  hand out 1 again. setval runs last, right before COMMIT (it is not transactional).
- **D-P2-5 Statuses.** Plan and dry run report `planned` (as the plan says) even when nothing is missing; a run
  refused before writing reports `failed` for the projects named by a refusal and `planned` for the others; after
  a failed project, later projects and the library say `planned` with `note: not attempted` (G8). A project whose
  copied set is empty is `already done` on its first copy. FK orphans after the insert abort with
  `count mismatch` (detail `foreign-key orphans: <table>.<constraint> (n)`), there being no named reason for it.
  `verify` also reports extra target rows that are not equal seeds (`target not empty and not equal`).
  `report` never fails on differences: they go to `differences`, and statuses read `verified` or `differs`.
  Coverage (I12.13) is written by `verify --all` only (with `--project` the other projects' rows would count as
  missing); covered means present and equal in a target or the library, unowned, or bookkeeping.
- **D-P2-6 Docker base pinned to bookworm.** On today's `python:3.12-slim` (trixie) `postgresql-client` is 17,
  whose `pg_restore` emits `SET transaction_timeout`, which PG14 refuses (tried: restore rc 1). Bookworm's client
  15 restores. The plan had assumed bookworm. Checked end to end: the tool's own `verify-dump` inside the built
  image (temporary tag, removed) verified the live copy's two dump files.
- **D-P2-7 Connection failures** print libpq's text with the password redacted (host, port, user, database only);
  every other database error prints class, sqlstate, constraint and table, never the message or detail.
- **D-P2-9 One work-in-progress commit for placement, copy, verify and CLI.** The brief asked for one commit per
  working step. The first agent committed the four together (fd5d992) and then committed the fixes one by one.
  History was not rewritten (never rewrite without the user).
- **D-P2-8 `IntervalStyle = postgres`** is added to the four settings of I12.7 (the default; pinned so interval
  text cannot differ between sessions).

## Plan and dry run on the live copy (throwaway restore; no row value printed or kept)

Second agent's run, in a fresh private PG14 container. The first agent's two containers were removed first, and
its outputs were moved aside. `~/aisc-isolation-rehearsal/live-20260925-1149.sql` was restored with `psql`: rc 0,
one expected error (`role ... already exists`). The dump resets the superuser's password to the live hash, so the
throwaway's own password was set again over the container's local socket. Every run went through a runner that
refuses a URL that is not on the container's own port (never 5432).

What the restore holds: `core.project` has **1 project** (`01399e17-4b01-4be9-997a-7f5e3574ab22`, 2 members). There
are **4** `project_*` databases. `project_01399e17...` has `controls, llm, provision`. Three more,
`project_20372074...`, `project_a4c880f7...` and `project_d78463e0...`, have `controls, provision` and **no
`core.project` row** (leftovers of deleted projects). The tool only works from `core.project`, so it ignores them.

1. `plan --all` on the restore as it is: rc 1, 47 refusals, all expected before cutover. `source not at old head`
   (1: report_composer, 3 files missing, 0003..0005, D13 / C4). `target not at new head` (4: qualification,
   alembic, Django, composer). `missing template` (1: 0006..0010). `column coverage` (41: the 37 mapped tables, no
   module tables yet, plus the 4 `form_library` tables). No conflict, no unclassified table, 0 unowned rows.
2. Classification from the live catalog (45 tables): **6 root** (`core.system`, `qualification.qualification`,
   `control_objectives.project`, `engine.project`, `report_composer.layout`, `report_composer.template`), **22
   owned**, **9 needed** (`engine.metric`, `direct`, `derived`, `metric_category`, `metric_category_metrics`, the
   four form tables), **5 bookkeeping**, **3 stays shared**, **0 unclassified**. `report_composer.preset` is absent
   until 0005 has run.
3. Staged in the throwaway only, as the cutover would stage it. Composer 0003..0005 were applied by the composer's
   own runner (`report_composer.migrate`, as report_composer_rw). `init/project-databases.sql` and
   `init/report-roles.sql` ran (rc 0). The library tables were made from `library_statements()` of the test
   helper, **empty** (unlike the first agent's run, no default form was seeded). `isolate provision --all`
   installed the setup function into the old project database and applied template 0006..0010, and a second
   `provision` was a no-op. The module tables came from the test helper's stand-in derivation of `live_shape.sql`
   (not the real module migrations, which are stage 5's job).
4. Then `plan --all` and `copy --all --dry-run`: both rc 0, **0 refusals, 0 conflicts, 0 unowned rows**.
   Rows to copy into the one project (47 in 16 tables):

   | source table | target | rows |
   |---|---|---|
   | core.system | project.system | 1 |
   | qualification.qualification / qualification_answer / qualification_risk / knowledge_graph | same | 1 / 14 / 5 / 1 |
   | control_objectives.project / graph / mapping_run / risk | same | 1 / 1 / 1 / 5 |
   | engine.project / ai_system / plugin | same | 1 / 1 / 2 |
   | report_composer.template / layout / layout_block / generated_report | same | 1 / 1 / 7 / 4 |
   | the other 21 mapped tables | | 0 |

   Form rows into the project: 0, because the one qualification has no form version (`form_version_id` is
   NULL). Into the library: `form` 1, `form_version` 1, `form_question` 14, `form_version_question` 14;
   `report_composer.preset` has 0 rows. 18 target sequences were planned.
5. No write, proven. Row digests (I12.10 formula, every table) and `n_tup_ins/upd/del` of all 60 tables of
   `platform` and all 51 of the project database were taken before and after a further dry run plus plan:
   byte-identical.
6. No leak on real data. None of the 331 distinct non-key text values (length 6 or more) of the moving tables
   appears in any stdout, stderr or report of these runs, except values that are tool words or Django bookkeeping
   names that are also catalog relation names (checked by category, without printing them).
7. Beyond the brief, still on the throwaway: `copy --all` gave **copied** (77 rows: 47 project, 30 library). In
   `platform` only the four `form_library` tables changed (digests before and after). `verify --all` gave
   verified, coverage **43 tables, 149 source rows, 0 missing**. A second `copy --all` gave `already done` (project
   and library). `report --all` gave verified. `verify-dump --all` ran with the two G7 files, in the compose form
   (no password in `ISOLATE_SUPERUSER_URL`, `PGPASSWORD` in the environment): rc 0, 0 missing, and the database
   count before and after is the same (15). The dump files were deleted.

## What later packages must know

- **X1 / cutover:** run the tool as `docker compose --profile isolation run --rm isolate <sub> --all --report ...`
  (W1). Order: C4 composer 0003..0005, then every module migration into each project database, then
  `provision`, `plan` (rc 0 with no refusals is the gate), `copy`, `verify --all` (coverage must be 0 missing).
  `plan` and `copy` refuse while any platform_rw, `*_rw`, report_ro or dashboard_ro session is on `platform` or
  a target, so the stack must be stopped first. The report is mode 600 and holds keys (primary-key values) and
  md5s; keep it out of the repo.
- **Q2:** the library tables must exist in `platform` before `plan` passes (`column coverage` on
  `form_library.*` otherwise). A seed that the library migration or a project's forms migration puts in must be
  byte-equal (row text) to the live default form, or the copy refuses with `target not empty and not equal`
  (on the table of the differing row). The live qualification row has no form version.
- **R1:** `report_library.preset` must exist; live has no preset rows today.
- **X1:** the live cluster has three `project_*` databases with no `core.project` row (see above). The tool leaves
  them alone; whether to drop them is the user's decision, not the tool's.
- **V1 / stage 5:** the rehearsal must build the targets with the real module migrations (not the helper's
  stand-in used here) and then run `plan`, `copy`, `verify --all`, `verify-dump`. The three xact_commit tests
  (T8) and T9 need the orchestrator's decision.
- **Image:** the platform image is now `python:3.12-slim-bookworm` with `postgresql-client` 15.

## Commits (top-level, `isolation/2026-09-25`)

- `fd5d992` the package (catalog, ownership, rowtext, copy, preconditions, verify, report, cli): work in progress, 53 of 58
- `4b7046b` verify-dump takes its dump files after the options (intermixed arguments)
- `61db3f9` `platform/Dockerfile`: postgresql-client
- `cfcfe5e` connection failures reported with libpq's text (redacted), other errors by sqlstate and constraint
- `5504dce` `platform/Dockerfile`: base pinned to bookworm (D-P2-6)
- `e3a897a` `prepare_threshold=None` (no DEALLOCATE ALL outside the read-only transactions)
- `f55b7fa` G8: later projects and the library reported `not attempted` after a failed project
- the commit of this file and PROGRESS.md

