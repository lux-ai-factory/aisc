# Evidence links: objectives to tests and controls (plan, 2026-09-30)

Status: PLAN, decisions taken 2026-09-30. Nothing built.

## What the user asked

1. Step 4 "Collect evidence" becomes a page of the overall platform app (not a new app).
2. It lists the control objectives **selected** in step 2, and the tests (plugins) and controls
   (checklists) **selected** in step 3 from the catalogue.
3. On that page the user links each test and each control to one or more objectives (many to many).
4. The page has two buttons: "Execute tests" (engine) and "Address controls" (controls app).
5. New: step 2 gets a selection of control objectives. Only the selected ones reach step 4.

## Current state (running clone, aisc 66a8f1e)

| Piece | Where | Selection today |
|---|---|---|
| Objectives (step 2) | project DB schema `control_objectives`: `project` (one assessment per card version), `risk`, `mapped_objective` (risk_row_id, objective_id "R1.1"). Catalogue = bundled CSV, 50 rows. Tiers computed on read (`prioritising.py`). | **None.** No selected/excluded flag anywhere. |
| Tests (step 3) | catalogue installs through the engine: `engine.aisc_backend_plugin` (package_name, version, display_name, catalogue_slug, enabled). | Installed = selected (`enabled` is a soft switch). |
| Controls (step 3) | catalogue installs through `controls/api/install`: `controls.checklist` (id cuid, catalogueId slug or null). | Installed = selected. |
| Links | only the report composer: `report_composer.layout.coverage` JSONB per layout, copied into the snapshot as `coverage_links`, read by `report_renderer/coverage.py`. Tests matched by normalised name (`tool_keys`), checklists by cuid. | Hand-typed per layout. |
| Step 4 today | `homepage/project.html:447-469`: a card with two links (`/controls/p/<pid>`, `/?project=<pid>`). | n/a |
| Platform app | static pages in `homepage/` + FastAPI routes in `platform/platform_service/app.py`; per-project tables via SQL templates `platform/project-template/00NN_*.sql`, applied on create and on start (`projectdb.provision`). | n/a |

## Design

### A. Step 2: select objectives (apps/control-objectives)

- New table `control_objectives.selected_objective` (assessment_id FK `project.id` ON DELETE CASCADE,
  objective_id text matching `^R\d+\.\d+$`, selected_by, selected_at; unique per assessment+objective).
  Alembic revision in the service + grant SELECT to `report_ro`, `dashboard_ro`, and to the platform reader (D4).
- A selection belongs to one assessment, so to one card version, like the risks and the mapping.
- Page `project.html.j2`: a checkbox per objective in the Tier 1/2/3 sections, plus "Save selection".
  Endpoint `POST /p/{project}/api/projects/{id}/selection` (full list, replaces).
- Payload of `GET /p/{project}/api/projects/{id}` gains `selected: [objective_id]`.
- Default when nothing is saved yet: D1; on a new card version: D2.

### B. Step 4: the evidence page (platform)

- New template `platform/project-template/0016_evidence.sql`: schema `evidence`, table `evidence.link`
  (objective_id text, kind `test` | `control`, item_key text, created_by, created_at;
  unique (objective_id, kind, item_key)). Grant SELECT to `report_ro`, `dashboard_ro`.
- Item keys (so the report can match them):
  - test: plugin `package_name` (stable across reinstalls; `tool_keys` already answers to it);
  - control: checklist `id` (cuid; what the report already uses; locally created checklists have no slug).
- Routes in `app.py` (user auth, project membership as today):
  - `GET /projects/{slug}/evidence`: selected objectives (latest version), installed enabled plugins,
    installed checklists, current links; links whose objective, plugin or checklist is no longer
    selected come back flagged `stale`, not deleted.
  - `PUT /projects/{slug}/evidence/links`: full list, replaces (same style as the allowlist).
- Page `homepage/evidence.html?project=<pid>` (static + inline JS, like `connections.html`):
  a grid, objectives as rows, tests and controls as columns, a tick per cell; each objective shows how
  many items it has ("not covered" when zero). Top of the page: the two buttons, same URLs the step 4
  card uses now.
- `project.html` step 4 card: opens `evidence.html` instead of holding the two links.

### C. Report

- The renderer reads `evidence.link` (as `report_ro`) instead of the layout's coverage map; statuses
  in `coverage.py` stay the same. The composer's map is removed (D5).

## Decisions (user, 2026-09-30)

- **D1** Step 2 default: every objective the mapping linked to a risk starts ticked; the user can
  untick them and tick voluntary ones.
- **D2** A new card version copies the previous selection for objectives still mapped; newly mapped
  objectives start ticked (D1).
- **D3** Links belong to the project, not to a card version. Objectives not selected in the latest
  version keep their links, flagged stale.
- **D4** The platform reads `control_objectives`, `engine.aisc_backend_plugin` and `controls.checklist`
  directly in the project DB through a read-only grant (as the report does with `report_ro`).
- **D5** The composer's coverage map is removed. The report reads only `evidence.link`, copied into
  the snapshot when a report is issued (as `coverage_links` is today), so issued reports never change.
  Fallback to the `summary_coverage` block's `options.links` is removed too.
- **D6** Editors and owners can edit links; viewers see the page read-only.
- **D7** Stale items are shown, never hidden or dropped: a disabled plugin, a deleted checklist or an
  unselected objective appears greyed with its reason; no new links can be added to it; existing
  links stay. A stale plugin's past Done runs still count as evidence in the report.

ASSUMED (to confirm): the report's Control objectives and Summary blocks list the step 2 **selected**
objectives, not every mapped one.

## Build order (test-first, one step at a time)

1. control-objectives: table + migration + selection endpoint + checkboxes + payload (tests first).
2. platform: template 0016 + store module + routes (tests first against a project DB).
3. homepage: `evidence.html` + step 4 card change.
4. report-generator + report-composer: read `evidence.link`, remove the composer map and the block fallback (D5); goldens.
5. Live check on the MCAS project: select objectives, link LangBiTe and one checklist, render a report.

Nothing is pushed without naming the repos first.
