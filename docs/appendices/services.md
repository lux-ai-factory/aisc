# Appendix 6: Services

Back to [How AISC works](../architecture.md).

Every service the stack runs, by its name in `docker-compose-infra.development.yml` and
`docker-compose.development.yml`, with what it does and what it talks to. A service marked *one-shot* runs at every
start, does its job and exits.

## Gateway and sign-in

| Service | What it does | Talks to |
|---|---|---|
| `caddy` | The gateway and the only published entry: the launcher on 8100, the step applications and the engine on 80, the dashboard on 8188 (443 too on an install served over https). Before passing a request on it asks `oauth2-proxy` whether the caller is signed in, asks the platform to witness every write (the ledger) and, for the admin tools, whether the caller is an admin. | `oauth2-proxy`, `platform`, every service it serves |
| `oauth2-proxy` | Holds the browser's session. Its cookie is set for the host, and cookies ignore ports, so one sign-in covers every port. | `keycloak` |
| `keycloak` | The identity provider, realm `aisc`. Published on `127.0.0.1:8081` only; the browser signs in there. | `postgres` (database `keycloak`) |

## The platform

| Service | What it does | Talks to |
|---|---|---|
| `platform` | The hub: projects and roles, one database per project, the AI card versions, the project's catalogue and installs, connections and the doors tests call the assessed system through, helper models, the AI assistants' keys, the Evidence map, the data of the Collect evidence and Results pages, the dashboards' sync, the ledger. See [How AISC works](../architecture.md#3-the-platform). | `postgres`, `immudb`, `aisc-backend`, `plugin-publisher`, `devpi`, `dashboard`, `report-composer`, the hosted catalogue, the assessed systems |
| `ledger-pool` | *One-shot.* Makes immudb databases ahead of time (only immudb's superuser may, and the platform never holds that password), gives waiting projects theirs, and makes the engine's own immudb account. | `immudb`, `postgres` |
| `plugin-publisher` | Builds a test's package, from its repository on github.com/lux-ai-factory or from your folder in `local_plugins/`, as an unprivileged user with no secrets, and uploads it to `devpi`. At start it publishes the plugin interface. | github.com, `devpi` |
| `devpi` | The stack's own package index, where tests are installed from. Kept in the volume `devpi_data`. | |

## Step 1: qualification (`apps/qualification`)

| Service | What it does | Talks to |
|---|---|---|
| `qualification-web` | The questionnaire, the AI card pages and their versions (Next.js). | `platform`, `aisc-backend` (lists the engine's components), the four services below, `postgres` |
| `qualification-prefill` | Turns an uploaded document into proposed answers, with text rules only (no model). Stores nothing. | |
| `qualification-agents` | The card agent, an AI assistant: drafts the card's techniques from the prose answers and critiques its own draft, with one model in two roles. | `qualification-web`, `qualification-ontology`, `platform` (the project's model and key), the model's provider |
| `qualification-ontology` | Builds the AI card's graph (AIRO, typed with VAIR) from the answers, the agent's draft and your corrections. No model. | |
| `qualification-pdf` | Renders the AI card as PDF. | |
| `qualification-migrate` | *One-shot.* Brings every project database's `qualification` schema up to date. | `postgres` |

## Step 2: control objectives (`apps/control-objectives`)

| Service | What it does | Talks to |
|---|---|---|
| `control-objectives` | Risk ratings, the risk and control matrix, the AI risk mapper (an AI assistant), priority objectives, objective sets and profiles. | `platform`, `qualification-web` (the AI card as JSON-LD), the model's provider, `postgres` |
| `control-objectives-migrate` | *One-shot.* Brings every project database's `control_objectives` schema up to date. | `postgres` |

## Step 3: catalogue (`apps/catalogue`)

| Service | What it does | Talks to |
|---|---|---|
| `catalogue-private` | The catalogue's pages, served under `/project-catalogue/` on the launcher's port. Static: the data comes from the platform's `/api`. | |

The public catalogue's data is the hosted one (https://sandboxconfigurator.aifactory.lu/catalogue), read by the
platform.

## Step 4: checklists, tests, results, report

| Service | What it does | Talks to |
|---|---|---|
| `controls-web` | The checklists (Next.js). | `platform` (rights, checklist packages), `controls-pdf`, `postgres` |
| `controls-pdf` | Renders a checklist's answers as PDF. | |
| `controls-migrate` | *One-shot.* Brings every project database's `controls` schema up to date. | `postgres` |
| `aisc-webapp` | The engine's pages (React, static). | (the browser calls `aisc-backend`) |
| `aisc-backend` | The engine's API (Django): datasets, models, plugins, evaluations and their results. Queues test runs. | `postgres`, `minio`, `rabbitmq`, `redis`, `devpi`, `immudb` (its own audit log), `platform` |
| `aisc-backend-migrate` | *One-shot.* Brings every project database's `engine` schema up to date and grants the readers. | `postgres` |
| `aisc-backend-ledger` | Every 10 seconds, sends the engine's ledger events from each project database to the platform. | `platform` |
| `aisc-eval-worker` | Runs tests (Celery): installs a test's package in a fresh environment, runs it, sends the results back. | `rabbitmq`, `redis`, `aisc-backend`, `devpi`, `platform` (run pass, connections, helper models), helper model endpoints |
| `aisc-eval-flower` | The monitor of the test runs' task queue, for admins (`inspect` profile). | `rabbitmq` |
| `rabbitmq` | The queue that carries test runs to the worker. | |
| `redis` | Where the worker keeps task results. | |
| `minio`, `make_buckets` | S3 storage: buckets `datasets`, `models`, `artifacts`. `make_buckets` (*one-shot*) creates them. | |
| `dashboard` | Superset with AISC's extension: one dashboard per test per project, comments and review requests. | `postgres` (database `superset`, the project databases read-only), `dashboard-redis`, `platform` |
| `dashboard-migrate` | *One-shot.* Superset's migrations. | `postgres` |
| `dashboard-redis` | Superset's own cache, with a password, on a network only the dashboard's services join. | |
| `report-composer` | Layouts, templates, generating reports and keeping them. | `postgres`, `report-renderer`, `platform` |
| `report-composer-migrate` | *One-shot.* Brings every project database's `report_composer` schema up to date. | `postgres` |
| `report-renderer` | Draws a report as PDF or Word. Reads the data itself, read-only. | `postgres` as `report_ro` (`platform`, the project databases, `superset`) |
| `report-grants` | *One-shot.* Grants `report_ro` what the report reads. | `postgres` |

## Storage and admin tools

| Service | What it does |
|---|---|
| `postgres` | PostgreSQL: databases `platform`, one `project_<pid>` per project, `keycloak`, `superset`, `ledger_identity`. Publishes nothing unless `AISC_ADMIN_PORTS=on`. |
| `postgres-setup` | *One-shot.* Applies the roles and grants on a volume that already exists. |
| `immudb`, `immudb-key` | The tamper-evident ledger; `immudb-key` (*one-shot*) hands immudb its signing key. |
| `pgadmin` | Browse and query every database, for admins, at `/inspect/pgadmin/` (`inspect` profile). |
| `schema-docs` | Database diagrams (structure, never rows), at `/inspect/schema/` (`inspect` profile). |

## Networks

| Network | Who is on it |
|---|---|
| `backend` | every service except the static pages, the inspector tools and the dashboard's cache |
| `frontend` | `caddy` and the services it serves |
| `inspector` | `caddy`, `postgres`, `pgadmin`, `schema-docs` |
| `dashboard` | `dashboard`, `dashboard-migrate`, `dashboard-redis` |

The worker, which runs test code, is on `backend`. See [Security](security.md) for what that means.
