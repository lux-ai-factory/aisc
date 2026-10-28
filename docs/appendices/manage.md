# Appendix 5: Manage

Back to [How AISC works](../architecture.md).

## Purpose

The **Manage** menu, at the top of a project's page, holds the project's settings that the steps rely on: which
models the AI assistants use, how the system being assessed is reached, which helper models tests may use, the
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
- **Delete this project…** is for admins only: type the project's name to confirm. Its database is dropped; there
  is no undo.
- **My account** opens Keycloak's account page for the realm `aisc`.

## AI assistants

**AI assistant models and keys** (admins only) chooses the model for each of the two AI assistants: the card agent of
step 1 and the risk mapper of step 2. Keys are stored per provider, encrypted in the project's database (schema
`llm`, with `PLATFORM_SECRETS_KEY`), and never shown again; each assistant uses the key of the provider chosen for
it. Removing a choice sends that assistant back to the stack's own setting.

## Assessed system: Components and connections

This is how tests reach the system being assessed. Owners and admins see the page; only admins list, create, edit,
test and delete connections.

- **A connection** registers one of the system's endpoints, with one of the built-in protocols (OpenAI-compatible,
  A2A, Open Inference Protocol, or a REST API with a JSON request template) or an adapter plugin. It has a timeout
  (60 s by default, from 1 to 600 s) and its secrets, stored encrypted.
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

## Helper models

**Judges, attackers and other tool models** (under Helper models) lists the models a test uses as tools: a judge, an
attacker, a grader, an embedder or a generator. Every member sees the list; owners and admins manage it. A helper
model has a name, a label, an endpoint (held to the same allowed-hosts rule), its roles and an optional key, stored
encrypted (schema `helper`). **Test** (owners and admins) sends one short OpenAI-style chat call to a model name you
type and reports whether it answered. A helper model is never what is assessed: the system is reached through its
connection.

## Logs

**Activity log** (every member) shows who did what in the project, read from the tamper-evident ledger (`immudb`).
Each entry is checked before it is shown. Owners and admins can export it and check the file offline with
`scripts/verify-ledger-export.py`. See the guide's [How it works](../guide.md#how-it-works) for what is recorded.

## Admin tools

The entries are always in the menu; their services run only when the stack is started with the `inspect` profile
(otherwise the page says how to start them). In the staging compose file Flower always runs.

- **Background tasks** (admins): Flower, the monitor of the test runs' task queue, at `/flower/`.
- **Database diagrams** (every member): SchemaSpy, the structure (never the rows) of the project's database and of
  the shared `platform` database.
- **Browse & query (pgAdmin)** (admins): every project's data.
