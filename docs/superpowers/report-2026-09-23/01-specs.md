# Stage 1: Specs for the modular AISC report (composer + renderer)

Status: stage 1 of 5. Binding input: `RULES.md` in this folder. This document stands on its own.
Every rule is numbered and phrased "When X, then Y" so that stage 3 can turn it into a test.
Open decisions are marked `DEFAULT (user to confirm)`; the default is what gets built unless the user says otherwise.

## 0. Vocabulary and fixed facts

- **Project**: a row of `core.project` (pid uuid, name, slug) in the `platform` database.
- **System version** (also "card version"): a row of `core.system` with `project_id`, `number` (1, 2, 3, per
  project), `name`, `version` (the makers' release string), `provider`, `description`, `created_at`.
  A project has one AI system; only its card is versioned. "Pinned version" means one `core.system.pid`.
- **Stamped data**: engine `evaluation.system_id`, controls `submission_answer.system_version_pid`,
  control-objectives `control_objectives.project.system_id`, qualification `qualification.system_id`
  all hold a `core.system.pid`. A report reads only rows stamped with its pinned version.
- **Membership**: `core.project_member (project_id, subject, role in viewer|editor|owner)`. Owner counts as editor.
  The realm role `admin` is not a membership (see R4.4.5).
- **Block type**: a kind of section (Cover, AI card, ...). **Block instance**: one occurrence of a block type in
  a layout, with its own options.
- **Layout**: an ordered list of block instances belonging to one project and pinned to one system version.
- **Template**: a project-independent copy of a layout's block list, reusable in any project.
- **Composer**: new service `apps/report-composer` in aisc-install (plain folder, Python, thin frontend).
- **Renderer**: `aisc-report-generator` (service `report_service.py`), with block and tool plugins whose base
  classes live in `aisc-report-plugin-interface`; `aisc-report-mlareject` is the first tool plugin.
- **Tool**: an engine test plugin (engine `plugin` / `evaluation_plugin` rows), for example MLAREJECT.

## 1. Block type contract

R1.1 When a block type is registered, then it declares: `type_id` (lowercase slug, unique, for example
`test_results`), `title` (default heading), `contract_version` (integer, starts at 1), `options_schema`
(a JSON Schema object, draft 2020-12), `default_options` (valid against the schema), and `reads` (the list of
sources from section 6 it may read).
R1.2 When two registered block types share a `type_id`, then the renderer refuses to start and logs both
origins (fail loudly at startup, never pick one silently).
R1.3 When a block instance is rendered, then the block receives a context with exactly: `project_id`,
`project` (name, slug), `system` (the pinned `core.system` row), `newer_versions` (numbers greater than the
pinned one, in this project), `generated_at` (UTC), `mode` (`preview` or `pdf`), a read-only data access
object scoped to (project_id, system pid), and its validated options.
R1.4 When a block renders, then it returns a `BlockResult` with `html` (a fragment, no `<html>`/`<body>`),
`status` (`ok`, `empty`, `stale`, `error`), and `notices` (list of short plain-text strings).
R1.5 When a block renders, then its fragment is wrapped by the renderer in
`<section class="block block-{type_id}" id="block-{instance_id}" data-status="{status}">` with an `<h2>`
holding the instance title (option `title` if set, else the type's `title`).
R1.6 Every block type accepts two common options in addition to its own: `title` (string, 0 to 200
characters, default empty meaning "use the type title") and `page_break_before` (boolean, default false).
When `page_break_before` is true, then the section carries CSS `break-before: page` in the PDF.
R1.7 When the data a block needs is absent for the pinned version, then the block returns `status=empty`
and a one-paragraph placeholder naming what is missing and the version number, for example
"No test results for version 2." It never raises.
R1.8 When the block's source holds data for the same project but a different system version, then that data
is never shown, counted or averaged in this block.
R1.9 When the block's source holds data stamped with a version newer than the pinned one, then the block
returns `status=stale` (unless `empty` or `error` applies) and a notice "Newer results exist for version N."
naming the highest such number.
R1.10 When a block raises any exception while loading or rendering, then the renderer catches it, renders
an error box "This section could not be rendered (ref {error_ref})." with `status=error`, logs the traceback
with that `error_ref` (8 hex characters), and continues with the next block. The traceback never appears
in the HTML or PDF.
R1.11 When options fail validation against `options_schema` at render time, then the block is rendered as
`status=error` with the notice "Invalid options: {field}: {reason}" and no data is read.
R1.12 All text coming from data sources or options is HTML-escaped (Jinja autoescape on). When a value
contains `<script>`, then it appears as literal text.
R1.13 A block type may declare `choices(ctx, option_name)` returning `[{value, label}]` for options that
refer to data (evaluations, charts, checklists). When called, then it returns only items of the context's
project and pinned version (charts: of the project, see R2.7.2).

## 2. The blocks

Numbering: R2.<block>.<rule>. Block order below is the default order of a new layout (R3.3).

### 2.1 Cover (`cover`)
Options: `report_title` (string, 1 to 200, default "AI system assessment report"), `subtitle` (string, 0 to
300, default empty), `show_logo` (bool, default true), `show_generated_by` (bool, default true).
R2.1.1 When rendered, then it shows: report title, subtitle if set, project name, system name, "Version
{number}" and the release string in parentheses if `core.system.version` is set, provider if set, the date
of generation (YYYY-MM-DD, UTC), the layout name and "revision {n}".
R2.1.2 When `show_generated_by` is true, then it shows the display name of the user who generated it (from
the sign-in headers; "preview" in preview mode).
R2.1.3 When newer versions exist in the project, then the cover shows a banner "This report covers version
{p}. Version {n} is newer." regardless of block options. (Report-level banner; also R5.1.6.)
R2.1.4 The cover never has `status=empty` (project and system always exist once the layout validates).

### 2.2 AI card (`ai_card`)
Options: `show_components` (bool, true), `show_tags` (bool, true), `show_graph_stats` (bool, false).
R2.2.1 When rendered, then it reads the `qualification.qualification` row whose `system_id` is the pinned pid
and shows: system name, company, description, target use case, target users, intended deployers (if set).
R2.2.2 When `show_tags` is true, then it lists target system, sector, market form and locality tags, each
group omitted if empty.
R2.2.3 When `show_components` is true, then it shows a table of `qualification.card_component` rows of that
qualification (name, component type, AIRO property, object name), ordered by `linked_at`, then `name`.
R2.2.4 When `show_graph_stats` is true and a `qualification.knowledge_graph` row exists, then it shows node
count, triple count, digest (first 12 characters) and build time, so the reader can match the report to the
exported JSON-LD card.
R2.2.5 When no qualification row exists for the pinned pid, then `status=empty` with "No AI card for version {n}."

### 2.3 Risk classification (`risk_classification`)
Options: `show_chains` (bool, true), `show_impact_areas` (bool, true).
R2.3.1 When rendered, then it shows the AI Act role and the risk class of the pinned version's card, read
from the knowledge graph JSON-LD (`knowledge_graph.jsonld`) of that qualification. DEFAULT (user to confirm):
role and class are the AIRO nodes typed as the AI Act role and risk category in the vendored AIRO/VAIR terms;
stage 2 names the exact IRIs.
R2.3.2 When either value is absent, then it shows "Not determined" for it (the block is still `ok` if chains exist).
R2.3.3 When `show_chains` is true, then it shows one row per `qualification.qualification_risk` of that
qualification, ordered by `position`: risk, source, vulnerability, consequence, affected, control,
follow-up control; plus impact areas when `show_impact_areas` is true. Identifiers are shown with their
labels from the vocabulary when a label exists, else the raw identifier.
R2.3.4 When there is no role, no class and no chain, then `status=empty`.

### 2.4 Control objectives (`control_objectives`)
Options: `group_by` (`objective` or `risk`, default `objective`), `show_rationale` (bool, true),
`show_quotes` (bool, false), `show_status` (bool, true).
R2.4.1 When rendered, then it reads the control-objectives assessment of the pinned version
(`control_objectives.project` row with `project_id` and `system_id` equal to the pinned ones) and its
`risk` and `mapped_objective` rows.
R2.4.2 When `group_by=objective`, then each distinct `objective_id` is listed once, with its label from the
objectives catalogue shipped with control-objectives (`ai_act_control_objectives.csv`: ID, Macro_Requirement,
Legal_Basis, Control_Objective) and the risks mapped to it; when `group_by=risk`, each risk lists its objectives.
R2.4.3 When `show_status` is true, then each objective shows its coverage status computed exactly as in R2.8.3.
R2.4.4 When the latest `mapping_run` of that assessment has `stop` other than `clean`, then a notice
"The mapping run stopped: {stop}." is added.
R2.4.5 When no assessment row exists for the pinned version, then `status=empty`.

### 2.5 Test results (`test_results`)
Options: `evaluations` (`"all"` or a list of evaluation pids, default `"all"`), `tools` (`"all"` or a list of
tool names, default `"all"`), `statuses` (list, default only the completed status of `EvaluationStatus`),
`show_measurements` (bool, true), `show_artifacts` (bool, false).
R2.5.1 When rendered, then it lists the engine evaluations of the project (engine `project.project_id` equal
to the project pid) with `evaluation.system_id` equal to the pinned pid, filtered by the options, ordered by
`created_at`.
R2.5.2 For each evaluation, then it shows pid (short), status, date, and for each `evaluation_plugin`: tool
name, the component it ran on (via `evaluation_input.component` to `ai_component`), its status, then the
tool section produced by the tool renderer (section 5.3).
R2.5.3 When a tool has no registered tool renderer, then the generic tool renderer shows a table of its
observations and measurements (metric name, value, unit if any) and the notice "No dedicated renderer for
{tool}; showing raw measurements." The report never fails because of an unknown tool.
R2.5.4 When a tool renderer raises, then that tool section falls back to the generic renderer with the notice
"The {tool} renderer failed (ref {error_ref})."; other tools and blocks are unaffected.
R2.5.5 When `evaluations` lists a pid that is not of this project and version, then validation fails (R3.6);
at render time such a pid is skipped with a notice (defence in depth).
R2.5.6 When evaluations of the project have `system_id` null, then they are not shown and a notice says
"{k} evaluations are not tied to a version and are not shown."
R2.5.7 When `show_artifacts` is true, then artifact names and sizes are listed, never their content.

### 2.6 Control answers (`control_answers`)
Options: `checklists` (`"all"` or a list of checklist ids, default `"all"`), `show_unanswered` (bool, true),
`show_scores` (bool, true), `include_archived` (bool, false).
R2.6.1 When rendered, then it reads the project's own controls database (schema `controls`) and, per
checklist, the latest submission (highest `version` in its chain, not archived unless `include_archived`)
that has at least one `submission_answer` with `system_version_pid` equal to the pinned pid.
R2.6.2 For each such checklist, then it shows title, source name, control topic, submission label, status
and version, then the questions ordered by `order` with article, answer and (if `show_scores`) score.
R2.6.3 Answers stamped with another version are treated as unanswered for this report; when any exist, a
notice says "{k} answers were given for other versions and are not shown."
R2.6.4 When `show_unanswered` is false, then unanswered questions are omitted; otherwise they show "Not answered".
R2.6.5 When `show_scores` is true, then each checklist shows the mean of its non-null scores for this
version, rounded to one decimal, and "answered {a} of {q}".
R2.6.6 When no checklist has answers for the pinned version, then `status=empty`.

### 2.7 Dashboard chart with comments (`dashboard_chart`)
Options: `chart_id` (integer, required, no default), `show_comments` (bool, true), `include_replies` (bool,
true), `width` (integer 400 to 1600, default 1200), `height` (integer 300 to 1200, default 700).
R2.7.1 When rendered, then it shows the chart's name, a PNG image obtained from Superset's own rendering of
that chart at generation time, filtered to the pinned version where the chart's dataset exposes the version
column, and the rendering time.
R2.7.2 A chart belongs to the project only when it is in a dashboard whose access is granted to the
project's Superset role (`project_role_name(pid)`, as in `apps/results-dashboard/aisc_ext/projects.py`).
When `chart_id` is not such a chart, then validation fails, and at render time the block shows
"Chart not available in this project." with `status=error` and no image is fetched.
R2.7.3 When the chart's dataset has no version column, then the image is unfiltered and the notice says
"This chart is not filtered by system version."
R2.7.4 When `show_comments` is true, then it lists the `aisc_comment` rows with that `chart_id` and a
`dashboard_id` of the project's dashboards, oldest first: author name, date, body; replies (`parent_id`)
indented under their parent when `include_replies`, omitted otherwise.
R2.7.5 Comments carry no version stamp. DEFAULT (user to confirm): all comments of the chart are shown with
the notice "Comments are not tied to a system version." (Alternative: only comments created between the
pinned version's `created_at` and the next version's.)
R2.7.6 When Superset fails or exceeds the timeout (R7.2.4), then the image is replaced by "Chart image
unavailable (ref {error_ref})." and comments are still shown; `status=error`.
R2.7.7 In tests, the Superset rendering client is an injected interface; a fake returns a fixed PNG.

### 2.8 Summary / coverage (`summary_coverage`)
Options: `links` (list of `{objective_id, tests: [tool names], checklists: [checklist ids]}`, default empty),
`show_uncovered_only` (bool, false).
R2.8.1 When rendered, then it lists every objective of the pinned version's control-objectives assessment
(same set as R2.4.2), with the tests and checklists linked to it and a result.
R2.8.2 Links come from the block's `links` option. DEFAULT (user to confirm): nothing in the platform today
records which test or checklist covers an objective, and the Catalogue is out of scope, so the editor sets
the links in this block's options; the composer offers every objective, every tool with results for this
version and every checklist as choices.
R2.8.3 Coverage status of an objective, computed from the data of the pinned version only (not from the other
rendered blocks, so it works even when they are absent from the layout):
`not covered` when it has no links; `no evidence` when it has links but none has data for this version;
`evidence` when at least one linked test has a completed evaluation or one linked checklist has answers;
`evidence, attention` when additionally a linked tool renderer's optional `verdict()` returns `fail` or a
linked checklist's mean score is below 3. DEFAULT (user to confirm): the threshold 3 on the 1 to 5 scale.
R2.8.4 When `show_uncovered_only` is true, then only `not covered` and `no evidence` rows are shown.
R2.8.5 The block ends with counts per status. When there is no assessment, then `status=empty`.

### 2.9 Free text (`free_text`)
Options: `text` (string, 1 to 20000 characters, required).
R2.9.1 When rendered, then the text is escaped and split into paragraphs on blank lines; single newlines
become line breaks. No HTML or Markdown is interpreted. DEFAULT (user to confirm): plain text only.
R2.9.2 Free text reads no source; it never has `status=empty` or `stale`.

## 3. Report layout

### 3.1 Data model (schema `report_composer` in the `platform` database)
- `layout`: `id` uuid pk, `project_id` uuid not null fk `core.project(pid)` on delete cascade, `system_id`
  uuid not null fk `core.system(pid)`, `name` text (1 to 120, unique per project), `description` text,
  `revision` integer not null default 1, `created_at`, `created_by` (subject), `updated_at`, `updated_by`.
- `layout_block`: `layout_id` fk on delete cascade, `instance_id` uuid, `position` integer (0-based),
  `block_type` text, `options` jsonb; pk (`layout_id`, `instance_id`), unique (`layout_id`, `position`).
- `template`: `id` uuid pk, `name` text unique (1 to 120), `description`, `blocks` jsonb (ordered list of
  `{block_type, options}`), `source_project_id` uuid null (on delete set null), `created_by`, `created_at`.
- `generated_report`: `id` uuid pk, `layout_id` fk on delete cascade, `layout_revision` integer,
  `project_id`, `system_id`, `snapshot` jsonb (the full block list as rendered), `status` (`running`,
  `done`, `partial`, `failed`), `pdf` bytea null, `sha256` text, `size_bytes`, `block_statuses` jsonb,
  `error_ref` text null, `created_by`, `created_at`, `finished_at`.

R3.1 When a layout is saved, then the system version must belong to the layout's project, else 422
`system_not_in_project`.
R3.2 When `project_id` of a layout is changed through the API, then the request is refused (422
`immutable_field`): a layout never moves between projects.
R3.3 When a layout is created without template or blocks, then it gets the default block list: cover,
ai_card, risk_classification, control_objectives, test_results, control_answers, summary_coverage, each
with default options. DEFAULT (user to confirm).
R3.4 When a layout is created without `system_id`, then it is pinned to the highest `number` of the project.

### 3.2 Validation
R3.5 When a layout is saved, then each block's `block_type` must be a registered type (422 `unknown_block_type`),
and its options must validate against the type's schema (422 `invalid_options` with the instance id and the
JSON pointer of the field).
R3.6 When an option refers to data (evaluation pid, chart id, checklist id, objective id), then the value must
be in the block type's `choices` for this project and version (422 `invalid_reference`).
R3.7 When a layout has more than 50 blocks, more than 10 `dashboard_chart` blocks, or more than one `cover`,
then it is refused (422 `too_many_blocks` / `duplicate_cover`).
R3.8 When a layout has zero blocks, then it may be saved but not generated (422 `empty_layout` on generate).
R3.9 When the pinned version of a saved layout is changed, then the save succeeds only if the references of
R3.6 are valid for the new version; otherwise 422 lists the invalid ones, and the client may resend with
those options reset (`reset_invalid: true`), which sets them back to their defaults.
R3.10 When a stored layout references a block type that is no longer registered, then it still loads, the
editor marks that block "unknown type", preview renders it as `status=error`, and generate is refused
(422 `unknown_block_type`) until the block is removed.

### 3.3 Versioning (simple)
R3.11 When a layout is saved, then `revision` increases by one; the request must carry the revision it was
based on, and when that is not the current one, then 409 `stale_revision` with the current revision.
R3.12 There is no history table for layouts. When a report is generated, then its `snapshot` holds the exact
block list and options used, so every generated PDF stays explainable after later edits.
R3.13 When a layout is deleted, then its generated reports are deleted with it. DEFAULT (user to confirm).

### 3.4 Templates
R3.14 When an editor saves a layout as a template, then the template stores block types and options in order,
with every data reference (R3.6) reset to the type default and `free_text.text` replaced by
"[text]" unless `keep_text: true` is sent. DEFAULT (user to confirm): references and text are stripped, so
a template carries no project data.
R3.15 When a layout is created from a template, then its blocks are copies (new instance ids) with the
template's options; later template changes or deletion do not affect it.
R3.16 Templates are visible to every signed-in user of the platform. When anyone other than the creator or
an `admin` deletes a template, then 403.

## 4. Report composer service (`apps/report-composer`)

### 4.1 Shape
R4.1.1 The composer is a Python web service (FastAPI DEFAULT (user to confirm)) serving server-rendered HTML
(Jinja) and a JSON API; the frontend is one small script for drag and drop and form submission. All
validation, ordering and rights logic is in Python.
R4.1.2 It is reachable at `/report-composer/` behind Caddy with oauth2-proxy and Keycloak like the other
modules, and appears as step 7 on the project launcher (`homepage/project.html`), opening
`/report-composer/p/{slug}/`.
R4.1.3 It owns schema `report_composer` in the `platform` database through its own role
`report_composer_rw` (all rights on its schema, SELECT on `core`, nothing else). Migrations run at start.

### 4.2 Screens
R4.2.1 **Layouts list** (`/p/{slug}/`): shows each layout's name, pinned version number, revision, last
update, last generated report date and status. Editors also see "New layout", "New from template", "Delete".
R4.2.2 **Editor** (`/p/{slug}/layouts/{id}`): a palette of block types; the ordered block list with move up,
move down, drag, remove and a configure form per block (generated in Python from the options schema, with
choices from R1.13); a version selector; Save; a preview pane; Generate; a list of generated reports.
R4.2.3 When the user moves, adds, removes or configures a block, then nothing is stored until Save; Save
sends the full ordered list (R4.3, PUT). Unsaved changes are flagged on screen.
R4.2.4 **Preview**: renders the saved revision (not unsaved edits) as HTML in a sandboxed iframe.
DEFAULT (user to confirm): preview of saved state only.
R4.2.5 **Generate**: creates the PDF of the saved revision; the screen shows progress, then the result with
per-block statuses and a Download link.
R4.2.6 When the user is a viewer, then the list, preview and download are available and all edit controls
(palette, reorder, configure, save, delete, generate, save as template) are absent.

### 4.3 API (JSON unless stated; prefix `/report-composer/api`; `{slug}` is `core.project.slug`)
| method, path | right | request | success |
|---|---|---|---|
| GET `/p/{slug}/systems` | viewer | | 200 `[{pid, number, name, release}]` newest first |
| GET `/block-types` | signed in | | 200 `[{type_id, title, contract_version, options_schema, default_options}]` |
| GET `/p/{slug}/choices?block_type=&system_id=` | viewer | | 200 `{option_name: [{value, label}]}` |
| GET `/p/{slug}/layouts` | viewer | | 200 list (R4.2.1 fields) |
| POST `/p/{slug}/layouts` | editor | `{name, description?, system_id?, template_id?, blocks?}` | 201 layout |
| GET `/p/{slug}/layouts/{id}` | viewer | | 200 `{id, name, description, system_id, revision, blocks:[{instance_id, block_type, options}]}` |
| PUT `/p/{slug}/layouts/{id}` | editor | `{name, description, system_id, revision, blocks, reset_invalid?}` | 200 layout with new revision |
| DELETE `/p/{slug}/layouts/{id}` | editor | | 204 |
| POST `/p/{slug}/layouts/{id}/validate` | viewer | | 200 `{valid, problems:[{instance_id, code, pointer, message}]}` |
| GET `/p/{slug}/layouts/{id}/preview` | viewer | | 200 `text/html` |
| POST `/p/{slug}/layouts/{id}/reports` | editor | `{}` | 201 `{id, status, block_statuses}` |
| GET `/p/{slug}/layouts/{id}/reports` | viewer | | 200 list `{id, layout_revision, status, created_at, created_by, size_bytes}` |
| GET `/p/{slug}/reports/{rid}/pdf` | viewer | | 200 `application/pdf`, attachment |
| POST `/p/{slug}/layouts/{id}/template` | editor | `{name, description?, keep_text?}` | 201 template |
| GET `/templates` | signed in | | 200 `[{id, name, description, block_types}]` |
| DELETE `/templates/{tid}` | creator or admin | | 204 |

R4.3.1 Errors have the body `{"error": {"code", "message", "details": []}}`. Codes: 401 `not_signed_in`,
404 `not_found`, 403 `forbidden`, 409 `stale_revision` / `generation_running`, 422 validation codes of
section 3, 502 `renderer_unavailable`, 504 `renderer_timeout`.
R4.3.2 When a layout id or report id exists but belongs to another project than `{slug}`, then 404
`not_found` (identical to a missing id).
R4.3.3 When a generation is already running for the layout, then POST reports returns 409 `generation_running`.
R4.3.4 The PDF filename is `{project slug}-v{number}-{layout name slugified}-{YYYYMMDD-HHMM}.pdf`.
R4.3.5 When the renderer returns a report with some blocks in `error`, then the report is stored with
`status=partial` and is downloadable; when the renderer itself fails, then `status=failed`, no PDF, and the
error ref is shown.

### 4.4 Auth and rights
R4.4.1 The caller is taken from the gateway headers with the shared `aisc_identity` helper
(`caller_from_headers`), as in control-objectives. When the headers are missing, then 401.
R4.4.2 The role is read from `core.project_member` for (project pid, subject) on every request, never cached
beyond the request.
R4.4.3 When the caller is not a member, then every `/p/{slug}/...` route answers 404 (not 403), so project
names are not confirmed.
R4.4.4 When a viewer calls a route marked editor, then 403 `forbidden`. When the membership lookup fails,
then 503 (fail closed).
R4.4.5 DEFAULT (user to confirm): the realm role `admin` gets viewer rights on every project and may delete
templates, but may not edit layouts of projects it is not a member of.
R4.4.6 State-changing routes (POST, PUT, DELETE) require a same-origin request (Origin header matching the
platform host), else 403.

## 5. Renderer (`aisc-report-generator`)

### 5.1 Rendering a layout
R5.1.1 The renderer receives a layout snapshot `{project_id, system_id, layout: {id, name, revision},
blocks: [{instance_id, block_type, options}], mode, requested_by}` and renders blocks strictly in list order.
R5.1.2 When `system_id` does not belong to `project_id`, then it refuses with 404 before reading any data.
R5.1.3 The output HTML is one document: shared stylesheet, a header/footer with project, version and page
numbers (PDF), the cover if present, then the sections. DEFAULT (user to confirm): an automatic table of
contents after the cover when the layout has more than 3 blocks.
R5.1.4 When `mode=preview`, then the result is the HTML; when `mode=pdf`, then the same HTML is converted
to PDF with WeasyPrint. Preview and PDF differ only in page features (page breaks, running header).
R5.1.5 Images (chart PNGs, logo) are embedded as `data:` URIs. The WeasyPrint URL fetcher only allows
`data:` URIs and the renderer's bundled resources; every other URL (http, file) is refused.
R5.1.6 When newer versions of the system exist, then the document carries the banner of R2.1.3 at the top
even without a cover block.
R5.1.7 The response includes `block_statuses: [{instance_id, block_type, status, notices}]`.

### 5.2 Block-renderer plugin contract (in `aisc-report-plugin-interface`)
R5.2.1 The interface package provides `BaseBlockRenderer` with the attributes of R1.1 and methods
`load(ctx, options) -> data` (reads only through `ctx.data`), `render(data, options, ctx) -> BlockResult`,
and optional `choices(ctx, option_name)`; templates are rendered with the existing `render_package_template`
machinery (autoescape on, relative template paths validated).
R5.2.2 The nine blocks of section 2 ship inside `aisc-report-generator` as built-in block renderers.
R5.2.3 Extra block renderers are discovered from installed packages (entry point group `aisc_report.blocks`)
and from the plugin directory (`REPORT_PLUGIN_PATH`) as today. When a plugin package fails to import,
then it is logged and skipped; the renderer still starts with the others.

### 5.3 Tool renderers (inside Test results)
R5.3.1 The interface provides `BaseToolRenderer`: `tool_name` (matched to the engine plugin name with the
existing normalisation: uppercase, spaces, dashes and underscores removed), `render(run, ctx) -> html`, and
optional `verdict(run) -> "pass" | "fail" | None` (used by R2.8.3).
R5.3.2 `run` is a read-only object with the evaluation, the evaluation_plugin, its component, its
observations, measurements (with metric names) and artifact metadata, all already filtered to the project
and version. Tool renderers get no database session. DEFAULT (user to confirm).
R5.3.3 When only a legacy `BaseReporterPlugin` subclass exists for a tool (named `{TOOL}ReportPlugin`, as
`MLAREJECTReportPlugin`), then an adapter calls its `generate_content(...)` with the same data and treats
the returned string as the tool section; legacy plugins keep working unchanged.
R5.3.4 When two renderers claim the same tool, then a `BaseToolRenderer` wins over a legacy plugin; two of
the same kind is a startup error (as R1.2).
R5.3.5 When the tool is unknown, then the generic renderer is used (R2.5.3).

### 5.4 Service interface (called only by the composer)
| method, path | request | response |
|---|---|---|
| GET `/health` | | 200 `{status, block_types, tool_renderers}` |
| GET `/v1/block-types` | | 200 as composer `/block-types` |
| POST `/v1/choices` | `{project_id, system_id, block_type}` | 200 `{option_name: [{value, label}]}` |
| POST `/v1/render` | snapshot of R5.1.1 with `mode` | preview: 200 `{html, block_statuses}`; pdf: 200 `{pdf_base64, sha256, block_statuses}` |

R5.4.1 When a request lacks the header `X-Report-Token` equal to `REPORT_SERVICE_TOKEN` (read from the
environment, compared in constant time), then 401. The renderer is not routed through Caddy.
R5.4.2 When the snapshot fails schema validation, then 422 with the same problem shape as R4.3 validate.
R5.4.3 The legacy `GET /generate?project_id=` route is removed. DEFAULT (user to confirm).
R5.4.4 The renderer holds no state between requests and writes no file outside a per-request temporary
directory, which is deleted when the request ends.

## 6. Data access (all read-only, scoped to project pid P and pinned system pid S)

R6.1 The renderer connects with a dedicated read-only role `report_ro`: SELECT on the tables below, no other
privilege; the Superset metadata database only for `aisc_comment` and dashboard/chart ownership; each
project's controls database for schema `controls`. When any write is attempted, then the database refuses it.
R6.2 Every data access function takes (P, S) as its first arguments and every query filters on them; there is
no function that reads without a project. When S is not a `core.system` row of P, then it raises `NotInProject`.

| block | source and query shape |
|---|---|
| cover | `core.project` where pid = P; `core.system` where pid = S and project_id = P; newer: `core.system` where project_id = P and number > S.number |
| ai_card | `qualification.qualification` where project_id = P and system_id = S; its `card_component`, `knowledge_graph` |
| risk_classification | same qualification row; `qualification_risk` by qualification id; `knowledge_graph.jsonld` parsed as JSON-LD |
| control_objectives | `control_objectives.project` where project_id = P and system_id = S; its `risk`, `mapped_objective`, latest `mapping_run`; labels from the objectives CSV |
| test_results | engine `project` where project_id = P; `evaluation` of it where system_id = S; `evaluation_plugin`, `evaluation_input`, `ai_component`, `observation`, `measurement`, `metric`, `artifact` joined from those evaluations |
| control_answers | controls database of P (named by the platform's `controls_database_name(slug)`); `checklist`, `checklist_question`, `submission`, `submission_answer` where system_version_pid = S; `source` |
| dashboard_chart | Superset API: chart metadata and image of the chart id, as a service account limited to P's role; Superset DB: `aisc_comment` where chart_id = C and dashboard_id in P's dashboards |
| summary_coverage | the objective set of control_objectives, evaluation counts of test_results, answers of control_answers, all as above |
| free_text | none |

R6.3 "Newer data" for R1.9 means rows in the same source, same project, stamped with a `core.system` pid of P
whose `number` is greater than S's.
R6.4 When the controls database of P does not exist, then control_answers is `empty`, not `error`.
R6.5 The renderer never reads the Catalogue (`catalogue` schema or service).

## 7. Non-functional

### 7.1 Errors
R7.1.1 When a source database is unreachable, then only the blocks that read it are `error`; the report
completes. When the `platform` database is unreachable, then the render fails with 503.
R7.1.2 Every error shown to a user carries an `error_ref` also present in the service log; logs never contain
free text bodies, answers or comment bodies (ids and counts only).

### 7.2 Performance limits (modest)
R7.2.1 When a layout of 20 blocks with a fake Superset is previewed on the test dataset, then the HTML
returns within 10 seconds.
R7.2.2 When a PDF is generated for such a layout, then it completes within 60 seconds; the composer's call to
the renderer times out at 120 seconds (504 `renderer_timeout`, report `failed`).
R7.2.3 A Test results block renders at most 500 measurements per tool section in the generic renderer and
then shows "and {k} more"; a Control answers block at most 1000 answers.
R7.2.4 Each chart image request times out at 30 seconds, no retry; chart blocks are fetched at most 3 at a time.
R7.2.5 When a generated PDF would exceed 25 MB, then it is not stored and the report is `failed` with
code `pdf_too_large`.
R7.2.6 Generation runs synchronously within the POST request. DEFAULT (user to confirm): no job queue.

### 7.3 Security
R7.3.1 When a caller of project A requests any id (layout, report, template-derived layout, evaluation pid,
chart id, checklist id) of project B, then the answer is 404 and no data of B is read.
R7.3.2 When a user of project A creates a layout from a template made in project B, then no data of B is
copied (R3.14).
R7.3.3 The composer never reads module schemas directly; only the renderer reads them, through `report_ro`.
R7.3.4 Preview HTML is served with `Content-Security-Policy: default-src 'none'; img-src data:; style-src
'unsafe-inline'` and shown in an iframe with `sandbox` (no scripts).
R7.3.5 `REPORT_SERVICE_TOKEN` and database passwords come from environment variables; they never appear in
responses, logs or generated documents.
R7.3.6 The composer and renderer never change frozen data (engine models, AIRO files, qualification's
`knowledge_graph` and `qualification_risk`); they only read them.

### 7.4 Testing hooks
R7.4.1 Superset, the renderer (from the composer's side) and the clock are injectable, so every rule above
can be tested against a throwaway postgres with fixed data and no live service.

## 8. Out of scope

- The Catalogue module (tools and controls registry): the report neither reads nor links to it.
- Editing any source data from the report (answers, comments, cards, results): the report only reads.
- Layout revision history, diffing and restore (only the per-report snapshot is kept, R3.12).
- Scheduled or emailed reports, sharing links outside the platform, public access.
- Formats other than HTML preview and PDF (no DOCX, no Markdown export).
- Rich text or HTML in Free text; custom per-project styling or branding beyond the existing logo.
- Changes to the engine data model, AIRO/VAIR files, qualification's frozen tables, and Sean's files listed
  as frozen in RULES.md.
- Automatic derivation of objective coverage links (R2.8.2) from any registry.
- Background job queue, parallel generation across layouts beyond what R4.3.3 allows.
- Pushing to any remote or creating repositories.
