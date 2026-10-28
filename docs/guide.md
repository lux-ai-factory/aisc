# AISC in detail

The [README](../README.md) says what AISC is and how to install it. This guide covers the rest: the
components, how the stack works, the details of installing and running it, configuration and tests.

## Components

Submodules (each has its own README):

| path | what it is |
|---|---|
| [`apps/qualification`](../apps/qualification) | step 1: the EU AI Act qualification questionnaire (Next.js) that produces the AI card, with its agents, PDF, prefill and ontology sidecars |
| [`apps/control-objectives`](../apps/control-objectives) | step 2: the catalogue of control objectives, the rating of the risks and their links to the objectives |
| [`apps/catalogue`](../apps/catalogue) | step 3: the catalogue's pages (service `catalogue-private`) and the `devpi` package index the tests install from (the aisc-catalogue-web repository); the catalogue's data is the hosted instance's, read through the platform |
| [`apps/backend`](../apps/backend) | step 4: the execution engine's Django API (datasets, models, plugins, evaluations) |
| [`apps/eval`](../apps/eval) | step 4: the engine's Celery worker that installs and runs plugins |
| [`apps/webapp`](../apps/webapp) | step 4: the engine's React frontend |
| [`apps/controls`](../apps/controls) | step 4: the compliance checklists (controls) a project answers |
| [`apps/results-dashboard`](../apps/results-dashboard) | step 5: Apache Superset configured for AISC results |
| [`apps/report-generator`](../apps/report-generator) | step 6: the report renderer (HTML, PDF, DOCX), service `report-renderer` |
| [`shared/plugin-interface`](../shared/plugin-interface) | the Python library every evaluation plugin implements |
| [`shared/plugin-manager`](../shared/plugin-manager) | the library that discovers, installs and loads plugins |
| [`shared/report-plugin-interface`](../shared/report-plugin-interface) | the interface of the report renderer's plugins |

Part of this repository:

| path | what it is |
|---|---|
| `platform/` | the platform service (FastAPI, service `platform`): projects, members and roles, one database per project, the AI system and its card versions, connections to systems under test, per-project LLM keys, evidence links, the ledger |
| `apps/report-composer/` | step 6: assembles a report from modules and asks the renderer for the document ([README](../apps/report-composer/README.md)) |
| `shared/identity/` | `aisc_identity`, shared by every Python service: who is calling (gateway headers, Keycloak tokens), what they may do in a project (`access`, held to `access-cases.json`), which service is calling (`service_tokens`), and the ledger event a change writes (`ledger_events`) |
| `shared/access-ts/` | The TypeScript client of the platform's `/authz/projects/{ref}`, vendored into qualification and controls |
| `shared/ledger-ts/` | How the Next.js apps write a ledger event, vendored into qualification and controls |
| `homepage/` | the launcher pages served by Caddy on port 8100: the project list, a project's page (Plan the assessment, then Collect evidence), the Collect evidence page, Manage pages |
| `dashboard-gateway/` | the Superset config overlay that takes the user from the gateway's token |
| `Caddyfile` | the gateway's routes |
| `init/` | SQL run once by `postgres-setup`: databases, roles and grants |
| `scripts/` | setup (`secrets.sh`), checks against a running stack (`verify*.sh`), tests of the stack's configuration (`scripts/tests`) |
| `keycloak/` | the realm export (template) and the login theme |
| `inspector/` | pgAdmin and SchemaSpy, for admins, at `:8100/inspect/` |
| `infra/minio/` | builds MinIO from source |
| `def_plugins/`, `local_plugins/` | `def_plugins/` is no longer used by `start` (see its README); `local_plugins/` holds your own plugin sources (`PLUGIN_PATH`) |
| `local_controls/` | checklists every project catalogue gets next to the public catalogue's (mounted into the platform) |
| `adapters/` | your adapter plugins: protocols a connection can use besides the built-in ones (mounted into the platform; only its README is in git) |
| `docs/` | design history; not needed to run anything |

## How it works

```
browser ──> Caddy :80   (engine, /qualification, /control-objectives, /controls, /report-composer, /api, /flower for admins)
            Caddy :8100 (launcher pages, /api/* -> platform)
            Caddy :8188 (dashboard, Superset)
              │ forward_auth on every request
              ├──> oauth2-proxy ──> Keycloak :8081 (realm aisc)
              └──> the module's container
modules ──> PostgreSQL: database `platform` (projects, members, report presets) + one `project_<pid>` per project
platform ──> immudb (ledger), the dashboard's bridge, the engine
engine ──> immudb (its own audit log: database auditdb, user aisc_engine)
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
- **Installing tests and controls.** Step 3 is a catalogue, chosen once per project, shown in the
  catalogue's own pages served by this stack under `/project-catalogue/` on the launcher (service
  `catalogue-private`), which read it through the platform. A public project reads the hosted
  catalogue (https://sandboxconfigurator.aifactory.lu/catalogue) live. A private one is a copy kept in
  the project's own database, with this stack's own plugins as Local entries and Update from public
  for admins. Both can be filtered by the project's dimensions, and their test Install buttons offer
  what this stack's index has. A control's Install button installs the checklist into the controls
  app, which asks the platform for its package; the platform answers from the project's catalogue.
  Tests are installed into the engine from the stack's own package index, `devpi`
  (`PACKAGE_REGISTRY_URL=http://devpi:3141` in `env.plugin_downloader`), which is kept in the
  `devpi_data` volume, so it survives restarts. At start `plugin-publisher` puts only the shared plugin
  interface on it. A test's plugin is fetched when an admin installs it from the catalogue: the platform
  asks `plugin-publisher` to clone the plugin's repo from github.com/lux-ai-factory (its
  `feat/unified-modules` branch where it has one, its default branch otherwise), build it and upload it,
  and then installs it. So installs need GitHub reachable from the stack, and the first install of a test
  takes about a minute (later installs of the same version reuse what is on the index). Builds run one
  at a time, as an unprivileged user with no secrets. The public plugin repos need nothing more; the
  private ones (agentseal, counterfactual, evasion, example, luxeval, uncertainty) need a `GITHUB_TOKEN`
  that can read them, which you add to `env.secrets` (it goes to `plugin-publisher` only). Without it
  their install fails with "could not fetch <repo>: ...; nothing was installed". A plugin that fails to
  build is named, with its error, in the install dialog and in the log of `plugin-publisher`. A container's
  name is the service's name behind the install's prefix, `aisc-<id>-plugin-publisher`: `docker ps -a`
  lists them, and `docker logs` takes that name.
  Controls are installed by the controls app from the catalogue's API.
- **What a test assesses, and the models that help it.** A test's target is what it assesses: the AI
  system or one component its AI card lists ("What is assessed (AI card)" in the evaluation form), or a
  local model file uploaded in step 4's Settings ("What is assessed (local model file)"). Each plugin
  declares which of the two it accepts (`@assesses`, section 13 of the plugin interface's
  `PLUGIN_DEVELOPER_GUIDE.md`), and the form offers only those. Runs on a local model file are listed
  apart under step 4's Results, never counted with the AI card's results or put in its reports. A helper model is a model a test uses
  as a tool, a judge, an attacker, a grader, an embedder or a generator, and is never what is assessed:
  the form asks for one per role ("Helper model · Judge (not assessed)"). The datashape role `target`
  of a dataset column (beside `feature`, `date` and `ignore`) marks the label column, the outcome each
  row records; it names no target.
- **The assessed system over the network.** Under a project's **Manage > Components and connections** an admin
  registers the AI systems the project assesses (OpenAI-compatible, A2A, Open Inference Protocol, or
  a REST API with a request template). A plugin reaches a connection through the platform. Calls to
  internal addresses are refused unless a project's owners allow them on that page, or the
  deployment allows them for every project with `CONNECTIONS_ALLOWED_HOSTS` on the `platform`
  service.
- **The dashboard** is Superset on its own port (it needs the site root). It has no login of its
  own: `dashboard-gateway/` turns the gateway's token into Superset's `REMOTE_USER`. It runs on the
  compose network like everything else (no service uses the host network, so the stack also runs where
  Docker runs in a VM, as Docker Desktop does on macOS and Windows) and publishes nothing: Caddy reaches
  it as `dashboard:8189`. Superset's cache is its own Redis, `dashboard-redis`, with a password
  (`DASHBOARD_REDIS_PASSWORD`, made by `scripts/secrets.sh`) and on a network only `dashboard`,
  `dashboard-migrate` and `dashboard-redis` join, because Superset unpickles what it reads from its cache:
  the shared Redis, which the eval worker (plugin code) reaches, is not used for it.
- **The launcher's links** to the engine, Keycloak and the dashboard take this install's addresses: the
  gateway answers `/origins.json` on the launcher's port (no sign-in; public addresses only) from
  `API_URL_EXTERNAL`, `KEYCLOAK_URL_EXTERNAL` and `DASHBOARD_EXTERNAL_URL`, and
  `homepage/assets/origins.js` sets every link marked `data-origin` from it. Until it answers, or when it
  cannot, the links use the page's own host with the local defaults (`:8081` for Keycloak, `:8188` for
  the dashboard).
- **The ledger** (immudb) records from the first project: every write is witnessed by the gateway
  (who did it) and the apps that log write their events in the same transaction as the change; the
  platform's relay moves them into the project's own immudb database. Manage > Logs > Activity log
  shows a project's entries; owners and admins can export them and check the file offline with
  `scripts/verify-ledger-export.py`. The `ledger-pool` one-shot makes those databases ahead of time,
  at every start. Not every module logs yet: the engine's test runs (and some install paths) are not
  in the ledger. Set `LEDGER_MODE=off` and `LEDGER_GATEWAY=off` to run without it. With the
  witness on, a write needs the platform service to be up (reads don't). The engine keeps its own
  audit log outside the platform ledger: immudb database `auditdb`, written as its own user
  `aisc_engine` (`ENGINE_IMMUDB_PASSWORD`), which `ledger-pool` makes with read on `defaultdb` and
  SELECT, CREATE, INSERT on `auditdb`; admins read it at the engine's `/api/v1/audit`. The dashboard
  writes nothing to immudb: Superset keeps its actions in its own action log, and comments and reviews
  reach the ledger through the platform. Only `immudb` and `ledger-pool` hold immudb's superuser
  password (`IMMUDB_ADMIN_PASSWORD`); `scripts/verify-immudb.sh` checks this on the running stack.
  The engine logs in to immudb again whenever immudb has ended its login. immudb ends a login
  token after `IMMUDB_TOKEN_EXPIRY_TIME` minutes, set to a year (`525600`) instead of immudb's day to keep
  that rare, and at every immudb restart, so compose restarts `aisc-backend` whenever it restarts `immudb`.
  The engine's audit clerk also logs in again by itself when a call fails because the login ended
  (`apps/backend/aisc_backend/audit/clerk.py`), so an immudb restarted outside compose
  (`docker restart aisc-<id>-immudb`, this install's immudb container, or `docker restart immudb` on an
  install made before ids; or Docker itself restarting) needs no restart of `aisc-backend`. The
  trade-off: a token, held only in the memory of the services that logged in, stays valid for a year
  unless immudb restarts. If `scripts/verify-rbac.sh`'s audit check FAILs, the cause is immudb itself
  (down, or refusing the engine's account); `scripts/verify-immudb.sh` shows which.
- **Ports.** Only 80, 8100 and 8188 are published to the network (443 too on an install served over
  https), and each answers an anonymous request with a redirect to Keycloak. Keycloak (8081) is bound to
  `127.0.0.1`. PostgreSQL, Redis, RabbitMQ, MinIO and immudb publish nothing by default: the services reach
  them on the compose network. To reach them from the host (pgAdmin, psql, redis-cli), set
  `AISC_ADMIN_PORTS=on` first (see the table below); they then answer on `127.0.0.1`, ports 5432, 6379,
  5672, 9000 and 3322. `dashboard-redis` publishes nothing. `scripts/verify-sso.sh` checks this.

## Install and run, in detail

The steps themselves are in the [README](../README.md#install-and-run). What they do:

- **Submodules.** `git submodule update --init --recursive` also restores the pinned submodule commits
  after a checkout. `git submodule update --remote` moves each submodule to the tip of the branch it
  tracks instead, which is an update, not a repair.
- **Secrets.** `./scripts/secrets.sh` writes `env.secrets` (git-ignored), combines it with
  `env.plugin_downloader` into `env.runtime` and makes immudb's signing key pair. The realm is imported
  from `keycloak/aisc-realm.json` as it is in git: Keycloak fills `${GATEWAY_CLIENT_SECRET}` and the
  passwords of its two accounts from its environment. The `immudb-key` job hands immudb its copy of the key, so no file ACL is needed (macOS
  has no `setfacl`). Run it again after a pull: it
  keeps existing values and adds any new secret. `--rotate` replaces them (except the ones stored data
  depends on, see the top of the script); `--add-ledger-key` adds a version of the ledger's key.
  `LEDGER_IMMUDB_PASSWORD` and `ENGINE_IMMUDB_PASSWORD` survive `--rotate` (immudb holds their users'
  copies).
  The infrastructure's own passwords (`POSTGRES_PASSWORD`, `S3_PASSWORD`, `RABBITMQ_PASSWORD`,
  `KEYCLOAK_ADMIN_PASSWORD`, and `AISC_ADMIN_PASSWORD` / `AISC_USER_PASSWORD` for the realm's `admin` and
  `user` accounts) are generated too, and `--rotate` keeps them: their images apply them only when the
  volume is first made. An install made before they were generated keeps the values it runs on (its
  `env.runtime`'s, else the old committed ones): `secrets.sh` writes those into `env.secrets`, never new
  ones, so such an install stays on well-known passwords until each is rotated. A new install gets
  random ones.
- **Rotating an infrastructure password.** `./scripts/rotate-infra-password.sh NAME` (one of the six
  above) sets a new value in the running service first (`ALTER ROLE`, `rabbitmqctl change_password`,
  Keycloak's `kcadm.sh`), then in `env.secrets` and `env.runtime`; a service that refuses leaves both files
  as they were. Then `docker compose ... up -d` recreates what reads it; MinIO takes its new root password
  there. With `--ask` it sets a password you type (twice, never shown) instead of a random one: at least
  12 characters, without spaces, quotes, `$`, `#` or `\`.
- **Rotating immudb's passwords.** `./scripts/secrets.sh --rotate-one NAME` writes a new
  `IMMUDB_ADMIN_PASSWORD`, `LEDGER_IMMUDB_PASSWORD` or `ENGINE_IMMUDB_PASSWORD` and changes nothing else.
  Then recreate `immudb`, `ledger-pool`, `platform` and `aisc-backend` (`docker compose ... up -d immudb
  ledger-pool platform aisc-backend`): immudb applies its superuser's password at start
  (`IMMUDB_FORCE_ADMIN_PASSWORD`), and `ledger-pool`, as the superuser, gives `aisc_ledger` and
  `aisc_engine` their new ones and must exit 0. Then `docker compose ... restart aisc-backend`, whichever
  name was rotated: `up -d` leaves an unchanged aisc-backend running, and immudb's restart ended its audit
  session, which the engine does not open again by itself (its audit writes fail until it restarts). The
  platform's ledger writes fail for the seconds between its restart and ledger-pool's run, then recover by
  themselves.
- **Start order.** Compose orders the start itself: `postgres-setup` runs `init/` and the one-shot
  `*-migrate` services migrate each module before it starts, and `ledger-pool` makes the ledger's
  databases. The first start takes several minutes (it builds every image, and compiles MinIO from
  source because MinIO publishes no community images).
- **One install at a time; stop and remove.** `start` refuses while another install's stack runs, and names
  its folder and the command that stops it (its data kept). `uv run scripts/aisc.py stop` stops this
  install's containers, data kept; `start` brings them back. `uv run scripts/aisc.py remove` deletes this
  install's containers, networks and volumes (`down -v` on its own stack) after you type the folder's name.
  Both act on this folder's stack only: they refuse, naming the folder, when a container of the stack was
  made from another folder, and `remove` refuses a stack with no container left unless its name holds this
  install's id (every install made before ids names its stack `aisc`); it then says how to list and delete
  the volumes by hand.
- **A project's page** shows two blocks: **Plan the assessment** (1 Qualify the AI system, 2 Set control
  objectives, 3 Choose tests and checklists) and below it **4 Collect evidence**, where checklists are
  answered, tests run, results are looked at and the report is composed.
- **Serving over HTTPS.** Caddy serves HTTPS when `CADDY_DOMAIN` starts with `https://`
  (`CADDY_ENVIRONMENT=development`: a certificate from Caddy's own local authority; `staging`: the
  certificate files the Caddyfile names). Set `GATEWAY_COOKIE_SECURE=true` with it, so the gateway's
  session cookie is never sent over plain HTTP, and `API_URL_EXTERNAL` to the same `https://` address.
  This stack is still wired to `localhost` in places a hosted install has to change too: the gateway's
  `--cookie-domain` and `--whitelist-domain`, and `KEYCLOAK_URL_EXTERNAL` (Keycloak is published on
  `127.0.0.1:8081`, without TLS).
- **Accounts.** The realm has two development accounts, `admin` (realm role `admin`) and `user`, with the
  passwords `AISC_ADMIN_PASSWORD` and `AISC_USER_PASSWORD` from `env.secrets`; the checks sign in with
  them too (`scripts/lib/dev-accounts.sh`). The Keycloak console's account is `admin` with
  `KEYCLOAK_ADMIN_PASSWORD` from `env.secrets`. The console is on `127.0.0.1:8081` only.
- **Checks.** `./scripts/verify.sh --stack` runs `verify-db-access.sh`, `verify-project-databases.sh`,
  `verify-sso.sh`, `verify-rbac.sh` and `verify-plugins.sh` against the running stack.
  `verify-project-databases.sh` (and `verify-db-consistency.sh`) read Postgres from this machine, on
  `127.0.0.1:5432`, which is published only with `AISC_ADMIN_PORTS=on` (in the environment or `env.local`,
  then `start`); without it they say so and fail. The checks that
  need platform projects make them once (`verify probe`, `verify rbac scratch`, `verify isolation A` and
  `B`, `verify plugins`) and reuse them: a project keeps its ledger database for good, deleted or not, so
  one made per run would use up the ledger pool.
  `verify-db-access.sh` makes one probe project and deletes only that one (also when interrupted); a
  check whose probe cannot run (a missing database, a failed query, an unreadable bundle) is a FAIL,
  never a PASS. `verify.sh --superset-upgrade [image]` checks the stack's own Superset image (the
  `FROM` line of `apps/results-dashboard/Dockerfile`) unless an image is given.
  `verify-plugins.sh` is the one to run before a demo: it checks that `plugin-publisher` is up and has
  published the shared interface, installs every plugin on the stack's index into its own project
  (`verify plugins`), and checks that the private catalogue offers each one with a blue, installable
  entry. `verify-plugins.sh --install langbite` also installs that catalogue entry as the admin, which
  fetches its repo from GitHub and builds it (about a minute); the admin password is read from the
  environment, never from the command line.
- **Optional model keys**, for steps 1 and 2 to suggest answers: `MISTRAL_API_KEY` or
  `ANTHROPIC_API_KEY` for qualification; control objectives defaults to a local Ollama on the host and
  takes `CONTROL_OBJECTIVES_LLM_PROVIDER` plus that provider's key instead. Per-project keys for the
  card agent and the risk mapper are set in the UI under **Manage > AI assistants > AI assistant models and keys**.
- **Host tools for tests:** [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 for the platform
  and the report composer).

Other addresses: the engine at http://localhost/, its API at `/api`, Keycloak at http://localhost:8081
(realm `aisc`, this machine only), the dashboard at http://localhost:8188. Flower, the eval worker's
Celery monitor, is at `/flower/` for admins only (it shows every project's task arguments and results),
and runs only under the compose profile `inspect` (`docker compose --profile inspect up -d
aisc-eval-flower`); without it the page says so. Its link is in a project's Manage menu, for admins.

### Your own plugins

`PLUGIN_PATH` (`./local_plugins/` in `env.plugin_downloader`) is mounted into the engine and the
eval worker as `/app/plugins`, where they discover plugin source trees. See
[`local_plugins/README.md`](../local_plugins/README.md) and the plugin developer guide in
`shared/plugin-interface`.

### Your own controls

Checklists in `local_controls/` (one control or a list per `*.json`, in the catalogue's seed format) join
every project catalogue: a public one reads them live, a private one copies them when the project chooses it
and each time an admin presses Update; they
show under Source = Local and install like any control. `scripts/start.sh` lists them at the end of a
start. A public entry with the same slug wins. See [`local_controls/README.md`](../local_controls/README.md).

### Your own protocols

A system that speaks none of the built-in protocols (REST, OpenAI-compatible, A2A, Open Inference Protocol) is
reached through an adapter: a folder in `adapters/` whose `adapter.py` declares a protocol and translates one call.
After a platform restart the protocol is offered when you connect a component, and tests reach the system
through it unchanged. Only `adapters/README.md` is part of AISC; your adapters stay out of git. See
[`adapters/README.md`](../adapters/README.md).

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
devpi. The webapp is on http://localhost:8080, the API on http://localhost:8000. Both are published on
127.0.0.1 only: standalone has no sign-in, so anyone who reached them could create projects and run
plugins. To develop one of the engine's apps on the host, see that submodule's README.

### Other compose files

`docker-compose-infra.staging.yml` and `docker-compose.staging.yml` are older deployment files for the
engine alone and are not used by the stack above.

### PostgreSQL 15

Every stack runs PostgreSQL 15 (the backend requires it): development, the standalone engine and
staging (`docker-compose-infra.staging.yml`). A data directory made
by PostgreSQL 14 does not start under 15, so moving from 14 needs fresh volumes on each of them,
staging included (`down -v`, which deletes the data); no data migration is provided.

## Configuration

Settings are in `env.plugin_downloader` (committed, no secrets) and secrets in `env.secrets` (made by
`scripts/secrets.sh`); compose reads both through `env.runtime`. Each service's variables are in the
compose files and in its own README (for the report composer,
[apps/report-composer/README.md](../apps/report-composer/README.md)). Settings an installer is most
likely to change:

| variable | where | meaning | default |
|---|---|---|---|
| `CADDY_DOMAIN` | `env.plugin_downloader` | the gateway's origin | `http://localhost` |
| `API_URL_EXTERNAL` | `env.plugin_downloader` | the engine as the browser reaches it (webapp, launcher links) | `http://localhost` |
| `KEYCLOAK_URL_EXTERNAL` | `env.local` (see the address row below) | Keycloak as the browser reaches it (webapp, launcher links) | `http://localhost:8081` |
| `DASHBOARD_EXTERNAL_URL` | `caddy`, `report-renderer`, `platform` (`env.local`, see the address row below) | the dashboard as the browser reaches it (launcher links, report links, plugin tile links) | `http://localhost:8188` |
| `KEYCLOAK_ADMIN` | `env.plugin_downloader` | Keycloak's bootstrap admin | `admin` |
| `GATEWAY_COOKIE_SECURE` | `env.plugin_downloader` | the gateway's session cookie is Secure: `true` when `CADDY_DOMAIN` is `https://` | `false` |
| `KEYCLOAK_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, `S3_PASSWORD`, `RABBITMQ_PASSWORD` | `env.secrets` | the infrastructure's own passwords, generated; kept by `--rotate`; an install made before keeps the values it runs on; changed by `rotate-infra-password.sh` | generated |
| `AISC_ADMIN_PASSWORD`, `AISC_USER_PASSWORD` | `env.secrets` (keycloak, the checks) | the realm's `admin` and `user` accounts, put into the realm at import; like the row above | generated |
| `DASHBOARD_INTERNAL_PORT` | `caddy`, `platform`, `dashboard` | Superset's port on the compose network (`dashboard:<port>`), not published | `8189` |
| `GITHUB_TOKEN` | `plugin-publisher` (you add it to `env.secrets`) | a GitHub token that can read lux-ai-factory's private plugin repos | empty: installing a private plugin fails |
| `PLUGIN_PUBLISHER_TOKEN` | `platform`, `plugin-publisher` (made by `start`) | the token the platform presents when it asks the publisher to fetch a plugin | generated |
| `PLATFORM_ENGINE_TOKEN` | `platform`, `aisc-backend` (made by `start`) | the token the engine presents when it asks the platform whether a card target has a connection | generated |
| `PLUGIN_PATH` | `env.plugin_downloader` | your plugin sources, mounted into the engine | `./local_plugins/` |
| `PACKAGE_REGISTRY_URL` | `env.plugin_downloader` | the index the engine installs plugins from | `http://devpi:3141` |
| `CATALOGUE_EXTERNAL_URL`, `CATALOGUE_API_URL` | `env.plugin_downloader` | the hosted catalogue's page and API | `https://sandboxconfigurator.aifactory.lu/...` |
| `CONNECTIONS_ALLOWED_HOSTS` | `platform` | internal hosts every project's connections may call (comma list) | empty |
| `PLATFORM_FACADE_THREADS` | `platform` | how many calls to systems under test the protocol endpoints run at once, in threads of their own (more wait), so slow systems cannot take the threads every other request needs | `16` |
| `MODEL_LISTING_SSL_VERIFY` | `env.plugin_downloader` | the engine checks TLS when it lists a provider's models; a provider behind a self-signed certificate fails to list until this is `False` | `True` |
| `PLATFORM_OLLAMA_BASE_URL` | `platform` | where a project's Ollama choice is reached | `http://host.docker.internal:11434` |
| `MISTRAL_API_KEY`, `ANTHROPIC_API_KEY` | qualification, control objectives | hosted model keys | empty |
| `CONTROL_OBJECTIVES_LLM_PROVIDER` | `control-objectives` | the model provider for suggestions | `ollama` |
| `LEDGER_MODE`, `LEDGER_GATEWAY` | every app that logs, `caddy` | the immudb ledger: `record` / `on`, or `off` / `off` to run without it | `record`, `on` |
| `LEDGER_POOL` | `ledger-pool` | how many free ledger databases (one per new project) are kept ready, refilled at each start | `50` |
| `ENGINE_IMMUDB_PASSWORD` | `env.secrets` (aisc-backend as `IMMUDB_PASSWORD`, `ledger-pool`) | the engine's own immudb user, aisc_engine; kept by `--rotate`, changed by `--rotate-one` | generated |
| `AISC_IMAGE_TAG` | all built images | the tag of locally built images | `latest` |
| `ENGINE_PORT`, `HOMEPAGE_PORT_EXTERNAL`, `DASHBOARD_PORT_EXTERNAL`, `KEYCLOAK_PORT_EXTERNAL` | `env.local` (written by `aisc.py start`, git-ignored) | the four browser ports: steps 1 and 2, the launcher, the dashboard and the sign-in. `start` checks them before building. When one is taken, an install not served over https moves to a free one and keeps it; an https install stops instead. Edit `env.local` to choose a port yourself | `80`, `8100`, `8188`, `8081` |
| `API_URL_EXTERNAL`, `LAUNCHER_EXTERNAL_URL`, `DASHBOARD_EXTERNAL_URL`, `KEYCLOAK_URL_EXTERNAL` | `env.local` | the address of each browser port, as the browser reaches it. `start` writes the address next to a port it moved, on plain http only. `env.local` comes last in `env.runtime`, so it wins over `env.plugin_downloader`. For an install served from another host, set these four in `env.plugin_downloader` (an https install does so; `start` writes no address for it) | `http://localhost`, `http://localhost:8100/`, `http://localhost:8188`, `http://localhost:8081` |
| `AISC_ADMIN_PORTS` | the environment or `env.local` | `on` adds `docker-compose.admin-ports.yml`, which publishes PostgreSQL (5432), Redis (6379), RabbitMQ (5672), MinIO (9000) and immudb (3322) on `127.0.0.1`, for tools on the host such as pgAdmin or psql. Nothing else needs them | unset: not published |
| `ENGINE_HTTPS_PORT` | `env.local` | port 443's setting, in `docker-compose.https.yml`. `start` adds that file only when `CADDY_DOMAIN` is an https address, so a taken 443 never stops an install on plain http | `443` |
| `AISC_INSTALL` | `env.secrets` (written with it by `start` or `secrets.sh`) | this install's id, six hex characters: its stack is `aisc-<id>`, its volumes `aisc-<id>_*`, its containers `aisc-<id>-<service>`. Kept by `--rotate`; do not edit or delete it (the install would fall back to the stack `aisc` and lose sight of its data). An install made before ids has none and keeps the stack `aisc` and the bare container names | generated for a new install |
| `CONTAINER_PREFIX` | `env.runtime` (made from `AISC_INSTALL`) | what every container's name starts with, `aisc-<id>-`; compose puts it before each `container_name` | `aisc-<id>-`; unset (bare names) for an install made before ids |
| `AISC_PROJECT` | the environment (`aisc.py`, the scripts) | the Compose project (stack) name, for a second copy beside an install's data. Unset, the stack is `aisc-<id>` from `AISC_INSTALL` | `aisc-<id>`; `aisc` for an install made before ids |

On every start, `start` tells the sign-in (Keycloak) the install's addresses, so a port that moved is
also the address people are sent back to after they sign in.

The secrets themselves (gateway cookie and client secrets, service tokens, database role passwords,
`PLATFORM_SECRETS_KEY` that encrypts stored LLM keys, the ledger keys, `DASHBOARD_REDIS_PASSWORD`) are listed with their purpose
in `scripts/secrets.sh`. Never commit `env.secrets`, `env.runtime` or `immudb-signing.key`.

## Tests

The tests never need the running stack. **Never point a test at the live database** (PostgreSQL on
`127.0.0.1:5432` of the running stack, which exists only with `AISC_ADMIN_PORTS=on`): tests that need a database get a throwaway container of
their own (`aisc-t-*`, `postgres:15-alpine` through `scripts/lib/throwaway-pg.sh` or
`scripts/lib/report_bed.py`) on a port the kernel picks, removed afterwards.

The harnesses in `scripts/tests` migrate their throwaway project databases with each module's own
migration scripts, so a fresh clone needs those modules' dependencies first:

```bash
scripts/prepare-tests.sh
```

It needs Node.js 20 and uv; rerun it after pulling, and `scripts/prepare-tests.sh --check` lists what is missing.

From the repository root:

```bash
# the stack's configuration (Caddyfile, compose files, init SQL, pages, scripts), read as text,
# plus harnesses that start throwaway Postgres containers with docker run
uv run --with pytest --with pyyaml --with 'psycopg[binary]' pytest -q -p no:cacheprovider scripts/tests

# the platform service, every test including the database ones, against a throwaway PostgreSQL
# (extra arguments go to pytest)
scripts/test-platform.sh -q

# the platform service without a database: its database tests skip
cd platform && uv run --extra dev pytest -q -p no:cacheprovider tests --ignore tests/ledger

# the identity library
scripts/lib/identity-tests.sh            # with a throwaway Postgres for the access tests

# the engine (apps/backend) without upstream's integration package, which needs a live stack;
# --postgres: its project database tests on a throwaway Postgres, in configurator mode
scripts/lib/engine-tests.sh

# the report composer (starts throwaway Postgres containers)
cd apps/report-composer && uv run --extra dev pytest -q

# the dashboard's gateway config (the root suite also runs it, in its own uv environment)
cd dashboard-gateway && uv run --with pyjwt --with cryptography python -m unittest test_gateway_identity
```

The platform's database tests use `PLATFORM_TEST_DATABASE_URL` only (a throwaway database; a URL on
port 5432 is refused) and skip when it is not set; they never use the stack's `PLATFORM_DATABASE_URL`. Tests that need
a superuser (making project databases) also need `PLATFORM_TEST_SUPERUSER_URL` for the same throwaway
server. `scripts/test-platform.sh` sets them for the server it starts and removes it on exit; its
ledger tests also read the canonical vectors in `apps/qualification` and `apps/controls`, so those
submodules must be checked out. `./scripts/verify.sh --modules` runs every module's suite whose dependencies are installed.
