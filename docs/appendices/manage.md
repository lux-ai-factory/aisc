# Appendix 5: Manage

Back to [How AISC works](../architecture.md).

## Purpose

The **Manage** menu, at the top of a project's page, holds the settings the four steps rely on: who is in the
project, which models the AI assistants use, how the system being assessed is reached, which helper models tests may
use, and the activity log. The platform (`platform`) serves all of them.

## Projects and roles

- Anyone signed in can **create a project** and becomes its owner. The project gets its own database.
- A project's members are owners, editors or viewers. A viewer reads, an editor changes, an owner also manages the
  members (a project always keeps one owner). The realm role `admin` acts as owner of every project and sees every
  project. Members are managed through the platform's API (`/projects/{slug}/members`).
- **Delete this project** is for admins only: type the project's name to confirm. Its database is dropped; there is
  no undo.
- **My account** opens Keycloak's account page (password, sessions).

## AI assistants

**AI assistant models and keys** (admins) sets the model and key for the two AI assistants: the card agent of step 1
and the risk mapper of step 2. A project without its own choice uses the stack's settings. Keys are stored encrypted
in the project's database (schema `llm`, key `PLATFORM_SECRETS_KEY`) and are never shown again. Each assistant can
read only its own key.

## Components and connections

This is how tests reach the system being assessed.

- **Connections** (admins) register the system's endpoints: OpenAI-compatible, A2A, Open Inference Protocol, a REST
  API with a request template, or an adapter plugin. A connection has a timeout (60 s by default, up to 600 s) and
  its secrets, stored encrypted.
- **Adapter plugins** add protocols for systems that speak none of the built-in ones. Each is a folder under
  `adapters/` with an `adapter.py`; see `adapters/README.md`. Adapters load when the platform starts.
- **Allowed internal hosts** (owners and admins): calls to internal or private addresses are refused unless a
  project allows that host here, or the stack allows it for every project with `CONNECTIONS_ALLOWED_HOSTS`. The
  stack's own services, loopback and cloud metadata addresses cannot be allowed from the page.
- **During a run** the worker gets a short-lived run key (12 hours at most, revoked when the run ends) and the test
  calls the platform's doors, which forward to the connection. The test never sees the system's address or secrets.

## Helper models

**Helper models** (owners and admins manage, every member sees) are the models a test uses as tools: a judge, an
attacker, a grader, an embedder or a generator. Each has a label, an endpoint (held to the same allowed-hosts rule),
its roles and an optional key, stored encrypted (schema `helper`). **Test** makes one small call to check it answers.
A helper model is never what is assessed: the system is reached through its connection.

## Logs

**Activity log** (every member) shows who did what in the project, read from the tamper-evident ledger (`immudb`).
Each entry is checked before it is shown. Owners and admins can export it and check the file offline with
`scripts/verify-ledger-export.py`. See the guide's [How it works](../guide.md#how-it-works) for what is recorded.

## Admin tools

For admins, and only when the stack runs with the `inspect` profile:

- **Background tasks**: Flower, the monitor of the test runs' task queue, at `/flower/`.
- **Inspect database**: **Database diagrams** (SchemaSpy, structure only, every member for their own project) and
  **Browse & query (pgAdmin)** (admins, every project's data).
