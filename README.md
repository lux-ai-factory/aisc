# AI Assessment Sandbox Configurator

The AI Assessment Sandbox Configurator is a platform for evaluating and assessing risks in AI models.

## 📚 Documentation

The official documentation lives in the [**lux-ai-factory/rfc**](https://github.com/lux-ai-factory/rfc) repository. It explains the **architecture** and the **mission** of the AI Assessment Sandbox Configurator, describes the **Catalogue** of tests and controls, and provides the **guide for users**.

As the name suggests, it is also a **Request for Comments**: anyone who wishes to contribute is warmly invited to share their feedback.

## 🚀 Getting Started

1. **Clone the repository and submodules:**
   ```bash
   git clone --recursive git@github.com:lux-ai-factory/aisc.git
   cd aisc
   git submodule foreach 'git checkout master; git pull'
   ```

   *If you've already cloned without submodules:*
   ```bash
   git submodule update --init --recursive
   git submodule foreach 'git checkout master; git pull'
   ```
   
   *If the plugin-interface or plugin-manager submodules are not updated:*
   ```bash
    GIT_ALLOW_PROTOCOL=file:https:ssh git submodule foreach 'uv sync --upgrade-package aisc-plugin-manager || :'
   ```
   
---

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
##  Contributing

We welcome community contributions! Please read our [CONTRIBUTING.md](CONTRIBUTING.md) for details.

By submitting contributions, you agree to the [CLA](CLA/CLA_VERA.md) and license your work under [Apache 2.0](LICENSE).

---

##  License

This project is licensed under the [Apache License 2.0](LICENSE).  
© 2024–2026 University of Luxembourg and Luxembourg Institute of Science and Technology.

---

## Acknowledgments

This work is part of ongoing research and development efforts within the University of Luxembourg’s digital governance and AI compliance initiatives, including the AI Factory Luxembourg initiative.  
