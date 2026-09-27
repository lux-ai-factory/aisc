# Stage 1: specification for finishing the isolation (one database per project)

Date: 2026-09-25. Branch `isolation/2026-09-25` in `~/aisc-isolation` and its submodule worktrees.
Binding input: `RULES.md` in this folder. The user is not available; every decision is recorded in
section 22 with its reason. Requirements are numbered `I<section>.<n>`; each names the suite that proves
it (section 20). "MUST" is binding. Anything under "Note" is context.

Survey method: every file named in the brief was read; the live database was read with SELECTs only
(a `default_transaction_read_only = on` session as the superuser); five read-only survey passes covered
qualification, control-objectives, the engine (backend, worker, SPA), the report composer, renderer,
dashboard and inspector, and the scripts, init files and compose files. Nothing was written anywhere
except this file and PROGRESS.md.

---

## 0. What exists today (survey, 2026-09-25 ~13:00)

### 0.1 Databases on the live cluster

`max_connections` = 100, no PgBouncer. Databases: `platform`, `superset`, `keycloak`, `postgres`,
four `project_*`, and leftovers `aisc`, `controls`, `qualification`, `control_objectives`,
`control_objectives_test`. `core.project` has exactly one row: `01399e17-4b01-4be9-997a-7f5e3574ab22`
(slug `microcredit-assist-score-mcas`, "MCAS"). Its database `project_01399e174b014be9997a7f5e3574ab22`
exists. `project_2037…`, `project_a4c8…`, `project_d784…` are orphans (no `core.project` row, template
0001 only, empty controls tables).

Row counts in `platform` (exact, `count(*)`):

| schema.table | owner | rows | project key |
|---|---|---|---|
| core.project | superuser | 1 | stays shared |
| core.project_member | platform_rw | 2 | stays shared |
| core.schema_migration | platform_rw | 4 (0001..0004) | stays shared |
| core.system | platform_rw | 1 (MCAS, number 1, `1e722ea2-…`) | `project_id` FK core.project CASCADE |
| qualification._prisma_migrations | qualification_rw | 18 (head `20260925120000_the_default_form_is_fixed`) | bookkeeping |
| qualification.qualification | qualification_rw | 1 (`cmue7pq23000mpv7zew2fghpg`, form_version_id NULL) | `project_id` FK core.project; `system_id` FK core.system; composite (system_id, project_id) |
| qualification.qualification_answer / _risk / knowledge_graph | qualification_rw | 14 / 5 / 1 | FK to qualification |
| qualification.card_component | qualification_rw | 0 | FK to qualification; `component_pid` soft ref to engine.ai_component.pid |
| qualification.form / form_version / form_question / form_version_question | qualification_rw | 1 / 1 / 14 / 14 (the seeded Annex IV default only) | no project column (install-wide by product decision, see 0.4) |
| control_objectives.alembic_version | control_objectives_rw | 1 (`7c3e5a9b1d24`) | bookkeeping |
| control_objectives.project (the assessment) | control_objectives_rw | 1 (`0a013fbcc79b`) | `project_id` uuid FK core.project; `system_id` FK core.system; composite |
| control_objectives.graph / risk / mapping_run / mapped_objective | control_objectives_rw | 1 / 5 / 1 / 0 | FK to control_objectives.project.id (their `project_id` column is the assessment id) |
| engine.* (Django, frozen definitions) | engine_rw | project 1, ai_system 1, plugin 2, others 0; django_migrations 26 (leaf 0024), django_content_type 22 | `engine.project.project_id` uuid FK core.project SET NULL; `engine.evaluation.system_id` FK core.system SET NULL; everything else FK-chains to engine.project, except metric, metric_category (global, no project) |
| report_composer.schema_migration | report_composer_rw | 2 (0001, 0002 only; 0003..0005 NOT applied live) | bookkeeping |
| report_composer.layout / layout_block / template / generated_report | report_composer_rw | 1 / 7 / 1 / 4 | `project_id` FK core.project CASCADE; `system_id` FK core.system (composite keys added by init/project-databases.sql) |
| catalogue.* | catalogue_rw | 8 tables | stays shared (roadmap) |

Sequences with values: `control_objectives.risk_id_seq` 10; engine `aisc_backend_plugin_id_seq` 30,
`aisc_backend_project_id_seq` 72, `aisc_backend_aisystem_id_seq` 1, `django_content_type_id_seq` 29,
`django_migrations_id_seq` 51.

Triggers and functions in the moving schemas: `core.system_only_latest_changes` (reads max(number) per
project_id); `qualification.card_is_latest(uuid)` (reads `core.system`), and the triggers
`qualification_only_latest_changes`, `qualification_answer_only_latest_changes`,
`card_component_only_latest_changes` that call it; the forms triggers `form_name_is_fixed`,
`form_builtin_is_fixed`, `form_version_is_append_only`, `form_question_identity_is_fixed`,
`form_version_question_is_append_only`.

The project database of MCAS holds: `controls.*` (checklist 4, checklist_question 123, source 2,
submission 0, submission_answer 0, `_prisma_migrations` 3 at head), `llm.provider` 0,
`llm.system_choice` 0, `provision.template_migration` 5 (0001..0005). Grants on it: CONNECT for
controls_rw, dashboard_ro, inspector_ro, report_ro; `engine_rw` and the other module roles cannot
connect (pinned by `platform/tests/test_project_databases.py`).

Superset (`superset` database): two connections, `AISC Results` (dashboard_ro on `platform`, exposed in
SQL Lab) and `AISC Controls microcredit-assist-score-mcas` (dashboard_ro on the project database).
Datasets: `engine_results_<hex>` on `AISC Results` (joins `engine.*` and `core.system`, filtered by
pid) and `controls_answers_<hex>` on the project connection. One dashboard `aisc-<hex>`, role
`AiscProject_<hex>`. `aisc_comment` 0 rows, `aisc_review_request` 0 rows; neither has a foreign key or a
project column.

Live sessions at survey time: platform_rw 1 and qualification_rw 2 on `platform`; superset 5; no module
session on any project database. `aisc-eval-worker` and `rabbitmq` are exited.

### 0.2 Code paths that read or write each module's data

- **Platform** (`platform/platform_service`): `db.py` writes and reads `core.system` (`create_version`,
  `list_versions`, `latest_version`, `get_system`); `projectdb.py` creates, provisions (template runner
  into `provision.template_migration`) and drops project databases; `llm_store.py` already connects to
  each project database as `platform_rw` (the model for everything below); `dashboard_bridge.py`
  registers on create and unregisters before drop; `app.py` `/authz/schema` is the diagrams gate,
  regex `^(platform|project_([0-9a-f]{32}))$`.
- **Qualification** (`apps/qualification`): one global Prisma client on
  `platform?schema=qualification`; no per-project routing; raw SQL only in `cardLatest.ts`
  (`qualification.card_is_latest`); card versions are made by calling the platform
  (`PlatformClient.createVersion`); six routes under `src/app/api/qualifications/[id]/*` and every
  repository write find a card by id alone; the card agent learns the project from
  `GET /api/qualifications/{id}/extracted`; no sidecar opens a database. Migrations 20260921233000,
  20260923210000 and 20260924120000 reference `core.*` and cannot replay in a project database.
  The forms work (two migrations, FormRepository, FormService, pages under `/p/[project]/forms`) is
  uncommitted in `~/aisc-install/apps/qualification`, applied live, and NOT on this branch.
- **Control objectives** (`apps/control-objectives`): one SQLAlchemy engine on `platform`;
  membership by direct SQL on `core.project_member` (`access.py`); `repository.py` reads `core.system`
  numbers; alembic revisions 3, 5, 6 reference `core.*`; the card is fetched over HTTP from qualification
  (`/p/{project}/api/system-versions/{pid}/ontology.jsonld`); the JSON API `/api/projects/{id}` is
  addressed by assessment id only; the risk mapper resolves its LLM with the assessment's pid.
- **Controls** (`apps/controls`): already per project database (`src/lib/projectDb.ts`, LRU of 20
  clients, `connection_limit=2`, `scripts/migrate-projects.mjs`). Reads the latest version over HTTP from
  the platform. `submission_answer.system_version_pid` has no foreign key.
- **Engine** (`apps/backend`, `apps/eval`, `apps/webapp`): one Django alias `default` on `platform`,
  `search_path=engine,core`; raw SQL on `core.project` (`platform_projects.py`), `core.project_member`
  (`auth/membership.py`), `core.system` (`system_version_repository.py`, used by the pre_save stamp
  `signals/system_stamp.py`). No auth, session or admin tables (migration 0024 dropped them). URLs carry
  the engine's own project pid or only a child id. The worker has no database access; it calls
  `/api/v1/internal/*` with `X-Internal-Secret`; tasks carry only the evaluation pid. Object storage:
  three shared buckets, flat uuid keys.
- **Report composer** (`apps/report-composer`, a plain folder of the top-level repo): one DSN on
  `platform` as `report_composer_rw`, its own runner (`migrate.py`, lock 8_190_233_707,
  `report_composer.schema_migration`); membership and project by direct SQL on `core.project`,
  `core.project_member`; reads `core.system`. Migration 0005 adds `report_composer.preset`, a
  platform-wide table with `source_project_id` FK core.project.
- **Report renderer** (`~/aisc-report-generator`, branch `dev`, NOT a submodule and without an isolation
  worktree): `report_ro` on `platform` for `core.*`, `qualification.*`, `control_objectives.*`,
  `engine.*`; on `project_<hex>` (template `REPORT_PROJECT_DB_URL`) for `controls.*`; on `superset` for
  charts and comments. The deployed renderer image is older than `dev` HEAD.
- **Results dashboard** (`apps/results-dashboard`): bridge `/api/v1/aisc_project/{pid}` (token
  `X-AISC-Bridge-Token`); membership read at sign-in by `sso.py` over `AISC_RESULTS_DB_URI`
  (`SELECT project_id FROM core.project_member`); `results_db.py` registers `AISC Results`.
- **Grants and readers**: `init/platform-db.sql` (fresh volume only) creates the module schemas,
  `core.system`, roles, `dashboard_ro` default privileges and search_path; `init/project-databases.sql`
  (every start, superuser) hands `core.system` to platform_rw and adds the composite keys;
  `init/report-roles.sql`, `init/report-ro-grants.sql` + `scripts/report-grants.sh` grant `report_ro`;
  `init/inspector-role.sql` gives `inspector_ro` `pg_read_all_data`; template 0004 lets it connect.
- **Scripts**: `verify-one-database.sh`, `verify-db-access.sh`, `db_consistency/checks.py`
  (C3, C4, C6 silently skip once the shared tables go; C4 `_answers` breaks), `guard-frozen.sh`
  (G1/G2 dump schemas of `platform`), `test-pipeline-chain.sh` and `pipeline_chain/*`,
  `scripts/lib/throwaway-pg.sh` all assume the shared layout.

### 0.3 Every cross-module and cross-database reference

| From | To | Kind today | After isolation |
|---|---|---|---|
| qualification.qualification (project_id, system_id) | core.project, core.system | FK, FK, composite FK | `system_id` FK `project.system(pid)` in the same DB; `project_id` column dropped |
| control_objectives.project (project_id, system_id) | core.project, core.system | FK, FK, composite FK | `system_id` FK `project.system(pid)`; `project_id` dropped |
| report_composer.layout, template, generated_report | core.project, core.system | FK, composite FK | `system_id` FK `project.system(pid)`; `project_id` dropped |
| report_composer.preset.source_project_id (0005, not live) | core.project | FK SET NULL | stays in `platform` (library, D4); plain uuid, no FK |
| engine.project.project_id | core.project | FK SET NULL | column kept (definitions frozen), no FK (cannot cross databases) |
| engine.evaluation.system_id | core.system | FK SET NULL | FK `project.system(pid)` ON DELETE SET NULL |
| controls.submission_answer.system_version_pid | core.system (by value) | none | FK `project.system(pid)` (I6.2) |
| qualification.card_component.component_pid | engine.ai_component.pid | soft, by value | soft, same database now; checked by consistency (I16.6) |
| qualification.qualification.form_version_id | qualification.form_version | FK RESTRICT | FK to the project's own copy of that version (D3) |
| control_objectives.graph (card JSON-LD copy, digest) | qualification knowledge graph | copy over HTTP | unchanged, same project |
| Card-version stamps: engine evaluation (pre_save), controls answer, CO assessment, composer layout/report | core.system | read at write time | read from `project.system` of the same database |
| LLM keys (`llm.*`) and per-system tokens | project database / env | already per project | unchanged (I18) |
| API-auth service tokens (per caller edge) | env | per edge | unchanged (I18) |
| Superset `aisc_comment`, `aisc_review_request`, dashboards, roles | dashboards by id / slug | no FK | unchanged, stay in `superset` (roadmap) |
| Diagrams gate, schema-docs | `platform` + `project_<hex>` by regex | allowlist | unchanged regex, new labels (I11) |
| Every module | core.project, core.project_member | SELECT (membership) | unchanged: the only shared reads a module keeps (I1.4) |

### 0.4 What changed since plans 2 to 5 were written, and what in them is now wrong or missing

- **Card versions** (pipeline 2026-09-23, platform 0003/0004): `core.system` is no longer "systems of a
  project" but one row per saved AI card version, numbered per project, only the latest may change,
  unique on `(pid, project_id)`. Plan 2's `project.system` shape (`UNIQUE(name, version)`,
  `system_identity_idx`, "a project may name several systems") is wrong; plan 3's "an assessment copies
  system_name and reads no system" is wrong (the assessment now has `system_id`, unique, and reads
  numbers); plan 4's gate 1 and `0004_engine.sql` naming are stale; the versioned-description spec's
  `project.system` (1 row) plus `project.system_version` was NOT what got built.
- **Constraint migrations** (2026-09-24): composite keys `(system_id, project_id)` in qualification,
  control_objectives, report_composer, repaired by `init/project-databases.sql` under lock 8190233523.
  None of the plans knows them; all become single-column keys inside the project database.
- **Template numbering**: 0002..0005 are now dashboard, report, inspector, llm. Every plan's file numbers
  (0002_system, 0003_qualification, 0003_control_objectives, 0004_engine, 0005_dashboard) collide. New
  files start at 0006 (I2.1).
- **Report composer** (2026-09-23/24) did not exist when the plans were written: its schema, roles,
  `report_ro` grants and the renderer's cross-module reads are all missing from the plans. Report v2
  (migration 0005, presets, renderer changes) is committed but not deployed.
- **Forms** (2026-09-25, uncommitted): four new tables with no project and a product-owner decision
  "forms are never project-scoped: one install-wide library" (form-assembly 06-spec-addendum, R47).
- **LLM keys** (2026-09-24): template 0005, `llm_store.connect(pid)`; agents resolve per pid. Plans do not
  mention it; it is already the per-project pattern and must survive.
- **API auth** (2026-09-25): control-objectives deny-by-default gate using Starlette's route path, the
  JSON API decided by the object's own project, qualification writes checked against the card's own
  project, the card agent's own token on `/extracted`, per-caller sidecar tokens, pgAdmin and
  schema-docs on the `inspector` network. Plans 2 and 3 predate it: plan 3's "no JSON API outside
  `/p/`" and plan 2's download moves must now keep every one of these checks (I18).
- **Engine** (backend 0022..0024): auth, session and admin tables are gone; plan 4's "Django users and
  sessions per project database" has nothing left to move. Plan 4's frozen-files gate still applies.
- **Dashboard**: part of plan 5 is built differently (the bridge is `POST/DELETE
  /api/v1/aisc_project/{pid}` with `X-AISC-Bridge-Token`, a per-project controls connection,
  role `AiscProject_<hex>`, dashboard `aisc-<hex>`); the engine dataset still reads `platform`, and the
  `AISC Results` connection still exists.

---

## 1. Target placement

- **I1.1** Every table of the modules qualification, control_objectives, engine, report_composer and
  controls, and the card-version table, lives in `project_<hex>` of its project, one schema per module:

  | project database schema | tables | owner of tables | made by |
  |---|---|---|---|
  | `provision` | template_migration | platform_rw | platform template runner |
  | `project` | system (card versions) | platform_rw | template `0006_project_system.sql` |
  | `llm` | provider, system_choice | platform_rw | template 0005 (unchanged) |
  | `controls` | as today | controls_rw | controls' Prisma migrations (unchanged) |
  | `qualification` | qualification, qualification_answer, qualification_risk, knowledge_graph, card_component, form, form_version, form_question, form_version_question, `_prisma_migrations` | qualification_rw | qualification's own Prisma migrations, replayed per database |
  | `control_objectives` | project (the assessment, name unchanged), graph, risk, mapped_objective, mapping_run, alembic_version | control_objectives_rw | its own alembic baseline, replayed per database |
  | `engine` | every table of today's `engine` schema, same names, columns, types, indexes | engine_rw | Django migrations 0001..0025 replayed per database |
  | `report_composer` | layout, layout_block, template, generated_report, schema_migration | report_composer_rw | the composer's own runner, `migrations/project/` |
- **I1.2** The schema that owns a module's tables is created by the platform template (owned by
  platform_rw, `USAGE, CREATE` to the module role), exactly as `0001_controls.sql` does; the tables are
  created only by the module's own migrations.
- **I1.3** What stays in `platform` after the drop step (stage 7), and nothing else:
  `core.project`, `core.project_member`, `core.schema_migration` (roadmap); `catalogue.*` (roadmap);
  `form_library.*` (D3) and `report_library.*` (D4), the two install-wide libraries that hold no project
  data; `public` empty. The `superset` and `keycloak` databases stay as they are.
- **I1.4** After cutover, a module role's only privileges in `platform` are `CONNECT`, `USAGE` on `core`
  and `SELECT` on `core.project` and `core.project_member`, plus: `qualification_rw` owns
  `form_library`; `report_composer_rw` owns `report_library`; `catalogue_rw` owns `catalogue`;
  `platform_rw` as today on `core`. `dashboard_ro` keeps only `CONNECT` and `SELECT core.project_member`;
  `report_ro` keeps only `CONNECT`, `USAGE core`, `SELECT core.project`. Proven by `has_*_privilege`
  checks in `verify-project-databases.sh` (I16.1).
- **I1.5** Card versions: `core.system` becomes `project.system` in each project database (D1), with
  columns `pid uuid PK DEFAULT gen_random_uuid(), number integer NOT NULL CHECK (number > 0) UNIQUE,
  name text NOT NULL, version text, provider text, description text, created_at timestamptz NOT NULL
  DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), created_by text`, i.e. `core.system`
  minus `project_id`, plus a trigger `project.system_only_latest_changes` that refuses an UPDATE changing
  `number` or touching a row whose number is below `max(number)`.
- **I1.6** Every foreign key that pointed at `core.system` is recreated inside the project database on
  `project.system(pid)` with the same ON DELETE rule: qualification CASCADE, control_objectives CASCADE,
  report_composer layout and generated_report NO ACTION, engine evaluation SET NULL. Foreign keys to
  `core.project` are dropped with their `project_id` columns (engine keeps the column, I7.9).
- **I1.7** `project_id` columns that named the platform project are dropped from
  `qualification.qualification`, `control_objectives.project`, `report_composer.layout`,
  `report_composer.template`, `report_composer.generated_report` (roadmap: "rows carry no project_id";
  plan 1 precedent). No other column is renamed or dropped (D6).
- **I1.8** Names are one rule everywhere: database `project_` + lowercase pid without hyphens; anything
  that becomes part of a database name first matches
  `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` case-insensitively, and the example
  pid `3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b` maps to `project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b` in every
  language's tests.

## 2. Platform, template, roles, create and delete

- **I2.1** New template files, applied by the existing runner and tracked in
  `provision.template_migration`, idempotent (`IF NOT EXISTS`, DO blocks that skip a missing role):
  - `0006_project_system.sql`: schema `project` and `project.system` (I1.5), owned by platform_rw;
    `GRANT USAGE ON SCHEMA project` and `SELECT, REFERENCES ON project.system` to qualification_rw,
    control_objectives_rw, controls_rw, engine_rw, report_composer_rw; `SELECT` to report_ro and
    dashboard_ro. No role but platform_rw may INSERT, UPDATE or DELETE it.
  - `0007_qualification.sql`, `0008_control_objectives.sql`, `0009_engine.sql`,
    `0010_report_composer.sql`: `GRANT CONNECT ON DATABASE` to the module role, `CREATE SCHEMA IF NOT
    EXISTS <module>`, `GRANT USAGE, CREATE` to the module role, schema comment; `GRANT USAGE ON SCHEMA
    <module>` to report_ro and dashboard_ro (SELECT on tables comes from the module, I2.6).
  - `ALTER ROLE <module role> IN DATABASE <this db> SET search_path = <module>` in each file, so an
    unqualified name never resolves to another schema.
- **I2.2** `platform_service.db` card-version functions (`create_version`, `list_versions`,
  `latest_version`, `get_system`) read and write `project.system` of the project's database through a
  project connection as platform_rw (like `llm_store.connect`). Numbering uses
  `pg_advisory_xact_lock` inside that database, so two saves at once get n and n+1. Responses keep their
  shape; `project_id` is filled from `core.project`. `core.system` is never written again.
- **I2.3** `GET /systems/{pid}`: a non-uuid is 404; otherwise it looks only in the databases of the
  caller's projects (every project for an admin) and returns 404 when none has it (D2).
- **I2.4** Create: `POST /projects` inserts `core.project` + owner, provisions the database with every
  template file (0001..0010+), and on failure undoes both (today's `provision_or_undo`, unchanged); then
  registers the dashboard (best-effort, retried by `provision_all`). Module tables are created by each
  module on first open and by its migrate one-shot at start (plan 1 pattern, I3.6, I5.5, I7.6, I8.4).
- **I2.5** Delete: order stays dashboard unregister, `DROP DATABASE … WITH (FORCE)`, delete
  `core.project` row. Every module that holds a pool or client for a dropped database MUST evict it on the
  first connection error naming a missing database and answer 404 (not 500) for that pid.
- **I2.6** Reader grants inside a project database are issued by the owner of each table as part of its
  module's migration path (precedent: controls `20260923210100_dashboard_reads_controls`), never by a
  default privilege that would also cover secrets. The reader list (one list, for report_ro and
  dashboard_ro, and it is exhaustive):

  | schema | SELECT for report_ro and dashboard_ro |
  |---|---|
  | project | system |
  | controls | checklist, checklist_question, source, submission, submission_answer |
  | qualification | qualification, qualification_answer, qualification_risk, knowledge_graph, card_component, form, form_version, form_question, form_version_question |
  | control_objectives | project, graph, risk, mapped_objective, mapping_run |
  | engine | project, ai_system, ai_component, evaluation, evaluation_plugin, evaluation_input, plugin, observation, measurement, metric, direct, derived, metric_category, metric_category_metrics, artifact; `plugin_config (id, plugin_id)` columns only |
  | report_composer, llm, provision | none |

  `engine.project_config`, `engine.plugin_config.config`, `engine.plugin_config_project_config`,
  `llm.*` and all bookkeeping tables MUST NOT be readable by either reader.
- **I2.7** `scripts/report-grants.sh` becomes the superuser repair one-shot for the same list in every
  `project_<hex>` database (idempotent, skips missing tables) and drops its `platform` section for the
  moved schemas.
- **I2.8** `init/project-databases.sql` must keep running on every start after the drop step: its
  `core.system` owner line and composite-key block run only when `to_regclass('core.system')` is not
  NULL. `init/platform-db.sql` (fresh volume) no longer creates `core.system`, the module schemas
  `qualification`, `control_objectives`, `engine`, their grants, the module search_paths, or dashboard_ro's
  default privileges; it creates `form_library` (owner qualification_rw) and `report_library` (owner
  report_composer_rw) schemas. A fresh volume brought up from these files plus the migrations produces a
  working stack (throwaway test, I16.4).
- **I2.9** `provision_all` keeps provisioning every project at the first query after start; a template
  file added later reaches existing databases (already true; test for 0006..0010 on a database that had
  0001..0005).

## 3. Qualification

- **I3.1** `src/lib/projectDb.ts` (the controls module is the model): `projectDatabaseName`,
  `projectDatabaseUrl` (env `PROJECT_DATABASE_URL` with `{database}`, `schema=qualification`,
  `connection_limit=2`), `prismaFor` (one client per database, LRU of at most 20, migrate once on first
  use, concurrent first requests share one migration, a failed migration is forgotten), and
  **`projectDbFor(pid, { write })`, the only way into a project database**: it validates the pid, asks
  the platform `GET /authz/projects/{pid}` with the caller's token (stranger 404, viewer write 403,
  platform silent 503) and only then opens the database. `new PrismaClient` and `prismaFor` appear in
  `src/` only inside `projectDb.ts` (source scan test). `src/lib/prisma.ts` is deleted.
- **I3.2** The middleware answers 404 for `/p/{x}` when x is not a pid, before calling the platform.
- **I3.3** Every route that today finds a card by id alone moves under the project:
  `/p/{pid}/api/qualifications/{id}/{ai-card.json,ai-card.pdf,system-card.pdf,ontology.jsonld,ontology.ttl,fill,extracted}`.
  The old `/api/qualifications/*` paths answer 404. A card id opened under another pid is 404 (it is not
  in that database). Every link, download and `revalidatePath` is rewritten to the new paths.
- **I3.4** The card agent: qualification-web calls `POST {AGENT_SERVICE_URL}/fill/{pid}/{qualificationId}`
  and `GET /fill/{pid}/{id}`; the agent calls `GET/PUT {APP_URL}/p/{pid}/api/qualifications/{id}/extracted`
  with its own token; the route accepts the agent token only on those two methods, looks the card up in
  that pid's database (404 when absent) and returns `projectId` = that pid; the agent resolves its LLM
  with that returned project. So the project the agent uses is still the project whose database holds
  the card, never one its caller chose (e9d0693 survives, I18.4).
- **I3.5** The migration history for project databases: one baseline
  `prisma/migrations/20260926000000_project_database` equal to the final state of the pre-forms history
  minus `project_id`, with `qualification_system_id_fkey` → `project.system(pid)` ON DELETE CASCADE,
  `qualification.card_is_latest(uuid)` reading `project.system` (max(number) over the table), the three
  only-latest triggers, the reader grants of I2.6; then the two forms migrations copied byte-for-byte
  (`20260925090000_forms_are_data`, `20260925120000_the_default_form_is_fixed`) and any later one. The
  old dirs are deleted from the branch. `grep -c 'core\.\|project_id'` on the baseline is 0.
- **I3.6** `scripts/migrate-projects.mjs` migrates every `^project_[0-9a-f]{32}$` database
  qualification_rw may connect to, skips the others, and exits 2 on a permanent error;
  `qualification-migrate` runs it and depends on `platform`. `seed_mcas.mjs` writes through the project
  database of the project it is given.
- **I3.7** The schema a project database gets from I3.5 is equivalent to today's live
  `platform.qualification` schema minus `project_id`, its index and its foreign keys to `core`, and with
  the FK to `project.system`: same tables, columns, types, defaults, NOT NULL, checks, unique indexes,
  triggers and function bodies up to the `core.system` → `project.system` change. Proven by a catalog
  diff test against a schema dump of the live shape (fixture from the rehearsal copy, never the live
  database).
- **I3.8** Env: qualification-web and qualification-migrate get `PROJECT_DATABASE_URL`; `DATABASE_URL` on
  `platform` remains only for the form library (I4.2) as `FORM_LIBRARY_DATABASE_URL`.

## 4. The form library (install-wide) and forms inside a project

- **I4.1** Decision D3: the library of forms (what the chooser, the library page, the builder, import
  and export list) stays install-wide, in schema `form_library` of `platform`, owned by
  qualification_rw, with the same four tables, constraints, triggers and seed as the forms migrations.
  It holds no card and no answer.
- **I4.2** A second Prisma schema `prisma/library/schema.prisma` (the four form models, generated to its
  own client) and migrations `prisma/library/migrations/` create `form_library`; `qualification-migrate`
  applies them to `platform` before the project databases.
- **I4.3** Copy on use: when a card is saved with a form version, that version (its `form`, the
  `form_version`, its `form_version_question` rows, every `form_question` they name and, recursively,
  each `copied_from_id` question and its owner form) is copied from the library into the project's
  `qualification.form*` tables in the same transaction as the card, unless already present with equal
  content (form versions are append-only, so equal id means equal content; a differing row aborts the
  save with 500 and a log line). The card's `form_version_id` FK then points at the project's copy.
- **I4.4** Reading a card's form (answered form, coverage, AI card export, PDF) reads the project's copy
  only. The library is read only by the chooser, library, builder, import and export.
- **I4.5** R47 of the forms addendum still holds: a form saved while working in project A is listed in
  project B's chooser.
- **I4.6** Gate: WP Q2 (section 21) starts only after the forms work is committed on
  `feat/unified-modules` of `apps/qualification` and merged into `isolation/2026-09-25`. Until then no
  isolation commit edits a forms file.

## 5. Control objectives

- **I5.1** Two kinds of connection: one SQLAlchemy engine on `platform` (pool 2) used only for
  `core.project` and `core.project_member` (the existing `access.py` SQL, unchanged in meaning), and one
  engine per project database (`pool_size=2, max_overflow=0`, LRU of 20), opened only through
  `ProjectDatabases.open(pid, caller, write)`, which decides membership first (same rules as today's
  `decide()`, admin as owner) and refuses before connecting.
- **I5.2** Routes: pages stay `/p/{project}/…`; the JSON API moves to `/p/{pid}/api/projects[/{id}[/map|/severity]]`.
  The old `/api/projects*` routes answer 404. The public catalogue routes stay public. `{project}` that is
  a slug is resolved to its pid through `core.project` before any database name is built.
- **I5.3** `repository.py` version numbers read `project.system` of the same database; the assessment
  table keeps its name (`control_objectives.project`) and loses its `project_id` column (D6).
- **I5.4** Alembic: the old chain is replaced by one baseline revision
  `20260926000000_project_database` equal to today's final shape minus `project_id` and with
  `system_id` FK `project.system(pid)` CASCADE, unique, plus the reader grants (I2.6). `alembic/env.py`
  sets `search_path` to `control_objectives` only. `grep core\.` in `alembic/versions` is 0.
- **I5.5** `python -m aisc_control_objectives.migrate_projects` (the `control-objectives-migrate`
  command) upgrades every project database the role may enter, skips the rest, exits 2 on a permanent
  error; the app also migrates a database the first time it opens it (one migration for concurrent
  first requests).
- **I5.6** The risk mapper resolves its LLM with the pid of the database it is working in.
- **I5.7** Tests: the fixture that drops and recreates `CONTROL_OBJECTIVES_TEST_DATABASE_URL` must refuse
  to run when that URL's database is `platform`, `postgres` or matches `^project_`.

## 6. Controls

- **I6.1** No routing change. Its `connection_limit=2`, LRU and access door stay.
- **I6.2** A new migration adds `submission_answer_system_version_pid_fkey` →
  `project.system(pid)` ON DELETE NO ACTION (answers are never lost by a version delete; versions are
  never deleted). The migration refuses with a clear message when an answer names a pid absent from
  `project.system` (the data move runs before it in the cutover order, I13).

## 7. Engine (backend, worker, SPA)

- **I7.1** Settings: alias `default` is Django's dummy backend (a query outside an admitted request
  fails); alias `platform` is a raw-SQL-only connection to `platform` as engine_rw
  (`search_path=core`), used only by membership (`auth/membership.py`) and the project-name lookup
  (`platform_projects.py`); one alias per project database, registered on first use by copying the
  template settings with `NAME=project_<hex>` and `OPTIONS -c search_path=engine`, `CONN_MAX_AGE=0`.
  The router (`aisc_backend/projectdb.py`) sends every ORM read, write and migrate to the alias admitted
  for the current request, read from a `ContextVar` (works under uvicorn and `sync_to_async`), forbids
  relations across aliases and never routes a model to `platform` or `default`.
- **I7.2** The door (async middleware): every `/api/*` call except the unauthenticated and project-less
  ones listed in plan 4 (docs, openapi, app-name, me, me/admin, audit, `GET /plugins`) carries
  `X-AISC-Project: <platform pid>`. Order: no header 400; not a pid 404; no token 401; platform
  membership read fails 503; stranger 404; viewer on a write 403 (writes are non GET/HEAD/OPTIONS except
  plan 4's `READ_POSTS`); a pid with no `core.project` row 404; only then the alias is opened. Every
  pid in a path or body that names an engine project must be the engine project of that database, else
  404. The membership check and the database open are in the same code path (plan 1 lesson).
- **I7.3** The worker: backend dispatch sends `run_evaluation(platform_pid, evaluation_pid, ticket)`,
  where ticket = HMAC-SHA256 over `platform_pid + "." + evaluation_pid` with `DJANGO_SECRET_KEY`, minted
  when an editor starts the run. Every worker call to `/api/v1/internal/*` sends `X-Internal-Secret`,
  `X-AISC-Project` and `X-AISC-Run`; the door accepts an internal call only when the secret is right
  (401) and the ticket matches that project and evaluation (403). Tasks never carry a DSN.
- **I7.4** The SPA sets `X-AISC-Project` from its current platform project on every API call; the
  plugin install dialog and every call builder send it; with no current project the SPA does not call a
  project route.
- **I7.5** Plugin install records `engine.plugin` in the database of the header's project; the body's
  `project_uuid` must equal that database's engine project pid, else 404. Plugin code and devpi stay
  global.
- **I7.6** `python manage.py migrate_projects` migrates every project database engine_rw may enter,
  then issues the reader grants of I2.6 as engine_rw (not a Django migration, so the schema history
  stays as it is), under a Postgres advisory lock per database; the app does the same the first time an
  alias is opened in a process (per-alias lock, one migration for concurrent first requests).
  `aisc-backend` no longer runs `manage.py migrate` on `platform`; a one-shot `aisc-backend-migrate`
  runs `migrate_projects`.
- **I7.7** New migration `0025_the_database_is_the_project` (RunPython, Postgres only): adds
  `aisc_backend_evaluation_system_id_fkey` → `project.system(pid)` ON DELETE SET NULL when
  `to_regclass('project.system')` is not NULL and the key is absent. On sqlite a no-op. Migrations 0015,
  0022, 0023 stay unchanged (their `core` blocks are already guarded by `to_regclass`).
- **I7.8** The stamp: `system_version_repository.LATEST` becomes `SELECT pid FROM project.system ORDER BY
  number DESC LIMIT 1` on the admitted alias; `signals/system_stamp.py` keeps stamping new evaluations
  only.
- **I7.9** Table definitions do not change: every column, type, index and non-core constraint of every
  `engine` table is the same as today (the only differences: the FK from `project.project_id` to
  `core.project` is absent, and `evaluation.system_id` points at `project.system`). Proven by a catalog
  diff between a project database migrated by I7.6 and the live `platform.engine` shape (fixture).
- **I7.10** What was global becomes per project: `metric`, `metric_category` and their links are rows
  of the project database, created by name inside it (unchanged code, different database). There are no
  users or sessions to move (0024 dropped them); identity stays the Keycloak token on every request.
- **I7.11** Object storage stays in the three shared buckets (D8); an object is reachable only through a
  row of the project's database.
- **I7.12** Frozen-file guards: `tests/test_frozen_sean_files.py`, `scripts/guard-frozen.sh` G1/G4/G5
  and `tests/test_one_system_per_project.py` (leaf is `0024`) pin behaviour this design changes. Each is
  changed only as far as this design requires (leaf becomes `0025`; G1 compares the engine table
  definitions of I7.9 in a project database instead of `platform.engine`; the settings/urls/routers
  files that must change are listed by name in 03-coding-plan), and each change is named in the WP
  notes.

## 8. Report composer

- **I8.1** Connections: `REPORT_COMPOSER_PROJECT_DATABASE_URL` (template `{database}`, report_composer_rw)
  for everything of a project; `REPORT_COMPOSER_DATABASE_URL` on `platform` only for `core.project`,
  `core.project_member` (the existing access SQL) and `report_library.preset`. A project database is
  opened only after `guards.guard` has decided membership for that pid.
- **I8.2** Migrations split: `migrations/project/` (a baseline `0001_project_database.sql` equal to
  today's 0001..0005 final shape of layout, layout_block, template, generated_report minus `project_id`,
  with `system_id` FKs to `project.system(pid)` NO ACTION) and `migrations/library/`
  (`0001_presets.sql`: `report_library.preset`, `source_project_id uuid NULL` without FK). Tracking tables
  `report_composer.schema_migration` (per project) and `report_library.schema_migration` (platform).
- **I8.3** Every query drops its `project_id` filter only where the column is gone; every `system_id`
  still names a row of `project.system` of the same database (422 `system_not_in_project` when not).
- **I8.4** The composer migrates the library at start and every project database at start (loop) and on
  first open (lock 8_190_233_707 in each database).
- **I8.5** It still never reads another module's schema (R7.3.3); the renderer does.
- **I8.6** The coverage-map data step of 0005 has run on every layout before its rows are copied
  (cutover step C4, I13).

## 9. Report renderer (`~/aisc-report-generator`)

- **I9.1** Workspace: stage 4 creates a git worktree `~/aisc-isolation-report-generator` of
  `~/aisc-report-generator` on branch `isolation/2026-09-25` from `dev`, and isolation builds set
  `REPORT_GENERATOR_DIR` to it (D9). The original checkout is never edited.
- **I9.2** `data/platform.py` reads only `core.project` (and `pg_database` existence) from
  `REPORT_PLATFORM_DATABASE_URL`; `pinned_system`, `newer_versions`, `older_versions` read
  `project.system` of the project database. `data/qualification.py`, `data/control_objectives.py`,
  `data/engine.py` connect to the project database (template `REPORT_PROJECT_DB_URL`, report_ro) and
  keep their `system_id` scope; `project_id` filters are replaced by the database itself; every
  `JOIN core.system` becomes `JOIN project.system`.
- **I9.3** `NotInProject` (404) when `system_id` is not in `project.system` of that project's database;
  a missing project database gives `status=empty` for every data block (as R6.4 does for controls);
  a missing module schema or table in an existing database gives `empty`, never `error`.
- **I9.4** Every data function still takes `(project_id, system_id)` first and cannot read without a
  project (R6.2).

## 10. Dashboard (results-dashboard, Superset)

- **I10.1** One Superset connection per project, to `project_<hex>` as dashboard_ro (the existing one,
  name unchanged); the bridge's `register_project` puts `engine_results_<hex>` on that connection with
  SQL that joins `engine.*` and `project.system` and has no pid filter. `unregister_project` unchanged.
  Re-registering a project whose dataset sits on `AISC Results` moves it (the upsert changes the
  dataset's database) and keeps its id, so charts keep working.
- **I10.2** `results_db.py` stops registering `AISC Results`; `sso.py` reads memberships over a plain
  DSN `AISC_MEMBERSHIP_DB_URI` (dashboard_ro on `platform`, SELECT `core.project_member` only), which is
  never a Superset connection, so SQL Lab cannot reach `platform`. The `AISC Results` row is deleted by
  the cutover (step C9) only after a query shows no dataset on it.
- **I10.3** dashboard_ro: in project databases the reader list of I2.6; in `platform` only I1.4.
- **I10.4** Superset opens analytics connections without a persistent pool (NullPool, Superset's
  default for query engines) or with at most 2; checked by a test on the config.
- **I10.5** Bridge ordering on create (after provision) and delete (before drop) unchanged; a
  registration retried after start (T5) unchanged.

## 11. Inspector and the diagrams gate

- **I11.1** `inspector_ro` connects to every project database (template 0004, unchanged) and reads every
  schema of it through `pg_read_all_data`; it writes nothing (read-only sessions). Test: it can
  `SELECT` one row from each new schema in a throwaway project database and cannot `INSERT`.
- **I11.2** The diagrams gate (`/authz/schema`) and schema-docs keep the regex
  `^(platform|project_[0-9a-f]{32})$`; a member sees their project database's diagrams, a stranger is
  refused, an admin may refresh (existing tests stay green).
- **I11.3** schema-docs labels: `PROJECT_SCHEMAS` gains `project`, `qualification`,
  `control_objectives`, `engine`, `report_composer`; `PLATFORM_SCHEMAS` becomes `core` ("Projects and
  their members"), `catalogue`, `form_library`, `report_library`.
- **I11.4** pgAdmin needs no change (one server, maintenance DB `platform`, every database listed).

---

## 12. The live data move: `python -m platform_service.isolate`

Form (D5): a module of the platform service, because it already owns the database name rule, the
template runner and psycopg; it runs in a one-shot container from the platform image
(`docker compose run --rm platform python -m platform_service.isolate …`), connecting as the Postgres
superuser through `ISOLATE_SUPERUSER_URL` (built from `POSTGRES_USER`/`POSTGRES_PASSWORD` inside the
container environment, never echoed). Subcommands: `plan`, `provision`, `copy`, `verify`,
`verify-dump`, `report`. Every subcommand takes `--project <pid>` (repeatable) or `--all`.

### 12.1 Classification (catalog-driven)

- **I12.1** Source tables are every table of the schemas `core` (only `system`), `qualification`,
  `control_objectives`, `engine`, `report_composer` in `platform`, read from `pg_class`/`pg_attribute`
  at run time, not from a list in code. Two small constant sets are allowed and are the whole
  hand-written knowledge: `STAYS_SHARED` = {core.project, core.project_member, core.schema_migration,
  catalogue.*} and `BOOKKEEPING` = {qualification._prisma_migrations, control_objectives.alembic_version,
  engine.django_migrations, engine.django_content_type, report_composer.schema_migration} (recreated by
  the module migrations, never copied). A table in neither set and in no rule below is reported and
  makes `copy` refuse (`unclassified table`).
- **I12.2** Target of a source table: `core.system` → `project.system`; every other table → the same
  schema.table in `project_<hex>`; `qualification.form*` also → `form_library.form*` in `platform`
  (every row, library copy, I12.9).
- **I12.3** Ownership, computed per project P from `pg_constraint` foreign keys, to a fixpoint:
  - root rows: rows of a table with a FK column referencing `core.project(pid)` whose value is P
    (core.system, qualification.qualification, control_objectives.project, engine.project,
    report_composer.layout, template, generated_report today, found by the catalog);
  - owned: a row with a FK to an owned row;
  - needed: a row (not in `STAYS_SHARED`) referenced by a FK of an owned or needed row, or a row whose
    FK columns are part of its own primary key and reference a copied row (identifying children:
    `form_version_question`, `engine.direct`, `engine.derived`);
  - copied(P) = owned ∪ needed.
- **I12.4** Conflicts abort the whole run before any write: a row owned by two projects; a copied row of
  P whose FK names a row owned by another project (a cross-project reference, e.g. an evaluation of P
  stamped with a card version of Q); a root row whose project value is not in `core.project`.
- **I12.5** Rows of a source table that are in no project's copied set and not in the library target are
  **unowned**: listed in the report (table, primary key, reason) and never moved. Rows owned by a
  `core.project` row whose database is missing are reported and not moved.

### 12.2 Copy

- **I12.6** Preconditions checked by `plan` and again by `copy`, each failing with a named reason:
  - the source schemas are at the old-layout heads of this branch's pre-isolation histories
    (qualification `_prisma_migrations` contains every pre-isolation migration name including both forms
    migrations, none rolled back or unfinished; `control_objectives.alembic_version` = `7c3e5a9b1d24`;
    engine `django_migrations` contains `0024_no_login_of_its_own`; `report_composer.schema_migration`
    contains 0001..0005; `core.schema_migration` contains 0001..0004);
  - every target database exists, has every template file, and every module schema is at its new head
    (qualification baseline + forms, alembic baseline, Django 0025, composer project 0001, controls head);
  - no session of a module role or of platform_rw is connected to `platform` or to a target database
    (`pg_stat_activity`), except the tool itself;
  - for every mapped table, the target columns cover the source columns except the allowed dropped ones
    (`project_id` of the five tables of I1.7 and of `core.system`), and each shared column has the same
    type; every target-only column has a default.
- **I12.7** Per project, one transaction on the target database: `SET LOCAL session_replication_role =
  replica` (user triggers and FK triggers off for the insert only), `TimeZone=UTC`, `DateStyle=ISO`,
  `extra_float_digits=3`, `bytea_output=hex` on both sides; rows are read from the source in a
  `REPEATABLE READ READ ONLY` transaction (one snapshot for the whole project) and inserted with the
  same primary keys and every value of the shared columns; then every FK of every target table is
  validated by an anti-join query generated from the catalog (any orphan aborts); sequences are set to
  `max(source last_value, max(target column))` with the source's `is_called`; the per-table checks
  (I12.10) run; only then COMMIT. Any failure rolls back that project and leaves its database as it was.
- **I12.8** Idempotent and resumable: a project whose every target table already equals its copied set
  (I12.10) is reported `already done` and skipped with no write; a project with some target rows that
  differ from the source, or with target rows that are neither copied rows nor identical to a source
  row of the same key (the migration seed, e.g. the Annex IV default form, is allowed only when equal
  to the source row), aborts that project with `target not empty and not equal`. Projects run one at a
  time in pid order; a run stopped midway resumes by running again.
- **I12.9** The library copy (`qualification.form*` → `form_library.form*` in `platform`) follows the
  same rules in its own transaction; its seeded default must equal the source row.
- **I12.10** Verification per table and per project: count and `md5(string_agg(row_text, E'\n' ORDER BY
  row_text))` over the shared columns in target column order, computed on the source copied set and on
  the target rows with those keys, must be equal; target extra rows are checked by I12.8. Any mismatch
  aborts.
- **I12.11** Never deletes, updates or locks-for-update anything in `platform`; the source is read in
  read-only transactions only. Test: an md5 over every source table of a throwaway `platform` taken
  before and after `copy` is identical.
- **I12.12** `--dry-run` (on `copy`) and `plan` compute and print everything (per project and table:
  source rows, rows to copy, already present, unowned, conflicts, sequence values) and write nothing
  (test: `pg_stat_database.xact_commit` of the targets unchanged, no table changed).
- **I12.13** `verify` recomputes I12.10 for every project and the library from scratch, independently of
  `copy`, and additionally proves that the union over all projects of copied rows plus unowned rows plus
  bookkeeping equals every row of every source table (nothing silently dropped).
- **I12.14** `verify-dump <dump files>` restores the stage-7 `pg_dump` of each shared schema into a
  throwaway database and runs `verify` against it instead of `platform` (row-by-row proof before the
  drop).
- **I12.15** Report: a JSON file and a human summary, per project and table, with counts, checksums,
  unowned rows by key, and the run's source snapshot time; written to the path given by `--report`;
  never contains row values, only keys and counts.
- **I12.16** The tool logs pids and counts only, never row contents or credentials, and exits non-zero on
  any refusal.

---

## 13. Cutover procedure (the orchestrator runs it live, stage 6)

Every step below is a subcommand of `scripts/isolation/cutover.sh <step>` (WP-X1) that prints what it
checks and exits non-zero on the first failed check. The same script runs the rehearsal against a
throwaway container (I15.1) with `--target rehearsal`.

| step | action | check before the next step |
|---|---|---|
| C0 | Preconditions: every WP merged, all suites green, the rehearsal (I15.1) passed on this exact commit set, forms work merged (I4.6), images built from this branch and tagged, the running images re-tagged `:pre-isolation` | `docker image inspect` of both tag sets |
| C1 | Backup: `pg_dumpall` to `~/aisc-isolation-backup/pre-cutover-<ts>.sql` (mode 600, outside any repo) and `pg_dump -Fc` of `platform`, `superset`, every `project_<hex>` | each dump restores into a throwaway container (`pg_restore --list` and a count query match) |
| C2 | Quiet: stop caddy (no user traffic), then every writer and reader: platform, qualification-web, qualification-agents, controls-web, control-objectives, aisc-backend, aisc-eval-worker, report-composer, report-renderer, dashboard; keep postgres, keycloak, redis, rabbitmq, minio | `pg_stat_activity` shows no module-role or platform_rw session; `engine.evaluation` has no `running`/`pending` row; rabbitmq queue empty |
| C3 | `isolate plan --all --report …/plan.json` | no conflict, no unclassified table, preconditions except "new heads" hold |
| C4 | Old-layout heads: apply the pending pre-isolation migrations to the shared schemas with the pre-isolation code (today: report_composer 0003, 0004, 0005 on `platform`) | `isolate plan` reports every source schema at its old head |
| C5 | `postgres-setup` with the new init files (roles, grants; guarded core lines) | exits 0 |
| C6 | `isolate provision --all` (template 0006..0010 into every project database, via `projectdb.provision`) | every project database lists 0001..0010 |
| C7 | Module migrations on every project database and the libraries: `qualification-migrate` (library then projects), `control-objectives-migrate`, `aisc-backend-migrate`, `controls-migrate`, composer migrate-only | `isolate plan` reports every target at its new head; I6.2's FK migration is held back to C8b |
| C8 | `isolate copy --all --report …/copy.json` | exit 0; every project `copied` or `already done` |
| C8b | controls FK migration (I6.2), then `report-grants` one-shot | exit 0 |
| C9 | Retire the shared schemas without dropping them: schema owners of `qualification`, `control_objectives`, `engine`, `report_composer` and table owner of `core.system` become the superuser; `REVOKE ALL` on them from every role; dashboard_ro, report_ro, module roles reduced to I1.4; delete the Superset `AISC Results` row when no dataset uses it; snapshot `pg_stat_user_tables` counters of the retired tables | `verify-project-databases.sh --privileges` passes |
| C10 | `isolate verify --all` | exit 0 |
| C11 | Start platform (provision_all re-registers dashboards), then the modules, dashboard, then caddy | every health check 200 |
| C12 | `scripts/verify-project-databases.sh` (I16) and the smoke list: open MCAS in each step as a member (qualification card shows v1 and its answers, controls library shows 4 checklists, control objectives assessment `0a013fbcc79b` with 5 risks, engine project with 2 plugins, reports list 1 layout and 4 generated reports that download, dashboard opens for a member and 404 for a non-member), save a card (v2 appears in `project.system` of MCAS only), create and delete a throwaway project (its database is made with every schema and dropped) | all pass |

- **I13.1** The steps run in this order only; each step refuses to start unless the previous step's
  check passed in this run (the script records passed steps in `…/cutover-state.json`).
- **I13.2** Every step has a named rollback (section 14) printed by `cutover.sh rollback <step>`.
- **I13.3** No step prints a credential or a row value; dumps and reports are written mode 600 to
  `~/aisc-isolation-backup/`, never into a repository.
- **I13.4** Between C2 and C11 no service that holds a module role connects (C2's check is repeated at
  C8 and C10).

## 14. Rollback at each step

- **I14.1** C0..C2: nothing changed; restart the running images.
- **I14.2** C3: read-only; nothing to undo.
- **I14.3** C4 (old-layout migrations on shared schemas): the old images tolerate the added columns and
  keys (additive migrations); if not, restore `platform` from the C1 `-Fc` dump into a new database,
  verify, and swap names with the superuser (documented commands in the script's `rollback C4`).
- **I14.4** C5..C8b: the shared schemas are unchanged; restart the `:pre-isolation` images, run the
  previous `postgres-setup`; the new schemas and rows in the project databases are left in place and are
  harmless to the old images (they read only `platform` and `controls`), and are removed by
  `cutover.sh rollback C8` which drops only the schemas created by 0006..0010 in each project database
  after confirming their `provision.template_migration` names (never `controls` or `llm`).
- **I14.5** C9: re-grant exactly what C9 revoked (the script saves the ACLs and owners it changes to
  `…/c9-acl.json` and restores them), then as I14.4.
- **I14.6** C10..C12 before users are let in (caddy is the last thing started): as I14.5.
- **I14.7** After users are let in, the point of no return: new rows exist only in project databases. A
  rollback then means restoring the old images, re-granting (I14.5), and losing the rows written since
  C11 unless they are exported by hand; the orchestrator therefore runs C12 fully before starting caddy.

## 15. Rehearsal, retire, drop

- **I15.1** Rehearsal (stage 5): `scripts/isolation/rehearse.sh` starts a throwaway `postgres:14-alpine`
  on a random port (never 5432), restores `~/aisc-isolation-rehearsal/live-*.sql` without printing it,
  runs C3..C10 and I16 against it with the isolation images (their DSNs pointed at the throwaway),
  twice (the second run must report `already done` for every project and write nothing), injects one
  failure midway through C8 in a third run from a fresh restore and proves the resume, then removes the
  container. Its output is 05-rehearsal.md.
- **I15.2** Drop (stage 7), only after the live cutover has run at least one full day without a
  rollback and the orchestrator re-runs I16: `pg_dump -Fc -n qualification -n control_objectives -n
  engine -n report_composer -t core.system platform` to the backup directory; `isolate verify-dump` on
  it passes; `pg_stat_user_tables` counters of the retired tables equal the C9 snapshot (nothing wrote
  them); then `DROP SCHEMA qualification, control_objectives, engine, report_composer CASCADE;
  DROP TABLE core.system CASCADE; DROP FUNCTION IF EXISTS core.system_only_latest_changes();`.
- **I15.3** Not dropped by this work (reported only; they need the user's decision per the database
  roadmap): databases `aisc`, `controls`, `qualification`, `control_objectives`,
  `control_objectives_test`, the three orphan project databases, `catalogue` schema, Superset's
  `aisc_*` tables.

## 16. Done: `scripts/verify-project-databases.sh`

It replaces `verify-one-database.sh` in `verify.sh`, read-only, superuser, and proves:

- **I16.1** Privileges: I1.4 in `platform` for every role; in each project database each module role has
  rights only on its own schema, `USAGE` + `SELECT, REFERENCES` on `project`, and nothing on `llm`,
  `provision` or another module's schema; readers match I2.6 exactly (no more, no less).
- **I16.2** Placement: after C9 the retired schemas are unreachable by every non-superuser role; after
  stage 7 `platform` has exactly the schemas of I1.3 and `core` exactly its three tables.
- **I16.3** Every project in `core.project` has a database with template 0001..0010 and every module
  at its head; `project.system` numbers are unique and positive, and every `system_id` of every module resolves in the same database.
- **I16.4** Configuration: every running container's DSN env (read with `docker inspect`, values never
  printed, only the database part) for qualification, control-objectives, engine, composer and renderer
  names `{database}` or `project_`, and the only `platform` DSNs are the membership/library ones of
  I3.8, I5.1, I7.1, I8.1, I9.2, I10.2. A fresh-volume throwaway bring-up (init files + migrations +
  `POST /projects`) yields a project database that passes I16.1 and I16.3.
- **I16.5** Isolation, functional: two throwaway projects A and B (made through the API); a card,
  checklist answer, assessment, evaluation row, layout made in A are absent from B's database and every
  API of B; A's ids opened under B's pid are 404 on every module.
- **I16.6** Consistency (`scripts/db_consistency`, rewritten per project database): C3 (versions
  resolve), C4 (paired stamps), C6 (graph digest vs knowledge graph), C7 (every module's migration
  tracker at head, not only controls), C8 (lint over the project schemas), plus
  `card_component.component_pid` exists in `engine.ai_component` of the same database.
- **I16.7** Connections: `(projects × per-project budget of section 17) + base` is below 80% of
  `max_connections`, else a WARN line (not a failure) naming PgBouncer.

## 17. Pools and connection limits (I17)

| service | per project database | shared |
|---|---|---|
| controls-web | 2 (Prisma `connection_limit`), LRU 20 clients | none |
| qualification-web | 2, LRU 20 | library client on `platform`, 2 |
| control-objectives | pool 2, overflow 0, LRU 20 | `platform` pool 2 |
| aisc-backend | 1 per request thread (`CONN_MAX_AGE=0`) | `platform` alias, 1 per request |
| report-composer, report-renderer | 1 per call, closed after | 1 per call |
| platform | 1 per call (`llm_store` pattern) | pool 4 |
| dashboard | NullPool (I10.4) | membership DSN, 1 per sign-in |

- **I17.1** Every per-project pool is created lazily, capped by the LRU (least recently used is closed),
  and evicted when its database is dropped (I2.5). No PgBouncer in this work (D7); `max_connections`
  stays 100.

## 18. Security that must survive (I18)

- **I18.1** Per-caller service tokens on every sidecar (`X-AISC-Service-Token` per edge,
  `scripts/secrets.sh` append-only, compose `:?`), unchanged; the agent's route change (I3.4) keeps the
  agent token valid only on GET/PUT of `extracted`.
- **I18.2** Control-objectives deny-by-default gate using `get_route_path`, the root-path bypass closed,
  object decided by its own project: under isolation "its own project" is the database the object was
  found in; every existing `test_api_auth.py` case is kept, moved to the `/p/{pid}/api` paths where the
  route moved (the test changes only its paths, named in the WP notes).
- **I18.3** Qualification writes need an editor of the card's own project (the database it is in).
- **I18.4** The card agent reads its project from the card, never from its caller (I3.4).
- **I18.5** Per-project LLM keys in `llm.*`, the internal resolve route bound to one system per token,
  Fernet rotation (`llm_store rotate` loops `core.project`), unchanged; no reader or module role gains
  access to `llm.*` (I16.1).
- **I18.6** The diagrams gate (I11.2) and the `inspector` network, unchanged.
- **I18.7** No tool, script or test prints a password, a key, a token or a row value; the rehearsal dump
  is never copied into a repository.

## 19. Consistency, verify and guard scripts (I19)

- **I19.1** `verify-one-database.sh` is retired from `verify.sh` and replaced by I16;
  `verify-db-access.sh` checks the project-database grants of I16.1 on a throwaway project instead of
  probes in `platform` module schemas.
- **I19.2** `scripts/lib/throwaway-pg.sh` gets `tpg_project_db <pid>` (create database, apply the
  template) and every harness (`guard-frozen.sh`, `test-pipeline-chain.sh`, `pipeline_chain/*`, module
  DB tests) targets project databases; `pipeline_chain/throwaway.py` N6 fix (`-tA`) is applied as part of
  that change.
- **I19.3** `test_dashboard_queries.py` runs the engine dataset SQL as dashboard_ro on a project
  database.

---

## 20. Test strategy

Every database test runs on a throwaway `postgres:14-alpine` (`aisc-t-iso-*`, random port, never 5432,
removed afterwards), recipe of `pipeline-2026-09-24-llm-keys/02-tests.md` section 3 with paths in
`~/aisc-isolation`, applying `init/{platform-db,project-databases,report-roles,inspector-role}.sql`.
`PLATFORM_TEST_DATABASE_URL`, `CONTROL_OBJECTIVES_TEST_DATABASE_URL`, `QUALIFICATION_TEST_*`, the
engine's `ENGINE_TEST_*` and the composer's and renderer's test DSNs are ALWAYS set (the platform
conftest deletes projects from the live database otherwise). Project databases in tests are made through
the platform's `projectdb.provision` (or `tpg_project_db`) so they get the real template.

| requirements | suite | how |
|---|---|---|
| I1.4..I1.8, I2.1..I2.3, I2.5, I2.9 | platform pytest (`tests/test_project_databases.py`, new `test_project_system.py`) | throwaway; grants probed per role with `_as()` |
| I2.6, I2.7, I16.1 | top-level `scripts/tests/test_project_grants.py` | throwaway; every module migrated into two project databases; `has_table_privilege` matrix against the list |
| I2.8, I16.4 fresh volume | top-level `scripts/tests/test_fresh_volume.py` | empty container, init files, migrations, one `POST /projects` through a TestClient |
| I3.1..I3.4, I3.6 | qualification vitest unit (`projectDb`, `middleware`, route moves, FillerClient) + agents pytest (paths) | fakes for platform and agent |
| I3.5, I3.7 | qualification `test/db` via `throwaway-db.sh` (rewritten to make project databases) | catalog diff against `scripts/tests/fixtures/isolation/live_shape.sql` (schema-only dump taken from the restored rehearsal copy, committed without data) |
| I4.1..I4.5 | qualification vitest + `test/db/forms*.db.test.ts` | throwaway; copy on use, equal-content no-op, differing-content abort, R47 across two project databases |
| I5.* | control-objectives pytest | throwaway; two project databases; old `/api/projects` 404; I5.7 refusal |
| I6.2 | controls vitest integration | throwaway |
| I7.1, I7.2, I7.5, I7.8, I7.10 | backend `manage.py test` on Postgres (`scripts/test-project-databases.sh`, plan 4 style) + sqlite unit | routing ContextVar, door order table, same-project body pid |
| I7.3 | eval unittest + backend door tests | ticket forgery, wrong project, wrong evaluation |
| I7.4 | webapp vitest | header on every call builder |
| I7.6, I7.7, I7.9, I7.12 | backend Postgres suite + `guard-frozen.sh` | catalog diff vs fixture |
| I8.* | report-composer pytest | throwaway; library + two project databases |
| I9.* | renderer pytest (`~/aisc-isolation-report-generator/tests`) | golden captures re-run on project-database fixtures; missing DB/table → empty |
| I10.* | results-dashboard pytest (pure + DB tests) | fake store; engine dataset moves connection and keeps id |
| I11.* | platform pytest (`/authz/schema`), schema-docs unit, `test_inspector_network.py` | throwaway |
| I12.* | platform pytest `tests/test_isolate.py` (new) | synthetic source in a throwaway `platform`: two projects, an unowned row, a cross-project stamp (conflict), a self-reference (form_question.copied_from_id, ai_component.source_dataset_id), an identifying child (engine.derived), a serial sequence, the seeded default form in target, a changed target row, an injected failure mid-copy (resume), dry-run no-write, source md5 unchanged |
| I13, I14 | `scripts/tests/test_cutover_script.py` (static: step list, every step has a check and a rollback) + the rehearsal | |
| I15.1 | stage 5 full rehearsal on the restored live copy | 05-rehearsal.md |
| I16.* | `verify-project-databases.sh` run in the rehearsal and live | |
| I17.1 | each module's unit suite (LRU cap, eviction after a drop, pool sizes read from config) | fakes and one throwaway drop |
| I19.* | top-level `scripts/tests` (harness self-tests) and the harnesses themselves | throwaway |
| I18.* | the existing security suites stay green (`test_api_auth.py`, `serviceTokens`, `agentToken`, `test_service_tokens.py`, `test_llm_keys.py`, platform `test_api_llm.py`) | only path changes, named |

Baselines: before any WP, stage 2 records each suite's pass/fail counts on this branch (the 06-report
known reds N1..N7 and F5 stay as they are unless a WP fixes them on purpose).

## 21. Work packages, in dependency order

Each is sized for one fresh agent; each ends with its suites green against the recorded baseline and
local commits only.

| WP | scope | depends on |
|---|---|---|
| P1 | Platform: template 0006..0010, reader grants helper, `db.py` card versions on `project.system`, `/systems/{pid}` scan, delete eviction contract, init files (guarded core lines, fresh volume) | none |
| P2 | `platform_service.isolate` (plan, provision, copy, verify, verify-dump, report) and `tests/test_isolate.py` | P1 (template) |
| Q1 | Qualification routing: `projectDb.ts`, middleware, route moves, agents paths, `migrate-projects.mjs`, seed, baseline migration (pre-forms squash), `card_is_latest` on `project.system`, env/compose | P1 |
| Q2 | Forms: merge the committed forms work, form library schema/client/migrations, copy on use, forms migrations after the baseline | Q1, gate I4.6 |
| O1 | Control objectives: per-project engines, `/p/{pid}/api`, baseline revision, `migrate_projects`, tests | P1 |
| C1 | Controls: FK to `project.system` migration | P1 |
| E1 | Engine backend part 1: aliases, router, `migrate_projects`, 0025, grants, stamp on `project.system`, frozen-guard updates | P1 |
| E2 | Engine part 2: the door, header, run ticket (backend), worker (apps/eval), SPA header (apps/webapp) | E1 |
| R1 | Report composer: project/library migrations, two DSNs, queries | P1 |
| R2 | Report renderer (new worktree): data modules on project databases | P1 |
| D1 | Dashboard: engine dataset on the project connection, membership DSN, no `AISC Results`, NullPool | P1 |
| V1 | Inspector labels, `db_consistency` per project, `verify-project-databases.sh`, `verify-db-access.sh`, `throwaway-pg.sh`, guard and pipeline-chain harnesses, `report-grants.sh` | P1..D1 |
| X1 | `scripts/isolation/cutover.sh` (C0..C12, rollbacks, C9 ACL save/restore), `rehearse.sh`, compose wiring review, live-shape fixture | P2, V1 |

## 22. Decisions (each with its reason)

- **D1** `core.system` becomes `project.system` (not `core.system` inside the project database):
  `core` then means only the shared platform schema, so "no module touches `core` except project and
  project_member" is checkable by name; the roadmap and plan 2 already use `project.system`. The table
  keeps today's card-version semantics (one row per saved card, number per project) rather than the
  unbuilt `project.system` + `project.system_version` pair of the versioned spec, because that is what
  every module stamps today.
- **D2** The platform stays the only writer of `project.system` through its existing endpoints: the
  qualification, controls and control-objectives clients keep their contract, and one writer keeps
  numbering in one place.
- **D3** Forms: the library stays install-wide in `platform.form_library`, and each project holds copies
  of the form versions its cards use. Reason: the product owner decided on 2026-09-25 that forms are
  never project-scoped (R47), while RULES require the forms tables in the data move and the roadmap keeps
  shared only what knows no project (like the catalogue). A library of questions knows no project; which
  version a card was answered with is project data and must be inside the project database with a real
  foreign key. Alternative, if the user prefers strict isolation over R47: per-project libraries (drop
  I4.1, I4.2, I4.5, keep I4.3 as the only storage); this is a small change of Q2 only.
- **D4** Report presets (0005, not yet live, no rows) are install-wide by their own spec ("seen by every
  signed-in user", no project data): they live in `platform.report_library.preset`, same reasoning as D3.
- **D5** The move tool is `python -m platform_service.isolate`, run as the superuser in a one-shot
  platform container: it reuses the name rule and the template runner, needs to read every schema and
  write tables owned by several roles, and must set `session_replication_role`.
- **D6** No renames beyond what isolation needs: `control_objectives.project` keeps its name (the
  `assessment` rename of the database roadmap is separate work), qualification camelCase columns stay,
  engine names stay. Only `project_id` columns that named the platform project go (roadmap, plan 1). This
  keeps the move a column-by-column copy with one allowed difference.
- **D7** No PgBouncer and no `max_connections` change now: one live project, measured budget about 11
  connections per active project; a verify WARN (I16.7) says when it is needed (about 7 active projects).
- **D8** Object storage buckets stay shared (the roadmap is about Postgres; plan 4 kept them shared);
  objects are reached only through rows of the project database.
- **D9** The renderer gets its own isolation worktree `~/aisc-isolation-report-generator`, mirroring the
  submodule rule of RULES.md; the original checkout is never edited.
- **D10** Module schemas in project databases are owned by platform_rw (template), tables by the module
  role (its migrations), as controls does; readers are granted by the table owner in its migration path,
  never by blanket default privileges, so secrets (`engine.project_config`, `llm.*`) stay unreadable.
- **D11** Membership stays where it is: qualification and controls ask `/authz`, control-objectives,
  engine and composer read `core.project_member` directly. Both are allowed shared reads; changing the
  mechanism would put the deployed API-auth work at risk for no isolation gain.
- **D12** Retire before drop: at cutover the shared schemas are made unreachable (owners to superuser,
  privileges revoked) but kept, so a rollback is a re-grant; the drop waits for stage 7 with dump and
  row-by-row verification, as RULES require.
- **D13** Old-layout heads first (C4): the tool copies between two known schema versions only; pending
  data steps (composer 0005's coverage move) run in the shape they were written for, instead of being
  re-implemented in the tool.
- **D14** The copy disables triggers only inside its own transaction (`session_replication_role =
  replica`) so append-only and only-latest triggers do not refuse historical rows, and replaces the
  disabled FK checks by explicit anti-join validation before commit.
- **D15** One transaction per project (data is small: hundreds of rows) makes resume trivial: a project is
  either fully copied and verified or untouched.
- **D16** Routes addressed by id alone move under `/p/{pid}/…` in qualification and control-objectives
  (no product code calls the old control-objectives JSON paths; qualification's are called only by its
  own pages and the agent).
- **D17** The report v2 composer migration 0005 and the renderer's `dev` HEAD go live with the cutover
  (they are committed but not deployed; the isolation builds contain them). The rehearsal covers them.

## 23. Risks

1. **Forms work is uncommitted and in flux** in another session; the live qualification image contains
   it and this branch does not. Deploying Q1 without Q2 would remove forms from live. Mitigation: gate
   I4.6, C0 requires the merge, forms migration files copied byte-for-byte, merge conflicts expected on
   the deleted pre-baseline migration directories.
2. **Engine frozen-file guards** (Sean's files, guard-frozen G1/G4/G5, leaf-0024 test) fight any routing
   change in settings/urls/routers. Mitigation: I7.12 lists the allowed changes; E1 names each test
   change.
3. **Id-only routes** in qualification, control-objectives and the engine are where isolation can leak
   or break; each gets a cross-project 404 test (I16.5).
4. **Connection growth**: about 11 connections per active project against 100 (D7, I16.7).
5. **Bundled deploys**: report v2 (composer 0005, renderer HEAD) and the forms work go live with the
   cutover (D17); the rehearsal is the only full test of that combination.
6. **Catalog-driven ownership** might classify an unforeseen table wrongly; mitigations: unclassified
   tables refuse the copy, conflicts abort, `verify` proves the union covers every source row.
7. **Trigger-off copy** could insert rows the triggers would reject; they are historical rows that
   already passed those triggers once, and FK validation plus checksums follow.
8. **Pools holding dropped databases** in long-running apps (I2.5) could 500 after a project delete.
9. **Postgres-setup on every start** would fail after the drop if its `core.system` lines stay unguarded
   (I2.8).
10. **The live qualification image** was built from a scratchpad copy (API-auth inventory); the isolation
    image replaces it, so anything only in that copy and not in git is lost. C0 compares the running
    route list with the new build's.
11. **Timing**: `aisc-eval-worker` and `rabbitmq` are exited today; C2 must confirm no evaluation is
    queued or running, since old tasks carry no project.
