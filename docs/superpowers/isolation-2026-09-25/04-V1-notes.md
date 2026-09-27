# WP V1 notes: verification, consistency, grants repair, guard and chain harnesses

Date: 2026-09-26. Branch `isolation/2026-09-25` in `~/aisc-isolation` and three submodule worktrees. Throwaway
Postgres only (every bed on a kernel-picked port, never 5432); credentials only in the V1 scratch folder; nothing
pushed; the `aisc` stack not touched; the controls live-exec integration files not run. At the end
`docker ps -a --filter name=aisc-t-` is empty.

## Commits

Top level (`isolation/2026-09-25`):

| commit | what |
|---|---|
| `e8ea680` | schema-docs labels (I11.3): `PROJECT_SCHEMAS` project, qualification, controls, control_objectives, engine, report_composer, llm, provision; `PLATFORM_SCHEMAS` core ("Projects and their members"), catalogue, form_library, report_library; new lede |
| `28c9a7c` | `scripts/lib/throwaway-pg.sh`: `tpg_project_db <pid> [template_dir]` (I19.2) |
| `a5c182c` | `scripts/db_consistency/checks.py` per project database, new `heads.py`, `verify-db-consistency.sh` header, `test_db_consistency.py` rebuilt (I16.6) |
| `2951a13` | `scripts/report-grants.sh` (the I2.6 list for both readers in every project database, the rest revoked, the template1 default privilege removed), `init/report-ro-grants.sql` (superset only), `test_report_grants.py` rewritten (I2.7) |
| `0f434d9` | `scripts/verify-project-databases.sh` (new, I16.1..I16.7), `verify.sh` runs it, `verify-db-access.sh` on a throwaway project database (I19.1) |
| `9708f12` | `scripts/lib/report_bed.py`: its project databases get the controls reader grants the controls migration gives; `test_report_grants.py` later-database case (see D-V1-3) |
| `361f138` | `scripts/guard-frozen.sh` (I7.12, I19.2), `test_guard_frozen.py` docstrings only |
| `29c4495` | `scripts/test-pipeline-chain.sh`, `scripts/pipeline_chain/test_dashboard_queries.py`, gitlinks of qualification, control-objectives, backend (I19.2, I19.3) |
| `f85900c` | `test_card_version_keys_orders.py` pinned to the f01288a trees (plan override; assertions unchanged) |
| `99d253b` | `python -m report_composer.migrate`: exit 1 while the platform cannot be reached, 2 on a permanent failure; new `apps/report-composer/tests/test_migrate_exit_codes.py` (orchestrator's item) |
| `c5204ab` | `docker-compose.development.yml` `report-composer-migrate` in the exit-2 loop; `test_compose_w1.py::test_i8_4_*` follows it (orchestrator's item) |

Submodules: qualification `0d6f8ca` (`test/chain/chain.test.ts`), control-objectives `f1e8c07` (`tests/test_chain.py`),
backend `1cc8bbc` (`aisc_backend/tests/test_chain.py`).

## Counts per file (`scripts/tests`, before = branch at `a585953`, after = `c5204ab`)

| file | before | after |
|---|---|---|
| test_card_version_keys_orders | 0 passed, 3 failed | 3 passed |
| test_compose | 10 passed | 10 passed |
| test_compose_isolation | 24 passed | 24 passed |
| test_compose_w1 | 6 passed | 6 passed (i8_4 changed, see below) |
| test_cutover_script | 43 failed | 43 failed (X1) |
| test_db_consistency | 48 passed, 3 failed | 65 passed (rewritten) |
| test_fresh_volume | 22 passed | 22 passed |
| test_guard_frozen | 6 passed, 13 failed | 16 passed, 3 failed (pre-isolation, D-V1-5) |
| test_inspector_network | 12 passed | 12 passed |
| test_isolation_fixture | 2 passed | 2 passed |
| test_isolation_harnesses | 2 passed, 22 failed | 23 passed, 1 failed (i18_7, X1) |
| test_isolation_unchanged | 4 passed | 4 passed |
| test_llm_keys | 17 passed, 1 failed | 17 passed, 1 failed (homepage, known) |
| test_pipeline_chain | 2 passed, 6 failed | 8 passed |
| test_project_grants | 58 passed, 5 failed | 61 passed, 2 failed (Q2 forms tables) |
| test_report_grants | 56 passed, 2 failed | 63 passed (rewritten) |
| test_report_stack | 22 passed, 2 failed | 22 passed, 2 failed (d6_guard known on purpose, P1; final_guard = D-V1-5) |
| test_schema_docs | 9 passed, 4 failed | 9 passed, 4 failed (homepage menu, known) |
| test_service_tokens | 23 passed | 23 passed |
| test_throwaway_rows | 12 passed | 12 passed |
| test_verify_project_databases | 27 failed | 27 passed |
| **total** | 335 passed, 131 failed | 429 passed, 56 failed |

Other suites, after: report composer 489 passed, 0 failed (483 plus the 6 new exit-code tests); report renderer
(`~/aisc-isolation-report-generator`) 672 passed, 0 failed. Direct runs: `scripts/test-pipeline-chain.sh` CHAIN PASS,
every `--break <link>` OK at its consuming step; `scripts/guard-frozen.sh --orders` S4.1..S4.4 PASS;
`scripts/verify-db-access.sh` on a throwaway bed 70 passed, 0 failed.

## Existing tests changed (S-D13, or as the plan or the orchestrator says)

- `test_db_consistency.py` (whole file, plan V1 item 1): rebuilt on `isolation_bed.build("consist-old", projects=(A, B, E))`
  with a fake keycloak and a minimal superset database; every case kept, premises moved as the plan lists (C4's "another
  project" is now "a pid of B planted in A does not resolve here"); new cases: retired schema and extra core table WARN
  (C2), answer number mismatch and card component (C4), every module tracker and the report library (C7), project.system
  and the library in C8.
- `test_report_grants.py` (plan item 2): on `report_bed_isolated.build_isolated("grants")`; report_ro cases in the
  project databases of A, B and E; `core.project` only in platform; a later database readable after the next
  report-grants run (not by default privilege); composer cases take R1's final grants (report_library owner, search_path
  `report_library, core` in platform and `report_composer` in a project database, REFERENCES on project.system; it may
  connect to a project database but reaches no module schema).
- `test_guard_frozen.py`: docstrings of S1.1 and S1.6 only.
- `test_card_version_keys_orders.py`: trees pinned to f01288a (init, platform migrations and runner, composer, and the
  qualification and control-objectives commits of its gitlinks); assertions unchanged.
- `test_compose_w1.py::test_i8_4_report_composer_migrate_one_shot`: pinned the bare command `python -m report_composer.migrate`;
  now pins it inside the exit-2 loop. Changed because the orchestrator decided the convention (not in the plan).
- Chain tests in the submodules (plan item 8): qualification (client on the project database, FK target project.system),
  control objectives (components read in the project database, FK found by target, app by `server.build_app()` through
  `isolation_support.deployed_app`, the owner's signed token), backend (the ORM inside `projectdb.open_alias`/`admitted`).

## Deviations and decisions

- **D-V1-1 Reference engine venv.** The guard's reference build (e34fca3, and dfe4120 in `--orders`) failed on
  `ModuleNotFoundError: allauth`: the worktree venv follows 0024, which dropped django-allauth. That was the
  baseline's 11 guard reds. The guard now makes a venv once from e34fca3's `uv.lock` in `GUARD_CACHE`
  (default `~/.cache/aisc-guard/backend-e34fca3`, outside the repo) and runs the reference engines there;
  `GUARD_BACKEND_PY`, when set, still wins (S0.1's forced failure).
- **D-V1-2 Reference init.** The reference uses `tpg_init_platform live/top` (ad6262f), not the candidate's init;
  `--orders` uses the f01288a trees throughout, including control objectives at its f01288a gitlink (its current alembic
  refuses `platform`), run with the worktree's CO venv.
- **D-V1-3 report_bed.** Removing the template1 default privilege (I2.6) turned 4 renderer tests red: `report_bed`'s
  project databases have the controls schema from a fixture with no grants. `_project_database` now applies the same
  grant as controls' migration `20260926000100_readers_read_the_listed_tables` (as controls_rw). Renderer back to 672.
- **D-V1-4 I16.5 functional part.** Qualification cards, assessments, engine evaluations and controls answers have no JSON
  create route, and the script's read-only rule forbids any write statement in its body. So I16.5 makes A and B, a card
  version of A and a layout of A through the APIs, checks their absence from B's database, and checks that A's ids are
  404 under B's pid on qualification, control-objectives, controls, engine (with `X-AISC-Project: B`) and report; it
  deletes both projects in a `finally`. It could not be run here (no stack); the endpoint paths are from the Caddyfile
  and the routers. X1 should run it at C12 and seed richer rows if it wants the full I16.5.
- **D-V1-5 Guard reds that are not the isolation's (for the orchestrator).** After V1, G1 differs from e34fca3 only by
  the 66 login objects migration 0024 drops (account_*, auth_*, django_session, socialaccount_*, ... and two indexes);
  I7.9's two differences normalise away and nothing else differs (checked object by object). G4 backend still reports
  `routers/plugin.py`, `pyproject.toml` (Sean's files), `admin.py`, `0024`, `config/jwt.py`, `config/urls.py` and the
  Dockerfile's collectstatic line, all from the pre-isolation commit 3aa01d0 and before. V1 did not add them to the
  allowed sets: that would bless a non-isolation change to Sean's files. Red: `test_s1_1`, `test_s1_4`, `test_s9_4`,
  `test_report_stack::test_final_guard_frozen_passes`. Decide whether the guard should accept 0024.
- **D-V1-6 verify-project-databases.sh wording.** No bare GRANT/REVOKE/TRUNCATE/drop in its body; rights beyond
  has_table_privilege's list are read with `aclexplode`. Skipped parts print `WARN I16.4/I16.5 not run (...)`, never PASS.
  The library roles are exempt from I16.1's platform schema check on the schema they hold by design (qualification_rw
  form_library, report_composer_rw report_library, catalogue_rw catalogue).
- **D-V1-7 report-grants.sh** also revokes every non-SELECT right of the readers on listed tables, and every right on
  unlisted tables of project, controls, qualification, control_objectives, engine, report_composer, llm and provision.
- **D-V1-8 C7** keeps checking every `project_` database (orphans too, as before), so a never-provisioned one lists each
  missing tracker; C3, C4, C5 and C6 read only databases with a core.project row.

## Flagged tests

- None wrong. Q2 owns `test_project_grants.py::test_i2_6_readers_see_exactly_the_listed_tables[qualification-*]` (the four
  form tables are not in the branch yet). X1 owns `test_cutover_script.py` (43) and `test_isolation_harnesses.py::test_i18_7`.
  D-V1-5 needs a decision.

## What X1 and Z1 must know

- **X1:** `scripts/verify-project-databases.sh` is the done check: `--privileges` at C9 (I16.1 and I16.2 only),
  plain at C12 with `VERIFY_ACCESS_TOKEN` (a member's token) and `VERIFY_BASE_URL`, `--final-layout` after stage 7.
  In the rehearsal set `VERIFY_SKIP_CONTAINERS=1 VERIFY_SKIP_FUNCTIONAL=1`. Before C9 I16.2 fails by design while the
  module schemas are reachable. `scripts/report-grants.sh` no longer touches platform and removes the template1 default
  privilege for report_ro; run it after C8. `report-composer-migrate` now retries non-2 exits; a failed project database
  is exit 2 (stops the start). The two I18.7 scripts X1 adds must not trace (`set -x`) or echo secret variables.
- **Z1:** the 56 remaining reds above: 43 + 1 X1, 2 Q2, 4 + 1 + 1 homepage/on-purpose knowns, 4 guard (D-V1-5).
  The guard's first run builds the reference venv (network, about a minute); later runs reuse it.
