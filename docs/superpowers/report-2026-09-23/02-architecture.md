# Stage 2: Architecture check for the modular AISC report

Status: stage 2 of 5. Inputs: `RULES.md`, `01-specs.md`, the code (read only) and the live databases
(read only, as `aisc-postgres-user`, 2026-09-23). Stages 3 to 5 follow the spec as amended by the
`DEVIATION Dn` entries in section 3. Where a deviation says "user to confirm", its resolution is still
what gets built unless the user says otherwise; D4 is the only one that needs a yes before stage 5.

## 1. Current architecture, as it really is

### 1.1 Databases on the live server (`postgres`, 127.0.0.1:5432, Postgres 14)
Databases: `platform` (every module schema), `superset` (dashboard metadata), `keycloak`, one
`project_<hex>` per project (hex = pid without dashes; name made by
`platform/platform_service/projectdb.py: database_name(pid)`), plus leftovers `aisc`, `controls`,
`qualification`, `control_objectives`, `control_objectives_test` (not read by anything in scope).
Roles: `platform_rw`, `qualification_rw`, `control_objectives_rw`, `controls_rw`, `engine_rw`,
`catalogue_rw`, `dashboard_ro` (dev password = role name). No `report_ro` or `report_composer_rw` yet.

### 1.2 Per block source: tables, columns, how project and version are identified

| block | database.schema.table (real columns used) | project key | version key |
|---|---|---|---|
| cover | `platform.core.project` (pid, name, slug, description); `core.system` (pid, project_id, number, name, version, provider, description, created_at, created_by); `core.project_member` (project_id, subject, email, role) | `pid` | `core.system.pid`; `number` unique per project (`system_project_number_key`); trigger `system_only_latest_changes` |
| ai_card | `platform.qualification.qualification` (id text, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", "intendedDeployers", "targetSystemTags", "sectorTags", "marketFormTags", "localityTags", project_id, system_id); `card_component` (qualification_id, component_pid, airo_property, name, component_type, object_name, linked_at); `knowledge_graph` ("qualificationId", digest, jsonld text, turtle, nodes, triples, built_at) | `project_id` uuid FK core.project | `system_id` uuid FK core.system, UNIQUE (one card per version) |
| risk_classification | same `qualification` row; `qualification_risk` ("qualificationId", position, risk, source, vulnerability, consequence, affected, "impactAreas" text[], control, "followUpControl"); `knowledge_graph.jsonld` | via qualification | via qualification |
| control_objectives | `platform.control_objectives.project` (id varchar pk, name, objectives_digest, project_id uuid, system_id uuid UNIQUE); `risk` (id, project_id varchar FK project.id, risk_id, position, text, short_label, ... , severity); `mapped_objective` (risk_row_id FK risk.id, objective_id, quote, rationale); `mapping_run` (project_id varchar PK, stop in clean/fixpoint/cap/failed, ran_at); `graph`. Labels: `apps/control-objectives/src/aisc_control_objectives/data/ai_act_control_objectives.csv` (ID, Macro_Requirement, Legal_Basis, Sub_Requirement_Label, Control_Objective, ...) | `project.project_id` | `project.system_id` |
| test_results | `platform.engine.project` (id bigint, pid, name, project_id uuid, unique when not null); `evaluation` (id, pid, status in Done/Failed/Archived/Pending/Processing/Custom, project_id bigint, system_id uuid nullable, created_at); `evaluation_plugin` (id, pid, name, evaluation_id, plugin_config_id nullable, status Pending/Running/Done/Failed, started_at, finished_at, error_message); `plugin_config` (plugin_id); `plugin` (name, display_name, package_name, version); `evaluation_input` (evaluation_plugin_id, component_id, value jsonb); `ai_component` (id, name, component_type, system_id bigint FK engine.ai_system); `observation` (evaluation_id, observer, tool); `measurement` (observation_id, metric_id, name, score float, unit, uncertainty, dimensions jsonb, direction, error); `metric` (name, type_spec); `artifact` (evaluation_plugin_id, name, file_size) | `engine.project.project_id` = P, then `evaluation.project_id` = engine.project.id | `evaluation.system_id` (FK core.system, ON DELETE SET NULL) |
| control_answers | `project_<hex>.controls.checklist` (id, "catalogueId", title, "sourceId", "controlTopic", description); `checklist_question` ("checklistId", "order", text, article, category); `submission` ("checklistId", label, status Draft/Closed, version, "previousVersionId", closed_at, archived_at); `submission_answer` ("submissionId", "questionId", answer, score, system_version_pid, system_version_number, answered_at); `source` (id, slug, name) | the database itself (nothing inside names a project) | `submission_answer.system_version_pid` (+ denormalised `system_version_number`) |
| dashboard_chart | `superset.public.dashboards` (id, slug `aisc-<hex>`, dashboard_title, uuid); `dashboard_roles` (dashboard_id, role_id); `ab_role` (name `AiscProject_<hex>`); `dashboard_slices` (dashboard_id, slice_id); `slices` (id, slice_name, viz_type, datasource_id); `tables` (id, table_name `engine_results_<hex>` / `controls_answers_<hex>`); `aisc_comment` (id, dashboard_id varchar, chart_id, parent_id, author_sub, author_name, body, created_at timestamp without tz) | role name `AiscProject_<hex>` (`apps/results-dashboard/aisc_ext/projects.py: project_role_name`) | none on comments; datasets expose `system_version` / `system_version_pid` (engine) and `system_version_number` (controls) |

Live data today: one project (MCAS, pid 01399e17-...), one version, one qualification, one CO assessment
(stop `failed`), zero evaluations, zero comments, one project dashboard with two charts (ids 33, 34).

### 1.3 Sign-in and project roles
- Caddy `(protect)`: `forward_auth host.docker.internal:4180` (oauth2-proxy, host network) copies
  `X-Auth-Request-User`, `-Email`, `-Preferred-Username` and `X-Auth-Request-Access-Token`; 401 becomes a
  redirect to `/oauth2/start`. Python modules are mounted behind `handle_path /<module>*` (prefix stripped,
  app told its root path by env, e.g. `CONTROL_OBJECTIVES_ROOT_PATH`).
- `shared/identity/aisc_identity`: `caller_from_headers(headers)` takes the Bearer token or the gateway
  token header, verifies it against Keycloak JWKS (`AUTH_ENABLED`, `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL`),
  returns `Caller(subject, email, username, roles)` (realm roles). `aisc_identity.fastapi.caller_dependency`
  maps to 401/500. Mounted read-only into each Python service and put on `PYTHONPATH`.
- Project role: the platform API (`platform:8000`) has `GET /authz/projects/{slug}` -> `{role, admin,
  may_write}` and membership CRUD; realm role `admin` counts as owner there. control-objectives instead reads
  `core.project_member` directly per request (`access.py`, `ProjectAccess` middleware, project path accepts
  slug or pid, 404 for strangers, 503 when the lookup fails). The composer follows the control-objectives
  pattern (R4.4.2), except admin rights per R4.4.5.

### 1.4 How an app joins the stack (the recipe, from control-objectives and platform)
1. Compose service in `docker-compose.development.yml`: `build`, `image`, `pull_policy: never`,
   `container_name`, mount `./shared/identity:/app/shared/identity:ro,z`, env (DB URL with its own role,
   `AUTH_ENABLED`, `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL`, `LAUNCHER_URL`, root path), `expose` only (no
   published port), networks `backend` + `frontend`, `depends_on` its migrate job or `postgres-setup`.
2. Caddy: a `handle_path /<prefix>* { import protect; reverse_proxy <svc>:<port> }` in the `:80` site.
3. Launcher: a card in `homepage/project.html` and an entry in the `inProject` map, which rewrites the
   card to `<base>/p/{pid}` (pid, not slug) once the project is loaded.
4. Roles and schemas: made by the superuser in `init/platform-db.sql` (fresh volume only) or
   `init/project-databases.sql` (fresh volume and every start through the `postgres-setup` one-shot);
   platform migrations (`platform/migrations/*.sql`, run as `platform_rw`, tracked in `core.schema_migration`)
   cannot create roles. Per project database: `platform/project-template/*.sql`, run as `platform_rw`
   by `projectdb.provision` on creation and by `provision_all` for every project at platform start
   (tracked in `provision.template_migration`), so a new template file reaches existing projects.
5. Migrations of the app itself: its own at start (platform: `migrate.py`), or a `*-migrate` one-shot.
6. Guards: `scripts/guard-frozen.sh` G1/G2 dump the engine schema and the two AIRO tables from a throwaway DB
   built with `init/platform-db.sql` + `init/project-databases.sql` + migrations; `pg_dump` includes GRANT
   and ALTER DEFAULT PRIVILEGES lines, so report grants must not go into those two init files.

### 1.5 Report generator, plugin interface, mlareject (as they are)
- `aisc-report-generator` (dist `vera-report-generator`, branch dev, no tests, not in any compose file):
  `report_service.py` is a stdlib `ThreadingHTTPServer` on 8001 with `GET /health`, `GET
  /generate?project_id=` (writes a PDF to `./reports`, 303 to `/reports/<name>`), CORS `*`, no auth.
  `report_generator.py: ReportGenerator.run()` opens `DB_URL` through `src/database_manager.py` (read-only
  ORM event guard plus per-plugin `with_loader_criteria` scoping) over `resources/sql_alchemy.py`, a
  BESSER-era model (Project, Evaluation, Observation.dataset_id, Measure.value, Tool, Element, Dataset,
  LegalRequirement) that does not match the engine schema of 1.2. Plugins: `src/plugin_registry.py`
  scans `REPORT_PLUGIN_PATH` directories, imports classes subclassing `BaseReporterPlugin`, looks up
  `normalise(tool)+"ReportPlugin"` (uppercase, spaces/dashes/underscores removed). Templates:
  `resources/templates/report.html.j2`, `title_page`, `system_card`, `assessment_summary`,
  `tool_plots_subsection`, `report_style.css`, `l-aif_style.css`; WeasyPrint `HTML(string=...)` with no
  URL fetcher restriction, `file://` logo. The Dockerfile installs jinja2/pyyaml/sqlalchemy/weasyprint
  but not the plugin interface, so the image cannot import `plugin_registry`.
- `aisc-report-plugin-interface` (dist `vera-report-plugin-interface`, module
  `vera_report_plugin_interface`): `BaseReporterPlugin(db_session)` with `render_package_template`
  (ChoiceLoader of the plugin package and a shared `resources/templates` dir found by walking up from the
  file, autoescape for html/xml, relative-path validation), abstract `get_template_relative_path`,
  `build_template_context(**kw)`, and `generate_content(**kw)` which swallows template errors only.
- `aisc-report-mlareject` (dist `vera-report-plugin-mlareject`): exports `MLAREJECTReportPlugin`;
  `data_loader.py` imports `resources.sql_alchemy` from the generator at import time and queries it with
  no project filter; the module prints at import. The `[tool.uv.sources]` of generator and mlareject point
  at `github.com/lux-ai-factory/vera-report-plugin-interface` (the repo is now
  `aisc-report-plugin-interface`). No MLA-Reject engine plugin is installed on the live stack (engine
  plugins present: LangBiTe, StrongREJECT).

### 1.6 Superset (results dashboard)
`apache/superset:4.1.1` plus immudb-py, Authlib, psycopg2; config overlay and `aisc_ext` bind-mounted;
`network_mode: host` on `DASHBOARD_PORT` (8188), reached from containers as `host.docker.internal:8188`
(as the platform bridge does). Keycloak OAuth (`AUTH_OAUTH`), `DASHBOARD_RBAC`, `EMBEDDED_SUPERSET`,
`THUMBNAILS: False`, `ALERT_REPORTS: False`, no celery worker service. In the running container: celery
5.4 and selenium 3.141 are installed, but no browser and no webdriver binary. So Superset cannot render a
chart image today. Comments: `aisc_ext/comments` (FAB API `/api/v1/aisc_comment`), keyed by
`dashboard_id` text; the review page (`aisc_ext/review`, uncommitted, someone else's) writes
`str(dashboards.id)`.

## 2. Fit/gap per spec rule

| rule | verdict | note |
|---|---|---|
| R1.1 to R1.8, R1.10 to R1.13 | fits | pure renderer logic; new code |
| R1.9, R6.3 | needs change | controls rows cannot join `core.system` (other database): D15 |
| R2.1.1, R2.1.3, R2.1.4 | fits | all fields exist in `core.system` |
| R2.1.2 | needs change | no display name in `Caller`: D12 |
| R2.2.1 to R2.2.5 | fits | columns as in 1.2 (quoted camelCase names) |
| R2.3.1, R2.3.2, R2.3.4 | impossible as specified | no AI Act risk class is stored; role only as operators in the graph: D2 |
| R2.3.3 | needs change | only `affected` and `impactAreas` are identifiers; label source: D3 |
| R2.4.1 to R2.4.3, R2.4.5 | fits | `uq_project_system_id` gives at most one assessment per version |
| R2.4.4 | fits, clarified | one `mapping_run` per assessment: D14 |
| R2.5.1, R2.5.3 to R2.5.7 | fits | engine read only through `report_ro` (frozen model untouched) |
| R2.5.2 | needs change | column is `evaluation_input.component_id`, several inputs per plugin run: D18 |
| R2.5 option `statuses` | fits | completed status is `Done` |
| R2.6.1 to R2.6.6 | fits with D1, D15 | per-project database |
| R2.7.1, R2.7.3, R2.7.6, R2.7.7 | impossible without a Superset change | no screenshot pipeline, no filter on screenshots: D4 |
| R2.7.2, R2.7.4 | needs change | ownership and comment keys via superset tables: D5 |
| R2.7.5 | fits | comments have no version stamp (confirmed) |
| R2.8.x, R2.9.x | fits | |
| R3.1 to R3.16 | fits | R3.1 FK needs grants: D13 |
| R4.1.1 | fits | FastAPI + Jinja as platform/control-objectives |
| R4.1.2 | needs change | launcher passes pid: D11 |
| R4.1.3 | needs change | role and schema must be made by the superuser; REFERENCES grants: D13 |
| R4.2.x | fits | |
| R4.3, R4.3.1 to R4.3.5 | fits | `{slug}` also accepts pid (D11) |
| R4.4.1, R4.4.3, R4.4.4, R4.4.6 | fits | `caller_from_headers`, pattern of `access.py` |
| R4.4.2 | fits | composer role has SELECT on `core.project_member` |
| R4.4.5 | fits | admin from realm role `admin` in the token |
| R5.1.1 to R5.1.4, R5.1.6, R5.1.7 | fits | new code; WeasyPrint already a dependency |
| R5.1.5 | fits | needs a custom `url_fetcher` (today none) |
| R5.2.1 | needs change | real package/module names: D10 |
| R5.2.2 | fits | |
| R5.2.3 | needs change | entry-point group names, packaging: D10 |
| R5.3.1 | needs change | which engine name is "the tool": D7 |
| R5.3.2 | needs change | observation to plugin-run link is a string match: D8 |
| R5.3.3, R5.3.4 | needs change | the one legacy plugin cannot work without a session: D9 |
| R5.3.5 | fits | |
| R5.4, R5.4.1, R5.4.2, R5.4.4 | fits | service rewritten (FastAPI + uvicorn) |
| R5.4.3 | fits | nothing in the stack calls `/generate` |
| R6.1 | needs change | where and how `report_ro` grants are made: D6 |
| R6.2 | needs change | table row for control_answers names the wrong function: D1 |
| R6.4, R6.5 | fits | existence via `pg_database`; catalogue never granted |
| R7.1.x, R7.2.x | fits | R7.2.4 applies to the screenshot poll (D4) |
| R7.3.1 to R7.3.5 | fits | |
| R7.3.6 | fits | only SELECT grants; engine models, AIRO files, knowledge_graph and qualification_risk untouched; G1/G2 unaffected because grants live outside the guard's init files (D6) |
| R7.4.1 | fits | inject Superset client, renderer client, clock |

## 3. Deviations

**DEVIATION D1 (amends R6.2 table, row control_answers; R6.4).** The controls database of P is
`project_<hex>` = `platform_service.projectdb.database_name(pid)`; `controls_database_name(slug)` is the
Superset connection name ("AISC Controls {slug}"). The renderer builds the DSN from
`REPORT_PROJECT_DB_URL` (a template with `{database}`, like controls' `PROJECT_DATABASE_URL`) and the pid;
the database name is validated against `^project_[0-9a-f]{32}$`. R6.4: existence is checked with
`SELECT 1 FROM pg_database WHERE datname = $1` on the platform connection before connecting.

**DEVIATION D2 (amends R2.3.1, R2.3.2, R2.3.4; DEFAULT, user to confirm).** Nothing in the platform
records an AI Act risk class: the qualification methodology states it does not decide high-risk, and the
live graph has no risk-level node. The "role" is recorded as operators of the system node. The block
therefore shows: **Operators**, read from the JSON-LD node typed `https://w3id.org/airo#AISystem`:
provider = objects of `https://w3id.org/airo#isProvidedBy`, deployer = objects of
`https://w3id.org/airo#isDeployedBy`, users = objects of `https://w3id.org/airo#hasAIUser`, each shown by
its `http://www.w3.org/2000/01/rdf-schema#label` (else the IRI); and **Risk class**, from a new option
`stated_risk_class` (enum `not_determined` default, `prohibited`, `high`, `limited`, `minimal`) printed as
"{class} (stated by the report editor; the qualification does not classify risk)" or "Not determined".
R2.3.4: `empty` when there is no operator, no chain and the stated class is `not_determined`.

**DEVIATION D3 (amends R2.3.3).** Only `affected` and `impactAreas` hold identifiers; the other columns are
free text shown as is. Labels come from `apps/qualification/src/data/airo_vocab.json` (keys `affected`,
`impactArea`), bind-mounted read-only into the renderer (`REPORT_AIRO_VOCAB_PATH`); the file is pinned
by G3 and is never copied or changed. Tests use a fixture with the same shape. The same mount pattern
serves the objectives CSV (`REPORT_OBJECTIVES_CSV_PATH`, R2.4.2).

**DEVIATION D4 (amends R2.7.1, R2.7.3, R2.7.6 and the dashboard row of R6.2; NEEDS USER YES before stage 5).**
"Superset's own rendering" (RULES) is Superset's chart screenshot API, which is off and unbuildable in the
current image. Resolution A (default): enable it in `apps/results-dashboard` and the compose file:
(1) `superset_config.py`: `THUMBNAILS: True`, `WEBDRIVER_TYPE` (firefox), `WEBDRIVER_BASEURL =
http://localhost:8188/`, `THUMBNAIL_SELENIUM_USER = "aisc-report"`, `CELERY_CONFIG` on the dashboard's
Redis; (2) Dockerfile: add `firefox-esr` and `geckodriver`; (3) compose: `dashboard-worker` service (same
image and env, `network_mode: host`, `celery --app=superset.tasks.celery_app:app worker`), and
`dashboard-migrate` creates Superset user `aisc-report` (password `DASHBOARD_REPORT_PASSWORD` from
`scripts/secrets.sh`) with role `AiscReportReader` (can read Chart, screenshot permissions on Chart,
`all_datasource_access`). The renderer logs in with `POST /api/v1/security/login {provider: "db"}`,
calls `GET /api/v1/chart/{id}/cache_screenshot/?q=(window_size:!(w,h))` and polls the returned image URL
until 200 or 30 s (R7.2.4). The exact 4.1.1 endpoint parameters and executor setting are checked against
the image's own source in stage 4. Changes to what the rule said: the screenshot renders the saved chart
and takes no filter, and the provisioned charts plot every version by `system_version`, so images are
never version-filtered. R2.7.3's notice is replaced by one on every chart block: "This chart shows all
system versions; this report covers version {n}." One service account serves all projects, so R2.7.2 is
enforced by the renderer (D5) before any Superset call. Why a yes is needed: `apps/results-dashboard` is a
submodule repo that is not among the four repos in RULES, its `superset_config.py` has someone else's
uncommitted hunks, and only the user rebuilds stack images. Resolution B, if the user refuses: the block
shows chart name and comments, and in place of the image "Chart image unavailable: Superset screenshots are
not enabled on this platform." with `status=error` (no image library in the renderer, which RULES would not
allow). The renderer code is the same under A and B; B only has no Superset configured.

**DEVIATION D5 (amends R2.7.2, R2.7.4, R1.13 for charts).** A chart C belongs to P when a row of
`dashboard_slices (dashboard_id, slice_id = C)` belongs to a dashboard `d` with a `dashboard_roles` row
whose `ab_role.name = 'AiscProject_' || hex(P)`. Comments: `aisc_comment WHERE chart_id = C AND
dashboard_id IN (d.id::text, d.slug)` over those dashboards; `created_at` is read as UTC. Choices list
those charts with `slice_name`. All of it is read from the `superset` database as `report_ro`.

**DEVIATION D6 (amends R6.1: where the grants live).** `report_ro`: LOGIN, password from
`REPORT_RO_PASSWORD` (dev default `report_ro`), `ALTER ROLE report_ro SET default_transaction_read_only = on`.
(a) `init/report-roles.sql` (superuser; initdb mount and every `postgres-setup` run): creates `report_ro`
and `report_composer_rw` if missing, CONNECT on `platform` and `superset`, USAGE + SELECT on `core`.
(b) `init/report-ro-grants.sql` (superuser, idempotent, each grant skipped when `to_regclass` is null),
run by a new one-shot `report-grants` service after `qualification-migrate`, `control-objectives-migrate`,
`controls-migrate` complete and once `engine.measurement` exists (wait loop): explicit SELECT on
`qualification.{qualification,card_component,knowledge_graph,qualification_risk}`,
`control_objectives.{project,risk,mapped_objective,mapping_run}`,
`engine.{project,evaluation,evaluation_plugin,evaluation_input,plugin_config,plugin,ai_component,observation,measurement,metric,artifact}`
(never `auth_*`, `django_*`, `project_config`, `plugin_config_project_config`, `account_*`), and in
`superset` SELECT on `aisc_comment, dashboards, dashboard_roles, ab_role, dashboard_slices, slices,
tables`. No ALTER DEFAULT PRIVILEGES on module schemas, so a new table is not readable by accident.
`plugin_config.config` may hold tool settings, so that table gets a column grant only:
`GRANT SELECT (id, plugin_id) ON engine.plugin_config TO report_ro` (the engine list above means that).
(c) Project databases: `platform/project-template/0003_report.sql` (as `platform_rw`, the owner of the
database and of schema `controls`): CONNECT and USAGE on `controls` for `report_ro`; the table SELECTs
(tables owned by `controls_rw`) come from the same `report-grants` job, looping over `pg_database WHERE
datname ~ '^project_[0-9a-f]{32}$'` and granting SELECT on `controls.{checklist,checklist_question,
submission,submission_answer,source}`; and in `template1` it runs `ALTER DEFAULT PRIVILEGES FOR ROLE
controls_rw GRANT SELECT ON TABLES TO report_ro`, so databases made later inherit it. No change to
`apps/controls`. None of this is in `init/platform-db.sql` or `init/project-databases.sql`, so the guard's
G1/G2 dumps do not change.

**DEVIATION D7 (amends R5.3.1).** An engine tool is identified by the `plugin` row reached through
`evaluation_plugin.plugin_config_id -> plugin_config.plugin_id`. A renderer declares `tool_names` (tuple);
it matches when any normalised name equals the normalised `display_name`, `name`, `name` without a
trailing `EvaluationPlugin`/`Plugin`, or `package_name` without the `aisc-plugin-` prefix. The tool name
shown and passed to `links` (R2.8) is `display_name`. The legacy lookup `{KEY}ReportPlugin` tries the
same keys.

**DEVIATION D8 (amends R5.3.2).** The engine links observations to a plugin run only by
`observation.evaluation_id` and `observation.tool = "{package_name}::{name} (v{version})"`
(`apps/backend/aisc_backend/routers/internal.py`). The run object takes the observations matching that
string; when `plugin_config_id` is null or nothing matches and the evaluation has exactly one
`evaluation_plugin`, it takes every observation of the evaluation; otherwise unmatched observations are
shown once per evaluation by the generic renderer with the notice "{k} observations could not be tied to
a tool." Measurements carry `score` (float), `unit`, `uncertainty`, `dimensions` (jsonb), `name` and the
metric name; there are no text values.

**DEVIATION D9 (amends R5.3.3, R5.3.4).** The only legacy plugin, `MLAREJECTReportPlugin`, reads the database
itself through the obsolete generator model; with no session it raises. The adapter stays as specified
(construct with `db_session=None`, call `generate_content(run=run, tool_plots={})`, fall back per R2.5.4).
`aisc-report-mlareject` gains `MLAREJECTToolRenderer(BaseToolRenderer)`, which wins by R5.3.4 and computes
its statistics from `run.measurements`: score = measurements whose metric name is `score`; language,
jailbreak method and category from `measurement.dimensions` keys `language`, `jailbreak`, `category`
(DEFAULT, user to confirm: no MLA-Reject engine plugin is installed to check against); missing keys show
"unknown"; harmful-case texts are omitted. The import of `resources.sql_alchemy` moves inside the legacy
loader and the import-time `print` goes, else the package fails to import once the generator drops that
module (R5.2.3 would then skip it).

**DEVIATION D10 (amends R5.2.1, R5.2.3; names and packaging).** Names are kept: dists
`vera-report-plugin-interface`, `vera-report-generator`, `vera-report-plugin-mlareject`, module
`vera_report_plugin_interface`. New public names: `vera_report_plugin_interface.BaseBlockRenderer`,
`BlockResult`, `BaseToolRenderer`, `ToolRun`. Entry-point groups: `aisc_report.blocks` and
`aisc_report.tools`; `REPORT_PLUGIN_PATH` scanning stays for both kinds and for legacy plugins. uv
sources become local path sources (`../aisc-report-plugin-interface`, `../aisc-report-mlareject`,
editable). The image is built by compose with `additional_contexts` (`interface`, `mlareject`, paths from
`REPORT_INTERFACE_DIR` / `REPORT_MLAREJECT_DIR`, default `../aisc-report-*`) and installs all three; smoke
builds are tagged `*:report-test`.

**DEVIATION D11 (amends R4.1.2, R4.3 `{slug}`).** The launcher opens modules with `/p/{pid}`. The composer
accepts slug or pid in `{slug}` (as `access.py` does) and redirects a pid URL to the slug URL; the
launcher card uses pid through the `inProject` map. Filenames (R4.3.4) always use the slug.

**DEVIATION D12 (amends R2.1.2).** "Display name" = `Caller.username` (preferred_username), else `email`,
else `subject`. The composer passes it as `requested_by` (string) in the snapshot.

**DEVIATION D13 (amends R4.1.3, R3.1).** `report_composer_rw` (dev password = role name, override
`REPORT_COMPOSER_PASSWORD`) and schema `report_composer` (owned by it) are made by the superuser in
`init/report-roles.sql`, with USAGE and SELECT on `core` and REFERENCES on `core.project`, `core.system`;
`ALTER ROLE report_composer_rw IN DATABASE platform SET search_path = report_composer, core`. Its own
migrations run at start (copy of `platform_service/migrate.py`, table `report_composer.schema_migration`).
`layout.system_id` is `NO ACTION` (not RESTRICT) so deleting a project cascades cleanly.

**DEVIATION D14 (clarifies R2.4.4).** `mapping_run` has one row per assessment (pk `project_id` =
`control_objectives.project.id`): that row is "the latest".

**DEVIATION D15 (amends R1.9, R6.3 for controls; R2.6.3).** The renderer reads from `platform` the pids of
P's versions newer than S and passes them as an array (`system_version_pid = ANY(%s)`). Answers with
`system_version_pid` null count with other-version answers in the R2.6.3 notice.

**DEVIATION D16 (amends R2.5.2).** "The component it ran on" = every `evaluation_input` of the plugin run:
`ai_component.name` and `component_type` (engine-local components, never matched to
`qualification.card_component`).

## 4. Build map (files and directories created or changed)

**aisc-install** (branch feat/unified-modules)
- new `apps/report-composer/`: `pyproject.toml`, `uv.lock`, `Dockerfile`, `README.md`,
  `report_composer/` (`app.py` routes, `access.py` membership/admin/origin, `db.py`, `migrate.py`,
  `layouts.py` validation/ordering/revision, `templates_store.py`, `renderer_client.py` (injectable),
  `forms.py` options-schema to form, `errors.py`, `clock.py`), `migrations/0001_report_composer.sql`,
  `templates/*.html.j2`, `static/composer.js`, `static/composer.css`, `tests/`.
- new `init/report-roles.sql`, `init/report-ro-grants.sql`, `scripts/report-grants.sh` (the loop of D6c).
- new `platform/project-template/0003_report.sql`.
- `docker-compose.development.yml`: services `report-composer`, `report-renderer`, `report-grants`;
  D4-A: `dashboard-worker` and the `dashboard-migrate` command.
- `docker-compose-infra.development.yml`: mount `init/report-roles.sql` in initdb and run it in `postgres-setup`.
- `Caddyfile`: `handle_path /report-composer* { import protect; reverse_proxy report-composer:8095 }`.
- `homepage/project.html`: card 7 "Report" (third row) and `inProject` entry.
- `scripts/secrets.sh` (and `env.secrets` it writes): `REPORT_SERVICE_TOKEN`, `REPORT_RO_PASSWORD`,
  `REPORT_COMPOSER_PASSWORD`, D4-A `DASHBOARD_REPORT_PASSWORD`.
- `scripts/tests/test_compose.py`: assertions for the new services (no published ports, networks, env).
- `scripts/verify-db-access.sh`: report_ro / report_composer_rw allow/deny lines (live only, never in tests).
- D4-A only, submodule `apps/results-dashboard`: `superset_config.py` (own hunks only), `Dockerfile`.

**aisc-report-generator** (branch dev)
- rewritten: `report_service.py` (FastAPI `/health`, `/v1/block-types`, `/v1/choices`, `/v1/render`, token),
  `pyproject.toml`, `uv.lock`, `Dockerfile`, `README.md`.
- new package `report_renderer/`: `snapshot.py` (schema, R5.4.2), `context.py`, `registry.py` (built-ins,
  entry points, plugin dir, duplicate refusal), `document.py` (order, wrapping, banner, TOC), `pdf.py`
  (WeasyPrint, `data:`-only fetcher), `errors.py` (error_ref, logging without bodies), `superset.py` (client
  interface, HTTP client, fake), `data/` (`scope.py` NotInProject, `platform.py`, `qualification.py`,
  `control_objectives.py`, `engine.py`, `controls.py`, `superset_db.py`, `vocab.py`), `blocks/` (nine
  renderers), `tools/` (`generic.py`, `legacy_adapter.py`), `templates/` (block templates, `report.html.j2`,
  styles moved from `resources/templates`).
- removed: `report_generator.py`, `src/`, `resources/sql_alchemy.py`, `/generate` and `/reports/` routes.
- new `tests/` (unit, `db/` against the throwaway bed, `fixtures/`).

**aisc-report-plugin-interface** (branch dev): new `vera_report_plugin_interface/blocks.py`, `tools.py`,
`templating.py` (shared loader taken out of `base_report_plugin.py`, which keeps its behaviour),
`__init__.py` exports, `pyproject.toml` (jsonschema dependency), `tests/`, `README.md`.

**aisc-report-mlareject** (branch dev): new `vera_report_plugin_mlareject/tool_renderer.py`,
`statistics.py` (pure functions over a run), template adjusted to the new context, `__init__.py` exports,
`mlareject_reporter.py` / `data_loader.py` (lazy import, no print), `pyproject.toml` (entry point, path
source), `tests/`.

Not touched: `apps/backend`, `apps/webapp`, `apps/eval`, `shared/plugin-interface`, AIRO/VAIR files,
`apps/qualification`, `apps/control-objectives`, `apps/controls`, `apps/catalogue`.

## 5. Test infrastructure

| repo | today | command |
|---|---|---|
| platform | pytest; DB tests skip without a DB; **default DSN is the live DB as platform_rw**, set `PLATFORM_TEST_DATABASE_URL` | `cd platform && uv run --extra dev pytest` |
| control-objectives | pytest; default `CONTROL_OBJECTIVES_TEST_DATABASE_URL` is live `control_objectives_test` on 5432 | `uv run --extra dev pytest` |
| scripts/tests | pytest over guard, chain, `docker compose config` of scratch copies | `uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests` |
| chain | `scripts/test-pipeline-chain.sh` (throwaway DB, all migrations at HEAD) | as named |
| guard | `scripts/guard-frozen.sh` (must pass at the end) | as named |
| controls, qualification | vitest (`npm test`); controls integration tests create and drop databases on their target | not run by this work |
| generator, interface, mlareject | no tests, no venv | new: `uv run --extra dev pytest` in each repo |

Host: `uv`, Python 3.12, node 20, Pango libraries present (WeasyPrint runs on the host); no `psql` or
`pg_dump` on the host, they run inside containers. Tokens in composer tests: sign with a local RSA key and
monkeypatch `aisc_identity.service.key_for_jwks`, as `platform/tests/conftest.py` does.

**Throwaway test bed for renderer and composer** (session fixture, `tests/conftest.py` in each):
1. Guard: refuse to start unless every DSN env var used by the tests points at the fixture's port; never 5432.
2. Start one `postgres:14-alpine` container `aisc-t-report-<hex>` through `scripts/lib/throwaway-pg.sh`
   (the renderer repos call it via `AISC_INSTALL_DIR`, default `../aisc-install`) or the equivalent Python
   `scripts/pipeline_chain/throwaway.py`; removed at session end.
3. Schema: `init/platform-db.sql`, `init/project-databases.sql`, `init/report-roles.sql`, platform
   migrations 0001 to 0003 as `platform_rw`; then a committed schema fixture
   `tests/fixtures/modules_schema.sql` holding the read tables of `qualification`, `control_objectives`,
   `engine` (schema-only, produced once by `tests/fixtures/refresh_schema.sh`, which runs `pg_dump
   --schema-only -t ...` inside the live `postgres` container, read only); a `superset` database with the
   seven tables of D6 (schema-only fixture from the same script); two project databases made with
   `platform/project-template/*.sql` and `tests/fixtures/controls_schema.sql`; then
   `init/report-ro-grants.sql` and the D6c loop.
4. Seed (`tests/fixtures/seed.sql`, superuser): project A with versions 1, 2, 3 and project B with version 1;
   for A: a qualification + card components + knowledge graph (small JSON-LD with isProvidedBy /
   isDeployedBy) + risks for v1 and v2; CO assessments for v1 and v2 with risks, objectives and a
   `mapping_run` with stop `cap`; an engine project with evaluations stamped v1 (Done, two tools, one
   MLAREJECT with `dimensions`), v2, and null; controls answers stamped v1, v2 and null; a dashboard with
   role `AiscProject_<hexA>`, two charts, comments with replies; for B: one of each, so every cross-project
   leak test has a victim.
5. Renderer tests connect as `report_ro` (proves R6.1: a write attempt must fail) and use the fake Superset
   client (fixed PNG) and a fixed clock; composer tests connect as `report_composer_rw` and use a fake
   renderer; one composer-to-renderer contract test runs the real renderer app in process on the same bed.
6. Unit tests (block logic, validation, escaping, ordering) need no database and run first.

## Orchestrator amendments (binding, override the sections above)

- **O1 (resolves D4 for this run): no change to Superset tonight.** Enabling screenshots means rebuilding
  the stack's own dashboard image and adding a worker, which is the user's call (they are away). So, for
  this run:
  - the chart block gets its image through a small **image-provider interface** in the renderer;
  - the implementation shipped tonight is `NoImageProvider`. The block renders the chart's title, a link to
    the chart in the dashboard, its review comments, and, if the chart-data API
    (`/api/v1/chart/{id}/data/`) is reachable with a read-only login, a compact table of the chart's data.
    Otherwise it shows a note that images need screenshots enabled;
  - `SupersetScreenshotProvider` (Resolution A) is written and unit-tested against a mocked Superset API,
    but it is off unless `REPORT_CHART_IMAGES=superset` is set;
  - no file in apps/results-dashboard and no compose change for Superset.
  D4's "all versions" notice stays on every chart block.
- **O2:** D2's default (the risk class is stated by the editor as a block option, with provider, deployer and
  users read from the card) is accepted for this run and listed for the user.
