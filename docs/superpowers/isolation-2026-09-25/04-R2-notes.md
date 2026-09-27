# Stage 4, WP R2: report renderer on project databases

Date: 2026-09-25. Renderer worktree `~/aisc-isolation-report-generator` (branch `isolation/2026-09-25`) and
top-level `scripts/lib/report_bed_isolated.py`. Nothing pushed; no live database or running container touched;
every run used the beds' own throwaway `aisc-t-*` containers (random ports, 5432 refused by `check_dsn_env`,
no DB URL taken from the environment); none left afterwards.

## Commits

| repo | commit | content |
|---|---|---|
| top-level | `c85c5b0` | `scripts/lib/report_bed_isolated.py`: `build_isolated(..., no_database=frozenset(NO_DATABASE))`, default unchanged |
| renderer | `91346b1` | `report_renderer/data/{db,platform,qualification,control_objectives,engine,controls,__init__}.py`, `report_renderer/blocks/key_figures.py`, `tests/conftest.py`, `README.md` |
| top-level | (this commit) | these notes and the PROGRESS.md line |

## What changed

- `data/db.py`: `_ABSENT` (UndefinedTable, InvalidSchemaName), `project_dsn(sources, project_id)` (looks up
  `pg_database` on the platform DSN, None when absent), `project_rows`, `project_one` (`[]` / `None` when the
  database, schema or table is missing). Connections are still opened without `with conn:`.
- `data/platform.py`: only `core.project`, `pg_database`, `project.system`. `pinned_system` reads
  `project.system` of the project database and sets `project_id` itself. No row gives `NotInProject`. A missing
  database, or a missing `project.system`, gives the stand-in `_without_database(p, s)`. `newer_versions` and
  `older_versions` go through `project_rows`.
- `qualification.py`, `control_objectives.py`, `engine.py`: every read goes through `db.project_*`. The scope is
  `system_id` only (the database is the project). The engine no longer joins `engine.project` (A5), and
  `unversioned_count` counts `system_id IS NULL` in the database. The `newest_newer_*` queries join `project.system`.
  The public signatures are unchanged.
- `controls.py`: a missing controls schema or table reads as None or `[]` (the recommended step in the plan).

## Counts

| suite | before (clean export of 27bb0cb) | after (91346b1) |
|---|---|---|
| renderer | 24 failed, 648 passed | 672 passed, 0 failed |
| `scripts/tests/test_compose_isolation.py -k i9` | 2 passed | 2 passed (compose not changed) |
| report composer | 56 failed, 427 passed (02-tests.md) | 59 failed, 424 passed: the 56 isolation reds plus 3 e2e, see below |

Plan target of 672 passed: met.

## Deviations and decisions

- **D-R2-1 `blocks/key_figures.py` changed** (the plan said the blocks stay as they are). The version tile always
  has a value, so the block could never be `empty`, and `test_i9_3_a_missing_project_database_gives_empty_for_every_data_block`
  and `test_i9_3_a_missing_module_schema_or_table_gives_empty_never_error` would stay red. I took the smallest
  change: the version tile no longer counts as data. R-V6.10 still holds (`test_r_v6_10_*` are green: D_V1 has
  other values; the C test leaves the version out).
- **D-R2-2 Stand-in version** `_without_database`: `number` 0, empty name, the other fields None. It applies only
  when the project has no database or no `project.system`, and every data block is then empty.
- **S-D13 test change**: `tests/conftest.py` builds `report_bed_isolated.build_isolated("renderer", modules=True,
  no_database=frozenset())` and fails with an `AISC_INSTALL_DIR` message if that module is missing. Gamma now
  has a database with C_V1 and no module rows, so `test_r6_4_no_project_database_is_empty_not_error` runs on a
  database with no controls rows. The no-database case is pinned by `test_i9_3_*` on their own bed.
- The first baseline run overlapped my edits, so I stopped it and measured red-before on a `git archive` export
  of HEAD. The `pkill -f` pattern I used to stop it could also match other agents' pytest runs with the same flags.
  Afterwards the O1 and control-objectives runs were still alive; I removed only my own two orphan containers.

## What R1 must know

- Three composer e2e tests fail now: `test_e2e.py::test_e2e_compose_preview_and_generate`,
  `test_e2e.py::test_e2e_pinned_to_version_1` and `test_e2e_v2.py::test_e2e_v2_preset_coverage_draft_pdf_and_docx`.
  They start this renderer on `report_bed.build(...)`, the old shared layout, which the renderer no longer reads.
  R1's planned switch of `full_bed` to `report_bed_isolated.build_isolated("e2e" / "e2e2", modules=True)` fixes
  them. With the default `no_database`, gamma has no database, so its data blocks are `empty`.
- `no_database` is done (R1 item 1 is not needed). Legacy beds that need gamma as "another project alice edits"
  should pass `no_database=frozenset()`.
- The renderer now opens two connections per data call: platform `pg_database`, then the project database.
  The performance tests are green.
