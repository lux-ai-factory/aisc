# VERA

VERA is a platform for evaluating and assessing risks in AI models.

## 🚀 Getting Started

If you just want to run the full system with all components, use Docker Compose:

1. **Clone the repository and submodules:**
   ```bash
   git clone --recursive https://github.com/lux-ai-factory/vera.git
   cd vera
   ```

   *If you've already cloned without submodules:*
   ```bash
   git submodule update --init --recursive
   ```

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

### 💻 Developing Core Apps (Webapp, Backend, or Eval)

If you are working on the webapp, backend, or evaluation service itself, it is easier to run the infrastructure in Docker and the apps locally on your machine.

#### 1. Start Infrastructure
```bash
docker compose --env-file env.development -f docker-compose-infra.development.yml up
```
This starts PostgreSQL, RabbitMQ, Redis, MinIO, and Caddy.

#### 2. Run Applications Locally

Make sure you have `node` (for webapp) and `uv` (for Python apps) installed.

**Webapp (React):**
```bash
cd apps/webapp
npm install
npm run dev
```

**Backend (Django):**
```bash
cd apps/backend
uv pip install -e ../../shared/plugin-manager -e ../../shared/plugin-interface
uv run manage.py migrate
uv run uvicorn config.asgi:application --host 0.0.0.0 --port 8000
```

**Evaluation Service (Celery Worker):**
```bash
cd apps/eval
uv pip install -e ../../shared/plugin-manager -e ../../shared/plugin-interface
uv run celery -A vera_eval.celery_worker worker --loglevel=debug
```

*(Note: Ensure your local environment variables in `env.development` are configured to point to `localhost` or `127.0.0.1` instead of container names like `rabbitmq` or `postgres` if you are running outside of the Docker network.)*
