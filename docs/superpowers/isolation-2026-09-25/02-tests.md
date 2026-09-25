# Stage 2: failing tests for one database per project

Date: 2026-09-25. Branch `isolation/2026-09-25` in `~/aisc-isolation`, its submodule worktrees and
`~/aisc-isolation-report-generator`. Input: `RULES.md`, `01-specs.md` (with D3/D4 as confirmed by the
user). This stage resumed an attempt that stopped at a usage limit; every file it left was reviewed,
fixed or finished, none was deleted. No product code was changed: every new file is a test, a test
fixture or a test helper. Nothing was pushed.

## 1. Commits

| repo | commit | files |
|---|---|---|
| top-level | `78b64fd` | `scripts/tests/{isolation_bed,test_project_grants,test_verify_project_databases,test_isolation_harnesses,test_fresh_volume,test_cutover_script,test_compose_isolation,test_isolation_fixture}.py`, `scripts/tests/fixtures/isolation/live_shape.sql`, `scripts/lib/report_bed_isolated.py` |
| top-level | `fd88f32` | `platform/tests/test_project_system.py` |
| top-level | `ebd0ae8` | `apps/report-composer/tests/{isolation_fixtures,test_isolation_project_databases,test_isolation_cross_project}.py` |
| top-level | `efded99` | `platform/tests/{test_isolate,isolate_support}.py` (the move tool) |
| top-level | `07a2e19` | `scripts/tests/test_isolation_unchanged.py` (I11.4, I18.6 guards) |
| apps/qualification | `bfc69ef` | `test/support/isolation.ts`, `test/unit/isolation{ProjectDb,Routes,ActionsAndPages,Baseline}.test.ts`, `test/db/{projectDatabase,formLibrary}.db.test.ts`, `test/db/throwaway-db.sh` (extended), `services/agents/tests/test_isolation_paths.py` |
| apps/control-objectives | `22ba3a2` | `tests/isolation_support.py`, `tests/test_isolation_static.py`, `tests/test_isolation_project_databases.py` |
| apps/controls | `bc5aca2` | `test/integration/{isolation-answer-fk,isolation-routes-by-id}.test.ts`, `test/integration/isolationDb.ts`, `test/unit/isolationControls.test.ts` |
| apps/backend | `3e262a7` | `aisc_backend/tests/{isolation_support,test_isolation_engine,test_isolation_engine_db}.py` |
| apps/eval | `7f7de02` | `tests/test_run_ticket.py` |
| apps/webapp | `a27871b` | `src/api/projectHeader.i7_4.test.ts`, `src/components/PluginInstallDialog.i7_4.test.tsx` |
| apps/results-dashboard | `9e0d018` | `tests/test_isolation_dashboard.py`, `tests/test_isolation_dashboard_db.py` |
| report renderer | `27bb0cb` | `tests/test_isolation_project_databases.py` (worktree `~/aisc-isolation-report-generator`, already existed on the branch from `dev` f632271) |

The top-level commit that adds this file also records the new submodule commits (gitlinks).

## 2. How to run each suite

Every database suite used its own throwaway `postgres:14-alpine` named `aisc-t-iso-<suite>-<rand>` on a
random port (never 5432), removed afterwards (checked: no `aisc-t-*` container left). Recipe (paths in
`~/aisc-isolation`, secrets never printed):

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
# suite command below
docker rm -f $NAME
```

| suite | command (from) |
|---|---|
| platform | `platform/`: `PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform PLATFORM_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` (baseline: add `--ignore=tests/test_project_system.py --ignore=tests/test_isolate.py`; the move tool alone: `tests/test_isolate.py`, about 21 s red, about 8 min once the tool exists) |
| top-level scripts | repo root: `uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider scripts/tests/<files>` (the DB tests start their own `aisc-t-*` containers) |
| qualification unit | `apps/qualification`: `npx vitest run test/unit` (baseline `--exclude 'test/unit/isolation*'`); `npx tsc --noEmit` |
| qualification db | `apps/qualification`: `THROWAWAY_PREFIX=aisc-t-iso-Q bash test/db/throwaway-db.sh` |
| qualification agents | a scratch directory: `A=/home/listuser/aisc-isolation/apps/qualification/services/agents; uv run --no-project --with-requirements $A/requirements.txt --with pytest --with httpx --with rdflib python -m pytest -q -p no:cacheprovider -c $A/pytest.ini --rootdir $A $A/tests` |
| control-objectives | `apps/control-objectives` (after `CREATE DATABASE control_objectives_test`): `CONTROL_OBJECTIVES_TEST_DATABASE_URL=postgresql+psycopg://aisc-postgres-user:$PW@127.0.0.1:$PORT/control_objectives_test PLATFORM_TEST_DATABASE_URL=postgresql://platform_rw:platform_rw@127.0.0.1:$PORT/platform uv run --extra dev pytest -q -p no:cacheprovider` |
| controls | `apps/controls`: `CONTROLS_TEST_PG_CONTAINER=$NAME PROJECT_DATABASE_URL="postgresql://controls_rw:controls_rw@127.0.0.1:$PORT/{database}?schema=controls&connection_limit=2" npx vitest run test/unit test/integration/answer-stamps.test.ts test/integration/dashboard-grants.test.ts test/integration/install-once-throwaway.test.ts test/integration/isolation-answer-fk.test.ts test/integration/isolation-routes-by-id.test.ts`. Never run `project-scope`, `action-access`, `install`, `project-database`, `submission-lifecycle` or `chain`: they `docker exec postgres`, the LIVE container. |
| results-dashboard | `apps/results-dashboard`, on a BARE container (its old fixture sets itself up and cannot run twice): `AISC_DASHBOARD_TEST_PG_CONTAINER=$NAME PYTHONPATH=. uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider --ignore=tests/test_sso_login.py` |
| backend sqlite | `apps/backend`: `PYTHONPATH=$PWD/../../shared/plugin-interface/src DB_ENGINE=django.db.backends.sqlite3 DB_NAME=$SCRATCH/t.db .venv/bin/python manage.py test aisc_backend` |
| backend Postgres | same with `DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=aisc-postgres-user DB_PASSWORD=$PW DB_HOST=127.0.0.1 DB_PORT=$PORT PLATFORM_TEST_DATABASE_URL=… manage.py test --noinput aisc_backend` |
| backend isolation DB | `ENGINE_TEST_SUPERUSER_URL=postgresql://aisc-postgres-user:$PW@127.0.0.1:$PORT/platform PLATFORM_TEST_DATABASE_URL=… DB_ENGINE=django.db.backends.postgresql DB_NAME=platform DB_USER=engine_rw DB_PASSWORD=engine_rw DB_HOST=127.0.0.1 DB_PORT=$PORT DB_SCHEMA=engine .venv/bin/python manage.py test --noinput aisc_backend.tests.test_isolation_engine_db` |
| eval | `apps/eval`: `uv run --group test python -m pytest -q -p no:cacheprovider --noconftest tests --ignore=tests/test_basic_integration.py` (the conftest needs `onnxruntime`, absent; `test_basic_integration.py` is a pre-existing collection error) |
| webapp | `apps/webapp`: `npx vitest run` |
| report composer | `apps/report-composer`: `env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL REPORT_GENERATOR_DIR=/home/listuser/aisc-isolation-report-generator uv run --extra dev pytest -q -p no:cacheprovider` (beds make their own containers) |
| report renderer | `~/aisc-isolation-report-generator`: `env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL AISC_INSTALL_DIR=/home/listuser/aisc-isolation uv run --extra dev pytest -q -p no:cacheprovider` |

## 3. Baselines and red counts

"Baseline" is the suite on this branch before the new files; "new" are the tests added in stage 2.
Every red was checked to fail on the missing feature (a missing module, template file, route,
migration or an assertion carrying the requirement ID against today's layout), not on a fixture bug
or a collection error. Every pre-existing test keeps its baseline result.

| suite | baseline | with the new tests | new: red / green guards / skipped |
|---|---|---|---|
| platform (without the move tool) | 278 passed, 2 skipped (`test_chain.py`, CHAIN_JSON unset) | 32 failed, 287 passed, 2 skipped | 32 / 9 / 0 |
| platform move tool `test_isolate.py` | not applicable | 55 failed, 3 passed | 55 / 3 fixture self-tests / 0 (all 58 skip without the two DSNs) |
| top-level scripts (pre-existing files) | 226 passed, 25 failed (known: guard_frozen 11, pipeline_chain 5, schema_docs 4, db_consistency 2, report_stack 2, llm_keys 1) | unchanged | |
| top-level scripts (new files) | not applicable | 195 failed, 10 passed (+4 passed in `test_isolation_unchanged.py`) | 195 / 14 / 0 |
| qualification unit (vitest) | 452 passed, 1 failed (`secrets.test.ts`, EISDIR on the node_modules symlink) | 457 passed, 98 failed, 3 skipped | 97 / 5 / 3 (Q2) |
| qualification db | 8 passed, 4 failed (3: symlinked Prisma client generated from the forms schema; 1: `cardVersions` S3.3 hits the composite key), 7 skipped | 9 passed, 22 failed, 16 skipped | 18 / 1 / 9 (Q2) |
| qualification agents | 164 passed | 167 passed, 8 failed | 8 / 3 / 0 |
| control-objectives | 318 passed, 1 skipped | 321 passed, 38 failed, 20 errors, 1 skipped | 58 (38 failed + 20 errors, see note) / 3 / 0 |
| controls | 141 passed | 150 passed, 9 failed | 9 / 9 / 0 |
| results-dashboard | 110 passed | 120 passed, 14 failed | 14 / 10 / 0 |
| backend sqlite | 140 ran: 6 failures, 5 errors, 13 skipped (known: F5 ImportError, three `test_g4`, three keycloak integration, three `project_config_router`, `s1_aisystem`) | 203 ran: 54 failures, 5 errors, 40 skipped | unit file 30 red / 5 green; DB file 27 skip (needs Postgres) / 1 |
| backend Postgres (superuser run) | 140 ran: 6 failures, 6 errors, 9 skipped (also `s9_3`) | 203 ran: 53 failures, 6 errors, 37 skipped | as above |
| backend isolation DB module | not applicable | 28 ran: 27 failed, 1 passed | 27 / 1 / 0 |
| eval | 5 passed, 1 failed, 1 error | same pre-existing, plus `test_run_ticket.py` | 9 / 1 / 0 |
| webapp | 7 files, 42 passed | 42 passed, 5 failed | 5 / 0 / 0 |
| report composer | 427 passed | 427 passed, 56 failed | 56 / 0 / 0 |
| report renderer | 642 passed | 648 passed, 24 failed | 24 / 6 / 0 |

Notes on the reasons:
- Most DB-backed reds stop at the first missing piece, WP P1's template `0006_project_system.sql`
  (`project.system` absent). Several suites carry an idempotent stand-in for 0006..0010 (applied only
  when the real file is missing) so that their reds point at their own module instead of P1:
  control-objectives, the move tool helper, the composer/renderer bed (`scripts/lib/report_bed_isolated.py`).
  Where no stand-in is used (controls, dashboard, backend DB), a dry run with scratch stand-ins was done
  and the next stop was the module's own missing feature.
- Control objectives: the 20 errors are the two-project fixture, which creates an assessment through
  the API and gets 500 `relation "control_objectives.project" does not exist` because today's code still
  writes the shared schema. That is the missing feature, not a fixture bug.
- Green guards pin behaviour that already holds and must survive (name rule, delete order, diagrams gate,
  public catalogue routes, controls routes by id across projects, I9.4 signatures, I18.1 tokens).

## 4. Requirement to test

Every `I<n>.<m>` of 01-specs.md is named by at least one test (checked by a grep of every ID, dotted or
underscored, over every committed test file of every repo: 119 of 119).

| requirements | suite and file | tests (prefixes) |
|---|---|---|
| I1.1, I1.2, I1.4, I1.5, I1.6, I1.7, I1.8, I2.1..I2.5, I2.8, I2.9, I11.2, I17.1 (platform), I18.5 | platform `tests/test_project_system.py` | `test_i1_2_*`, `test_i1_4_*`, `test_i1_5_*`, `test_i1_6_*`, `test_i1_8_*`, `test_i2_1_*` .. `test_i2_9_*`, `test_i11_2_*`, `test_i17_1_*`, `test_i18_5_*` |
| I12.1..I12.16, C6 provision, D4, D14, D15, I13.4 | platform `tests/test_isolate.py` | `test_I12_*` (42 functions, 58 cases with parameters), `test_fixture_*` |
| I1.3, I1.4, I2.8, I16.2..I16.4 (fresh volume) | `scripts/tests/test_fresh_volume.py` | `test_i1_3_*`, `test_i1_4_*`, `test_i2_8_*`, `test_i16_4_*` |
| I1.2, I2.1, I2.6, I2.7, I10.3, I11.1, I16.1, D10 | `scripts/tests/test_project_grants.py` | `test_i2_1_*`, `test_i2_6_*`, `test_i2_7_*`, `test_i11_1_*` |
| I1.4, I16.1..I16.5, I16.7, I17.1, I19.1 | `scripts/tests/test_verify_project_databases.py` | `test_i16_*` |
| I7.12, I11.2, I11.3, I16.6, I18.7, I19.2, I19.3 | `scripts/tests/test_isolation_harnesses.py` | |
| I13.1..I13.4, I14.1..I14.7, I15.1..I15.3, I18.7 | `scripts/tests/test_cutover_script.py` | |
| I3.6, I3.8, I5.1, I5.5, I7.6, I8.1, I9.1, I9.2, I10.2, I16.4, I18.1 (compose wiring) | `scripts/tests/test_compose_isolation.py` | |
| I3.7, I7.9 (fixture), I18.7 | `scripts/tests/test_isolation_fixture.py` | |
| I11.4, I18.6 | `scripts/tests/test_isolation_unchanged.py` | green guards |
| I1.8, I2.5, I3.1..I3.4, I3.8, I16.5, I17.1, I18.1, I18.3, I18.4 | qualification `test/unit/isolation{ProjectDb,Routes,ActionsAndPages}.test.ts` | |
| I3.5, I4.* (static) | qualification `test/unit/isolationBaseline.test.ts` | |
| I1.5..I1.7, I2.5, I2.6, I3.5..I3.7, I16.5 | qualification `test/db/projectDatabase.db.test.ts` | |
| I4.1..I4.6 (Q2, D3) | qualification `test/db/formLibrary.db.test.ts`, `isolationBaseline` | skip with "I4.6 gate: forms files absent on this branch; WP Q2 waits for the forms merge", decided at run time |
| I3.4, I18.1, I18.4 | qualification `services/agents/tests/test_isolation_paths.py` | |
| I1.1, I1.6..I1.8, I5.1..I5.7, I16.5, I17.1, I2.5, I18.2, I18.3 | control-objectives `tests/test_isolation_static.py`, `tests/test_isolation_project_databases.py` | `test_I5_*`, `test_I16_5_*`, `test_I17_1_*`, auth mirrors in section 3 of the DB file |
| I6.1, I6.2, I2.5, I17.1, I16.5 | controls `test/unit/isolationControls.test.ts`, `test/integration/isolation-*.test.ts` | |
| I7.1..I7.12, I2.5, I2.6 (engine), I16.5, I17.1 | backend `test_isolation_engine.py` (sqlite and static), `test_isolation_engine_db.py` (Postgres) | `TheDoorOrder` (17-row table), `ROUTES` (70 rows), `EveryRouteByIdIsInTheTable` |
| I7.3 | eval `tests/test_run_ticket.py` | |
| I7.4 | webapp `projectHeader.i7_4.test.ts`, `PluginInstallDialog.i7_4.test.tsx` | |
| I8.1..I8.6, I2.5, I2.6, I17.1, I16.5, D4 | report composer `tests/test_isolation_project_databases.py`, `tests/test_isolation_cross_project.py` | `test_i8_*`, `test_i16_5_*` |
| I9.1..I9.4 | renderer `tests/test_isolation_project_databases.py`; I9.1 wiring in `test_compose_isolation.py` | |
| I10.1..I10.5, I19.3, I16.5, I17.1, I1.8 | results-dashboard `tests/test_isolation_dashboard.py`, `tests/test_isolation_dashboard_db.py` | |

### 4.1 Cross-project isolation by id (I16.5, risk 3), per module

An object of project A is addressed under project B (by B's pid, header or database) and must be 404,
with A's rows unchanged; where it matters the caller is a member of both, so the 404 comes from the
database and not from membership.

- **Qualification**: the seven card routes under `/p/{pid}/api/qualifications/{id}/…` (ai-card.json,
  ai-card.pdf, system-card.pdf, ontology.jsonld, ontology.ttl, fill, extracted), the
  `system-versions/{systemPid}/ontology.jsonld` route, the five server actions (loadOntology,
  patchOntologyNode, resetOntology, linkComponent, unlinkComponent), `QualificationService.get`/`list`
  behind the pages; old `/api/qualifications/*` paths 404; link and `revalidatePath` scans.
- **Control objectives**: page `GET /p/{p}/projects/{id}`, forms `POST …/{id}/map`, `…/{id}/severity`,
  JSON `GET`/`DELETE /p/{pid}/api/projects/{id}`, `POST …/{id}/map`, `…/{id}/severity`; lists; old
  `/api/projects*` 404; by slug and as admin.
- **Controls** (already per database, green guards): pages `checklists/[id]/fill`,
  `checklists/[id]/review`, `submissions/[id]`; actions submitForm, saveReviewedQuestions, saveDraft,
  reopenForAmendment, archiveSubmission, restoreSubmission; `submissions/[id]/report`.
- **Engine**: 70 routes (projects 14, components 6, evaluations 8, tasks 1, files 3, stats 4, project
  settings 5, plugins 15, internal 14 with a valid ticket for B and A's evaluation), plus 9 reads under
  A that must be 200; `EveryRouteByIdIsInTheTable` fails if `config.urls.api` gains a route missing from
  the table.
- **Report composer**: layouts/{id} GET, PUT, DELETE, validate, preview (GET, POST), outline, duplicate,
  export, preset, reports (GET, POST); reports/{id} pdf and download; templates/{id} PUT, DELETE, export,
  logo; page `GET /p/{ref}/layouts/{id}`. `presets/{id}` is the install-wide library (D4), no case.
- **Renderer**: `NotInProject` 404 on `/v1/choices`, `/v1/coverage-choices`, `/v1/render` for a version
  of another project; no B data in an A report.
- **Dashboard**: unregistering A leaves B's objects; each project database role sees only its rows.

## 5. Decisions taken in this stage (the user was not available)

- **S-D1 Move tool interface** (pinned in the docstring of `platform/tests/test_isolate.py`): CLI
  `python -m platform_service.isolate {plan,provision,copy,verify,verify-dump,report} (--project PID… |
  --all) [--dry-run] [--report PATH]`, `ISOLATE_SUPERUSER_URL` whose database is the source, exit
  non-zero on any refusal, report keys `subcommand, dry_run, snapshot_time, classification,
  refusals[{reason,table,project,projects,keys}], projects[pid]{database,status,tables{…},sequences},
  library, unowned[{table,key,reason}], coverage`, and the named refusal reasons listed there. Read-only
  target reads end in ROLLBACK (so `xact_commit` proves no write).
- **S-D2** `report_composer.preset` (0005) is a library table: all its rows go to
  `report_library.preset`, none into a project (its FK to core.project would otherwise make it a root).
- **S-D3** With the forms tables absent the old-head check accepts the pre-forms history and the library
  copy is skipped. `copy` refuses a project with no database (I12.6); `plan` reports it (I12.5).
- **S-D4** A database made by `isolate provision` is owned by platform_rw (as the superuser, template
  0001's `REVOKE CONNECT FROM PUBLIC` would lock platform_rw out).
- **S-D5** Q2 tests follow D3 as confirmed: library in `platform.form_library`, copy on use, R47 across
  two projects; seams `createFromForm(project, formData)` with `formVersionId` and
  `formService.chooserOptions()` taken from the forms work in `~/aisc-install` (WP Q2 may adapt a seam,
  never an assertion). They skip at run time while the forms files are absent.
- **S-D6** Env names: control-objectives `DATABASE_URL` = platform (membership only),
  `PROJECT_DATABASE_URL` = template with `{database}`; modules `aisc_control_objectives.projectdb`
  (`database_name`, `ProjectDatabases.open`) and `aisc_control_objectives.migrate_projects.main`; app
  built by `server.build_app()`. A start naming a version absent from `project.system` is 4xx (409
  suggested), never 500. Qualification `migrate-projects.mjs` reads `PROJECT_DATABASE_URL` and
  `FORM_LIBRARY_DATABASE_URL`; `schema.prisma` may keep `env("DATABASE_URL")` for the CLI.
- **S-D7** Composer factory `create_app(*, database_url, project_database_url, renderer, clock)`
  (only the fixture needs editing if stage 4 names it differently). Its old migrations 0001..0005 must be
  gone from the top of `migrations/` (by analogy with I3.5). Gamma (a project row, no database) gives
  `empty` blocks per I9.3, not 404.
- **S-D8** Engine: every internal worker call also sends `X-AISC-Evaluation` (E-G1): internal routes for
  project settings and files carry no evaluation in the path, so the ticket needs it; when the path names
  an evaluation the two must match. Ticket tests read the Celery message, not the frozen router source.
  The core-name scan looks at SQL only (frozen models name `core.*` in comments). The SPA may have at most
  one module in `src/` that calls the network (today 23 files do).
- **S-D9** I6.2's refusal message must contain the absent pid and the text `project.system`.
- **S-D10** I1.4 read strictly: a module role gets SELECT on `core.project` and `core.project_member`
  only (no `core.schema_migration`, no REFERENCES); `controls_rw` counts as a module role. The catalogue
  schema owner is not asserted (the superuser owns it today; catalogue-migrate makes its tables).
- **S-D11** `verify-project-databases.sh` contract: `VERIFY_SKIP_CONTAINERS=1` and
  `VERIFY_SKIP_FUNCTIONAL=1` let the tests run its static and database parts; `cutover.sh rollback
  <step> --print` texts are pinned ("pre-isolation", "nothing to undo", "rollback C8", "c9-acl.json").
- **S-D12** `scripts/lib/report_bed_isolated.py` stays in `scripts/lib` next to `report_bed.py`, which the
  composer and renderer tests already import from there; it is test infrastructure, not product code.
- **S-D13** The existing frozen-file guards and the tests that pin today's layout were not edited (RULES:
  only where the approved design changes behaviour, and that is stage 4). Stage 4 must change, and name
  in its WP notes: backend `test_frozen_sean_files.py` (settings.py), `test_one_system_per_project.py`
  (leaf 0025), `test_evaluation_system_stamp.py` (S9 on core.system), `scripts/guard-frozen.sh` G1/G4/G5;
  qualification agents `test_service.py`, `test_project_llm.py`, `test_service_token.py`,
  `test_clients.py` (old fill/extracted paths) and `test/db/cardVersions*.db.test.ts` (core.system);
  control-objectives `test_api_auth.py` (paths only, every case mirrored at `/p/{pid}/api` in the new
  file), conftest `repository`/`system_version` fixtures, `test_migration_*`; dashboard `test_projects.py`
  S11.1/S11.4, `test_results_database.py`, engine parts of `test_project_datasets_db.py`.

## 6. Spec gaps and open issues for stage 3

1. **Fresh volume vs platform migrations** (I1.3/I2.8): platform migrations 0002..0004 need
   `core.system`; a fresh `core` with three tables needs P1 to guard them or end the history with a new
   migration. The test pins only the end state; P1 decides.
2. **I15.2's dump command is wrong**: `pg_dump -n … -t core.system` ignores the `-n` options when `-t`
   is given. The stage-7 dump needs two files (schemas, and core.system); `verify-dump` takes both.
3. **`engine.metric_category_metrics` is never placed by I12.3** (link table with its own PK and FKs to
   metric and category); its rows would come out unowned although I7.10 makes them per project. Live has
   0 rows. Proposed rule for stage 3: a link row whose every FK points at rows copied to P is needed by P.
4. **Owned-by-two and cross-project reference overlap** (I12.4): the tests accept either reason.
5. `form_library` migration head names are not in the spec (no precondition test on them); the `report`
   subcommand's meaning is pinned by the tests as a read-only current-state report.
6. **Fixture**: `live_shape.sql` has no `CREATE SCHEMA core` and no `core.system_only_latest_changes()`;
   the qualification, engine and move-tool loaders create them first. Left as is (changing it now would
   break those loaders); a stage-4 change must keep the loaders in step.
7. **Existing leak found**: `GET /plugins/{evaluation_plugin_pid}/evaluations/{evaluation_uuid}/result`
   has no membership check today (`test_every_project_route_is_guarded` misses it). Isolation closes it
   and `ROUTES` covers it; the live system is exposed until then.
8. Engine `ROUTES` request bodies were checked by reading the schemas, not end to end; a body that does
   not validate would give 422 instead of 404 and needs fixing in E2.
9. Control-objectives I5.1 "one migration for concurrent first requests" is proven by outcome only (all
   200, one `alembic_version` row); the LRU test polls `pg_stat_activity` for up to 5 s; two DB tests use
   the dev role passwords (password = role name) set by `init/platform-db.sql`.
10. The dashboard has no per-project DSN template (host:port plus the bridge), so I16.4 only asks it for no
   stray `platform` DSN. I16.4's docker-inspect part and I16.5's functional part of
   `verify-project-databases.sh` are checked statically here and run for real in the rehearsal.
11. Suites with runners that are unsafe or fragile, kept out of the commands above: controls integration
   files that `docker exec postgres` (the live container), dashboard `test_sso_login.py` (needs
   Superset), eval `test_basic_integration.py` and its conftest (`onnxruntime`).
12. Q2 gate (I4.6) still closed: the forms work is not on this branch; its tests skip and will run once
   merged.
