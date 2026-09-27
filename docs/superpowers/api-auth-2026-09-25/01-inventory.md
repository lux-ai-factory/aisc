# API authentication and authorization inventory (2026-09-25)

Read-only inventory of every HTTP service of the running `aisc` compose stack except the catalogue
(catalogue-backend, catalogue-frontend) and the engine (aisc-backend, aisc-webapp, aisc-eval-worker,
aisc-eval-flower). Method: source reading of this checkout plus the deployed copies where they differ,
`docker ps`, the Caddyfile, and GET-only probes with no token from inside `aisc-eval-worker` (the
container that runs third-party plugin code, so it is the realistic "anything on the backend network"
caller). No POST/PUT/DELETE was sent, nothing was restarted, nothing was written to any database
(sample ids were read with a read-only transaction).

Sample objects used by the probes, all of project `microcredit-assist-score-mcas`
(pid `01399e17-...ab22`): system version `1e722ea2-...`, qualification `cmue7pq23000mpv7zew2fghpg`,
control-objectives assessment `0a013fbcc79b`, report `8c051fd1-...`.

Threat model in one line: the `backend` network is not a trust boundary. aisc-eval-worker installs and
runs plugins from devpi, and any of that code can open a socket to every service below by name.

## 1. Summary

| Service (container:port) | Exposed via | Today's auth | Unauthenticated routes found | Live probe (no token, from eval-worker) |
|---|---|---|---|---|
| platform:8000 | Caddy launcher `:8100/api/*` (protect, prefix stripped); `/api/internal/*` answered 404 by Caddy | `aisc_identity` JWT per route (`caller_dependency` / `requires_role`), membership via `role_or_404`; internal route: per-system service token + refuses X-Forwarded-* | `/health`, `/docs`, `/openapi.json` only | 401 on every data route, 401 on internal route; 200 on docs/openapi |
| control-objectives:8090 | Caddy `:80/control-objectives*` (protect, prefix stripped) | `ProjectAccess` middleware, regex `^/p/` only; nothing on `/api/*` | ALL of `/api/*` (list, read, map, rate, delete assessments); ALL of `/p/*` via the `/control-objectives/p/...` prefix bypass | **200 with assessment data** on `/api/projects?project=<pid>`, `/api/projects/<id>`, `/control-objectives/api/projects/<id>`; **200 HTML** on `/control-objectives/p/<pid>/projects[/<id>]`; 401 on plain `/p/...` |
| qualification-web:3000 | Caddy `:80/qualification*` (protect) | Next middleware matcher `/p/:path*` asks platform `/authz`; `/api/qualifications/[id]/*` check the qualification's own project per route (`qualificationForCaller`) | none found without a token; see F6/F7 for authenticated gaps | 404 on all `/api/qualifications/<id>/*` (existing id), 503 on `/p/...` (platform answers 401, mapped to "unavailable"), 200 on `/methodology` |
| qualification-agents:8012 | not routed; backend network only | none | `POST /fill/{id}`, `GET /fill/{id}`, `/docs`, `/openapi.json` | 200 health/openapi, 404 `/fill/<id>` (no run in memory) |
| qualification-ontology:8011 | not routed | none | `GET /vocabularies`, `POST /build`, docs | 200 on all probed |
| qualification-prefill:8012 | not routed | none | `POST /prefill`, `POST /forms/import`, docs | 200 health/openapi |
| qualification-llm:4000 (LiteLLM wrapper) | not routed | none | `POST /generate` (caller picks any model), docs | 200 health/openapi; provider keys are currently empty in the container, so it cannot spend money today |
| qualification-pdf:8005 | not routed | none | `POST /render/html`, `POST /render/pdf`, docs | 200 health/openapi |
| controls-web:3000 | Caddy `:80/controls*` (protect) | Next middleware matcher `/p/:path*`; every action/route re-checks through `projectDbFor(pid)` with the caller's token; `/api/install` Origin check + caller token | none found | 307 root, 503 `/p/...`, 403 `/api/install` without Origin, 404 with a forged Origin (no project data, no token so no install possible) |
| controls-pdf:8005 | not routed | none | `POST /render/html`, `POST /render/pdf`, docs | 200 health/openapi |
| report-composer:8095 | Caddy `:80/report-composer*` (protect) | `signed_in` / `project_guard(right)` dependency on every API route and page, same-origin check on writes | none (only `/` redirect) | 401 on API and pages, 404 on `/openapi.json` (docs off) |
| report-renderer:8001 | not routed | global middleware, `X-Report-Token` shared secret, constant-time compare | none | 401 on everything incl. `/health` |
| devpi:3141 (aisc) | not routed; backend network only | devpi's own: `--restrict-modify root`, index `root/public` `acl_upload: [root]`, `volatile: True`; **root password is empty** | read is anonymous by design; upload effectively open (see F3) | 200 `/+api` (authstatus `noauth`), 200 index JSON showing `volatile: true`, `acl_upload: ['root']` |
| pgadmin:80 | Caddy `:8100/inspect/pgadmin*` (protect + admin_only) | Caddy only; pgAdmin in desktop mode (`SERVER_MODE=False`, no master password), pgpass for `inspector_ro` preloaded | the whole pgAdmin app on the backend network | **200** `/inspect/pgadmin/browser/` (full UI, no login) |
| schema-docs:8080 | Caddy `:8100/inspect/schema*` (protect + admin_only) | Caddy only; database name allowlist regex | the whole SchemaSpy site on the backend network | 204 `/health`, 404 for a non-allowlisted name (generation not triggered on purpose) |
| dashboard (Superset) host-net `172.17.0.1:8189` | Caddy `:8188` (protect) | `GatewayIdentity` WSGI middleware verifies `X-Auth-Request-Access-Token` and sets REMOTE_USER; `PUBLIC_ROLE_LIKE=None`; FAB password login unrouted; bridge `/api/v1/aisc_project/<pid>` needs `DASHBOARD_BRIDGE_TOKEN` (set, 64 chars) | `/health` only | 200 `/health`, 401 `/api/v1/*`, 302 to `/login/` for UI, 405 GET on bridge |
| oauth2-proxy host-net `0.0.0.0:4180` | Caddy forward_auth, `/oauth2/*` on every origin | its own cookie | `/ping` | 401 `/oauth2/auth`, 200 `/ping` |
| connectors (apps/connectors) | not in any compose file, not running | `admin_call` dependency on every `/api/v1/connectors` route | n/a | not probed (not running) |
| plugin-publisher | one-shot job, no HTTP server | n/a | n/a | n/a |

Host-published ports (docker ps): caddy `0.0.0.0:80,443 -> 8005`, `0.0.0.0:8100`, `0.0.0.0:8102`,
`0.0.0.0:8188`; keycloak `0.0.0.0:8081`; oauth2-proxy `0.0.0.0:4180` (host network); dashboard
`172.17.0.1:8189` (host network, docker bridge address); postgres, redis, rabbitmq, minio, immudb on
`127.0.0.1` only. None of the in-scope bridge-network services publishes a port. Outside the `aisc`
project, `catalogue-dev-*` publishes `0.0.0.0:8000`, `:3000` and its own devpi on `0.0.0.0:3141`
(a different devpi instance from `aisc`'s `devpi`; out of scope but worth knowing).

Deployment notes: qualification-web/-migrate/-agents were built from a scratchpad copy
(`deploy-override.yml` build context that no longer exists), so for qualification the compiled route
list in the container (`.next/server/app`, identical 8 routes) and the middleware manifest (matcher
`^/qualification/p/...`) were checked rather than assuming the checkout. report-renderer's deployed
`report_service.py` is older than `~/aisc-report-generator` (no `/v1/languages`, `/v1/coverage-choices`)
but has the same token middleware.

## 2. Per-service route tables

Legend: Auth = a verified identity (or service token) is required. Authz = membership/role or object
ownership is checked.

### 2.1 platform (platform/platform_service/app.py)

Callers: browser via Caddy `:8100/api/*` (launcher `homepage/index.html`, `project.html`, `llm.html`);
server-to-server from qualification-web, controls-web, control-objectives (caller's token), Caddy
forward_auth (`/authz/admin`), qualification-agents and control-objectives (internal route).

| Method | Path | Auth | Authz | Notes |
|---|---|---|---|---|
| GET | /health | no | no | |
| GET | /docs, /openapi.json | no | no | `docs_url="/docs"` app.py:43; route list disclosure only |
| GET | /projects | yes | yes | admin sees all, others their memberships (app.py:121) |
| GET | /projects/{slug} | yes | yes | `role_or_404` viewer |
| POST | /projects | yes | no (by design) | any signed-in user creates and owns a project (app.py:137) |
| DELETE | /projects/{slug} | yes | admin + typed name | app.py:170 |
| GET | /authz/projects/{slug} | yes | answers for strangers by design | used by the Next middlewares |
| GET | /authz/admin | yes | admin role | Caddy forward_auth for /inspect |
| GET | /projects/{slug}/members | yes | viewer | |
| POST/PUT/DELETE | /projects/{slug}/members[/{subject}] | yes | owner | last-owner guard |
| POST | /projects/{project}/system-versions | yes | editor | |
| GET | /projects/{project}/system-versions[/latest] | yes | viewer | |
| GET | /systems/{pid} | yes | yes, object's own project | app.py:299-310, the correct id-addressed pattern |
| GET | /projects/{slug}/llm | yes | admin | never returns a key |
| PUT/DELETE | /projects/{slug}/llm/providers/{provider} | yes | admin | |
| GET | /projects/{slug}/llm/providers/{provider}/models | yes | admin | live call with the stored key |
| PUT/DELETE | /projects/{slug}/llm/systems/{system} | yes | admin | |
| GET | /internal/projects/{pid}/llm/{system} | service token | token bound to one system | 404 if X-Forwarded-*; 503 if tokens unset or equal (app.py:564-615) |

### 2.2 control-objectives (apps/control-objectives/src/aisc_control_objectives)

Callers: browser via Caddy `:80/control-objectives*` (launcher project page links). Nothing calls it
server-to-server (grep for `control-objectives:8090` finds no caller).

Auth mechanism: `ProjectAccess` middleware (access.py:118-152) runs only when `request.url.path`
matches `^/p/([^/]+)` (access.py:38, 131-133). Nothing else is gated. FastAPI is created with
`root_path="/control-objectives"` (api/app.py:122), and Starlette routes a request whose path starts
with the root path by stripping it, while the middleware reads the unstripped path. So
`/control-objectives/p/<project>/...` reaches every `/p/` handler and the middleware does not fire.

| Method | Path | Auth | Authz | Notes |
|---|---|---|---|---|
| GET | / | no | no | redirect to launcher |
| GET | /static/{name} | no | no | path confined to STATIC |
| GET | /health, /openapi.json, /docs | no | no | |
| GET | /objectives | no | no | reference catalogue, same for everyone (intended) |
| GET | /api/config | no | no | discloses provider/model (`ollama`, `mistral:latest`) |
| GET | /api/control-objectives[/{id}], /api/macro-requirements | no | no | reference data (intended open) |
| GET | /api/projects?project= | **no** | **no** | lists every assessment of any project by pid; probe 200 with data (app.py:357-361) |
| GET | /api/projects/{project_id} | **no** | **no** | full assessment: risks, ratings, mapping run, priorities; probe 200 (app.py:363-365) |
| POST | /api/projects/{project_id}/map | **no** | **no** | triggers LLM calls with the project's own resolved key (app.py:367-373) |
| POST | /api/projects/{project_id}/severity | **no** | **no** | overwrites risk ratings (app.py:375-381) |
| DELETE | /api/projects/{project_id} | **no** | **no** | deletes an assessment (app.py:383-386) |
| GET | /p/{project} | yes (bypassable) | member (bypassable) | |
| GET | /p/{project}/objectives | yes (bypassable) | member | |
| GET | /p/{project}/projects | yes (bypassable) | member | probe via prefix: 200 |
| POST | /p/{project}/projects | yes (bypassable) | editor | forwards only `Authorization` to platform/qualification (upstream.py:30) |
| GET | /p/{project}/projects/{project_id} | partial | **project of the object not checked** | `_view_or_404(project_id)` only (app.py:251-258); probe via prefix: 200 |
| POST | /p/{project}/projects/{project_id}/map | partial | object project not checked | app.py:260-272 |
| POST | /p/{project}/projects/{project_id}/severity | partial | object project not checked | app.py:274-291 |

### 2.3 qualification-web (apps/qualification, basePath /qualification)

Callers: browser via Caddy `:80/qualification*`; server-to-server from control-objectives
(`/p/{project}/api/system-versions/{systemPid}/ontology.jsonld`) and qualification-agents
(`/api/qualifications/{id}/extracted` GET and PUT).

Middleware (src/middleware.ts:17-22): matcher `/p/:path*`, compiled as
`^/qualification(/_next/data/...)?/p(/...)?`; asks platform `/authz/projects/{project}` with the
caller's token; GET/HEAD/OPTIONS need any role, other methods need `may_write`. With no token the
platform answers 401, `fetchAccess` returns null and the page answers 503 (fails closed, wrong status).

| Method | Path | Auth | Authz | Notes |
|---|---|---|---|---|
| GET | / , /methodology | no | no | static content, 307 / 200 |
| GET/POST | /p/{project}/** pages and server actions | yes | role on the URL's project; writes need may_write | server actions take `projectId` as a client-supplied argument (see F7) |
| GET | /api/qualifications/{id}/ai-card.json | yes | member of the qualification's own project | route.ts:23 |
| GET | /api/qualifications/{id}/ai-card.pdf, /system-card.pdf | yes | same | |
| GET | /api/qualifications/{id}/ontology.jsonld, /ontology.ttl | yes | same | |
| GET | /api/qualifications/{id}/fill | yes | same | proxies agents `/fill/{id}` |
| GET | /api/qualifications/{id}/extracted | yes | same (any role) | the agent calls it with NO token, see F9 |
| PUT | /api/qualifications/{id}/extracted | yes | **any role, viewer included**; no may_write | extracted/route.ts:40-56; outside the middleware matcher so its write rule does not apply |
| GET | /p/{project}/api/system-versions/{systemPid}/ontology.jsonld | yes | member + card must be of that project | route.ts:21-28, correct pattern |

Probe: all four `/api/qualifications/<existing id>/*` returned 404 with no token; both `/p/...` 503.

### 2.4 qualification sidecars (apps/qualification/services)

None has any authentication; none is routed by Caddy; all are on `backend` only.

| Service | Method | Path | Auth | Authz | Callers |
|---|---|---|---|---|---|
| qualification-agents:8012 (agents/service.py) | GET | /health, /docs, /openapi.json | no | no | |
| | POST | /fill/{qualification_id} | **no** | no | qualification-web (FillerClient, on save). Starts a run that spends the qualification's project key via platform's internal route (service.py:64-82) |
| | GET | /fill/{qualification_id} | **no** | no | qualification-web `/api/qualifications/{id}/fill`. Returns run state, error text and result (service.py:85-90) |
| qualification-ontology:8011 (ontology/app.py) | GET | /vocabularies | no | no | qualification-web, agents |
| | POST | /build | no | no | qualification-web, agents. Pure computation on the body sent |
| qualification-prefill:8012 (prefill/app.py) | POST | /prefill | no | no | qualification-web (PrefillClient). Stateless |
| | POST | /forms/import | no | no | qualification-web (FormImportClient). Stateless |
| qualification-llm:4000 (llm/app.py) | POST | /generate | **no** | no | no caller found in code (`LLM_SERVICE_URL` is set but not read). Caller-chosen `model`; keys empty in the running container |
| qualification-pdf:8005 (system_card_renderer/app.py) | POST | /render/html, /render/pdf | no | no | qualification-web (SystemCardRendererClient). Stateless |

### 2.5 controls-web and controls-pdf (apps/controls)

Callers: browser via Caddy `:80/controls*`; catalogue frontend (browser) to `/controls/api/install`
with credentials from origin `CATALOGUE_ORIGIN`. `CONTROLS_APP_URL` is set on catalogue-backend but no
code reads it, so there is no server-to-server caller of controls-web today.

| Method | Path | Auth | Authz | Notes |
|---|---|---|---|---|
| GET | / | no | no | redirect to launcher |
| GET | /install | no | lists only the caller's writable projects | uses caller token; empty without one |
| GET/POST | /p/{project}/** pages and server actions | yes | middleware on the URL's project, and each action calls `projectDbFor(project, {write})` on the project it acts on (lib/projectDb.ts:158-172) | the argument project is re-checked, unlike qualification |
| GET | /p/{project}/submissions/{id}/report | yes | yes, the submission is read from that project's own database | route.ts:25-26 |
| GET | /api/install?slug=&project= | yes (caller token) | yes; Origin must equal CATALOGUE_ORIGIN | Origin is a browser-CSRF guard only; a script can forge it (probe 404 with forged Origin) but still needs a token to do anything |
| POST | /api/install | yes | `writableProject` editor check | route.ts:40-48 |
| controls-pdf POST | /render/html, /render/pdf | no | no | called by controls-web report route only |

### 2.6 report-composer and report-renderer

report-composer callers: browser via Caddy `:80/report-composer*`. report-renderer callers:
report-composer only (`REPORT_RENDERER_URL`, `X-Report-Token`).

report-composer: every API route depends on `signed_in` or `project_guard(right)` (guards.py:51-77),
which resolves the project by slug or pid, reads `core.project_member`, and for writes checks the
Origin/Referer equals `PLATFORM_ORIGIN`. Every id-addressed lookup takes the guarded project pid
(`layout_or_404(conn, pid, id)`, `template_or_404(conn, pid, id)`, `db.get_report(conn, pid, id)`).

| Method | Path | Auth | Authz | Notes |
|---|---|---|---|---|
| GET | / , /p/{ref} | no | no | redirects only |
| GET | /p/{ref}/, /p/{ref}/layouts/{id}, /p/{ref}/templates (pages) | yes | viewer | `guard()` inside the handler |
| GET | /api/block-types, /api/fonts | yes | no (global) | |
| GET | /api/presets, /api/presets/{id}/export | yes | no (global by design) | a preset saved with `keep_text` carries one project's free text to every signed-in user (api.py:394-408); by design per R-V1.7 |
| POST | /api/presets/import | yes | none (any signed-in user) | origin check |
| DELETE | /api/presets/{id} | yes | creator or admin | |
| GET | /api/p/{ref}/systems, /choices, /layouts, /layouts/{id}, /preview, /export, /reports, /templates, /templates/{id}/export, /logo, /reports/{id}/pdf, /download | yes | viewer, object scoped to project | |
| POST | /api/p/{ref}/layouts/{id}/validate | yes | viewer, origin check off | read-only computation |
| POST/PUT/DELETE | all other /api/p/{ref}/... | yes | editor + origin | |

report-renderer (`report_service.py` in the renderer image): middleware on every request requires
`X-Report-Token` (compare_digest). Routes `GET /health`, `/v1/block-types`, `/v1/fonts`,
(`/v1/languages`), `POST /v1/choices`, (`/v1/coverage-choices`), `/v1/render`. It trusts the
`project_id` in the body: authorization is the composer's job. Probe: 401 everywhere.

### 2.7 dashboard (Superset) and dashboard-gateway

Callers: browser via Caddy `:8188` (protect); platform to the bridge
`POST/DELETE http://host.docker.internal:8189/api/v1/aisc_project/<pid>` with `DASHBOARD_BRIDGE_TOKEN`
(platform_service/dashboard_bridge.py:29). report-renderer reads the `superset` database directly
(read-only role), not over HTTP.

Gate: `GatewayIdentity` (dashboard-gateway/gateway_identity.py:49-57) pops any client REMOTE_USER,
verifies the gateway token (RS256, issuer), sets REMOTE_USER to `preferred_username`;
`AUTH_REMOTE_USER`, `PUBLIC_ROLE_LIKE = None`, `/api/v1/security/login` and `/refresh` unrouted
(superset_gateway_config.py:51-60). Roles are re-synced from the token and `core.project_member`
on each sign-in. Superset listens on `172.17.0.1:8189` (compose :588), reachable from every
container, but only with a valid realm token.

### 2.8 devpi, pgadmin, schema-docs

| Service | Method | Path | Auth | Authz | Notes |
|---|---|---|---|---|---|
| devpi:3141 | GET | /+api, /root/public, /+simple/, packages | no | no | anonymous read is devpi's default and what the engine uses |
| | POST | /+login, uploads to root/public | root login | root only, but root's password is empty | entrypoint.sh:17,30 logs in with the empty password under `set -eu`, so the empty password is known to work; index `volatile=True` (entrypoint.sh:32) allows overwriting a published version |
| pgadmin:80 | any | /inspect/pgadmin/** | **no** (desktop mode) | no | compose infra :286-287; pgpass for `inspector_ro` is preloaded, so the SQL tool opens any allowed database without a password |
| schema-docs:8080 | GET | /health, /{platform or project_<32hex>}/** | **no** | no | server.py:29,100-108; schema, relationships and row counts, no row data; a GET to a database's index regenerates it |

### 2.9 connectors (not running)

`apps/connectors` has no compose service and no container. Code: every `/api/v1/connectors` route
depends on `admin_call` (routes_admin.py:1, 115-202); `/health` open. Not probed.

## 3. Findings, ranked

1. **Critical. control-objectives JSON API has no authentication or authorization at all.**
   `GET/POST/DELETE /api/projects...` sit outside `^/p/` (access.py:38, 131-133; api/app.py:357-386).
   Evidence live: from eval-worker with no token, `GET http://control-objectives:8090/api/projects?project=01399e17-...`
   and `/api/projects/0a013fbcc79b` returned 200 with the MCAS assessment (risks, ratings, mapping).
   Through Caddy the same routes are open to any signed-in realm user for any project. By code, the
   same caller can overwrite ratings, delete assessments, and trigger `/map`, which resolves and spends
   the project's own stored LLM key (risk_mapper) via the platform's internal route.

2. **Critical. control-objectives middleware bypass by root-path prefix.** The middleware tests
   `request.url.path` against `^/p/` while Starlette also routes `/control-objectives/p/...` to the
   same handlers (root_path, api/app.py:122). Evidence live: `GET /control-objectives/p/<pid>/projects`
   and `/control-objectives/p/<pid>/projects/0a013fbcc79b` returned 200 HTML with no token, while the
   plain `/p/...` returned 401. Through Caddy, `handle_path /control-objectives*` strips one prefix, so
   `/control-objectives/control-objectives/p/...` should reach the same bypass for any signed-in user
   (derived, not probed through Caddy). Writes (`POST .../map`, `.../severity`, start assessment) are
   behind the same, bypassed, gate.

3. **Critical. devpi root has an empty password on the index the engine installs plugins from.**
   `DEVPI_ROOT_PASSWORD` is empty in env.development and env.runtime and in the running container;
   entrypoint.sh:17,30 logs in with it; `root/public` is `volatile: true`, `acl_upload: ['root']`
   (live GET). Any container on the backend network (plugin code included) can log in as root and
   upload or replace a package that aisc-backend and aisc-eval-worker then install and import. This is
   a code-execution path into the engine. Login is a POST, so it was not exercised; the evidence is
   the configuration and the entrypoint succeeding with `set -eu`.

4. **High. pgAdmin is open on the backend network.** Desktop mode, no master password, preloaded
   pgpass for `inspector_ro` (docker-compose-infra.development.yml:286-298). Caddy's `admin_only`
   gate only protects the browser path; `GET http://pgadmin:80/inspect/pgadmin/browser/` returned 200
   with the full UI and no login. Anything on the backend network can run read queries across the
   platform and project databases (every module's data, the ciphertext of stored LLM keys).

5. **High. control-objectives id-addressed pages do not check the object's project.**
   `/p/{project}/projects/{project_id}` and its `/map`, `/severity` posts call `_view_or_404(project_id)`
   without comparing `view.record.project` with `{project}` (api/app.py:251-291). A member (editor for
   the posts) of project A can read and change project B's assessment through `/p/A/projects/<B's id>`.
   Assessment ids are 12 hex characters. Superseded in practice by F1/F2, but must be fixed with them.

6. **Medium. qualification `PUT /api/qualifications/{id}/extracted` accepts any role.**
   extracted/route.ts:47 only requires `access.role`; the path is outside the middleware matcher, so
   the "writes need may_write" rule never applies. A viewer can replace the card's agent draft of
   the latest version.

7. **Medium. qualification server actions trust a client-supplied project.** `patchOntologyNode`,
   `resetOntology`, `linkComponent`, `unlinkComponent` take `projectId` from the client
   (OntologyView.tsx:60, ComponentsPanel.tsx:73,82) while the middleware checks the project in the
   URL the action is posted to. The only check on the argument project is `assertLatestCard`, which
   asks the platform as the caller and needs only viewer (cardLatest.ts:21-28). So an editor of any
   project A who is a viewer of B can write B's card. Not probed (needs POST). `loadOntology` has the
   same shape but is not imported by any client component today. controls-web does this correctly
   (`projectDbFor` on the argument project).

8. **Medium. Unauthenticated LLM and agent entry points on the backend network.**
   `qualification-agents POST /fill/{id}` (service.py:64) starts a run that spends the
   qualification's project key; `GET /fill/{id}` returns run state and results. `qualification-llm
   POST /generate` (llm/app.py:49) is an open completion relay with a caller-chosen model; its keys
   are empty in the running container, so it is latent today.

9. **Medium (functional, affects the auth design). The card agent calls qualification-web with no
   identity.** agents/fill/clients.py:59-77 GETs and PUTs `/api/qualifications/{id}/extracted` with
   no token, and those routes require a caller who is a project member. Live: the same GET with no
   token answered 404 for an existing qualification. So the agent edge fails today and needs a
   service credential, not a user token, when auth is reworked. Similarly control-objectives'
   "Start assessment" forwards only `Authorization` (upstream.py:30), while Caddy delivers the user
   token as `X-Auth-Request-Access-Token`; unless something sets Authorization, that call reaches the
   platform with no token (probable, not probed).

10. **Low. schema-docs is open on the backend network** (server.py:100-108): schemas and row counts
    of the platform and every project database; a GET can trigger regeneration (CPU, DB reads).

11. **Low. Unauthenticated stateless sidecars** (ontology `/build`, prefill `/prefill` and
    `/forms/import`, qualification-pdf and controls-pdf `/render/*`): no stored data exposed, but
    usable for CPU abuse, and the PDF renderers process caller-supplied content.

12. **Low. Tokens are accepted from any client of the realm.** `verify_aud: False`
    (shared/identity/aisc_identity/tokens.py:46, gateway_identity.py:44). Any access token issued by
    the `aisc` realm to any client is accepted by every service. Superset keys users on
    `preferred_username` rather than `sub`.

13. **Low. qualification middleware answers 503 instead of 401 when there is no token**
    (projectAccess.ts:57: any non-OK platform answer becomes "unavailable"). Fails closed, but
    misreports.

14. **Info.** `/docs` and `/openapi.json` open on platform, control-objectives, agents, ontology,
    prefill, llm, qualification-pdf, controls-pdf. report-composer and report-renderer disable them.
    oauth2-proxy listens on `0.0.0.0:4180` on the host network (only its own endpoints). Form
    definitions in qualification are a global library editable from any project (by design).

## 4. Server-to-server call edges (must keep working when auth is added)

Credential column: what the caller sends today.

| Caller | Callee route | Credential today | Source |
|---|---|---|---|
| Caddy forward_auth | oauth2-proxy `GET /oauth2/auth` | browser cookie | Caddyfile `(protect)` |
| Caddy forward_auth | platform `GET /authz/admin` | copied `X-Auth-Request-Access-Token` | Caddyfile `(admin_only)` |
| qualification-web middleware and routes | platform `GET /authz/projects/{project}` | user Bearer | projectAccess.ts:53-56 |
| qualification-web | platform `GET/POST /projects/{p}/system-versions[/latest]` | user Bearer | PlatformClient.ts:77-93 |
| qualification-web | aisc-backend `GET /api/v1/projects?platform_project_id=`, `GET /api/v1/projects/{pid}/aisystem` | user Bearer | EngineClient.ts:36-44 |
| qualification-web | qualification-agents `POST /fill/{id}`, `GET /fill/{id}` | none | FillerClient.ts:17, fill/route.ts:23 |
| qualification-web | qualification-ontology `POST /build`, `GET /vocabularies` | none | OntologyClient.ts:42,66 |
| qualification-web | qualification-prefill `POST /prefill`, `POST /forms/import` | none | PrefillClient.ts:74, FormImportClient.ts:51 |
| qualification-web | qualification-pdf `POST /render/pdf` | none | SystemCardRendererClient.ts:28 |
| qualification-agents | qualification-web `GET` and `PUT /qualification/api/qualifications/{id}/extracted` | none (fails today, F9) | agents/fill/clients.py:59-77 |
| qualification-agents | qualification-ontology `GET /vocabularies`, `POST /build` | none | agents/fill/clients.py:37-56 |
| qualification-agents | platform `GET /internal/projects/{pid}/llm/card_agent` | `X-AISC-Service-Token` (card agent) | agents/fill/baf_llm.py:152-162 |
| qualification-agents | qualification-llm or a provider / ollama via BAF | provider key | compose `BAF_LLM_BASE_URL` |
| control-objectives | platform `GET /projects/{project}/system-versions/latest` | forwards `Authorization` only | upstream.py:42-48 |
| control-objectives | qualification-web `GET /qualification/p/{project}/api/system-versions/{systemPid}/ontology.jsonld` | forwards `Authorization` only | upstream.py:51-61 |
| control-objectives | platform `GET /internal/projects/{pid}/llm/risk_mapper` | `X-AISC-Service-Token` (risk mapper) | baf_llm.py:142-160 |
| controls-web middleware and actions | platform `GET /authz/projects/{project}` | user Bearer | lib/access/projectAccess.ts:56-57 |
| controls-web | platform `GET /projects` (writable projects) | user Bearer | lib/writableProjects.ts:21 |
| controls-web | platform `GET /projects/{pid}/system-versions/latest` | user Bearer | lib/systemVersion.ts:18 |
| controls-web | catalogue-backend `GET /control/{slug}/export` | optional `CATALOGUE_TOKEN` (empty locally) | lib/cataloguePackage.ts:25 |
| controls-web | controls-pdf `POST /render/pdf` | none | submissions/[id]/report/route.ts:79 |
| catalogue frontend (browser) | controls-web `GET/POST /controls/api/install` | gateway cookie + Origin | api/install/route.ts |
| report-composer | report-renderer `GET /v1/block-types`, `/v1/fonts`, `/v1/languages`; `POST /v1/choices`, `/v1/coverage-choices`, `/v1/render` | `X-Report-Token` | renderer_client.py:60-77 (the deployed renderer lacks `/v1/languages` and `/v1/coverage-choices`) |
| platform | dashboard `POST/DELETE /api/v1/aisc_project/{pid}` on `host.docker.internal:8189` | `DASHBOARD_BRIDGE_TOKEN` | dashboard_bridge.py:29-38 |
| aisc-backend, aisc-eval-worker | devpi `GET /root/public/+simple/...` | `PACKAGE_REGISTRY_USER`/`PASSWORD` (password empty) | routers/plugin.py:39, celery_tasks.py:92 |
| plugin-publisher (one-shot) | devpi upload to `root/public` | root with empty password | docker-compose.development.yml:617-629 |
| catalogue-backend | devpi (index lookups) | none | out of scope, listed for completeness |

Direct database readers that bypass HTTP authorization entirely, and so need the same thought when
membership rules change: control-objectives and report-composer read `core.project_member`
themselves; report-renderer reads the platform, superset and project databases as `report_ro`;
Superset reads through `dashboard_ro`; pgAdmin and schema-docs as `inspector_ro`.
