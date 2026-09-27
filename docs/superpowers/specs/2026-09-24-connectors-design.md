# Connectors: one way to reach any assessed system

Date: 2026-09-24. Branch: `feat/unified-modules` (all repos). Status: design for review.

## What the user asked for (their words, condensed)

- Global connectors for the AI system and for its components. Not every component needs a
  connector, but there must be at least one, so the target can be reached for assessment.
- Admin only, and secured.
- Flexible enough to reach different kinds of API. Not limited to LLMs: AISC assesses entire
  systems through the API the company provides, and most companies use widely used API types.
- Ease of use first. "Let's get the main technologies and a user interface so easy that we can
  use to define. Maybe we do this through OpenAPI and we map all different technologies to it so
  that from the user perspective it is only OpenAPI."
- "A connector page, where you can set up the connections using the variety of connectors we
  have and then provide an OpenAPI view that is the one actually called by all plugins."
- No page specific to one system. MCAS is only the first system connected with it.

## Constraints that shape the design

1. **The freeze of 2026-09-23 holds** (`docs/superpowers/pipeline-2026-09-23/RULES.md`): the engine
   data model (apps/backend models and tables, schema `engine`), Sean's files of 2026-09-23 in
   backend / webapp / eval / plugin-interface, and AIRO must not change. `scripts/guard-frozen.sh`
   checks it. G1 dumps `pg_dump --schema-only --schema=engine`, which includes GRANTs, so even a
   new grant on an engine table fails the freeze.
2. Links to frozen rows are added on the non-frozen side.
3. Local commits only on `feat/unified-modules`, never push. No `docker compose` against the
   running `aisc` stack, no writes to its databases. Tests use throwaway Postgres containers.
4. TDD. Prose without em dashes. Business logic in Python, the webapp stays thin (the user reads
   Python, not TypeScript).
5. Plugins run as subprocesses of the eval worker, on the `backend` Docker network. They receive
   AI components as `input/<name>.json` and project secrets as `AISC_SECRET_<KEY>` env vars. The
   plugin interface already offers `InputType.RESOURCE` (`{value: str}`), `InputType.LLM`
   (`{endpoint_url, secret_key, model}`) and `@project_config` secrets. No change there is needed.

## Decisions

### D1. A new service, `connectors`, outside the engine

`apps/connectors`, Python 3.12, FastAPI, psycopg 3 (the platform service's stack). It owns a new
schema `connector` in the shared `platform` database through a new role `connector_rw`. It has two
faces:

- **Admin API** `/api/v1/connectors/...`: reached through Caddy, admin realm role only.
- **Gateway** `/gw/...`: reached only on the internal `backend` network (never routed by Caddy),
  authenticated by connector access tokens. This is what plugins call.

A separate service keeps the target systems' credentials, their encryption key and the outbound
traffic to company systems in one place with one owner, instead of spreading them over the
platform service or the engine.

### D2. References to engine rows are soft, checked through the engine API

`connector.connector.project_pid` (the engine project, the pid the webapp already uses),
`connector.connector.ai_system_pid` and `connector.operation_link.component_pid` hold engine
`pid` UUIDs without a foreign key. A foreign key is impossible without a grant on `engine` tables
(fails G1), and the engine's `pid` is not unique-constrained anyway. The engine project's pid is
not `core.project.pid` (the engine keeps `platform_project_id` and does not expose it), so there
is no foreign key to `core` either. On every write the service calls the engine API with the
admin's own token (`GET /api/v1/projects/{pid}/aisystem`, which lists the components) and
refuses a pid the engine does not return. A connector whose project the engine no longer knows
(404) is listed as **orphaned** and can be deleted regardless of D6.

### D3. OpenAPI is the one model; every technology is imported into it

A connector stores a **canonical OpenAPI 3.1 document**. Whatever the source, the importer turns
it into operations of that document. What OpenAPI cannot say lives in AISC extensions on each
operation (`x-aisc-binding`) and on the document (`x-aisc-auth`); the UI sets them, the user
never writes them.

Connector types offered on the page (the "variety of connectors"), all ending in the same
canonical document:

| Connector type | Input the admin gives | Becomes |
|---|---|---|
| OpenAPI 3.0 / 3.1 | spec URL, or file | operations as they are |
| Swagger 2.0 | spec URL, or file | converted to 3.1, then as above |
| cURL | pasted command | one operation per command |
| Postman collection v2.1 | file | one operation per request |
| Manual | method, URL, example request and response | one operation |
| SOAP | WSDL URL or file | one operation per SOAP operation, JSON in and out, XML envelope built by the gateway |
| GraphQL | endpoint (introspection) | one operation per chosen query or mutation, fixed document, variables as JSON body |
| OpenAI-compatible | base URL | `POST /chat/completions`, `GET /models` |
| Ollama | base URL | `POST /api/chat` |
| Hugging Face Inference | model URL | `POST /` with `{inputs}` |

Auth schemes (connector level, `x-aisc-auth`): none, API key (header or query), bearer, basic,
OAuth2 client credentials (token cached until expiry), mutual TLS (client certificate and key).

Interaction patterns (operation level, `x-aisc-binding`), so a plugin always sees one synchronous
request and one JSON response:

- `session`: capture an id from a response (JSON path) and inject it into later calls that carry
  the same `X-AISC-Session` header value (multi-turn chatbots).
- `async`: after a `202`, poll a status URL (from a header or a JSON path) until a JMESPath
  condition holds, then return the result (job APIs).
- `stream`: read SSE or NDJSON, join the deltas found at a JSON path, return one JSON document.

**Out of v1** (the `protocol` field of the binding is the extension point): gRPC, WebSocket,
HMAC-signed requests, OAuth2 flows that need a person to log in.

### D4. The unified OpenAPI view is what plugins call

For each connector the gateway serves `GET /gw/{connector_pid}/openapi.json`: the canonical
document reduced to the **allowed** operations, with `servers` rewritten to the gateway, one
security scheme (gateway bearer token) and the AISC extensions removed. Plugins call exactly the
paths and methods in that view, at `/gw/{connector_pid}/<path>`. The gateway matches the call to
an allowed operation and executes its binding against the real system. For REST imports the
paths are the company's own paths; for SOAP and GraphQL they are synthetic
(`/soap/{Operation}`, `/graphql/{operationName}`).

Two facades let plugins that only speak LLM chat use any connector, by mapping one chosen
operation (the connector's "chat operation", with an input field and an answer JMESPath):

- OpenAI: `/gw/{cid}/openai/v1/chat/completions` and `/gw/{cid}/openai/v1/models`.
- Ollama: `/gw/{cid}/k/{token}/ollama/api/chat` (token in the path, because plugins such as
  LangBiTe 0.1.1 only accept a base URL; see Security).

### D5. Plugins reach a connector with what the engine already has

"Publish to AI system" on the page makes the service, with the admin's token, call the engine
API to create:

- a project secret `CONNECTOR_<SLUG>_TOKEN` holding a new access token (engine ProjectConfig,
  encrypted by the engine as today);
- a `resource` component `<name> (connector)` whose value is the view URL
  `http://connectors:8097/gw/<cid>/openapi.json`;
- if a chat operation is set, an `llm` component with `endpoint_url`
  `http://connectors:8097/gw/<cid>/openai/v1` and `secret_key` `CONNECTOR_<SLUG>_TOKEN`.

A plugin declares a resource input and a `@project_config` secret, reads the view URL, and calls
it with the token from `AISC_SECRET_...`. Existing LLM plugins select the `llm` component.
Unpublish revokes the token and removes what publish created.

### D6. "At least one connector" means one target-access connector per project

Each connector belongs to one project and to its AI system. One connector per project is marked
**target access**. The first connector of a project becomes it automatically. The service refuses
to delete or unmark the last target-access connector; the admin marks another one first.
`GET /api/v1/connectors/projects/{project_pid}/readiness` says whether the project has one,
and the page shows a warning when it does not. The engine cannot be made to refuse evaluations
without one (frozen), so this is enforced in the connectors service and shown, not enforced at
evaluation start. **ASSUMED:** refusing the last delete is acceptable; the alternative is to
allow it and only warn.

Operations can be linked to one or more components ("this operation exercises the scorer").
Components without a link are fine.

### D7. Security

- **Admin only**: every admin route depends on `requires_role("admin")` from
  `shared/identity`, and Caddy puts `/api/v1/connectors*` behind the existing `protect` and
  `admin_only` forward auth. The webapp shows the page and its menu entry only to realm admins,
  but the server is the one that enforces it.
- **Secrets** of target systems are encrypted with `CONNECTOR_SECRETS_KEY` (Fernet, via
  `MultiFernet` so the key can rotate), a key only the connectors service holds, generated by
  `scripts/secrets.sh`. The API is write-only: set, replace, delete; reads return
  `{name, masked, updated_at}` only. Secrets never appear in logs, errors or the unified view.
- **Access tokens** for the gateway: 32 random bytes, shown once, stored as SHA-256, scoped to one
  connector, revocable. The Ollama facade's token-in-path is weaker (it can end up in a plugin's
  logs); it is off unless enabled per connector, and access logs redact the path segment.
- **Default deny on operations**: an imported operation is not callable until an admin allows it.
  Operations with a method other than GET/HEAD/OPTIONS are marked "may change data" and need a
  separate confirmation. A connector also carries `environment: sandbox | production`; allowing
  an operation on a production connector asks for the confirmation again.
- **Outbound safety**: the gateway only calls the servers of the connector's own document (host
  fixed at import, path parameters percent-encoded), follows no redirect to another host,
  refuses link-local metadata addresses (169.254.0.0/16, fd00:ec2::254), verifies TLS by default
  (per-connector CA bundle allowed), applies a per-connector rate limit (requests per minute) and
  timeout.
- **Audit**: one row per gateway call (connector, operation, token, status, error kind, latency,
  time); bodies are never stored.
- **Known risk, not fixed here (frozen)**: plugin subprocesses inherit the worker's whole
  environment, including `DJANGO_SECRET_KEY` and `INTERNAL_API_KEY`, so a malicious plugin can
  decrypt any project secret, including connector tokens of other projects. Target credentials
  are still safe (they never leave the connectors service). The fix belongs in `apps/eval`
  (pass the plugin a filtered environment) once the freeze allows it.

### D8. Errors a person can act on

Every failure is classified: `auth` (401/403 from the target, or OAuth2 token refused), `not_found`,
`rate_limited` (429 or our own limit), `timeout`, `tls`, `dns`, `connection`, `target_error`
(5xx), `bad_mapping` (response does not contain the configured path), `not_allowed` (operation
not allowed), `invalid_input`. The page's "Test" shows the kind, status, latency and response.

Through the gateway, whatever the target answered is passed back as it is (status, content type,
body), so a plugin sees the company's real behaviour, including its 4xx answers; a header
`X-AISC-Outcome` carries `ok` or the kind (`auth`, `rate_limited`, `target_error`, ...).
Failures that happen before or instead of a target answer come back as the gateway's own
`{"error": {"kind": ..., "message": ...}}`: 403 `not_allowed`, 422 `invalid_input`,
429 `rate_limited` (our limit), 504 `timeout`, 502 for `tls`, `dns`, `connection`,
`bad_mapping`.

## The page

`/projects/:project_name/connectors`, in the project sidebar, admin only.

1. **List**: connectors of the project, their type, environment, target-access badge, published
   state, a readiness warning if none is target access.
2. **New connector**: pick a connector type from D3's table, give its input (URL, file, pasted
   text), name, environment. The service imports it and opens the detail view.
3. **Detail**:
   - *Credentials*: the auth scheme and its secret fields (write-only).
   - *Operations*: the imported operations with method, path, summary, "may change data" flag;
     allow or deny each, link each to components, set patterns (session / async / stream).
   - *Test*: run an allowed operation with an example body; see kind, status, latency, response.
   - *OpenAPI view*: the unified document exactly as plugins get it, rendered as a readable
     operation list with a raw JSON toggle and a copy button.
   - *Chat mapping* (optional): the operation, input field and answer path used by the facades.
   - *Publish*: create or revoke plugin access; show the view URL, the OpenAI base URL, and (if
     enabled) the Ollama URL for older plugins.

Everything the page shows is prepared by the service (Python); the page renders it.

## Acceptance

1. MCAS-lite (running on the host, `http://172.17.0.1:8500`) is connected from its OpenAPI URL
   with the OpenAPI connector type. `score`, `explain`, `chat` are allowed; `halt`, `resume`,
   `override` stay denied and a gateway call to them answers 403 `not_allowed`.
2. "Test" on `chat` returns MCAS's answer; "Test" with a wrong API key on a stub target returns
   kind `auth`; an unreachable host returns `connection` or `dns`.
3. A plugin-shaped client (resource input + `AISC_SECRET_*`, run through `plugin_runtime.py`)
   fetches the unified view and calls `POST /chat` through the gateway.
4. The `ollama` Python client pointed at the Ollama facade URL gets MCAS's answer as
   `message.content`; the `openai` client does the same through the OpenAI facade.
5. A SOAP stub and a GraphQL stub are connected and called through the gateway the same way.
6. `scripts/guard-frozen.sh` passes; no file frozen on 2026-09-23 changed.
7. A non-admin gets 403 on every admin route, and the page and menu entry are hidden from them.

Running the new service on the real stack needs a rebuild of the `aisc` compose project, which
the rules forbid without the user: the plan stops and asks at that point.

## Not in scope

gRPC, WebSocket, HMAC signing, interactive OAuth2, external secret managers, per-evaluation
connector pickers, changes to any plugin, the eval worker environment fix (D7 known risk), an
automatic mapping of connector operations to AIRO card components.
