# AI Assessment Sandbox Configurator (AISC)

The **AI Assessment Sandbox Configurator** is a platform for evaluating and
assessing risks in AI models. It lets you upload models and datasets, configure
and run evaluation plugins, and collect the results.

## ­¤ōÜ Documentation

The official documentation lives in the [**lux-ai-factory/rfc**](https://github.com/lux-ai-factory/rfc)
repository. It explains the **architecture** and the **mission** of the AI
Assessment Sandbox Configurator, describes the **Catalogue** of tests and
controls, and provides a **guide for users**.

As the name suggests, it is also a **Request for Comments**: anyone who wishes to
contribute is warmly invited to share their feedback.

See also:

| Document | What it covers |
| --- | --- |
| [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | Building from source, local development, plugin development, CI/CD and releases |

---

## ­¤ÜĆ Getting Started (users)

Everything below runs the **core platform from published container images**.
You do **not** need to clone the child repositories (backend, webapp, eval) or
build anything locally.

> The companion **Controls** and **Qualification** apps are not part of this
> stack yet and will be added at a later date.

### Prerequisites

- **Docker Engine 24+** (or Docker Desktop) with the **Compose v2** plugin ŌĆö
  i.e. the `docker compose` command.
- **Git**.
- ~5 GB of free disk space for images, containers and volumes.
- A free host port for the platform (default **8080**).

### Run it

```bash
# 1. Clone the parent repository only ŌĆö no submodules needed
git clone https://github.com/lux-ai-factory/aisc.git
cd aisc

# 2. Create your local configuration
cp env.example .env

# 3. Start the platform (pulls pre-built images from ghcr.io)
docker compose up -d
```

The **first** start downloads the images and clones the default evaluation
plugins, so it can take a few minutes. (The bundled plugin downloader is
temporary and will be replaced by the public plugin catalogue.) Track progress
with:

```bash
docker compose ps          # all services should become "running"/"healthy"
docker compose logs -f aisc-backend
```

When the stack is up, open:

**­¤æē http://localhost:8080**

Sign in with the bundled demo Keycloak users (see `keycloak/aisc-realm.template.json`):

| User | Password | Role |
| --- | --- | --- |
| `user` | `user` | regular user |
| `admin` | `admin` | administrator |

> ŌÜĀ’ĖÅ These credentials, and the default passwords in `env.example`, are for
> **local evaluation only**. Change them in `.env` before exposing the stack.

### What you get

| URL | Service |
| --- | --- |
| http://localhost:8080 | **Platform webapp** (evaluations, models, datasets) |
| http://localhost:8080/admin | Django admin |
| http://localhost:8080/api/docs | Backend API (OpenAPI) |
| http://localhost:8080/auth | Keycloak single sign-on |
| http://localhost:8080/flower | Celery / evaluation task monitor |

### Common commands

```bash
docker compose ps                 # status of every service
docker compose logs -f            # follow all logs
docker compose pull && docker compose up -d   # upgrade to newer images
docker compose down               # stop (keeps data)
docker compose down -v            # stop and DELETE all data volumes
```

### Configuration

All settings live in `.env` (created from `env.example`). The most useful ones:

| Variable | Default | Description |
| --- | --- | --- |
| `CADDY_HOST_PORT` | `8080` | Host port the platform is served on |
| `AISC_IMAGE_TAG` | `latest` | Image tag to pull; pin a release (e.g. `v1.3.0`) for a reproducible stack |
| `MISTRAL_API_KEY` / `ANTHROPIC_API_KEY` | *(empty)* | Provider key for the Qualification LLM sidecar |
| `POSTGRES_PASSWORD`, `S3_PASSWORD`, `DJANGO_SECRET_KEY`, `INTERNAL_API_KEY`, `IMMUDB_ADMIN_PASSWORD` | dev values | Change before exposing the stack |
| `AUTH_ENABLED` | `true` | Keycloak authentication for the API |

After editing `.env`, apply the changes with `docker compose up -d`.

### Troubleshooting

- **`denied` / `manifest unknown` / `unauthorized` while pulling images** ŌĆö the
  `ghcr.io/lux-ai-factory/*` packages must be **public** for anonymous pulls.
  If you see this, ask a maintainer to make the packages public, or authenticate:
  ```bash
  echo "$GITHUB_TOKEN" | docker login ghcr.io -u <your-github-user> --password-stdin
  ```
  (The token needs the `read:packages` scope.)
- **Port already in use** ŌĆö set a different `CADDY_HOST_PORT` in `.env`
  (e.g. `8081`) and run `docker compose up -d` again.
- **Apple Silicon (arm64)** ŌĆö the evaluation image is published for `linux/amd64`
  and runs under emulation; expect slower first startup.
- **No evaluation plugins listed** ŌĆö wait for the one-shot `plugin-downloader`
  service to finish (`docker compose logs plugin-downloader`) and then
  `docker compose restart aisc-backend aisc-eval-worker`.
- **Start completely fresh (reset databases and storage)** ŌĆö
  `docker compose down -v && docker compose up -d`.
- **`TLS handshake timeout` / `failed to resolve reference` / `EOF`, while pulling images** —
  this is a *Docker-host network* problem, not a configuration one, and pulls are
  resumable. It is common on WSL2, either because the host resolves image registries to
  IPv6 that is unreachable, or because an MTU mismatch drops large layer downloads.
  Try, in order:
  ```bash
  wsl --shutdown            # from Windows PowerShell, then start Docker again
  docker compose pull       # retry; already-downloaded layers are cached
  ```
  If it persists: lower the MTU (`sudo ip link set dev eth0 mtu 1350` inside WSL — the
  usual fix for `EOF`/resets on large layers), disable broken IPv6
  (`sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1`), or set the MTU/proxy in Docker.

---

## ­¤ōü Repository structure

The parent repository wires together the applications and shared libraries. They
are git submodules so contributors can develop everything side by side, but
**users of the published images never need to clone them**.

### Applications (`apps/`)
*   **Webapp (`apps/webapp`)**: React frontend for the platform.
*   **Backend (`apps/backend`)**: Django API that manages datasets, models and evaluation requests.
*   **Evaluation Service (`apps/eval`)**: Celery worker that executes evaluation tasks via plugins.
*   **Controls (`apps/controls`)**: Next.js app for AI-compliance checklists. _Not part of the default stack yet._
*   **Qualification (`apps/qualification`)**: Next.js app for EU AI Act qualification and system cards. _Not part of the default stack yet._

### Shared libraries (`shared/`)
*   **Plugin Interface (`shared/plugin-interface`)**: the standard interface every AISC plugin implements.
*   **Plugin Manager (`shared/plugin-manager`)**: discovers, loads and runs plugins (used by backend + eval).

### Compose files

| File | Purpose |
| --- | --- |
| **`docker-compose.yml`** | **Users** ŌĆö pulls published images and runs the core platform. |
| `docker-compose-infra.development.yml` + `docker-compose.development.yml` | **Contributors** ŌĆö builds the apps from source with hot reload. |
| `docker-compose.plugin_downloader.yml` | Optional plugin fetcher used by the development flow. |
| `docker-compose.staging.yml`, `docker-compose-infra.staging.yml`, `docker-compose.demo.nbg.yml` | Historical staging / demo deployments. |

---

## ­¤øĀ Developing

Interested in changing the platform itself, or writing evaluation plugins? Start
with the **[Developer Guide](docs/DEVELOPER_GUIDE.md)**.

Quick reference for the two most common contributor workflows:

**Develop a plugin** (run the released stack, mount your local plugin folder):

```bash
# set PLUGIN_PATH=/path/to/your/plugins in env.development
docker compose --env-file env.development \
  -f docker-compose-infra.development.yml \
  -f docker-compose.development.yml up
```

**Develop the core apps** (infra in Docker, apps running locally):

```bash
docker compose --env-file env.development -f docker-compose-infra.development.yml up
# then run backend/webapp/eval from your IDE (see .vscode/ and .run/)
```

Full instructions, including how to tag a release so new images get published,
are in **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)**.

---

## ŌÜĀ’ĖÅ Current limitations & roadmap

The platform currently assumes that both the AI system under test and the test
data are **uploaded into the platform**:

- **Models** are uploaded files stored in the platform's object storage (the web
  UI currently accepts `.onnx`). Assessing a system that runs in your own
  infrastructure, through the API it already exposes, is not yet supported as a
  first-class concept; some evaluation plugins (e.g. StrongREJECT) approximate it
  by taking an API key or base URL in their own configuration.
- **Datasets** must be uploaded through the webapp. Test sets that already live
  in your own permanent storage (S3-compatible, Azure Blob, GCS, ...) cannot yet
  be attached by reference.

Note that the platform's *own* infrastructure is already fully configurable at
deployment time: object storage is any S3-compatible endpoint (`S3_URL`,
`S3_USER`, `S3_PASSWORD`, `S3_*_BUCKET`), the database is any PostgreSQL instance
(`DB_*`), and the broker/cache likewise (`MQ_*`, `REDIS_*`).

**What we are doing about it:** we are introducing **connection profiles**:
configure your storage and your system's API endpoint once, then create datasets
by reference and register models as endpoints, with evaluations connecting
directly to your infrastructure at run time and credentials stored encrypted,
write-only. Progress is tracked in
[lux-ai-factory/aisc#52](https://github.com/lux-ai-factory/aisc/issues/52).

---

## Contributing

We welcome community contributions! Please read our
[CONTRIBUTING.md](CONTRIBUTING.md) for details.

By submitting contributions, you agree to the [Individual CLA](<AISC ICLA (Individuals).txt>)
(or the [Entity CLA](<AISC CCLA (Entities).txt>)) and license your work under
[Apache 2.0](LICENSE.md).

---

## License

This project is licensed under the [Apache License 2.0](LICENSE.md).
┬® 2024ŌĆō2026 Universit├® du Luxembourg and Luxembourg Institute of Science and Technology.
