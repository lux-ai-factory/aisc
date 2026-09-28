# Report composer (step 7)

Assembles an assessment report of one project from **modules** (blocks), saves their order and a
template as a **layout**, previews it as HTML and generates the PDF or Word document. A layout holds
no data: the AI card version, the period of test runs, whether runs of other versions are included and
the version Changes since compares with are chosen when a report is generated, and recorded on it
(report modules spec, `docs/superpowers/specs/2026-09-28-report-modules-design.md`). Five built-in
layouts (Summary, Management overview, Assessment report, EU AI Act conformity, Technical dossier) are
shared by every project, read-only: open one to inspect it, duplicate it to adapt it. A layout moves
between projects as a file (Export, Import). The renderer (`aisc-report-generator`, service
`report-renderer`) draws the modules; the composer never reads a module's data itself.

Behind the platform's sign-in (Caddy, oauth2-proxy, Keycloak) at `/report-composer/`. Rights come
from the platform's project roles, read on every request: viewers read and preview, editors and
owners change layouts and generate reports; a realm admin reads every project. Writes must come
from the platform's origin.

## Screens

- `/p/{slug}/`: the layouts, built-in ones first; New layout and Import from file in the header;
  Open, Duplicate and Export on each row
- `/p/{slug}/layouts/{id}` (and `/layouts/new`, `/layouts/builtin-<slug>` read-only): the editor
  (name, template, index, numbering, the grouped module palette, order, per-module options, Save,
  Generate report, Delete) with the preview beside it, drawn with a version and period chosen in the
  preview pane and never saved
- `/p/{slug}/layouts/{id}/generate`: the Generate report form (version, period, other versions,
  compare with, PDF or Word), handled in Python
- `/p/{slug}/templates`: the templates (a report's look), one editor

The screens are drawn in Python (`report_composer/pages.py`, `templates/`); the only script is
`static/composer.js`, which collects the form values and calls the API.

## API (under `/api`)

| route | right |
|---|---|
| `GET /p/{ref}/systems` | viewer |
| `GET /block-types` | signed in |
| `GET /p/{ref}/choices?block_type=&system_id=` | viewer |
| `GET, POST /p/{ref}/layouts` (POST: `{name, blocks?, template_id?, show_index?, numbering?, coverage?, file?}`) | viewer, editor |
| `GET, PUT, DELETE /p/{ref}/layouts/{id}` | viewer, editor, editor |
| `POST /p/{ref}/layouts/{id}/validate` | viewer |
| `GET, POST /p/{ref}/layouts/{id}/preview` (the version and period: query or `preview_with`) | viewer, editor |
| `POST /p/{ref}/layouts/{id}/duplicate` (also of a `builtin-<slug>` id) | editor |
| `GET /p/{ref}/layouts/{id}/export` | viewer |
| `GET /p/{ref}/builtin-layouts`, `GET .../{id}`, `.../{id}/preview`, `.../{id}/export` | viewer |
| `GET, POST /p/{ref}/layouts/{id}/reports` (POST: `{system_id, period_from?, period_to?, other_versions?, compare_to?, format?}`) | viewer, editor |
| `GET /p/{ref}/reports/{rid}/pdf`, `/download` | viewer |
| `GET, POST /p/{ref}/templates`, `PUT, DELETE .../{tid}`, `POST .../import`, `GET .../{tid}/export`, `.../{tid}/logo` | viewer, editor |

A period is two dates, both included, in UTC. `{ref}` is the project's slug or pid. Errors are `{"error": {"code", "message", "details"}}`.

## Storage

One database per project (isolation 2026-09-25). A project's layouts, templates and generated
reports are tables of schema `report_composer` in that project's own database `project_<pid without
hyphens>`; the schema is made by the platform's project template (`0010_report_composer.sql`), the
tables by `migrations/project/` (tracked in `report_composer.schema_migration` of each project
database), and a layout's or report's version names a row of that database's `project.system`.

Saved presets are the install-wide library: table `report_library.preset` of the `platform` database
(schema owned by `report_composer_rw`, made by the init files), from `migrations/library/` (tracked in
`report_library.schema_migration`). On `platform` the composer otherwise reads only `core.project` and
`core.project_member`.

Migrations run in the one-shot `python -m report_composer.migrate` (the library, then every project
database), again at start, and on the first open of a project database made later (advisory lock
8_190_233_707 in each database). The files the shared schema had before the isolation are kept in
`pre_isolation_migrations/` for the cutover; the image no longer ships them.

## Environment

| variable | meaning |
|---|---|
| `REPORT_COMPOSER_DATABASE_URL` | the platform database as `report_composer_rw` (membership and the preset library) |
| `REPORT_COMPOSER_PROJECT_DATABASE_URL` | the same kind of DSN with `{database}` in place of the name, for each project's database |
| `REPORT_RENDERER_URL` | the renderer, e.g. `http://report-renderer:8001` |
| `REPORT_SERVICE_TOKEN` | the token shared with the renderer |
| `REPORT_COMPOSER_ROOT_PATH` | the prefix Caddy strips (`/report-composer`) |
| `PLATFORM_ORIGIN` | the origin writes must come from (default `http://localhost`) |
| `LAUNCHER_URL` | where `/` sends the browser |
| `AUTH_ENABLED`, `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL` | sign-in checks (shared `aisc_identity`) |

## Tests

```
uv run --extra dev pytest -q
```

The database tests start a throwaway `postgres:14-alpine` container (`aisc-t-*`) through
`scripts/lib/report_bed.py` and remove it afterwards. `tests/test_e2e.py` also starts the real
renderer from `../../../aisc-report-generator` (or `REPORT_GENERATOR_DIR`) on a free port.
