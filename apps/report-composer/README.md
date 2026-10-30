# Report composer

The report composer is the Report of step 4 Collect evidence in AISC, the AI Assessment Sandbox Configurator
(steps: 1 Qualify the AI system, 2 Set control objectives, 3 Choose tests and checklists, 4 Collect evidence).
It runs as the compose service `report-composer`, with `report-composer-migrate` (its database migrations) and
`report-renderer` (which draws the documents, `apps/report-generator`).

You assemble a report from **blocks**, save their order and a look (a template) as a **layout**, preview it as
HTML, and generate a PDF or Word document for one AI card version. A Word report also gets a PDF copy when the
renderer can make one. A layout holds no data: the AI card version, the period of test runs, whether runs of
other versions are included and the version "Changes since" compares with are chosen when a report is generated,
and recorded on it. Five built-in layouts (Summary, Management overview, Assessment report, EU AI Act
conformity, Technical dossier) are shared by every project and read-only: open one to inspect it, duplicate it
to change it. A layout moves between projects as a file (Export, Import).

[How AISC works](../../docs/architecture.md) gives the whole picture; [Appendix 4: Collect
evidence](../../docs/appendices/4-collect-evidence.md) describes the Report from the user's side.

## How it works

- A FastAPI service (`report_composer/app.py`, port 8095) behind the AISC gateway (Caddy, oauth2-proxy,
  Keycloak) at `/report-composer/`. Caddy strips the prefix.
- The renderer owns the block types and draws every block. To preview or generate, the composer sends the
  renderer a **request** (the code calls it the snapshot, version 3): the layout and its blocks, the AI card
  version and the selection (period, other versions, compare with), the coverage links, the charts each test
  plugin declares, and the template's style. The renderer reads the project's data itself, read-only, as the
  database role `report_ro`. The composer never reads a block's data.
- A generated report is stored with its document, the document's checksum and the request it was made from,
  so it records the layout, selection, links and charts it was drawn with.
- The block palette is grouped: AI card, Control objectives and checklists, Tests run, Results, Summary,
  Document, and Other for block types a report plugin adds (`report_composer/groups.py`).
- Coverage: which tests and checklists are the evidence for each control objective is set per AI card version
  on the platform's Evidence map (step 4), in `evidence.link` of the project's database. The composer reads
  those links and sends them as `coverage_links` (`report_composer/evidence_links.py`).
- Declared charts: for a layout with a Test results block, the composer asks the platform
  (`GET /projects/{slug}/declared-charts`, as the person who asks) for the charts each test plugin declares.
  With no answer, Test results draws the tool's own section or the generic table.
- Rights come from the platform's project roles (`core.project_member`), read on every request through
  `aisc_identity.access` (the rule every service shares): viewers read and preview, editors and owners change
  layouts and templates and generate reports, and an account with the realm role `admin` is owner of every
  project. Writes must come from `PLATFORM_ORIGIN`.
- The ledger: with `LEDGER_MODE` not `off`, every change, generation and download writes an event through the
  project database's `ledger.emit`, and a generated report prints the ledger anchor it was made at. An event
  cites the gateway's `X-AISC-Request-Id` only when the request also carries a gateway token that verifies
  (`aisc_identity.gateway`); a caller reaching the service directly cannot make an event cite a request it
  names. With `AUTH_ENABLED` off the id is kept.

### Screens

The screens are drawn in Python (`report_composer/pages.py`, `templates/`); the only script is
`static/composer.js`, which collects the form values and calls the API.

- `/p/{ref}/`: the layouts, built-in ones first; New layout and Import from file in the header; Open,
  Duplicate and Export on each row.
- `/p/{ref}/layouts/{id}` (and `/layouts/new`, `/layouts/builtin-<slug>` read-only): the editor (name,
  template, index, numbering, the grouped block palette, order, per-block options, Save, Generate report,
  Delete) with the preview beside it, drawn with a version and period chosen in the preview pane and never
  saved.
- `/p/{ref}/layouts/{id}/generate`: the Generate report form (version, period, other versions, compare with,
  PDF or Word), handled in Python.
- `/p/{ref}/templates`: the templates (a report's look), one editor.
- `/`: sends the browser to the launcher (`LAUNCHER_URL`).

## Run it

### Inside the AISC stack (the usual way)

From the aisc folder:

```bash
uv run scripts/aisc.py start
```

This brings up the whole stack, the three services above included. To run Compose by hand instead,
`uv run scripts/aisc.py secrets` prints the exact command for this install (an install served over https needs
one more compose file than the others).

Open a project on http://localhost:8100, then 4. Collect evidence and its **Report** heading, or go to
http://localhost/report-composer/p/<project pid>.

Migrations run in `python -m report_composer.migrate` (every project database, in the one-shot
`report-composer-migrate`), again at the app's start, and on the first open of a project database made later,
under advisory lock 8_190_233_707 in each database. Its exit status: 0 done, 1 the platform database is not
reachable yet (the compose loop retries), 2 a missing setting or a failed database (permanent).

### Standalone, for development

Prerequisites: Python 3.12 and [uv](https://docs.astral.sh/uv/). The service needs a PostgreSQL that has the
platform's `core` schema and the project databases, and a running renderer, so in practice it runs against the
stack. `aisc_identity` is not installed: it is read from `../../shared/identity`.

```bash
cd apps/report-composer
uv sync --extra dev
REPORT_COMPOSER_DATABASE_URL=... REPORT_COMPOSER_PROJECT_DATABASE_URL=... \
REPORT_RENDERER_URL=... REPORT_SERVICE_TOKEN=... \
PYTHONPATH=.:../../shared/identity \
uv run uvicorn report_composer.app:app --host 127.0.0.1 --port 8095 --proxy-headers
```

## Reference

### Settings

| variable | meaning | default in the code | value in the stack |
|---|---|---|---|
| `REPORT_COMPOSER_DATABASE_URL` | the `platform` database as `report_composer_rw` (membership) | none, required | `postgresql://report_composer_rw:...@postgres:5432/platform` |
| `REPORT_COMPOSER_PROJECT_DATABASE_URL` | the same kind of DSN with `{database}` in place of the name, for each project's database | none, required | `...@postgres:5432/{database}` |
| `REPORT_RENDERER_URL` | the renderer | `http://report-renderer:8001` | same |
| `REPORT_SERVICE_TOKEN` | the token shared with the renderer | empty | from `env.secrets` |
| `REPORT_COMPOSER_ROOT_PATH` | the prefix Caddy strips | empty | `/report-composer` |
| `PLATFORM_ORIGIN` | the origin writes must come from | `http://localhost` | the engine's address (`API_URL_EXTERNAL`, `http://localhost` by default) |
| `LAUNCHER_URL` | where `/`, the header's mark and Back send the browser | `http://localhost:8100/` | same |
| `PLATFORM_URL` | the platform, asked for a report's ledger anchor and for the declared charts | empty (no anchor, no declared charts) | `http://platform:8000` |
| `LEDGER_MODE` | `off`, `record` or `enforce`; events are written only when not `off` | `off` | `record` |
| `AUTH_ENABLED` | verify the caller's token (`aisc_identity`) | `true` | `true` |
| `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL` | the realm the token is checked against | empty | the `aisc` realm |
| `AISC_GATEWAY_CLIENT_ID` | the gateway's client, whose token lets an event cite `X-AISC-Request-Id` | `aisc-gateway` | unset (the default) |
| `AUTH_DEV_ROLES` | realm roles of the fake identity used when `AUTH_ENABLED` is off | empty | unset |

The passwords come from `env.secrets` (`REPORT_COMPOSER_PASSWORD`, `REPORT_SERVICE_TOKEN`), made by
`scripts/secrets.sh`.

### API (under `/api`)

| route | right |
|---|---|
| `GET /p/{ref}/systems` (the project's AI card versions) | viewer |
| `GET /p/{ref}/choices?block_type=&system_id=` (what a block may pick from on one version) | viewer |
| `GET /p/{ref}/layouts` (the project's layouts and the built-in ones), `GET /p/{ref}/deleted-layouts` | viewer |
| `POST /p/{ref}/layouts/{id}/validate` (the layout's problems, checked by the renderer) | viewer |
| `POST, GET /p/{ref}/layouts/{id}/reports` (generate a report; the layout's reports) | editor, viewer |
| `GET /p/{ref}/templates` | viewer |
| `POST /p/{ref}/layouts` (`{name, blocks?, template_id?, show_index?, numbering?, file?}`) | editor |
| `GET, PUT, DELETE /p/{ref}/layouts/{id}` | viewer, editor, editor |
| `POST /p/{ref}/layouts/{id}/outline` (numbers and hints for the editor's current order) | editor |
| `GET, POST /p/{ref}/layouts/{id}/preview` (the version and period: query or `preview_with`) | viewer, editor |
| `POST /p/{ref}/layouts/{id}/duplicate` (also of a `builtin-<slug>` id) | editor |
| `GET /p/{ref}/layouts/{id}/export` | viewer |
| `GET /p/{ref}/builtin-layouts/{id}/preview`, `.../{id}/export` | viewer |
| `GET /p/{ref}/reports?system_id=` (how many reports a version has and the newest; the platform asks it for the Report tile) | viewer |
| `GET /p/{ref}/reports/{rid}/pdf` (the PDF; a Word report's copy), `/download` (the document as generated) | viewer |
| `POST /p/{ref}/templates`, `PUT, DELETE .../{tid}`, `POST .../import`, `GET .../{tid}/export`, `.../{tid}/logo` | editor, viewer for export and logo |

Reports are generated from the Generate report form (`POST /p/{ref}/layouts/{id}/generate` on the screens).
A period is two dates, both included, in UTC. `{ref}` is the project's slug or pid: a value shaped like a UUID
is looked up only as a pid, anything else only as a slug. Errors are `{"error": {"code", "message",
"details"}}`.

### Limits and refusals

- A template's logo is PNG, JPEG or SVG, at most 1 MiB, and is checked against the renderer's limits when the
  template is saved or imported: a PNG or JPEG must have a readable size in its header and at most 16,000,000
  pixels; an SVG must declare a usable size (width and height, the viewBox's for a side it does not give, as
  cairosvg reads it) and stay under the same cap drawn at twice that size, as the Word export draws it, and must
  hold no `<image>`, `<feImage>`, `href` or `xlink:href` (an embedded raster is decoded in full whatever size the
  SVG declares). Otherwise 422 `invalid_template` on `/logo/data_base64`.
- Text with a lone surrogate (an unpaired UTF-16 half) in a layout or a template is 422 (`invalid_request` for
  layouts, `invalid_template` for templates) with a pointer to the field.
- A period cannot end on 9999-12-31: 422 `invalid_request` on `/period_to`.
- A layout deleted while it is being saved is 404 `not_found`; a template deleted after it was chosen and before
  the layout is written is 422 `template_not_in_project`.
- The renderer's own limits reach the person as such: a request over its size cap is 413 `report_too_large`;
  all its render slots taken is 503 `renderer_busy` (nothing was rendered, try again shortly); a refusal of the
  request at generation is 422 `invalid_snapshot` with the renderer's problems; an answer that is not JSON is
  502 `renderer_unavailable`, as when it is down (a late one is 504 `renderer_timeout`). A generation that fails
  so is recorded as a failed report with the same code.
- A Word report whose PDF copy cannot be rendered is kept without it; its `/pdf` answers 404.
- Every database connection gives up after 10 s (`db.CONNECT_TIMEOUT_S`, `migrate.CONNECT_TIMEOUT_S`) instead of
  waiting on a server that accepts and never answers: a request then answers 503 `unavailable`, and the migrate
  one-shot exits 1 (platform not reachable yet) or 2.

### Data it keeps

One database per project. A project's layouts (with every saved revision), templates and generated reports
(document, checksum, the request sent to the renderer) are tables of schema `report_composer` in that project's
own database `project_<pid without hyphens>`. The schema is made by the platform's project template
(`platform/project-template/0010_report_composer.sql`), the tables by `migrations/project/` (tracked in
`report_composer.schema_migration` of each project database). A layout's or report's version names a row of
that database's `project.system`. A deleted layout is hidden, and its reports stay.

On the `platform` database the composer only reads `core.project` and `core.project_member`.

### Files

- `report_composer/`: the app.
  - `api.py`, `pages.py`: the routes; `guards.py`: who may do what, through `aisc_identity.access`.
  - `db.py`, `projectdb.py`, `records.py`: SQL and the per-project connections.
  - `layouts.py`, `presets.py`, `builtin_layouts.py`, `groups.py`, `prose.py`, `forms.py`: layout rules, layout
    files, the built-in layouts, the palette's groups, the configure forms.
  - `reports.py`, `builtin_reports.py`, `selection.py`, `preview_with.py`, `settings.py`: the request sent to
    the renderer and the generation.
  - `renderer_client.py`, `renderer_calls.py`: the calls to the renderer.
  - `evidence_links.py`, `declared_charts.py`: the coverage links and the declared charts the request carries.
  - `templates.py`: a report's look; `ledger.py`, `anchor.py`: ledger events and the report's anchor;
    `migrate.py`: the migrations.
  - `presets/`: the built-in layouts; `templates/` and `static/`: the screens.
- `migrations/project/`: the migration history of each project database.
- `tests/`: the test suite.

## Tests

From `apps/report-composer`:

```bash
uv run --extra dev pytest -q
```

- The database tests (marker `db`) start a throwaway `postgres:15-alpine` container (`aisc-t-*`) on a free port
  through `scripts/lib/report_bed.py` and `report_bed_isolated.py`, and remove it afterwards. They need Docker.
  They refuse to run when a DSN variable they read points anywhere else: **never point them at the live
  database** (port 5432 of the running stack).
- The browser tests (`test_*_browser.py`) drive the system Chrome through Playwright; no browser is downloaded.
- The end-to-end tests (marker `e2e`) start the real renderer in a subprocess on a free port. Both
  `tests/test_e2e.py` and `tests/test_e2e_v2.py` take it from the `apps/report-generator` submodule, or from
  `REPORT_GENERATOR_DIR` when it is set, and skip without it.
- To leave out the tests marked `db` and `e2e`: `uv run --extra dev pytest -q -m "not db and not e2e"`.

## Contributing

Work on the branch `pilot` of the aisc repository (the only branch). A change to the tables goes
in a new file of `migrations/project/`: applied files are recorded by name and never run again.
