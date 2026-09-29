# AI Assessment Sandbox Configurator

The AI Assessment Sandbox Configurator is a platform for evaluating and assessing risks in AI models.

## 📚 Documentation

The official documentation lives in the [**lux-ai-factory/rfc**](https://github.com/lux-ai-factory/rfc) repository. It explains the **architecture** and the **mission** of the AI Assessment Sandbox Configurator, describes the **Catalogue** of tests and controls, and provides the **guide for users**.

As the name suggests, it is also a **Request for Comments**: anyone who wishes to contribute is warmly invited to share their feedback.

## 🚀 Getting Started

1. **Clone the repository and submodules:**
   ```bash
   git clone --recursive --branch feat/unified-modules https://github.com/lux-ai-factory/aisc.git
   cd aisc
   ```

   `feat/unified-modules` is the branch to ask for. Submodules are pinned by the
   clone above, so it is the only branch name you need; each one otherwise tracks
   its own `main` or `master`, except `apps/results-dashboard`, `apps/report-generator`
   and `shared/report-plugin-interface`, which carry commits that are not on their
   `main` yet and so track this branch name too.

   The PDF report renderer is built from two of these submodules: `apps/report-generator`
   and `shared/report-plugin-interface`. No evaluation tool needs a report plugin of its own:
   a tool without one gets its results in the report's generic results table.

   > [!NOTE]
   > `git submodule update --remote --recursive` moves each submodule to the tip of
   > the branch it tracks, which is not what the pins say. `apps/qualification` is
   > one commit behind its `main` here, so that command would move it. Use it only
   > when you mean to update, not to repair a checkout: for that, plain
   > `git submodule update --init --recursive` restores the pinned commits.

   *If you've already cloned without submodules:*
   ```bash
   git submodule update --init --recursive
   ```
   
   *If the plugin-interface or plugin-manager submodules are not updated:*
   ```bash
    GIT_ALLOW_PROTOCOL=file:https:ssh git submodule foreach 'uv sync --upgrade-package aisc-plugin-manager || :'
   ```

2. **Make the secrets, once.** None is committed; this writes `env.secrets`, combines it with
   `env.plugin_downloader` into `env.runtime`, and renders the Keycloak realm:
   ```bash
   ./scripts/secrets.sh
   ```

3. **Start it.** The downloader fetches the default plugins into `def_plugins/`, and
   `plugin-publisher` uploads them to the stack's own package index:
   ```bash
   docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml \
     -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build
   ```
   Then open http://localhost:8100, sign in (`user` / `user` or `admin` / `admin`) and create a
   project. `./scripts/verify.sh --stack` checks the running stack once a project exists.
   
---

## What runs where

**Start here: http://localhost:8100** — the project list. Create a project, open
it, and the six assessment modules appear in the order they are meant to be used. It is a static page in `homepage/`,
served by the platform's own Caddy on a listener of its own, because the execution
engine owns the root of port 80 and cannot be served under a path prefix.

A project is defined once, at the platform level: `platform/` is a small service
over a `platform` database whose only table is `project`, created by
`init/platform-db.sql` before any app migrates. Its API is served on the
launcher's own origin at `/api/projects`, behind the same sign-in, and every
account may see every project.

> [!NOTE]
> **Every project has a database of its own**, `project_<pid without hyphens>`, made by the
> platform when the project is made. Qualification (with its question sets and
> questionnaires), control objectives, controls, the engine, the report composer and the
> dashboard's data keep a project's records there and nowhere else. The shared `platform`
> database holds only the projects and their members (`core`) and the report presets
> (`report_library`). The built-in Annex IV forms are seeded into every project database;
> a form made in one project is reused in another by exporting and importing it.

| step | module | open |
|---|---|---|
| 1 | Qualification (`apps/qualification`) | http://localhost/qualification |
| 2 | Control objectives (`apps/control-objectives`) | http://localhost/control-objectives |
| 3 | Catalogue (hosted) | https://sandboxconfigurator.aifactory.lu/catalogue |
| 4 | Execution engine (`apps/webapp` + `apps/backend` + `apps/eval`) | http://localhost/ |
| 5 | Controls (`apps/controls`) | http://localhost/controls |
| 6 | Results dashboard (`apps/results-dashboard`) | http://localhost:8188 |

The catalogue is the hosted one; no catalogue runs in this stack. It is for browsing: it
has no Install button. Tests are installed into the engine from the stack's own package index,
the local `devpi` (`PACKAGE_REGISTRY_URL` in `env.plugin_downloader`), through the engine's
install dialog, which a link opens. `plugin-publisher` fills that index at start from
`def_plugins/`, with the packages and versions the hosted catalogue names:

    http://localhost/receiver?project=<project pid>&uri=web%2Baiscplugin%3A%2F%2Fenable%3Fpackage%3D<name>%26version%3D<version>

`project` is the pid on the project's launcher page (its URL). It is needed because the engine
remembers the current project per browser tab, and the link opens in a new one: without it the
dialog has no project to offer. The dialog lists that project in a **dropdown** and posts your choice to its own
`POST /api/v1/plugins`. Controls are installed from the hosted catalogue's API by
controls itself (`/controls/install?slug=<control>`).

No token, no allowlist and no pasted UUID: the engine knows its own projects, so
the install happens where that knowledge is. The endpoint predates the feature and
is on the engine's `master`.


> [!NOTE]
> There is a second, unused implementation of this in the codebase: a token-guarded
> `POST /api/v1/catalogue/install` on `aisc-backend`'s `feat/catalogue-1click-install`,
> with a trusted-index allowlist, driven by an Install button that asks for a project
> UUID. It was written for a **hosted** catalogue talking to a deployment it can
> reach over the network. Here both sit in one stack and the browser does the hop, so
> this install uses the engine's own dialog instead and pins `apps/backend` at
> `master`.

**Signing in, once.** Every module above sits behind a gateway: Caddy asks
oauth2-proxy about each request with `forward_auth`, and an unauthenticated one
becomes a redirect to Keycloak. You sign in at the first page you open and that
session covers all of them, because the cookie is scoped to domain `localhost`
and cookies ignore ports.

The realm ships two dev accounts, `user` / `user` and `admin` / `admin`. They are
development credentials in a committed realm export, as is the gateway's own
client secret in `keycloak/aisc-realm.json`: change all of them for anything that
is not localhost.

The execution engine keeps its own Keycloak client and its own check, but it
initialises with `check-sso`, so it accepts the gateway's session silently rather
than asking a second time. `./scripts/verify-sso.sh` asserts exactly that, one
login then every module, ending with the `prompt=none` request the engine itself
makes.

The dashboard is covered the same way. Superset has no login of its own: Caddy serves it on
8188 behind the gateway, and `dashboard-gateway/` (loaded through `SUPERSET_CONFIG_PATH`, with
the dashboard's own `superset_config.py` run unchanged) verifies the token the gateway passes
and hands Superset the user as `REMOTE_USER`. Roles and project access are synced from the
token's realm roles and the platform's memberships, by the dashboard's own code. There is no
local admin account and no password login. Superset still runs with `network_mode: host`, so it
reaches Postgres on the host port its project connections were registered with, but it listens
only on the Docker host address (`172.17.0.1:8189`): Caddy and the platform's bridge reach it,
the network does not.

Internal traffic is unaffected: services call the backend directly on
`http://aisc-backend:8000` rather than through Caddy.

**Nothing bypasses the gateway.** Only four ports are published to the network:
80, 8081 (Keycloak, which the browser must reach), 8100 and 8188, and every
one of them answers an anonymous request with a redirect to Keycloak. The apps'
own ports are not published, and Postgres, Redis, RabbitMQ, MinIO and immudb are
bound to `127.0.0.1`, reachable from the host only because the dashboard runs with
`network_mode: host`. `scripts/verify-sso.sh` asserts all of this, so an
accidentally published port fails the suite.

> [!WARNING]
> One exception remains, and it is not fixable from this repository. The execution
> engine's frontend renders its own "Please sign in to get started" screen when its
> silent Keycloak check has not completed: `GlobalHome.tsx` gates on `authenticated`
> with no flag, and the app has no equivalent of the backend's `AUTH_ENABLED`, so it
> cannot be told that the gateway already authenticated. Keycloak does answer its
> silent check with a code, so the screen is a one-click pass rather than a second
> login, but making it disappear needs a change in `apps/webapp`.

> [!NOTE]
> A shared name such as `keycloak.localhost` looks like the tidier answer and does
> not work over plain HTTP. Keycloak 26 sets `SameSite=None` on its session
> cookies, which forces `Secure`, and `localhost` is the one origin exempt from
> that. On any other hostname the login fails with "Restart login cookie not
> found" until you put Keycloak behind TLS.

Also reachable: the backend's API at `/api`, Celery's
Flower at `/flower`, and Keycloak on http://localhost:8081 (realm `aisc`).

The dashboard has a port of its own because Superset needs the site root and does
not work under a path prefix. It reads the platform database through a read-only
role, so it can chart results but never write to them.

**Systems under test over the network.** Under the project page's **Manage → Connections**, an
admin registers the AI systems the project assesses through their API (an OpenAI-compatible
endpoint, or any REST API with a request template), tests each with one probe, and an evaluation
then picks one as its system under test. Calls to internal addresses (loopback, private ranges,
the stack's own services) are refused unless listed in `CONNECTIONS_ALLOWED_HOSTS` (host or
host:port, comma list), e.g. `CONNECTIONS_ALLOWED_HOSTS=host.docker.internal:8500` for a system
running on the Docker host.

Steps 1, 2 and 5 need a model to be useful. Qualification's LiteLLM sidecar takes
`MISTRAL_API_KEY` or `ANTHROPIC_API_KEY`; control objectives defaults to a keyless
local Ollama and takes `CONTROL_OBJECTIVES_LLM_PROVIDER` plus that provider's key
for a hosted model instead.

## Two deployment modes

The execution engine (`apps/backend`, `apps/eval`, `apps/webapp`) can run standalone, on its
own, or inside the Configurator, which is what this stack runs.

`AISC_DEPLOYMENT` is the switch: `aisc-backend` and `aisc-eval-worker`/`aisc-eval-flower` read
it once (`aisc_backend/deployment.py`, `aisc_eval/deployment.py`). Left unset, they default to
**standalone**: one database holding all projects (created in the engine), no per-request
project header. Set to
`configurator`, they run **configurator** mode: one database per project (which needs
PostgreSQL), and every request carries the caller's project. The webapp reads the matching
`APP_DEPLOYMENT` the same way; its image defaults to `standalone` (`apps/webapp/Dockerfile`)
and this stack sets it to `configurator` in `docker-compose.development.yml`.

This repository's compose files set `AISC_DEPLOYMENT: configurator` (and
`APP_DEPLOYMENT: configurator` on the webapp), so `docker compose ... up` here always runs the
engine inside the Configurator: migrations run per project through the one-shot
`aisc-backend-migrate` (`manage.py migrate_projects`), never a plain `manage.py migrate` on the
long-running `aisc-backend` service, and the engine's Caddy site proxies
`GET /platform/api/projects` (protected, then rewritten to `/projects`) to the platform, so it
can list the caller's projects.

To run the engine **on its own**, without the Configurator, the platform, or the gateway, use
`docker-compose.engine-standalone.yml` instead:

```bash
docker compose --env-file env.engine-standalone -f docker-compose.engine-standalone.yml up --build
```

(`env.engine-standalone` holds its secrets; see below.)

This starts `aisc-backend`, `aisc-eval-worker` and `aisc-webapp` with `AISC_DEPLOYMENT` unset,
plus the infrastructure they need on their own (PostgreSQL, Redis, RabbitMQ, MinIO, and the
package index plugins are installed from). The backend's own Dockerfile already runs
`manage.py migrate` before it serves, so no separate migration step is needed here. The webapp
is on http://localhost:8080, the API on http://localhost:8000.

The standalone compose ships no secrets: port 8000 is published with no gateway in front, so a
default `INTERNAL_API_KEY` would let anyone call `/api/v1/internal/*`. Put them in an env file
(not committed) and pass it with `--env-file`:

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

Compose refuses to start while one of them is missing.

### PostgreSQL 15

Every stack runs PostgreSQL 15 (the backend requires it): development, the standalone engine,
`docker-compose-infra.yml` and staging (`docker-compose-infra.staging.yml`). A data directory
made by PostgreSQL 14 does not start under 15, so moving from 14 needs fresh volumes on each of
them, staging included (for example `docker compose ... down -v`, which deletes the data); no
data migration is provided.

## 📁 Repository Structure

This repository consists of three main applications that work in tandem, along with shared libraries for plugin management:

### Applications (`apps/`)
*   **Webapp (`apps/webapp`)**: A React-based frontend for interacting with the aisc platform.
*   **Backend (`apps/backend`)**: A Django-based bakend that manages datasets, models, and evaluation requests.
*   **Evaluation Service (`apps/eval`)**: A Celery worker that executes evaluation tasks using plugins.
*   **Controls (`apps/controls`)**: A Next.js app for AI-compliance checklists with 1–5 readiness scoring and PDF reporting. Served under `/controls`.
*   **Qualification (`apps/qualification`)**: A Next.js app that qualifies AI systems against the EU AI Act (Articles 10/12/13/14) and generates system cards, via a LiteLLM completion sidecar and a PDF renderer. Served under `/qualification`.

### Shared Libraries (`shared/`)
*   **Plugin Interface (`shared/plugin-interface`)**: Defines the standard interface that all aisc plugins must implement.
*   **Plugin Manager (`shared/plugin-manager`)**: A library used by both the backend and evaluation service to discover, load, and execute plugins.

> **Note**: While these shared libraries are typically distributed as separate git repositories and included via `uv`, they are included here as submodules to facilitate local development and ensure compatibility across the entire system.

---

## 🛠 Developer Guide

### 🧩 Developing Plugins

If you only want to develop and test plugins, you can run the core system in Docker and load your local plugins.

1. **Set your plugin folder path** in `env.development` (this should be a folder on your local machine, it will be mounted into the docker containers):
   ```ini
   PLUGIN_PATH=/path/to/your/plugins
   ```

2. **Run the infrastructure and application:**
   ```bash
   docker compose --env-file env.development -f docker-compose-infra.development.yml -f docker-compose.development.yml up
   ```

Your plugins will be automatically mounted and loaded into the backend and evaluation worker.

   > **Note**: `docker-compose.development.yml` will install the `plugin-interface` and `plugin-manager` from the `shared` folder in this repo 

### 💻 Developing Core Apps (Webapp, Backend, or Eval)

If you are working on the webapp, backend, or evaluation service itself, it is easier to run the infrastructure in Docker and the apps locally on your machine.

#### 1. Start Infrastructure
```bash
docker compose --env-file env.development -f docker-compose-infra.development.yml up
```
This starts PostgreSQL, RabbitMQ, Redis, MinIO, and Caddy.

#### 2. Run Applications Locally

Make sure you have `node` (for webapp) and `uv` (for Python apps) installed.

#### 2.1 Setup

**Webapp (React):**

```bash
cd apps/webapp
npm i
```

**Backend (Django):**
```bash
cd apps/backend
uv sync
uv run manage.py migrate
```

  > **Note**: to run the app with the local `plugin-manager` and `plugin-interface` run the following command

```bash
uv pip install --no-deps -e ../../shared/plugin-manager -e ../../shared/plugin-interface
```

**Evaluation Service (Celery Worker):**
```bash
cd apps/eval
uv sync
```

  > **Note**: to run the app with the local `plugin-manager` and `plugin-interface` run the following command

```bash
uv pip install --no-deps -e ../../shared/plugin-manager -e ../../shared/plugin-interface
```

#### 2.2 Run

You can run the apps with the included run configurations in `.vscode/` for **VSCode** or `.run/` for **JetBrains IDEs**.

> **Note**: In **JetBrains IDEs** you will need to setup the python interpreters in the rin configurations to point to the virtual environments in each app

> **Note**: `backend` and `eval` will use the `env.development` files in their respective folders (`apps/backend/env.development`, `apps/eval/env.development`) when running these run configurations.

> Make sure you update the **PLUGIN_PATH** in `apps/backend/env.development`, `apps/eval/env.development`

#### 2.3 Run all the platform via Docker, automatically download default plugins

If you want to just try the platform and play a bit with it, you can run all the infra and the application services using a single compose command.
```bash
docker compose --env-file env.plugin_downloader -f docker-compose.plugin_downloader.yml -f docker-compose-infra.development.yml -f docker-compose.development.yml up
```
## ⚠️ Current Limitations & Roadmap

The platform currently assumes that both the AI system under test and the test data are **uploaded into the platform**:

- **Models** are uploaded files stored in the platform's object storage (the web UI currently accepts `.onnx`). Assessing a system that runs in your own infrastructure, through the API it already exposes, is not yet supported as a first-class concept; some evaluation plugins (e.g. StrongREJECT) approximate it by taking an API key or base URL in their own configuration.
- **Datasets** must be uploaded through the webapp. Test sets that already live in your own permanent storage (S3-compatible, Azure Blob, GCS, ...) cannot yet be attached by reference.

Note that the platform's *own* infrastructure is already fully configurable at deployment time: object storage is any S3-compatible endpoint (`S3_URL`, `S3_USER`, `S3_PASSWORD`, `S3_*_BUCKET`), the database is any PostgreSQL instance (`DB_*`), and the broker/cache likewise (`MQ_*`, `REDIS_*`).

**What we are doing about it:** we are introducing **connection profiles**: configure your storage and your system's API endpoint once, then create datasets by reference and register models as endpoints, with evaluations connecting directly to your infrastructure at run time and credentials stored encrypted, write-only. Progress is tracked in [lux-ai-factory/aisc#52](https://github.com/lux-ai-factory/aisc/issues/52).

---

##  Contributing

We welcome community contributions! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) for details.

By submitting contributions, you agree to the [CLA](CLA/CLA_VERA.md) and license your work under [Apache 2.0](LICENSE).

---

##  License

This project is licensed under the [Apache License 2.0](LICENSE).  
© 2024–2026 Université du Luxembourg and Luxembourg Institute of Science and Technology.
