# AISC Developer Guide

This guide is for **contributors** who want to build the platform from source,
run the applications locally, develop evaluation plugins, or publish new
container images.

> Looking to just **run** the platform? See the
> [Getting Started (users)](../README.md#-getting-started-users) section of the
> README — it runs everything from published images and needs no child repos.

## Contents

- [Repository structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Developing plugins](#developing-plugins)
- [Developing the core apps](#developing-the-core-apps)
- [Running the whole platform via Docker](#running-the-whole-platform-via-docker)
- [Building the images locally](#building-the-images-locally)
- [End-to-end smoke test](#end-to-end-smoke-test)
- [CI/CD & release](#cicd--release)

---

## Repository structure

The parent repository (`aisc`) is an umbrella for the applications and shared
libraries. Each lives in its own GitHub repository, included here as a
**git submodule** so everything can be developed together:

```
aisc/                    ← parent repo (compose files, docs, keycloak, init)
├── apps/
│   ├── backend/         → lux-ai-factory/aisc-backend      (Django API)
│   ├── eval/            → lux-ai-factory/aisc-eval         (Celery workers)
│   ├── webapp/          → lux-ai-factory/aisc-webapp       (React frontend)
│   ├── controls/        → lux-ai-factory/aisc-controls     (Next.js checklists; not in the default stack yet)
│   └── qualification/   → lux-ai-factory/aisc-qualification (Next.js EU AI Act; not in the default stack yet)
└── shared/
    ├── plugin-interface/ → lux-ai-factory/aisc-plugin-interface (Python lib)
    └── plugin-manager/   → lux-ai-factory/aisc-plugin-manager   (Python lib)
```

Clone everything for development:

```bash
git clone --recursive git@github.com:lux-ai-factory/aisc.git
cd aisc
git submodule foreach 'git checkout master; git pull'
```

*Already cloned without submodules?*

```bash
git submodule update --init --recursive
git submodule foreach 'git checkout master; git pull'
```

*If the `plugin-interface` / `plugin-manager` submodules are out of date:*

```bash
GIT_ALLOW_PROTOCOL=file:https:ssh git submodule foreach \
  'uv sync --upgrade-package aisc-plugin-manager || :'
```

> The shared libraries are normally consumed as Python packages pinned to a git
> tag (see `tool.uv.sources` in each app's `pyproject.toml`); the submodules
> exist to make local, side-by-side development and compatibility testing easy.

---

## Prerequisites

- **Docker** with **Compose v2** (`docker compose`).
- **Node.js 20+** and **npm** (webapp, controls, qualification).
- **[uv](https://docs.astral.sh/uv/)** (backend, eval, shared libs).
- **Git**.

---

## Developing plugins

If you only want to develop and test evaluation plugins, run the core system in
Docker and mount your local plugins.

1. Set your plugin folder path in `env.development` (a folder on your machine
   that will be mounted into the backend and eval containers):

   ```ini
   PLUGIN_PATH=/path/to/your/plugins
   ```

   Each plugin project lives in its own subfolder of that path.

2. Start the infrastructure and applications:

   ```bash
   docker compose --env-file env.development \
     -f docker-compose-infra.development.yml \
     -f docker-compose.development.yml up
   ```

Your plugins are automatically mounted and loaded into both the backend and the
evaluation worker.

> **Note:** `docker-compose.development.yml` installs `plugin-interface` and
> `plugin-manager` from the local `shared/` folder.

---

## Developing the core apps

When working on the webapp, backend or evaluation service themselves it is
easier to run the **infrastructure in Docker** and the apps **locally**.

### 1. Start infrastructure

```bash
docker compose --env-file env.development -f docker-compose-infra.development.yml up
```

This starts PostgreSQL, RabbitMQ, Redis, MinIO, Keycloak, immudb and Caddy.

### 2. Run the applications locally

Make sure `node` (webapp) and `uv` (Python apps) are installed.

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

**Evaluation service (Celery worker):**

```bash
cd apps/eval
uv sync
```

To run against the **local** `plugin-manager` / `plugin-interface` instead of the
published git-tagged packages:

```bash
uv pip install --no-deps -e ../../shared/plugin-manager -e ../../shared/plugin-interface
```

### 3. Run

Use the included run configurations in `.vscode/` (VS Code) or `.run/`
(JetBrains). In JetBrains IDEs, point each run configuration's Python
interpreter at the virtual environment in the corresponding app.

> `backend` and `eval` read `env.development` from their own folders
> (`apps/backend/env.development`, `apps/eval/env.development`). Make sure
> `PLUGIN_PATH` is set there too.

---

## Running the whole platform via Docker

To try the platform with the default plugins fetched automatically, run the
full development stack in one command:

```bash
docker compose --env-file env.plugin_downloader \
  -f docker-compose.plugin_downloader.yml \
  -f docker-compose-infra.development.yml \
  -f docker-compose.development.yml up
```

The `plugin_downloader` service clones the default plugin repositories into
`PLUGIN_PATH` before the backend and eval worker start.

> Users who don't need to modify the platform should prefer the published-image
> stack (`docker-compose.yml`) described in the README.

---

## Building the images locally

The `docker-compose.yml` used by end users references **published images** and
contains no `build:` sections. To build the same images locally (for example to
test a change before publishing):

```bash
docker build -t aisc-backend:local apps/backend
docker build -t aisc-eval:local    apps/eval
docker build -t aisc-webapp:local  apps/webapp
```

> The `apps/controls` and `apps/qualification` images are not published yet and
> are not part of the default stack. When they are added they must be built with
> `--build-arg NEXT_BASE_PATH=/controls` (resp. `/qualification`), because they
> are served under a path prefix behind Caddy.

---

## End-to-end smoke test

`e2e/` contains a Playwright test that starts the **published-image** stack
(`docker-compose.yml`), waits for the backend, Keycloak and webapp to be ready,
then drives a real Chromium browser to confirm the webapp actually renders. It
catches the class of regression `docker compose config` cannot see — images that
pull fine but serve a blank page. See [`e2e/README.md`](../e2e/README.md).

```bash
cd e2e
npm install
npx playwright install chromium   # first time only
npm test                          # starts the stack, tests, tears it down
```

It runs in CI via `.github/workflows/e2e-compose.yaml` on every `v*.*.*` tag and
on manual dispatch, against the published `ghcr.io/lux-ai-factory/*` images.

---

## CI/CD & release

The core application repositories each have a GitHub Actions workflow that
builds and pushes their image(s) to the **GitHub Container Registry (GHCR)**:

| Repository | Workflow | Images published |
| --- | --- | --- |
| `aisc-backend` | `.github/workflows/build-and-push.yml` | `ghcr.io/lux-ai-factory/aisc-backend` |
| `aisc-eval` | `.github/workflows/build-and-push.yml` | `ghcr.io/lux-ai-factory/aisc-eval` |
| `aisc-webapp` | `.github/workflows/build-and-push.yml` | `ghcr.io/lux-ai-factory/aisc-webapp` |

> The `aisc-controls` and `aisc-qualification` images are not published yet;
> their build workflows will be added together with those apps.

### Triggers

Every workflow runs on:

- a **tag** matching `v*.*.*` — this is the release path; it publishes the
  versioned images and moves `latest`;
- a push to **`master`** or **`dev`** — publishes branch-tagged images
  (`master`, `dev`) for testing;
- **manual dispatch** (`workflow_dispatch`).

The backend, eval and webapp workflows additionally run lint/test stages before
building, and all workflows generate and archive an **SBOM** (Syft + Grype).

### Cutting a release

1. Merge the change into `master` in the relevant child repository.
2. Create and push a semantic-version tag on `master`:

   ```bash
   git checkout master && git pull
   git tag v1.4.0
   git push origin v1.4.0
   ```

3. The workflow builds and pushes `ghcr.io/lux-ai-factory/<repo>:v1.4.0`,
   `:1.4`, `:1`, and `:latest` (plus a `:sha-…` tag).
4. In the parent `aisc` repository, bump the submodule pointer and, if you want
   to pin users to the release, set `AISC_IMAGE_TAG=v1.4.0` in `env.example`.

> Tag a **master** commit. Branch pushes also build images, but only tags produce
> versioned, user-facing releases.

### Package visibility

For `docker compose pull` to work for anonymous users, the GHCR packages must be
**public**: *GitHub org → Packages → (package) → Package settings → Change
visibility*. A newly published package defaults to **private**.

### Building for other architectures

The workflows build single-platform `linux/amd64` images. To add `linux/arm64`,
extend `docker/build-push-action` with `platforms: linux/amd64,linux/arm64` and
use a QEMU setup step.
