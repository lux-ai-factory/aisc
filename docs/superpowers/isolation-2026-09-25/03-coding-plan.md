# Stage 3: coding plan, one database per project

Date: 2026-09-25. Branch `isolation/2026-09-25` in `~/aisc-isolation`, its submodule worktrees and
`~/aisc-isolation-report-generator`. Inputs: `RULES.md`, `01-specs.md` (D3/D4 as confirmed), `02-tests.md` and
the committed stage-2 tests (they are the contract). The user was not available; every decision below is recorded
with its reason. No product code was written in this stage. The platform sections (P1, P2) and the framework were
written by the stage-3 agent directly; the module sections were researched by one read-only agent per module
(qualification, control objectives and controls, engine, composer and renderer, dashboard and verification, cutover)
and edited here to fit the global decisions of section 2. Where a module section and section 2 disagree, section 2
wins, and each WP starts with a "Plan overrides" box that says so.

How a fresh coding agent uses this file: read `RULES.md`, then sections 1 to 5 of this file, then only the section of
its own WP. Everything it needs is in those three places; it re-derives nothing.

## 1. Conventions for every WP

- **TDD against the committed tests.** Every red listed for the WP must turn green; nothing green may turn red except
  where the WP names the existing test it changes (S-D13 and section 4 of this file). Never weaken a test. A test
  correction is allowed only if it is listed in section 4 (T1..T7) and is committed on its own with the message
  prefix `Isolation test correction Tn:`.
- **Commits** by explicit path only (`git commit -m ... -- <paths>` or `git add <paths>` then commit). Never
  `git add -A`, never `.`; never commit `__pycache__`, `node_modules`, `.venv` or generated clients. Never push.
  Submodule commits are made inside the submodule worktree; the top-level gitlink is then committed by path
  (`apps/<module>`). Several WPs may share the top-level worktree at once: if `git` reports `index.lock`, wait and
  retry, never delete the lock of another process.
- **Never** edit `~/aisc-install` or `~/aisc-report-generator`; never run `docker compose` against project `aisc`;
  never write to the live databases; never run the controls integration files that `docker exec postgres`
  (`project-scope`, `action-access`, `install`, `project-database`, `submission-lifecycle`, `chain`).
- **Throwaway databases only**, and always set `PLATFORM_TEST_DATABASE_URL` and the module's test DSN.
  `docker ps -a --filter name=aisc-t- -q` is empty at the end of every WP.
- **Prose** without em dashes; logs and reports print pids, names and counts only (I18.7).
- **WP notes**: each WP appends a section to `docs/superpowers/isolation-2026-09-25/04-code-notes.md` (created by the
  first WP) with: tests turned green, pre-existing tests changed and why, compose requests for W1, anything left
  undone, and the suite counts it measured. It commits that file by path with its code.

### 1.1 Recipes

**New-layout recipe** (every WP from P1 on; 02-tests.md section 2 with the post-P1 init files):

```
cd /home/listuser/aisc-isolation
NAME=aisc-t-iso-X-$(openssl rand -hex 4); PW=$(openssl rand -hex 12)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
[ "$PORT" != 5432 ] || exit 1
docker run --rm -d --name $NAME -p 127.0.0.1:$PORT:5432 -e POSTGRES_USER=aisc-postgres-user \
  -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=platform postgres:14-alpine
until docker exec $NAME pg_isready -U aisc-postgres-user -d platform; do sleep 1; done; sleep 2
for f in platform-db project-databases inspector-role report-roles; do
  docker exec -i $NAME psql -U aisc-postgres-user -d platform -v ON_ERROR_STOP=1 -q < init/$f.sql; done
# the suite command of 02-tests.md section 2 (or of the WP), then:
docker rm -f $NAME
```

**Old-layout recipe** (only to compare a not-yet-converted module's baseline after P1 has changed the init files):
replace the first init file with `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql` (made by P1) and
apply `git show f01288a:init/report-roles.sql` instead of `init/report-roles.sql`. A module's final green run is
always on the new-layout recipe.

Per-suite commands are those of 02-tests.md section 2, with two changes decided here: the pre-existing backend
Postgres suite runs with `DJANGO_SETTINGS_MODULE=config.settings_single_database` (E1), and the controls suite
list is unchanged.

## 2. Global decisions of this stage (they override any WP text)

- **G1 Compose ownership.** WP W1 is the only writer of the top-level compose and env files
  (`docker-compose*.yml`, `env.development`, `env.staging`, `env.plugin_downloader`). Module WPs do not edit them;
  a module section that describes a compose change is input for W1 (W1's section already contains every one of
  them). Reason: every compose test resolves the whole file, several agents share one worktree, and
  "commit by explicit path" cannot separate hunks. A submodule's own env file stays with its module.
- **G2 Harness ownership.** WP V1 is the only writer of `scripts/guard-frozen.sh`, `scripts/lib/throwaway-pg.sh`
  (`tpg_project_db`), `scripts/test-pipeline-chain.sh`, `scripts/pipeline_chain/*`,
  `scripts/tests/test_card_version_keys_orders.py` and `scripts/tests/test_guard_frozen.py`. E1 and E2 put the
  exact file lists for G4/G5 in their WP notes; V1 applies them. Reason: the guard needs `tpg_project_db`, E1's
  `migrate_projects` and E2's final file list at once; one editor keeps one set of hunks.
- **G3 The old layout is a fixture.** `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql` (P1) is a
  verbatim copy of `git show f01288a:init/platform-db.sql`. Every harness that must build the pre-isolation shared
  layout (platform `core_scratch.scratch_database(old_layout=True)`, `scripts/lib/report_bed.py`, the historical
  `--orders` modes pinned to f01288a trees) uses it; nothing else does. `f01288a` (stage 1 commit) is the
  pre-isolation reference everywhere in this plan.
- **G4 Retirement marker.** Cutover C9 sets a comment beginning with `retired:` on `core.system` and on the four
  retired schemas (`retired: isolation cutover C9 <ts>; dropped in stage 7`). Every init file that runs on every
  start skips `core.system` when it is absent or its comment begins with `retired:`, and none of them touches the
  four module schemas in `platform` any more (P1-D3). Reason: postgres-setup runs on every start as the superuser and
  would otherwise silently undo the retirement.
- **G5 Per-database search_path through a definer function** (P1-D1): platform_rw cannot run
  `ALTER ROLE <other> IN DATABASE ... SET` on PG14 (verified on a throwaway; needs SUPERUSER or CREATEROLE, and
  CREATEROLE on PG14 is close to superuser). `aisc_setup.apply_role_setting(stmt)` in `template1` (and installed by
  `isolate provision` in older databases) executes only the four allowed statements.
- **G6 The qualification baseline is named `20260925000000_project_database`** (T1), not `20260926000000_...`:
  Prisma applies directories in name order, the two forms migrations (`20260925090000_*`, `20260925120000_*`) must
  keep their names and bytes (I3.5), and the first of them alters `qualification.qualification`, so the baseline
  must sort before them. This supersedes the name in 01-specs.md I3.5. The control-objectives alembic revision keeps
  `20260926000000_project_database` (unrelated, alembic orders by `down_revision`).
- **G7 Stage-7 dump is two files** (open issue 2): `pg_dump -Fc -n qualification -n control_objectives -n engine -n
  report_composer platform > <schemas>.dump` and `pg_dump -Fc -t core.system platform > <core-system>.dump`;
  `isolate verify-dump --all <schemas>.dump <core-system>.dump`. This supersedes the single command of I15.2.
- **G8 The copy stops at the first failed project** (D15): later projects are not attempted in that run; re-running
  resumes.
- **G9 Security of builds.** Every built image gets `image: <name>:${AISC_IMAGE_TAG:-latest}` and
  `pull_policy: never` (W1), and isolation builds use `AISC_IMAGE_TAG=isolation` and compose project
  `aisc-isolation-build`, so no isolation build overwrites a `:latest` image the running stack uses.

## 3. Work packages, in dependency order

| # | WP | repos | depends on | wave |
|---|---|---|---|---|
| 1 | P1 platform: templates 0006..0010, card versions in `project.system`, init files, old-layout fixture | top-level (`platform/`, `init/`, `scripts/lib/report_bed.py`, `scripts/tests/fixtures/`) | none | 0 |
| 2 | W1 compose and env wiring (every module's DSN templates, migrate one-shots, `isolate` one-shot, image tags) | top-level (compose and env files) | P1 | 1 |
| 3 | P2 move tool `python -m platform_service.isolate` | top-level (`platform/platform_service/isolate/`, `platform/Dockerfile`) | P1 | 1 |
| 4 | Q1 qualification routing, baseline migration, agents paths | `apps/qualification` (+ gitlink) | P1 | 1 |
| 5 | O1 control objectives per project database | `apps/control-objectives` (+ gitlink) | P1 | 1 |
| 6 | C1 controls: FK to `project.system`, reader-grant repair, 404 after drop | `apps/controls` (+ gitlink) | P1 | 1 |
| 7 | E1 engine part 1: aliases, router, `migrate_projects`, 0025, stamp | `apps/backend` (+ gitlink) | P1 | 1 |
| 8 | R2 report renderer on project databases | `~/aisc-isolation-report-generator`, top-level `scripts/lib/report_bed_isolated.py` | P1 | 1 |
| 9 | D1 dashboard: engine dataset per project, membership DSN | `apps/results-dashboard` (+ gitlink) | P1 | 1 |
| 10 | E2 engine part 2: the door, run ticket, worker, SPA header | `apps/backend`, `apps/eval`, `apps/webapp` (+ gitlinks) | E1 | 2 |
| 11 | R1 report composer: project and library migrations, two DSNs | top-level (`apps/report-composer/`, `platform/tests/isolate_support.py` line 54, two scripts tests) | R2, P2 | 2 |
| 12 | V1 verification, consistency, grants repair, guard and chain harnesses | top-level (`scripts/`, `inspector/schema-docs/`, `init/report-ro-grants.sql`), chain tests in submodules | waves 0..2 | 3 |
| 13 | Q2 forms: merge, `platform.form_library`, copy on use (gate I4.6) | `apps/qualification` (+ gitlink) | Q1, gate I4.6 | 3 (when the gate opens) |
| 14 | X1 cutover and rehearsal scripts, stage-7 drop | top-level (`scripts/isolation/`) | P2, V1, W1 | 4 |
| 15 | Z1 every suite together, final counts | all (read-only except `04-code-notes.md`) | all, Q2 or its recorded skip | 5 |

Waves: WPs of one wave may run at the same time (their files are disjoint by the ownership rules G1, G2 and the
table's repos column). R1 waits for R2 (the composer e2e tests start the real renderer, and both edit
`report_bed_isolated.py`) and for P2 (both touch `platform/tests/isolate_support.py`). The cutover (stage 6) needs
every WP including Q2 (C0 checks the forms gate).

## 4. Tests flagged as wrong, and the correction the coder makes

Every other stage-2 test is taken as correct. These are wrong in a way no product code can satisfy; the named WP
makes exactly this correction, committed alone, and names it in its notes.

| id | test | why it is wrong | correction (WP) |
|---|---|---|---|
| T1 | `apps/qualification/test/unit/isolationBaseline.test.ts:13`, `apps/qualification/test/db/projectDatabase.db.test.ts:30`, `platform/tests/isolate_support.py:128` | pin the baseline name `20260926000000_project_database`, which sorts after the byte-for-byte forms migrations; on a fresh project database `20260925090000_forms_are_data` would run first and fail (`isolationBaseline.test.ts:42` and `projectDatabase.db.test.ts:205` expect the baseline first) | the constant becomes `20260925000000_project_database` (G6). Q1 changes the two qualification files, P1 the platform helper |
| T2 | `apps/qualification/test/unit/isolationActionsAndPages.test.ts:119-135` | its `beforeEach` never closes the cached project clients, so with the cache I3.1/I17.1 require, the "opened B/A" cases at lines 220 (5), 229 and 263 see databases opened by earlier tests | add `await (await load(join(SRC, "lib", "projectDb.ts"))).mod?.closeProjectDatabases?.()` to that `beforeEach` (Q1) |
| T3 | `apps/qualification/services/agents/tests/test_isolation_paths.py:54` | the fake `config_for` returns a dict; `fill_one` reads `config.provider`, so line 111 can never be `done` | return `types.SimpleNamespace(provider="fake", model="m")` (Q1) |
| T4 | `apps/qualification/test/db/formLibrary.db.test.ts:129, 157, 224-226, 254` | written against an older forms snapshot: `is_default` is dropped by `20260925120000`, `origin 'user'` is forbidden by `form_origin_check`, `blocks` is `text[]` not jsonb, and `SET session_replication_role` runs on a pooled client apart from its UPDATE | `id = 'annex-iv-default'` instead of `is_default`; `origin 'builder'`; `ARRAY['risks']::text[]`; the three statements in one interactive `$transaction` with `SET LOCAL` (Q2, re-checked against the merged forms files) |
| T5 | `apps/backend/aisc_backend/tests/test_isolation_engine_db.py:67-128` (`_seed`) with `:571-579` (`test_i17_1`) | `_seed` uses the ORM in the main thread and never closes `connections[alias]`; Django connections are per thread, so the session it leaves is counted by `test_i17_1` whatever the implementation does | `connections[alias].close()` in `_seed`'s `finally` (E1) |
| T6 | `apps/backend/aisc_backend/tests/test_isolation_engine_db.py:472` (`CONTROLS` row `/api/v1/evaluations/{evaluation_pid}/artifacts`) | without its required query parameter it is 422; with it, the view reads every artifact from S3, which the throwaway has not, so it can never be 200 | replace the row with `/api/v1/evaluations/{evaluation_pid}/plugins/status` (E2) |
| T7 | Sean's frozen webapp tests `src/pages/PluginStartEvaluation.test.tsx`, `src/components/plugin/PluginEvaluationForm.test.tsx` versus the new `src/api/projectHeader.i7_4.test.ts:108-113` | the new test (correct for I7.4) forbids a project call without a current project; the two frozen tests render without one and expect `/projects/...` to be fetched | add one line to each frozen test's setup: `sessionStorage.setItem("aisc_platform_project", "<a pid>"); // I7.4 (isolation)` (E2); V1's G4 drops lines tagged `// I7.4 (isolation)` before comparing Sean's files |

Not wrong, but weak or constraining (no correction; the WP works as stated):

- W-1 `platform/tests/test_project_system.py::test_i2_8_project_databases_sql_still_runs_once_core_system_is_gone` and
  `scripts/tests/test_fresh_volume.py::test_i2_8_project_databases_sql_runs_after_*` become vacuous once P1's init
  files no longer create `core.system` (they drop what is not there). P1 adds `platform/tests/test_init_after_retire.py`
  (old layout, retire, drop, re-run), which proves the guard for real; the rehearsal proves it on the live copy.
- W-2 `scripts/tests/test_cutover_script.py:226-227` pins I15.2's single dump command on one line; X1 writes the two
  correct commands of G7 on one physical line joined by `&&`, which is correct and passes.
- W-3 `scripts/tests/test_cutover_script.py:57, 105, 169, 218-225` are fragile regexes; X1 follows the text rules in
  its section 3. `scripts/tests/test_verify_project_databases.py:47-53` forbids the bare words GRANT, REVOKE,
  TRUNCATE and `DROP ` in non-comment lines; V1 words around them (`aclexplode`).
- W-4 `scripts/tests/test_compose_isolation.py:128-144` (I9.1) passes vacuously (it sets `REPORT_GENERATOR_DIR`
  itself), and `:164-184` does not look at the engine's `DB_*`; V1's I16.4 `docker inspect` covers both at C12.
- W-5 `apps/report-composer/tests/test_isolation_project_databases.py:326-327` (`test_i17_1`) reads
  `pg_stat_activity` right after the request; a just-closed backend may linger for milliseconds. If it flakes, report
  it; do not add retries.
- W-6 `apps/control-objectives/tests/test_api_auth.py:404` (`test_a_page_refuses_an_assessment_of_another_project`)
  cannot hold "paths only" (S-D13) in the one-database fixture once `project_id` is gone; O1 rewrites it in place on
  the two-database fixtures of `isolation_support` with the same assertions (not deleted).

## 5. Open issues of 02-tests.md section 6, resolved, and issues found in stage 3

| # | issue | resolution | WP |
|---|---|---|---|
| 1 | fresh volume vs platform migrations 0002..0004 | the guard is inside each SQL file (no-op without `core.system`, unchanged with it), because the test beds replay the files with psql and bypass `migrate.py`; plus migration `0005_the_composer_reads_members.sql` for I1.4 on a fresh volume | P1 (P1-D2) |
| 2 | I15.2 dump command wrong (`-t` overrides `-n`) | two dump files, `verify-dump` takes both (G7); already the form of `test_isolate.py:765-789` | P2, X1 |
| 3 | `engine.metric_category_metrics` never placed | rule L: a row of a global table whose columns are only its single-column primary key and the columns of two or more FKs (a many-to-many link) is needed by P when any row it references is copied to P; its other referents then become needed. Categories follow the metrics a project uses; an unused category stays unowned | P2 |
| 4 | owned-by-two and cross-project overlap | both reasons are reported when both hold; the tests accept either | P2 |
| 5 | form library head names; `report` meaning | library migration `prisma/library/migrations/20260926000200_form_library` tracked in `form_library._prisma_migrations`; composer library `migrations/library/0001_presets.sql` in `report_library.schema_migration`; `report` is a read-only current-state report, as the tests pin | Q2, R1, P2 |
| 6 | `live_shape.sql` lacks `CREATE SCHEMA core` and the core function | unchanged; the loaders create them first | none |
| 7 | leak: `GET /plugins/{evaluation_plugin_pid}/evaluations/{evaluation_uuid}/result` has no membership check | confirmed in `apps/backend/aisc_backend/routers/plugin.py` (`get_plugin_evaluation_results`); closed by E2's door (header required, membership before the database opens, the ORM sees only that project's database); pinned by the `ROUTES` row at `test_isolation_engine_db.py:439`. The live stack stays exposed until cutover (live has 0 evaluation rows today). No live hotfix in this pipeline (RULES); the orchestrator should tell the user, who may choose a separate hotfix. Do not add the route's tokens to `test_every_project_route_is_guarded.looks_project_scoped` (the frozen view has no membership call) | E2 |
| 8 | engine `ROUTES` bodies | every body validates; `GET /api/v1/evaluations/{evaluation_pid}/artifacts` (row at `:409`) lacks a required query and would be 422: E2's door checks that the path's evaluation exists in the admitted database before the view, which answers 404. The `CONTROLS` row is T6 | E2 |
| 9 | control-objectives concurrency and LRU proven by outcome | accepted as written | O1 |
| 10 | dashboard DSN template; I16.4/I16.5 functional parts | the rehearsal has no running stack (it would collide with live names and ports), so `verify-project-databases.sh` runs there with `VERIFY_SKIP_CONTAINERS=1 VERIFY_SKIP_FUNCTIONAL=1`; the functional I16.5 and the `docker inspect` I16.4 run live at C12, before caddy opens | V1, X1 |
| 11 | unsafe runners | unchanged exclusions (controls live-exec files, dashboard `test_sso_login.py`, eval `test_basic_integration.py`) | all |
| 12 | Q2 gate closed | Q2 is fully planned and runs when the gate opens; Z1 records its skip if it has not | Q2, Z1 |
| N1 | platform_rw cannot `ALTER ROLE ... IN DATABASE` | G5, P1-D1 | P1 |
| N2 | every-start init files would undo retirement and re-create `report_composer` in `platform` | G4, P1-D3; C9's check re-runs postgres-setup and report-grants on purpose | P1, X1 |
| N3 | `scripts/lib/report_bed.py` builds the old layout from the current init files | G3: it uses the old-layout fixture and re-creates the old composer schema and grants itself | P1 |
| N4 | three suites read `apps/report-composer/migrations/0001..0005` directly | R1 moves them to `apps/report-composer/pre_isolation_migrations/` and repoints the three readers | R1 |
| N5 | controls' `20260923210100_dashboard_reads_controls` grants dashboard_ro every table and a default privilege | a new controls migration revokes the default privilege and `_prisma_migrations`, and grants report_ro the five tables | C1 |
| N6 | qualification baseline order | G6, T1 | Q1 |
| N7 | isolation builds would overwrite `:latest` images | G9 | W1 |
| N8 | C2's evaluation check names `running`/`pending` | the real statuses are `Pending` and `Processing` | X1 |
| N9 | the qualification worktree's `node_modules` is a symlink into `~/aisc-install`; `prisma generate` would write there | Q1 replaces the link with a real directory of symlinks plus private copies of `@prisma` and `.prisma` and checks the install's mtime is unchanged | Q1 |

Questions for the user before stage 6 (not needed for stages 4 and 5; recorded in PROGRESS.md): which env file the
live cutover uses (`ISOLATION_ENV_FILE`, presumably `~/aisc-install/env.runtime`; never run `scripts/secrets.sh` in
the worktree, it would mint a new `PLATFORM_SECRETS_KEY`), and from which directory the live stack runs after C11
(the compose bind mounts follow `ISOLATION_COMPOSE_DIR`; until the branch is merged into `~/aisc-install` that is
the worktree).

---

## WP P1: platform, template 0006..0010, card versions per project database, init files

**Repos**: top-level only (`platform/`, `init/`). **Depends on**: nothing. **Blocks**: every other WP.

### Requirements and the tests it turns green

I1.2, I1.4, I1.5, I1.6, I1.8 (guard), I2.1, I2.2, I2.3, I2.4, I2.5, I2.8, I2.9, I11.2 (guard), I17.1 (platform),
I18.5.

- `platform/tests/test_project_system.py`: all of it (32 red today, 9 green guards stay green).
- `scripts/tests/test_fresh_volume.py`: the static `test_i2_8_*` tests, `test_i2_8_project_databases_sql_runs_after_*`,
  `test_i16_4_init_files_and_migrations_apply_on_a_fresh_volume`, `test_i1_3_*`, `test_i1_4_*` (all parametrised
  cases). `test_i16_4_post_projects_on_a_fresh_volume_yields_a_complete_project_database` stays red until every
  module WP has landed (it needs every module's migrate command); it is the Z1 check.
- `scripts/tests/test_project_grants.py`: the template parts only (`test_i2_1_*` on schemas and CONNECT); the
  table-level reader rows turn green module by module (each module WP issues its own grants, I2.6).

### Decisions taken in this plan for P1

- **P1-D1 (found in stage 3, verified on a throwaway PG14)**: `ALTER ROLE <other role> IN DATABASE <db> SET ...`
  needs SUPERUSER or CREATEROLE; platform_rw has neither (it applies the template on `POST /projects`), and
  CREATEROLE on PG14 is close to superuser (it can grant `pg_execute_server_program`). So the per-database
  search_path of I2.1 is set through one SECURITY DEFINER function owned by the superuser,
  `aisc_setup.apply_role_setting(stmt text)`, that EXECUTEs only a statement matching exactly
  `^ALTER ROLE (qualification_rw|control_objectives_rw|engine_rw|report_composer_rw) IN DATABASE (project_[0-9a-f]{32}) SET search_path = (qualification|control_objectives|engine|report_composer)$`
  where the role and schema pair up (qualification_rw with qualification, and so on) and the database equals
  `current_database()`; anything else raises. The template files call it with the literal statement, so the text
  the static test looks for is the statement that runs:
  `PERFORM aisc_setup.apply_role_setting(format('ALTER ROLE qualification_rw IN DATABASE %I SET search_path = qualification', current_database()));`
  (inside the file's DO block). Where it lives: schema `aisc_setup` (owner superuser, `REVOKE ALL FROM PUBLIC`,
  `GRANT USAGE` to platform_rw) with the function (`REVOKE EXECUTE FROM PUBLIC`, `GRANT EXECUTE` to platform_rw,
  `SET search_path = pg_catalog`). `init/project-databases.sql` creates both in `template1` (so every database
  made afterwards has them); `isolate provision` (P2) installs them into an existing project database that lacks
  them by reading `pg_get_functiondef` from `template1` (the MCAS database predates it). Template 0007..0010 raise
  `aisc_setup.apply_role_setting is missing: run init/project-databases.sql (postgres-setup) or isolate provision`
  when `to_regproc('aisc_setup.apply_role_setting')` is NULL.
- **P1-D2, open issue 1 (fresh volume vs platform migrations 0002..0004)**: the guard goes inside the three SQL
  files, not into the runner, because the test bed (`scripts/pipeline_chain/throwaway.platform_migration`)
  replays the files with psql and bypasses `migrate.py`. Each file becomes a no-op when
  `to_regclass('core.system') IS NULL`, and is unchanged in effect when core.system exists (live has applied all
  three; the runner never re-runs a recorded file and keeps no checksum). Concretely:
  - `0002_one_ai_system_per_project.sql`: only the carry-over `INSERT ... FROM core.system` is wrapped in
    `DO $$ BEGIN IF to_regclass('core.system') IS NOT NULL THEN ... END IF; END $$;` (plpgsql plans lazily, the
    0003 comment already relies on it). Everything else in 0002 only makes `core.ai_system*`, which 0003 drops.
  - `0003_card_versions_in_core_system.sql`: steps 1..5, 7 and 8 go into one
    `DO $m$ BEGIN IF to_regclass('core.system') IS NULL THEN RAISE NOTICE '0003 skipped: no core.system'; RETURN; END IF; ... END $m$;`
    with the ownership guard's exact message kept (`test_s2_8` pins it); step 6 (drop the freeze model) stays
    unconditional. The trigger function is made with `CREATE OR REPLACE FUNCTION ... AS $f$ ... $f$` inside the
    block. The step-7 trigger is created only in the guarded branch.
  - `0004_card_version_of_its_project.sql`: the DO block returns early when core.system is absent.
  - New `platform/migrations/0005_the_composer_reads_members.sql` (see below).
- **P1-D3, retirement marker (found in stage 3)**: `init/project-databases.sql` and `init/report-roles.sql` run on
  every start of postgres-setup as the superuser. After C9 (retire) their `ALTER TABLE core.system OWNER TO
  platform_rw`, the composite-key block, `ALTER SCHEMA report_composer OWNER TO report_composer_rw` and the
  `core.system` grants would silently undo the retirement at the next start. Rule: C9 sets
  `COMMENT ON TABLE core.system IS 'retired: isolation 2026-09-25'`; every every-start file runs its core.system
  lines only when `to_regclass('core.system') IS NOT NULL AND coalesce(obj_description('core.system'::regclass, 'pg_class'), '') NOT LIKE 'retired:%'`,
  and none of them touches the shared module schemas any more. The literal
  `ALTER TABLE core.system OWNER TO platform_rw` stays in the file (inside `EXECUTE '...'`), which
  `test_card_versions_migration.py::test_d1_project_databases_sql_gives_core_system_to_platform_rw` looks for.

### Files

Create:
- `platform/project-template/0006_project_system.sql`
  ```sql
  CREATE SCHEMA IF NOT EXISTS project;
  COMMENT ON SCHEMA project IS 'This project''s AI card versions: one row per saved card, numbered 1, 2, ...';
  CREATE TABLE IF NOT EXISTS project.system (
      pid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      number integer NOT NULL CHECK (number > 0) UNIQUE,
      name text NOT NULL, version text, provider text, description text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      created_by text);
  CREATE OR REPLACE FUNCTION project.system_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $f$
  BEGIN
    IF NEW.number <> OLD.number OR OLD.number < (SELECT max(number) FROM project.system) THEN
      RAISE EXCEPTION 'system version % is not the latest and cannot change', OLD.number;
    END IF;
    RETURN NEW;
  END $f$;
  -- trigger made only when absent (DO block on pg_trigger), named system_only_latest_changes
  REVOKE ALL ON project.system FROM PUBLIC;
  DO $g$ ... for each role in (qualification_rw, control_objectives_rw, controls_rw, engine_rw, report_composer_rw)
       that exists: GRANT USAGE ON SCHEMA project, GRANT SELECT, REFERENCES ON project.system;
     for report_ro, dashboard_ro that exist: GRANT USAGE ON SCHEMA project, GRANT SELECT ON project.system $g$;
  ```
  Column order is exactly I1.5 (the move tool's checksums compare in target column order). The function body
  must match `PROJECT_SYSTEM_DDL` in `platform/tests/isolate_support.py` in meaning (that helper uses
  IF NOT EXISTS / OR REPLACE and fills only what the template did not make).
- `platform/project-template/0007_qualification.sql`, `0008_control_objectives.sql`, `0009_engine.sql`,
  `0010_report_composer.sql`, one shape (shown for qualification):
  ```sql
  DO $grant$
  BEGIN
    IF to_regproc('aisc_setup.apply_role_setting') IS NULL THEN
      RAISE EXCEPTION 'aisc_setup.apply_role_setting is missing: run init/project-databases.sql (postgres-setup) or isolate provision';
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO qualification_rw', current_database());
    PERFORM aisc_setup.apply_role_setting(
      format('ALTER ROLE qualification_rw IN DATABASE %I SET search_path = qualification', current_database()));
  END $grant$;
  CREATE SCHEMA IF NOT EXISTS qualification;
  GRANT USAGE, CREATE ON SCHEMA qualification TO qualification_rw;
  COMMENT ON SCHEMA qualification IS 'Step 1: this project''s AI cards, answers, risks and the forms they use.';
  DO $r$ BEGIN  -- readers get USAGE only; SELECT on tables comes from the module (I2.6)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'report_ro') THEN
      GRANT USAGE ON SCHEMA qualification TO report_ro; END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_ro') THEN
      GRANT USAGE ON SCHEMA qualification TO dashboard_ro; END IF;
  END $r$;
  ```
  The static test normalises whitespace and wants, in the file text: `GRANT CONNECT ON DATABASE %I TO <role>`,
  `CREATE SCHEMA IF NOT EXISTS <schema>`, `GRANT USAGE, CREATE ON SCHEMA <schema> TO <role>`,
  `COMMENT ON SCHEMA <schema>`, `ALTER ROLE <role> IN DATABASE %I SET search_path = <schema>`,
  `GRANT USAGE ON SCHEMA <schema> TO ... report_ro` and `... dashboard_ro` (one statement per reader, as above,
  satisfies `GRANT USAGE ON SCHEMA {schema} TO [^;]*\b{reader}\b`), no `ALTER DEFAULT PRIVILEGES`, no
  `BEGIN;`/`COMMIT;` lines, every CREATE with IF NOT EXISTS. Roles: 0008 control_objectives_rw, 0009 engine_rw,
  0010 report_composer_rw (skip the CONNECT/search_path part when report_composer_rw does not exist? No: it always
  exists after P1, platform-db.sql and report-roles.sql both create it; raise if absent).
- `platform/migrations/0005_the_composer_reads_members.sql`: `DO $$ BEGIN IF EXISTS (role report_composer_rw) THEN
  GRANT SELECT ON core.project_member TO report_composer_rw; END IF; END $$;` (platform_rw owns project_member, made
  by 0001). Reason: I1.4 on a fresh volume, where the bed runs init files once and the migrations after them, and
  report-roles.sql's old `ALTER DEFAULT PRIVILEGES FOR ROLE platform_rw IN SCHEMA core` must go (it would also
  cover `core.schema_migration`, which I1.4 forbids).
- `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql`: a verbatim copy of `init/platform-db.sql` at the
  pre-isolation base `f01288a` (`git show f01288a:init/platform-db.sql`), test infrastructure for every harness that
  must build the OLD shared layout (G3).
- `platform/tests/test_init_after_retire.py` (new test, TDD for P1-D3): on `scratch_database(old_layout=True)` run
  setup part, migrations, setup part; then C9's statements (owner to superuser, `REVOKE ALL`, the retired comment);
  run the setup part again and assert core.system is still owned by the superuser and no role gained a privilege
  on it; and the same after `DROP TABLE core.system CASCADE` (the non-vacuous form of the I2.8 guard tests, see
  section 5, W-1). The retirement comment is also set on the four schemas by C9 (G4).

Change:
- `platform/platform_service/db.py`, card versions (I2.2, I2.3, I2.5, I17.1):
  ```python
  class ProjectDatabaseGone(LookupError): """The project's row exists, its database does not (between drop and delete)."""
  def project_connection(pid) -> psycopg.Connection        # dict_row, one per call, closed by `with`
  def _project_ref(conn, identifier: str) -> dict | None   # {"pid", "slug"} from core.project
  def create_version(project, name, version, provider, description, subject) -> dict | None
  def list_versions(project) -> list[dict] | None
  def latest_version(project) -> tuple[bool, dict | None]
  def get_system(version_pid: str, project_pids: list[str]) -> dict | None   # scans only those databases
  ```
  `project_connection(pid)` first checks `SELECT 1 FROM pg_database WHERE datname = %s` through the pool and
  raises `ProjectDatabaseGone`; it also maps `psycopg.OperationalError` whose message names a missing database to
  `ProjectDatabaseGone` (the race). `create_version`: resolve the pid on the pool, then in one transaction on
  the project connection `SELECT pg_advisory_xact_lock(hashtext('project.system'))` and
  `INSERT INTO project.system (number, name, version, provider, description, created_by) VALUES
  ((SELECT coalesce(max(number), 0) + 1 FROM project.system), ...) RETURNING pid, number, name, version, provider,
  description, created_at, created_by`; add `project_id` = the pid to the returned dict (response shape
  unchanged: `_VERSION_COLUMNS` order). `list_versions`/`latest_version`: `ORDER BY number DESC` on
  `project.system`, `project_id` filled in. `get_system`: for each pid of `project_pids` (in `core.project`
  order), skip a missing database or one without `project.system` (`to_regclass`), return the first row found with
  `project_id` and `updated_at`. `core.system` is never named in `db.py` afterwards (grep).
- `platform/platform_service/app.py`: `/projects/{project}/system-versions` (POST, GET) and `/latest`: catch
  `db.ProjectDatabaseGone` and raise `no_project(project)` (404). `/systems/{pid}`: `looks_like_pid(pid)` else 404;
  `project_pids = [all pids] if caller.has_role(ADMIN_ROLE) else [r["pid"] for r in db.projects_for(caller.subject)]`;
  404 when not found; keep `role_or_404(str(found["project_id"]), caller)` as a second check.
- `platform/platform_service/projectdb.py`: add
  `def install_setup_function(su_conn_to_target, template1_dsn) -> None` (used by P2; reads the definition from
  template1 and creates `aisc_setup` + function + grants when absent) and
  `def provision_as(dsn: str, pid, *, set_role: str | None = None, owner: str | None = None) -> str`
  (`CREATE DATABASE ... OWNER <owner>` when given; `SET ROLE <set_role>` on the target connection before
  `migrate(...)`); `provision(dsn, pid)` keeps its signature and behaviour (it calls `provision_as(dsn, pid)`).
- `platform/platform_service/systems.py`: docstring only (card versions live in `project.system`).
- `platform/migrations/0002_*.sql`, `0003_*.sql`, `0004_*.sql`: guards of P1-D2.
- `init/platform-db.sql` (fresh volume; I2.8, I1.3, I1.4):
  - keep: the database, `REVOKE CREATE ON SCHEMA public FROM PUBLIC`, `CREATE SCHEMA core`, `core.project` and its
    index and comment, schema `catalogue` with its comment and `GRANT USAGE, CREATE ON SCHEMA catalogue TO
    catalogue_rw`, the roles loop (add `report_composer_rw` to it, password = name, as report-roles.sql's
    default), `GRANT CONNECT ON DATABASE platform` to every role, `GRANT USAGE ON SCHEMA core` to the module roles
    and dashboard_ro, platform_rw's rights on core, `ALTER ROLE platform_rw IN DATABASE platform SET search_path = core`;
  - remove: `core.system` and its indexes and comment, schemas qualification, control_objectives, engine, the
    module loop (REFERENCES, default privileges, dashboard_ro grants, module search_paths), every
    `ALTER DEFAULT PRIVILEGES` that names dashboard_ro or a module role on core, `GRANT SELECT ON ALL TABLES IN
    SCHEMA core`, dashboard_ro's multi-schema search_path;
  - add: `GRANT SELECT ON core.project TO qualification_rw, control_objectives_rw, controls_rw, engine_rw,
    catalogue_rw, report_composer_rw;` (not dashboard_ro, not REFERENCES);
    `ALTER ROLE dashboard_ro IN DATABASE platform SET search_path = core;`
    `CREATE SCHEMA form_library AUTHORIZATION qualification_rw;` `COMMENT ON SCHEMA form_library IS 'The install-wide library of qualification forms (D3): no project data.';`
    `CREATE SCHEMA report_library AUTHORIZATION report_composer_rw;` with a comment (D4).
    `core.project_member` SELECT comes from platform migration 0001 (module roles, catalogue_rw, dashboard_ro) and
    0005 (report_composer_rw).
- `init/project-databases.sql` (every start, superuser):
  - `\connect template1`: keep the REVOKE; add `CREATE SCHEMA IF NOT EXISTS aisc_setup;`, `REVOKE ALL ON SCHEMA
    aisc_setup FROM PUBLIC; GRANT USAGE ON SCHEMA aisc_setup TO platform_rw;`, `CREATE OR REPLACE FUNCTION
    aisc_setup.apply_role_setting(stmt text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path =
    pg_catalog AS $$ ... $$;` (the validation of P1-D1, `RAISE EXCEPTION 'refused: %', left(stmt, 200)` on
    anything else), `REVOKE ALL ON FUNCTION ... FROM PUBLIC; GRANT EXECUTE ... TO platform_rw;`.
  - `\connect platform`: `CREATE SCHEMA IF NOT EXISTS form_library AUTHORIZATION qualification_rw` and
    `report_library AUTHORIZATION report_composer_rw` (in a DO block that skips a missing role; the live volume
    gets them here at C5); the core.system owner line and the composite-key block inside one
    `DO $$ ... IF to_regclass('core.system') IS NULL OR <retired> THEN RETURN; END IF; EXECUTE 'ALTER TABLE core.system OWNER TO platform_rw'; ... $$`
    (P1-D3); nothing else about module schemas.
- `init/report-roles.sql` (every start): drop `core.system` from the SELECT and REFERENCES grants
  (`GRANT SELECT ON core.project TO report_ro, report_composer_rw;` and no REFERENCES at all), drop the
  `ALTER DEFAULT PRIVILEGES FOR ROLE platform_rw ...` line, keep the guarded `GRANT SELECT ON core.project_member TO
  report_composer_rw`, drop the three `report_composer` schema lines (`CREATE SCHEMA ... report_composer`,
  `ALTER SCHEMA report_composer OWNER`, its comment) and set `ALTER ROLE report_composer_rw IN DATABASE platform
  SET search_path = report_library, core;`; add `CREATE SCHEMA IF NOT EXISTS report_library AUTHORIZATION
  report_composer_rw` (idempotent; platform-db.sql made it on a fresh volume). The comment at its top that says
  the guard dumps the other two files stays true.
- `init/report-ro-grants.sql` is NOT touched by P1 (V1 owns it with `scripts/report-grants.sh`, I2.7).
- Compose files are NOT touched by P1 (W1 owns them, G1).

### Existing tests that change (S-D13, named in the commit message)

- `platform/tests/core_scratch.py`: `scratch_database(old_layout: bool = False)`; with `old_layout=True` it applies
  `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql` instead of `init/platform-db.sql`. Reason: the fresh volume no
  longer makes core.system (I2.8); the migration tests pin history that only exists on the old layout.
- `platform/tests/test_card_versions_migration.py` and `platform/tests/test_card_version_keys.py`: every
  `scratch_database()` becomes `scratch_database(old_layout=True)`. No assertion changes.
- `platform/tests/test_api_system_versions.py`: the three direct SQL reads/writes on `core.system` (lines 46,
  156-157, 183) move to `project.system` of the project's database (connect with
  `make_conninfo(dsn, dbname=projectdb.database_name(pid))`, drop the `where project_id = %s` filter). Same
  assertions.
- `platform/tests/test_systems.py`: docstring only (no assertion names core.system).

- `scripts/lib/report_bed.py` (G3, N3): `build()` builds the OLD shared layout on purpose (it is step 1 of
  `report_bed_isolated` and the bed of every not-yet-converted report test). It applies
  `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql` instead of `init/platform-db.sql`, and after
  `init/report-roles.sql` it creates what the new report-roles.sql no longer makes in `platform`:
  `CREATE SCHEMA IF NOT EXISTS report_composer AUTHORIZATION report_composer_rw`, `GRANT SELECT ON core.system TO
  report_ro, report_composer_rw`, `GRANT REFERENCES ON core.project, core.system TO report_composer_rw`,
  `ALTER ROLE report_composer_rw IN DATABASE platform SET search_path = report_composer, core` (the pre-isolation
  lines of report-roles.sql, `git show f01288a:init/report-roles.sql`). Every other step unchanged. Check: the
  composer (427) and renderer (642) baselines still pass after P1.
- `platform/tests/isolate_support.py` line 128 (T1): `NEW_QUALIFICATION_BASELINE = "20260925000000_project_database"`.

### Commands

New-layout recipe of section 1 (this plan), then from `platform/`:
`PLATFORM_TEST_DATABASE_URL=... PLATFORM_TEST_SUPERUSER_URL=... uv run --extra dev pytest -q -p no:cacheprovider --ignore=tests/test_isolate.py`
Expected: every test of `test_project_system.py` green; the pre-existing 278 pass (2 skipped, `test_chain.py`);
the new `test_init_after_retire.py` green. Then from the repo root:
`uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests/test_fresh_volume.py`
(all green except `test_i16_4_post_projects_*`, which waits for Z1), and
`scripts/tests/test_isolation_unchanged.py` (4 green).

### Commits (top-level repo, `isolation/2026-09-25`)

1. `platform/project-template/0006_project_system.sql` ... `0010_report_composer.sql`, `init/project-databases.sql`:
   "Isolation P1: template 0006..0010 open each project database to its modules (I2.1, P1-D1 definer for search_path)"
2. `platform/platform_service/db.py`, `platform/platform_service/app.py`, `platform/platform_service/projectdb.py`,
   `platform/platform_service/systems.py`: "Isolation P1: card versions live in project.system of each project database (I2.2, I2.3, I2.5)"
3. `init/platform-db.sql`, `init/report-roles.sql`, `platform/migrations/0002_one_ai_system_per_project.sql`,
   `platform/migrations/0003_card_versions_in_core_system.sql`, `platform/migrations/0004_card_version_of_its_project.sql`,
   `platform/migrations/0005_the_composer_reads_members.sql`: "Isolation P1: a fresh volume has only the shared schemas; every-start files survive retire and drop (I1.3, I1.4, I2.8)"
4. `platform/tests/core_scratch.py`, `scripts/tests/fixtures/isolation/pre_isolation_platform_db.sql`,
   `scripts/lib/report_bed.py`,
   `platform/tests/test_card_versions_migration.py`, `platform/tests/test_card_version_keys.py`,
   `platform/tests/test_api_system_versions.py`, `platform/tests/test_systems.py`, `platform/tests/test_init_after_retire.py`:
   "Isolation P1: tests that pinned core.system on a fresh volume use the pre-isolation layout (S-D13), and a retire guard test"
5. `platform/tests/isolate_support.py`: "Isolation test correction T1: the qualification baseline sorts before the forms migrations (20260925000000_project_database)"
6. `docs/superpowers/isolation-2026-09-25/04-code-notes.md` (created, P1 section).

---

## WP W1: compose and env wiring (the only writer of the top-level compose files, G1)

### Plan overrides (read first; they win over the text below)

- **Repos**: top-level only: `docker-compose.development.yml`, `docker-compose-infra.development.yml` (image tags),
  `env.development` (comment only). **Depends on** P1 (so the one-shots' commands exist on the branch in name; the
  compose tests are static `docker compose config` checks and do not run them). Wave 1.
- **Tests it turns green**: every `scripts/tests/test_compose_isolation.py` case (19 red today) and keeps green
  the 7 green ones; keeps `test_compose.py`, `test_service_tokens.py`, `test_inspector_network.py`,
  `test_isolation_unchanged.py` green and `test_report_stack.py` (2 known reds), `test_llm_keys.py` (1 known red) at
  baseline. The case list is in the X1 section's "1. Requirements" (the compose block); it belongs to W1.
- The text below was written as X1's section 4; W1 applies all of it. It already includes every compose request
  of Q1 (3.10), O1 (O1.7), E1 ("Files, top level"), R1 (compose line), D1 (step 6): those module sections are input
  only and their agents do not edit compose (G1). Where two texts differ, the text below wins, except: the dashboard's
  `AISC_MEMBERSHIP_DB_URI` goes on the `dashboard-env` anchor used by `dashboard-migrate` too when
  `test_i10_2_dashboard_reads_memberships_over_a_plain_dsn_and_registers_no_platform_connection[dashboard-migrate]`
  requires it (read the test; D1 step 6 describes both lines).
- `platform/Dockerfile` (`postgresql-client`) is P2's, not W1's.
- The qualification services lose `env_file: apps/qualification/env.development` (it would merge `DATABASE_URL`,
  which `test_compose_isolation.py:62` forbids) and get the listed variables inline.
- Command to run: `uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider
  scripts/tests/test_compose_isolation.py scripts/tests/test_compose.py scripts/tests/test_service_tokens.py
  scripts/tests/test_inspector_network.py scripts/tests/test_isolation_unchanged.py scripts/tests/test_report_stack.py
  scripts/tests/test_llm_keys.py`. Never `docker compose up` or `build` here.
- Commit (top-level): `docker-compose.development.yml docker-compose-infra.development.yml [env.development]`,
  "Isolation W1: compose wiring for project databases (DSN templates, migrate one-shots, membership DSN, isolate one-shot, image tags)".

### 4.0 Image tag (safety, applies to every built service)

- **What:** give every service with a `build:` an explicit `image: <name>:${AISC_IMAGE_TAG:-latest}` and `pull_policy: never`.
  - Keep today's names: `aisc-platform`, `aisc-backend`, `aisc-eval`, `aisc-webapp`, `aisc-control-objectives`, `aisc-report-composer`, `aisc-report-renderer`, `aisc-results-dashboard`, `aisc-qualification-agents`, `aisc-qualification-prefill`, `aisc-catalogue-*`, `aisc-schema-docs`.
  - Services that today get compose's default name get it written out: `aisc-controls-web`, `aisc-controls-migrate`, `aisc-controls-pdf`, `aisc-qualification-web`, `aisc-qualification-migrate`, `aisc-qualification-llm`, `aisc-qualification-ontology`, `aisc-qualification-pdf`.
  - `aisc-eval-flower` uses `aisc-eval:${AISC_IMAGE_TAG:-latest}`.
- **Why:** without this, building from the worktree overwrites the `:latest` images of the running stack. Any `docker compose up` in `~/aisc-install` by another session would then silently deploy isolation code. With the variable unset, the names resolve exactly as today.
- **Build command for stage 5 and 6:**
  ```
  AISC_IMAGE_TAG=isolation REPORT_GENERATOR_DIR=$HOME/aisc-isolation-report-generator \
    docker compose -p aisc-isolation-build --project-directory ~/aisc-isolation --env-file env.development \
    -f docker-compose-infra.development.yml -f docker-compose.development.yml build
  ```

### 4.1 Qualification

- Remove `env_file: apps/qualification/env.development` from `qualification-web` and `qualification-migrate`. `docker compose config` merges env_file into `environment`: I checked that it puts `DATABASE_URL` into qualification-web today, and `test_compose_isolation.py:62` forbids it.
- Inline the non-secret variables that file provided into `qualification-web` only: `LLM_SERVICE_URL: http://qualification-llm:4000`, `SYSTEM_CARD_RENDERER_URL: http://qualification-pdf:8005`, `ONTOLOGY_SERVICE_URL: http://qualification-ontology:8011`, `PLATFORM_URL: http://platform:8000`, `LAUNCHER_URL: ${LAUNCHER_EXTERNAL_URL:-http://localhost:8100/}`.
- Both services get:
  ```yaml
  PROJECT_DATABASE_URL: ${QUALIFICATION_PROJECT_DATABASE_URL:-postgresql://qualification_rw:qualification_rw@postgres:5432/{database}?schema=qualification&connection_limit=2}
  FORM_LIBRARY_DATABASE_URL: ${QUALIFICATION_FORM_LIBRARY_DATABASE_URL:-postgresql://qualification_rw:qualification_rw@postgres:5432/platform?schema=form_library&connection_limit=2}
  ```
  I probed this: `{database}` inside a `${VAR:-...}` default resolves correctly.
- `qualification-migrate`:
  ```yaml
  command: >
    sh -c "until node scripts/migrate-projects.mjs; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[qualification] waiting for postgres'; sleep 2; done"
  depends_on: [postgres, platform]
  restart: "no"
  ```
- Tokens: qualification-migrate holds none. Keep every `${…TOKEN:?run scripts/secrets.sh first}` on qualification-web exactly as it is (`test_service_tokens`).
- Note to Q1 (not X1): the submodule's `env.development` still has `DATABASE_URL`. It is unused by compose now; Q1 may update it for standalone dev.

### 4.2 Control objectives

- `control-objectives` and `control-objectives-migrate` keep `DATABASE_URL` (membership, unchanged) and add:
  ```yaml
  PROJECT_DATABASE_URL: ${CONTROL_OBJECTIVES_PROJECT_DATABASE_URL:-postgresql+psycopg://control_objectives_rw:control_objectives_rw@postgres:5432/{database}}
  ```
  The driver is explicit because the tests use `+psycopg` and only `settings.py` normalizes `DATABASE_URL`.
- `control-objectives-migrate`:
  ```yaml
  command: >
    sh -c "until python -m aisc_control_objectives.migrate_projects; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[control-objectives] waiting for postgres'; sleep 2; done"
  depends_on: [postgres, platform]
  ```
  Add `PYTHONPATH: /app/src` if the image does not install the package (check the CO Dockerfile).

### 4.3 Engine

- `aisc-backend`:
  - Turn its environment into an anchor `environment: &backend-env`.
  - Change the command to `sh -c "uv pip install --no-deps -e /app/shared/plugin-manager -e /app/shared/plugin-interface && uv run uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --no-access-log"`. The `manage.py migrate` is gone.
  - Add `aisc-backend-migrate: {condition: service_completed_successfully}` to `depends_on`.
- New `aisc-backend-migrate`:
  ```yaml
  aisc-backend-migrate:
    build: apps/backend/
    image: aisc-backend:${AISC_IMAGE_TAG:-latest}
    pull_policy: never
    container_name: aisc-backend-migrate
    environment: {<<: *backend-env}
    volumes: [same two as aisc-backend]
    networks: [backend]
    depends_on: {postgres: {condition: service_started}, platform: {condition: service_started}}
    restart: "no"
    command: >
      sh -c "uv pip install --no-deps -e /app/shared/plugin-manager -e /app/shared/plugin-interface
      && until uv run manage.py migrate_projects; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[engine] waiting for postgres'; sleep 2; done"
  ```
- `DB_NAME=platform`, `DB_USER=engine_rw` and `DB_SCHEMA=engine` stay (E1's platform alias and template, as the isolation bed calls it).

### 4.4 Report composer and renderer

- `report-composer`: turn its environment into an anchor `&composer-env`. Keep `REPORT_COMPOSER_DATABASE_URL` exactly as it is (`test_r4_1_3` wants `report_composer_rw` and a URL ending in `/platform`). Add:
  ```yaml
  REPORT_COMPOSER_PROJECT_DATABASE_URL: postgresql://report_composer_rw:${REPORT_COMPOSER_PASSWORD:-report_composer_rw}@postgres:5432/{database}
  ```
  Add `report-composer-migrate: {condition: service_completed_successfully}` and `platform: {condition: service_started}` to its `depends_on`.
- New `report-composer-migrate`:
  - `image: aisc-report-composer:${AISC_IMAGE_TAG:-latest}`, `pull_policy: never`, `environment: {<<: *composer-env}`, the same identity volume, `networks: [backend]`, `restart: "no"`.
  - `depends_on: {postgres-setup: completed, platform: started}`.
  - `command: ["python", "-m", "report_composer.migrate"]`. This command is already pinned by `scripts/tests/isolation_bed.py:236`: the library, then every project database.
- `report-renderer`: no change. `REPORT_PROJECT_DB_URL` already has `{database}`. Keep `${REPORT_GENERATOR_DIR:-../aisc-report-generator}`: the default must stay for main after the merge, and the cutover exports `REPORT_GENERATOR_DIR=$HOME/aisc-isolation-report-generator`.
- `report-grants`: add `aisc-backend-migrate: {condition: service_completed_successfully}` to `depends_on`. It now has a one-shot to wait for, so V1's script no longer needs the 600 s wait for `engine.measurement`.

### 4.5 Dashboard

- Delete `AISC_RESULTS_DB_URI` from the `dashboard-env` anchor (which covers `dashboard-migrate`) and from `dashboard`.
- Add to `dashboard` only:
  ```yaml
  AISC_MEMBERSHIP_DB_URI: ${AISC_MEMBERSHIP_DB_URI:-postgresql+psycopg2://dashboard_ro:dashboard_ro@localhost:5432/platform}
  ```
  It uses `localhost` because the dashboard is on the host network.

### 4.6 Move tool one-shot

```yaml
isolate:
  image: aisc-platform:${AISC_IMAGE_TAG:-latest}
  pull_policy: never
  profiles: ["isolation"]           # never started by `up`; `run isolate` enables it
  entrypoint: ["python", "-m", "platform_service.isolate"]
  environment:
    # no password in the URL (no URL-encoding problem); libpq and pg_restore take PGPASSWORD
    ISOLATE_SUPERUSER_URL: postgresql://${POSTGRES_USER}@postgres:5432/${POSTGRES_DB}
    PGPASSWORD: ${POSTGRES_PASSWORD}
    PYTHONPATH: /app/shared/identity
  volumes:
    - ./shared/identity:/app/shared/identity:ro,z
    - ./platform/project-template:/app/project-template:ro,z
  networks: [backend]
  restart: "no"
```

- **Why a separate service:** it keeps the superuser credential out of the long-running `platform` service. The spec's `run --rm platform python -m …` is otherwise equivalent.
- **Backup mount:** the cutover adds `-v "$BACKUP:/backup"` on the `compose run` line, so no path variable is needed in compose. A `:?` variable there would break every normal `up`.
- **`platform/Dockerfile`:** add `RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*`. Debian ships client 15. It restores a pg_dump 14 archive into server 14, and the rehearsal's stage-7 drill proves it.

### 4.7 Rule for new variables

Every new variable has a compose default or is built from `POSTGRES_*`. The live env file (`env.runtime` = `env.plugin_downloader` + `env.secrets`) then works unchanged.


---

## WP P2: the move tool, `python -m platform_service.isolate`

**Repos**: top-level (`platform/`). **Depends on**: P1 (template 0006..0010, `projectdb.provision_as`,
`install_setup_function`). Can run in parallel with every module WP (its tests build their own targets).

### Requirements and tests

I12.1..I12.16, C6 (provision), D4, D5, D14, D15, I13.4, S-D1..S-D4. Tests: all 58 cases of
`platform/tests/test_isolate.py` (55 red, 3 fixture self-tests green). The interface is pinned in that file's
docstring; this section adds only how to build it.

### Files (create)

A package, so `python -m platform_service.isolate` and `import platform_service.isolate` both work:

| file | contents |
|---|---|
| `platform/platform_service/isolate/__init__.py` | `main(argv: list[str] | None = None) -> int`; re-exports |
| `platform/platform_service/isolate/__main__.py` | `raise SystemExit(main())` |
| `.../isolate/cli.py` | argparse: subcommand, `--project` (append), `--all`, `--dry-run` (copy only), `--report PATH`, positional dump files for `verify-dump`; pids validated with `projects.PID` (a bad pid exits 2 with `not a project id`); `ISOLATE_SUPERUSER_URL` required (exit 2, never echoed) |
| `.../isolate/catalog.py` | `Table` dataclass (`name`, `columns: list[Column(name, type, not_null, has_default)]`, `pk: tuple[str, ...]`, `fks: list[Fk(name, columns, ref_table, ref_columns)]`, `sequences: dict[column, seq]`); `read_tables(conn, schemas) -> dict[str, Table]` from `pg_class`, `pg_attribute`, `format_type(atttypid, atttypmod)`, `pg_constraint`, `pg_get_serial_sequence`/`pg_depend`; `classify(tables) -> dict[str, str]` |
| `.../isolate/ownership.py` | `load_keys(conn, tables) -> RowGraph` (every row's pk tuple and FK values; data is small, one snapshot); `place(graph, projects: set[str]) -> Placement` (fixpoint of I12.3 plus rule L below); conflicts; unowned |
| `.../isolate/rowtext.py` | `SETTINGS` (the four `SET` of I12.7, also `SET TIME ZONE 'UTC'`); `checksum_sql(table, cols, keyset)` producing exactly `SELECT count(*), md5(coalesce(string_agg(r, E'\n' ORDER BY r), '')) FROM (SELECT ROW(<cols>)::text AS r FROM t WHERE <pk> IN (...)) s` (same as `isolate_support.checksum`), per-row `md5(ROW(...)::text)` by key for the equality checks |
| `.../isolate/copy.py` | `copy_project(src_snapshot, target_su_conn, placement, pid, *, dry_run) -> ProjectReport`; `copy_library(...)` |
| `.../isolate/verify.py` | `verify_project(...)`, `coverage(...)` (I12.13), `verify_dump(dump_files, ...)` (I12.14) |
| `.../isolate/preconditions.py` | old heads, new heads, templates, sessions, column coverage (I12.6) |
| `.../isolate/report.py` | report dict of the docstring, written with `os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`; the human summary (pids, table names, counts, statuses, refusal reasons only) |

### Rules the code implements (the only hand-written knowledge)

- Source schemas: `core` (only `core.system` moves), `qualification`, `control_objectives`, `engine`,
  `report_composer`. `STAYS_SHARED = {core.project, core.project_member, core.schema_migration}` plus every
  `catalogue.*`. `BOOKKEEPING` = the five tables of I12.1. `LIBRARY = {qualification.form: form_library.form,
  qualification.form_version: ..., qualification.form_question: ..., qualification.form_version_question: ...,
  report_composer.preset: report_library.preset}`; `LIBRARY_ONLY = {report_composer.preset}` (S-D2: never a root,
  never copied into a project). Target of `core.system` is `project.system`; every other table keeps its name.
  `DROPPED_COLUMNS = {"project_id"}` allowed on `core.system` and the five tables of I1.7, nothing else.
- Old heads (preconditions, `source not at old head`): the names in `isolate_support.OLD_QUALIFICATION` (+
  `FORMS_MIGRATIONS` when `to_regclass('qualification.form')` is not NULL, S-D3), every row finished and not
  rolled back; `control_objectives.alembic_version = '7c3e5a9b1d24'`; engine `django_migrations` contains
  `0024_no_login_of_its_own`; `report_composer.schema_migration` contains `OLD_COMPOSER` (0001..0005); core
  contains `OLD_CORE` (0001..0004; 0005 of P1 may be present). Keep these lists as constants in
  `preconditions.py` (copied, not imported from tests). `verify` and `verify-dump` skip the old-head check.
- New heads (`target not at new head`, per project database): qualification `_prisma_migrations` contains
  `20260925000000_project_database` (T1; + the two forms names when the source has forms), finished, not rolled back;
  `control_objectives.alembic_version = '20260926000000_project_database'`; engine `django_migrations` contains
  `0025_the_database_is_the_project`; `report_composer.schema_migration` contains `0001_project_database.sql`;
  `controls._prisma_migrations` contains the three controls names of `CONTROLS_HEAD`. `missing template`: a file
  of `projectdb.TEMPLATE` absent from `provision.template_migration`.
- `active sessions`: any `pg_stat_activity` row, other than the tool's own backends, on the source database or a
  target database whose `usename` is platform_rw or ends in `_rw`, or is report_ro, dashboard_ro. (The tests hold
  one platform_rw session on a target and one qualification_rw session on the source.)
- `column coverage`: every source column except the allowed dropped ones exists in the target with the same
  `format_type`; every target-only column has a default or is nullable (`NOT NULL` without default refuses).
- **Placement (I12.3 as written, plus rule L that closes open issue 3)**, over the FK graph child -> parent:
  - global table: a moving table with no FK path to `core.project` (today `engine.metric`, `engine.direct`,
    `engine.derived`, `engine.metric_category`, `engine.metric_category_metrics`, the four form tables);
  - root rows: rows of a table with an FK to `core.project(pid)`, excluding `LIBRARY_ONLY`; owner = that value;
    a NULL value makes the row unowned (engine.project 3); a value not in `core.project` is `unknown project`;
  - owned(P): root rows of P, then any row with an FK to an owned(P) row (to a fixpoint);
  - needed(P): a row outside `STAYS_SHARED` referenced by an FK of an owned(P) or needed(P) row; and an
    identifying child (its PK columns include an FK's columns) whose FK references a copied(P) row;
  - **rule L (link rows)**: a row of a global table whose columns are only its single-column primary key and the
    columns of two or more FKs (a many-to-many link, today `engine.metric_category_metrics`) is needed by P when
    any row it references is copied(P); its other referents then become needed by the rule above. Categories
    follow the metrics a project uses; an unused category stays unowned (fixture: metric_category 2);
  - conflicts, all collected before any write: a row owned by two projects (`owned by two projects`, both pids);
    a copied(P) row whose FK names a row owned by Q != P (`cross-project reference`); either reason may be
    reported for the same row (open issue 4: report both when both hold; the tests accept either);
  - unowned: a row of a moving, non-bookkeeping table in no copied set and not a library row, reported with its
    pk and reason (`no project`, `engine project without platform project`, `not used by any project`); rows of a
    project whose database is missing are reported, not moved.
- A moving table without a primary key refuses (`unclassified table`, reason detail `no primary key`); a table in
  no set and in none of the rules refuses (`unclassified table`).

### Copy, per project, pid order (I12.7, I12.8, D14, D15)

1. Source: one connection, `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`, SETTINGS; read the catalog and the
   row graph once (one snapshot for the run; `snapshot_time = now()` of that transaction); never `FOR UPDATE`;
   end with ROLLBACK. The I12.11 test holds EXCLUSIVE locks on every moving table while the tool runs: plain
   SELECT and COPY TO pass, anything else blocks, so the source code path may only SELECT/COPY.
2. Target, as the superuser: `BEGIN`, `SET LOCAL session_replication_role = replica`, SETTINGS (SET LOCAL);
   for each mapped table: per-key md5 of the target rows vs the source copied set; a target row with a copied key
   and a different md5, or a target row whose key is not in the copied set and not equal to a source row of the
   same key (the equal seed is allowed), aborts the project with `target not empty and not equal` (table, pid,
   keys); if every copied key is present and equal and nothing extra is there for every table, the project is
   `already done` and the transaction ends in ROLLBACK (no commit: the xact_commit tests);
3. otherwise insert the missing keys with `COPY (SELECT <shared cols in target order> FROM t WHERE <pk> IN (...))
   TO STDOUT` on the source piped to `COPY t (<cols>) FROM STDIN` on the target (text format under the same
   SETTINGS keeps floats, bytea, jsonb, arrays and timestamps exact); then every FK of every target table by an
   anti-join (as `isolate_support.fk_orphans`), any orphan aborts; sequences: for every target column with a
   sequence, `setval(seq, max(source last_value, max(target column)), source is_called)` (when the target
   maximum wins, `is_called = true`); then the per-table checksums of I12.10 on the copied keys, any mismatch
   aborts; COMMIT. Any exception: ROLLBACK, status `failed`; the run does not go on to later projects: stop at the first failed project, report it `failed`, exit non-zero (D15 resumes by re-running;
   the resume test expects A copied, B failed, and a second run A `already done`, B `copied`).
4. The library copy runs after the projects in its own transaction on the source database (the only write the tool
   makes to `platform`): `qualification.form*` rows (every row) into `form_library.form*`, `report_composer.preset`
   into `report_library.preset`, same equality rules (a seed that differs aborts with `target not empty and not
   equal`, table `qualification.form`). With the forms tables absent the form part is skipped (S-D3). The I12.11
   test reads the digests of the source's moving schemas and core, not `form_library`/`report_library`.
5. `--dry-run` and `plan` do steps 1 and 2 read-only, fill `to_copy`, `already_present`, `sequences` and end in
   ROLLBACK everywhere; status `planned`.

### Subcommands

- `plan`: preconditions except new heads when a target is missing; classification, placement, per-table counts;
  `missing database` status for a project without a database (no refusal in `plan`).
- `provision`: for each project, `projectdb.provision_as(ISOLATE_SUPERUSER_URL, pid, owner="platform_rw",
  set_role="platform_rw")` after `projectdb.install_setup_function(...)` into the target when absent (S-D4); twice
  is a no-op.
- `copy [--dry-run]`: all preconditions (every refusal before any write), then per project, then library.
- `verify`: recomputes placement from the current source and every target's checksums from scratch; status
  `verified`; `coverage[table] = {source_rows, covered, missing}` where covered = union of copied keys over all
  projects + unowned keys + library rows + bookkeeping (I12.13); any missing is `count mismatch`.
- `verify-dump <files...>`: create `isolate_verify_<hex>` as the superuser; in it `CREATE SCHEMA core`, create
  `core.project` (columns and pk from the source catalog) and copy its rows from the source, and
  `core.system_only_latest_changes()` from `pg_get_functiondef` of the source when it exists; restore the file
  that holds `core.system` first, then the schema file (`pg_restore --no-owner --no-acl --exit-on-error
  --single-transaction -d <dsn>`; the tool tells the two files apart with `pg_restore --list`); then run `verify`
  with that database as the source of the moving tables (library tables still from the source database); drop the
  database in a `finally` (the test checks nothing is left). `pg_restore` comes from PATH (the tests put a shim
  there; the platform image gets `postgresql-client`, see below).
- `report`: read-only current state (as `verify`, without failing on differences: statuses and md5s only).

### Also

- `platform/Dockerfile`: `RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*`
  (verify-dump in the one-shot container; the bookworm client restores a PG14 custom dump). Compose wiring of the
  one-shot is X1's.
- Logging: `logging` to stderr, pids, table names and counts only. Every exception message printed goes through
  `redact(text, dsn)` that removes the DSN's password and never includes row data (use `%s` of counts, never of
  `psycopg` `Diagnostic.message_detail`, which can contain key values: print `sqlstate` and the constraint name).

### Commands

New-layout recipe, then from `platform/`:
`PLATFORM_TEST_DATABASE_URL=... PLATFORM_TEST_SUPERUSER_URL=... uv run --extra dev pytest -q -p no:cacheprovider tests/test_isolate.py`
(about 8 minutes). Then the whole platform suite as in P1 (must stay as P1 left it).

### Commits (top-level)

1. `platform/platform_service/isolate/` (all files), `platform/Dockerfile`:
   "Isolation P2: python -m platform_service.isolate moves each project's rows into its database, verified by count and checksum (I12)"

---

## WP Q1: qualification routing, one database per project

### Plan overrides (read first; they win over the text below)

- **G6/T1**: the baseline directory is `prisma/migrations/20260925000000_project_database` (not `20260926...` as
  written below). Q1 also makes correction T1 in `test/unit/isolationBaseline.test.ts:13` and
  `test/db/projectDatabase.db.test.ts:30`, and corrections T2 and T3 (section 4), each committed alone.
- **G1**: Q1 does not edit `docker-compose.development.yml`; section 3.10's compose lines are W1's. Q1 still edits
  the submodule's own `env.development` and `Dockerfile`.
- **G2**: the harnesses of flag F6 below (`test_card_version_keys_orders.py`, `guard-frozen.sh --orders`,
  `test-pipeline-chain.sh`) are V1's; Q1 only lists them in its notes.
- The flags F2 and F3 below are T2 and T3; F6 is handed to V1; R1 in its section 8 is a risk, not a test change.
- Run the unit and agents suites first (no P1 needed); the DB suite after P1 is committed.
- Ambiguity 10 (local `node_modules`) is accepted (N9); the check that `~/aisc-install/...` was not written is
  mandatory, and the new `node_modules` directory is never committed.

### 0. Scope, dependencies, repos

- **Repos:**
  - Submodule worktree `/home/listuser/aisc-isolation/apps/qualification` (branch `isolation/2026-09-25`).
  - Top level `/home/listuser/aisc-isolation`, only for `docker-compose.development.yml` and the gitlink.
- **Depends on P1.** The DB tests need templates `platform/project-template/0006_project_system.sql` and `0007_qualification.sql`:
  - `0006` makes schema `project` and table `project.system`, with SELECT and REFERENCES for `qualification_rw`.
  - `0007` makes schema `qualification`, owned by `platform_rw`. It grants USAGE and CREATE to `qualification_rw`, USAGE to `report_ro` and `dashboard_ro`, CONNECT to `qualification_rw`, and sets search_path `qualification`.
  - The unit tests, the agents tests and the compose tests do not need P1, so they can be done first.
- **Out of scope:**
  - No forms file is touched (gate I4.6).
  - `test/db/formLibrary.db.test.ts` keeps skipping.
  - No platform or template code.

### 1. Requirements and the tests that turn green

**I1.8, I3.1, I17.1, I2.5 in `test/unit/isolationProjectDb.test.ts`:** every case.
- "I1.8 one name rule" (8 cases)
- "I3.1 projectDatabaseUrl" (4)
- "I3.1 I17.1 prismaFor" (5)
- "I3.1 projectDbFor" (6)
- "I3.1 source scan" (4)

**I3.2, I3.3, I3.4, I16.5, I18.1, I18.3, I18.4 in `test/unit/isolationRoutes.test.ts`:** every case.
- "I3.3 the id-addressed routes move" (10)
- "I3.3 I16.5 a card of project A opened under project B" (22)
- "I3.4 I18.1 I18.4 the card agent" (11)
- "I18.3" (2)
- "I3.2 the middleware" (6)

**I3.3, I3.4, I3.6, I3.8, I16.5, I18.3 in `test/unit/isolationActionsAndPages.test.ts`:** every case, but 7 of them only after the test fix in section 8 (F2).

**I3.5 in `test/unit/isolationBaseline.test.ts`:** the five "I3.5 one baseline" cases. The byte-for-byte case and the two "I4.2" cases keep skipping; the "I4.6 gate recorded" guard stays green.

**I1.5, I1.6, I1.7, I2.5, I2.6, I3.5, I3.6, I3.7, I16.5, I17.1 in `test/db/projectDatabase.db.test.ts`** (after P1):
- "isolation setup"
- "I3.6 scripts/migrate-projects.mjs" (5)
- "I3.5 I3.7 ..." (5)
- "I1.5 I1.6 I3.5 I16.5 cards and versions" (5)
- "I2.6 report_ro and dashboard_ro" (2)
- "I2.5 I17.1 projectDb.ts after the drop" (1)

**I3.4, I18.1, I18.4, I1.8 in `services/agents/tests/test_isolation_paths.py`:** all 11 cases except `test_i3_4_the_run_is_polled_at_fill_pid_id`, which needs the F3 fixture fix.

**I3.6, I3.8, I16.4, I18.1 in `scripts/tests/test_compose_isolation.py`:**
- `test_i3_8_qualification_gets_a_project_database_template[qualification-web|qualification-migrate]`
- `test_i3_8_qualification_reaches_platform_only_for_the_form_library[...]`
- `test_i3_6_qualification_migrate_runs_migrate_projects_after_the_platform`
- `test_i16_4_...[qualification-web|qualification-migrate]`
- `test_i18_1_*` (must stay green)

**Qualification parts of `scripts/tests/test_project_grants.py`** (after P1, run with `-k qualification`): I2.1 search_path, I2.6 readers, I2.6 owners, I16.1.

### 2. Pre-work: a local Prisma client (required)

`apps/qualification/node_modules` is a symlink to `~/aisc-install/...`. Its generated client (`.prisma/client`) was built from the forms schema, which still has `projectId` and the form models. Q1 removes `projectId`, so the client must be regenerated. Writing through the symlink would modify `~/aisc-install`, which RULES forbid.

The worktree gets a real `node_modules` directory: symlinks to every original entry, plus private copies of `@prisma` and `.prisma`.

```
cd /home/listuser/aisc-isolation/apps/qualification
SRC=/home/listuser/aisc-install/apps/qualification/node_modules
before=$(stat -c %Y $SRC/.prisma/client/index.js)
rm node_modules                     # removes the LINK only (check first: [ -L node_modules ])
mkdir node_modules
for e in "$SRC"/* "$SRC"/.bin; do ln -s "$e" node_modules/; done
rm node_modules/@prisma && cp -a "$SRC/@prisma" node_modules/@prisma
cp -a "$SRC/.prisma" node_modules/.prisma
npx prisma generate
[ "$(stat -c %Y $SRC/.prisma/client/index.js)" = "$before" ] || echo "STOP: wrote into aisc-install"
grep -c projectId node_modules/.prisma/client/schema.prisma   # expect 0
```

`node_modules` is untracked and shows as `??`, so never add it to a commit. It is flagged as ASSUMED in section 9 for orchestrator acknowledgement.

### 3. Files, modules, signatures

#### 3.1 `src/server/access/projectAccess.ts` (change, must stay edge-safe)

Add the following. Keep `decide`, `fetchAccess` and `REFUSED` unchanged.

```ts
export const PROJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isProjectId = (x: string): boolean => PROJECT_ID.test(x);
```

Change `projectFromPath` so a malformed `%` escape returns the raw segment instead of throwing (URIError). The pid check then gives 404.

#### 3.2 `src/lib/projectDb.ts` (create, modelled on `apps/controls/src/lib/projectDb.ts`)

Imports:
- `PrismaClient` from `"@prisma/client"` (the tests mock that id).
- `execFile` from `"node:child_process"`. It must be the `node:` id, because that is what the tests mock.
- `promisify`, and `notFound` from `next/navigation`.
- `decide`, `fetchAccess`, `REFUSED`, `PROJECT_ID` from `projectAccess`.
- `callerToken`.

```ts
export { PROJECT_ID };
export class NotAProject extends Error {}
export class Refused extends Error { constructor(readonly status: 403 | 503, message: string) }
export const PLATFORM_SILENT = "The platform is not answering, so who may be here cannot be established.";
export const MAX_OPEN_PROJECTS = 20;
export function projectDatabaseName(pid: string): string;          // throws NotAProject unless PROJECT_ID; "project_" + lowercase hex
export function projectDatabaseUrl(pid: string, template: string = process.env.PROJECT_DATABASE_URL ?? ""): string;
export async function migrateProjectDatabase(url: string): Promise<void>;   // run("npx", ["prisma","migrate","deploy"], { env: { ...process.env, DATABASE_URL: url } })
export function isMissingDatabase(err: unknown): boolean;          // code|errorCode P1003, or message (or stderr) /database .* does not exist/i
export async function prismaFor(pid: string, deps?: { migrate: (url: string) => Promise<void> }): Promise<PrismaClient>;
export async function closeProjectDatabases(): Promise<void>;
export async function callerAccess(pid: string): Promise<Access | null>;    // fetchAccess(pid, await callerToken(), { platformUrl: process.env.PLATFORM_URL ?? "" })
export async function projectDbFor(pid: string, opts: { write: boolean }): Promise<PrismaClient>;
export async function projectDbForRoute(pid: string, opts: { write: boolean }): Promise<PrismaClient | Response>;
export async function projectDbForAction(pid: string, opts: { write: boolean }):
  Promise<{ db: PrismaClient; error?: undefined } | { db?: undefined; status: 403 | 404 | 503; error: string }>;
export async function projectDbForService(pid: string): Promise<PrismaClient | Response>;
export async function projectDbPastDoor(pid: string): Promise<PrismaClient>;
```

**`projectDatabaseUrl`:**
- Throws `Error("PROJECT_DATABASE_URL must contain {database}")` when the template has no `{database}`.
- Replaces `{database}`, then always sets the query parameters `schema=qualification` and `connection_limit=2`. Existing values are overwritten, because the budget belongs to the module.

**`prismaFor`:** the same as controls.
- The cache is a `Map` on `globalThis`, keyed by URL, most recently used last.
- The entry is set synchronously before the migration is awaited, so concurrent first requests share one migration.
- `ready.catch` forgets the entry.
- Past 20 entries, the oldest is disconnected.
- Build the client with `new PrismaClient({ datasources: { db: { url } } })`.
- Add `client.$use(...)`: when a query throws and `isMissingDatabase(err)` is true, forget the entry and rethrow.
- Also handle P1017 or "closed the connection" (see risk R1): probe once with `SELECT 1`, guarded against recursion. If the probe fails with a missing database, forget the entry and throw the probe's error.

**One internal decision, `door(pid, write)`, behind all the wrappers:**
- Not a pid: 404, with the platform never asked.
- Otherwise `decide(write ? "POST" : "GET", await callerAccess(pid))`:
  - `not-found` gives 404.
  - `forbidden` gives 403 with `REFUSED[403]`.
  - `unavailable` gives 503 with `PLATFORM_SILENT`.
  - `allow` opens the database with `prismaFor(pid)`. If that fails with a missing database, the answer is 404.

**How each wrapper maps the decision:**

| wrapper | 404 | 403 | 503 | used by |
|---|---|---|---|---|
| `projectDbFor` | `notFound()` | throw `new Refused(403, REFUSED[403])` | throw `new Refused(503, PLATFORM_SILENT)` | the core door (the tests pin it) |
| `projectDbForRoute` | `new NextResponse("Not found", {status:404})` | `NextResponse.json({error: REFUSED[403]}, {status:403})` | `NextResponse.json({error: PLATFORM_SILENT}, {status:503})` | route handlers |
| `projectDbForAction` | `{status:404, error: REFUSED[404]}` | `{status:403, error: REFUSED[403]}` | `{status:503, error: PLATFORM_SILENT}` | server actions |
| `projectDbForService` | 404 Response (non-pid or missing database) | n/a | n/a | the card agent's routes only, after the token check. No platform question |
| `projectDbPastDoor` | `notFound()` (non-pid or missing database) | n/a | n/a | code reached only through a door (see below) |

`projectDbPastDoor` asks the platform nothing. It is for code that only runs after a door has let the caller through:
- a page server component, whose `/p/{pid}` the middleware already decided;
- services called after one of the other doors;
- the agent branch, after its token check.

No other file in `src/` may construct a `PrismaClient` from `@prisma/client` or call `prismaFor` (the scan test enforces this).

#### 3.3 `src/middleware.ts` (change)

```ts
const AGENT_ROUTE = /^\/p\/[^/]+\/api\/qualifications\/[^/]+\/extracted\/?$/;
export async function middleware(request: NextRequest) {
  const project = projectFromPath(pathname);
  if (project === null) return NextResponse.next();
  if (!isProjectId(project)) return new NextResponse("No such project.", { status: 404 });   // I3.2, before the platform
  if (AGENT_ROUTE.test(pathname) && ["GET","PUT"].includes(request.method.toUpperCase())
      && request.headers.get(SERVICE_TOKEN_HEADER) !== null) return NextResponse.next();        // the route checks the token
  ...existing fetchAccess / decide switch...
}
```

- Import `SERVICE_TOKEN_HEADER` from `@/server/services/http`, which is edge-safe.
- Do not import `serviceToken.ts` (it uses `node:crypto`, and Next 15.0 middleware runs on the edge), and do not import `projectDb.ts`.
- Do not read `QUALIFICATION_AGENTS_TO_WEB_TOKEN` here. `agentToken.test` pins that exactly one file reads it.

#### 3.4 `src/server/repositories/QualificationRepository.ts` (change: bound to one project database)

- Remove the `@/lib/prisma` import, the default constructor argument, and the `qualificationRepository` singleton.
- Remove `projectId` from `CreateQualificationInput`.
- Every query filters by `id`, `systemId` or `qualificationId` only, because the database is the project.

```ts
export class QualificationRepository {
  constructor(private readonly db: PrismaClient) {}
  create(input: CreateQualificationInput): Promise<{ id: string }>;
  find(id: string): Promise<QualificationWithAnswers | null>;
  findBySystem(systemId: string): Promise<{ id: string; systemId: string; systemName: string; systemVersion: string } | null>;
  list(): Promise<QualificationWithAnswers[]>;
  cardSummary(id: string): Promise<...same Pick as today... | null>;
  linkComponent(qualificationId: string, link: ComponentLinkInput): ...;
  unlinkComponent(qualificationId: string, componentPid: string): ...;
  knowledgeGraph(qualificationId: string): ...;
  saveKnowledgeGraph(data: ...): ...;
  saveOntologyPatch(id: string, patch: Prisma.InputJsonValue): ...;
  saveOntologyExtracted(id: string, extracted: Prisma.InputJsonValue): ...;
  saveSystemCard(id: string, json: Prisma.InputJsonValue): ...;
  isLatest(systemId: string): Promise<boolean>;   // SELECT qualification.card_is_latest(${systemId}::uuid) AS latest
}
export type RepositoryFor = (project: string) => Promise<QualificationRepository>;
export const repositoryFor: RepositoryFor = async (project) => new QualificationRepository(await projectDbPastDoor(project));
```

#### 3.5 Services (change)

**`KnowledgeGraphStore.ts`**
- The class keeps its API unchanged: `constructor(repo)`, `save(qid, built)`, `document(qid, built, format)`, `deliver(qid, format, build)`. This keeps `KnowledgeGraphStore.test.ts` green.
- The exported singleton becomes a per-project front:

```ts
export class ProjectKnowledgeGraphs {
  async deliver(qualificationId: string, format: "turtle" | "jsonld", build: () => Promise<OntologyBuild>, project: string)
    { return new KnowledgeGraphStore(await repositoryFor(project)).deliver(qualificationId, format, build); }
}
export const knowledgeGraphStore = new ProjectKnowledgeGraphs();
```

The first argument must stay the card id, because `isolationActionsAndPages` checks `c[0]`.

**`OntologyService.ts`**
- Constructor: `constructor(repos: RepositoryFor = repositoryFor, clientFactory = () => OntologyClient.fromEnv(), graphsFor = (r: QualificationRepository) => new KnowledgeGraphStore(r))`.
- Signatures stay: `build(project, id)`, `patchNode(project, id, nodeId, change)`, `resetPatch(project, id)`. Each resolves `repo = await this.repos(project)` and calls `repo.find(id)`.
- `assertLatestCard(project, systemId)` stays (the platform answers it, on the person path).

**`QualificationService.ts`**
- Constructor: `constructor(repos: RepositoryFor | QualificationRepository = repositoryFor, parser, platform)`. A plain object is wrapped as `async () => repos`, which keeps the construction in `cardSubmission` and `cardVersionsInCoreSystem` unchanged.
- `createFromForm(project, fd)` calls `repo.create({ ...parsed, systemId: version.pid })` with no `projectId`, and returns `{ id, projectId: version.project_id }`.
- `versionsAndCards` calls `(await this.repos(project)).list()`.
- `standing(project, card: { systemId: string })`, `list(project)`, `get(project, id)`.

**`cardLatest.ts`:** delete `isLatestCardInDb`; the agent path uses `repo.isLatest(systemId)`. Keep `NOT_LATEST`, `NotLatestError`, `isLatestCard` and `assertLatestCard`.

**`FillerClient.ts`**
- `request(project: string, qualificationId: string): Promise<boolean>` posts to `${serviceUrl}/fill/${encodeURIComponent(project)}/${encodeURIComponent(qualificationId)}`.
- `export async function requestFill(project: string, qualificationId: string)` has `length === 2`.

#### 3.6 Routes

**Delete** `src/app/api/qualifications/` (7 route files).

**Create** `src/app/p/[project]/api/qualifications/[id]/{ai-card.json,ai-card.pdf,system-card.pdf,ontology.jsonld,ontology.ttl,fill,extracted}/route.ts`. Params are `Promise<{ project: string; id: string }>`.

- **`ai-card.json`, `ai-card.pdf`, `ontology.jsonld`, `ontology.ttl`**
  1. `const db = await projectDbForRoute(project, { write: false })`; if it is a `Response`, return it.
  2. `const repo = new QualificationRepository(db)`; `repo.cardSummary(id)`, 404 when absent.
  3. Then the existing body, with `ontologyService.build(project, id)` and `knowledgeGraphStore.deliver(id, fmt, () => ontologyService.build(project, id), project)`.
- **`system-card.pdf`:** `export { GET } from "../ai-card.pdf/route";`
- **`fill` (GET)**
  1. Door (read), then `cardSummary(id)`, 404 when absent.
  2. `fetch(\`${AGENT_SERVICE_URL}/fill/${project}/${id}\`, { headers: serviceTokenHeaders(process.env.QUALIFICATION_WEB_TO_AGENTS_TOKEN), cache: "no-store" })`.
  3. Idle fallbacks as today.
- **`extracted`**
  - Keep `agentCall(req)`, which is the only reader of `QUALIFICATION_AGENTS_TO_WEB_TOKEN`: 401 when wrong, 503 when unset.
  - **GET:** the agent gets `projectDbForService(project)`, a person gets `projectDbForRoute(project, {write:false})`. Then `repo.find(id)`, 404 when absent. Return `{ ...toExport(q), extracted: q.ontologyExtracted ?? null, projectId: project.toLowerCase() }`. The project comes from the database, never from the query string.
  - **PUT:** the agent gets `projectDbForService`, a person gets `projectDbForRoute(project, {write:true})` (a viewer gets 403 JSON `REFUSED[403]`).
    1. `cardSummary(id)`: 404 when absent.
    2. Latest check: the agent uses `repo.isLatest(systemId)`, a person uses `isLatestCard(project, systemId)`. Not latest gives 403 `NOT_LATEST`.
    3. Parse: 400 when the body is not JSON, 422 when it fails validation.
    4. `repo.saveOntologyExtracted(id, value)`, then `try ontologyService.build(project, id)`.
    5. `revalidatePath(\`/p/${project}/qualify/${id}\`)`.
- **`src/app/p/[project]/api/system-versions/[systemPid]/ontology.jsonld/route.ts` (change)**
  1. If `systemPid` does not match `PROJECT_ID`, return 404.
  2. Door (read).
  3. `new QualificationRepository(db).findBySystem(systemPid)`, 404 when absent. The comparison with `card.projectId` goes: a version outside this database is simply not found.
  4. `knowledgeGraphStore.deliver(card.id, "jsonld", () => ontologyService.build(project, card.id), project)`, 502 on error.

#### 3.7 Actions, pages, components

**`qualify/[id]/ontology-actions.ts`**
- `loadOntology(project, id)`:
  1. `const d = await projectDbForAction(project, {write:false})`; if it carries an error, return `{ok:false, error: d.error}`.
  2. `new QualificationRepository(d.db).cardSummary(id)`; when absent, return `REFUSED[404]`.
  3. `ontologyService.build(project, id)`, with exactly two arguments.
- `patchOntologyNode` and `resetOntology` do the same with `{write:true}`, calling `ontologyService.patchNode(project, id, nodeId, change)` and `ontologyService.resetPatch(project, id)`.
- Revalidate `\`/p/${project}/qualify/${id}\``.
- The first parameter is renamed from `_clientProject` to `project`: it now names the database to open, and the platform is asked about that same pid.

**`qualify/[id]/component-actions.ts`:** `latestCard(project, id)` does the write door, then `cardSummary`, then `assertLatestCard(project, systemId)`. Then `engineClient.components(project)`, then `repo.linkComponent` or `unlinkComponent`, and `revalidatePath(\`/p/${project}/qualify/${id}\`)`.

**`qualify/new/actions.ts`**
- `const d = await projectDbForAction(project, {write:true})`.
- If `d.status === 503`, return `{error: PLATFORM_SILENT}`, the local string "The platform did not answer; nothing was saved".
- Any other error returns `{error: d.error}`.
- Then `createFromForm`, the same error mapping as today, then `await requestFill(project, id)` (the regex `requestFill\(\s*project\s*,\s*id\s*\)` must match), then the redirect.
- Remove the `projectForWriter` import.

**`qualify/[id]/page.tsx`**
- `.standing(project, { systemId: q.systemId })` and `loadEngineComponents(project)`.
- Downloads become `${basePath}/p/${project}/api/qualifications/${q.id}/{ai-card.pdf,ai-card.json,ontology.jsonld}`.
- `<FillStatus qualificationId={q.id} statusUrl={\`${basePath}/p/${project}/api/qualifications/${q.id}/fill\`} />`

**`FillStatus.tsx`:** the new prop `statusUrl: string`, and `fetch(statusUrl, { cache: "no-store" })`. No `api/qualifications/` literal remains in the file.

**`system/page.tsx`:** `engineClient.components(project)`.

**Delete:** `src/lib/prisma.ts` and `src/server/access/qualificationAccess.ts`. `callerAccess` moves to `projectDb.ts`.

#### 3.8 Prisma schema and the baseline migration

**`prisma/schema.prisma`:** remove the `projectId` field and `@@index([projectId])` from `Qualification`. Update its comment: the version is a row of `project.system` in this project's database. Keep `url = env("DATABASE_URL")` for the CLI (S-D6).

**Delete these 16 directories** under `prisma/migrations/`, keeping `migration_lock.toml`:
- 20260430105826_add_qualification
- 20260430112359_add_system_card
- 20260430115050_add_taxonomy_and_pdf
- 20260430120000_multi_tags
- 20260430140000_keycloak_drop_passwordhash
- 20260602000000_drop_auth_open_app
- 20260910120000_add_risks_and_airo_fields
- 20260910180000_add_ontology_columns
- 20260914150253_add_ontology_versions
- 20260914151848_knowledge_graph_per_system
- 20260921233000_qualification_of_a_project_and_a_system
- 20260922100000_the_links_are_named_project_id_and_system_id
- 20260922110000_one_naming_convention
- 20260923180000_one_ai_card_per_system_version
- 20260923210000_card_versions_point_at_core_system
- 20260924120000_a_card_is_of_a_version_of_its_project

**Create `prisma/migrations/20260926000000_project_database/migration.sql`:** the end state of those 16, written directly (not as renames), minus `project_id`, its index and its keys. The check is the I3.7 catalog diff against `scripts/tests/fixtures/isolation/live_shape.sql`, which compares names, types, defaults and function bodies exactly.

Rules for the file:
- Qualify every name with its schema.
- No line may contain the text `core.` or `project_id`, comments included. Watch words such as "score.".
- No `BEGIN`/`COMMIT`.
- No extra functions: I3.7 compares the list of functions.

```sql
CREATE TABLE qualification.qualification (
  id text NOT NULL, "systemName" text NOT NULL, "systemVersion" text NOT NULL, company text NOT NULL,
  description text NOT NULL, "targetUseCase" text NOT NULL, "targetUsers" text NOT NULL,
  created_at timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at timestamptz(3) NOT NULL,
  "systemCard" text, system_card_at timestamptz(3), "systemCardJson" jsonb, "systemCardPdfPath" text,
  "targetSystemTags" text[] DEFAULT ARRAY[]::text[], "sectorTags" text[] DEFAULT ARRAY[]::text[],
  "marketFormTags" text[] DEFAULT ARRAY[]::text[], "localityTags" text[] DEFAULT ARRAY[]::text[],
  "intendedDeployers" text, "ontologyExtracted" jsonb, "ontologyPatch" jsonb, ontology_at timestamptz(3),
  system_id uuid NOT NULL,
  CONSTRAINT "Qualification_pkey" PRIMARY KEY (id),
  CONSTRAINT qualification_system_id_fkey FOREIGN KEY (system_id) REFERENCES project.system (pid) ON DELETE CASCADE);
CREATE UNIQUE INDEX qualification_system_id_key ON qualification.qualification (system_id);

CREATE TABLE qualification.qualification_answer (id text NOT NULL, "qualificationId" text NOT NULL,
  "toolId" text NOT NULL, "questionId" text NOT NULL, answer text NOT NULL,
  CONSTRAINT "QualificationAnswer_pkey" PRIMARY KEY (id),
  CONSTRAINT "QualificationAnswer_qualificationId_fkey" FOREIGN KEY ("qualificationId")
    REFERENCES qualification.qualification (id) ON UPDATE CASCADE ON DELETE CASCADE);
CREATE INDEX "QualificationAnswer_qualificationId_toolId_idx" ON qualification.qualification_answer ("qualificationId", "toolId");
CREATE UNIQUE INDEX "QualificationAnswer_qualificationId_questionId_key" ON qualification.qualification_answer ("qualificationId", "questionId");
-- (the forms migration drops that last index by this exact name)

CREATE TABLE qualification.qualification_risk (id text NOT NULL, "qualificationId" text NOT NULL,
  "position" integer NOT NULL, risk text NOT NULL, source text NOT NULL, vulnerability text,
  consequence text NOT NULL, affected text NOT NULL, "impactAreas" text[] DEFAULT ARRAY[]::text[],
  control text NOT NULL, "followUpControl" text,
  CONSTRAINT "QualificationRisk_pkey" PRIMARY KEY (id),
  CONSTRAINT "QualificationRisk_qualificationId_fkey" FOREIGN KEY ("qualificationId")
    REFERENCES qualification.qualification (id) ON UPDATE CASCADE ON DELETE CASCADE);
CREATE INDEX "QualificationRisk_qualificationId_idx" ON qualification.qualification_risk ("qualificationId");

CREATE TABLE qualification.knowledge_graph (id text NOT NULL, "qualificationId" text NOT NULL,
  digest text NOT NULL, turtle text NOT NULL, jsonld text NOT NULL, stamp text[] DEFAULT ARRAY[]::text[],
  nodes integer NOT NULL, triples integer NOT NULL, built_at timestamptz(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "KnowledgeGraph_pkey" PRIMARY KEY (id),
  CONSTRAINT "KnowledgeGraph_qualificationId_fkey" FOREIGN KEY ("qualificationId")
    REFERENCES qualification.qualification (id) ON UPDATE CASCADE ON DELETE CASCADE);
CREATE UNIQUE INDEX "KnowledgeGraph_qualificationId_key" ON qualification.knowledge_graph ("qualificationId");

-- card_component: step 6 of 20260923210000 VERBATIM (table with inline PK/FK/CHECK, its two indexes)

CREATE FUNCTION qualification.card_is_latest(version_pid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM project.system s
     WHERE s.pid = version_pid
       AND s.number = (SELECT max(o.number) FROM project.system o));
END $$;
-- qualification_only_latest_changes(), answer_only_latest_changes(), component_only_latest_changes()
-- and the three triggers: steps 4, 5 and 6 of 20260923210000 VERBATIM (bodies are compared exactly)

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['report_ro', 'dashboard_ro'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT SELECT ON qualification.qualification, qualification.qualification_answer, '
        'qualification.qualification_risk, qualification.knowledge_graph, qualification.card_component TO %I', r);
    END IF;
  END LOOP;
END $$;
```

No grant on `_prisma_migrations`, no default privileges, and no schema USAGE grant (that one comes from P1's 0007).

#### 3.9 Scripts

**`scripts/projectDb.mjs` (create):** `PROJECT_ID`, `projectDatabaseName(pid)` and `projectDatabaseUrl(pid, template)`, following the same rule as the TypeScript module. The `.mjs` scripts cannot import the TypeScript file.

**`scripts/migrate-projects.mjs` (create):**
- It must contain the literal `^project_[0-9a-f]{32}$`.
- It must not read `DATABASE_URL`: no `process.env.DATABASE_URL`, no `env.DATABASE_URL`, and no `delete env.DATABASE_URL`.
- Steps:
  1. `template = process.env.PROJECT_DATABASE_URL`. If it has no `{database}`, log and exit 2.
  2. List the databases with `new PrismaClient({ datasourceUrl: <template with {database}=postgres, query stripped> })` and the query `SELECT datname FROM pg_database WHERE NOT datistemplate AND datallowconn AND has_database_privilege(current_user, datname, 'CONNECT')`. Filter by the regex and sort. If listing fails, exit 1 (the compose loop retries).
  3. For each database, run `execFileSync("npx", ["prisma","migrate","deploy"], { stdio: "inherit", env: { ...process.env, DATABASE_URL: <url> } })`. Collect failures and keep going.
  4. Exit 2 if any database failed, else 0.
- `FORM_LIBRARY_DATABASE_URL` is ignored in Q1 (Q2 adds the library step).

**`scripts/seed_mcas.mjs` (change)**
- `seedMcas` writes `systemId` only, with no `projectId`.
- The CLI takes a pid (`argv[2]` or `SEED_PROJECT`) and refuses a slug with a clear message.
- It opens `new PrismaClient({ datasourceUrl: projectDatabaseUrl(pid, process.env.PROJECT_DATABASE_URL) })` from `./projectDb.mjs`.
- No bare `new PrismaClient()`.

**`scripts/export_qualification.mjs` (change):** takes `--project <pid>` and opens the same way.

**`scripts/seed_examples.mjs`:** leave it. It has been unable to create a card since WP3 (it never supplies a `systemId`). Report it; do not fix it.

#### 3.10 Environment, compose, Dockerfile

**`apps/qualification/env.development`:** delete `DATABASE_URL` and add:

```
PROJECT_DATABASE_URL=postgresql://qualification_rw:qualification_rw@postgres:5432/{database}?schema=qualification&connection_limit=2
FORM_LIBRARY_DATABASE_URL=postgresql://qualification_rw:qualification_rw@postgres:5432/platform?schema=form_library&connection_limit=2
```

These are the dev role passwords already in the file. Update its comment.

**Top-level `docker-compose.development.yml`, service `qualification-migrate`:**

```yaml
command: >
  sh -c "until node scripts/migrate-projects.mjs; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[qualification] waiting for postgres'; sleep 2; done"
depends_on:
  - postgres
  - platform
```

`qualification-web` needs no change. Every token stays `:?` (I18.1).

**`apps/qualification/Dockerfile`:** change `CMD` to `["npx","next","start","-p","3000"]`. The old `prisma db push --accept-data-loss` would target `DATABASE_URL`.

#### 3.11 Agents (`services/agents`)

**`fill/clients.py`**
- `qualification(pid: str, qualification_id: str) -> dict` sends GET to `f"{APP_URL}/p/{quote(pid, safe='')}/api/qualifications/{quote(qid, safe='')}/extracted"`.
- `publish(pid: str, qualification_id: str, extracted: dict) -> dict` sends PUT to the same URL.
- Both keep `APP_TOKEN_VAR`.

**`agent.py`**
- Signature: `fill_one(pid: str, qualification_id: str, dry_run: bool = False) -> dict`. The parameter is named `pid`, not `project`, so `test_s3_7_fill_one_takes_no_project_from_its_caller` still holds.
- Body:
  1. `q = clients.qualification(pid, qid)`; `project = q.get("projectId")`.
  2. If `project` is set and `str(project).lower() != pid.lower()`, raise `clients.ServiceError`.
  3. `config_for(project, "card_agent")`.
  4. `publish = lambda qid, payload: clients.publish(pid, qid, payload)`, or the no-op when `dry_run`.
- CLI: `--qualification ID --project PID`.

**`service.py`**
- Routes:
  - `@app.post("/fill/{pid}/{qualification_id}", status_code=202) def start(pid: uuid.UUID, qualification_id: str, background)`
  - `@app.get("/fill/{pid}/{qualification_id}") def status(pid: uuid.UUID, qualification_id: str)`
- A non-uuid pid gets 422. The old `/fill/{id}` is gone (404/405).
- `def run_key(pid: str, qid: str) -> str: return f"{pid}/{qid}"`. `RUNS` is keyed by it, and each record carries `"project": str(pid)` and `"qualification": qid`.
- `_run(pid, qid)` calls `fill_one(pid, qid)`. Unknown runs are 404.

### 4. How to run (throwaway databases only; no live stack)

- **Unit:** from `apps/qualification`, `npx vitest run test/unit` and `npx tsc --noEmit`.
  - Baseline: 452 passed, 1 failed (`secrets.test.ts`, EISDIR). The new node_modules directory may change that one; report it.
- **DB:** from `apps/qualification`, `THROWAWAY_PREFIX=aisc-t-iso-Q bash test/db/throwaway-db.sh`. Needs P1. Baseline: 8 passed, 4 failed, 7 skipped.
- **Agents:** from a scratch directory,

  ```
  A=/home/listuser/aisc-isolation/apps/qualification/services/agents
  uv run --no-project --with-requirements $A/requirements.txt --with pytest --with httpx --with rdflib \
    python -m pytest -q -p no:cacheprovider -c $A/pytest.ini --rootdir $A $A/tests
  ```

  Baseline: 164 passed.
- **Top-level:** from the repo root,

  ```
  uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_compose.py scripts/tests/test_compose_isolation.py scripts/tests/test_service_tokens.py \
    scripts/tests/test_llm_keys.py
  ```

  Then `scripts/tests/test_project_grants.py -k qualification` after P1.

Always set every test DSN. The qualification harness sets its own; check no `aisc-t-*` container is left afterwards.

### 5. Tests that must change (named in the commit)

S-D13 named only the agents tests and the two `cardVersions*` DB tests. The unit tests in section 7 must change too.

**Agents tests:**
- `test_service.py`: the fake becomes `fake_fill(pid, qualification_id)`. Every `/fill/q1` becomes `f"/fill/{PID}/q1"` with a `PID = str(uuid.uuid4())` constant. Line 57 becomes `f"/fill/{PID}/never-heard-of-it"`. Line 75 becomes `service.RUNS[service.run_key(PID, "q1")]`. `runs` compares `(PID, "q1")`.
- `test_project_llm.py`:
  - Line 157: `lambda pid, qid: {...}`; line 159: `lambda pid, qid, payload: None`.
  - Line 180: `fake_fill(pid, qualification_id, dry_run=False, **extra)`, recording `(pid, qid, extra)`.
  - Lines 192, 199, 200, 205, 251 and 252: `/fill/{PID}/q1` and `/fill/{PID}/q9`.
  - `fill_one("q1")` becomes `fill_one(PID, "q1")` (lines 217, 242, 284); `fill_one("q-none")` becomes `fill_one(PID, "q-none")` (line 232).
  - Keep line 274 as it is, and reword its docstring.
- `test_service_token.py`: line 20 PROBES `f"/fill/{uuid}/q1"`. Line 86: `lambda pid, qid: runs.append((pid, qid)) or {}`. Lines 88 to 93 use the new path.
- `test_clients.py`: lines 48, 49 and 82 to 86 use `publish(PID, "q1", …)` and `qualification(PID, "q1")`, and the URL ends with `f"/p/{PID}/api/qualifications/q1/extracted"`. Line 101 becomes `qualification(PID, "q1")`. Update the line 54 comment.

**DB harness and tests:**
- `test/db/throwaway-db.sh`:
  - Delete lines 46 to 48, which migrate `platform?schema=qualification`. The new history cannot replay there, and with `set -e` it would abort the whole suite.
  - Provision a fifth pid, `ISO_F=ffffffff-0000-4000-8000-00000000000f`, in the same provision call, and migrate it with `DATABASE_URL=<F as qualification_rw ?schema=qualification> npx prisma migrate deploy`.
  - Repoint lines 89 to 91: `QUALIFICATION_TEST_DATABASE_URL`, `QUALIFICATION_TEST_ADMIN_URL` (superuser on `project_<F>` `?schema=qualification`) and `QUALIFICATION_TEST_PSQL` (`-d project_<F>`) all point at project F.
- `test/db/cardVersions.db.test.ts`: port it to project F.
  - Fixtures insert into `project.system (pid, number, name)`, and `card()` has no `projectId`.
  - Line 52 expects the target `project.system`.
  - Delete the "migration file refuses …" case (lines 117 to 140): that file is deleted by I3.5, and the FK now carries the guarantee (projectDatabase "I1.6 … refused").
  - The "deleting the project" case (lines 226 to 248) becomes "deleting a version removes its card, answers, risks, graph and components".
- `test/db/cardVersionOfItsProject.db.test.ts`: delete it. The composite key it pins is removed by I1.6 and I1.7. A version of another project is in another database, and the FK refusal is covered by `projectDatabase.db.test.ts`.

### 6. Commits (explicit paths, never push)

**Submodule `apps/qualification`, 1:** `Isolation Q1: the card agent works under /p/{pid} (fill paths, extracted paths, runs keyed by project and card)`
- `services/agents/{agent.py,service.py,fill/clients.py}`
- `services/agents/tests/{test_service.py,test_project_llm.py,test_service_token.py,test_clients.py}`

**Submodule `apps/qualification`, 2:** `Isolation Q1: one database per project for qualification (projectDb.ts, the door, routes under /p/{pid}, baseline migration, migrate-projects)`
- `src/lib/projectDb.ts`
- `src/middleware.ts`
- `src/server/access/projectAccess.ts`
- `src/server/repositories/QualificationRepository.ts`
- `src/server/services/{OntologyService,KnowledgeGraphStore,QualificationService,cardLatest,FillerClient}.ts`
- `src/app/p/[project]/api/**`
- `src/app/p/[project]/qualify/**/{page.tsx,FillStatus.tsx,ontology-actions.ts,component-actions.ts,actions.ts}`
- `src/app/p/[project]/system/page.tsx`
- `prisma/schema.prisma`
- `prisma/migrations/20260926000000_project_database/migration.sql`
- `scripts/{projectDb.mjs,migrate-projects.mjs,seed_mcas.mjs,export_qualification.mjs}`
- The test files of section 7, plus `test/db/{throwaway-db.sh,cardVersions.db.test.ts}`
- Removals with `git rm -r` of explicit paths: the 16 migration directories, `src/app/api/qualifications`, `src/lib/prisma.ts`, `src/server/access/qualificationAccess.ts` and `test/db/cardVersionOfItsProject.db.test.ts`.
- The message body names every changed test and why (the design changes the behaviour it pinned).

**Submodule `apps/qualification`, 3:** `Isolation Q1: qualification reads PROJECT_DATABASE_URL and FORM_LIBRARY_DATABASE_URL; the image no longer runs prisma db push`
- `env.development`, `Dockerfile`

**Top level:** `Isolation Q1: qualification-migrate runs migrate-projects.mjs after the platform, and the qualification gitlink`
- `docker-compose.development.yml`, `apps/qualification`

### 7. Existing unit tests stage 2 missed (they pin the old design; change and name them)

| file | what changes |
|---|---|
| `agentToken.test.ts` | Mock `@/lib/projectDb` (`projectDbForService`, `projectDbForRoute`) and a `QualificationRepository` class instead of `@/lib/prisma` (line 30) and `qualificationAccess` (31 to 35). Route `@/app/p/[project]/api/qualifications/[id]/extracted/route`, params `{project: OWN, id}`, URLs under `/p/OWN`. The agent's latest check uses `repo.isLatest`. Line 162 expects `src/app/p/[project]/api/qualifications/[id]/extracted/route.ts`. Keep every assertion's meaning: 401, 503, 404, no platform for the agent, database latest check. |
| `fillerReadsItsProject.test.ts` | New route path and mocks. `projectId` equals the path's pid, and the query is ignored. Lines 50 to 67: `requestFill.length === 2` and the URL `http://agents:8012/fill/${PID}/q1`. |
| `writeAccess.test.ts` | Lines 30 to 68 test `qualificationForWriter` and `projectForWriter` (module deleted): re-express the same editor, admin, viewer (403), stranger and silent cases against `projectDbForAction`. F6 (132 to 163): new path and mocks. F7 (165 to 248): the action now opens the database of the project it is given, after the platform confirms that project. A viewer of OTHER is refused, and an editor's patch goes to `patchNode(OTHER, …)`. Line 243: `submitQualification` is refused 403 when the door says 403. |
| `onlyLatestCardChanges.test.ts` | Mocks move to `@/lib/projectDb` and `repositoryFor`; the route path (lines 114 to 129) changes. The S3.3 and S3.4 assertions stay (`saveOntologyPatch("c2", …)` unchanged). |
| `serviceTokens.test.ts` | Line 48: `.request(PID, "q1")`. Lines 52 to 66: mock the door and repository, use the new fill route, URL `/fill/${PID}/q1`. Line 116: the new fill route path. |
| `systemVersionOntologyRoute.test.ts` | Mock the door instead of `@/lib/prisma` and `fetchAccess`. The "card belongs to another project" case becomes "no card for this version in this database" (still 404). Line 241: `deliver` is called with `("c2","jsonld",Function,PROJECT)`. |
| `qualificationScope.test.ts` | Lines 39 and 50 expect `where: { id: "qual-1" }`, calling `new QualificationRepository(db).find("qual-1")`. Lines 53 to 90 test `qualificationForCaller`, which is deleted: remove them. The isolationRoutes "stranger 404" cases cover the rule. |
| `cardSubmission.test.ts:66-68` | Expect `objectContaining({ systemId: "v2" })`, and `create`'s input has no `projectId`. |
| `cardVersionsInCoreSystem.test.ts` | Line 179 becomes "no `projectId`". The S3.6 action test (221 to 240) also mocks `@/lib/projectDb` so that `projectDbForAction` returns `{db}`; otherwise the non-pid `"mcas"` would call `notFound()`, which its navigation mock lacks. |
| `seedMcasVersions.test.ts:77` | Expect `toMatchObject({ systemId: V1.pid })`, and no `projectId` key. |
| `FillerTrigger.test.ts` | Lines 11, 13, 26, 35 and 44: `request(PID, "q1")` and URL `/fill/${PID}/q1`. |
| `FillStatus.test.tsx` | Every render passes `statusUrl`. |

### 8. Flagged tests (do not edit them in stage 4; the orchestrator decides)

- **F2.** `test/unit/isolationActionsAndPages.test.ts:119-135`. The `beforeEach` never calls `closeProjectDatabases`, which `isolationProjectDb.test.ts:82` does. With the cache that I3.1 and I17.1 require, B and A are already open from the earlier tests. So `openedB()` at line 220 (5 cases), `openedA()` at 229 and `openedB()` at 263 are false.
  - Fix: add `await (await load(join(SRC,"lib","projectDb.ts"))).mod?.closeProjectDatabases?.()` to that `beforeEach`.
  - The same line in `isolationRoutes.test.ts` would make that file order-independent too; it passes today only by order.
- **F3.** `services/agents/tests/test_isolation_paths.py:54`: `config_for` returns `{"provider": "fake"}`, but `fill_one` reads `config.provider` and `config.model`. The run fails, so line 111 (`state == "done"`) stays red.
  - Fix: return `types.SimpleNamespace(provider="fake", model="m")`.
- **F6.** These top-level harnesses migrate qualification into `platform`, and the new baseline cannot replay there, so they go red after Q1:
  - `scripts/tests/test_card_version_keys_orders.py` (step `Q`, line 139)
  - `scripts/guard-frozen.sh:112` (`--orders`)
  - `scripts/test-pipeline-chain.sh:71-72`

  `test_card_version_keys_orders.py` pins the composite keys that I1.6 and I1.7 remove; it should be retired by V1 or X1, not weakened. The other two belong to V1 (I19.2).
- **R1 (risk, not a test bug).** In the I2.5 DB test, the first query after `DROP DATABASE … WITH (FORCE)` may fail with P1017 ("Server has closed the connection") instead of P1003. The probe in `$use` (section 3.2) handles that. If it still fails, report the actual error; do not change the test.

### 9. Ambiguities resolved

1. **Page reads use a door with no platform question.** The service test in `isolationActionsAndPages` gives the caller a stranger answer (`access = {}`) and still requires B's database to be opened. So `QualificationService.get` and `list` go through `projectDbPastDoor`; the middleware is the page's door. Actions and routes always use a door that asks the platform.
2. **The repository is bound to one project database** (`QualificationRepository(db)`, `repositoryFor(project)`). This keeps `KnowledgeGraphStore.test` untouched and makes "the database is the project" explicit.
3. **Middleware checks only that the agent's header is present,** because the edge runtime has no `node:crypto`. The route does the constant-time comparison.
4. **`migrate-projects.mjs` exits 2 when any project database fails,** as I3.6 says. This differs from controls, which exits 0. One broken project database will keep qualification-web from starting.
5. **Databases are listed through a Prisma raw query on the `postgres` database.** qualification has no `pg` dependency.
6. **`schema=qualification` and `connection_limit=2` are always forced** onto the database URL.
7. **The seed CLI takes a pid only.**
8. **`/extracted` returns `projectId` as the lowercase path pid.**
9. **Agent runs are keyed `"{pid}/{qid}"`.**
10. **ASSUMED: the worktree gets its own `node_modules` directory** (section 2), so the local Prisma client can be regenerated.
11. **`createFromForm` does not compare `version.project_id` with the project.** The FK to this database's `project.system` refuses a foreign version, and adding the comparison would break two existing tests.

---


---

## WP O1: control objectives on one database per project

### Plan overrides (read first; they win over the text below)

- **G1**: section O1.7 (compose) is W1's; O1 does not edit or commit `docker-compose.development.yml`, and its
  third commit is only the gitlink `apps/control-objectives` ("Isolation O1: control-objectives gitlink").
- **W-6**: `test_api_auth.py:404` is rewritten in place on the two-database fixtures (the first option of O1.8,
  exception 1), not deleted.
- `tests/test_chain.py` of control objectives is V1's (pipeline chain, G2); O1 leaves it.

**Repo:** `/home/listuser/aisc-isolation/apps/control-objectives` (worktree, branch `isolation/2026-09-25`), plus `docker-compose.development.yml` in the top-level repo.
**Depends on:** P1 (templates 0006, 0008). The tests carry a stand-in (`isolation_support.stand_in_for_missing_template`), so O1 can be built and turned green before P1 lands.
**Requirements:** I1.1, I1.6, I1.7, I1.8, I2.5, I2.6 (control_objectives rows), I5.1 to I5.7, I16.5, I17.1, I18.2, I18.3, I18.7.

### O1.1 Tests this WP turns green

`tests/test_isolation_static.py` (no database):
- `test_I1_8_the_example_pid_names_its_database`
- `test_I1_8_I5_2_anything_but_a_pid_never_becomes_a_database_name` (9 parameters)
- `test_I5_1_create_engine_appears_only_in_projectdb`
- `test_I5_1_the_door_is_ProjectDatabases_open`
- `test_I5_3_the_repository_reads_project_system_not_core`
- `test_I5_3_I1_7_the_assessment_has_no_project_id_column`
- `test_I5_1_nothing_in_src_names_core_system`
- `test_I5_4_one_baseline_revision`
- `test_I5_4_no_revision_names_core`
- `test_I5_4_the_baseline_points_system_id_at_project_system`
- `test_I5_4_env_sets_the_search_path_to_its_own_schema_only`
- `test_I5_5_migrate_projects_is_a_module_with_main`
- `test_I5_2_no_route_under_the_old_api_projects`
- `test_I5_2_the_json_api_is_under_the_project` (5 parameters)
- `test_I5_2_the_public_catalogue_routes_stay` (a guard that must stay green)
- `test_I5_7_the_drop_and_recreate_fixture_refuses` (4 parameters)

`tests/test_isolation_project_databases.py` (30 tests, all of them):
- **Placement:** `test_I1_1_I5_1_an_assessment_is_written_into_its_projects_database`, `test_I5_3_I1_6_I1_7_the_assessment_table_in_a_project_database`, `test_I5_4_the_database_is_at_the_baseline_and_readers_get_their_reads`
- **Cross-project and routes:** `test_I16_5_I5_2_an_assessment_of_A_under_Bs_pid_is_404_on_every_route`, `test_I16_5_the_same_by_slug_and_for_an_admin`, `test_I16_5_a_list_shows_only_its_own_projects_assessments`, `test_I5_2_the_old_api_projects_paths_are_404`, `test_I5_2_a_slug_opens_the_same_database_as_the_pid`, `test_I5_2_I5_1_a_project_that_does_not_exist_is_404_without_a_database`
- **Auth mirrors (I18.2):** `test_I18_2_every_moved_route_is_401_without_a_token`, `test_I18_2_no_variant_of_a_moved_path_answers_without_a_token`, `test_I18_2_no_variant_shows_a_stranger_the_assessment`, `test_I18_2_a_viewer_reads_through_the_api`, `test_I18_2_I18_3_a_viewer_cannot_change_anything`, `test_I18_2_an_editor_may`, `test_I18_2_an_admin_may_without_being_a_member`, `test_I18_2_a_stranger_is_told_nothing_exists`, `test_I18_2_a_member_of_one_project_cannot_reach_anothers_by_id`, `test_I18_2_pages_open_by_pid_or_slug_and_behind_the_root_path`
- **Versions and mapper:** `test_I5_3_a_newer_version_in_project_system_makes_it_read_only`, `test_I5_3_a_start_with_a_version_not_in_project_system_stores_nothing`, `test_I5_6_the_mapper_resolves_its_llm_with_the_databases_pid`
- **Door, first open, pools:** `test_I5_1_a_stranger_or_a_viewers_write_never_opens_the_database`, `test_I5_1_membership_unknown_is_503_and_opens_nothing`, `test_I5_5_concurrent_first_requests_share_one_migration`, `test_I17_1_at_most_two_connections_per_project_and_two_to_platform`, `test_I17_1_at_most_twenty_project_databases_are_held_open`, `test_I2_5_I17_1_a_dropped_database_is_evicted_and_answers_404`
- **Migrate one-shot:** `test_I5_5_migrate_projects_upgrades_what_it_may_enter_and_skips_the_rest`, `test_I5_5_migrate_projects_exits_2_on_a_permanent_error`

`scripts/tests/test_compose_isolation.py` (top level):
- `test_i5_5_control_objectives_migrate_runs_migrate_projects`
- `test_i5_1_control_objectives_has_a_project_database_template[control-objectives]` and `[control-objectives-migrate]`
- `test_i16_4_every_module_dsn_names_a_project_database_except_the_allowed_platform_ones[control-objectives]` and `[control-objectives-migrate]`

Also consumed later: `scripts/tests/isolation_bed.py:215` runs `python -m aisc_control_objectives.migrate_projects` with `PYTHONPATH=apps/control-objectives/src` only, and `platform/tests/isolate_support.py:129` pins `NEW_ALEMBIC = "20260926000000_project_database"`.

### O1.2 Files

**Create:**
- `src/aisc_control_objectives/projectdb.py`
- `src/aisc_control_objectives/migrate_projects.py`
- `alembic/versions/20260926000000_project_database.py`
- `tests/test_migration_project_database.py` (replacement coverage, see O1.8)

**Change:**
- `src/aisc_control_objectives/db/tables.py`, `db/repository.py`, `projects.py`, `access.py`, `api/app.py`, `server.py`, `settings.py`
- `src/aisc_control_objectives/upstream.py` (docstring line 59 names `core.system`)
- `alembic/env.py`, `README.md` (the API table), `pyproject.toml` (optional `[project.scripts]`)
- Tests listed in O1.8

**Delete (git rm):**
- `alembic/versions/20260914171611_projects_graphs_risks_runs.py`
- `alembic/versions/20260914191531_drop_the_profile_run_and_the_answer.py`
- `alembic/versions/20260921220000_an_assessment_belongs_to_a_project.py`
- `alembic/versions/20260922100000_the_project_link_is_named_project_id.py`
- `alembic/versions/20260923210000_an_assessment_is_of_one_system_version.py`
- `alembic/versions/20260924120000_an_assessment_is_of_a_version_of_its_project.py`
- `tests/test_migration_assessment_of_a_version.py`, `tests/test_migration_card_version_of_its_project.py`
- Also remove the untracked `alembic/versions/__pycache__/`.

**Top level:** `docker-compose.development.yml` (the two control-objectives services).

### O1.3 `projectdb.py`: the only module that contains `create_engine(`

```python
PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
APP_ROOT = Path(__file__).resolve().parents[2]          # /app in the image, apps/control-objectives in tests
ALEMBIC_INI, ALEMBIC_DIR = APP_ROOT / "alembic.ini", APP_ROOT / "alembic"
MAX_OPEN_PROJECTS = 20

def database_name(pid: str) -> str
    # lower(); fullmatch PID else ValueError; "project_" + hex without hyphens

def make_engine(url: str, **kwargs) -> Engine
    # the ONE create_engine( call in src

def pooled_engine(url: str) -> Engine
    # make_engine(url, pool_size=2, max_overflow=0, pool_pre_ping=True, pool_timeout=30)

def project_url(template: str, database: str) -> str
    # template.replace("{database}", database)  (never str.format)

def migrate(engine: Engine) -> None
    # alembic Config(ALEMBIC_INI), script_location=ALEMBIC_DIR;
    # with engine.begin() as c: config.attributes["connection"] = c; command.upgrade(config, "head")

def is_missing_database(exc: BaseException) -> bool
    # orig.sqlstate == "3D000", or re.search(r'database "[^"]+" does not exist', str(orig))

def may_not_connect(exc: BaseException) -> bool
    # sqlstate "42501", or "permission denied for database" in the message

class ProjectDatabaseGone(LookupError): ...

class Refused(Exception):
    verdict: Verdict            # "not-found" | "forbidden" | "unavailable"

@dataclass(frozen=True)
class Opened:
    pid: str
    database: str
    engine: Engine
    access: Access

class ProjectDatabases:
    def __init__(self, platform_url: str, project_url_template: str, *,
                 capacity: int = MAX_OPEN_PROJECTS,
                 migrate: Callable[[Engine], None] = migrate): ...
    @property
    def platform(self) -> Engine: ...   # pooled_engine(platform_url), created lazily, never connects at build
    def open(self, project: str, caller, write: bool) -> Opened: ...
    def evict(self, pid_or_database: str) -> None: ...
    def dispose(self) -> None: ...
```

`open(project, caller, write)` runs in this order, and nothing connects to a project database until step 4:
1. `access = access_for(self.platform, project, caller)`. Admin gives owner without a query; a failed membership read gives `None`.
2. `verdict = decide("POST" if write else "GET", access)`. If it is not `"allow"`, raise `Refused(verdict)`.
3. `pid = project_pid(self.platform, project)`. A `SQLAlchemyError` raises `Refused("unavailable")`; `None` raises `Refused("not-found")`. This is how a slug is resolved (I5.2) and how an admin asking for a ghost pid gets 404.
4. `name = database_name(pid)`, then the engine:
   - Take it from an `OrderedDict` LRU under a `threading.Lock` (`move_to_end` on a hit).
   - On a miss, take a per-name `threading.Lock`, check again, create `pooled_engine(project_url(template, name))`, and run `self._migrate(engine)` once.
   - If that fails and `is_missing_database`, dispose the engine and raise `ProjectDatabaseGone`. Any other error propagates.
   - Insert the engine. While `len > capacity`, pop the oldest and `dispose()` it.
5. Return `Opened(pid, name, engine, access)`.

**Import rule:** import `aisc_control_objectives.access` lazily inside `open()`. `access.py` imports `aisc_identity`, which is not on the path of the migrate container or of `isolation_bed` (PYTHONPATH is src only). The subprocess in `test_I5_5_*` needs this too.

### O1.4 Other source changes

**`settings.py`**
- `database_url()` is unchanged: the `platform` database, used for membership only.
- Add `project_database_url(env=None) -> str`:
  - Read `PROJECT_DATABASE_URL`.
  - If it is unset, derive it from `database_url(env)` by replacing the database with `{database}`. `test_project_llm.py::built` sets only `DATABASE_URL`.
  - Normalise `postgresql://` to `postgresql+psycopg://` and strip `?…`.
  - Raise `ValueError` without `{database}`.

**`db/tables.py`**
- Remove `_core_table`, `core_project` and `core_system`.
- Add an external table: `project_system = Table("system", Base.metadata, Column("pid", UUID(as_uuid=False), primary_key=True), Column("number", Integer), schema="project", info={"external": True})`.
- On `Project`:
  - Drop `project_id` and the composite `ForeignKeyConstraint`.
  - `system_id = mapped_column(UUID(as_uuid=False), ForeignKey("project.system.pid", ondelete="CASCADE", name="fk_project_system_id_project_system"), nullable=False)`.
  - `__table_args__ = (UniqueConstraint("system_id", name="uq_project_system_id"),)`. Do not also pass `unique=True`: the DB test counts exactly one unique index.
- `Graph`, `Risk`, `MappedObjectiveRow` and `MappingRunRow` are unchanged. Their `project_id` is the assessment id, not the platform project.
- Fix the comments that name `core.`.

**`db/repository.py`**
- Constructor: `ProjectRepository(url_or_engine: str | Engine, objectives_digest: str = "", *, pid: str | None = None)`.
  - A str becomes `projectdb.make_engine(url, pool_pre_ping=True)`; keep `self._url` (test_s7_7 uses `repository._url`).
  - An Engine is used as given.
  - Keep the `engine` property, `pid` and `reopened()`.
- `_VERSION_NUMBERS = text("SELECT s.number, (SELECT max(o.number) FROM project.system o) FROM project.system s WHERE s.pid::text = :sid")`.
- `has_version(system_id: str) -> bool`: `SELECT 1 FROM project.system WHERE pid::text = :sid`.
- `create(self, project, name, ontology, jsonld, *, system_id)`: keep the `project` parameter so call sites stay valid (test_api_auth's `assessment` fixture), but do not store or validate it (I1.7). The docstring says the database is the project.
- `list(self) -> list[ProjectRecord]`: no parameter, no filter, `ORDER BY updated_at DESC`.
- `_to_record` sets `ProjectRecord.project = self._pid`. Make it an instance method or pass the pid in.

**`projects.py`**
- `Projects(repository: ProjectRepository | None, catalogue, mapper, model="", mapper_for=None)`. In `server.build_app` keep keyword arguments; `test_project_llm.py::built` captures `model=` and `mapper_for=`.
- Add `bound(self, repository) -> Projects`: `copy.copy(self)` with `_repository` replaced, so a monkeypatched subclass is not re-initialised.
- Add `has_version(system_id)`.
- `list()` takes no parameter.
- `map_risks_of` still calls `mapper_for(record.project)`. That is now the database's pid (I5.6).
- Fix the docstring at line 85.

**`access.py`** (the `ProjectAccess` gate)
- New constructor: `ProjectAccess(app, engine, databases: ProjectDatabases | None = None)`.
- The order stays: public path, then 401 (`caller_from_headers`), then under `/p/`.
- With `databases`: `opened = await run_in_threadpool(databases.open, project, caller, request.method.upper() not in SAFE_METHODS)`.
  - `Refused` maps through `REFUSALS`.
  - `ProjectDatabaseGone` answers 404 "No such project.".
  - On success set `request.state.opened = opened`.
- Without `databases` (single-database mode, used only by the existing domain tests): today's `access_for` and `decide`, also in the threadpool.
- For route paths matching `^/p/[^/]+/api(?:/|$)`, return refusals as `JSONResponse({"detail": message}, status)` instead of plain text. `test_api_auth::test_a_stranger_is_told_nothing_exists` compares `response.json()["detail"]` of two gate refusals. The other paths stay plain text.

**`api/app.py`**
- Signature: `create_app(objectives, projects, *, base_config=None, root_path="", cors_origins=None, source_name=..., engine=None, databases=None)`.
- `databases` without `engine` raises `ValueError`.
- Add the gate with `ProjectAccess(app, engine=engine, databases=databases)` when `engine` is set.
- `_projects_of(request)`: return `projects` when `request.state` has no `opened`; otherwise `projects.bound(ProjectRepository(opened.engine, objectives_digest=objectives.digest, pid=opened.pid))`.
- `_view_in` and `_view_of` both become "view in this database or 404 (`detail=f"Unknown project {id}"`)". Drop the `record.project` and `project_pid` cross-check: in deployed mode the database decides.
- Routes. The old `/api/projects*` routes are removed; they now answer 404 with a token and 401 without.

  | method | path | status codes |
  |---|---|---|
  | GET | `/p/{project}/api/projects` | 200 (list of payloads) |
  | GET | `/p/{project}/api/projects/{project_id}` | 200 or 404 |
  | POST | `…/{project_id}/map` | 200, 404, 409 (read-only), 502 (model unavailable); the gate gives 403 |
  | POST | `…/{project_id}/severity` (`Body dict[str,int]`) | 200, 404, 409, 422 |
  | DELETE | `…/{project_id}` | 204 or 404 |

- Pages keep their paths. The start form (`POST /p/{project}/projects`) changes as follows:
  - `_latest_version(opened.pid if opened else project, auth)`.
  - After `_card_of`: if `not projects_.has_version(latest["pid"])`, answer 409 "The latest version is not in this project's database." and store nothing.
  - Catch `IntegrityError`: a foreign-key violation (`orig.sqlstate == "23503"`) answers the same 409; a unique violation keeps today's "started twice" path.
- Home page: `len(_projects_of(request).list())`.
- With `databases`, register `@app.exception_handler(sqlalchemy.exc.DBAPIError)`:
  - If `projectdb.is_missing_database(exc)`, call `databases.evict(request.state.opened.pid)` and answer 404 "No such project." (JSON under `/api`). This is I2.5.
  - Otherwise log it and answer 500.
  - Project engines use `pool_pre_ping=True`, so the first request after `DROP DATABASE … WITH (FORCE)` sees 3D000.
- Optional: a shutdown handler that calls `databases.dispose()`.

**`server.py`**
- `build_app()` builds `databases = ProjectDatabases(settings.database_url(), settings.project_database_url())`.
- It builds `projects = Projects(repository=None, catalogue=objectives, mapper=RiskMapper(...), model=..., mapper_for=mapper_for)`.
- It returns `create_app(..., engine=databases.platform, databases=databases)`.
- Keep `_build_completer`, `RiskMapper` and `baf_llm.config_for` as module-level names looked up at call time; `isolation_support` patches them.
- Import `ProjectDatabases` into `server` (the changed `test_build_app_fits_the_gate` patches it).
- Update the env docstring: `DATABASE_URL` is platform (membership), `PROJECT_DATABASE_URL` is the `{database}` template.

### O1.5 Alembic

**`alembic/env.py`**
- If `context.config.attributes.get("connection")` is set, use it and never commit it.
- Otherwise read the URL from `context.get_x_argument(as_dictionary=True).get("url")`. If there is none, stop with "runs per project database: python -m aisc_control_objectives.migrate_projects". Refuse a URL whose database is `platform`. Then use `projectdb.make_engine(url, poolclass=NullPool)` with `engine.begin()`.
- On the connection, in this order:
  1. `SELECT pg_advisory_xact_lock(hashtext('aisc_control_objectives.alembic'))`, so the app and the one-shot never migrate together.
  2. If the schema is missing: `CREATE SCHEMA` only when `has_database_privilege(current_user, current_database(), 'CREATE')`. Otherwise raise "schema control_objectives is missing: platform template 0008 not applied".
  3. `connection.execute(text(f"SET search_path TO {SCHEMA}"))`.
  4. `context.configure(connection=..., target_metadata=Base.metadata, version_table_schema=SCHEMA, include_schemas=True, include_object=_include_object)`.
  5. `with context.begin_transaction(): context.run_migrations()`.
- The string `SET search_path TO` must appear only in that one call, not in the docstring or comments: the test regex captures every occurrence.

**`alembic/versions/20260926000000_project_database.py`**
- Header: `revision = "20260926000000_project_database"` (31 characters, fits `varchar(32)`, equals `isolate_support.NEW_ALEMBIC`) and `down_revision = None`.
- The docstring says `system_id` references `project.system(pid)` ON DELETE CASCADE.
- **No `core.` substring anywhere in the file** (also avoid words like "score.").
- `upgrade()` is today's live shape minus `project_id`. Use Postgres default names for everything not named here, so the names match live.
  - **project:** `id varchar(32)` PK `project_pkey`, `name text NN`, `objectives_digest varchar(64) NN`, `created_at timestamptz NN`, `updated_at timestamptz NN`, `system_id uuid NN`; `UniqueConstraint("system_id", name="uq_project_system_id")`. Then `op.create_foreign_key("fk_project_system_id_project_system", "project", "system", ["system_id"], ["pid"], referent_schema="project", ondelete="CASCADE")`. There is no `project_id`, no `ix_project_project_id` and no key into the platform: this must be the table's only FK (the test asserts `[("project.system","c")]`).
  - **graph:** `project_id varchar(32)` PK and FK to `project.id` CASCADE, `jsonld text NN`, `digest varchar(64) NN`, `risks int NN`, `uploaded_at timestamptz NN`.
  - **mapping_run:** `project_id varchar(32)` PK and FK CASCADE, `findings jsonb NN`, `stops jsonb NN`, `stop text NN`, `attempts int NN`, `error text NN`, `model text NN`, `ran_at timestamptz NN`.
  - **risk:** `id` serial PK (sequence `risk_id_seq`), `project_id varchar(32) NN` FK CASCADE, then `risk_id`, `position`, `text`, `short_label`, `source`, `vulnerability`, `consequence`, `impact`, `stakeholder`, `control`, `follow_up_control` (text or int NN, as today), `areas text[] NN`, `vair_terms text[] NN`, `provenance text NN`, `severity int` NULL; `UNIQUE(project_id, risk_id)`; `op.f("ix_risk_project_id")`.
  - **mapped_objective:** `id` serial PK, `risk_row_id int NN` FK to `risk.id` CASCADE, `objective_id`, `quote`, `rationale text NN`; `UNIQUE(risk_row_id, objective_id)`; `op.f("ix_mapped_objective_risk_row_id")`.
  - **Reader grants (I2.6),** issued by the owner (the migrating role). No grant on `alembic_version` or on sequences.

    ```sql
    DO $$ DECLARE r text; BEGIN
      FOREACH r IN ARRAY ARRAY['report_ro','dashboard_ro'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
          EXECUTE format('GRANT SELECT ON control_objectives.project, control_objectives.graph,
            control_objectives.risk, control_objectives.mapped_objective, control_objectives.mapping_run TO %I', r);
        END IF; END LOOP; END $$;
    ```
- `downgrade()` drops the five tables in reverse order.
- `alembic.ini` is unchanged apart from an optional comment.

### O1.6 `migrate_projects.py`

- `def main(argv: list[str] | None = None) -> int`, with `if __name__ == "__main__": raise SystemExit(main())`.
- Optional in `pyproject.toml`: `[project.scripts] control-objectives-migrate = "aisc_control_objectives.migrate_projects:main"`.
- Steps:
  1. Read `SELECT pid::text FROM core.project ORDER BY pid` through `pooled_engine(settings.database_url())`. If the platform is unreachable, return **1** (the compose loop retries).
  2. For each pid, build `make_engine(project_url(settings.project_database_url(), database_name(pid)), poolclass=NullPool)`, `connect()` once, and classify:
     - `is_missing_database` or `may_not_connect` at connect time: print `skip project_<hex>: <reason>` and continue.
     - The missing-schema error (template 0008 not yet applied): skip too; the app's first open migrates it later.
     - Otherwise run `projectdb.migrate(engine)`. Any error is permanent: print `FAILED project_<hex>: <sqlstate> <diag.message_primary>` and continue.
     - Always `dispose()`.
  3. Return **2** if any permanent failure, else **0**.
- **Never print a URL** or `str(exc)` with its `[SQL:]` block (I18.7). Do not import `access` or `aisc_identity`.

### O1.7 Compose (top-level `docker-compose.development.yml`)

- **`control-objectives-migrate`:**
  - `command: sh -c "until python -m aisc_control_objectives.migrate_projects; do s=$$?; [ $$s -eq 2 ] && exit 2; echo '[control-objectives] waiting for postgres'; sleep 2; done"`
  - `environment`: keep `DATABASE_URL` (platform, allowed by I16.4) and add a literal `PROJECT_DATABASE_URL: postgresql://control_objectives_rw:control_objectives_rw@postgres:5432/{database}`. Do not wrap it in `${…:-…}`: nested braces are risky in compose interpolation.
  - `depends_on: [postgres, platform]`.
- **`control-objectives`:** add the same `PROJECT_DATABASE_URL`, and update the header comment (the tables are in each project database).

### O1.8 Existing tests that must change (S-D13, with the reason: the approved design removes `project_id` and moves routes)

**`tests/conftest.py`**
- `database_url` fixture: parse the database name. If it is `platform` or `postgres`, or starts with `project_`, call `pytest.fail(f"refusing to drop and recreate database {name!r} …", pytrace=False)` **before any connection** (I5.7).
- Recommended hardening: also refuse port 5432 and an unset variable. Today the default URL points at `localhost:5432`, which is the live Postgres.
- `CORE_PROJECT_DDL`: keep `core.project` and `core.project_member` (membership stand-in for single-database `create_app(engine=…)` tests). Remove `core.system`. Add `CREATE SCHEMA project; CREATE TABLE project.system (…I1.5 columns…)`.
- `repository`: generate `pid = str(uuid4())`, build `ProjectRepository(database_url, objectives_digest=…, pid=pid)`, run the DDL, then `create_all()`. On teardown, dispose the engine and drop the database.
- `platform_project`: insert the `core.project` row for `repository.pid` and return it.
- `system_version(project, number)`: `INSERT INTO project.system (pid, number, name)`, ignoring `project`. Each test uses unique numbers, which holds today.

**`tests/test_api_auth.py`** (paths, plus three named exceptions)
- Map every `/api/projects?project={pid}` to `/p/{pid}/api/projects` and every `/api/projects/{aid}…` to `/p/{pid}/api/projects/{aid}…`. This covers `_gated_routes`, `_bypass_variants` (use the `/p/{pid}/api/…` forms), `_risk_id` (give it a `pid` argument) and each case.
- In `test_a_stranger_is_told_nothing_exists`, the `startswith` condition and the unknown path become `/p/{pid}/api/projects/…`.
- In `test_a_member_of_one_project_cannot_reach_anothers_assessment_by_id`, use `/p/{theirs}/…`. The own-pid variant is mirrored in the new file.
- **Exception 1:** `test_a_page_refuses_an_assessment_of_another_project` cannot hold in the one-database fixture, because two projects share one database once `project_id` is gone. Rewrite it in place onto `isolation_support` (`Projects`, `deployed_app`, two real databases) with the same assertions (mine is an editor, theirs is the owner, 404 on GET, map and severity under mine and my slug, no rated risk in theirs), or delete it and point to `test_I16_5_I5_2_…` and `test_I18_2_a_member_of_one_project_…`. Name the choice in the WP notes.
- **Exception 2:** `test_build_app_fits_the_gate`: patch `server.ProjectDatabases` with a fake whose `.platform == "the-engine"` instead of `server.ProjectRepository`, and keep `assert seen["engine"] == "the-engine"`.

**`tests/test_repository.py`**
- `repository.list(platform_project)` becomes `repository.list()`.
- Delete `test_listing_shows_one_project_and_not_another` (mirrored by `test_I16_5_a_list_shows_only_its_own_projects_assessments`).
- Replace `test_the_database_refuses_an_assessment_of_a_project_that_does_not_exist` with "refuses a version absent from project.system" (`IntegrityError`).
- Update the `TestOneDatabase` docstring.

**Other test files**
- `tests/test_projects.py`: API paths go under `/p/{platform_project}/api/…`.
- `tests/test_project_llm.py`: the paths at lines 107, 111 and 123 go under `/p/{platform_project}/api/…`.
- `tests/test_assessment_of_a_version.py`:
  - `DELETE FROM core.system` becomes `project.system`.
  - Delete `test_s7_6_deleting_the_project_deletes_versions_and_assessments`. A deleted project's database is dropped; that is covered by `test_I2_5_…` and the platform's delete tests.
- Replace the two `test_migration_*` files with `tests/test_migration_project_database.py`, on a scratch database refused by the same rule, with the `project.system` stand-in:
  - (a) upgrade to head gives `alembic_version = "20260926000000_project_database"` and the tables;
  - (b) deleting a `project.system` row cascades the assessment (from the old S7.6 schema test);
  - (c) `create_all` and the baseline give the same `pg_get_constraintdef` set on `control_objectives.project` (from the old `test_the_model_has_the_same_key`).
- `tests/test_chain.py` (skipped without `CHAIN_JSON`) pins `fk_project_system_id_core_system` and a repository on `platform`. Leave it to V1 (pipeline-chain harness) and flag it.

### O1.9 Commands (throwaway database only)

1. Recipe of 02-tests.md section 2 (a random port that is not 5432, and the four init files). Then:
   ```
   docker exec $NAME psql -U aisc-postgres-user -d platform -c 'CREATE DATABASE control_objectives_test'
   ```
2. In `apps/control-objectives`:
   ```
   CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider
   ```
   Then `uv run --extra dev ruff check src tests`.
   **Target:** every test passes and 1 is skipped (`test_chain.py`). The 318 baseline passes, minus the deleted cases, plus the new ones. Nothing is red.
3. From the repo root:
   ```
   uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests/test_compose_isolation.py -k 'i5_ or i16_4'
   ```
   This is `docker compose config` only.
4. `docker rm -f $NAME`, then check that no `aisc-t-*` container is left.

### O1.10 Commits (explicit paths, never push)

1. `apps/control-objectives`, TDD first:
   - `git add tests/conftest.py tests/test_api_auth.py tests/test_repository.py tests/test_projects.py tests/test_project_llm.py tests/test_assessment_of_a_version.py tests/test_migration_project_database.py`
   - `git rm tests/test_migration_assessment_of_a_version.py tests/test_migration_card_version_of_its_project.py`
   - Message: "Isolation O1: the existing tests follow one database per project (S-D13): /p/{pid}/api paths, fixtures on project.system, the old chain's migration tests replaced by the baseline's"
2. `apps/control-objectives`:
   - `git add src/aisc_control_objectives/{projectdb,migrate_projects,settings,server,access,projects,upstream}.py src/aisc_control_objectives/api/app.py src/aisc_control_objectives/db/{tables,repository}.py alembic/env.py alembic/versions/20260926000000_project_database.py README.md pyproject.toml`
   - `git rm` the six old revisions.
   - Message: "Isolation O1: each project's assessments live in its own database (I5.1..I5.7): ProjectDatabases.open decides membership before connecting, /p/{pid}/api, one alembic baseline on project.system, migrate_projects"
3. Top level: `git add docker-compose.development.yml apps/control-objectives`, with message "Isolation O1: control-objectives migrates every project database (I5.5) and gets PROJECT_DATABASE_URL (I5.1)". Commit the compose file only if `git diff docker-compose.development.yml` holds only O1's hunks; otherwise hand it to the orchestrator.

---


---

## WP C1: controls, the answer key into project.system, reader grants, 404 after a drop

### Plan overrides (read first; they win over the text below)

- Add the reader-grant repair of N5 as a second new migration, sorted after the FK one:
  `prisma/migrations/20260926000100_readers_read_the_listed_tables/migration.sql` with
  `ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw IN SCHEMA controls REVOKE SELECT ON TABLES FROM dashboard_ro;`,
  `REVOKE SELECT ON controls."_prisma_migrations" FROM dashboard_ro;` and a DO block that, for each of report_ro and
  dashboard_ro that exists, grants SELECT on `controls.checklist, checklist_question, source, submission,
  submission_answer` (I2.6). It turns green `scripts/tests/test_project_grants.py::test_i2_6_readers_see_exactly_the_listed_tables[controls]`
  and `::test_i2_6_no_default_privilege_grants_to_a_reader` (with the other modules' WPs); run
  `-k controls` after P1. Commit it with the FK migration.
- Both new controls migrations run at cutover step C8b (after the copy), not at C7.

**Repo:** `/home/listuser/aisc-isolation/apps/controls`.
**Depends on:** P1 (template `0006_project_system.sql`); it is a hard dependency, see C1.4. No routing change (I6.1).
**Requirements:** I6.1, I6.2 (S-D9), I2.5, I17.1, I16.5 (guards).

### C1.1 Tests this WP turns green (9 red; 9 guards stay green)

- **`test/unit/isolationControls.test.ts`:** "I6.2: a new migration adds submission_answer_system_version_pid_fkey", "I6.2: it references project.system(pid) with ON DELETE NO ACTION", "I6.2: it checks for answers naming an absent version and refuses with a message". The two I6.1 cases stay green.
- **`test/integration/isolation-answer-fk.test.ts`:** all 4 (the key exists with NO ACTION; accepted, null and absent; delete refused; the migration refuses naming the pid).
- **`test/integration/isolation-routes-by-id.test.ts`:** "I2.5: an open client whose database is dropped is evicted, and the pid is not found" and "I2.5: a pid whose database never existed is not found". The 7 I16.5 cases stay green.

### C1.2 Files

- **Create:** `prisma/migrations/20260926000000_an_answer_is_of_a_version_in_this_database/migration.sql`. The directory name must sort after `20260923210100_dashboard_reads_controls`, and no other migration may contain the constraint name.
- **Change:** `src/lib/projectDb.ts` (I2.5).
- **Change (tests):** `test/integration/throwawayDb.ts`, `test/integration/answer-stamps.test.ts` and `test/unit/projectDb.test.ts`. These changes are not in S-D13, see C1.4.
- `prisma/schema.prisma` is unchanged: the foreign key is to another schema, `migrate deploy` ignores drift, and Prisma multiSchema is not in use.

### C1.3 Migration SQL

The check comes first, so the key is never added when it refuses.

```sql
-- I6.2 (isolation 2026-09-25): an answer's card version is a row of this project's own
-- project.system, made by the platform template 0006. NO ACTION: versions are never deleted,
-- and an answer must never be lost by a delete. The data move fills project.system before
-- this runs (cutover order); if it has not, this refuses and names the version.
DO $$
DECLARE
  absent uuid;
  n bigint;
BEGIN
  IF to_regclass('project.system') IS NULL THEN
    RAISE EXCEPTION 'project.system is missing in database %: apply the platform template 0006_project_system.sql first', current_database();
  END IF;
  SELECT a.system_version_pid, count(*) OVER () INTO absent, n
    FROM "submission_answer" a
   WHERE a.system_version_pid IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM project.system s WHERE s.pid = a.system_version_pid)
   ORDER BY a.system_version_pid LIMIT 1;
  IF absent IS NOT NULL THEN
    RAISE EXCEPTION 'an answer names card version % which is not in project.system (% answers do); run the data move (platform_service.isolate copy) before this migration', absent, n;
  END IF;
END $$;

ALTER TABLE "submission_answer"
  ADD CONSTRAINT "submission_answer_system_version_pid_fkey"
  FOREIGN KEY ("system_version_pid") REFERENCES "project"."system"("pid")
  ON DELETE NO ACTION ON UPDATE NO ACTION;
```

- No comment may contain "ON DELETE CASCADE" or "SET NULL": the unit test regex scans the whole file.
- The message contains the pid and `project.system` (S-D9) and no other row value (I18.7).
- `controls_rw` needs `USAGE` on schema `project` and `REFERENCES` on `project.system`. Template 0006 gives both (I2.1).
- **Operational note for X1:** a refused Prisma migration leaves a failed `_prisma_migrations` row. After the data is fixed, run `prisma migrate resolve --rolled-back 20260926000000_an_answer_is_of_a_version_in_this_database` before deploying again.

### C1.4 Test helpers that must change (the tests stay as they are)

- **`throwawayDb.makeProject()`** applies only template 0001 today. After this migration, every `prismaFor()` on such a database refuses, which breaks the pre-existing `answer-stamps`, `dashboard-grants` and `install-once-throwaway` suites and the 7 `isolation-routes-by-id` guards.
  - Change it to apply every `^\d{4}_.*\.sql$` file of `platform/project-template` (honour `ISOLATION_TEMPLATE_DIR` the way `isolationDb.ts` does) in order, each under `SET ROLE platform_rw;`, exactly like `isolationDb.makeTemplatedProject`.
  - Inline the loop rather than importing `isolationDb` (circular import).
- **`answer-stamps.test.ts`:** its stub platform stamps `V1` and `V2`, which the key now refuses unless they exist. In `beforeAll`, after `makeProject()`, insert them with `su("SET ROLE platform_rw; INSERT INTO project.system (pid, number, name) VALUES ('V1',1,'MCAS'),('V2',2,'MCAS')", db)`. This is what the platform does before it answers "latest" (D2, I2.2).
- **`projectDb.test.ts`:** add failing cases first:
  - an `execFile`-style error whose `stderr` holds "P1003: Database `project_x` does not exist" is missing;
  - the connection-lost codes are not missing on their own.

### C1.5 `src/lib/projectDb.ts` (I2.5)

- `isMissingDatabase(err)` also inspects `err.stderr` and `err.stdout` strings (the `prisma migrate deploy` failure) for `P1003` or `/database .* does not exist/i`. The existing unit cases stay true or false as they are.
- In `projectDbFor`, wrap `prismaFor(pid)`: if the error `isMissingDatabase`, call `notFound()`. This covers the second request and a database that never existed.
- In the `$use` handler of `prismaFor`:
  - If `isMissingDatabase(err)`, forget the client and call `notFound()`.
  - If the error is a lost connection (`P1001`, `P1017`, or `/terminating connection|server has closed the connection/i`): forget the client, probe `SELECT 1 FROM pg_database WHERE datname = $1` over `pg` on the template with `{database}` replaced by `postgres` (as `scripts/migrate-projects.mjs` does), and call `notFound()` when the database is gone. Otherwise rethrow.
  - This covers the first request after `DROP … WITH (FORCE)`.
- `MAX_OPEN_PROJECTS = 20` and `connection_limit=2` are unchanged (I6.1, I17.1).

### C1.6 Commands (throwaway database, after P1's 0006 is on the branch)

1. Same recipe as O1, then in `apps/controls`:
   ```
   CONTROLS_TEST_PG_CONTAINER=$NAME PROJECT_DATABASE_URL="postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls&connection_limit=2" npx vitest run test/unit test/integration/answer-stamps.test.ts test/integration/dashboard-grants.test.ts test/integration/install-once-throwaway.test.ts test/integration/isolation-answer-fk.test.ts test/integration/isolation-routes-by-id.test.ts
   ```
   Also run `npx tsc --noEmit` if configured. **Target:** 159 passed (the 141 baseline plus the 18 new ones), 0 failed.
2. Before P1 lands, dry check only: set `ISOLATION_TEMPLATE_DIR` to a scratch copy with a stand-in 0006.
3. **Never run** `project-scope`, `action-access`, `install`, `project-database`, `submission-lifecycle` or `chain`: they run SQL in the live `postgres` container.

### C1.7 Commits

1. `apps/controls`: `git add test/integration/throwawayDb.ts test/integration/answer-stamps.test.ts test/unit/projectDb.test.ts`, message "Isolation C1: test databases are made with every template file and register the versions they stamp (the key into project.system needs both)".
2. `apps/controls`: `git add prisma/migrations/20260926000000_an_answer_is_of_a_version_in_this_database/migration.sql src/lib/projectDb.ts`, message "Isolation C1: an answer's card version is a foreign key into project.system, refused with the absent pid (I6.2, S-D9); a dropped project database is 404 (I2.5)".
3. Top level: `git add apps/controls`, message "Isolation C1: controls gitlink".

---


---

## WP E1: engine part 1 (aliases, router, migrate_projects, 0025, reader grants, stamp)

### Plan overrides (read first; they win over the text below)

- **G2**: E1 does not edit `scripts/guard-frozen.sh` or `scripts/lib/throwaway-pg.sh`; the "Files, top level"
  subsections on them are input for V1, and the harness tests listed under "Top-level scripts/tests" for
  `test_isolation_harnesses.py` turn green in V1. E1 writes in its notes the exact G4 file list (the
  "G4 (backend)" list below) and the G5 settings variable.
- **G1**: the compose part (`aisc-backend` command, `aisc-backend-migrate`) is W1's; E1's top-level commit is only
  the gitlink `apps/backend`.
- **T5**: E1 makes the `_seed` correction of section 4 (close `connections[alias]` in `finally`), committed alone.
- `apps/backend/Dockerfile`: CMD without `manage.py migrate` (as below).

**Depends on:** P1 (templates `0006_project_system.sql` and `0009_engine.sql`). Without P1, engine_rw has no CONNECT on a project database, and the DB suite stops at "project.system is missing".

**Requirements:** I7.1, I7.6, I7.7, I7.8, I7.9, I7.10, I7.12, I2.6 (engine row), I1.8 (engine), I17.1 (engine settings part), S-D13 (backend part and G1/G4/G5).

After E1 alone, a deployed-mode engine refuses every ORM query, because nothing admits a request until E2's door exists. That is expected: nothing is deployed before cutover.

### Tests E1 turns green

**`apps/backend/aisc_backend/tests/test_isolation_engine.py`**
- `TheNewMigration`:
  - `test_i7_7_0025_has_the_name_of_the_spec`
  - `test_i7_7_0025_adds_the_fk_to_project_system_only_when_it_exists`
  - `test_i7_12_the_leaf_becomes_0025`
  - `test_i7_7_0015_0022_0023_are_unchanged` is already green and must stay green: do not touch 0015, 0022 or 0023.
- `TheNewMigrationOnSqlite.test_i7_7_0025_is_applied_as_a_no_op_on_sqlite`
- `SettingsOfADeployedEngine`, all 6: `default_is_the_dummy_backend`, `the_platform_alias_is_core_only`, `the_router_is_the_project_router`, `a_query_outside_an_admitted_request_fails`, `i17_1_an_alias_per_project_database`, `i1_8_only_a_pid_names_an_alias`
- `TheRouter`, all 5
- `OnlyTwoFilesReadPlatform`, all 3 (includes `test_i7_8_latest_reads_project_system`)
- `TheOneShotMigrates`, all 3: `migrate_projects_is_a_command`, `it_takes_an_advisory_lock_per_database`, `the_image_no_longer_migrates_platform`

**`apps/backend/aisc_backend/tests/test_isolation_engine_db.py`** (Postgres)
- `TheOneShotMigratesEveryProjectDatabase`, all 7
- `TheEngineReaderGrants`, all 4
- `TheShapeIsTheLiveShape.test_i7_9_every_table_column_index_and_key_is_as_live`
- `TheOrmStaysInItsDatabase`, all 4
- `EveryRouteByIdIsInTheTable` stays green.
- `TheDoorOnPostgres`, `NothingOfAIsReachableUnderB` and `ADroppedDatabase` belong to E2.

**Top-level `scripts/tests/`**
- `test_compose_isolation.py`:
  - `test_i7_6_aisc_backend_no_longer_migrates_platform`
  - `test_i7_6_aisc_backend_migrate_one_shot_runs_migrate_projects`
- `test_isolation_harnesses.py`:
  - `test_i7_12_guard_g1_compares_engine_definitions_in_a_project_database`
  - `test_i19_2_throwaway_pg_has_tpg_project_db`
  - `test_i19_2_tpg_project_db_makes_a_project_database_with_the_template`
  - `test_i19_2_harnesses_target_project_databases[guard-frozen.sh]` (the `test-pipeline-chain.sh` case is V1's)
- `test_project_grants.py`: the engine rows (`-k engine`) once P1 is in.

### Files, backend (`apps/backend`, branch `isolation/2026-09-25`)

#### `config/settings.py` (frozen until now; I7.12 lets it change)

Replace the Database block. Everything else in the file stays; E2 adds MIDDLEWARE and CORS later.

- Keep `DB_SCHEMA = env("DB_SCHEMA", "")` and `_db_engine`.
- `PROJECT_DATABASES = "postgresql" in _db_engine`
- `def _single_database() -> dict`: today's `default` dict exactly (search_path `DB_SCHEMA,core` on Postgres, `{}` on sqlite).
- When `PROJECT_DATABASES` is true:
  ```python
  DATABASES = {
      "default": {"ENGINE": "django.db.backends.dummy"},
      "platform": {"ENGINE": "django.db.backends.postgresql", "NAME": env("DB_NAME", "platform"),
                   "USER": env("DB_USER", ""), "PASSWORD": env("DB_PASSWORD", ""),
                   "HOST": env("DB_HOST", ""), "PORT": env("DB_PORT", ""),
                   "OPTIONS": {"options": "-c search_path=core"}, "CONN_MAX_AGE": 0},
  }
  PROJECT_DATABASE_TEMPLATE = {"ENGINE": "django.db.backends.postgresql", "USER": ..., "PASSWORD": ...,
                               "HOST": ..., "PORT": ...,
                               "OPTIONS": {"options": f"-c search_path={DB_SCHEMA or 'engine'}"},
                               "CONN_MAX_AGE": 0}
  DATABASE_ROUTERS = ["aisc_backend.projectdb.ProjectDatabaseRouter"]
  ```
- When it is false: `DATABASES = {"default": _single_database()}`, `PROJECT_DATABASE_TEMPLATE = None`, `DATABASE_ROUTERS = []`.
- `DB_NAME` now means only the platform alias's database.

#### `config/settings_single_database.py` (new; test and harness settings only)

- Starts with `from config.settings import *`, then sets:
  - `PROJECT_DATABASES = False`
  - `DATABASES = {"default": _single_database()}`
  - `DATABASE_ROUTERS = []`
  - `PROJECT_DATABASE_TEMPLATE = None`
- Docstring: never used by a deployed engine. It exists so that the pre-existing backend Postgres suite and guard-frozen's `--orders` mode can migrate one database.
- Why a module and not an environment switch: `isolation_support.settings_probe` forces `DJANGO_SETTINGS_MODULE=config.settings` and copies `os.environ`. A switch variable would leak into the probe and turn `SettingsOfADeployedEngine` red.

#### `aisc_backend/projectdb.py` (new)

Names the tests pin: `ProjectDatabaseRouter`, `admitted`, `alias_for`. The rest is the proposed interface.

```python
PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
DATABASE = re.compile(r"^project_[0-9a-f]{32}$")
admitted: ContextVar[str | None] = ContextVar("aisc_admitted_alias", default=None)
admitted_pid: ContextVar[str | None] = ContextVar("aisc_admitted_pid", default=None)   # used by E2

class NotAPid(ValueError): ...
class NoProjectAdmitted(RuntimeError): ...        # raised by the router; never an OperationalError
class NoSuchProjectDatabase(Exception): ...       # missing database, or engine_rw may not CONNECT
class SchemaNotProvisioned(Exception): ...        # no `engine` schema, or no CREATE on it
class MigrationFailed(Exception): ...

def enabled() -> bool                     # settings.PROJECT_DATABASES
def normalise(pid) -> str                 # lower-case, checked against PID, else NotAPid
def database_name(pid) -> str             # "project_" + hex; I1.8 example maps to EXAMPLE_DB
def pid_of(database: str) -> str
def alias_for(platform_pid) -> str
def forget(alias: str) -> None
def open_alias(alias: str) -> str
class ProjectDatabaseRouter
```

**`alias_for(platform_pid) -> str`**
- Validate the pid. Registration only, no I/O.
- Copy-on-write registration, as in plan 4's `_register`/`_replace_settings`:
  ```python
  configured = connections.configure_settings({DEFAULT_DB_ALIAS: {}, alias: {**settings.PROJECT_DATABASE_TEMPLATE, "NAME": alias}})[alias]
  ```
  then replace both `connections._settings` and `connections.__dict__["settings"]` under a `threading.Lock`.
- Returns the alias, which is the database name.
- When `enabled()` is false, it only validates and returns `"default"`.
- Must refuse `""`, `"abc"`, `"../platform"`, `pid+"x"`, `"platform"` and `"default"`.

**`forget(alias) -> None`**
- Remove the alias from `connections.settings` (copy-on-write).
- `del connections[alias]`, ignoring AttributeError.
- Discard it from `_migrated`.

**`open_alias(alias) -> str`**
- `connections[alias].ensure_connection()`.
- An OperationalError for a missing database (sqlstate 3D000, or "does not exist") or no CONNECT (42501, "permission denied for database") calls `forget(alias)` and raises `NoSuchProjectDatabase`.
- If the alias is not in `_migrated`: take the per-alias `threading.Lock`, call `migrate_projects.migrate_database(alias)`, then add it to `_migrated`.
- A failure is not remembered and raises `MigrationFailed`.
- `SchemaNotProvisioned` maps to `NoSuchProjectDatabase` in the door.

**`ProjectDatabaseRouter`**
- `db_for_read` and `db_for_write` return `admitted.get()`. With nothing admitted they raise `NoProjectAdmitted`: never None, never "default", never "platform".
- `allow_relation(o1, o2)` returns `o1._state.db == o2._state.db`.
- `allow_migrate(db, app_label, **h)` returns `bool(DATABASE.match(db))`. That is False for "platform" and "default" and True for project aliases, for every app including contenttypes.

**Rule for this file:** it names nothing in `core` (the SQL scan in `OnlyTwoFilesReadPlatform`).

#### `aisc_backend/management/__init__.py`, `aisc_backend/management/commands/__init__.py` (new, empty)

#### `aisc_backend/management/commands/migrate_projects.py` (new)

- Module constant: `ENGINE_MIGRATE_LOCK = 0x656E67696E65` (plan 4's "engine" key). Postgres advisory locks are per database.

**`migrate_database(alias: str) -> None`** (the door's first-use path imports this lazily)
1. `token = projectdb.admitted.set(alias)`, so historical-model RunPython queries route there.
2. On `connections[alias]`:
   - If `SELECT to_regclass('django_migrations')` is null, and `SELECT has_schema_privilege(current_user, 'engine', 'CREATE')` is false or the schema is missing, raise `SchemaNotProvisioned`.
   - `SELECT pg_advisory_lock(%s)`, then `call_command("migrate", database=alias, interactive=False, verbosity=0)`, then `grant_readers(connection)`, then `SELECT pg_advisory_unlock(%s)` in `finally`.
3. `admitted.reset(token)`.

**`grant_readers(connection)`** (I2.6, as engine_rw, the table owner)

```sql
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['report_ro','dashboard_ro'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('GRANT SELECT ON engine.project, engine.ai_system, engine.ai_component, engine.evaluation,
        engine.evaluation_plugin, engine.evaluation_input, engine.plugin, engine.observation, engine.measurement,
        engine.metric, engine.direct, engine.derived, engine.metric_category, engine.metric_category_metrics,
        engine.artifact TO %I', r);
      EXECUTE format('GRANT SELECT (id, plugin_id) ON engine.plugin_config TO %I', r);
    END IF;
  END LOOP;
END $$;
```

- No grant on `project_config`, `plugin_config_project_config`, `django_migrations` or `django_content_type`.
- No default privileges.
- Not a Django migration, so the schema history does not change.

**`Command.handle()`**
- Refuse with `CommandError` when `not projectdb.enabled()`.
- Wait for the platform, up to `MIGRATE_PROJECTS_WAIT` seconds (default 60, sleeping 2 s between tries).
- List the databases through `connections["platform"]`:
  ```sql
  SELECT datname FROM pg_database
  WHERE datname ~ '^project_[0-9a-f]{32}$'
    AND has_database_privilege(current_user, datname, 'CONNECT')
  ORDER BY datname
  ```
  This is pg_database, not core.project, so the bare database and the orphans are skipped. C, dropped, is simply absent.
- For each database: `alias = projectdb.alias_for(pid_of(name))`, then `migrate_database(alias)`, then `connections[alias].close()` in `finally`.
- `NoSuchProjectDatabase` and `SchemaNotProvisioned` print "skipped" and carry on.
- Any other exception counts as a failure. Print the database name and the exception type only: no DSN, no row values.
- Exit non-zero (`CommandError`) if any failure occurred.
- `requires_system_checks = []` is allowed if the checks trip on the dummy default.

#### `aisc_backend/migrations/0025_the_database_is_the_project.py` (new)

- `dependencies = [("aisc_backend", "0024_no_login_of_its_own")]`
- `operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]`
- `forwards` returns early when `schema_editor.connection.vendor != "postgresql"` (the no-op on sqlite; the text must contain "postgresql").
- SQL:
  ```sql
  DO $$
  BEGIN
    IF to_regclass('project.system') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint
                       WHERE conrelid = 'evaluation'::regclass
                         AND conname = 'aisc_backend_evaluation_system_id_fkey') THEN
      ALTER TABLE evaluation ADD CONSTRAINT aisc_backend_evaluation_system_id_fkey
        FOREIGN KEY (system_id) REFERENCES project.system (pid) ON DELETE SET NULL;
    END IF;
  END $$;
  ```
- The file must not contain the text `core.` anywhere, including comments and docstrings. The test regex is `core\.`.
- No UPDATE that nulls dangling ids: a violation must fail loudly (RULES: data is verified, never silently changed).

#### `aisc_backend/auth/membership.py`

- Import `connections` (never `connection`).
- Add:
  ```python
  def _platform():
      return connections["platform"] if "platform" in connections.settings else connections[DEFAULT_DB_ALIAS]
  ```
- `role_in_project(platform_project_id, subject)` keeps its name and signature; the E2 door and tests patch it. It uses `_platform()`, keeps the vendor and `to_regclass('core.project_member')` guards, and lets DatabaseError propagate (the door turns it into 503).

#### `aisc_backend/platform_projects.py`

- Same `_platform()` helper; `platform_project_name` uses it.
- Add `platform_project_exists(pid) -> bool`: `SELECT 1 FROM core.project WHERE pid = %s`. It returns True when the platform connection is not Postgres or `core.project` is absent (sqlite and single mode).
- Both files must contain the literal `connections["platform"]`.

#### `aisc_backend/repositories/system_version_repository.py`

- `LATEST = "SELECT pid FROM project.system ORDER BY number DESC LIMIT 1"` (exact string).
- `latest_system_pid_sync(platform_project_id, using=None)`:
  - Returns None when the pid is None.
  - `alias = using or projectdb.admitted.get() or DEFAULT_DB_ALIAS`
  - Returns None when `connections[alias].vendor != "postgresql"`.
  - Checks `to_regclass('project.system')`, then runs LATEST inside `transaction.atomic(using=alias)`.
  - Keeps the DatabaseError-to-None savepoint behaviour.
- `latest_system_pid` (async) keeps its signature.

#### `aisc_backend/signals/system_stamp.py`

- Pass `using=kwargs.get("using")`. Still new evaluations only (I7.8).

#### `aisc_backend/repositories/measurement_repository.py` (not frozen)

- Replace `connection.vendor` with `connections[base_queryset.db].vendor`. On the dummy default the Postgres `jsonb_object_keys` path would otherwise silently fall back to the Python path.

#### `Dockerfile`

- `CMD uv run uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --no-access-log`: no `manage.py migrate` (I7.6 test regex).
- Update the comment.

### Files, top level

#### `docker-compose.development.yml`

- **`aisc-backend`:** the command becomes
  ```
  sh -c "uv pip install --no-deps -e /app/shared/plugin-manager -e /app/shared/plugin-interface && uv run uvicorn config.asgi:application ..."
  ```
  Add `depends_on: aisc-backend-migrate: condition: service_completed_successfully`. Keep the DB_* environment. No PLATFORM_URL (`test_compose.py` pins its absence).
- **New `aisc-backend-migrate`:**
  - Same image, same DB_* environment (DB_USER=engine_rw), same `./shared` volume.
  - Command: the same `uv pip install` prefix, then `uv run manage.py migrate_projects`.
  - `restart: "no"`
  - `depends_on: postgres`; also `platform` if it has a healthcheck, since templates reach existing databases through `provision_all`.
  - `networks: backend`
- The file is shared with other WPs. Commit only E1's hunks. `git add -p` is interactive and not available here, so make a patch of the hunks and use `git apply --cached`.

#### `scripts/lib/throwaway-pg.sh`

- New `tpg_project_db()` (I19.2; V1 reuses it for the pipeline chain):
  - Takes a pid.
  - Creates `project_<hex>`.
  - Applies every `platform/project-template/*.sql` through the platform's own runner, tracked in `provision.template_migration`.
- Preferred way: call `platform_service.projectdb.provision(tpg_dsn superuser, pid)` with the platform's Python. This matches `test_i19_2_tpg_project_db_makes_a_project_database_with_the_template`, which expects the sorted template names.

#### `scripts/guard-frozen.sh` (S-D13, I7.12)

**G1**
- The reference build is unchanged (e34fca3 on `platform`).
- `build_candidate`:
  - Replace `engine_migrate "$WORK/cand/backend"` with `tpg_project_db <fixed pid>`.
  - Then run `migrate_projects` from `$WORK/cand/backend` (deployed settings, engine_rw, DB_NAME=platform, DB_SCHEMA=engine).
  - Then `tpg_dump project_<hex> --schema-only --schema=engine > "$OUT/engine.candidate.sql"`. The literal `tpg_dump platform ... > "$OUT/engine.candidate.sql"` must disappear (harness test).
  - Add `platform/project-template` to the `tree "$ROOT" ... init platform/migrations` list.
- `g1()` compares normalised copies (`$OUT/engine.{reference,candidate}.g1.sql`). Normalisation, on both sides:
  - Drop the GRANT, REVOKE and DEFAULT PRIVILEGES lines (the reader grants differ by design).
  - Drop `ALTER SCHEMA engine OWNER` and `COMMENT ON SCHEMA engine`.
  - Drop the `aisc_backend_project_platform_project_id_fkey` statement.
  - Drop the `aisc_backend_evaluation_system_id_fkey` statement.
  - Then assert separately that the candidate holds `FOREIGN KEY (system_id) REFERENCES project.system(pid) ON DELETE SET NULL` (I7.9's two allowed differences).
- Keep the PASS text exactly `G1 PASS (engine schema equals e34fca3)`, because `test_guard_frozen.py::test_s1_1` and `test_s9_4` pin it. `test_s1_6` still reads `engine.candidate.sql`.
- `--orders` (S4): step E migrates the candidate tree on `platform`. Give only that call `DJANGO_SETTINGS_MODULE=config.settings_single_database`. The ref and live trees are old code without that module and must not get it.

**G4 (backend)**
- Part 1 (Sean's files): exclude `config/settings.py`, by name, with an I7.12 comment.
- Part 2 (`backend_allowed`), add:
  - `config/settings.py`, `config/settings_single_database.py`
  - `aisc_backend/projectdb.py`, `aisc_backend/management/*`
  - `aisc_backend/migrations/0025_the_database_is_the_project.py`
  - `aisc_backend/auth/membership.py`, `aisc_backend/platform_projects.py`
  - `aisc_backend/repositories/measurement_repository.py`
  - `aisc_backend/services/celery_service.py` and `aisc_backend/project_door.py` (for E2)
- The Dockerfile rule becomes: e34fca3's Dockerfile, minus the CMD block, differs from HEAD's by exactly dfe4120's change, and the CMD has no `manage.py migrate` other than `migrate_projects`.
- Do not add `0024_no_login_of_its_own.py`: that is a pre-existing red from another pipeline.

**G5:** no change needed. Models are untouched and 0025 is RunPython only, so `makemigrations --check` on sqlite stays clean. Verify it.

### Existing tests that must change (S-D13, name each in the WP notes)

- **`aisc_backend/tests/test_frozen_sean_files.py`:** remove `"config/settings.py"` from `SEAN_FILES_2026_09_23`, with a comment ("left the list with isolation I7.1/I7.2/I7.12; see 03-coding-plan E1"). Nothing else. `test_g4` stays red on `routers/plugin.py` and `pyproject.toml`, which are pre-existing known reds.
- **`aisc_backend/tests/test_one_system_per_project.py::test_s1_0023_is_the_leaf`:**
  - Expect `leaf_nodes == [("aisc_backend", "0025_the_database_is_the_project")]`.
  - Keep the assertion that 0024's parent is 0023; add that 0025's parent is 0024.
  - Update the comment. Keep the method name so baseline counts map one to one.
- **`aisc_backend/tests/test_evaluation_system_stamp.py`:**
  - `_make_core_system` becomes `_make_project_system`: `CREATE SCHEMA IF NOT EXISTS project; CREATE TABLE IF NOT EXISTS project.system (pid uuid PRIMARY KEY, number integer NOT NULL CHECK (number > 0) UNIQUE)`.
  - `_add_version(platform_project, number)` inserts `(pid, number)`; the project argument is ignored.
  - In `test_s9_2_highest_number_wins`, remove `_add_version(uuid.uuid4(), 7)`: with one project per database, it would now win. Leave a comment saying another project's versions live in another database.
  - `test_s9_3_none_when_core_system_is_absent` becomes `..._project_system_is_absent`, checking `to_regclass('project.system') IS NULL`.
  - Update the docstring.

### Commands (throwaway recipe of 02-tests.md section 2; never port 5432; `docker rm -f` afterwards; always set `PLATFORM_TEST_DATABASE_URL`)

- **Backend sqlite:**
  ```
  cd apps/backend; PYTHONPATH=$PWD/../../shared/plugin-interface/src DB_ENGINE=django.db.backends.sqlite3 DB_NAME=$SCRATCH/t.db .venv/bin/python manage.py test aisc_backend
  ```
  Baseline: 140 ran, 6 failures, 5 errors, 13 skipped. Known reds: F5 ImportError, three `test_g4`, three keycloak integration, three `project_config_router`, `s1_aisystem`.
- **Backend Postgres, the pre-existing suite, now single database:** the 02-tests command plus `DJANGO_SETTINGS_MODULE=config.settings_single_database`. Baseline: 140 ran, 6 failures, 6 errors, 9 skipped (also `s9_3`). The changed stamp tests may turn `s9_3` green.
- **Backend isolation DB:** the 02-tests line, unchanged:
  ```
  ENGINE_TEST_SUPERUSER_URL=... PLATFORM_TEST_DATABASE_URL=... DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT=$PORT DB_SCHEMA=engine .venv/bin/python manage.py test --noinput aisc_backend.tests.test_isolation_engine_db
  ```
  After E1, expect the E1 classes green and the E2 classes red.
- **Top level:**
  ```
  uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
    scripts/tests/test_compose_isolation.py -k i7_6 \
    scripts/tests/test_isolation_harnesses.py -k "i7_12 or i19_2" \
    scripts/tests/test_project_grants.py -k engine \
    scripts/tests/test_guard_frozen.py
  ```
  Record the `test_guard_frozen` baseline first: 11 known failures, and none may be added. Also run `GUARD_SOURCE=worktree scripts/guard-frozen.sh --only G1,G4,G5`.

### Commits (explicit paths, never push)

1. **`apps/backend`:** `aisc_backend/projectdb.py aisc_backend/management/__init__.py aisc_backend/management/commands/__init__.py aisc_backend/management/commands/migrate_projects.py aisc_backend/migrations/0025_the_database_is_the_project.py config/settings.py config/settings_single_database.py aisc_backend/auth/membership.py aisc_backend/platform_projects.py aisc_backend/repositories/system_version_repository.py aisc_backend/signals/system_stamp.py aisc_backend/repositories/measurement_repository.py Dockerfile`
   Message: "Isolation E1: every engine query goes to the admitted project database (aliases, router, migrate_projects with reader grants, 0025, stamp on project.system)"
2. **`apps/backend`:** `aisc_backend/tests/test_frozen_sean_files.py aisc_backend/tests/test_one_system_per_project.py aisc_backend/tests/test_evaluation_system_stamp.py`
   Message: "Isolation E1: the frozen-file tests follow I7.12 (settings.py leaves the list, leaf 0025, S9 on project.system)"
3. **Top level:** `docker-compose.development.yml` (E1 hunks only), `scripts/guard-frozen.sh`, `scripts/lib/throwaway-pg.sh`, gitlink `apps/backend`
   Message: "Isolation E1: aisc-backend-migrate one-shot, G1 in a project database, tpg_project_db, G4 allowed set"

---


---

## WP R2: report renderer on project databases

### Plan overrides (read first; they win over the text below)

- Order: R2 runs in wave 1, before R1 (R1's composer e2e tests start this renderer).
- The `no_database` parameter of `scripts/lib/report_bed_isolated.py` is added by R2 (not R1).
- P1 has already made `scripts/lib/report_bed.py` build the old layout from the G3 fixture; check its precondition
  (`report_bed.build("x", modules=False)` builds) before starting.
- The renderer's compose block needs no change (W1 checks it).

**Repo:** the worktree `~/aisc-isolation-report-generator`, branch `isolation/2026-09-25` (it already exists, at 27bb0cb). Never edit `~/aisc-report-generator`. There is one top-level change as well (the bed parameter).

### Requirements and the tests that must turn green

I9.1 to I9.4, through 30 tests in `tests/test_isolation_project_databases.py` (24 red and 6 green guards today):
- `test_the_isolated_bed_has_the_isolated_shape`
- `test_i9_2_no_module_of_the_renderer_names_core_system`
- `test_i9_2_the_module_readers_never_use_the_platform_dsn` (qualification, control_objectives, engine)
- `test_i9_2_platform_py_reads_only_core_project_and_pg_database`
- `test_i9_2_a_full_report_reads_platform_only_for_core_project`
- `test_i9_2_versions_come_from_the_projects_database`
- `test_i9_2_module_data_of_the_pinned_version_from_the_projects_database`
- `test_i9_2_i9_4_another_projects_version_reads_nothing_from_this_database`
- `test_i9_2_no_other_projects_data_in_a_report`
- `test_i9_3_a_version_of_another_project_is_not_in_project`
- `test_i9_3_the_service_answers_404_for_a_version_of_another_project`
- `test_i9_3_the_service_serves_alpha_from_its_database`
- `test_i9_3_a_missing_project_database_gives_empty_for_every_data_block`
- `test_i9_3_a_missing_project_database_reads_as_nothing` (3 cases)
- `test_i9_3_a_missing_module_schema_or_table_gives_empty_never_error`
- `test_i9_4_every_data_function_still_takes_project_and_system_first` (5 cases)
- `test_i9_2_golden_without_evaluations_is_byte_identical_on_project_databases` (3 cases)
- `test_i9_2_golden_with_evaluations_on_project_databases` (3 cases)

I9.1 and I9.2 compose wiring (`scripts/tests/test_compose_isolation.py::test_i9_1_renderer_builds_from_report_generator_dir` and `test_i9_2_renderer_reads_projects_from_their_database`) already hold with today's compose file. Verify them; do not change compose. Setting `REPORT_GENERATOR_DIR` for isolation builds is X1's job (rehearse and cutover).

### Files

**Renderer worktree, change:**
- `report_renderer/data/db.py`
- `report_renderer/data/platform.py`
- `report_renderer/data/qualification.py`
- `report_renderer/data/control_objectives.py`
- `report_renderer/data/engine.py`
- `report_renderer/data/controls.py` (recommended only: treat a missing table as nothing)
- `report_renderer/data/__init__.py` (docstring)
- `tests/conftest.py`
- `README.md` (env and bed notes)

`report_service.py` stays as it is: it already maps `NotInProject` to 404 `not_found` on `/v1/choices`, `/v1/coverage-choices` and `/v1/render`. `context.py`, `document.py` and the blocks stay as they are.

**Top level:** `scripts/lib/report_bed_isolated.py` gets the `no_database` parameter (see R1, item 1).

### Signatures and behaviour

**`data/db.py`** (not covered by the I9.4 signature check, so the helpers live here)
```python
def connect(dsn, source)       # unchanged
def rows(dsn, source, sql, params=None) -> list[dict]
def one(dsn, source, sql, params=None) -> dict | None
_ABSENT = (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName)
def project_dsn(sources, project_id) -> str | None
    # database_name(project_id) from .scope; SELECT 1 AS x FROM pg_database WHERE datname = %(n)s on
    # sources.platform_dsn; None when the database is absent
def project_rows(sources, project_id, source, sql, params=None) -> list[dict]
    # [] when the database is absent or _ABSENT is raised
def project_one(sources, project_id, source, sql, params=None) -> dict | None
    # None likewise
```
Keep the pattern where `psycopg.connect` returns an object that is used without `with conn:`. The renderer test's `_Spy` has no `__enter__` or `__exit__`, so `with psycopg.connect(...) as conn` would break `test_i9_2_a_full_report_*`.

**`data/platform.py`**

The source may name only `core.project`, `pg_database` and `project.system` after FROM or JOIN, and `project.system` must appear. The words `core.system` and `platform_dsn` in data modules other than `platform.py` are forbidden, in comments too.

- `pinned_system(project_id, system_id, *, sources) -> dict`:
  - A bad uuid raises `NotInProject`.
  - If the project database is missing, or it exists without a `project.system` table, return the stand-in `_without_database(p, s)` (resolved ambiguity A3, A4).
  - Otherwise run `SELECT pid::text, number, name, version, provider, description, created_at FROM project.system WHERE pid = %(s)s` on the project database. No row raises `NotInProject`.
  - Always set `row["project_id"] = p` (`context_for` and `ScopedData.for_version` use it).
- `project(project_id, system_id, *, sources)`: unchanged (`core.project` on platform).
- `newer_versions(project_id, system_id, *, sources) -> list[dict]`: `SELECT pid::text, number FROM project.system WHERE number > (SELECT number FROM project.system WHERE pid = %(s)s) ORDER BY number`, through `db.project_rows`.
- `older_versions(...)`: the same with `version` in the columns, and `number <`, `ORDER BY number DESC`.
- `database_exists(project_id, system_id, *, sources, name) -> bool`: unchanged.
- Any new public function must still take `(project_id, system_id)` first. Keep helpers private (leading `_`) or in `db.py`.

**`data/qualification.py`, `data/control_objectives.py`, `data/engine.py`**

Every function uses `db.project_one` or `db.project_rows(sources, project_id, "<module>", sql, params)`. The public names and signatures stay the same.

- Qualification: `_SCOPE = "q.system_id = %(s)s"`. `newest_newer_card` uses `JOIN project.system s ON s.pid = q.system_id WHERE s.number > (SELECT number FROM project.system WHERE pid = %(s)s)`.
- Control objectives: `_SCOPE = "a.system_id = %(s)s"`, and the same `project.system` pattern in `newest_newer_assessment`.
- Engine: `_EVAL = "engine.evaluation e"`, `_SCOPE = "e.system_id = %(s)s"`. Remove the join to `engine.project`: the project filter is the database itself (I9.2, resolved ambiguity A5).
  - `unversioned_count` becomes `SELECT count(*) AS n FROM engine.evaluation e WHERE e.system_id IS NULL`, and returns 0 when there is no row.
  - `newest_newer_evaluation` uses `JOIN project.system s`.
- Still call `check_uuid(project_id)` (bad input raises `ValueError`, as today).

**`data/controls.py`:** unchanged behaviour: `None` when the database is missing. Recommended: return `None` or `[]` on `_ABSENT` as well.

**Result:**
- For gamma (a `core.project` row but no database), every data block renders `empty`.
- For project X (an empty `qualification` schema, and no `control_objectives` or `engine` schema), every data block renders `empty`.
- Beta's version under alpha gives `NotInProject`, so the service answers 404.

### Existing tests that must change (S-D13)

1. **`tests/conftest.py`**:
   - `bed` becomes `report_bed_isolated.build_isolated("renderer", modules=True, no_database=frozenset())`, imported from `AISC_INSTALL/scripts/lib`. If the module is missing, fail with a clear `AISC_INSTALL_DIR` message.
   - Gamma gets a database holding only its version C_V1 ("Gamma model", number 1) and empty module tables. That keeps the legacy gamma tests (`test_block_cover.py:25,72`, `test_block_ai_card.py:63`, `test_block_control_answers.py:77`, `test_block_risk.py`, `test_block_summary_coverage.py`, `test_block_test_results.py:109`, `test_v2_chart_block.py:110,115`, `test_v2_key_figures.py:99`, `test_block_free_text.py`, `test_block_control_objectives.py`) valid. Their assertions stay unchanged.
   - Name one change: `test_r6_4_no_project_database_is_empty_not_error` now runs on a database with no controls rows. The "no database at all" case is pinned by the new `test_i9_3_a_missing_project_database_*` on its own bed.
   - Update the docstring.
2. No other renderer test reads module tables through `bed`. `test_data_access.py` only writes `core.project` as report_ro and reads `bed.env()`, so it needs no change.

### Commands

Renderer suite, from `~/aisc-isolation-report-generator`:
```
env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL AISC_INSTALL_DIR=/home/listuser/aisc-isolation uv run --extra dev pytest -q -p no:cacheprovider
```
- Baseline: 642 passed.
- Target: 672 passed, 0 failed (642 plus 30).

Top-level check, from the repo root:
```
uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests/test_compose_isolation.py -k "i9"
```
Must be green.

Then run the composer suite (R1 command) to confirm the e2e tests with the new renderer. Stopping rule and cleanup are as in R1.

### Commits (no push)

1. Top level:
   ```
   git add scripts/lib/report_bed_isolated.py
   ```
   Message: "Isolation R2: build_isolated can give every seeded project a database (no_database parameter, default unchanged)"
2. Renderer worktree:
   ```
   git -C ~/aisc-isolation-report-generator add report_renderer/data/{db,platform,qualification,control_objectives,engine,controls,__init__}.py tests/conftest.py README.md
   ```
   Message: "Isolation R2: the renderer reads versions and module data from the project's own database; a missing database, schema or table reads as empty (I9.2..I9.4)"

---


---

## WP D1: results dashboard reads each project from its own database

### Plan overrides (read first; they win over the text below)

- **G1**: step 6 (top-level compose lines) is W1's; D1's top-level commit is only the gitlink
  `apps/results-dashboard`.
- The `AISC Results` row is deleted by X1's C12 (after C11 re-registers every project), not at C9.
- Provide `aisc_ext.results_db.remove_results_connection() -> int` (refuses, raising, while any dataset uses
  `AISC Results`; else deletes the rows of every table with a foreign key to `dbs` for it and the `dbs` row, returns
  the count). Test it with the fake store. X1 calls it at C12 (`superset shell` or a small script in the dashboard
  image); its SQL fallback in X1 is used only if the image cannot run it.

**Repos:** `apps/results-dashboard` (submodule worktree, branch `isolation/2026-09-25`), plus two env lines and the gitlink in the top-level repo.
**Depends on:** P1 (templates `0006_project_system.sql`, `0009_engine.sql`, the new `init/platform-db.sql`). The seeding change below keeps the suite green whether or not C1 has landed.
**Requirements:** I10.1, I10.2, I10.3, I10.4, I10.5, I17.1 (dashboard row), I16.5 (dashboard part), I19.3 (dashboard side), I1.8.

### Tests it turns green
- `tests/test_isolation_dashboard.py`: 10 red today (checked by a run): `test_i10_1_the_engine_dataset_is_on_the_projects_own_connection`, `test_i10_1_the_engine_sql_joins_project_system_and_never_core`, `test_i10_1_the_engine_sql_has_no_pid_filter`, `test_i10_1_reregistering_moves_a_dataset_that_sits_on_aisc_results`, `test_i10_1_isolation_a_projects_role_reaches_only_its_own_database`, `test_i10_2_superset_config_no_longer_registers_aisc_results`, `test_i10_2_results_db_registers_nothing_named_aisc_results`, `test_i10_2_sso_reads_membership_over_aisc_membership_db_uri`, `test_i10_2_the_dashboards_compose_file_passes_the_membership_dsn`, `test_i16_5_unregistering_one_project_leaves_the_other_projects_objects`. The other 10 are guards and must stay green.
- `tests/test_isolation_dashboard_db.py` (4, need P1): `test_i10_3_dashboard_ro_reads_project_system_and_never_writes_it`, `test_i10_1_i19_3_the_engine_dataset_runs_as_dashboard_ro_in_the_project_database`, `test_i16_5_the_engine_dataset_of_one_project_database_never_shows_another_projects_rows`, `test_i10_3_dashboard_ro_cannot_write_the_engine_tables_of_a_project_database`.
- Top level, if D1 edits the dashboard's compose lines (recommended, see step 6): `scripts/tests/test_compose_isolation.py::test_i10_2_dashboard_reads_memberships_over_a_plain_dsn_and_registers_no_platform_connection[dashboard|dashboard-migrate]` and `::test_i16_4_every_module_dsn_names_a_project_database_except_the_allowed_platform_ones[dashboard]`.

### Code changes (apps/results-dashboard)

1. **`aisc_ext/projects.py`**
   - `engine_results_sql() -> str` takes **no argument** and returns the SQL below. Drop the `engine.project` join: `e.project_id` would trip the `"project_id" not in sql` assertion, and each database holds exactly one engine project.
     ```sql
     SELECT m.pid, m.score, m.unit, m.time, m.dimensions, met.name AS metric,
            e.pid AS evaluation_pid, e.created_at AS evaluated_at,
            s.pid AS system_version_pid, s.number AS system_version
       FROM engine.measurement m
       JOIN engine.observation o ON o.id = m.observation_id
       JOIN engine.evaluation e ON e.id = o.evaluation_id
       JOIN engine.metric met ON met.id = m.metric_id
       LEFT JOIN project.system s ON s.pid = e.system_id
     ```
     No trailing semicolon: the tests wrap it in `SELECT … FROM (<sql>) t`.
   - `register_project`: `store.upsert("dataset", engine_ds, {**tag, "database": database, "sql": engine_results_sql()})`, where `database` is `controls_database_name(slug)` (name unchanged, I10.1). Everything else stays as it is.
   - Import only `READ_ONLY_ROLE` from `results_db`.
   - Update the module docstring and the `MEMBER_PROJECTS_SQL` comment: it is read over `AISC_MEMBERSHIP_DB_URI`, not "the results connection".
   - `SupersetStore._upsert_dataset`: keep the in-place move (the id stays; the guard test already passes). Add a Superset permission refresh after `found.database = database`: `if hasattr(found, "get_perm"): found.perm = found.get_perm()`, and the same for `schema_perm` with `get_schema_perm`. The test's fake `Row` lacks both methods, hence `hasattr`.
   - Do **not** swallow `fetch_metadata()` errors. A failed registration must fail the bridge call so `db.provision_all` retries it (see the risk below).
2. **`aisc_ext/results_db.py`**
   - Delete `registration_for` and `register_results_database`.
   - Keep `READ_ONLY_ROLE = "dashboard_ro"`.
   - Keep `RESULTS_DB_NAME = "AISC Results"`, documented as the retired connection name that nothing registers any more; cutover C9 deletes that row.
   - Add `MEMBERSHIP_ENV = "AISC_MEMBERSHIP_DB_URI"` and `membership_uri(env=None) -> str | None`. It strips the value, returns `None` when blank, and raises `ValueError("… must connect as the read-only role 'dashboard_ro' …")` unless the value contains `//dashboard_ro:` or `//dashboard_ro@`. Keep the wording "read-only".
3. **`aisc_ext/sso.py` `_member_projects`**
   - `uri = membership_uri(os.environ)`; on `ValueError`, log and return `[]`.
   - `create_engine(uri, poolclass=NullPool)` (import `sqlalchemy.pool.NullPool`), keeping `engine.dispose()` in `finally`.
   - The docstring names `AISC_MEMBERSHIP_DB_URI`.
   - The text must not contain `AISC_RESULTS_DB_URI`, `superset.models.core` or `Database(`. The gateway (`dashboard-gateway/superset_gateway_config.py`) calls `_member_projects` unchanged.
4. **`superset_config.py`**: remove the `register_results_database` import and call from `FLASK_APP_MUTATOR` (keep `_install_extension(app)` inside `app_context`). Optionally add a comment that analytics connections use Superset's default no-persistent-pool engines (I10.4). The comment must not contain the word `QueuePool` or any `pool_size` above 2: the test scans the whole file, comments included.
5. **Docs and config text:**
   - `docker-compose.yml`: replace `AISC_RESULTS_DB_URI: ${AISC_RESULTS_DB_URI:-}` with `AISC_MEMBERSHIP_DB_URI: ${AISC_MEMBERSHIP_DB_URI:-}`.
   - `.env.example`, `docker-compose.aisc.yml` (comment), `README.md` (env table row), `scripts/bootstrap.sh` (the "Next:" text): the membership DSN (dashboard_ro on `platform`), and project connections built by the bridge from `AISC_PROJECT_DB_HOSTPORT`.
   - `scripts/verify_review.py`: stop using `RESULTS_DB_NAME`. Pick the first `Database` whose `extra` carries `aisc_project` (an "AISC Controls <slug>" connection) and exit with a clear message when none exists.
6. **Top level, `docker-compose.development.yml`:** line 576 (the `&dashboard-env` anchor, used by `dashboard-migrate`) becomes `AISC_MEMBERSHIP_DB_URI: ${AISC_MEMBERSHIP_DB_URI:-postgresql+psycopg2://dashboard_ro:dashboard_ro@postgres:5432/platform}`; line 630 (`dashboard` override) becomes the same with `@localhost:5432/platform`. No `AISC_RESULTS_DB_URI` remains. Also update the header comment "reading the platform's own database read-only". If the orchestrator prefers X1 to own compose, hand over these two lines instead.

### Existing tests that change (S-D13), and exactly how
- **`tests/test_projects.py`**
  - Module docstring: engine dataset "on the project's own connection".
  - `test_s11_1_engine_dataset_is_on_the_results_connection_and_carries_the_version`: rename to `test_s11_1_engine_dataset_is_on_the_project_connection_and_carries_the_version`. Assert `ds["database"] == "AISC Controls mcas"` and `"left join project.system s on s.pid = e.system_id"`; keep the column assertions.
  - `test_s11_4_engine_dataset_filters_on_this_project_only`: becomes "S11.4 as changed by I10.1: the database is the project". Assert `PID not in sql`, `OTHER not in sql`, no `\bwhere\b` and no `project_id`, calling `projects.engine_results_sql()`.
  - `test_s11_4_a_pid_that_is_not_a_uuid_never_reaches_the_sql` (4 cases): keep the cases, and assert `ValueError` from `projects.register_project(bad, "s", "n", store=FakeStore(), controls_password="pw")` and from `projects.project_role_name(bad)`. The pid still becomes part of a connection URI and a role name.
- **`tests/test_results_database.py`**: retarget to `membership_uri` and `AISC_MEMBERSHIP_DB_URI`.
  - Test 1 (configured returns the DSN verbatim), test 2 (unset or blank gives `None`) and test 3 (a `platform_rw` DSN raises `ValueError` matching "read-only") keep their intent.
  - Delete test 4 (`…the_name_is_stable…`). It pins re-registering a Superset connection, which I10.2 removes; the counterpart is `test_i10_2_results_db_registers_nothing_named_aisc_results`.
  - Update the module docstring.
- **`tests/test_project_datasets_db.py`**: keep the exported names `CONTAINER`, `ENGINE_DDL`, `ROOT`, `psql` unchanged; the isolation DB file imports them.
  - `_seed_platform`:
    - Apply the two init files only when `to_regnamespace('core') IS NULL`, exactly as `test_isolation_dashboard_db.py:57` does. Otherwise, once P1 exists, the isolation module (collected first) initialises the cluster and the old fixture fails on `CREATE SCHEMA core`, turning `test_s11_2_member_projects_sql_as_dashboard_ro` red.
    - Keep the platform migrations and the `core.project` rows P and Q.
    - Remove `ENGINE_DDL`, the `core.system` insert and the engine inserts from `platform`.
  - Rename `_seed_controls` to `_seed_project(db, versions, eval_version)` and use it for P's and Q's databases. Each database is created from every template file with the controls migrations applied. Then:
    - Insert the `project.system` rows as platform_rw: P gets V1 (number 1) and V2 (number 2); Q gets QV1 (number 1).
    - Run `ENGINE_DDL`, then `SET ROLE engine_rw; GRANT SELECT ON ALL TABLES IN SCHEMA engine TO dashboard_ro`.
    - Insert the engine rows: `engine.project` with `project_id` = that pid, a metric, and one evaluation stamped V1 (or QV1) with one observation and one measurement.
    - Insert the controls rows, the P answer stamped V2. Inserting the versions before the answer keeps C1's future foreign key (I6.2) satisfied.
  - `Seeded.missing` keys become `platform` and `project`.
  - `test_s11_1_engine_results_carries_the_evaluations_version`: `projects.engine_results_sql()` on `db=seeded.db` as dashboard_ro returns `{("1", V1)}`.
  - `test_s11_4_engine_results_never_returns_another_projects_rows`: in P's database, count where `system_version_pid = QV1` is 0 and the total is 1; in Q's database the only pid is QV1.
  - S11.2 (membership on `platform`) and the controls tests are unchanged apart from the fixture.

### Commands (02-tests.md section 2, BARE container)
Run the recipe without applying the init files: the fixtures apply them. `docker run … postgres:14-alpine` (name `aisc-t-iso-dash-<hex>`), wait for `pg_isready`, then from `apps/results-dashboard`:
`AISC_DASHBOARD_TEST_PG_CONTAINER=$NAME PYTHONPATH=. uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py`, then `docker rm -f $NAME`.
- **Expected:** 133 passed, 0 failed (110 baseline, minus the 1 deleted `test_results_database` case, plus 24 new).
- Quick loop without a container: the same command without the variable (the DB tests skip).
- Top level: `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_compose_isolation.py -k "i10_2 or (i16_4 and dashboard)"`.

### Commits
1. **results-dashboard**, explicit paths `aisc_ext/projects.py aisc_ext/results_db.py aisc_ext/sso.py superset_config.py docker-compose.yml docker-compose.aisc.yml .env.example README.md scripts/bootstrap.sh scripts/verify_review.py tests/test_projects.py tests/test_results_database.py tests/test_project_datasets_db.py`.
   Message: "Isolation D1: the engine dataset on the project's own connection, memberships over AISC_MEMBERSHIP_DB_URI, no AISC Results connection (I10.1-I10.5)".
2. **Top level**, `docker-compose.development.yml apps/results-dashboard` (gitlink).
   Message: "Isolation D1: the dashboard reads memberships over a plain DSN; gitlink".

### Risks and flags for D1
- **New project, no engine tables yet.** `_upsert_dataset` calls `fetch_metadata()` on the project connection. For a project created at runtime, the engine tables exist only after the engine migrates that database (first open, or `aisc-backend-migrate`). The same already holds for controls today. With failures propagating, the platform's retry (`db._unregistered`, `provision_all`) eventually registers it. The rehearsal (stage 5) must check that a project created at runtime gets a working `engine_results_<hex>`.
- **Datasets move at cutover.** The move happens when the platform re-registers every project on its first query after start (`_register_pending` with `_registered_all` false). X1's C9 must delete `AISC Results` only after that has run and a query shows no dataset on it.
- **No new test is wrong.** One note: `test_isolation_dashboard.py:227-232` scans the whole of `superset_config.py`, comments included.

---


---

## WP E2: engine part 2 (the door, run ticket, worker, SPA header)

### Plan overrides (read first; they win over the text below)

- **T6** and **T7** (section 4) are made by E2, each committed alone: the `CONTROLS` artifacts row becomes
  `/api/v1/evaluations/{evaluation_pid}/plugins/status`, and Sean's two webapp tests get the tagged
  `sessionStorage` line (decision 2 (a) below is the one taken).
- "Decisions needed before E2" below are decided: decision 1 is T5/T6/T7; decision 2 is (a).
- **G2**: the `scripts/guard-frozen.sh` G4 subsection is input for V1; E2's top-level commit is only the gitlinks
  `apps/backend apps/eval apps/webapp`.
- Open issue 7 is closed by this WP (section 5 of the plan).

**Depends on:** E1.

**Requirements:** I7.2, I7.3, I7.4, I7.5, I7.11, I2.5 (engine), I16.5 (engine), I17.1 (connections closed), I18 (the API-auth gate survives: `KeycloakAuth` deny-by-default is untouched), S-D8 (E-G1), S-D13 (G4 webapp and eval parts).

### Tests E2 turns green

**`test_isolation_engine.py`**
- `TheDoorOrder.test_i7_2_the_door_order` (17 rows)
- `TheDoorsExemptions`, 3
- `TheWorkersTicket`, 8
- `TheStartRouteMintsTheTicket.test_i7_3_an_editor_starting_a_run_dispatches_the_ticket`

**`test_isolation_engine_db.py`**
- `TheDoorOnPostgres`, 4
- `NothingOfAIsReachableUnderB`, 5 (see the flags on `CONTROLS`)
- `ADroppedDatabase`, 2 (see the flag on `test_i17_1`)

**`apps/eval/tests/test_run_ticket.py`:** all 10 (the settings guard stays green).

**`apps/webapp`:**
- `src/api/projectHeader.i7_4.test.ts`, 3
- `src/components/PluginInstallDialog.i7_4.test.tsx`, 2

### Backend

#### `aisc_backend/project_door.py` (new)

`class ProjectDoor` with `async_capable = True`, `sync_capable = False`, `markcoroutinefunction(self)`.

Constants:
```python
PROJECT_HEADER = "X-AISC-Project"; RUN_HEADER = "X-AISC-Run"; EVALUATION_HEADER = "X-AISC-Evaluation"
INTERNAL_PREFIX = "/api/v1/internal/"
EXEMPT = {"/api/docs", "/api/openapi.json", "/api/v1/app/app-name", "/api/v1/me", "/api/v1/me/admin", "/api/v1/audit"}   # any method
EXEMPT_FOR = {("GET", "/api/v1/plugins"), ("HEAD", "/api/v1/plugins")}
READ_POSTS = re.compile(r"^/api/v1/(?:evaluations/[^/]+/measurements/(?:aggregate|dimension-keys|metric-names|dimension-values/[^/]+)"
                        r"|projects/[^/]+/measurements/aggregate|plugins/[^/]+/config/state)$")   # plan 4's list
def writes(method, path) -> bool   # method not in GET/HEAD/OPTIONS and not READ_POSTS
```

**Order in `__call__`** (on `request.path_info`; anything not under `/api/`, or exempt, passes through without admission):

| step | check | answer |
|---|---|---|
| 1 | no `X-AISC-Project` | 400 |
| 2 | header is not a pid (`projectdb.normalise`) | 404 |
| 3a | worker (path under `/api/v1/internal/`): `X-Internal-Secret` != `os.environ["INTERNAL_API_KEY"]` (read at call time, `hmac.compare_digest`; unset means always wrong) | 401 |
| 3b | worker: `X-AISC-Evaluation` missing, not a pid, or `X-AISC-Run` missing | 403 |
| 3c | worker: ticket != `projectdb.run_ticket(pid, evaluation)` | 403 |
| 3d | worker: path names `/internal/evaluations/<x>` and `<x>` != the named evaluation | 403 |
| 4a | person, only when `keycloak.AUTH_ENABLED`: no bearer (`Authorization: Bearer` or `X-Auth-Request-Access-Token`), or `keycloak.verify_token` raises | 401 |
| 4b | person: realm role `admin` skips membership; otherwise `membership.role_in_project(pid, sub)` raises DatabaseError | 503 |
| 4c | person: role None | 404 |
| 4d | person: role viewer and `writes()` | 403 |
| 5 | `alias = projectdb.alias_for(pid)` | registration only, no connection |
| 6 | `platform_projects.platform_project_exists(pid)` is False: `forget(alias)` | 404 |
| 6' | DatabaseError at step 6 | 503 |
| 7 | `projectdb.open_alias(alias)` in `sync_to_async`: `NoSuchProjectDatabase` | 404 (I2.5) |
| 7' | `MigrationFailed` | 503 |
| 8 | set `admitted` = alias and `admitted_pid` = pid; same-project checks (below) | 404 |
| 9 | `await get_response(request)` | the view's answer |

- Read `keycloak.AUTH_ENABLED`, `keycloak.verify_token`, `membership.role_in_project` and `projectdb.alias_for` off their modules at call time; the tests patch them there.
- `finally` for steps 8 and 9: reset both ContextVars, and close `connections[alias]` and `connections["platform"]` (when present) in `sync_to_async`. This is required: Django's test client disconnects `close_old_connections`, and I17.1 counts sessions.
- Refusals are `JsonResponse({"detail": ...}, status)`.
- The door names nothing in `core`.

**Same-project checks (step 8, on the admitted alias, via `sync_to_async`):**
- `POST /api/v1/projects/for-platform/{x}`: `normalise(x)` must equal the header pid.
- JSON body of `POST /api/v1/projects` and `PATCH /api/v1/projects/{pid}`: `platform_project_id`, when present and not null, must equal the header pid.
- JSON body of `POST` and `DELETE /api/v1/plugins`, `POST /api/v1/plugins/refresh` (`project_uuid`) and `POST /api/v1/evaluations/task` (`project_pid`): `Project.objects.filter(pid=v).exists()` (I7.5). This must run before the view, because `refresh_package` runs before the project lookup and DELETE filters to 204.
- Path `^/api/v1/(projects|stats/projects|project/settings)/<uuid>(/|$)`: an engine project in this database.
- Path `^/api/v1/evaluations/<uuid>(/|$)`: `Evaluation.objects.filter(pid=...).exists()`. This also makes the artifacts `ROUTES` row 404, see issue 8.
- `/api/v1/internal/projects/settings/<uuid>[/by-pid]`: an engine project in this database.
- `/api/v1/internal/files/dataset/<name>` and `/model/<name>`: `AIComponent.objects.filter(data=name, storage_container=Datasets` or `Models).exists()` (I7.11).
- Every internal call: the named evaluation exists in this database.
- Parse the body only for these JSON routes. Never parse multipart (file sizes). A body that does not parse falls through to the view's own 422.

#### `aisc_backend/projectdb.py`

- `run_ticket(platform_pid, evaluation_pid) -> str`:
  ```python
  hmac.new(settings.SECRET_KEY.encode(), f"{normalise(platform_pid)}.{normalise(evaluation_pid)}".encode(), hashlib.sha256).hexdigest()
  ```
- `ticket_is_valid(platform_pid, evaluation_pid, ticket) -> bool`: uses `compare_digest`.

#### `aisc_backend/services/celery_service.py`

- `run_evaluation(evaluation_uuid)` keeps its signature (the frozen router calls it; the stamp test patches it).
- `platform_pid = projectdb.admitted_pid.get()`. If that is None, fall back to `(await Evaluation.objects.select_related("project").aget(pid=evaluation_uuid)).project.platform_project_id`. If still None, raise `HttpError(409, ...)`.
- Then `celery.send_task(RUN_EVAL_TASK, args=[platform_pid, str(evaluation_uuid), ticket])`, all lower-case strings, no DSN.

#### `config/settings.py`

- Add `'aisc_backend.project_door.ProjectDoor'` to MIDDLEWARE, right after CorsMiddleware.
- Add `CORS_ALLOW_HEADERS = (*default_headers, "x-aisc-project")`.

`config/urls.py` and every `routers/*.py` stay byte-identical. The only settings, urls or routers file E1 and E2 change is `config/settings.py` (I7.12 list).

### Worker (`apps/eval`)

#### `aisc_eval/service/api_client.py`

```python
@dataclass(frozen=True) class Run: platform_pid; evaluation_pid; ticket
def headers() -> dict   # at call time
@contextmanager def acting_for(run)   # ContextVar current_run
```

- `headers()` returns `{"X-Internal-Secret": env.INTERNAL_API_KEY, "X-AISC-Project": str(run.platform_pid), "X-AISC-Run": run.ticket, "X-AISC-Evaluation": str(run.evaluation_pid)}`; with no run, only the secret.
- Every function keeps its signature and uses `headers()`. This keeps `tests/services/test_api_client.py::test_get_evaluation(evaluation_uuid)` passing.
- The module-level `headers` dict goes. The file must not read `DJANGO_SECRET_KEY`.

#### `aisc_eval/celery_tasks.py`

Signatures (the test pins only `run_evaluation`'s):
```python
run_evaluation(self, platform_pid, evaluation_pid, ticket)
install_package(self, package_name, version, platform_pid, evaluation_pid, ticket, evaluation_plugin_pids)
run_plugin(self, package_name, plugin_name, version, plugin_config, input_components, project_settings,
           platform_pid, evaluation_pid, ticket, evaluation_plugin_pid)
post_measurements(measurements_dict, platform_pid, evaluation_pid, ticket, evaluation_plugin_uuid)
finalize_evaluation(platform_pid, evaluation_id, ticket)
handle_error(platform_pid, evaluation_id, ticket, request, exc, traceback)
```
- Each body runs inside `with api_client.acting_for(Run(...))`.
- Every `.si` and `.s` passes `platform_pid` and `ticket`.
- The one-argument call fails with TypeError before any call.

`env.py`, `celery_app.py` and `env.development` are untouched (the guard test).

### SPA (`apps/webapp`)

#### `src/api/projectHeader.ts` (new; the only module under `src/` that calls the network)

- `PROJECT_HEADER = "X-AISC-Project"`
- `class NoCurrentProject extends Error`
- `isProjectLess(method, url)`: GET or HEAD `/plugins`; `/me`, `/me/admin`, `/app-name`, `/docs`, `/openapi.json`, `/audit`.
- `apiFetch(input: string, init?: RequestInit): Promise<Response>`:
  - `pid = currentPlatformProject()`, checked against the pid regex (an invalid value counts as none).
  - If pid is set, merge `new Headers(init?.headers)` with `X-AISC-Project`. It is also sent on project-less routes: test 1 requires every call to carry it.
  - If pid is null and the URL is an API route that is not project-less, throw `NoCurrentProject` without calling `fetch`.
  - URLs outside the API base pass through unchanged.
  - Call the global `fetch` at call time (the tests replace `globalThis.fetch`).
- `apiAxios`: `axios.create()` with a request interceptor that applies the same rule. `UploadFileField.tsx` keeps its upload progress this way; `apiAxios.put(` does not match the scan regex.

#### Swap `fetch(` for `apiFetch(` (plus one import line) in all 23 current callers

- Sean's frozen files: `src/api/api.tsx`, `src/components/AISystemSettings.tsx`, `src/components/plugin/PluginConfigForm.tsx`, `src/components/plugin/PluginEvaluationForm.tsx`, `src/pages/PluginsConfig.tsx`, `src/pages/PluginStartEvaluation.tsx`, `src/pages/Settings.tsx`
- The rest: `src/MyApp.tsx`, `src/components/{GenericTextDataGrid,LeftBar,PluginInstallDialog,TopBar,EvaluationProgressList,SummaryTable}.tsx`, `src/components/plugin/{ConfigHistory,CSVDataGridChart}.tsx`, `src/pages/{StartEvaluation,GlobalHome,PluginEvaluationsTasks,Plugins,PluginEvaluations,PluginEvaluationMeasurements}.tsx`
- `src/components/UploadFileField.tsx`: `axios.put` becomes `apiAxios.put`, and drop the axios import.
- `GlobalHome` with no project catches `NoCurrentProject` and shows the launcher link (`projectPageUrl`) instead of listing everything.
- `gatewaySession.ts` stays as it is.

#### `scripts/guard-frozen.sh` G4 (webapp and eval)

- **Webapp rule:** each of Sean's files, after `sed 's/apiFetch(/fetch(/g'` and deleting the single `import { apiFetch } from ".../projectHeader";` line (plus lines tagged `// I7.4 (isolation)`, if decision 2 below is (a)), must be byte-identical to 429f62c.
- **Eval rule:** "no commits after e5b1b0a" becomes: files changed between e5b1b0a and HEAD ⊆ {`aisc_eval/service/api_client.py`, `aisc_eval/celery_tasks.py`, `tests/test_run_ticket.py`}. Stage 2's commit 7f7de02 already turned the old rule red.
- On success, no G4 line may mention webapp, apps/eval, plugin-interface or plugin-manager (`test_guard_frozen` filters on those names).

### Commands

- The three backend suites as in E1 (single-database settings for the pre-existing Postgres suite).
- **Eval:** `cd apps/eval; uv run --group test python -m pytest -q -p no:cacheprovider --noconftest tests --ignore=tests/test_basic_integration.py`. Baseline: 5 passed, 1 failed, 1 error.
- **Webapp:** `cd apps/webapp; npx vitest run; npx tsc -b --noEmit`. Baseline: 7 files, 42 passed; record tsc first.
- **Top level:** `scripts/tests/test_guard_frozen.py` (no new reds), and `GUARD_SOURCE=worktree scripts/guard-frozen.sh --only G4`.

### Commits

1. **`apps/backend`:** `aisc_backend/project_door.py aisc_backend/projectdb.py aisc_backend/services/celery_service.py config/settings.py`
   Message: "Isolation E2: the door (X-AISC-Project, membership, run ticket, same-project checks) and the ticket on dispatch"
2. **`apps/eval`:** `aisc_eval/service/api_client.py aisc_eval/celery_tasks.py`
   Message: "Isolation E2: the worker names its project, evaluation and run ticket on every internal call"
3. **`apps/webapp`:** `src/api/projectHeader.ts` and the 24 files listed above (plus the two Sean tests if decision 2 is (a))
   Message: "Isolation E2: one network module for the SPA, which names the current platform project"
4. **Top level:** `scripts/guard-frozen.sh` and the gitlinks `apps/backend apps/eval apps/webapp`
   Message: "Isolation E2: G4 knows the isolation changes of webapp and eval"

### Open issue 7 (confirmed)

- **Where:** `apps/backend/aisc_backend/routers/plugin.py`, `get_plugin_evaluation_results` (`GET /plugins/{evaluation_plugin_pid}/evaluations/{evaluation_uuid}/result`). It makes no `membership.` call.
- **Why the guard test misses it:** `test_every_project_route_is_guarded.looks_project_scoped` lists neither `{evaluation_plugin_pid}` nor `{evaluation_uuid}`.
- **Live exposure:** any valid token plus the two uuids reads that run's measurements and visualisations. Live has 0 evaluation rows today.
- **Closed by:** E2's door. The header is required, membership of the header's project is checked before the database opens, and the ORM sees only that project's database. `plugin.py` stays frozen.
- **Pinned by:** the `ROUTES` row at `test_isolation_engine_db.py:439`, which must answer 404 under B.
- **Interim guard:** none in this pipeline, since live is never touched. If the cutover slips, the user should choose a separate live hotfix: either a one-line `membership.for_evaluation` call in the frozen file, or a gateway rule. Do not add the two tokens to `looks_project_scoped`: the frozen view has no `membership.` call, so that test would stay red for good.

### Open issue 8 (bodies and queries checked against the Ninja schemas)

- Every `ROUTES` body validates.
- One exception: `GET /api/v1/evaluations/{evaluation_pid}/artifacts` (`test_isolation_engine_db.py:409`) is missing the required query parameter `evaluation_plugin_uuid: uuid.UUID`, so Ninja answers 422. E2's door-level evaluation-exists check turns it into a 404 without editing the test.
- Routes that give 200 or 204 instead of 404 unless the door checks them:
  - `for-platform` (it would create A's row in B's database)
  - `DELETE /plugins` (204)
  - `/plugins/refresh` (the registry is called first, so 500)
  - internal `projects/settings` and `by-pid` (200 with an empty list)
  - internal `files/*` (goes to S3)
- All of these are covered by the same-project checks above.

### Tests I believe are wrong (the coder must not edit them; the orchestrator decides)

1. **`test_isolation_engine_db.py:67-128` (`_seed`) together with `:571-579` (`test_i17_1`).**
   - `_seed` uses the ORM in the main thread and never closes `connections[alias]`. Django connections are per thread (`ConnectionHandler.thread_critical = True`), so an engine_rw session to A stays open.
   - `test_i17_1` is the module's first test (alphabetical order) and will count that session, whatever the implementation does.
   - Fix: `connections[alias].close()` in `_seed`'s `finally`.
2. **`test_isolation_engine_db.py:472` (`CONTROLS` `/api/v1/evaluations/{evaluation_pid}/artifacts`).**
   - Without the query it is 422. With it, the route reads every artifact from S3 (`file_repository.get_object(...)["Body"]`), and there is no S3 in the throwaway, so 500.
   - Fix: replace it with `/api/v1/evaluations/{evaluation_pid}/plugins/status`, or add the query and drop the artifact from the seed.
3. **`apps/webapp/src/api/projectHeader.i7_4.test.ts:108-113` ("with no current project the SPA calls no project route").**
   - It is correct for I7.4, but it conflicts with Sean's frozen tests `src/pages/PluginStartEvaluation.test.tsx` and `src/components/plugin/PluginEvaluationForm.test.tsx`.
   - Both render with no platform project and expect `/projects/...` to be fetched, so they break once `apiFetch` refuses.
   - This needs decision 2 below.

### Ambiguities resolved

- **`alias_for` only registers; opening means connecting and migrating.** The core.project existence check comes after `alias_for` and before any connection. That is the only order that satisfies both the DoorCase "admin, not a member" row (stub None, must open, no DB in a SimpleTestCase) and `TheDoorOnPostgres` (admin with an absent pid gets 404).
- **Membership lives in two places.** It comes from `core.project_member` over the `platform` alias (D11). Plan 4's `/authz` over HTTP and its `PLATFORM_URL` are not used; `test_compose.py` pins that PLATFORM_URL is absent.
- **The ticket format is spec I7.3's hex HMAC**, with the evaluation in `X-AISC-Evaluation` (S-D8). Plan 4's `evaluation.mac` format is not used.
- **`migrate_projects` lists pg_database with CONNECT privilege, not core.project rows.** A missing or unprovisioned database is skipped with exit 0; a migration failure exits non-zero.
- **The advisory lock SQL lives in `migrate_projects.py`**, because its test reads that file. The door's first-use path imports `migrate_database` from there.
- **The pre-existing Postgres suite runs under `config.settings_single_database`**, not an environment switch, so the settings probe is not affected.
- **An "engine project of this database" is any `engine.project` row in it.** The database is the project, and rows with a null `platform_project_id` are admin-only already through `membership._require_owner`.
- **Known residual risk:** the worker holds `DJANGO_SECRET_KEY`, which `utils/encryption.py` needs to decrypt secrets. The ticket therefore stops misrouted calls and callers who have only `INTERNAL_API_KEY`, not a compromised worker. I7.3 fixes the key, so this is recorded rather than changed.

### Decisions needed before E2

1. **Fixing the three wrong tests above.** Test-fixture changes only, done by the orchestrator or a test WP.
2. **The webapp conflict. Recommended (a):** add one tagged line (`sessionStorage.setItem('aisc_platform_project', '<pid>'); // I7.4 (isolation)`) to the setup of Sean's two tests, and let G4's normalisation drop tagged lines. RULES allow a test change where the approved design changes the behaviour it pins. **(b)** would weaken I7.4 so that a call with no project goes out without the header and the backend answers 400; that violates the spec text.

---

## WP R1: report composer on project and library databases

### Plan overrides (read first; they win over the text below)

- Order: after R2 and after P2 (it edits `platform/tests/isolate_support.py` line 54, a file P2's suite uses; T1 at
  line 128 was already made by P1).
- **G1**: the compose line is W1's; R1 does not commit `docker-compose.development.yml`.
- **G3**: `report_bed.build()` already builds the old layout from the fixture (P1); precondition 1 below is then
  satisfied. Precondition 2 (report-roles.sql) is done by P1.
- Item 1 of "Existing tests that must change" (`no_database` parameter) is done by R2.
- The old composer migrations move to `apps/report-composer/pre_isolation_migrations/` (N4); X1's C4 reads them from
  `git show f01288a:apps/report-composer/migrations/<file>`, so the move does not affect the cutover.

**Repo:** the top-level repo `~/aisc-isolation`. The composer is a plain folder there, not a submodule. Branch `isolation/2026-09-25`. Never push.

### Requirements and the tests that must turn green

I8.1 to I8.6, I1.1, I1.6, I1.7, I2.5, I2.6, I17.1 and D4, through 56 tests that are red today.

In `apps/report-composer/tests/test_isolation_project_databases.py`:
- `test_i8_2_the_project_baseline_makes_the_four_tables_without_core_or_project_id`
- `test_i8_2_the_library_migration_makes_report_library_preset_without_a_key`
- `test_i8_2_i8_6_the_project_baseline_is_schema_only`
- `test_i8_2_no_old_migration_is_left_for_the_platform_database`
- `test_i8_4_the_runner_keeps_its_lock_number`
- `test_i8_5_the_composer_names_no_other_modules_schema`
- `test_i8_1_the_source_reads_the_project_database_template`
- `test_i8_4_start_migrates_the_library_and_every_project_database`
- `test_i8_2_i1_7_the_project_tables_have_no_project_id_and_keys_on_project_system`
- `test_i2_6_no_reader_reads_the_composers_tables`
- `test_i8_1_a_projects_layouts_live_in_its_own_database`
- `test_i8_1_the_platform_connection_reads_only_core_and_the_library`
- `test_i8_1_the_guard_decides_before_a_project_database_is_opened` (4 cases)
- `test_i8_3_a_version_of_another_project_is_422_system_not_in_project`
- `test_i8_3_the_versions_are_those_of_the_projects_database`
- `test_i8_3_a_generated_report_names_a_version_of_its_database`
- `test_i8_4_a_project_made_after_start_is_migrated_on_first_open`
- `test_i8_4_the_first_open_waits_for_the_lock_of_that_database`
- `test_i8_4_concurrent_first_opens_migrate_once`
- `test_i17_1_one_connection_per_call_closed_after`
- `test_i2_5_a_dropped_project_database_is_404_not_500`
- `test_d4_a_preset_saved_in_a_project_is_in_the_library_and_seen_from_another`

In `apps/report-composer/tests/test_isolation_cross_project.py`:
- `test_i16_5_an_alpha_object_opened_under_beta_is_404` (19 cases)
- `test_i16_5_the_same_id_under_its_own_project_answers` (9 cases)
- `test_i8_3_alphas_template_named_in_a_beta_layout_is_422`
- `test_i8_3_alphas_version_named_in_a_beta_layout_is_422`
- `test_i16_5_beta_lists_nothing_of_alpha`

In the top-level `scripts/tests/test_compose_isolation.py`:
- `test_i8_1_composer_has_a_project_database_template_and_platform_for_the_library`
- `test_i16_4_every_module_dsn_names_a_project_database_except_the_allowed_platform_ones[report-composer]`

`scripts/tests/isolation_bed.py` (steps `migrate_modules`) needs `python -m report_composer.migrate` to create `report_composer.schema_migration` in every project database. That is what satisfies the `report_composer` part of `test_project_grants.py`, `test_fresh_volume.py`, `test_verify_project_databases.py` and `test_isolation_harnesses.py`. Those files as a whole stay red until the other WPs land.

### Preconditions (stop and report to the orchestrator if one fails)

1. `report_bed.build("x", modules=False)` still builds on this branch, including `core.system` from platform migrations 0003 and 0004 (see open issue 1 in 02-tests section 6).
2. `init/report-roles.sql` belongs to P1 (the init files). After isolation it must:
   - not create the `report_composer` schema in `platform`;
   - guard or drop the grants on `core.system`, and drop REFERENCES;
   - stop granting `report_composer_rw` SELECT on every `core` table through `ALTER DEFAULT PRIVILEGES`.

   This is what I1.3 and I1.4 require (`test_fresh_volume.py::test_i1_3_*`, `test_i1_4_a_module_role_reads_only_core_project_and_members_in_platform[report_composer_rw]`). R1 does not edit it; if P1 has not done it, report that.
3. Templates 0006 and 0010 are not required to start. `report_bed_isolated` and `isolation_fixtures.new_project` stand in for them. The final green run should still happen after P1, once the real templates apply.

### Files

**Create:**
- `apps/report-composer/migrations/project/0001_project_database.sql`
- `apps/report-composer/migrations/library/0001_presets.sql`
- `apps/report-composer/report_composer/projectdb.py`

**Move with `git mv`** (resolved ambiguity A1): `apps/report-composer/migrations/0001_report_composer.sql`, `0002_templates_are_looks.sql`, `0003_a_report_points_at_its_project_and_version.sql`, `0004_a_version_of_its_project.sql` and `0005_presets_and_document_settings.sql` go to `apps/report-composer/pre_isolation_migrations/` with the same names. They are outside `migrations/`, so the Dockerfile's `COPY migrations` no longer ships them.

**Change (product code):**
- `apps/report-composer/report_composer/app.py`
- `apps/report-composer/report_composer/migrate.py`
- `apps/report-composer/report_composer/db.py`
- `apps/report-composer/report_composer/api.py`
- `apps/report-composer/report_composer/pages.py`
- `apps/report-composer/report_composer/reports.py`
- `apps/report-composer/report_composer/records.py`
- `apps/report-composer/report_composer/presets.py` (docstring: `report_library.preset`)
- `apps/report-composer/README.md` (Storage and Environment sections)
- `docker-compose.development.yml`, service `report-composer`, add:
  `REPORT_COMPOSER_PROJECT_DATABASE_URL: postgresql://report_composer_rw:${REPORT_COMPOSER_PASSWORD:-report_composer_rw}@postgres:5432/{database}`
  Keep `REPORT_COMPOSER_DATABASE_URL` on `platform`.

**Do not change:** `guards.py` (same logic, still decides membership before any project database opens), `access.py` (keep `role_in_project(database_url, project_pid, subject)`, which a test patches), and `renderer_client.py`.

### Signatures and behaviour

**`app.py`**
```python
def create_app(*, database_url: str | None = None, project_database_url: str | None = None,
               renderer=None, clock=None) -> FastAPI
```
- Defaults come from `REPORT_COMPOSER_DATABASE_URL` and `REPORT_COMPOSER_PROJECT_DATABASE_URL`.
- It must **not** raise or connect at construction. `tests/test_links_unit.py` builds it without a project URL.
- `app.state` holds `database_url` (platform), `project_database_url`, `projects = ProjectDatabases(project_database_url, database_url)`, `renderer` and `clock`.
- Lifespan, in order:
  1. `with db.connect(database_url) as c: migrate.migrate_library(c)`. A failure here is fatal, as today.
  2. `migrate.migrate_everything(database_url, project_database_url, library=False)`. For each database that succeeds, call `app.state.projects.mark_migrated(name)`. A failure is logged with the database name and the exception class only, then skipped.

**`projectdb.py`** (new)
```python
def database_name(pid: str) -> str
    # I1.8: pid must match ^[0-9a-f]{8}-...-[0-9a-f]{12}$ (case-insensitive), else ValueError
    # returns "project_" + lowercase hex
class ProjectDatabases:
    def __init__(self, template: str, platform_url: str) -> None
    def dsn(self, pid: str) -> str                  # ValueError if the template lacks {database}
    def exists(self, pid: str) -> bool              # SELECT 1 FROM pg_database WHERE datname = %s, on platform
    def mark_migrated(self, name: str) -> None
    def forget(self, pid: str) -> None              # I2.5 eviction: forget the migrated mark
    @contextmanager
    def connect(self, pid: str) -> Iterator[psycopg.Connection]
```
How `connect` works:
- On the first open of a database in this process (a per-name `threading.Lock` plus a set), it runs `migrate.migrate_project(conn)` on its own connection. That takes `pg_advisory_xact_lock(8_190_233_707)` in that database and re-reads the history inside the lock.
- Then it opens `psycopg.connect(dsn, row_factory=dict_row)` as one transaction and closes it on exit (I17.1: one connection per call, no pool).
- It must call `psycopg.connect` through the module attribute, because the test spies monkeypatch `psycopg.connect`.
- On `psycopg.OperationalError` at connect time (for the migration connection or the work connection): if `not self.exists(pid)`, call `forget(pid)` and raise `ApiError(404, "not_found", "No such project.")`. Otherwise raise `ApiError(503, "unavailable", …)`. Do not parse the error message.
- A missing `report_composer` schema (template 0010 not applied yet) gives `ApiError(503, "unavailable", …)`.

**`migrate.py`**

It must stay loadable as a standalone file: `test_card_version_keys_orders.py` runs it with `spec_from_file_location` and calls `module.migrate`. So the module top level imports only stdlib and `psycopg`, with no relative imports. Import `report_composer.projectdb` only inside functions.

```python
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
PROJECT = MIGRATIONS / "project";  PROJECT_TABLE = "report_composer.schema_migration"
LIBRARY = MIGRATIONS / "library";  LIBRARY_TABLE = "report_library.schema_migration"
_LOCK = 8_190_233_707              # keep this exact literal (test_i8_4_the_runner_keeps_its_lock_number)
def pending(applied: set[str], directory: Path = PROJECT) -> list[Path]
def migrate(conn, directory: Path = PROJECT, table: str = PROJECT_TABLE, *, create_schema: bool = True) -> list[str]
    # the generic runner: the old tests still call migrate(conn, directory=...)
def migrate_library(conn) -> list[str]   # migrate(conn, LIBRARY, LIBRARY_TABLE, create_schema=False)
def migrate_project(conn) -> list[str]   # migrate(conn, PROJECT, PROJECT_TABLE, create_schema=False); raises if the schema is absent
def migrate_everything(database_url: str, project_database_url: str, *, library: bool = True) -> dict[str, str]
    # optionally the library, then every pid of core.project whose project_<hex> exists in pg_database
    # (pid order); value "ok" or "failed: <ExceptionClass>"
def main(argv=None) -> int
    # reads the two env vars; 0 if everything is "ok", else 1; logs names and counts only
if __name__ == "__main__": raise SystemExit(main())
```
- With `create_schema=False`, the runner never runs `CREATE SCHEMA`. If the schema is missing it raises a clear error.
- The start loop must never create a `report_composer` schema in `platform` (`test_i8_4_start_*` checks that it is absent).

**`db.py`** (project connection = a connection to the project's own database)

- Every `project_id` filter and column goes away. Each function takes a project connection first.
- Change the module docstring so that no `core.system`, `engine.`, `controls.` or `provision.` text remains (the `test_i8_5` regex also scans comments).

Versions:
- `systems(conn)`, `system_of_project(conn, system_pid)`, `latest_system(conn)`, all reading `project.system` with the same columns (`pid::text AS pid, number, name, version AS release`).

Layouts:
- `layout_names(conn)`, `list_layouts(conn)` (`JOIN project.system s`)
- `get_layout(conn, layout_id, for_update=False)`: the row no longer carries `project_id`
- `insert_layout(conn, *, system_pid, template_id, name, description, blocks, who, now, settings=None)`
- `update_layout(...)` unchanged
- `delete_layout(conn, layout_id)`

Templates:
- `list_templates(conn)`, `get_template(conn, template_id, with_logo=False)`, `template_names(conn)`
- `insert_template(conn, *, look, logo, who, now)`, `update_template(conn, template_id, *, look, logo, who, now)`, `delete_template(conn, template_id)`

Reports:
- `insert_report(conn, *, layout_id, layout_revision, system_id, snapshot, created_by, created_at, fmt="pdf", report_id=None)` (no `project_id`)
- `get_report(conn, report_id)` (`LEFT JOIN project.system s`, no layout project filter)
- `running_report`, `finish_report` and `list_reports` unchanged

Presets (on the **platform** connection):
- `list_presets`, `get_preset`, `preset_names`, `insert_preset`, `delete_preset`, all on `report_library.preset`

**`records.py`:** `layout_or_404(conn, layout_id, for_update=False)`, `template_or_404(conn, template_id, with_logo=False)`, `template_of(conn, layout)`, `chosen_template(conn, template_id)`. Keep the error codes: 404 `not_found`, and 422 `template_not_in_project`.

**`api.py`, `pages.py`, `reports.py`:**
- Every project read or write goes through `with request.app.state.projects.connect(g.project["pid"]) as conn:`. Every preset read or write goes through `db.connect(request.app.state.database_url)`.
- `layout_view(layout, project_pid)` keeps the `project_id` key in the API response, filled from the guard.
- `put_layout` keeps its `immutable_field` check.
- `post_layout` keeps its check order: system (422 `system_not_in_project`), then template, then preset (a saved preset is read on platform), then names.
- `save_as_preset` reads the layout on the project connection, closes it, then inserts on platform. The two steps are not atomic, which is acceptable because the preset is a copy.
- `layouts_page` reads presets on a separate platform connection.
- `reports.generate` and `_start` use the project connection. `snapshot_of` is unchanged.
- `get_choices` returns 404 when the version is not in `project.system` (the test accepts 404 or 422).

### Migration SQL (outline)

Both files contain DDL only: no INSERT, UPDATE or DELETE, no text `core.`, and no `project_id` anywhere, including constraint names. Keep the live column order minus `project_id`, and keep the live constraint names where they do not name `project_id`.

**`migrations/project/0001_project_database.sql`**

The final shape of 0001 to 0005, minus `project_id` and minus the preset table. The word "preset" must not appear outside comments.
```sql
CREATE TABLE report_composer.template (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
  font text NOT NULL CHECK (font ~ '^[a-z0-9-]{1,40}$'),
  font_size_pt numeric(4,1) NOT NULL CHECK (font_size_pt BETWEEN 8 AND 16),
  primary_color text NOT NULL CHECK (...), accent_color text NOT NULL CHECK (...),
  logo_mime text CHECK (logo_mime IN ('image/png','image/jpeg','image/svg+xml')),
  logo bytea CHECK (octet_length(logo) <= 1048576), CHECK ((logo IS NULL) = (logo_mime IS NULL)),
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL,
  header_text text CONSTRAINT template_header_text_check CHECK (char_length(header_text) <= 120),
  footer_text text CONSTRAINT template_footer_text_check CHECK (...),
  marking text NOT NULL DEFAULT 'none' CONSTRAINT template_marking_check CHECK (...),
  show_document_id boolean NOT NULL DEFAULT false,
  CONSTRAINT template_name_key UNIQUE (name));
CREATE TABLE report_composer.layout (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  system_id uuid NOT NULL CONSTRAINT layout_system_id_fkey REFERENCES project.system (pid),   -- NO ACTION
  name ..., description ..., revision ..., created_at, created_by, updated_at, updated_by,
  template_id uuid CONSTRAINT layout_template_id_fkey REFERENCES report_composer.template (id) ON DELETE SET NULL,
  language text NOT NULL DEFAULT 'en' CONSTRAINT layout_language_check CHECK (...),   -- kept: move tool I12.6
  toc ... layout_toc_check, numbering boolean NOT NULL DEFAULT false,
  coverage jsonb NOT NULL DEFAULT '[]' CONSTRAINT layout_coverage_check CHECK (jsonb_typeof(coverage) = 'array'),
  CONSTRAINT layout_name_key UNIQUE (name));
CREATE TABLE report_composer.layout_block (... as 0001, FK layout ON DELETE CASCADE ...);
CREATE TABLE report_composer.generated_report (
  id, layout_id uuid NOT NULL REFERENCES report_composer.layout (id) ON DELETE CASCADE, layout_revision,
  system_id uuid NOT NULL CONSTRAINT generated_report_system_id_fkey REFERENCES project.system (pid),
  snapshot, status CHECK (...), pdf, sha256, size_bytes, block_statuses, error_ref, error_code,
  created_by, created_at, finished_at,
  format text NOT NULL DEFAULT 'pdf' CONSTRAINT generated_report_format_check CHECK (...), fingerprint text);
CREATE INDEX generated_report_layout_idx ON report_composer.generated_report (layout_id, created_at DESC);
```
Do not write `ON DELETE` after `REFERENCES project.system (pid)`. Grant nothing (I2.6 gives report_ro and dashboard_ro no access to these tables).

**`migrations/library/0001_presets.sql`**
```sql
CREATE TABLE report_library.preset (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE CONSTRAINT preset_name_check CHECK (char_length(name) BETWEEN 1 AND 120),
  description text NOT NULL DEFAULT '',
  language text CONSTRAINT preset_language_check CHECK (...),
  toc text CONSTRAINT preset_toc_check CHECK (...), numbering boolean,
  blocks jsonb NOT NULL CONSTRAINT preset_blocks_check CHECK (jsonb_typeof(blocks) = 'array'),
  source_project_id uuid,          -- NULL, no foreign key (D4)
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
```
The word REFERENCES must not appear in any case, and neither may `core.` or `report_composer.`.

**Tracking tables:** the runner creates `report_composer.schema_migration` in each project database and `report_library.schema_migration` in platform, both as `(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())`.

### Existing tests that must change (S-D13; list each one in the WP notes)

The reason is the same everywhere: the approved design moves the composer's tables into the project databases and the presets into `report_library`. No assertion is weakened.

1. **`scripts/lib/report_bed_isolated.py`** (only if R2 has not already done it): add the parameter `build_isolated(label="iso-rep", *, modules=True, no_database=frozenset(NO_DATABASE))`, used in the two loops over `pids`. The default leaves the new tests' beds unchanged. Legacy beds pass `no_database=frozenset()` so gamma keeps its role as "another project alice edits" with its version C_V1 (resolved ambiguity A2).
2. **`tests/conftest.py`**:
   - `bed` becomes `report_bed_isolated.build_isolated("composer", modules=False, no_database=frozenset())`.
   - Add a helper `pdb_of(key="A") -> report_bed.project_db(IDS[key])`.
   - `make_client` sets `REPORT_COMPOSER_PROJECT_DATABASE_URL` and passes `project_database_url=bed.project_db_template("report_composer_rw")`.
   - `clean_layouts` truncates the tables in `pdb_of(k)` for A, B, C and E, with `check=False`.
   - Update the docstring's `create_app` line.
3. **`tests/v2_fakes.py`**: `clean_presets` deletes from `report_library.preset` on platform. `scalar_json(bed, sql, db="platform")` gains a `db` parameter.
4. **`tests/test_api_layouts.py`**:
   - `test_r4_1_3_migrations_run_at_start`: count `report_composer.schema_migration` in `pdb_of("A")`. The owner assertion becomes "the owner of table `report_composer.layout` in alpha's database is `report_composer_rw`", plus "the owner of schema `report_library` in platform is `report_composer_rw`". In a project database the schema itself belongs to platform_rw (I1.2, D10).
   - `test_r3_10` (line 148) and `test_r3_13` (line 180): use `pdb_of("A")`.
5. **`tests/test_api_reports.py`**: lines 38, 48, 92, 104 and 118 use `pdb_of("A")`. Line 125 inserts into `pdb_of("A")` without the `project_id` column.
6. **`tests/test_p2_english_only.py`**: the layout lines (40, 127, 200) use the layout's project database (alpha). The preset lines (139, 215) use `report_library.preset` on platform. Line 153 calls `scalar_json(..., db=pdb_of("A"))`.
7. The same database swap applies to:
   - `tests/test_v2_layout_settings.py:187` (`pdb_of("A")`)
   - `tests/test_v2_pages.py:81,251` (`pdb_of("A")`)
   - `tests/test_v2_reports.py:54,110` (`pdb_of("A")`)
   - `tests/test_v2_presets.py:279` (`report_library.preset` on platform)
8. **`tests/test_v2_browser.py:35-36`**: pass `project_database_url=bed.project_db_template("report_composer_rw")`.
9. **`tests/test_e2e.py` and `tests/test_e2e_v2.py`**:
   - `full_bed` becomes `report_bed_isolated.build_isolated("e2e" / "e2e2", modules=True)`.
   - Set `REPORT_COMPOSER_PROJECT_DATABASE_URL` and pass `project_database_url=full_bed.project_db_template("report_composer_rw")`.
   - `test_e2e_v2.py:153` reads `report_bed.project_db(IDS["E"])`.
   - These tests stay red until R2 is in.
10. **`tests/test_migration_keys.py`**: it pins pre-isolation 0003 and 0004, which cutover step C4 still runs live. Keep it for the moved files:
    - `MIGRATIONS` becomes `APP / "pre_isolation_migrations"`.
    - Give it its own module-scoped shared bed, `report_bed.build("composer-keys", modules=False)`.
    - Apply the files with the generic `migrate(conn, directory=…)` as `report_composer_rw`, instead of starting the app.
    - Use a local cleanup on platform instead of `clean_layouts`.
    - All assertions stay as they are.
11. **`tests/test_v2_migration.py`**:
    - `M0005` is read from `pre_isolation_migrations/`.
    - The `mig` fixture runs 0001 to 0004 from there, inserts the old rows, then runs 0005 with the generic runner (what C4 does) instead of "the app starts and runs 0005". The R-D.1 and R-U2.4 tests lose their `client.get("/api/block-types")` trigger and keep their assertions.
    - A new module fixture `moved` builds an isolated bed. It copies project A's rows of `template`, `layout`, `layout_block` and `generated_report` from `mig`'s platform (after 0005) into alpha's database by column name, without `project_id` (what `isolate copy` does), then starts the new app.
    - The three `test_r_c_3_*` tests use `moved`, with their assertions unchanged.
12. **Other repos' helpers that read the old files** (path only):
    - `platform/tests/isolate_support.py:54`: `COMPOSER_MIGRATIONS = REPO / "apps" / "report-composer" / "pre_isolation_migrations"`. Tell P2 about this.
    - `scripts/tests/test_db_consistency.py:140`: the same directory.
    - `scripts/tests/test_card_version_keys_orders.py:148,187`: `RC / "pre_isolation_migrations"`.

    These pin the old shared layout until V1, X1 or stage 7 retire them.
13. **Optional:** add `"REPORT_COMPOSER_PROJECT_DATABASE_URL"` to `report_bed.DSN_ENV_VARS` (additive, refuses a :5432 value).

No other existing composer test needs a change. Everything else goes through the API, and the gamma cases work because gamma now has a database in the legacy bed.

### Commands

Composer suite, from `apps/report-composer`:
```
env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL REPORT_GENERATOR_DIR=/home/listuser/aisc-isolation-report-generator uv run --extra dev pytest -q -p no:cacheprovider
```
- Baseline: 427 passed.
- Target: 483 passed, 0 failed (427 existing plus 56 new). The e2e tests need R2.

Top-level, from the repo root:
```
uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests/test_compose_isolation.py scripts/tests/test_db_consistency.py scripts/tests/test_card_version_keys_orders.py scripts/tests/test_report_stack.py
```
- The report-composer cases must be green.
- Known baselines stay as they are: db_consistency 2 failed, report_stack 2 failed. `test_card_version_keys_orders` must stay green.

Move tool fixture self-tests, in `platform/` on a throwaway (02-tests section 2 recipe, with `PLATFORM_TEST_DATABASE_URL` and `PLATFORM_TEST_SUPERUSER_URL` set):
```
uv run --extra dev pytest -q -p no:cacheprovider tests/test_isolate.py -k fixture
```
3 passed.

Stopping rule: stop on any precondition failure, or if a pre-existing test regresses. Checkpoint after each suite. At the end, `docker ps -a --filter name=aisc-t-` must list nothing.

### Commits (top-level repo, explicit paths, no push)

1. Tests and infrastructure (S-D13):
   ```
   git add apps/report-composer/tests/{conftest,v2_fakes,test_api_layouts,test_api_reports,test_p2_english_only,test_v2_layout_settings,test_v2_pages,test_v2_reports,test_v2_presets,test_v2_browser,test_e2e,test_e2e_v2,test_migration_keys,test_v2_migration}.py platform/tests/isolate_support.py scripts/tests/test_db_consistency.py scripts/tests/test_card_version_keys_orders.py [scripts/lib/report_bed_isolated.py scripts/lib/report_bed.py]
   ```
   Message: "Isolation R1: composer tests run on project databases; the pre-isolation migrations are read from pre_isolation_migrations (S-D13, named in the WP notes)"
2. Product code:
   ```
   git add apps/report-composer/migrations/project/0001_project_database.sql apps/report-composer/migrations/library/0001_presets.sql apps/report-composer/pre_isolation_migrations/ apps/report-composer/migrations/000{1,2,3,4,5}_*.sql apps/report-composer/report_composer/{app,projectdb,migrate,db,api,pages,reports,records,presets}.py apps/report-composer/README.md docker-compose.development.yml
   ```
   Message: "Isolation R1: the composer keeps each project's layouts, templates and reports in the project's database and presets in report_library (I8.1..I8.6)"

---


---

## WP V1: verification, consistency, grants repair and harness scripts

### Plan overrides (read first; they win over the text below)

- **G2**: V1 is the only writer of `scripts/guard-frozen.sh`, `scripts/lib/throwaway-pg.sh`,
  `scripts/test-pipeline-chain.sh`, `scripts/pipeline_chain/*`, `scripts/tests/test_guard_frozen.py` and
  `scripts/tests/test_card_version_keys_orders.py`. It takes the G4/G5 file lists from E1's and E2's notes (the
  E1 section's "scripts/guard-frozen.sh" subsection describes the same G1 normalisation; where it and the text
  below differ, the text below wins, e.g. `--no-privileges` dumps and the f01288a reference trees).
- `test_card_version_keys_orders.py` (it pins composite keys that I1.6/I1.7 remove, on the old layout) is kept as a
  historical regression by pinning its trees to f01288a, like `guard-frozen.sh --orders`; its assertions do not
  change.
- G4 of guard-frozen drops lines tagged `// I7.4 (isolation)` before comparing Sean's webapp files (T7).
- The controls reader-grant gap (step 4, "Cross-WP gap") is closed by C1 (N5), not V1; V1 only checks it.
- `tpg_project_db`: the implementation below (psql replay as platform_rw) is taken; it must also call
  `aisc_setup.apply_role_setting` indirectly by applying the template files as they are (they do), so the
  throwaway cluster needs `init/project-databases.sql` applied first (it installs the function in template1).
- `test_isolation_harnesses.py::test_i18_7_isolation_scripts_print_no_secret` turns green only after X1.

**Repo:** top level `~/aisc-isolation`. Chain test edits may touch the qualification, control-objectives and backend submodules (see step 8).
**Depends on:** P1..D1 (spec). **Requirements:** I2.7, I7.12 (guard), I11.3, I16.1..I16.7, I17.1 (budget), I18.7, I19.1, I19.2, I19.3.

### Tests it turns green
- **`scripts/tests/test_isolation_harnesses.py`**
  - Static, red today (checked by a run): `test_i11_3_project_schemas_name_every_module`, `test_i11_3_platform_schemas_are_the_shared_ones_only`, `test_i19_2_throwaway_pg_has_tpg_project_db`, `test_i19_2_harnesses_target_project_databases[guard, chain]`, `test_i7_12_guard_g1_compares_engine_definitions_in_a_project_database`, `test_i19_3_dashboard_queries_run_the_engine_dataset_on_a_project_database`, `test_i16_6_checks_no_longer_read_core_system`, `test_i16_6_checks_cover_card_component_against_the_engine`.
  - Against the bed: `test_i19_2_tpg_project_db_makes_a_project_database_with_the_template`, `test_i16_6_a_clean_isolated_bed_passes_every_data_check`, `test_i16_6_c7_every_module_tracker_is_checked[4]`, `test_i16_6_c4_*` (2), `test_i16_6_c8_lints_the_project_schemas`, `test_i16_6_c3_*`, `test_i16_6_card_component_*`, `test_i16_6_c6_*`.
  - Stays green: `test_i11_2_the_database_rule_is_unchanged`, and `test_i19_2_n6_throwaway_rows_parse_a_single_row` (N6 is **already fixed** by 343b1fe; do not touch `Throwaway.rows`).
  - Not greenable by V1 alone: `test_i18_7_isolation_scripts_print_no_secret` needs X1's `scripts/isolation/*.sh` (2 or more files plus V1's script).
- **`scripts/tests/test_verify_project_databases.py`:** all 22 (static, and against the bed).
- **`scripts/tests/test_project_grants.py`:** V1's own `test_i2_7_*` (4). Every other test there is the integration proof of P1, the module WPs and V1 together, and must be green at V1's end (see the controls gap below).
- **`test_isolation_fixture.py` and `test_isolation_unchanged.py`:** stay green (6 tests, checked). The fixture belongs to X1.

### Existing tests (the 226 passed, 25 known failures baseline) and how each changes
Known failures on the baseline (read from stage 2's run log):
- `test_guard_frozen` 11: the reference build fails, plus G4 "Sean's files differ: routers/plugin.py config/settings.py pyproject.toml".
- `test_pipeline_chain` 5: setup failed.
- `test_schema_docs` 4: homepage menu, unrelated.
- `test_db_consistency` 2: C1 orphans `project_d000…`/`project_f000…` from report_bed.
- `test_report_stack` 2: `test_d6_guard_init_files_do_not_mention_report_roles`, `test_final_guard_frozen_passes`.
- `test_llm_keys` 1: homepage.

Files that pin today's layout and must change (S-D13), and how:
1. **`scripts/tests/test_db_consistency.py` (582 lines, whole file).** Rebuild it on `isolation_bed.build("consist-old")`: real migrations, so the trackers exist for C7. Add a fake `keycloak` database (as today) and a minimal `superset` database (the `aisc_comment` and `aisc_review_request` columns the seed uses). Seed A and B through `project.system` (superuser, `session_replication_role = replica`) and module tables without `project_id`. Map each case:
   - C1: unchanged. The 2 known reds disappear because there are no M/D orphans.
   - C2: known platform schemas become `core, catalogue, form_library, report_library, public`. `junk` stays FAIL; the leftover databases stay FAIL; the catalogue is never flagged.
   - C3: the card or assessment against `project.system` of the same database; messages name the database.
   - C4: the "belongs to another project" cases become "a pid of B's `project.system` planted in A's table does not resolve here" (FAIL, names the database). The cases stay; only the premise changes (FKs make cross-project stamps impossible).
   - C5: `report_composer.*_by` is read from the project databases.
   - C6: per project database.
   - C7: template, controls, qualification, control_objectives, engine and report_composer trackers.
   - C8: the lint fixture's module schemas move into a project database.
   - `test_every_connection_is_read_only` and `test_the_script_passes_a_clean_bed_and_fails_a_broken_one`: keep.
2. **`scripts/tests/test_report_grants.py`.** It pins report_ro on the platform module schemas and template1 default privileges. Rewrite on `report_bed_isolated.build_isolated("grants")`. The report_ro tables in `platform` (`test_r6_1_report_ro_reads_the_listed_tables`, `test_d6b_plugin_config…`, `test_d6b_engine_tables_outside_the_list…`, `test_d6b_a_new_module_table_is_not_readable`, the writes on `platform` module tables) move to the project databases of A, B and E.
   - `test_r6_1_report_ro_reads_core`: `core.project` only; `core.system` is not readable (I1.4).
   - `test_d6c_a_project_database_made_later_is_readable`: it is readable **after the next `report-grants.sh` run** (I2.7), not through template1's default privileges (I2.6 forbids them).
   - Superset cases: unchanged.
   - Composer cases (`test_d13_*`, `test_r4_4_2_*`, `test_r7_3_3_*`) take R1's final grants (report_library owner; SELECT on core.project and core.project_member only; CONNECT to project databases). Take the wording from R1's WP notes; if R1 left them, V1 edits them.
3. **`scripts/tests/test_guard_frozen.py`.** No assertion change if the guard keeps its verdict texts: keep `G1 PASS (engine schema equals e34fca3)` and keep writing `$OUT/engine.candidate.sql`. Update docstrings only (S1.1 now "in a project database").
4. **`scripts/tests/test_pipeline_chain.py`:** no change (it pins only CHAIN PASS and BREAK texts and the five link names).
5. **`scripts/tests/test_schema_docs.py`:** no change. Keep the headings "This project" and "Shared platform"; never write `project_` in platform labels (`test_without_a_project_only_the_shared_platform_is_offered`).

### Changes, file by file

1. **`inspector/schema-docs/server.py` (I11.3)**
   - `PROJECT_SCHEMAS` in pipeline order: `project` ("AI card versions", every saved version of this project's card, numbered, only the latest changes), `qualification`, `controls`, `control_objectives`, `engine`, `report_composer` (move and adapt the sentences from `PLATFORM_SCHEMAS`), `llm`, `provision`.
   - `PLATFORM_SCHEMAS` is exactly `core` (`("Projects and their members", …)`), `catalogue`, `form_library` ("Form library", the forms every project may use; a project keeps its own copy of each version it uses), `report_library` ("Report presets", shared presets that hold no project data).
   - Replace the lede "Modules that are not per project yet keep their data here…" with one about what every project shares. Keep `DATABASE`.

2. **`scripts/lib/throwaway-pg.sh` (I19.2)**
   - At source time, `TPG_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)`.
   - New `tpg_project_db() { # pid [template_dir]`:
     - Validate the uuid (the I1.8 regex, case-insensitive) and lowercase it; `db=project_<hex>`.
     - If the database is absent, `tpg_as platform platform_rw -c "CREATE DATABASE \"$db\""`.
     - Read the applied names, tolerating a missing table: `tpg_as "$db" platform_rw -tA -c "SELECT name FROM provision.template_migration"`.
     - Pipe one transaction as platform_rw (`tpg_as "$db" platform_rw -f -`), mirroring `platform_service.migrate`: `BEGIN; SELECT pg_advisory_xact_lock(8190233419); CREATE SCHEMA IF NOT EXISTS provision; CREATE TABLE IF NOT EXISTS provision.template_migration (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());`, then for each pending file of `${2:-$TPG_ROOT/platform/project-template}` in sorted order: its text, then `;`, then `INSERT INTO provision.template_migration (name) VALUES ('<file>')`; then `COMMIT;`.
     - Print `$db` on stdout.
   - No literal `127.0.0.1:`. S0.3 (`test_guard_frozen.py:77-88`) scans this file.

3. **`scripts/db_consistency/checks.py` (I16.6), plus `scripts/verify-db-consistency.sh` header text**
   - The string `core.system` must appear in **no** non-comment line, docstrings included.
   - A shared `_dbs(cl)` yields `(db, pid, slug)` for project databases that have a `core.project` row (orphans are C1's).
   - C1: unchanged.
   - C2:
     - `KNOWN_PLATFORM_SCHEMAS = {"core","catalogue","form_library","report_library","public"}`.
     - `RETIRED_PLATFORM_SCHEMAS = {"engine","qualification","control_objectives","report_composer"}`: WARN "retired, pending the stage-7 drop".
     - A `core` table other than the three: WARN, naming it from the catalog.
   - C3, per database:
     ```sql
     SELECT s.pid::text, s.number, q.id, q."systemName", s.name, q."systemVersion", coalesce(s.version,''), q.company, coalesce(s.provider,'')
       FROM qualification.qualification q JOIN project.system s ON s.pid = q.system_id
     ```
     plus the control_objectives name rule. Messages start with the database name and name the card or assessment id.
   - C4, per database (FAIL unless noted), each message naming the database and the row id:
     - `system_id` of `qualification.qualification`, `control_objectives.project`, `report_composer.layout`, `report_composer.generated_report`, `engine.evaluation` (by `pid`), and `controls.submission_answer.system_version_pid`, each `LEFT JOIN project.system`, must resolve.
     - `controls.submission_answer.system_version_number` equals that version's `number`.
     - `generated_report` follows its layout (exists, same `system_id`).
     - `engine.project.project_id`: NULL is WARN; any value other than this database's pid is FAIL.
     - **card_component:**
       ```sql
       SELECT c.id, c.component_pid::text FROM qualification.card_component c
        WHERE NOT EXISTS (SELECT 1 FROM engine.ai_component a WHERE a.pid = c.component_pid)
       ```
       FAIL naming the database and the component pid. Run it only when both tables exist.
   - C5: add `report_composer` `*_by` columns of every project database.
   - C6: the same query per database; the message is prefixed with the database.
   - C7, per project database (a missing tracker is a FAIL naming it; `lacks …` otherwise):
     - `provision.template_migration` against `platform/project-template/*.sql`.
     - `controls._prisma_migrations` and `qualification._prisma_migrations` (finished, not rolled back) against the directories of `apps/controls/prisma/migrations` and `apps/qualification/prisma/migrations`.
     - `engine.django_migrations WHERE app='aisc_backend'` against the stems of `apps/backend/aisc_backend/migrations/[0-9]*.py`.
     - `report_composer.schema_migration` against `apps/report-composer/migrations/project/*.sql`.
     - `control_objectives.alembic_version.version_num` equals the head: revisions in `apps/control-objectives/alembic/versions/*.py` that no `down_revision` names, parsed with a regex.
     - Optionally, in `platform`, `form_library` and `report_library` trackers when their directories exist.
     - Put the heads logic in a new `scripts/db_consistency/heads.py`; the verify script reuses it.
   - C8: `platform` (`core`, `form_library`, `report_library`); each project database (`project`, `qualification`, `control_objectives`, `report_composer`, `controls`; never `engine`); superset `aisc_*`. Labels are the database names.

4. **`scripts/report-grants.sh` and `init/report-ro-grants.sql` (I2.7)**
   - `report-ro-grants.sql` keeps **only** the superset section. It still exists and is still mounted, as required by `test_report_stack.py::test_d6_report_grants_*`.
   - `report-grants.sh` (sh, superuser, idempotent):
     - Wait for `pg_isready` only. No `engine.measurement` wait, and no `-d platform -f`.
     - `psql -v ON_ERROR_STOP=1 -d postgres -f "$HERE/report-ro-grants.sql"`.
     - In `template1`: `ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw REVOKE SELECT ON TABLES FROM report_ro` (undoes the old line 49, which new project databases would copy).
     - Then, for each `^project_[0-9a-f]{32}$` database, one `DO $grants$` heredoc. For each reader of `report_ro` and `dashboard_ro` that exists:
       - CONNECT, and USAGE on those of `project, controls, qualification, control_objectives, engine, report_composer` that exist.
       - SELECT on exactly the I2.6 list (`project.system`, `controls.checklist` … `engine.artifact`), skipping any `to_regclass` that is NULL. `engine.plugin_config` gets column-level `(id, plugin_id)` only.
       - Revoke SELECT on every other table of those schemas plus `llm.*`, so secrets and bookkeeping stay unreadable.
       - `ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw [IN SCHEMA controls] REVOKE SELECT ON TABLES FROM report_ro, dashboard_ro`.
     - The literals `'project'`, `qualification.`, `control_objectives.`, `engine.` and `dashboard_ro` appear in the text (`test_i2_7_…covers…`).
     - Echo only database names.
   - **Cross-WP gap:** `apps/controls/prisma/migrations/20260923210100_dashboard_reads_controls/migration.sql` grants `SELECT ON ALL TABLES` (so `_prisma_migrations` too) and a **default privilege** to dashboard_ro in every project database. That breaks `test_project_grants.py::test_i2_6_readers_see_exactly_the_listed_tables[controls]` and `::test_i2_6_no_default_privilege_grants_to_a_reader`, and report_ro gets no controls SELECT from a migration. It needs a new controls migration (C1's repo):
     ```sql
     ALTER DEFAULT PRIVILEGES FOR ROLE controls_rw IN SCHEMA controls REVOKE SELECT ON TABLES FROM dashboard_ro;
     REVOKE SELECT ON controls."_prisma_migrations" FROM dashboard_ro;
     -- DO block: GRANT SELECT on the five tables TO report_ro when the role exists
     ```
     If C1 did not ship it, V1 adds it in `apps/controls` and commits there.

5. **`scripts/verify-project-databases.sh`** (new, `chmod +x`; I16, S-D11)
   - bash, `set -uo pipefail` (never `-x`).
   - Usage: `[--privileges] [--final-layout]`.
     - `--privileges` runs only I16.1 and I16.2 (cutover C9).
     - `--final-layout` adds I16.2's stage-7 exactness. Avoid the name `--after-drop`: `\bDROP\s` in `test_verify_project_databases.py:51` rejects "drop" followed by a space anywhere.
   - Connection: PG\* as `verify-db-consistency.sh`, PGPASSWORD from the postgres container when unset, never printed. All SQL runs from one embedded Python heredoc: `uv run --no-project --quiet --with 'psycopg[binary]' python - "$@" <<'PY'`. The host has no psql, and the static test needs the SQL in the `.sh` body. Connect with `options="-c default_transaction_read_only=on"`.
   - Output lines: `  PASS|FAIL|WARN I16.x <text>`. Exit 1 on any FAIL.
   - **Keep collecting after a FAIL**, so I16.7's WARN still prints (`test_i16_7_…`).
   - **Wording rule** (`:47-53`, case-insensitive, every non-comment line including messages): no `GRANT`, `REVOKE`, `TRUNCATE`, `ALTER TABLE|ROLE|SCHEMA|DATABASE`, `DROP `, `DELETE FROM`, `INSERT INTO`, `UPDATE x SET`. Detect non-SELECT table rights with `aclexplode(relacl)` and `privilege_type <> 'SELECT'` rather than naming TRUNCATE. No `echo`/`printf` line may mention a `$…_URI`, `DATABASE_URL`, `_DSN`, `PASSWORD`, `TOKEN`, `SECRET` or `_KEY` variable; do the printing from Python.
   - **I16.1, platform.** Mirror `test_fresh_volume.py:155-183` exactly: table privileges outside what the role owns, via `has_table_privilege`.
     - The six module roles (qualification_rw, control_objectives_rw, controls_rw, engine_rw, report_composer_rw, catalogue_rw): exactly `{core.project SELECT, core.project_member SELECT}`.
     - dashboard_ro: `{core.project_member SELECT}`. report_ro: `{core.project SELECT}`.
     - Schema USAGE only on `core` (the owners of `form_library`, `report_library` and `catalogue` are excluded). CREATE nowhere but owned schemas.
     - FAIL lines name the relation (`core.project_member`).
   - **I16.1, project databases.**
     - Each module role: USAGE and CREATE on its own schema; USAGE on `project`; SELECT and REFERENCES on `project.system`; nothing on `llm`, `provision` or another module schema. FAIL lines name the role (`qualification_rw`).
     - Readers: exactly the I2.6 tables and the `plugin_config (id, plugin_id)` columns (`has_column_privilege`). FAIL lines name the table (`engine.project_config`).
     - Readers: no row in `pg_default_acl`.
     - `PUBLIC`: no CONNECT (`aclexplode(datacl)` grantee 0).
     - `inspector_ro`: no write anywhere.
   - **I16.2.** Every platform schema outside I1.3, and `core.system` if present, has no USAGE or CREATE or table right for any non-superuser role except `inspector_ro`. It reads everything through `pg_read_all_data` by design (I11.1); state that exclusion in the output. With `--final-layout`: the schemas are exactly I1.3, and `core` has exactly its three tables. Uses `has_schema_privilege`.
   - **I16.3.**
     - Every `core.project` has `project_<hex>`; print the database name so the hex appears.
     - `provision.template_migration` equals the repository's template list; print the missing file name.
     - Every module tracker is at head: reuse `db_consistency.heads`; print the module name.
     - `project.system`: `number > 0` and unique (`GROUP BY number HAVING count(*) > 1`).
     - Every `system_id` of every module resolves in the same database: the C4 list, printing the dangling pid.
   - **I16.4** (skipped when `VERIFY_SKIP_CONTAINERS=1`):
     - For the running containers `qualification-web`, `control-objectives`, `aisc-backend`, `report-composer`, `report-renderer` and `dashboard`, read `docker inspect <c> --format '{{range .Config.Env}}{{println .}}{{end}}'` inside Python and reduce each DSN to its database part.
     - Allowed `platform` DSNs, as in `test_compose_isolation.py:167-175`: qualification `FORM_LIBRARY_DATABASE_URL`, control-objectives `DATABASE_URL`, engine `DB_NAME=platform`, composer `REPORT_COMPOSER_DATABASE_URL`, renderer `REPORT_PLATFORM_DATABASE_URL`, dashboard `AISC_MEMBERSHIP_DB_URI`.
     - Every module except the dashboard names `{database}` or `project_`.
   - **I16.5** (skipped when `VERIFY_SKIP_FUNCTIONAL=1`):
     - Needs `VERIFY_BASE_URL` (default `http://localhost:8100`) and `VERIFY_ACCESS_TOKEN` (a member token read from env, never printed). When the token is absent: FAIL "not run", never a silent pass.
     - Two throwaway projects A and B via `POST /projects`. In A: a card (qualification API), an assessment (`POST /p/{pid}/projects`), an engine evaluation (`/api/v1/…` with `X-AISC-Project`), a layout (composer), and a controls answer. Controls has no JSON API, so the answer is the one direct write, as controls_rw in A's database; name that in a comment.
     - Assert absence in B's database, and 404 for A's ids under B's pid, on qualification, control-objectives, controls, engine and report.
     - Delete A and B at the end, in a `finally`.
     - The body must contain `/projects`, `404` and the five module names.
   - **I16.6:** `(cd scripts && uv run … python -m db_consistency)`; its exit status counts.
   - **I16.7:**
     - `budget = count(core.project) * ${VERIFY_PER_PROJECT_CONNECTIONS:-11} + ${VERIFY_BASE_CONNECTIONS:-20}` (D7).
     - If `budget > 0.8 * current_setting('max_connections')::int`: print `WARN I16.7 … consider PgBouncer (D7)` on one line; never a failure.
     - Check: 2 projects give 42 < 80; 12 give 152 > 80.

6. **`scripts/verify.sh` and `scripts/verify-db-access.sh` (I19.1)**
   - `verify.sh` line 35: `verify-one-database.sh` becomes `verify-project-databases.sh`. Keep `verify-one-database.sh` itself untouched (retired from `verify.sh` only; the catalogue test's docstring names it).
   - `verify-db-access.sh`: keep sections 1, 6 and 7. Section 2 reads `core.project` and `core.project_member` and cannot write them, and never mentions `core.system`.
   - Replace sections 3 to 5 with a throwaway `project_<random 32 hex>` on the same cluster:
     - Created as platform_rw with the template, like `tpg_project_db`, through `docker exec "$PGC"`. A `trap` removes it with `WITH (FORCE)` as platform_rw.
     - Probes: each module role creates a probe in its own schema and is refused in another module's schema, `llm` and `provision`; reads `project.system` and cannot write it. Readers read `project.system` and cannot create or write.
   - The first occurrence of `project_` must come before any `qualification.x` or `engine.x` text, header comments included (`:94`).

7. **`scripts/guard-frozen.sh` (I7.12, I19.2).** Recommended single owner: **V1**, with E1 and E2 supplying the exact file lists in their WP notes. E1 does not edit this file. The reason: it needs `tpg_project_db` (V1) and E1's `migrate_projects`, and the G4 allow-lists are final only after E2. One editor, one set of hunks.
   - `prepare_trees`: add `platform/project-template` to `cand/top`.
   - **Reference build (historical):** `tpg_init_platform "$WORK/live/top"` instead of the candidate init. After P1 the candidate init no longer creates the module schemas in `platform`, so `e34fca3` and `e112001` could not migrate there.
   - **G1 candidate:**
     - Candidate init and platform migrations, then a `core.project` row for `$MCAS_PID` as platform_rw.
     - `tpg_project_db $MCAS_PID "$WORK/cand/top/platform/project-template"`.
     - `(cd cand/backend && DB_* as today with DB_NAME=platform "$PY" manage.py migrate_projects)`.
     - `tpg_dump project_<hex> --schema-only --schema=engine --no-privileges > "$OUT/engine.candidate.sql"`. Removing the old `tpg_dump platform … > "$OUT/engine.candidate.sql"` line is what `test_i7_12` checks.
     - Dump the reference with `--no-privileges` as well.
     - Filter schema-level lines from both (`CREATE SCHEMA`, `ALTER SCHEMA … OWNER`, `COMMENT ON SCHEMA`; ownership and comments differ by design).
     - Normalise the reference by exactly I7.9's two differences: remove the FK from `engine.project(project_id)` to `core.project`, and retarget the evaluation `system_id` FK from `core.system(pid)` to `project.system(pid)`, same ON DELETE. Check the constraint names against 0025's `aisc_backend_evaluation_system_id_fkey`.
     - Keep the verdict text `G1 PASS (engine schema equals e34fca3)`, and write the normalised files to `$OUT`.
   - **G2:** the same move. `prisma migrate deploy` of the candidate qualification with `DATABASE_URL=$(tpg_dsn qualification_rw project_<hex>)?schema=qualification` (or Q1's `migrate-projects.mjs`), dumped `--no-privileges` from the project database.
   - **G4:**
     - Add an `ISOLATION_ALLOWED` case list in `backend_allowed`, plus a Sean's-file exemption list: exactly the files named in E1's notes (expected: `config/settings.py`, the new `aisc_backend/projectdb.py`, `aisc_backend/management/commands/migrate_projects.py`, `migrations/0025_the_database_is_the_project.py`, `auth/membership.py`, `platform_projects.py`, E2's door middleware and dispatch). `routers/evaluation.py` and `models/evaluation.py` stay byte-identical (S9.1).
     - The webapp check allows exactly E2's listed files.
     - The apps/eval check becomes "`git diff --name-only e5b1b0a HEAD` is a subset of {`tests/test_run_ticket.py`} plus E2's worker files". Today it already fails on stage 2's `7f7de02`.
     - The pre-existing G4 differences (`routers/plugin.py`, `pyproject.toml`) stay reported: they are not isolation's.
   - **G5:** models are unchanged. Run `makemigrations --check` with whatever sqlite mode E1's settings honour (E1 names the variable).
   - **`--orders` (S4):** the E and Q steps cannot run on the candidate any more: E1's `default` alias is a dummy, and Q1 deletes `20260923210000_…`. Pin them to the pre-isolation trees: `ORDERS_TOP_REF=f01288a`, and the backend and qualification commits read from that commit's gitlinks (`git -C "$ROOT" rev-parse f01288a:apps/backend`). S4 stays the historical regression it is.
   - **Diagnose the pre-existing red first:** run `scripts/guard-frozen.sh --reference-only` and read `ref.log`. If the cause is environmental, record it; the 11 guard tests then stay baseline red.

8. **Pipeline chain (I19.2, I19.3): `scripts/test-pipeline-chain.sh`, `scripts/pipeline_chain/test_dashboard_queries.py`.**
   - `setup()`: init and platform migrations only. Remove the qualification, engine and control-objectives migrations on `platform`.
   - After step 1 (whose `POST /projects` provisions the database), a new `migrate_project_database` runs every module's migrate one-shot against `{database}`, exactly as `isolation_bed.migrate_modules`, and records `project_db`. It must also call `tpg_project_db` (or `tpg_project_db "$pid"` as an idempotent top-up), since `test_i19_2_harnesses_target_project_databases` greps for it.
   - `apply_break`:
     - `qualification_fk` and `co_fk` move from `:0` to `:1`. They run in the project database and look the constraint up by target: a DO block selecting `conname` where `conrelid` is the table and `confrelid='project.system'::regclass`, then removing it.
     - `card_component:2`, `engine_stamp:4` and `controls_stamp:7` run in the project database.
     - `CONSUMER` is unchanged.
   - Step env:
     - 2: `PROJECT_DATABASE_URL=…/{database}?schema=qualification`.
     - 3: `DATABASE_URL` (platform) plus `PROJECT_DATABASE_URL`.
     - 4: `DB_*` as engine_rw with `manage.py test aisc_backend.tests.test_chain --tag chain -k chain_step4`. This narrowing is the N7 fix, applied on purpose (spec section 20 allows it); name it in the notes.
   - Module chain tests (their WPs may have changed them; otherwise V1 does, committing in each submodule):
     - `apps/qualification/test/chain/chain.test.ts`: Prisma client on the project database, FK target `project.system`, no `projectId` (I1.7).
     - `apps/control-objectives/tests/test_chain.py`: components read from the project database, FK to `project.system`, app built by `server.build_app()` (S-D6).
     - `apps/backend/aisc_backend/tests/test_chain.py`: run inside E1's admitted-alias context for the project.
     - controls and platform: unchanged.
   - `test_dashboard_queries.py`:
     - The first occurrence of `ENGINE_RESULTS_SQL` must be the assignment. Its text is D1's SQL (no `{pid}`, `project.system`). Add a check that it equals `aisc_ext.projects.engine_results_sql()` ignoring whitespace, with `apps/results-dashboard` on `sys.path`.
     - It runs on `ctx.project_db` as dashboard_ro. The `rows("platform", ENGINE_RESULTS_SQL` pattern is forbidden.
     - Standalone mode: P and Q project databases (platform_rw plus template, as `tpg_project_db`), `manage.py migrate_projects`, versions in each `project.system`.
     - S11.4: P's and Q's databases give disjoint evaluation pids.
     - Build DSNs only with `t.dsn()`: S0.3 allows only `{port}`, `{self.port}` or `{t.port}` after `127.0.0.1:`.

### Commands
- **Quick static:** `uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests/test_isolation_harnesses.py scripts/tests/test_verify_project_databases.py scripts/tests/test_project_grants.py scripts/tests/test_isolation_fixture.py scripts/tests/test_isolation_unchanged.py`. The DB tests start their own `aisc-t-*` containers.
- **Full suite:** `uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests`. Baseline is 226 passed and 25 known failures.
  - These may only get greener or change as stated: `db_consistency` (rewritten; its 2 reds go), `report_grants` (rewritten), `guard_frozen` (green if the reference cause is fixed, else the same 11), `pipeline_chain` (should turn green with N7).
  - These stay as they are: `schema_docs` 4, `llm_keys` 1, `report_stack` 2.
- **Direct runs:** `scripts/guard-frozen.sh`, `scripts/test-pipeline-chain.sh`, and `--break <each link>`.
- **Composer and renderer suites** (commands in 02-tests.md section 2): the `report-grants.sh` change must not move their post-R1/R2 counts.
- **At the end:** `docker ps -a --filter name=aisc-t- --format '{{.Names}}'` must be empty.

### Commits (top level, explicit paths; submodule commits in their worktrees, then gitlinks)
1. `inspector/schema-docs/server.py`: "Isolation V1: schema-docs labels, every module in the project database, only shared data in platform (I11.3)".
2. `scripts/lib/throwaway-pg.sh`: "Isolation V1: tpg_project_db makes a project database with the platform template (I19.2)".
3. `scripts/db_consistency/checks.py scripts/db_consistency/heads.py scripts/verify-db-consistency.sh scripts/tests/test_db_consistency.py`: "Isolation V1: consistency checks per project database (I16.6)".
4. `scripts/report-grants.sh init/report-ro-grants.sql scripts/tests/test_report_grants.py` (plus the controls migration in `apps/controls` if C1 lacks it): "Isolation V1: report-grants repairs the reader list in every project database (I2.7)".
5. `scripts/verify-project-databases.sh scripts/verify.sh scripts/verify-db-access.sh`: "Isolation V1: verify-project-databases.sh, the done check; verify.sh runs it (I16, I19.1)".
6. `scripts/guard-frozen.sh scripts/tests/test_guard_frozen.py`: "Isolation V1: the guard compares engine and AIRO tables inside a project database (I7.12, I19.2)".
7. `scripts/test-pipeline-chain.sh scripts/pipeline_chain/test_dashboard_queries.py`, the chain tests in the submodules, and the gitlinks: "Isolation V1: pipeline chain on project databases, N7 narrowed (I19.2, I19.3)".
8. WP notes (04 code notes, V1 section): every changed pre-existing test and why.

### Tests that are constraining or unreachable (none is wrong)
- `test_verify_project_databases.py:47-53`: the read-only regexes forbid the bare words GRANT, REVOKE and TRUNCATE (and "drop "), case-insensitively, in any non-comment line. Word messages around them and use `aclexplode`; do not edit the test.
- `test_isolation_harnesses.py:299-302` (`test_i18_7`): green only after X1 adds `scripts/isolation/*.sh`.

### Ambiguities resolved, and cross-WP risks for the orchestrator
1. **`--final-layout` flag:** named so, not `--after-drop`, because of the `DROP\s` regex. `--privileges` alone suits C9, where the retired schemas exist but are unreachable.
2. **inspector_ro and I16.2:** inspector_ro is excluded from I16.2 "unreachable by every non-superuser role". `pg_read_all_data` defeats any revoke, and I11.1 wants it.
3. **I16.5 without a token:** FAIL "not run" (verify.sh ethos), with `VERIFY_SKIP_FUNCTIONAL=1` as the explicit opt-out. The controls answer is the one non-API write.
4. **Budget constants for I16.7:** 11 per project (D7) and 20 base, both overridable by env.
5. **`--orders` pinned to f01288a trees:** it cannot run on isolated candidates.
6. **G1 and G2 compare with `--no-privileges`:** grants are proven by `test_project_grants.py` and I16.1 instead.
7. **P1 risk:** templates 0007..0010 must run `ALTER ROLE … IN DATABASE … SET search_path` (I2.1), but `platform_rw` has only CREATEDB (`init/project-databases.sql:10`). Non-superusers without CREATEROLE cannot set other roles' defaults. P1 must resolve this; `tpg_project_db` mirrors provisioning as platform_rw.
8. **P1 risk:** `scripts/lib/report_bed.py` (old layout, also step 1 of `report_bed_isolated`) restores module schemas into `platform` and relies on `init/platform-db.sql` creating them. After P1 it breaks for composer, renderer, `test_report_grants` and `test_db_consistency`. P1 must make the bed create the legacy schemas itself.
9. **P1 or R1 risk:** `init/report-roles.sql` grants report_ro and report_composer_rw SELECT and REFERENCES on `core.system`, creates `report_composer` in `platform` and sets core default privileges. This contradicts I1.3 and I1.4, and fails after stage 7. Without that fix, I16.1 fails.
10. **C1 gap:** the controls default privilege and the `_prisma_migrations` grant (step 4 above).

---

## WP Q2: the form library and copy on use (gated on I4.6)

### Plan overrides (read first; they win over the text below)

- **Gate I4.6** is checked first: `git -C /home/listuser/aisc-install/apps/qualification log --oneline feat/unified-modules -5`
  must show the forms commit (read-only). While it does not, Q2 does nothing and Z1 records the skip.
- **G6**: flag F1 below is decided: the baseline is `20260925000000_project_database` (made by Q1, T1).
- **T4** is flag F4 below; Q2 makes it, re-checked against the merged forms files, committed alone.
- The forms migration bytes are compared with the committed forms commit (not with the live database); if they
  differ from what is applied live, stop and report to the orchestrator (the live schema is the source of the
  copy and must match).

### 0. Gate and dependencies

- **Gate I4.6.** Start only when the forms work is a commit on `feat/unified-modules` of the qualification repository.
  - Check read-only with `git -C /home/listuser/aisc-install/apps/qualification log --oneline feat/unified-modules -5`.
  - Today it is still uncommitted: 2 migrations, FormRepository, FormService, `/p/[project]/forms`, about 40 test files and changes to 30 tracked files. So Q2 is blocked.
  - Merge that commit into `isolation/2026-09-25` in the submodule worktree. It shares the object store, so no fetch is needed.
- **Depends on Q1.**
- **Depends on P1 (I2.8):** `init/platform-db.sql` must create schema `form_library` owned by `qualification_rw`. The role cannot create a schema on `platform`.
- **Decision needed first:** F1 below, the name of the baseline migration.

### 1. Requirements and the tests that turn green

**I4.1, I4.3, I4.4, I4.5 in `test/db/formLibrary.db.test.ts`:** every case, but only after the fixture fixes in F4.

**I3.5 and I4.2 in `test/unit/isolationBaseline.test.ts`:**
- "I3.5 I4.6 the two forms migrations are byte-for-byte"
- "I4.2 prisma/library/schema.prisma …"
- "I4.2 I3.8 the library client is opened from FORM_LIBRARY_DATABASE_URL"
- The I3.5 cases must stay green, which needs the F1 decision.

**I3.5, I3.7, I2.6 in `test/db/projectDatabase.db.test.ts`, which now compares the form lines:**
- "I3.5 the baseline is applied first, then the forms migrations"
- "I3.7 … equal the live shape" (with form tables, the `form_version_id` column, the FK, the index, and the answer unique-index swap)
- "I2.6" with the four form tables readable

**Also:**
- `test_project_grants.py -k qualification`: form tables are readable, `_prisma_migrations` is not.
- The merged forms work's own unit tests stay green.
- Its `test/db/forms.db.test.ts` is ported to project F, like `cardVersions`.

### 2. Files

**Merge conflicts to expect:**
- `src/app/api/qualifications/[id]/extracted/route.ts`: modified by the forms work, deleted by Q1. Port the `formService` part into the new route.
- `QualificationRepository.ts`, `QualificationService.ts`, `OntologyService.ts`, `qualify/[id]/page.tsx`, `prisma/schema.prisma`: keep Q1's no-`projectId`, project-bound design and add the forms fields.
- `test/db/cardVersions.db.test.ts`, `test/unit/serviceTokens.test.ts`.
- The forms work's `FormRepository` imports `@/lib/prisma`, which Q1 deleted.

**Migrations:**
- `prisma/migrations/20260925090000_forms_are_data/` and `20260925120000_the_default_form_is_fixed/` must be byte-for-byte the originals in `~/aisc-install`. Re-check this at merge time, because the files have changed since they were applied live.
- **Create `prisma/migrations/20260926000100_the_readers_read_the_forms/migration.sql`** (I2.6): the same DO-block pattern as the baseline, `GRANT SELECT` on `qualification.form`, `form_version`, `form_question`, `form_version_question` to `report_ro` and `dashboard_ro`. It must sort after both forms migrations.

**Library schema and migrations:**
- **`prisma/library/schema.prisma` (create):**
  - `generator client { provider = "prisma-client-js" output = "./generated" }`
  - `datasource db { provider = "postgresql" url = env("FORM_LIBRARY_DATABASE_URL") }`
  - The four models `Form`, `FormVersion`, `FormQuestion`, `FormVersionQuestion`, copied from the main schema with the same `@map`, `@@map` and relations. No `Qualification`.
  - A comment containing the lowercase text `form_library`: the test's regex needs it, and the env var name alone is uppercase.
  - Add `prisma/library/generated/` to `.gitignore`.
- **`prisma/library/migrations/migration_lock.toml`** and **`prisma/library/migrations/20260926000200_form_library/migration.sql` (create):** the end state of both forms migrations with `qualification.` replaced by `form_library.`.
  - Keep: the four tables, their constraints and indexes, the seed rows, and the five trigger functions and triggers (the second migration's `form_name_is_fixed` body, and its `form_builtin_is_the_default` check).
  - Drop: `is_default`, `form_one_default`, `form_default_is_listed` (the second migration removes them), and steps 3 and 4 of the first migration, which touch `qualification.qualification` and the answers.
  - Column order must equal the project tables' so the row-text md5 compares.

**Code:**
- **`src/lib/formLibraryDb.ts` (create):** `export function formLibraryDb(): FormLibraryClient` builds the client lazily, never at import, from `process.env.FORM_LIBRARY_DATABASE_URL` with `connection_limit=2` added. Import it as `import { PrismaClient as FormLibraryClient } from "../../prisma/library/generated"`. Never write `new PrismaClient` or import from `"@prisma/client"` in this file (scan test). Also export `closeFormLibrary()`.
- **`src/server/repositories/FormRepository.ts`**
  - Constructor `constructor(private readonly db: FormStoreClient)`, with no default. `FormStoreClient` is the structural type the four model delegates share on both clients.
  - `export const libraryForms = () => new FormRepository(formLibraryDb())`
  - `export const projectForms = async (project: string) => new FormRepository(await projectDbPastDoor(project))`
- **`src/server/services/FormService.ts`**
  - The library default becomes `new FormRepository(formLibraryDb())`. Keep `resolve`, `latestVersion`, `exportable`, `library`, `libraryGroups`, `chooserOptions` and `saveDraft` on the library (I4.1, I4.5).
  - Add `export async function cardForm(project: string, formVersionId: string | null): Promise<ResolvedFormVersion | null>`. `null` returns `annexDefaultVersion()`; otherwise it reads `projectForms(project)` (I4.4).
  - Use `cardForm` in the new extracted route, in `qualify/[id]/page.tsx`, and in OntologyService's `FormResolver` (project copy).
- **`src/server/repositories/FormCopy.ts` (create)**

```ts
export type LibraryVersionRows = { forms: FormRow[]; questions: FormQuestionRow[]; version: FormVersionRow; snapshots: FormVersionQuestionRow[] };
export async function readLibraryVersion(versionId: string, lib = formLibraryDb()): Promise<LibraryVersionRows>;  // version, its vq rows, their questions, the copied_from closure, every owner form
export class FormCopyConflict extends Error { constructor(readonly table: string, readonly id: string) }
export async function copyFormVersion(tx: Prisma.TransactionClient, rows: LibraryVersionRows): Promise<void>;
```

  `copyFormVersion` inserts in foreign-key order: forms, then questions (sources before copies), then the version, then the snapshots.
  - Every column is copied verbatim, `created_at` included.
  - A row that is already present must be equal on every column, or it throws `FormCopyConflict`. Log `console.error` with the table and id, never row values.
  - It never updates, and it never inserts the builtin form's version: that is already seeded in every project database, so the equal check makes it a no-op.

- **`QualificationRepository.create(input, opts?: { formCopy?: LibraryVersionRows })`:** runs `this.db.$transaction(async (tx) => { if (opts?.formCopy) await copyFormVersion(tx, opts.formCopy); return tx.qualification.create(...) })`. Keep the forbidden identifiers of I4.4 out of this file; `FormCopy.ts` holds the library import.
- **`QualificationService.createFromForm`:** resolve the version from the library, as today. Read `readLibraryVersion(form.versionId)`, then `repo.create({ ...parsed, formVersionId: form.versionId, systemId }, { formCopy })`. A conflict propagates, so the save returns 500 and stores nothing.
- **`scripts/migrate-projects.mjs`:** first run `npx prisma migrate deploy --schema prisma/library/schema.prisma` with `FORM_LIBRARY_DATABASE_URL`.
  - If that variable is missing, exit 2.
  - A connection failure exits 1; any other failure exits 2.
  - Then do the project databases.
- **`Dockerfile`:** `RUN npx prisma generate && npx prisma generate --schema prisma/library/schema.prisma`.
- **Local setup:** generate the library client locally too. Verify `npx next build` loads it; do not build images.

### 3. How to run

- The suites and commands are the same as Q1's section 4. Pass criteria: `formLibrary.db.test.ts` (7 cases after F4) runs and passes, and the merged forms tests stay green.
- Throwaway databases only. `FORM_LIBRARY_DATABASE_URL` is set by `throwaway-db.sh` (`QUALIFICATION_TEST_FORM_LIBRARY_URL`).

### 4. Commits

**Submodule `apps/qualification`:**
1. The merge commit: `Merge the forms work (feat/unified-modules <sha>) into the isolation branch, on the per-project design`.
2. `Isolation Q2: the form library lives in platform.form_library, and a card's form version is copied into its project on use`
   - `prisma/library/**` (not `generated/`)
   - `.gitignore`
   - `prisma/migrations/20260926000100_the_readers_read_the_forms/`
   - `src/lib/formLibraryDb.ts`
   - `src/server/repositories/{FormRepository,FormCopy,QualificationRepository}.ts`
   - `src/server/services/{FormService,QualificationService,OntologyService}.ts`
   - The routes and pages touched
   - `scripts/migrate-projects.mjs`
   - `Dockerfile`
   - The ported `test/db/forms.db.test.ts`

**Top level:** the gitlink only.

### 5. Flagged tests and decisions

- **F1 (blocking): the baseline name versus the forms migrations.**
  - The forms directories must keep their names and bytes (I3.5, the byte-for-byte test, the `FORMS` constants, the `formsMerged` gate).
  - They sort before `20260926000000_project_database`. Prisma applies them first on a fresh project database, and `20260925090000_forms_are_data` fails because it alters `qualification.qualification`.
  - `isolationBaseline.test.ts:42` (`all[0]`) and `projectDatabase.db.test.ts:205` (`names[0]`) also fail.
  - Proposal: rename the baseline to `20260925000000_project_database` and change the constant in three places: `test/unit/isolationBaseline.test.ts:13`, `test/db/projectDatabase.db.test.ts:30` and `platform/tests/isolate_support.py:128` (`NEW_QUALIFICATION_BASELINE`). Also change I3.5 in `01-specs.md`.
  - The control-objectives alembic constant with the same name is unrelated.
  - This is cheapest if decided before Q1, which would then use the new name from the start.
  - No project database is live yet, so the rename costs nothing in production.
- **F4: `test/db/formLibrary.db.test.ts` fixture bugs**, against the current forms migrations:
  - Lines 129 and 157 use `WHERE is_default` / `f.is_default`. That column is dropped by `20260925120000`; use `id = 'annex-iv-default'`.
  - Line 254 inserts `is_default` (same fix) and `origin 'user'`, which `form_origin_check` forbids; use `'builder'`.
  - Line 225 sets `blocks = '[]'::jsonb` on a `text[]` column; use `ARRAY['risks']::text[]`.
  - Lines 224 to 226 run `SET session_replication_role` and the `UPDATE` as separate calls on a pooled client, so they may use different connections. Wrap them in one interactive `$transaction` using `SET LOCAL`.
  - The `beforeAll` at line 156 throws on the first of these, so all four I4.3 and I4.4 cases fail until it is fixed.

### 6. Ambiguities resolved

- **Library and project copy share one `FormRepository` class** over two clients; the models are the same. FormService keeps the library, and `cardForm` reads the project copy (I4.4).
- **The seeded default form is present in every project database** (its forms migration seeds it), so copying it on use is the equal-content no-op of I4.3.
- **Project copies are never updated.** A differing row aborts the save (500), in keeping with append-only versions.

---

## WP X1: cutover, rehearsal and stage-7 scripts

### Plan overrides (read first; they win over the text below)

- **G1**: section 0 of the original text (compose ownership) became G1, and its section 4 (compose) became WP W1;
  X1 edits no compose file. The compose tests in "1. Requirements" below are W1's; X1's own tests are
  `test_cutover_script.py` (43), `test_isolation_fixture.py` (2, green) and, with V1, `test_isolation_harnesses.py::test_i18_7_*`.
- **G4**: C9's comment on the four schemas and on `core.system` begins with `retired:` (P1's init files test that
  prefix).
- **G7**: the stage-7 dump is the two files below.
- **G8**: C8 relies on the copy stopping at the first failed project.
- C12 removes `AISC Results` through D1's `remove_results_connection()` when available.
- Questions 1 and 2 of section 12 below are recorded for the user (plan section 5); the scripts refuse until the
  variables are set, and stage 4 never runs any step with `--target live`.

### 1. Requirements and the tests X1 turns green

Requirements: I13.1..I13.4, I14.1..I14.7, I15.1..I15.3, I18.7, plus the compose wiring for I3.6, I3.8, I5.1, I5.5, I7.6, I8.1, I8.4, I9.1, I9.2, I10.2, I16.4, I18.1.

**`scripts/tests/test_cutover_script.py`: all 43 tests, all red today.**
- `test_i13_1_cutover_script_exists_and_is_executable`
- `test_i13_1_every_step_is_a_subcommand_in_order`
- `test_i13_1_the_script_lists_its_steps_in_order`
- `test_i13_1_a_step_refuses_to_start_before_the_previous_one_passed`
- `test_i13_1_a_step_after_a_fake_passed_state_still_checks_its_predecessor`
- `test_i13_1_the_state_file_is_named_cutover_state_json`
- `test_i13_steps_run_their_check[C1-pg_dumpall, C1-pg_restore --list, C2-pg_stat_activity, C3-isolate plan, C6-isolate provision, C8-isolate copy, C10-isolate verify, C12-verify-project-databases.sh]`
- `test_i13_4_the_quiet_check_is_repeated_at_c8_and_c10`
- `test_i13_2_every_step_has_a_named_rollback`
- `test_i14_4_rollback_c8_drops_only_the_schemas_of_0006_to_0010`
- `test_i14_5_c9_saves_and_restores_acls`
- `test_i14_3_rollback_c4_documents_the_restore_and_swap`
- `test_i14_7_caddy_starts_last_after_c12`
- `test_i13_3_dumps_and_reports_are_mode_600_under_the_backup_directory`
- `test_i18_7_no_credential_is_echoed[path0, path1]`
- `test_i13_3_backups_are_never_written_inside_a_repository`
- `test_i15_1_rehearsal_script_exists`
- `test_i15_1_rehearsal_uses_a_throwaway_postgres_on_a_random_port`
- `test_i15_1_rehearsal_restores_the_copy_without_printing_it`
- `test_i15_1_rehearsal_runs_twice_injects_a_failure_and_resumes`
- `test_i15_1_rehearsal_runs_the_cutover_script_against_the_throwaway`
- `test_i15_2_drop_statements_appear_only_in_a_step_guarded_by_verify_dump`
- `test_i15_3_databases_needing_a_user_decision_are_never_dropped`
- `test_i14_each_rollback_names_its_action[C0, C1, C2, C3, C5, C8, C9, C10, C11, C12]`
- `test_i14_7_the_point_of_no_return_is_stated`
- `test_i15_2_the_drop_is_exactly_the_four_schemas_core_system_and_its_function`

**`scripts/tests/test_compose_isolation.py`: 19 red today, and 7 green that must stay green.**
- Red: `test_i3_8_qualification_gets_a_project_database_template[qualification-web, qualification-migrate]`
- Red: `test_i3_8_qualification_reaches_platform_only_for_the_form_library[qualification-web, qualification-migrate]`
- Red: `test_i3_6_qualification_migrate_runs_migrate_projects_after_the_platform`
- Red: `test_i5_5_control_objectives_migrate_runs_migrate_projects`
- Red: `test_i5_1_control_objectives_has_a_project_database_template[control-objectives, control-objectives-migrate]`
- Red: `test_i7_6_aisc_backend_no_longer_migrates_platform`
- Red: `test_i7_6_aisc_backend_migrate_one_shot_runs_migrate_projects`
- Red: `test_i8_1_composer_has_a_project_database_template_and_platform_for_the_library`
- Red: `test_i10_2_dashboard_reads_memberships_over_a_plain_dsn_and_registers_no_platform_connection[dashboard, dashboard-migrate]`
- Red: `test_i16_4_every_module_dsn_names_a_project_database_except_the_allowed_platform_ones[control-objectives, control-objectives-migrate, dashboard, qualification-migrate, qualification-web, report-composer]`
- Green, keep: `test_i9_1_renderer_builds_from_report_generator_dir`, `test_i9_2_renderer_reads_projects_from_their_database`, `test_i16_4_...[report-renderer]`, `test_i18_1_every_service_token_required_before_isolation_is_still_required[both files]`

**`scripts/tests/test_isolation_fixture.py`:** both tests are green; keep them green.

**Regression suites that also resolve the compose files.** Keep each at its baseline:
- `test_compose.py` and `test_service_tokens.py`: currently green.
- `test_inspector_network.py`, `test_isolation_unchanged.py`: currently green.
- `test_report_stack.py`: baseline 2 known reds.
- `test_llm_keys.py`: baseline 1 known red.

### 2. Files

| path | action |
|---|---|
| `scripts/isolation/cutover.sh` | new, executable (`chmod 755`) |
| `scripts/isolation/rehearse.sh` | new, executable |
| `docker-compose.development.yml` | change (section 4) |
| `docker-compose-infra.development.yml` | change: only the `schema-docs` image tag (4.0) |
| `platform/Dockerfile` | add `postgresql-client` so `isolate verify-dump` finds `pg_restore` (only if P2 has not done it) |
| `env.development` | optional: fix the stale comment above `DB_NAME` (engine: "platform alias and template for project aliases"); do not remove any "comes from env.secrets" line, because tests pin them |
| `scripts/tests/fixtures/isolation/live_shape.sql` | **no change** (issue 6: the qualification, engine and move-tool loaders create `core` and `core.system_only_latest_changes()` first; editing the file would break them) |

Not touched:
- `docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.demo.nbg.yml`, `docker-compose-infra.staging.yml`, `docker-compose-infra.yml`: these are engine-only legacy stacks with no platform service, so they are out of the isolated deployment. Report them as a follow-up for the user.
- The Caddyfile: it has no per-path rules for the moved routes.

### 3. Rules the script text must follow (the static tests read it)

`code()` drops only lines whose first non-blank character is `#`, so heredoc SQL and printed text are checked too.

1. **Step labels.** A step id followed directly by `)` may appear only as a case label: one label per line, in C0..C12 order, in every `case`. Never write combined labels such as `C0|C1|C2)`, and never write prose like "(see C9)" (regex at `test_cutover_script.py:57`).
2. **The quiet function.** `quiet_check() {` must mention `pg_stat_activity` before any `}` character: no `${...}` and no brace before it (regex at `:105`). Call it at C2, C8 and C10.
3. **`DROP SCHEMA` lines.**
   - The literal `DROP SCHEMA qualification, control_objectives, engine, report_composer CASCADE;` appears only in the stage-7 function, within 4000 characters after both `verify-dump` and `pg_stat_user_tables`.
   - Rollback C8 must build its drop dynamically (`format('DROP SCHEMA IF EXISTS %I CASCADE', r.nsp)`), with the schema list on other lines.
   - No line containing `DROP SCHEMA` may contain `controls`, `llm` or `catalogue`.
   - Never write `DROP DATABASE` anywhere.
4. **No repo paths with those extensions.** Never write `$ROOT`, `$HERE` or `./` followed (without a space) by anything ending in `.sql`, `.dump` or `.json`, even for reading. For example, `for f in "$ROOT"/platform/project-template/*.sql` fails. Use `TEMPLATE_DIR="$ROOT/platform/project-template"` and then `"$TEMPLATE_DIR"/*.sql`. Init files are applied only through the `postgres-setup` one-shot.
5. **No secrets in output.** No `set -x`. No `echo` or `printf` line may reference `$…PASSWORD`, `$PGPASSWORD`, `$…TOKEN` or `$…SECRET`. Pass secrets as `docker exec -e PGPASSWORD` (name only, value inherited) or through env files written at mode 600.
6. **Mode 600.** Put `umask 077` at the top of both scripts. Backups and reports go under `${ISOLATION_BACKUP_DIR:-$HOME/aisc-isolation-backup}` (the literal `aisc-isolation-backup` must appear).
7. **Keep checks in `cutover.sh` itself.** Every string a test greps for (`pg_dumpall`, `pg_restore --list`, `isolate plan|provision|copy|verify`, `verify-project-databases.sh`, `provision.template_migration`, `c9-acl.json`, `caddy`, `point of no return`, `ALTER DATABASE … RENAME`, `pg_restore`) must be in `cutover.sh`, not in a sourced library.

### 5. `scripts/isolation/cutover.sh`

#### 5.1 Interface

```
cutover.sh steps                               # prints the 14 steps; stage 7 and open on lines not starting with C
cutover.sh status [--target T]                 # the state file, names and times only
cutover.sh fingerprint                         # sha256 of: git HEAD, `git submodule status`, renderer worktree HEAD,
                                               #   image IDs of every built service at $AISC_IMAGE_TAG
cutover.sh C0|C1|…|C8|C8b|C9|…|C12 --target live|rehearsal
cutover.sh open --target T                     # after C12: point of no return, start caddy
cutover.sh drop --target T                     # stage 7
cutover.sh rollback <step> --print             # prints the text; exit 0; needs no docker, env or state
cutover.sh rollback <step> --yes --target T    # executes; only C8, C9, and C10..C12 (= C9 then C8); others print and exit 2
```

**Exit codes:** 0 passed; 1 a check failed; 2 usage; 3 refused (order, target, point of no return).

**Order of work inside a step** (the order is pinned by the tests):
1. Parse arguments.
2. **Order check.** Read the state and refuse if the previous step is missing from `.passed`, naming it: "refused: C3 needs C2 passed in this run (state …/cutover-state.json)". Nothing is recorded.
3. Only then validate the environment and target.
4. Take a lock (`flock` on `$STATE/cutover.lock`).
5. Run the action.
6. Run the check.
7. Record the step as passed.

- A step also refuses when any later step has already passed ("already past C9"). The exception is C8, which may be re-run while C8b has not passed (resume).
- **Environment:**
  - `ISOLATION_BACKUP_DIR`: default `$HOME/aisc-isolation-backup`.
  - `ISOLATION_STATE_DIR`: default `$ISOLATION_BACKUP_DIR/cutover-<target>`.
  - `ISOLATION_ENV_FILE`: required; for live it must exist at mode 600.
  - `ISOLATION_COMPOSE_DIR`: default the repo root.
  - `AISC_IMAGE_TAG`: required and not `latest`.
  - `REPORT_GENERATOR_DIR`: exported, default `$HOME/aisc-isolation-report-generator`.
  - `ISOLATION_DROP_MIN_HOURS`: default 24; below 24 is refused on live.
  - Live only: `ISOLATION_CONFIRM_LIVE=yes`. The project is fixed as `aisc` and the PG container as `postgres`.
  - Rehearsal only: `ISOLATION_COMPOSE_PROJECT`, `ISOLATION_PG_CONTAINER` and `ISOLATION_NETWORK` are required and must match `^aisc-t-reh-`. Refuse `aisc` and `postgres`.
- **Superuser password:** live reads `POSTGRES_PASSWORD` from `ISOLATION_ENV_FILE` into an exported `PGPASSWORD` (never printed). Rehearsal inherits `PGPASSWORD` from `rehearse.sh`. `PGSU` is `POSTGRES_USER` from the same file (default `aisc-postgres-user`).

#### 5.2 State file `$ISOLATION_STATE_DIR/cutover-state.json` (mode 600, written with jq to a temp file then `mv`)

```json
{"target": "live", "run": "20260926T080000Z", "fingerprint": "<sha256>",
 "passed": ["C0", "C1"],
 "steps": {"C0": {"started": "…Z", "passed": "…Z", "log": "<state>/C0.log"}},
 "rolled_back": [], "opened_at": null,
 "reports": {"C3": "<backup>/<run>/plan.json"}}
```

- Tolerate a file that holds only `{"passed": [...]}`, as the test writes.
- Append with `jq --arg s "$step" '.passed = ((.passed // []) | if index($s) then . else . + [$s] end)'`. Never use `unique`: it sorts, so C10 would sort before C2.
- Each step's output is `tee`d to `<state>/<step>.log`.
- `c9-acl.json` and `c9-counters.json` live in `$ISOLATION_BACKUP_DIR` (per target), not in the state directory. They are written only when absent, so a re-run never overwrites the original ACLs with the retired ones.

#### 5.3 Helpers (they must live in `cutover.sh`)

```bash
psql_su() { docker exec -i -e PGPASSWORD "$PG_CONTAINER" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$PGSU" "$@"; }
pgx()     { docker exec -i -e PGPASSWORD "$PG_CONTAINER" "$@"; }            # pg_dump, pg_dumpall inside the container
compose() { docker compose -p "$COMPOSE_PROJECT" --project-directory "$COMPOSE_DIR" --env-file "$ENV_FILE" \
              -f "$COMPOSE_DIR/docker-compose-infra.development.yml" -f "$COMPOSE_DIR/docker-compose.development.yml" \
              ${OVERRIDE:+-f "$OVERRIDE"} "$@"; }
oneshot() { compose run --rm --no-deps -T "$@"; }                           # --no-deps: never start postgres or platform
isolate() { compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -v "$BACKUP:/backup" isolate "$@"; }
project_dbs() { psql_su -d platform -tA -c "SELECT 'project_' || replace(lower(pid::text), '-', '') FROM core.project ORDER BY pid"; }
```

- **Host tools:** the host has no psql, pg_dump or pg_restore. It has docker, jq, python3 and uv.
- **`--user`** makes the reports owned by the operator. The script then `chmod 600`s them.
- **Rehearsal `OVERRIDE`:** a file `<state>/compose.rehearsal.yml` (mode 600) that sets `backend`, `frontend` and `inspector` to `{external: true, name: $ISOLATION_NETWORK}`. The throwaway postgres is on that network with alias `postgres`, so every DSN reaches it unchanged.

The quiet check (rule 2):

```bash
quiet_check() {
  local rows
  rows=$(psql_su -d postgres -tA -c "SELECT usename || '@' || datname || '=' || count(*) FROM pg_stat_activity WHERE usename = ANY (ARRAY['platform_rw','qualification_rw','control_objectives_rw','controls_rw','engine_rw','report_composer_rw','report_ro','dashboard_ro']) AND pid <> pg_backend_pid() GROUP BY usename, datname ORDER BY 1")
  if [ -n "$rows" ]; then say "quiet check failed, sessions: $rows"; return 1; fi
  say "quiet: no module or platform_rw session"
}
```

#### 5.4 Steps (action, then check)

| step | action | check |
|---|---|---|
| **C0** | (1) Git: `git diff --quiet` on the top-level repo, every submodule and `$REPORT_GENERATOR_DIR`, excluding `**/__pycache__/**` (tracked `.pyc` files are modified today). (2) Forms gate I4.6: `apps/qualification/prisma/migrations/20260925090000_forms_are_data` and `…/20260925120000_the_default_form_is_fixed` exist. (3) Every built service's `<image>:$AISC_IMAGE_TAG` exists (`docker image inspect`); record their IDs. (4) Live only: `ISOLATION_SUITES_GREEN` equals `fingerprint`. (5) Live only: `$BACKUP/rehearsal-passed.json` `.fingerprint` equals `fingerprint`. (6) Live only: for each running container of project `aisc`, `docker tag "$(docker inspect -f '{{.Image}}' c)" "<repo>:pre-isolation"`, where repo is `.Config.Image` without its tag. (7) Live only: `psql_su -d platform -tAc 'SELECT 1'`. (8) Print the qualification route files of the running container and of the new image (names only; risk 10), and require `ISOLATION_ROUTES_CHECKED=yes`. | `docker image inspect` succeeds for both tag sets |
| **C1** | `pgx pg_dumpall -U "$PGSU" >"$BACKUP/pre-cutover-$TS.sql"`. `pgx pg_dump -Fc -U "$PGSU" <db>` for platform, superset and every `^project_[0-9a-f]{32}$` database into `$BACKUP/pre-cutover-$TS/<db>.dump`. Also save `pg_db_role_setting` and `datacl` of platform to `…/platform-settings.json`, needed by rollback C4. | Start a throwaway with `. "$ROOT/scripts/lib/throwaway-pg.sh"`, `TPG_OWN_TRAP=1`, `tpg_start c1`. For each `.dump`: `docker exec -i "$TPG_NAME" pg_restore --list <f` has entries; restore with `--no-owner --no-acl` into a database of the same name; compare exact per-table `count(*)` between source and restored (generated with `\gexec`; print only "N tables equal" or the names that differ). The pg_dumpall file's tail must contain `database cluster dump complete` (`grep -q`, never printed). `tpg_cleanup`. |
| **C2** | Live: `docker stop caddy`, then `docker stop -t 30 platform qualification-web qualification-agents controls-web control-objectives aisc-backend aisc-eval-worker aisc-eval-flower report-composer report-renderer dashboard`. If `rabbitmq` is not running (exited today), `docker start rabbitmq` and wait for `rabbitmqctl await_startup`. Take a quiet-state `pgx pg_dump -Fc platform >"$BACKUP/quiet-platform-$TS.dump"` for rollback C4. Rehearsal: stop nothing and skip rabbitmq. | `quiet_check`. `SELECT count(*) FROM engine.evaluation WHERE status IN ('Pending','Processing')` = 0: the real choices are capitalized (`models/evaluation.py`); the spec's "running/pending" is wrong. `docker exec rabbitmq rabbitmqctl -q list_queues messages \| awk '{s+=$1} END {print s+0}'` = 0. `pg_restore --list` of the quiet dump has entries. |
| **C3** | `isolate plan --all --report /backup/$RUN/plan.json` | Exit code ignored. Pass only if the only refusals are `target not at new head`, `missing template`, and `source not at old head` for `report_composer.*` tables; and the classification has no `unclassified`. (jq: `[.refusals[] \| select(...not allowed...)] \| length == 0`) |
| **C4** | For each of `0003_a_report_points_at_its_project_and_version.sql`, `0004_a_version_of_its_project.sql`, `0005_presets_and_document_settings.sql` not in `report_composer.schema_migration`: `{ printf 'SET ROLE report_composer_rw;\nSELECT pg_advisory_xact_lock(8190233707);\n'; git -C "$ROOT" show "f01288a:apps/report-composer/migrations/$f"; printf "\nINSERT INTO report_composer.schema_migration (name) VALUES ('%s');\n" "$f"; } \| psql_su -d platform -1`. This is exactly the runner's semantics, with the pre-isolation files from the stage-1 base commit, and no image or password is needed. | `isolate plan --all --report …/plan-c4.json` has no `source not at old head`. `schema_migration` holds 0001..0005. |
| **C5** | `oneshot postgres-setup` (new init files from `$COMPOSE_DIR`) | Exit 0. `form_library` is owned by `qualification_rw` and `report_library` by `report_composer_rw` in platform. Those schemas must be created by a file that runs on every start (cross-WP item 7.1). |
| **C6** | `isolate provision --all --report …/provision.json` | For each `project_dbs`, `SELECT string_agg(name, ',' ORDER BY name) FROM provision.template_migration` equals the basenames of `"$TEMPLATE_DIR"/*.sql` (0001..0010) |
| **C7** | `oneshot qualification-migrate`, `oneshot control-objectives-migrate`, `oneshot aisc-backend-migrate`, `oneshot report-composer-migrate`. `controls-migrate` is **not** run here: controls is already at its pre-isolation head, and its only new migration is I6.2's FK, which belongs to C8b. | `isolate plan --all --report …/plan-c7.json` exits 0 with no refusal. In each project database: `qualification._prisma_migrations`, `control_objectives.alembic_version`, `engine.django_migrations` containing `0025_the_database_is_the_project`, `report_composer.schema_migration`, `project.system`. In platform: `to_regclass('form_library.form')` and `to_regclass('report_library.preset')` are not null. |
| **C8** | `quiet_check`, then `isolate copy --all --report …/copy.json` | Exit 0. `jq -e '[.projects[].status] \| all(. == "copied" or . == "already done")'`. Library status is copied or already done. |
| **C8b** | `oneshot controls-migrate`, then `oneshot report-grants` | Both exit 0. Every project database has `submission_answer_system_version_pid_fkey` in `pg_constraint`. |
| **C9** | See 5.5 | See 5.5 |
| **C10** | `quiet_check`, then `isolate verify --all --report …/verify.json` | Exit 0. `jq -e '[.coverage[].missing] \| all(. == 0)'`. |
| **C11** | Live: `compose up -d --no-deps --no-build platform`, wait for `/health` (`docker exec platform python -c "import urllib.request,sys;sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5).status!=200)"`) and make one request that queries the database so `provision_all` and dashboard re-registration run. Then `up -d --no-deps --no-build` for the qualification sidecars and web, controls-pdf, controls-web, control-objectives, report-renderer, report-composer, aisc-backend, aisc-eval-worker, aisc-eval-flower, aisc-webapp and schema-docs. Then `oneshot dashboard-migrate` and `up -d --no-deps --no-build dashboard`. **Never caddy.** Rehearsal: "no services started" and pass. | Each container is running with RestartCount unchanged after 30 s, and each HTTP health route the coder finds in the app answers 200 (a table in the script) |
| **C12** | `verify-project-databases.sh` with `PGHOST=127.0.0.1 PGPORT=<5432 live, or the rehearsal port> PGUSER=$PGSU PGDATABASE=platform` (rehearsal adds `VERIFY_SKIP_CONTAINERS=1 VERIFY_SKIP_FUNCTIONAL=1`). Then remove Superset's `AISC Results` connection, deferred from C9 (5.5). Then print the manual smoke list of section 13 C12 (names and expected counts only) and the point-of-no-return statement. | The verify script exits 0 |
| **open** | Needs C12 passed and a confirmation (`--yes`). Print: "point of no return: from now on new rows exist only in project databases; a rollback loses every row written since C11." Live: `compose up -d --no-deps --no-build caddy`. Rehearsal: record only. Set `opened_at`. | caddy is running |

#### 5.5 C9, retire (I14.5, D12)

All SQL is inline heredocs run with `psql_su -d platform -1` (one transaction).

1. **Refuse unless not yet retired.** If the schemas already carry the retirement comment and `$BACKUP/c9-acl.json` exists, skip straight to the check (idempotent). If they are retired and the file is absent, refuse.
2. **Save `$BACKUP/c9-acl.json`** with one `psql -tA` query producing one JSON value (names and privileges only, no rows):
   - `schemas[]` for `qualification`, `control_objectives`, `engine`, `report_composer`: `{name, owner: pg_get_userbyid(nspowner), comment: obj_description(oid,'pg_namespace'), acl: <aclexplode(nspacl) minus the owner>}`.
   - `relations[]`: every `pg_class` with relkind `r,p,v,m,S,f` in those schemas, plus `core.system`: `{schema, name, kind, owner, linked (sequence owned by a table through pg_depend deptype 'a' or 'i'), comment, acl, columns: [{name, acl from aclexplode(attacl)}]}`.
   - `functions[]`: every `pg_proc` in those schemas plus `'core.system_only_latest_changes()'::regprocedure`: `{signature: oid::regprocedure::text, owner, acl}`.
   - `types[]`: standalone enums, domains and composite types in those schemas (`typtype IN ('e','d','r')`, or `'c'` whose typrelid has relkind `'c'`): `{schema, name, owner}`.
   - `reduced[]` (I1.4): for the roles `qualification_rw, control_objectives_rw, controls_rw, engine_rw, report_composer_rw, catalogue_rw, dashboard_ro, report_ro`, every explicit grant in platform outside the four schemas and core.system, on objects the role does not own, minus the allowlist:
     - every module role: `SELECT` on `core.project` and `core.project_member`, and `USAGE` on `core`;
     - `dashboard_ro`: `SELECT core.project_member`, `USAGE core`;
     - `report_ro`: `SELECT core.project`, `USAGE core`;
     - database `CONNECT` is kept for all.
     Each entry is `{kind, object, column|null, grantee, privilege, grantable}`. `platform_rw` and `inspector_ro` (whose `pg_read_all_data` is I11.1) are excluded.
   - `superuser`, `saved_at`.
3. **Save `$BACKUP/c9-counters.json`:** `SELECT json_object_agg(schemaname || '.' || relname, json_build_array(n_tup_ins, n_tup_upd, n_tup_del)) FROM pg_stat_user_tables WHERE schemaname IN (the four) OR (schemaname = 'core' AND relname = 'system')`, after `SELECT pg_stat_clear_snapshot()` and a one-second sleep.
4. **Retire** (a DO block):
   - `ALTER SCHEMA %I OWNER TO current_user`.
   - `ALTER TABLE|VIEW|MATERIALIZED VIEW|FOREIGN TABLE %I.%I OWNER TO current_user`. Unlinked sequences use `ALTER SEQUENCE`; linked ones follow their table.
   - `ALTER FUNCTION %s OWNER TO current_user` and `ALTER TYPE %I.%I OWNER TO current_user`.
   - The same for `core.system` and its function.
   - `REVOKE ALL ON SCHEMA %I FROM PUBLIC, <every grantee seen>`, and `REVOKE ALL ON ALL TABLES|SEQUENCES|FUNCTIONS IN SCHEMA %I FROM PUBLIC, <grantees>`.
   - `REVOKE ALL ON TABLE core.system FROM PUBLIC, <grantees>`.
   - Each `reduced[]` entry becomes `REVOKE <priv> [(<col>)] ON <object> FROM <grantee>`.
   - `COMMENT ON SCHEMA %I IS 'retired by the isolation cutover C9 <ts>; dropped in stage 7'` and `COMMENT ON TABLE core.system IS …`.
5. **Superset:** `SELECT count(*) FROM tables t JOIN dbs d ON d.id = t.database_id WHERE d.database_name = 'AISC Results'` on database superset. If it is above 0 (expected: the engine datasets move only when C11 re-registers), print "deferred to C12".
6. **Check:**
   - `oneshot postgres-setup`, then `oneshot report-grants`, **run again on purpose**, so an init file that un-retires anything (see 7.2) fails here and in the rehearsal, not silently after a later restart.
   - Then `verify-project-databases.sh --privileges` exits 0.
   - `jq -e .schemas c9-acl.json`.

**Rollback C9 (`--yes`)** is one DO block given the JSON through `-v acl="$(jq -c . "$BACKUP/c9-acl.json")"` and `:'acl'::jsonb` (it holds no secret):
1. Owners back: schemas, types, functions, relations, `core.system`.
2. Each saved ACL entry re-granted: `GRANT <priv> [(<col>)] ON <kind> <obj> TO <grantee> [WITH GRANT OPTION]`. A superuser's grant is recorded under the owner as grantor, so it compares equal.
3. Each `reduced[]` entry re-granted.
4. Comments back.

Its check re-runs the save query into a temp file and diffs it with `c9-acl.json` (ignoring `saved_at`), printing only the names that differ. `AISC Results` needs no restore: the pre-isolation dashboard re-registers it on start. After that, `rollback C9` runs rollback C8.

**C12, removing `AISC Results`.** Use D1's function if it provides one (request `aisc_ext.results_db.remove_results_connection()`, which refuses while a dataset uses it). Otherwise run SQL in database superset in one transaction:
1. Refuse if the `tables` count is above 0.
2. Delete the rows of every table with a foreign key to `dbs` (found from `pg_constraint` where `confrelid = 'dbs'::regclass`).
3. Delete the `dbs` row.

This also drops the SQL Lab history on that connection. Report the count of rows deleted.

#### 5.6 Rollback texts (`--print`, exit 0; needles in brackets)

- **C0, C1, C2:** "Nothing in any database changed. Start what C2 stopped: `docker start <the containers>`. They still run the images tagged :pre-isolation [pre-isolation]; nothing was rebuilt."
- **C3:** "Read-only step: nothing to undo [nothing to undo]."
- **C4:**
  1. "The composer migrations 0003..0005 are additive and the :pre-isolation images run on them; usually nothing to do. Only if they do not:"
  2. `docker exec -i postgres psql -U <su> -d postgres -c 'CREATE DATABASE platform_restore'`
  3. `docker exec -i postgres pg_restore -d platform_restore < <backup>/quiet-platform-<ts>.dump`, or the C1 dump as fallback [pg_restore]
  4. Compare per-table counts with the C2 counts.
  5. Stop everything connected to platform, catalogue-backend included.
  6. `ALTER DATABASE platform RENAME TO platform_pre_c4_<ts>; ALTER DATABASE platform_restore RENAME TO platform;` [ALTER DATABASE … RENAME]
  7. Re-apply the role settings and CONNECT grants saved in `pre-cutover-<ts>/platform-settings.json`.
  8. Proceed as rollback C0.
- **C5, C6, C7, C8, C8b:** "The shared schemas are unchanged. Restart the :pre-isolation images (as rollback C0; after C11 use `docker compose -p aisc` from ~/aisc-install with its own env file, `up -d --no-build`), run the previous postgres-setup from ~/aisc-install, then `cutover.sh rollback C8 --yes` to remove the new schemas [pre-isolation, rollback C8]." C8's text also says what it removes and that controls and llm are never touched.
- **Rollback C8 `--yes`:** refused after `opened_at` (point of no return). For each `^project_[0-9a-f]{32}$` database:
  - Refuse if `provision.template_migration` has a name at or above 0006 outside the known five.
  - Then:
    ```sql
    DO $rb$ DECLARE r record; BEGIN
      FOR r IN SELECT v.file, v.nsp FROM (VALUES
          ('0006_project_system.sql', 'project'), ('0007_qualification.sql', 'qualification'),
          ('0008_control_objectives.sql', 'control_objectives'), ('0009_engine.sql', 'engine'),
          ('0010_report_composer.sql', 'report_composer')) AS v(file, nsp)
        WHERE EXISTS (SELECT 1 FROM provision.template_migration t WHERE t.name = v.file)
      LOOP
        EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', r.nsp);
        DELETE FROM provision.template_migration WHERE name = r.file;
      END LOOP;
    END $rb$;
    ```
  - Then `ALTER ROLE <r> IN DATABASE <db> RESET search_path` and `REVOKE CONNECT ON DATABASE <db> FROM <r>` for `qualification_rw, control_objectives_rw, engine_rw, report_composer_rw`, matching `platform/tests/test_project_databases.py`.
  - Delete from `controls._prisma_migrations` the migration names that are in `apps/controls/prisma/migrations` but not in the tree of the controls gitlink at f01288a (`b3b4a57`). The FK itself went with `project` CASCADE.
  - Leave `form_library` and `report_library` in platform: the old images ignore them.
- **C9:** "Restore the owners and grants C9 saved in c9-acl.json [c9-acl.json]: `cutover.sh rollback C9 --yes`, then as rollback C8."
- **C10, C11, C12:** "Stop the isolation services (never caddy), then as rollback C9: restore c9-acl.json [c9-acl.json], restart the :pre-isolation images, then rollback C8. After `open` this is past the point of no return: rows written since C11 exist only in project databases and are lost unless exported by hand."

#### 5.7 Stage 7, `drop` (I15.2, with the corrected dump)

Preconditions: C12 passed; `opened_at` at least `ISOLATION_DROP_MIN_HOURS` ago (24 on live); `rolled_back` empty; `verify-project-databases.sh` re-run exits 0. Then, in one compact function kept under 4000 characters up to the DROP:

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ); SCHEMAS="$BACKUP/stage7-$TS-schemas.dump"; SYSTEM="$BACKUP/stage7-$TS-core-system.dump"
# two files: pg_dump ignores -n when -t is given (02-tests.md section 6, issue 2); one physical line for test :226
pgx pg_dump -Fc -h 127.0.0.1 -U "$PGSU" -n qualification -n control_objectives -n engine -n report_composer platform >"$SCHEMAS" && pgx pg_dump -Fc -h 127.0.0.1 -U "$PGSU" -t core.system platform >"$SYSTEM"
pgx pg_restore --list <"$SCHEMAS" | grep -q . && pgx pg_restore --list <"$SYSTEM" | grep -q 'TABLE core system'
isolate verify-dump --all "/backup/stage7-$TS-schemas.dump" "/backup/stage7-$TS-core-system.dump" --report "/backup/stage7-$TS-verify-dump.json"
# nothing wrote the retired tables since C9
now=$(psql_su -d platform -tA -c "SELECT json_object_agg(schemaname || '.' || relname, json_build_array(n_tup_ins, n_tup_upd, n_tup_del)) FROM pg_stat_user_tables WHERE schemaname IN ('qualification','control_objectives','engine','report_composer') OR (schemaname = 'core' AND relname = 'system')")
[ "$(jq -S . <<<"$now")" = "$(jq -S . "$BACKUP/c9-counters.json")" ] || { say "refused: retired tables changed since C9"; exit 1; }
psql_su -d platform -1 <<'SQL'
DROP SCHEMA qualification, control_objectives, engine, report_composer CASCADE;
DROP TABLE core.system CASCADE;
DROP FUNCTION IF EXISTS core.system_only_latest_changes();
SQL
```

- The argument order of `verify-dump` (two positional files after `--all`) follows `platform/tests/test_isolate.py:782`.
- Counters are reset by a Postgres crash. A mismatch then fails safe and the orchestrator decides.
- After the drop: `oneshot postgres-setup` must exit 0 (I2.8); `verify-project-databases.sh` exits 0 (I16.2, post-drop placement); print the I15.3 list, names only (databases `aisc`, `controls`, `qualification`, `control_objectives`, `control_objectives_test`, the three orphan project databases, the `catalogue` schema, Superset's `aisc_*` tables) as "kept, needs the user's decision".

#### 5.8 `steps` output

One line per step, each starting with its id: `C0   preconditions: commit set, forms merged, images, :pre-isolation tags`, … `C12  verify-project-databases.sh and the smoke list`. Then lines that do not start with `C<digit>`: `open  start caddy (point of no return)` and `stage 7: drop (after one day, dump, verify-dump, counters)`.

### 6. `scripts/isolation/rehearse.sh` (I15.1)

- **Setup.** `set -euo pipefail; umask 077`, then `ROOT`, `CUTOVER="$ROOT/scripts/isolation/cutover.sh"`. Require `AISC_IMAGE_TAG` not `latest`.
- **Pick the dump.** Exactly one `~/aisc-isolation-rehearsal/live-*.sql`, unless `REHEARSAL_DUMP` names one. With more than one, refuse and list the names. Only `live-20260925-1149.sql` exists today.
- **Workspace and names.** `WORK=$HOME/aisc-isolation-backup/rehearsal-<ts>`; `NAME=aisc-t-reh-<hex4>`; `NET=$NAME-net`.
- **Cleanup trap.** `trap cleanup EXIT`, plus INT and TERM. `cleanup` runs `docker ps -aq --filter label=com.docker.compose.project=$NAME | xargs -r docker rm -f`, `docker rm -f "$NAME"` and `docker network rm "$NET"`. It removes `$WORK/backup-*` (dumps of the live copy, with password hashes) unless `REHEARSAL_KEEP=1`.
- **`start_pg`.**
  - Port: a free port from python3; `[ "$PORT" != "5432" ] || { echo "rehearse: refusing port 5432" >&2; exit 1; }`.
  - Write `REH_PW` into `$WORK/pg.env` with `POSTGRES_DB=postgres`, so the dump's `CREATE DATABASE platform` does not collide.
  - `docker network create "$NET"`.
  - `docker run -d --rm --name "$NAME" --network "$NET" --network-alias postgres -p "127.0.0.1:$PORT:5432" --env-file "$WORK/pg.env" postgres:14-alpine`.
  - Wait until ready.
- **`restore <n>`.**
  - `docker exec -i "$NAME" psql -X -q -U aisc-postgres-user -d postgres -o /dev/null <"$DUMP" 2>"$WORK/restore-<n>.err"`.
  - Count `ERROR` lines other than `role "aisc-postgres-user" already exists`. Print only the count; if it is above 0, fail.
  - Over stdin to `docker exec -i … psql` (local socket), never on argv: reset the superuser password to `REH_PW` (the restore wrote the live hash). Set the module and reader roles' passwords to their role names; set `report_ro`, `report_composer_rw` and `inspector_ro` to their names too.
- **`$WORK/env.rehearsal`** (mode 600). `env.development` minus the overridden keys, plus:
  - `POSTGRES_PASSWORD=<REH_PW>`, `DB_PASSWORD=engine_rw`;
  - `REPORT_RO_PASSWORD=report_ro`, `REPORT_COMPOSER_PASSWORD=report_composer_rw`, `INSPECTOR_PASSWORD=inspector_ro`;
  - a random hex value for every other `${X:?` variable found in the two compose files.
- **`run_cutover <run> <args>`** passes `ISOLATION_STATE_DIR=$WORK/<run>`, `ISOLATION_BACKUP_DIR=$WORK/backup-<restore>`, `ISOLATION_PG_CONTAINER=$NAME`, `ISOLATION_NETWORK=$NET`, `ISOLATION_COMPOSE_PROJECT=$NAME`, `ISOLATION_ENV_FILE=$WORK/env.rehearsal`, `PGHOST=127.0.0.1 PGPORT=$PORT PGUSER=aisc-postgres-user PGPASSWORD PGDATABASE=platform` and `VERIFY_SKIP_CONTAINERS=1 VERIFY_SKIP_FUNCTIONAL=1`, then runs `bash "$CUTOVER" <args> --target rehearsal`.

Flow:
1. **Run 1.** `start_pg`, `restore 1`. Run `C0 C1 C2 C3 C4 C5 C6 C7 C8 C8b C9 C10 C11 C12` one by one. Assert every project in `copy.json` is `copied`. Save per-table digests of each project database (`md5(string_agg(t::text, E'\n' ORDER BY t::text))`, names and md5 only).
2. **Run 2, idempotence, same container, backup-1.**
   - Snapshot `xact_commit` of every `project_%` database (after `pg_stat_clear_snapshot()` and a one-second sleep) and the digests.
   - Run `C0..C7`, then `C8`. Assert every project is `already done`, `xact_commit` is unchanged, and the digests are equal ("the second run wrote nothing").
   - Continue `C8b..C12` and `open` (records only).
3. **Stage-7 drill.** `ISOLATION_DROP_MIN_HOURS=0 run_cutover run2 drop`. This proves the two dump files, verify-dump with a pg_restore 15 client against a 14 dump, the counter comparison, the DROP, `postgres-setup` after the drop, and I16.2.
4. **Run 3, inject a failure and resume, fresh restore.**
   - `docker rm -f "$NAME"`, `start_pg`, `restore 3`, run `C0..C7` with state `run3` and `backup-3`.
   - **Inject:** in the only project's database (`SELECT 'project_' || replace(pid::text,'-','') FROM core.project ORDER BY pid LIMIT 1`), `CREATE FUNCTION public.rehearsal_inject() … RAISE EXCEPTION 'injected failure'`; `CREATE TRIGGER rehearsal_inject BEFORE INSERT ON qualification.qualification_answer … ; ALTER TABLE … ENABLE ALWAYS TRIGGER rehearsal_inject` (the same method as `test_isolate.py:502`). Take a digest.
   - `C8` must exit non-zero, `copy.json` status must be `failed`, the state must not contain C8, and the digest must be unchanged (rolled back).
   - Drop the trigger and function. **Resume:** `C8` again exits 0 with status `copied`. Continue `C8b C9 C10 C11 C12`.
5. **Rollback drill (on run 3).** `rollback C9 --yes`: the ACL diff is empty. `rollback C8 --yes`: every project database has template 0001..0005 only; none of `project`, `qualification`, `control_objectives`, `engine`, `report_composer` exists there; `has_schema_privilege('qualification_rw','qualification','USAGE')` is true again in platform.
6. **Record.** Write `$HOME/aisc-isolation-backup/rehearsal-passed.json` with the fingerprint (from `cutover.sh fingerprint`), the dump file name only, `finished_at`, and per-run statuses. Write `$WORK/summary.txt` with counts and statuses only, and print it. Stage 5 writes 05-rehearsal.md from it; `rehearse.sh` never writes into a repo.

### 7. Cross-WP items X1 checks first (report any that is missing, do not fix another WP's code)

1. **P1: libraries on an existing volume.** `form_library` and `report_library` must be created by a file that runs on every start (`project-databases.sql` or `report-roles.sql`), not only by `platform-db.sql` (initdb only). Otherwise C5 fails on the live volume.
2. **P1: init files must not undo C9.**
   - `project-databases.sql:22` (`ALTER TABLE core.system OWNER TO platform_rw`) and the composite-key block must skip a retired `core.system`, not just a missing one.
   - `report-roles.sql:35-45` `GRANT SELECT/REFERENCES ON core.system`, `CREATE SCHEMA … report_composer`, `ALTER SCHEMA report_composer OWNER TO report_composer_rw` and the default privilege on core would un-retire the schemas, and after stage 7 would recreate `report_composer` in platform.
   - The re-run built into C9's check catches this.
3. **V1:** `report-grants.sh` must drop its platform section (I2.7). And I16.2 "unreachable by every non-superuser role" cannot hold for `inspector_ro` (`pg_read_all_data`, I11.1): V1 must exempt it, since C9 cannot remove it.
4. **P2:**
   - `verify-dump` must cope with the `-t core.system` archive: it has no `CREATE SCHEMA core`, no trigger function, and FKs to `core.project` in the schemas dump.
   - At C7 the controls "new head" must exclude I6.2's FK migration, which is held back to C8b.
   - The `isolate` entrypoint must work as a non-root uid.
5. **R1:** `python -m report_composer.migrate` (pinned by `isolation_bed.py:236`) exits 0, or 2 on a permanent error.
6. **E1:** `apps/backend/Dockerfile:55` CMD still runs `manage.py migrate` (used by the non-dev compose files); E1 should make it `migrate_projects` or drop it. `migrate_projects` should exit 2 on a permanent error.
7. **D1:** stop reading `AISC_RESULTS_DB_URI`; optionally provide `remove_results_connection()`.

### 8. How to test

```
cd /home/listuser/aisc-isolation
bash -n scripts/isolation/cutover.sh scripts/isolation/rehearse.sh
uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
  scripts/tests/test_cutover_script.py scripts/tests/test_compose_isolation.py scripts/tests/test_isolation_fixture.py
# expect: 71 passed
uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
  scripts/tests/test_compose.py scripts/tests/test_service_tokens.py scripts/tests/test_inspector_network.py \
  scripts/tests/test_report_stack.py scripts/tests/test_isolation_unchanged.py scripts/tests/test_llm_keys.py
# expect: the baseline (report_stack 2 and llm_keys 1 known reds, nothing new)
```

- **Optional self-check of C9's round trip** (throwaway only; recommended because no test covers it):
  1. Restore the dump into an `aisc-t-*` container with `rehearse.sh`'s `start_pg` and `restore` (behind a `--only-restore` flag that stops there).
  2. Write a scratch state `{"target":"rehearsal","passed":["C0","C1","C2","C3","C4","C5","C6","C7","C8","C8b"]}`.
  3. Run `C9`, then `rollback C9 --yes`, and require an empty ACL diff.
- **Never** run any step with `--target live`.
- **Never** run `rehearse.sh` in full in stage 4: it needs every WP's images, which is stage 5.
- **Never** build without `AISC_IMAGE_TAG` and `-p aisc-isolation-build`.

### 9. Commits (top-level repo `~/aisc-isolation`, explicit paths, never push)

1. `git commit -m "Isolation X1: compose wiring for project databases (migrate one-shots, DSN templates, membership DSN, isolate one-shot, image tag)" -- docker-compose.development.yml docker-compose-infra.development.yml platform/Dockerfile [env.development]`
2. `git commit -m "Isolation X1: cutover.sh, steps C0..C12 with checks, rollbacks, C9 ACL save and restore, stage-7 drop from two dump files" -- scripts/isolation/cutover.sh`
3. `git commit -m "Isolation X1: rehearse.sh, the I15.1 rehearsal on a throwaway restore (twice, injected failure and resume, drop and rollback drills)" -- scripts/isolation/rehearse.sh`

Set the executable bit before `git add`. Never add `__pycache__`.

### 10. Tests I believe are wrong or fragile (do not edit them; work as stated)

- **`scripts/tests/test_cutover_script.py:226-227` is WRONG.** It pins I15.2's single command (`pg_dump -Fc … -n qualification … -t core.system` on one line), which dumps `core.system` only. What to do: write the two correct commands on one physical line joined by `&&` (5.7); this is correct and passes. Record it in the WP notes, and fix I15.2's text in 01-specs.md.
- **`test_cutover_script.py:169` is over-broad.** It flags any `$ROOT/…\.sql|json` reference, reads included. What to do: use a separate directory variable and the `postgres-setup` one-shot (rule 4).
- **`test_cutover_script.py:57` and `:105` are fragile regexes.** What to do: follow rules 1 and 2.
- **`test_cutover_script.py:218-225` blocks listing schema names on rollback C8's drop.** What to do: build that drop dynamically with `%I` (5.6).
- **`scripts/tests/test_compose_isolation.py:128-144` (I9.1) passes vacuously:** it sets `REPORT_GENERATOR_DIR` itself. What to do: the cutover exports the variable and C0's fingerprint includes the renderer worktree HEAD.
- **`test_compose_isolation.py:164-184` never checks the engine:** `aisc-backend` and `aisc-backend-migrate` use `DB_*`, not a DSN, and are not listed. What to do: nothing in X1; V1's `docker inspect` (I16.4) covers it at C12.

### 11. Ambiguities I resolved (record them in the WP notes)

1. **Compose ownership:** X1 owns all top-level compose and env files (section 0).
2. **Qualification env file:** removed from the two qualification services instead of editing the submodule's env file. X1 then does not need to touch Q1's repository.
3. **Image-tag variable (4.0) added:** without it, isolation builds overwrite the live `:latest` images.
4. **`isolate` is its own profiled service:** the spec's `run platform` would put the superuser DSN into the long-running platform service. The password travels as `PGPASSWORD`.
5. **The rehearsal runs C0..C2 in a rehearsal mode:** the state machine requires them before C3, while the spec says C3..C10. C11 starts nothing in the rehearsal, and C12 there runs `verify-project-databases.sh` with `VERIFY_SKIP_CONTAINERS` and `VERIFY_SKIP_FUNCTIONAL`. The functional I16.5 runs live at C12 before caddy opens. This corrects the claim in 02-tests issue 10: a full rehearsal stack would collide with live container names, ports and the host-network dashboard.
6. **C7 does not run `controls-migrate`:** it is a no-op except for I6.2's FK, which belongs to C8b.
7. **Deleting `AISC Results` moves from C9 to C12:** the engine datasets leave it only when C11 re-registers the dashboards.
8. **Caddy is started by a separate `open` step after C12**, not in C11 (I14.7 overrides the C11 row of the table). The UI smoke therefore happens just after `open`.
9. **C2 takes a quiet-state platform dump:** C1 runs before the quiet window, so rollback C4 uses the quiet dump.
10. **C4 applies 0003..0005 with psql** from commit f01288a under `SET ROLE report_composer_rw` and the runner's lock, instead of a pre-isolation image.
11. **Evaluation status values are `Pending` and `Processing`**, not "running/pending".
12. **`c9-acl.json` is written once per target**, and a retired state is detected, so a re-run never saves the retired ACLs as the originals.
13. **The live-shape fixture is unchanged** (issue 6).
14. **The non-development compose files are out of scope.**

### 12. Questions for the user before stage 6 (the script refuses until they are set)

1. **Which env file does the live cutover use?** Presumably `~/aisc-install/env.runtime` (`env.plugin_downloader` + the live `env.secrets`), passed as `ISOLATION_ENV_FILE`. Never run `scripts/secrets.sh` in the worktree: it would mint a new `PLATFORM_SECRETS_KEY` and make every stored LLM key unreadable.
2. **From which directory should the live stack run after C11?** The compose bind mounts (`./shared/identity`, `./platform/*`, `./init`, `./Caddyfile`) follow `ISOLATION_COMPOSE_DIR`. With the default (`~/aisc-isolation`), the live stack depends on the worktree until the branch is merged into `~/aisc-install`, which the rules forbid us to touch.

---

## WP Z1: every suite together

**Repos**: all, read-only except `docs/superpowers/isolation-2026-09-25/04-code-notes.md`. **Depends on**: every WP
(Q2 either done or its gate recorded as closed). Its purpose is to prove that the WPs, each green on its own, are
green together on the final branch state, before stage 5 builds images and rehearses.

### Steps

1. `git status` in the top-level worktree, every submodule worktree and the renderer worktree: no modified tracked
   file other than tracked `__pycache__` noise; every WP commit present; gitlinks point at the submodule HEADs
   (`git submodule status` shows no `+`).
2. New-layout recipe (section 1.1) once per database suite, each on its own throwaway, in this order, recording
   passed/failed/skipped per suite in `04-code-notes.md`:
   - platform: whole suite including `tests/test_isolate.py` and `tests/test_init_after_retire.py`;
   - top-level `scripts/tests` (all files; the DB tests start their own containers);
   - qualification unit (`npx vitest run test/unit`, `npx tsc --noEmit`), qualification db
     (`THROWAWAY_PREFIX=aisc-t-iso-Q bash test/db/throwaway-db.sh`), qualification agents;
   - control objectives; controls (the safe file list of 02-tests.md section 2 only);
   - backend sqlite, backend Postgres (`DJANGO_SETTINGS_MODULE=config.settings_single_database`), backend isolation DB;
   - eval; webapp (`npx vitest run`, `npx tsc -b --noEmit`);
   - results-dashboard (bare container); report composer; report renderer.
3. Harness runs: `scripts/guard-frozen.sh` (G1..G5), `scripts/test-pipeline-chain.sh` and each `--break` link,
   `scripts/verify-project-databases.sh` against the fresh-volume bed of `test_fresh_volume.py` with
   `VERIFY_SKIP_CONTAINERS=1 VERIFY_SKIP_FUNCTIONAL=1`.
4. Acceptance: every stage-2 red of 02-tests.md section 3 is green (the Q2 ones may still skip only with the I4.6
   reason); every pre-existing test is at its baseline or green, or is a change named in some WP's notes; the
   known reds that stay are listed by name (06-report N1..N7, F5, schema_docs 4, llm_keys 1, report_stack 2 unless
   fixed on purpose). `test_fresh_volume.py::test_i16_4_post_projects_on_a_fresh_volume_yields_a_complete_project_database`
   is green (it needs every module).
5. `docker ps -a --filter name=aisc-t- -q` is empty.
6. Commit `docs/superpowers/isolation-2026-09-25/04-code-notes.md` (the Z1 section with the counts) and a stage-4
   row in `PROGRESS.md`: "Isolation Z1: every suite green together on the isolation branch (counts in 04-code-notes.md)".

Stopping rule: a red that no WP names stops Z1; it is reported with the suite, the test and the first failing
line, and the owning WP (by the ownership rules of section 2) is re-opened. Z1 fixes nothing itself.
