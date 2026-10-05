# Report composer

The report composer is step 6 of AISC, the AI Assessment Sandbox Configurator (steps: 1 qualification,
2 control objectives, 3 install plugins and tools, 4 execute tests and address controls, 5 analyse
results on the dashboard, 6 compose the report). It assembles an assessment report of one project from
**modules** (blocks), saves their order and a template as a **layout**, previews it as HTML and
generates the PDF or Word document (a Word report also gets its PDF, rendered in the same generation, so
every report has Download PDF). A layout holds no data: the AI card version, the period of test
runs, whether runs of other versions are included and the version "Changes since" compares with are
chosen when a report is generated, and recorded on it. Five built-in layouts (Summary, Management
overview, Assessment report, EU AI Act conformity, Technical dossier) are shared by every project,
read-only: open one to inspect it, duplicate it to adapt it. A layout moves between projects as a file
(Export, Import).

## How it works

- A FastAPI service (`report_composer/app.py`, port 8095) behind the platform's gateway (Caddy,
  oauth2-proxy, Keycloak) at `/report-composer/`. Caddy strips the prefix.
- The renderer (`apps/report-generator`, compose service `report-renderer`) owns the block types and
  draws every module: the composer sends it a snapshot (the layout, the chosen version and period, the
  template, the coverage links) and stores what comes back. The composer never reads a module's data
  itself.
- Rights come from the platform's project roles (`core.project_member`), read on every request:
  viewers read and preview, editors and owners change layouts and templates and generate reports; an
  account with the realm role `admin` reads every project. Writes must come from the platform's origin
  (`PLATFORM_ORIGIN`).
- Coverage: which tests and controls give evidence for each control objective is set once per project
  on the platform's Collect evidence page (step 4), in `evidence.link` of the project's database. Every
  preview and report snapshot carries those links as `coverage_links`, so a generated report keeps the
  links it was made with.
- With the ledger on (`LEDGER_MODE`), every change and generation writes an event through the project
  database's `ledger.emit`, and a generated report prints the ledger anchor it was made at.

### Screens

The screens are drawn in Python (`report_composer/pages.py`, `templates/`); the only script is
`static/composer.js`, which collects the form values and calls the API.

- `/p/{slug}/`: the layouts, built-in ones first; New layout and Import from file in the header;
  Open, Duplicate and Export on each row
- `/p/{slug}/layouts/{id}` (and `/layouts/new`, `/layouts/builtin-<slug>` read-only): the editor
  (name, template, index, numbering, the grouped module palette, order, per-module options, Save,
  Generate report, Delete) with the preview beside it, drawn with a version and period chosen in the
  preview pane and never saved
- `/p/{slug}/layouts/{id}/generate`: the Generate report form (version, period, other versions,
  compare with, PDF or Word), handled in Python
- `/p/{slug}/templates`: the templates (a report's look), one editor

### API (under `/api`)

| route | right |
|---|---|
| `GET /p/{ref}/systems` | viewer |
| `GET /block-types`, `GET /fonts` | signed in |
| `GET /p/{ref}/choices?block_type=&system_id=` | viewer |
| `GET, POST /p/{ref}/layouts` (POST: `{name, blocks?, template_id?, show_index?, numbering?, file?}`) | viewer, editor |
| `GET, PUT, DELETE /p/{ref}/layouts/{id}` | viewer, editor, editor |
| `GET /p/{ref}/deleted-layouts` (deleted layouts that still have reports) | viewer |
| `POST /p/{ref}/layouts/{id}/validate` | viewer |
| `POST /p/{ref}/layouts/{id}/outline` (numbers and hints for the editor's current order) | editor |
| `GET, POST /p/{ref}/layouts/{id}/preview` (the version and period: query or `preview_with`) | viewer, editor |
| `POST /p/{ref}/layouts/{id}/duplicate` (also of a `builtin-<slug>` id) | editor |
| `GET /p/{ref}/layouts/{id}/export` | viewer |
| `GET /p/{ref}/builtin-layouts`, `GET .../{id}`, `.../{id}/preview`, `.../{id}/export` | viewer |
| `GET, POST /p/{ref}/layouts/{id}/reports` (POST: `{system_id, period_from?, period_to?, other_versions?, compare_to?, format?}`) | viewer, editor |
| `GET /p/{ref}/reports/{rid}/pdf` (the PDF; a Word report's copy), `/download` (the document as generated) | viewer |
| `GET, POST /p/{ref}/templates`, `PUT, DELETE .../{tid}`, `POST .../import`, `GET .../{tid}/export`, `.../{tid}/logo` | viewer, editor |

A period is two dates, both included, in UTC. `{ref}` is the project's slug or pid. Errors are
`{"error": {"code", "message", "details"}}`.

### Storage

One database per project. A project's layouts (with every saved revision), templates and generated
reports are tables of schema `report_composer` in that project's own database `project_<pid without
hyphens>`. The schema is made by the platform's project template
(`platform/project-template/0010_report_composer.sql`), the tables by `migrations/project/` (tracked
in `report_composer.schema_migration` of each project database). A layout's or report's version names
a row of that database's `project.system`. A deleted layout is hidden, and its reports stay.

On the `platform` database the composer reads `core.project` and `core.project_member`, and migrates
schema `report_library` (owned by `report_composer_rw`, made by the init files) from
`migrations/library/` (tracked in `report_library.schema_migration`). That install-wide preset
library is not used by any route.

## Install and run

### Inside the AISC stack (the usual way)

The composer is three compose services of `docker-compose.development.yml`: `report-composer` (the
app), `report-composer-migrate` (a one-shot that migrates the library and every project database
before the app starts) and `report-renderer`. From the aisc repository root, once:

```bash
./scripts/secrets.sh
```

then bring up the whole stack:

```bash
docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml \
  -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build
```

Open a project on http://localhost:8100 and its "Compose the report" card, or
http://localhost/report-composer/.

Migrations run in `python -m report_composer.migrate` (the library, then every project database),
again at the app's start, and on the first open of a project database made later, under advisory lock
8_190_233_707 in each database. Its exit status: 0 done, 1 the platform database is not reachable yet
(the compose loop retries), 2 a missing setting or a failed database (permanent).

### Standalone, for development

Prerequisites: Python 3.12 and [uv](https://docs.astral.sh/uv/). The service needs a PostgreSQL that
has the platform's `core` schema and the project databases, and a running renderer, so in practice it
runs against the stack. `aisc_identity` is not installed: it is read from `../../shared/identity`.

```bash
cd apps/report-composer
uv sync --extra dev
REPORT_COMPOSER_DATABASE_URL=... REPORT_COMPOSER_PROJECT_DATABASE_URL=... \
REPORT_RENDERER_URL=... REPORT_SERVICE_TOKEN=... \
PYTHONPATH=.:../../shared/identity \
uv run uvicorn report_composer.app:app --host 127.0.0.1 --port 8095 --proxy-headers
```

## Configuration

| variable | meaning | default in the code | value in the stack |
|---|---|---|---|
| `REPORT_COMPOSER_DATABASE_URL` | the `platform` database as `report_composer_rw` (membership and the preset library) | none, required | `postgresql://report_composer_rw:...@postgres:5432/platform` |
| `REPORT_COMPOSER_PROJECT_DATABASE_URL` | the same kind of DSN with `{database}` in place of the name, for each project's database | none, required | `...@postgres:5432/{database}` |
| `REPORT_RENDERER_URL` | the renderer | `http://report-renderer:8001` | same |
| `REPORT_SERVICE_TOKEN` | the token shared with the renderer | empty | from `env.secrets` |
| `REPORT_COMPOSER_ROOT_PATH` | the prefix Caddy strips | empty | `/report-composer` |
| `PLATFORM_ORIGIN` | the origin writes must come from | `http://localhost` | same |
| `LAUNCHER_URL` | where `/`, the header's mark and Back send the browser | `http://localhost:8100/` | same |
| `PLATFORM_URL` | the platform, asked for a report's ledger anchor | empty (no anchor) | `http://platform:8000` |
| `LEDGER_MODE` | `off`, `record` or `enforce`; events are written only when not `off` | `off` | `off` |
| `AUTH_ENABLED` | verify the caller's token (`aisc_identity`) | `true` | `true` |
| `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL` | the realm the token is checked against | empty | the `aisc` realm |
| `AUTH_DEV_ROLES` | realm roles of the fake identity used when `AUTH_ENABLED` is off | empty | unset |

The passwords come from `env.secrets` (`REPORT_COMPOSER_PASSWORD`, `REPORT_SERVICE_TOKEN`), made by
`scripts/secrets.sh`.

## Tests

From `apps/report-composer`:

```bash
uv run --extra dev pytest -q
```

- The database tests (marker `db`) start a throwaway `postgres:15-alpine` container (`aisc-t-*`) on a
  free port through `scripts/lib/report_bed.py` and `report_bed_isolated.py`, and remove it
  afterwards. They need Docker. They refuse to run when a DSN variable they read points anywhere else:
  **never point them at the live database** (port 5432 of the running stack).
- The browser tests (`test_*_browser.py`) drive the system Chrome through Playwright; no browser is
  downloaded.
- The end-to-end tests (marker `e2e`) start the real renderer in a subprocess on a free port.
  `tests/test_e2e_v2.py` takes it from the `apps/report-generator` submodule; `tests/test_e2e.py` looks
  for a checkout named `aisc-report-generator` beside the aisc repository. Set
  `REPORT_GENERATOR_DIR` to the renderer's directory to choose it for both, for example
  `REPORT_GENERATOR_DIR=$PWD/../report-generator`.
- To leave out the tests marked `db` and `e2e`: `uv run --extra dev pytest -q -m "not db and not e2e"`.

## Layout

- `report_composer/`: the app. `api.py` and `pages.py` (the routes), `guards.py` and `access.py`
  (who may do what), `db.py` and `projectdb.py` (SQL and the per-project connections), `layouts.py`,
  `presets.py`, `prose.py` and `forms.py` (layout rules, layout files, the configure forms),
  `reports.py` and `renderer_client.py` (snapshots and the renderer), `ledger.py` and `anchor.py`,
  `migrate.py`; `presets/` holds the built-in layouts, `templates/` and `static/` the screens.
- `migrations/project/`, `migrations/library/`: the two migration histories.
- `pre_isolation_migrations/`: the migrations of the shared schema used before each project had its
  own database, kept for the platform's data move; the image does not ship them.
- `tests/`: the test suite.

## Contributing

Work on the branch `feat/unified-modules` of the aisc repository (the only branch). A change to the
tables goes in a new file of `migrations/project/` (or `migrations/library/`): applied files are
recorded by name and never run again.
