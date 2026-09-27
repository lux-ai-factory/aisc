# Report composer (step 7)

Assembles an assessment report of one project from **blocks**, saves it as a **layout**, previews
it as HTML and generates the PDF. A layout is pinned to one system version: every block shows the
data of that version only. A layout can be saved as a **template** (without project data) and
reused by any project. The renderer (`aisc-report-generator`, service `report-renderer`) draws the
blocks; the composer never reads a module's data itself.

Behind the platform's sign-in (Caddy, oauth2-proxy, Keycloak) at `/report-composer/`. Rights come
from the platform's project roles, read on every request: viewers read and preview, editors and
owners change layouts and generate reports; a realm admin reads every project. Writes must come
from the platform's origin.

## Screens

- `/p/{slug}/`: the project's layouts (new layout, new from template, delete for editors)
- `/p/{slug}/layouts/{id}`: the editor (palette, order, per-block options, version, save,
  generate, save as template) with the preview beside it

The screens are drawn in Python (`report_composer/pages.py`, `templates/`); the only script is
`static/composer.js`, which collects the form values and calls the API.

## API (under `/api`)

| route | right |
|---|---|
| `GET /p/{ref}/systems` | viewer |
| `GET /block-types` | signed in |
| `GET /p/{ref}/choices?block_type=&system_id=` | viewer |
| `GET, POST /p/{ref}/layouts` | viewer, editor |
| `GET, PUT, DELETE /p/{ref}/layouts/{id}` | viewer, editor, editor |
| `POST /p/{ref}/layouts/{id}/validate` | viewer |
| `GET /p/{ref}/layouts/{id}/preview` | viewer |
| `GET, POST /p/{ref}/layouts/{id}/reports` | viewer, editor |
| `GET /p/{ref}/reports/{rid}/pdf` | viewer |
| `POST /p/{ref}/layouts/{id}/template` | editor |
| `GET /templates`, `DELETE /templates/{tid}` | signed in; the creator or an admin deletes |

`{ref}` is the project's slug or pid. Errors are `{"error": {"code", "message", "details"}}`.

## Storage

Schema `report_composer` of the `platform` database, owned by `report_composer_rw` (made by
`init/report-roles.sql`); tables from `migrations/`, applied at start.

## Environment

| variable | meaning |
|---|---|
| `REPORT_COMPOSER_DATABASE_URL` | the platform database as `report_composer_rw` |
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
