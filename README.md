# AI Assessment Sandbox Configurator (AISC)

AISC is a platform for assessing an AI system against the EU AI Act and similar requirements. A
project walks through six steps: **1** qualification (describe the system and get its AI card),
**2** control objectives (rate the risks and choose the objectives that mitigate them), **3** install
the plugins and tools the assessment needs, **4** execute the tests and address the controls,
**5** analyse the results on the dashboard, **6** compose the report. Every step is a separate
module, most of them in a git submodule of their own. This repository ties them together: the
platform service that owns projects and their members, the launcher pages, the gateway that gives
one sign-in to every module (Caddy, oauth2-proxy and Keycloak), the report composer, the database
init files, and the Docker Compose files that run the whole stack. Each project's data lives in a
PostgreSQL database of its own; an immudb ledger can record who did what.

The background documentation (architecture, mission, user guide) is in
[lux-ai-factory/rfc](https://github.com/lux-ai-factory/rfc).

## Components

Submodules (each has its own README):

| path | what it is |
|---|---|
| [`apps/qualification`](apps/qualification) | step 1: the EU AI Act qualification questionnaire (Next.js) that produces the AI card, with its LLM, PDF, prefill and ontology sidecars |
| [`apps/control-objectives`](apps/control-objectives) | step 2: the catalogue of control objectives, the risk register and the risk and control matrix |
| [`apps/catalogue`](apps/catalogue) | step 3: the registry of tests (plugin packages) and controls; the stack uses the hosted instance and builds only its `devpi` package index from here |
| [`apps/backend`](apps/backend) | step 4: the execution engine's Django API (datasets, models, plugins, evaluations) |
| [`apps/eval`](apps/eval) | step 4: the engine's Celery worker that installs and runs plugins |
| [`apps/webapp`](apps/webapp) | step 4: the engine's React frontend |
| [`apps/controls`](apps/controls) | step 4: the compliance checklists (controls) a project answers |
| [`apps/results-dashboard`](apps/results-dashboard) | step 5: Apache Superset configured for AISC results |
| [`apps/report-generator`](apps/report-generator) | step 6: the report renderer (HTML, PDF, DOCX), service `report-renderer` |
| [`shared/plugin-interface`](shared/plugin-interface) | the Python library every evaluation plugin implements |
| [`shared/plugin-manager`](shared/plugin-manager) | the library that discovers, installs and loads plugins |
| [`shared/report-plugin-interface`](shared/report-plugin-interface) | the interface of the report renderer's plugins |

Part of this repository:

| path | what it is |
|---|---|
| `platform/` | the platform service (FastAPI, service `platform`): projects, members and roles, one database per project, the AI system and its card versions, connections to systems under test, per-project LLM keys, evidence links, the ledger |
| `apps/report-composer/` | step 6: assembles a report from modules and asks the renderer for the document ([README](apps/report-composer/README.md)) |
| `shared/identity/` | `aisc_identity`, the one way every Python service reads who is calling (gateway headers, Keycloak tokens, service tokens) |
| `homepage/` | the launcher pages served by Caddy on port 8100: the project list, a project's page with its six steps, step 4's evidence page, Manage pages |
| `dashboard-gateway/` | the Superset config overlay that takes the user from the gateway's token |
| `Caddyfile` | the gateway's routes |
| `init/` | SQL run once by `postgres-setup`: databases, roles and grants |
| `scripts/` | setup (`secrets.sh`), checks against a running stack (`verify*.sh`), tests of the stack's configuration (`scripts/tests`) |
| `keycloak/` | the realm export (template) and the login theme |
| `inspector/` | pgAdmin and SchemaSpy, for admins, at `:8100/inspect/` |
| `infra/minio/` | builds MinIO from source |
| `apps/connectors/` | an import service for API descriptions (OpenAPI, Postman, ...); not started by any compose file |
| `def_plugins/`, `local_plugins/` | the default plugins (downloaded at start) and your own plugin sources (`PLUGIN_PATH`) |
| `docs/` | design history; not needed to run anything |

## How it works

```
browser ──> Caddy :80   (engine, /qualification, /control-objectives, /controls, /report-composer, /api, /flower)
            Caddy :8100 (launcher pages, /api/* -> platform)
            Caddy :8188 (dashboard, Superset)
              │ forward_auth on every request
              ├──> oauth2-proxy ──> Keycloak :8081 (realm aisc)
              └──> the module's container
modules ──> PostgreSQL: database `platform` (projects, members, report presets) + one `project_<pid>` per project
platform ──> immudb (ledger), the dashboard's bridge, the engine
```

- **One sign-in.** Caddy asks oauth2-proxy about every request (`forward_auth`); an anonymous one is
  redirected to Keycloak. The session cookie is scoped to `localhost`, so one login covers all
  ports. Every service also verifies the token itself (`AUTH_ENABLED=true`, through
  `aisc_identity`). The engine's frontend keeps its own Keycloak client with `check-sso`, so it
  takes the gateway's session silently; it may show a one-click "Please sign in" screen while that
  check runs.
- **Projects and roles.** The platform owns projects and their members (owner, editor, viewer);
  every module reads the caller's role in the project from the platform's `core` schema. An
  account with the realm role `admin` may act on every project, and only an admin deletes one.
- **One database per project.** Creating a project creates `project_<pid without hyphens>` from
  `platform/project-template/`. Qualification, control objectives, controls, the engine, the report
  composer and the dashboard keep that project's records there. The shared `platform` database
  holds only projects, members, AI systems and card versions (`core`), the report presets
  (`report_library`) and the ledger's state.
- **Installing tests.** Step 3 is the hosted catalogue
  (https://sandboxconfigurator.aifactory.lu/catalogue).
  Tests are installed into the engine from the stack's own package index, `devpi`
  (`PACKAGE_REGISTRY_URL=http://devpi:3141` in `env.plugin_downloader`), which `plugin-publisher`
  fills at start from `def_plugins/` with the packages and versions the hosted catalogue names.
  Controls are installed by the controls app from the catalogue's API.
- **Systems under test over the network.** Under a project's **Manage > Connections** an admin
  registers the AI systems the project assesses (OpenAI-compatible, A2A, Open Inference Protocol, or
  a REST API with a request template). A plugin reaches a connection through the platform. Calls to
  internal addresses are refused unless a project's owners allow them on that page, or the
  deployment allows them for every project with `CONNECTIONS_ALLOWED_HOSTS` on the `platform`
  service.
- **The dashboard** is Superset on its own port (it needs the site root). It has no login of its
  own: `dashboard-gateway/` turns the gateway's token into Superset's `REMOTE_USER`. It runs with
  `network_mode: host`, listening only on the Docker host address (`172.17.0.1:8189`).
- **The ledger** (immudb) is off by default (`LEDGER_MODE=off` on `platform`, `LEDGER_GATEWAY=off`
  on `caddy`).
- **Ports.** Only 80 (and 443, the same listener), 8081 (Keycloak), 8100 and 8188 are published to
  the network, and each answers an anonymous request with a redirect to Keycloak. PostgreSQL (5432), Redis, RabbitMQ, MinIO and
  immudb are bound to `127.0.0.1`. `scripts/verify-sso.sh` checks this.

## Prerequisites

- Linux with Docker Engine and the Docker Compose v2 plugin (`docker compose`). The stack needs
  ports 80, 443, 8081, 8100 and 8188 free, and 5432, 5672, 6379, 9000 and 3322 free on `127.0.0.1`.
- `git`, `openssl`, `python3` and `setfacl` (package `acl`), used by `scripts/secrets.sh`.
- For running tests on the host: [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 for the
  platform and the report composer).
- Optional, for steps 1 and 2 to suggest answers: an API key (`MISTRAL_API_KEY` or
  `ANTHROPIC_API_KEY` for qualification; control objectives defaults to a local Ollama on the host
  and takes `CONTROL_OBJECTIVES_LLM_PROVIDER` plus that provider's key instead). Per-project keys
  for the card agent and the risk mapper are set in the UI under **Manage > Models and API keys**.

## Install and run

1. **Clone with the submodules**, on the branch `feat/unified-modules`:
   ```bash
   git clone --recursive --branch feat/unified-modules https://github.com/lux-ai-factory/aisc.git
   cd aisc
   ```
   Already cloned without them: `git submodule update --init --recursive`. That command also
   restores the pinned submodule commits after a checkout. `git submodule update --remote` moves
   each submodule to the tip of the branch it tracks instead, which is an update, not a repair.

2. **Make the secrets, once.** None is committed and the compose files refuse to start without
   them:
   ```bash
   ./scripts/secrets.sh
   ```
   It writes `env.secrets` (git-ignored), combines it with `env.plugin_downloader` into
   `env.runtime`, renders the Keycloak realm to `keycloak/aisc-realm.local.json`, and makes immudb's
   signing key pair. Run it again after a pull: it keeps existing values and adds any new secret.
   `--rotate` replaces them (except the ones stored data depends on, see the top of the script);
   `--add-ledger-key` adds a version of the ledger's key.

3. **Start the stack**, as compose project `aisc`:
   ```bash
   docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml \
     -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build
   ```
   Compose orders the start itself: `postgres-setup` runs `init/` and the one-shot `*-migrate`
   services migrate each module before it starts. The first start takes several minutes (it builds
   every image, and compiles MinIO from source because MinIO publishes no community images).

4. **Sign in.** Open http://localhost:8100. The realm ships two development accounts,
   `user` / `user` and `admin` / `admin` (realm admin). Create a project and open it: its page shows
   the six steps in order. These accounts, the Keycloak console's `admin` / `admin` and the realm
   export are for localhost only; change them for any other deployment.

5. **Check it** once a project exists: `./scripts/verify.sh --stack` runs the checks against the
   running stack (`verify-db-access.sh`, `verify-project-databases.sh`, `verify-sso.sh`,
   `verify-rbac.sh`).

Other addresses: the engine at http://localhost/, its API at `/api`, Flower at `/flower`, Keycloak
at http://localhost:8081 (realm `aisc`), the dashboard at http://localhost:8188.

### Your own plugins

`PLUGIN_PATH` (`./local_plugins/` in `env.plugin_downloader`) is mounted into the engine and the
eval worker as `/app/plugins`, where they discover plugin source trees. See
[`local_plugins/README.md`](local_plugins/README.md) and the plugin developer guide in
`shared/plugin-interface`.

### The engine on its own

The execution engine (`apps/backend`, `apps/eval`, `apps/webapp`) also runs standalone, without the
platform or the gateway. `AISC_DEPLOYMENT` selects the mode in the backend and the eval worker
(`APP_DEPLOYMENT` in the webapp): unset means **standalone** (one database holding all projects, no
project header); `configurator`, which every compose file here except the standalone one sets,
means one database per project, migrated by the one-shot `aisc-backend-migrate`
(`manage.py migrate_projects`).

The standalone compose ships no secrets, because port 8000 is published with no gateway in front.
Put them in a git-ignored env file:

```bash
cat > env.engine-standalone <<'EOF_ENV'
DB_PASSWORD=<choose one>
S3_PASSWORD=<choose one>
RABBITMQ_PASSWORD=<choose one>
DJANGO_SECRET_KEY=<a long random string>
INTERNAL_API_KEY=<a long random string>
DEVPI_ROOT_PASSWORD=<choose one>
EOF_ENV
chmod 600 env.engine-standalone
docker compose --env-file env.engine-standalone -f docker-compose.engine-standalone.yml up --build
```

This starts the backend, the eval worker and the webapp with PostgreSQL, Redis, RabbitMQ, MinIO and
devpi. The webapp is on http://localhost:8080, the API on http://localhost:8000. To develop one of
the engine's apps on the host, see that submodule's README.

### Other compose files

`docker-compose-infra.yml`, `docker-compose-infra.staging.yml`, `docker-compose.staging.yml`,
`docker-compose.demo.nbg.yml` and `docker-compose.yml` are older deployment files for the engine
alone and are not used by the stack above.

### PostgreSQL 15

Every stack runs PostgreSQL 15 (the backend requires it): development, the standalone engine,
`docker-compose-infra.yml` and staging (`docker-compose-infra.staging.yml`). A data directory made
by PostgreSQL 14 does not start under 15, so moving from 14 needs fresh volumes on each of them,
staging included (`down -v`, which deletes the data); no data migration is provided.

## Configuration

Settings are in `env.plugin_downloader` (committed, no secrets) and secrets in `env.secrets` (made by
`scripts/secrets.sh`); compose reads both through `env.runtime`. Each service's variables are in the
compose files and in its own README (for the report composer,
[apps/report-composer/README.md](apps/report-composer/README.md)). Settings an installer is most
likely to change:

| variable | where | meaning | default |
|---|---|---|---|
| `CADDY_DOMAIN` | `env.plugin_downloader` | the gateway's origin | `http://localhost` |
| `KEYCLOAK_URL_EXTERNAL` | `env.plugin_downloader` | Keycloak as the browser reaches it | `http://localhost:8081` |
| `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD` | `env.plugin_downloader` | Keycloak's bootstrap admin (development values) | `admin`, `admin` |
| `HOMEPAGE_PORT_EXTERNAL` | `caddy` | the launcher's published port | `8100` |
| `DASHBOARD_PORT_EXTERNAL` | `caddy` | the dashboard's published port | `8188` |
| `DASHBOARD_INTERNAL_PORT` | `caddy`, `platform`, `dashboard` | Superset's port on the Docker host address | `8189` |
| `PLUGIN_PATH` | `env.plugin_downloader` | your plugin sources, mounted into the engine | `./local_plugins/` |
| `PACKAGE_REGISTRY_URL` | `env.plugin_downloader` | the index the engine installs plugins from | `http://devpi:3141` |
| `CATALOGUE_EXTERNAL_URL`, `CATALOGUE_API_URL` | `env.plugin_downloader` | the hosted catalogue's page and API | `https://sandboxconfigurator.aifactory.lu/...` |
| `CONNECTIONS_ALLOWED_HOSTS` | `platform` | internal hosts every project's connections may call (comma list) | empty |
| `PLATFORM_OLLAMA_BASE_URL` | `platform` | where a project's Ollama choice is reached | `http://host.docker.internal:11434` |
| `MISTRAL_API_KEY`, `ANTHROPIC_API_KEY` | qualification, control objectives | hosted model keys | empty |
| `CONTROL_OBJECTIVES_LLM_PROVIDER` | `control-objectives` | the model provider for suggestions | `ollama` |
| `LEDGER_MODE`, `LEDGER_GATEWAY` | `platform`, `caddy` | the immudb ledger | `off` |
| `AISC_IMAGE_TAG` | all built images | the tag of locally built images | `latest` |

The secrets themselves (gateway cookie and client secrets, service tokens, database role passwords,
`PLATFORM_SECRETS_KEY` that encrypts stored LLM keys, the ledger keys) are listed with their purpose
in `scripts/secrets.sh`. Never commit `env.secrets`, `env.runtime` or
`keycloak/aisc-realm.local.json`.

## Tests

The tests never need the running stack. **Never point a test at the live database** (PostgreSQL on
`127.0.0.1:5432` of the running stack): tests that need a database get a throwaway container of
their own (`aisc-t-*`, `postgres:15-alpine` through `scripts/lib/throwaway-pg.sh` or
`scripts/lib/report_bed.py`) on a port the kernel picks, removed afterwards.

From the repository root:

```bash
# the stack's configuration (Caddyfile, compose files, init SQL, pages, scripts), read as text,
# plus harnesses that start throwaway Postgres containers with docker run
uv run --with pytest --with pyyaml --with 'psycopg[binary]' pytest -q -p no:cacheprovider scripts/tests

# the platform service; database tests skip unless given a database
cd platform && uv run --extra dev pytest -q -p no:cacheprovider tests --ignore tests/ledger

# the identity library
cd shared/identity && uv run --extra dev pytest -q -p no:cacheprovider tests

# the report composer (starts throwaway Postgres containers)
cd apps/report-composer && uv run --extra dev pytest -q

# the dashboard's gateway config
cd dashboard-gateway && uv run --with pyjwt --with cryptography python -m unittest test_gateway_identity
```

The platform's database tests use `PLATFORM_TEST_DATABASE_URL`, falling back to
`PLATFORM_DATABASE_URL` and then to `127.0.0.1:5432/platform`: on a machine that runs the stack,
always set `PLATFORM_TEST_DATABASE_URL` to a throwaway database before running them. Tests that need
a superuser (making project databases) also need `PLATFORM_TEST_SUPERUSER_URL` for the same throwaway
server. `./scripts/verify.sh --modules` runs every module's suite whose dependencies are installed.

## Contributing

- **Branch:** `feat/unified-modules` is the only branch, in this repository and in every submodule
  that tracks it. Work, merge and push there; do not create side branches.
- A change to a submodule is committed in the submodule first, then the new pin is committed here.
- Database changes are migration files: `platform/migrations/` for the `platform` database,
  `platform/project-template/` for what every new project database starts with, and each module's
  own migrations for its tables. Applied migrations are recorded by file name and never run again,
  so a change goes in a new file.
- Read [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are made under the contributor license
  agreements in this repository (`AISC ICLA (Individuals).txt`, `AISC CCLA (Entities).txt`) and
  licensed under [Apache 2.0](LICENSE.md).

## License

Apache License 2.0, see [LICENSE.md](LICENSE.md).
© 2024–2026 Université du Luxembourg and Luxembourg Institute of Science and Technology.
