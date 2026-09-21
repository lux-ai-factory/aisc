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
   its own `main` or `master`, except `apps/results-dashboard`, which carries a
   commit that is not on its `main` yet and so tracks this branch name too.

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
   
---

## What runs where

**Start here: http://localhost:8100** — a launcher listing the six assessment
modules in the order they are meant to be used. It is a static page in `homepage/`,
served by the platform's own Caddy on a listener of its own, because the execution
engine owns the root of port 80 and cannot be served under a path prefix.

| step | module | open |
|---|---|---|
| 1 | Qualification (`apps/qualification`) | http://localhost/qualification |
| 2 | Control objectives (`apps/control-objectives`) | http://localhost/control-objectives |
| 3 | Catalogue | *not in this install* |
| 4 | Execution engine (`apps/webapp` + `apps/backend` + `apps/eval`) | http://localhost/ |
| 5 | Controls (`apps/controls`) | http://localhost/controls |
| 6 | Results dashboard (`apps/results-dashboard`) | http://localhost:8188 |

Step 3, the catalogue, is not wired into this install. The launcher keeps it in the
sequence so the workflow reads correctly, marks it, and does not link it.

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

The dashboard is covered differently, because Superset authenticates itself rather
than being proxied: it uses its own Keycloak client (`superset`, also declared in
the realm) through the native SSO the dashboard repo ships. Its login page offers
Keycloak instead of a password form, and with a session already established it
logs you in without asking. That is why the `dashboard` service runs with
`network_mode: host`: it fetches the OIDC metadata server-side and then sends the
browser to the same issuer, so both have to be the identical string, and
`http://localhost:8081` is the only one that is. It still serves on 8188, since
the stock entrypoint honours `SUPERSET_PORT`.

Internal traffic is unaffected: services call the backend directly on
`http://aisc-backend:8000` rather than through Caddy.

> [!NOTE]
> A shared name such as `keycloak.localhost` looks like the tidier answer and does
> not work over plain HTTP. Keycloak 26 sets `SameSite=None` on its session
> cookies, which forces `Secure`, and `localhost` is the one origin exempt from
> that. On any other hostname the login fails with "Restart login cookie not
> found" until you put Keycloak behind TLS.

Also reachable: the backend's API at `/api`, the Django admin at `/admin`, Celery's
Flower at `/flower`, and Keycloak on http://localhost:8081 (realm `aisc`).

The dashboard has a port of its own because Superset needs the site root and does
not work under a path prefix. It logs in with its own admin account
(`DASHBOARD_ADMIN` / `DASHBOARD_ADMIN_PASSWORD`, both `admin` by default) and reads
the platform database through a read-only role, so it can chart results but never
write to them.

Steps 1, 2 and 5 need a model to be useful. Qualification's LiteLLM sidecar takes
`MISTRAL_API_KEY` or `ANTHROPIC_API_KEY`; control objectives defaults to a keyless
local Ollama and takes `CONTROL_OBJECTIVES_LLM_PROVIDER` plus that provider's key
for a hosted model instead.

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
