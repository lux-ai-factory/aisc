# Appendix 5: Manage

Back to [How AISC works](../architecture.md).

## Purpose

The **Manage** menu, at the top of a project's page, holds the project's settings that the steps rely on: its
connectivity (the assessed system, the Configurator's agents and the test tools), the
activity log and the admin tools. The pages are launcher pages backed by the platform's API (`platform`); the admin
tools are services of their own. Which entries a person sees depends on their role.

## Projects and roles

- Anyone signed in can **create a project** (on the project list) and becomes its owner. The project gets its own
  database.
- A project's members are owners, editors or viewers. A viewer reads, an editor changes, an owner also manages the
  members; a project always keeps at least one owner. The realm role `admin` counts as owner of every project and
  sees every project.
- **Members have no page yet.** They are managed through the platform's API (`/projects/{slug}/members`), by an
  owner or an admin.
- **Delete this project…** is for admins only: type the project's name to confirm. Its database is dropped and its
  proof files (MinIO bucket `proof-<pid>`) are removed; there is no undo.
- **My account** opens Keycloak's account page for the realm `aisc`.

## Connectivity

**Connectivity** (owners and admins) is one page for everything the project connects to. A **connection** is a way to
reach a model or a system, set up once; what it is *used for* is recorded apart from it (`connection.use`, in the
project's database, `project-template/0030_connectivity.sql`). The page has four tabs and reads everything in one
call, `GET /projects/{slug}/connectivity`, which never holds a key.

- **System under assessment.** One row per component of the AI card and the connection or uploaded file that
  reaches it. Every call to these is recorded in the run trace. A connection that reaches the assessed system is
  never used by an agent or as a test tool, and a used connection never reaches it: the database refuses both
  (409 from the API).
- **Configurator agents** (admins choose). The card agent (step 1) and the risk mapper (step 2) each run on a
  **provider connection** with a model (`PUT/DELETE /projects/{slug}/agents/{system}`); with no choice an agent uses
  the stack's own setting. The agents read their choice on the same internal route as before.
- **Test tools** (owners and admins). A test asks for a tool by role (judge, attacker, grader, embedder, generator);
  the run's form offers the connections that serve that role, and the choice stays per run. A connection serves
  roles by `PUT/DELETE /projects/{slug}/connections/{name}/tool`; the engine lists them and the worker resolves them
  on the same internal routes as before, `helper:<project>/<name>` with the connection's name. A tool is never what
  is assessed.
- **Connections** (admins add them). Every connection, its protocol, address, whether it has a key and what it is
  used for. A **provider connection** (`kind: provider`) holds a model provider's key (OpenAI, Anthropic, Mistral,
  ...), or a self-hosted model server's address (`provider: compatible` or `ollama`); a hosted provider is called at
  its own address. Keys are stored encrypted for this project (with `PLATFORM_SECRETS_KEY`) and never shown again.

Before this page, keys and agent choices were kept in schema `llm` and helper models in schema `helper`; `0030` moves
them into connections (each key as the encrypted token it is, a helper model under its own name, `<name>-helper` when a
connection already had that name) and leaves the old tables unwritten. The former pages (`llm.html`,
`helpers.html`) and their routes still work for one release, on the new tables, and are no longer in the menu.

### The connections editor: the assessed system's endpoints and files

The tab **System under assessment** links to this editor (`connections.html`), where a component's connection or
uploaded file is set up. Owners and admins see it; only admins list, create, edit, test and delete connections.

- **A connection** registers one of the system's endpoints, with one of the built-in protocols (OpenAI-compatible,
  A2A, Open Inference Protocol, or a REST API with a JSON request template) or an adapter plugin. It has a timeout
  (60 s by default, from 1 to 600 s) and its secrets, stored encrypted.
- **An uploaded file** reaches a model component (a model file such as ONNX, joblib or safetensors) or a data
  component (training, validation or other data) instead of an endpoint: **Upload a file** on its row, up to 2 GB
  (`TARGET_FILE_MAX_MB` on `platform`). The platform makes one engine component for it (a model or a dataset, named
  "AI card · Component: ... · uploaded file") and the engine stores the bytes in `minio`. The row shows the file's
  name, size and SHA-256. **Replace the file** uploads a new one to the same engine component; the old object
  stays in the bucket for the runs that used it. Tests list the file as they list any model or dataset.
- **Adapter plugins** add protocols for systems that speak none of the built-in ones. Each is a folder under
  `adapters/` with an `adapter.py`; see `adapters/README.md`. The platform reads the folder the first time it needs
  it, so a change takes a restart of `platform`.
- **Allowed internal hosts** (owners and admins): calls to internal or private addresses are refused unless the
  project allows that host here, or the stack allows it for every project with `CONNECTIONS_ALLOWED_HOSTS`. The
  stack's own services, loopback and cloud metadata addresses cannot be allowed from the page. Changes apply without
  a restart.
- **During a run** the worker hands the test a run pass. With it the test can read the connection's settings (its
  address, path and headers, with secret values masked) and get a run key (valid 12 hours by default,
  `CONNECTIONS_RUN_KEY_TTL_S`, and ending with the run). It calls the platform's doors with that key, and the
  platform adds the secrets and forwards the call. The test never sees the secrets.

## Logs

**Activity log** (every member) shows who did what in the project, read from the tamper-evident ledger (`immudb`).
Each entry is checked before it is shown. Owners and admins can export it and check the file offline with
`scripts/verify-ledger-export.py`. See the guide's [How it works](../guide.md#how-it-works) for what is recorded.

The ledger holds no names: each entry names a random reference per person and project, and the link to the person
is kept apart, in the `ledger_identity` database. To honour a request to be forgotten, an operator removes that link
for one person in one project:

```bash
docker exec aisc-<id>-platform python -m platform_service.ledger.actors erase <project pid> <person's Keycloak id>
```

The person's entries stay, so the log can still be verified, but nothing links them to that person any more. It
cannot be undone.

## Admin tools

The entries are always in the menu. Their services start with the stack, except Flower, which runs only when
asked. If one is down, the page says so and how to start it.

- **Background tasks** (admins): Flower, the monitor of the test runs' task queue, at `/flower/`. It has no sign-in
  of its own and shows every project's task arguments and results, so it runs only when an administrator starts it
  with `COMPOSE_PROFILES=inspect ./scripts/start.sh`.
- **Database diagrams** (every member): SchemaSpy, the structure (never the rows) of the project's database and of
  the shared `platform` database.
- **Browse & query (pgAdmin)** (admins): every project's data.
