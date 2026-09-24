# Connectors, plan 2 of 2: the Connector page, the stack wiring, and acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One admin-only Connector page in the webapp where connections are set up with any connector type and the unified OpenAPI view is shown; the connectors service wired into the stack definition (not started on the live stack); and an acceptance run proving MCAS-lite, SOAP and GraphQL targets are reached by plugins only through the unified view.

**Architecture:** The connectors service (plan 1) describes its connector types and auth schemes itself (`GET /api/v1/connectors/types`), so the React page only renders forms and tables from what Python prepares. The page calls `${VITE_API_URL}/api/v1/connectors`, which the webapp's token-patched `fetch` already signs; Caddy routes that prefix to the service behind `protect` and `admin_only`. The acceptance run starts the service with uvicorn against a throwaway Postgres and a stub engine, and drives it with a real plugin process (`apps/eval/aisc_eval/plugin_runtime.py`), the `ollama` and `openai` Python clients, a SOAP stub and a GraphQL stub.

**Tech Stack:** React 18 + TypeScript + MUI 6 + @tanstack/react-query 5, vitest 4 with jsdom (tests render with `createRoot` + `act`, no testing-library); Docker Compose, Caddy 2.10; Python acceptance with pytest, uvicorn, `ollama`, `openai`, `aisc-plugin-interface`.

**Spec:** `docs/superpowers/specs/2026-09-24-connectors-design.md`. **Depends on:** plan 1 (`docs/superpowers/plans/2026-09-24-connectors-1-service.md`) fully done.

## Global Constraints

- Everything in plan 1's Global Constraints applies.
- Frozen webapp files (Sean, 2026-09-23, must stay byte-identical): `src/api/api.tsx`, `src/components/AISystemSettings.tsx`, `src/components/plugin/PluginConfigForm.tsx`, `src/components/plugin/PluginEvaluationForm.tsx`, `src/components/plugin/PluginEvaluationForm.test.tsx`, `src/models/models.tsx`, `src/pages/PluginStartEvaluation.tsx`, `src/pages/PluginStartEvaluation.test.tsx`, `src/pages/PluginsConfig.tsx`, `src/pages/Settings.tsx`; treat `src/components/TopBar.tsx`, `src/pages/ProjectHome.tsx`, `src/pages/StartEvaluation.tsx` as frozen too. New code goes in new files; `src/MyApp.tsx` and `src/components/LeftBar.tsx` may change.
- The webapp stays thin: no validation or business rules in TypeScript beyond "show what the service said".
- Never `docker compose up/down/build/restart` against compose project `aisc`. `docker compose ... config` (render only) and `docker build -t <new tag>` of the new image are allowed. Starting the service on the real stack is the user's decision (Task 9 stops and asks).
- Other people commit to this repo concurrently (report composer work on 2026-09-24). Commit only the files a task names; never `git add -A`; never commit someone else's uncommitted changes. If a task needs a file that has someone else's uncommitted edits (currently `Caddyfile`, `docker-compose.development.yml`, `docker-compose-infra.development.yml`, `scripts/secrets.sh`, `scripts/verify.sh`), stop and ask the user how to proceed.
- Page route: `/projects/:project_name/connectors` and `/projects/:project_name/connectors/:connector_pid`; menu entry "Connectors" in the "Project" section, shown only when `useAuth().roles` includes `admin`.
- Run webapp tests from `apps/webapp` with `npx vitest run <file>`; connectors tests from `apps/connectors` with `uv run pytest`.

## Review Focus

1. An admin whose token expires while the page is open: the next call answers 401, and the page must say "sign in again" rather than show an empty list as if there were no connectors. (Task 3, `connectorsApi reports 401 as a sign-in problem`.)
2. The one-time plugin token after Publish: navigating away and back must not show it again, and it must never be written to the react-query cache that other components read. (Task 6, `the publish token is shown once and not cached`.)
3. A connector with dozens of operations (a big OpenAPI spec): the operations table must stay usable, so it is sorted by path and filterable by text. (Task 5, `operations are sorted and filterable`.)
4. The service answers 409 with a sentence when an allow needs confirmation; the page must show that sentence in a confirm dialog and retry with the confirmation flag, not drop the click. (Task 5, `a 409 on allow asks for confirmation and retries`.)
5. A non-admin who types the page URL directly: the page must render a plain "admins only" notice without calling the service repeatedly. (Task 7, `a non-admin sees a notice and no calls are made`.)

---

## File structure

```
apps/connectors/aisc_connectors/catalogue.py        connector types + auth schemes, with their form fields
apps/connectors/tests/test_catalogue.py
apps/connectors/tests/test_wiring.py                 compose, Caddy, secrets, init SQL are wired as intended
apps/connectors/tests/acceptance/                    the end-to-end run (skipped unless MCAS-lite answers)
  __init__.py
  conftest.py                                        service, stub engine, stubs, throwaway Postgres
  stub_engine.py                                     the engine API as the service uses it, in memory
  stub_graphql.py                                    a tiny GraphQL server
  connector_probe/__init__.py                        a real plugin: resource input + secret, calls the view
  test_acceptance.py
apps/webapp/src/models/connectors.ts                 types for what the service returns
apps/webapp/src/api/connectors.ts                    one function per service route
apps/webapp/src/auth/useIsAdmin.ts
apps/webapp/src/pages/Connectors.tsx                 list + new connector
apps/webapp/src/pages/ConnectorDetail.tsx            the detail view, composed of the panels below
apps/webapp/src/components/connectors/FieldsForm.tsx       renders fields the service describes
apps/webapp/src/components/connectors/CredentialsPanel.tsx
apps/webapp/src/components/connectors/OperationsPanel.tsx
apps/webapp/src/components/connectors/TestPanel.tsx
apps/webapp/src/components/connectors/OpenApiView.tsx
apps/webapp/src/components/connectors/ChatPanel.tsx
apps/webapp/src/components/connectors/PublishPanel.tsx
apps/webapp/src/components/connectors/testUtils.tsx  shared test rendering helper
apps/webapp/src/**/*.test.tsx                        next to each file above
docker-compose.development.yml, docker-compose-infra.development.yml, Caddyfile, scripts/secrets.sh, scripts/verify.sh
```

---

### Task 1: The service describes its connector types and auth schemes

**Files:**
- Create: `apps/connectors/aisc_connectors/catalogue.py`
- Modify: `apps/connectors/aisc_connectors/routes_admin.py` (route `GET /api/v1/connectors/types`, declared before `/{connector_pid}`)
- Test: `apps/connectors/tests/test_catalogue.py`

**Interfaces:**
- Produces: `catalogue.CONNECTOR_TYPES: list[dict]` and `catalogue.AUTH_SCHEMES: list[dict]`. Each type: `{kind, label, description, fields: [Field]}`; each scheme: `{scheme, label, fields: [Field], secrets: [{name, label, multiline}]}`; `Field` = `{name, label, type: "url" | "text" | "textarea" | "select" | "boolean", required: bool, options?: [str], help?: str}`. Route answers `{"connector_types": [...], "auth_schemes": [...]}` to admins.

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_catalogue.py`:

```python
from fastapi.testclient import TestClient


def test_every_importer_kind_is_described_once():
    from aisc_connectors.catalogue import CONNECTOR_TYPES
    from aisc_connectors.importers import KINDS

    assert [t["kind"] for t in CONNECTOR_TYPES] == list(KINDS)


def test_fields_have_what_the_page_needs():
    from aisc_connectors.catalogue import AUTH_SCHEMES, CONNECTOR_TYPES

    for entry in CONNECTOR_TYPES + AUTH_SCHEMES:
        for field in entry["fields"]:
            assert {"name", "label", "type", "required"} <= set(field)
            assert field["type"] in ("url", "text", "textarea", "select", "boolean")
            if field["type"] == "select":
                assert field["options"]


def test_auth_scheme_secrets_are_vault_names():
    from aisc_connectors.catalogue import AUTH_SCHEMES
    from aisc_connectors.vault import SECRET_NAMES

    assert {s["scheme"] for s in AUTH_SCHEMES} == {"none", "api_key", "bearer", "basic",
                                                   "oauth2_client_credentials", "mtls"}
    for scheme in AUTH_SCHEMES:
        assert {s["name"] for s in scheme["secrets"]} <= SECRET_NAMES


def test_the_route_is_admin_only(auth_on, as_user):
    from aisc_connectors.app import app

    client = TestClient(app)
    assert client.get("/api/v1/connectors/types", headers=as_user("bob", ("primary-user",))).status_code == 403
    body = client.get("/api/v1/connectors/types", headers=as_user()).json()
    assert set(body) == {"connector_types", "auth_schemes"}
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_catalogue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.catalogue'`.

- [ ] **Step 3: Implement**

`apps/connectors/aisc_connectors/catalogue.py`:

```python
"""What the Connector page offers, described here so the page only renders it (spec, The page)."""


def _f(name, label, type_="text", required=False, **extra):
    return {"name": name, "label": label, "type": type_, "required": required, **extra}


_URL_OR_TEXT = [_f("url", "Where to download it", "url"), _f("text", "...or paste it", "textarea")]

CONNECTOR_TYPES = [
    {"kind": "openapi", "label": "OpenAPI or Swagger",
     "description": "The system's OpenAPI 3.x or Swagger 2.0 description. Most REST APIs publish one.",
     "fields": [*_URL_OR_TEXT, _f("base_url", "Base URL (only if the spec names no server)", "url")]},
    {"kind": "curl", "label": "cURL command",
     "description": "One call, pasted from the API's documentation or a terminal. Credentials in it go to the vault.",
     "fields": [_f("text", "curl command", "textarea", True)]},
    {"kind": "postman", "label": "Postman collection",
     "description": "An exported Postman collection (v2.1). One operation per request.",
     "fields": [*_URL_OR_TEXT]},
    {"kind": "manual", "label": "Describe one call",
     "description": "No documentation at hand: give the method, the URL and an example.",
     "fields": [_f("method", "Method", "select", True, options=["GET", "POST", "PUT", "PATCH", "DELETE"]),
                _f("url", "URL", "url", True), _f("operation_id", "Name of the operation", "text"),
                _f("example_request", "Example request body (JSON)", "textarea"),
                _f("example_response", "Example answer (JSON)", "textarea")]},
    {"kind": "wsdl", "label": "SOAP web service",
     "description": "The service's WSDL. Each SOAP operation becomes a JSON operation.",
     "fields": [*_URL_OR_TEXT]},
    {"kind": "graphql", "label": "GraphQL API",
     "description": "The GraphQL endpoint. Queries and mutations are read from the schema.",
     "fields": [_f("url", "GraphQL endpoint", "url", True)]},
    {"kind": "openai", "label": "OpenAI-compatible LLM",
     "description": "Any /chat/completions API: OpenAI, Azure OpenAI, vLLM, LiteLLM, most hosted models.",
     "fields": [_f("url", "Base URL (ending in /v1)", "url", True), _f("model", "Model name", "text")]},
    {"kind": "ollama", "label": "Ollama",
     "description": "An Ollama server.",
     "fields": [_f("url", "Base URL", "url", True), _f("model", "Model name", "text")]},
    {"kind": "huggingface", "label": "Hugging Face Inference",
     "description": "A Hugging Face Inference endpoint for one model.",
     "fields": [_f("url", "Model URL", "url", True)]},
]


def _s(name, label, multiline=False):
    return {"name": name, "label": label, "multiline": multiline}


AUTH_SCHEMES = [
    {"scheme": "none", "label": "No credentials", "fields": [], "secrets": []},
    {"scheme": "api_key", "label": "API key",
     "fields": [_f("in", "Sent in", "select", True, options=["header", "query"]),
                _f("name", "Header or parameter name", "text", True)],
     "secrets": [_s("api_key", "API key")]},
    {"scheme": "bearer", "label": "Bearer token", "fields": [], "secrets": [_s("token", "Token")]},
    {"scheme": "basic", "label": "Username and password", "fields": [_f("username", "Username", "text", True)],
     "secrets": [_s("password", "Password")]},
    {"scheme": "oauth2_client_credentials", "label": "OAuth2 client credentials",
     "fields": [_f("token_url", "Token URL", "url", True), _f("client_id", "Client id", "text", True),
                _f("scope", "Scope", "text")],
     "secrets": [_s("client_secret", "Client secret")]},
    {"scheme": "mtls", "label": "Client certificate (mutual TLS)", "fields": [],
     "secrets": [_s("client_cert", "Certificate (PEM)", True), _s("client_key", "Private key (PEM)", True)]},
]
```

Add to `apps/connectors/aisc_connectors/routes_admin.py`, directly below `router = APIRouter(...)` (so it is declared before `/{connector_pid}`):

```python
from aisc_connectors.catalogue import AUTH_SCHEMES, CONNECTOR_TYPES  # noqa: E402


@router.get("/types")
def types(admin: "Admin" = Depends(admin_call)) -> dict:
    return {"connector_types": CONNECTOR_TYPES, "auth_schemes": AUTH_SCHEMES}
```

(If `Admin`/`admin_call` are imported below that point, move this route below the imports but above the first `/{connector_pid}` route.)

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_catalogue.py -v && uv run pytest -q`
Expected: 4 passed, then the whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors/aisc_connectors/catalogue.py apps/connectors/aisc_connectors/routes_admin.py apps/connectors/tests/test_catalogue.py
git commit -m "Connectors: the service describes its connector types and auth schemes for the page"
```

---

### Task 2: Wire the service into the stack definition

**Files:**
- Modify: `docker-compose.development.yml` (new service `connectors`)
- Modify: `docker-compose-infra.development.yml` (init script on a fresh volume and in `postgres-setup`)
- Modify: `Caddyfile` (route `/api/v1/connectors*`)
- Modify: `scripts/secrets.sh` (`CONNECTOR_SECRETS_KEY`, `CONNECTOR_DB_PASSWORD`)
- Modify: `scripts/verify.sh` (the connectors suite)
- Test: `apps/connectors/tests/test_wiring.py`

**Interfaces:**
- Produces: compose service `connectors` (build `apps/connectors`, image `aisc-connectors:latest`, `pull_policy: never`, networks `backend` + `frontend`, `expose: ["8097"]`, no `ports`, env `CONNECTORS_DATABASE_URL`, `CONNECTOR_SECRETS_KEY`, `ENGINE_API_URL=http://aisc-backend:8000/api/v1`, `GATEWAY_BASE_URL=http://connectors:8097`, `AUTH_ENABLED`, `KEYCLOAK_ISSUER`, `KEYCLOAK_JWKS_URL` copied from report-composer's entry, volume `./shared/identity:/app/shared/identity:ro,Z`); Caddy sends `/api/v1/connectors*` (and nothing under `/gw`) to `connectors:8097` behind `protect` and `admin_only`.

- [ ] **Step 1: Check nobody else is editing these files**

Run: `cd ~/aisc-install && git status --short Caddyfile docker-compose.development.yml docker-compose-infra.development.yml scripts/secrets.sh scripts/verify.sh`
Expected: no output. If any file is listed as modified, STOP: those are someone else's uncommitted changes. Ask the user whether to wait, or to build on top of them without committing them. Also check `(admin_only)` exists in the committed Caddyfile: `git show HEAD:Caddyfile | grep -c "(admin_only)"` should print `1`; if it prints `0`, ask the user (the snippet was uncommitted work of another session on 2026-09-24; the fallback is `import protect` alone, since the service checks the admin role itself).

- [ ] **Step 2: Write the failing test**

`apps/connectors/tests/test_wiring.py`:

```python
"""The stack definition says what the spec says: internal gateway, admin-only API, own secrets."""
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]


def compose():
    return yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]


def test_the_service_is_internal_only():
    service = compose()["connectors"]
    assert "ports" not in service
    assert set(service["networks"]) == {"backend", "frontend"}
    assert service["expose"] == ["8097"]
    env = service["environment"]
    assert env["GATEWAY_BASE_URL"] == "http://connectors:8097"
    assert env["ENGINE_API_URL"] == "http://aisc-backend:8000/api/v1"
    assert "CONNECTOR_SECRETS_KEY" in str(env["CONNECTOR_SECRETS_KEY"])


def test_only_the_admin_api_is_routed_by_caddy():
    caddy = (ROOT / "Caddyfile").read_text()
    block = re.search(r"handle /api/v1/connectors\* \{(.*?)\n  \}", caddy, re.S)
    assert block, "no /api/v1/connectors* route"
    assert "import protect" in block.group(1) and "import admin_only" in block.group(1)
    assert "reverse_proxy connectors:8097" in block.group(1)
    assert caddy.index("handle /api/v1/connectors*") < caddy.index("handle /api/* {")
    assert "/gw" not in caddy


def test_the_database_role_is_created_on_fresh_and_existing_volumes():
    infra = (ROOT / "docker-compose-infra.development.yml").read_text()
    assert "./init/connectors-db.sql:/docker-entrypoint-initdb.d/80-connectors-db.sql" in infra
    assert "-f /setup/connectors-db.sql" in infra


def test_secrets_are_generated():
    secrets = (ROOT / "scripts" / "secrets.sh").read_text()
    assert "CONNECTOR_SECRETS_KEY" in secrets and "CONNECTOR_DB_PASSWORD" in secrets


def test_verify_runs_the_connectors_suite():
    assert "apps/connectors" in (ROOT / "scripts" / "verify.sh").read_text()
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_wiring.py -v`
Expected: FAIL with `KeyError: 'connectors'`.

- [ ] **Step 4: Add the compose service**

In `docker-compose.development.yml`, next to the `report-composer` service, add (copy the three Keycloak lines verbatim from report-composer's `environment`, so issuer and JWKS URL match the rest of the stack):

```yaml
  # Connectors (spec docs/superpowers/specs/2026-09-24-connectors-design.md): admin-defined
  # connections to assessed systems and the gateway plugins call. /api/v1/connectors is routed by
  # Caddy (admins only); /gw is reachable only on the backend network.
  connectors:
    build: apps/connectors
    image: aisc-connectors:latest
    pull_policy: never
    container_name: connectors
    environment:
      CONNECTORS_DATABASE_URL: postgresql://connector_rw:${CONNECTOR_DB_PASSWORD:-connector_rw}@postgres:5432/platform
      CONNECTOR_SECRETS_KEY: ${CONNECTOR_SECRETS_KEY:?run scripts/secrets.sh first}
      ENGINE_API_URL: http://aisc-backend:8000/api/v1
      GATEWAY_BASE_URL: http://connectors:8097
      AUTH_ENABLED: "true"
      # KEYCLOAK_ISSUER and KEYCLOAK_JWKS_URL: the same two lines as report-composer's
    volumes:
      - ./shared/identity:/app/shared/identity:ro,Z
    expose:
      - "8097"
    networks:
      - backend
      - frontend
    depends_on:
      - postgres
    restart: unless-stopped
```

- [ ] **Step 5: Add the database role to both init paths**

In `docker-compose-infra.development.yml`:
- under the `postgres` service's volumes, after the `70-inspector-role.sql` line, add
  `      - ./init/connectors-db.sql:/docker-entrypoint-initdb.d/80-connectors-db.sql:ro,Z`
- under `postgres-setup` volumes add `      - ./init/connectors-db.sql:/setup/connectors-db.sql:ro,Z`
- under `postgres-setup` environment add `      CONNECTOR_DB_PASSWORD: ${CONNECTOR_DB_PASSWORD:-connector_rw}`
- append to its `command`, after the inspector line (inside the same `sh -c` string):
  `      && psql -v ON_ERROR_STOP=1 -v connector_password=\"$$CONNECTOR_DB_PASSWORD\" -f /setup/connectors-db.sql"`
  (move the closing `"` from the inspector line to this new last line).

- [ ] **Step 6: Route the admin API in Caddy**

In `Caddyfile`, directly above `  # Should be the backend API, so forward also this path there` (the `handle /api/* {` block), add:

```caddy
  # Connectors admin API (spec 2026-09-24): admins only. The gateway (/gw) is never routed here.
  handle /api/v1/connectors* {
    import protect
    import admin_only
    reverse_proxy connectors:8097 {
      header_up X-Real-IP {remote_host}
    }
  }
```

- [ ] **Step 7: Generate the secrets and run the suite in verify**

In `scripts/secrets.sh`, in the block that generates the other values (lines 34 to 45), add, following the file's own pattern for a generated value:

```bash
# Fernet key for the connectors service's vault: 32 random bytes, url-safe base64 (spec D7)
CONNECTOR_SECRETS_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
CONNECTOR_DB_PASSWORD=$(openssl rand -hex 24)
```

and make sure both names are written to `env.secrets` the same way the other names are (the loop at line 61 appends names added later).

In `scripts/verify.sh`, in the module suites list (lines 53 to 64), add a line in the same style as its neighbours that runs, on the host:

```bash
(cd apps/connectors && uv run pytest -q --ignore=tests/acceptance)
```

- [ ] **Step 8: Run the tests and render the configuration**

Run:

```bash
cd apps/connectors && uv run pytest tests/test_wiring.py -v
cd ~/aisc-install && CONNECTOR_SECRETS_KEY=x docker compose -p connectors-config-check -f docker-compose-infra.development.yml -f docker-compose.development.yml config --services | grep -x connectors
docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.10.2 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker build -t aisc-connectors:check apps/connectors
```

Expected: 5 passed; `connectors`; `Valid configuration`; the image builds. (`config` only renders; the project name `connectors-config-check` keeps it away from `aisc` either way.)

- [ ] **Step 9: Commit**

```bash
git add docker-compose.development.yml docker-compose-infra.development.yml Caddyfile scripts/secrets.sh scripts/verify.sh apps/connectors/tests/test_wiring.py
git commit -m "Connectors in the stack definition: internal gateway, admin-only API behind Caddy, own key and role"
```

---

### Task 3: Webapp foundations: types, API client, admin check

**Files:**
- Create: `apps/webapp/src/models/connectors.ts`, `apps/webapp/src/api/connectors.ts`, `apps/webapp/src/auth/useIsAdmin.ts`
- Create: `apps/webapp/src/components/connectors/testUtils.tsx`
- Test: `apps/webapp/src/api/connectors.test.ts`, `apps/webapp/src/auth/useIsAdmin.test.tsx`

**Interfaces:**
- Produces:
  - Types in `models/connectors.ts`: `Field`, `ConnectorType`, `AuthScheme`, `Catalogue`, `SecretInfo`, `Connector`, `OperationRow`, `ImportAnswer`, `TestAnswer`, `Publication`, `PublishAnswer`, `CallRow` (fields exactly as plan 1 and Task 1 return them).
  - `api/connectors.ts`: `class ConnectorsError extends Error { status: number; needsSignIn: boolean }` and object `connectorsApi` with `types()`, `list(projectPid)`, `readiness(projectPid)`, `create({project_pid, name, environment})`, `get(cid)`, `patch(cid, body)`, `remove(cid)`, `makeTargetAccess(cid)`, `setAuth(cid, auth)`, `setServer(cid, url)`, `putSecret(cid, name, value)`, `deleteSecret(cid, name)`, `importSource(cid, body)`, `operations(cid)`, `patchOperation(cid, operationId, body)`, `testOperation(cid, operationId, body)`, `setChat(cid, mapping)`, `view(cid)`, `publication(cid)`, `publish(cid)`, `unpublish(cid)`, `calls(cid)`. All call `${import.meta.env.VITE_API_URL}/api/v1/connectors...`.
  - `useIsAdmin(): boolean` from `useAuth().roles`.
  - `testUtils.tsx`: `render(ui) -> { container, unmount }` wrapping `QueryClientProvider` (retry off), and `flush()` awaiting pending promises inside `act`.

- [ ] **Step 1: Write the failing tests**

`apps/webapp/src/api/connectors.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { connectorsApi, ConnectorsError } from './connectors';

const base = import.meta.env.VITE_API_URL + '/api/v1/connectors';

function answer(status: number, body: unknown) {
    return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status }));
}

describe('connectorsApi', () => {
    beforeEach(() => { vi.restoreAllMocks(); });

    it('lists the connectors of a project', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(answer(200, []));
        await connectorsApi.list('p1');
        expect(fetchMock).toHaveBeenCalledWith(`${base}?project_pid=p1`, expect.objectContaining({}));
    });

    it('sends JSON for writes', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockReturnValue(answer(200, { pid: 'c1' }));
        await connectorsApi.create({ project_pid: 'p1', name: 'MCAS', environment: 'sandbox' });
        const [, init] = fetchMock.mock.calls[0];
        expect(init?.method).toBe('POST');
        expect(JSON.parse(String(init?.body))).toEqual({ project_pid: 'p1', name: 'MCAS', environment: 'sandbox' });
    });

    it('turns the service detail into the error message', async () => {
        vi.spyOn(globalThis, 'fetch').mockReturnValue(answer(409, { detail: 'confirm to allow it' }));
        await expect(connectorsApi.patchOperation('c1', 'op', { allowed: true }))
            .rejects.toMatchObject({ status: 409, message: 'confirm to allow it' });
    });

    it('reports 401 as a sign-in problem', async () => {
        vi.spyOn(globalThis, 'fetch').mockReturnValue(answer(401, { detail: 'expired' }));
        const error = await connectorsApi.list('p1').catch((e) => e);
        expect(error).toBeInstanceOf(ConnectorsError);
        expect(error.needsSignIn).toBe(true);
    });

    it('treats 204 as done', async () => {
        vi.spyOn(globalThis, 'fetch').mockReturnValue(answer(204, null));
        await expect(connectorsApi.remove('c1')).resolves.toBeUndefined();
    });
});
```

`apps/webapp/src/auth/useIsAdmin.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }));
import { useAuth } from '../context/AuthContext';
import { useIsAdmin } from './useIsAdmin';

function Probe() { return <span>{useIsAdmin() ? 'admin' : 'not'}</span>; }

function show(roles: string[]) {
    (useAuth as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ roles });
    const div = document.createElement('div');
    act(() => { createRoot(div).render(<Probe />); });
    return div.textContent;
}

it('is true only with the admin realm role', () => {
    expect(show(['admin'])).toBe('admin');
    expect(show(['primary-user'])).toBe('not');
    expect(show([])).toBe('not');
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/webapp && npx vitest run src/api/connectors.test.ts src/auth/useIsAdmin.test.tsx`
Expected: FAIL, `Failed to resolve import "./connectors"`.

- [ ] **Step 3: Implement**

`apps/webapp/src/models/connectors.ts`:

```ts
// Shapes returned by the connectors service (apps/connectors). The service decides; the page shows.
export type Field = {
    name: string; label: string; type: 'url' | 'text' | 'textarea' | 'select' | 'boolean';
    required: boolean; options?: string[]; help?: string;
};
export type ConnectorType = { kind: string; label: string; description: string; fields: Field[] };
export type AuthScheme = {
    scheme: string; label: string; fields: Field[];
    secrets: { name: string; label: string; multiline: boolean }[];
};
export type Catalogue = { connector_types: ConnectorType[]; auth_schemes: AuthScheme[] };
export type SecretInfo = { name: string; masked: string; updated_at: string };
export type Connector = {
    pid: string; project_pid: string; ai_system_pid: string; name: string; slug: string; kind: string;
    environment: 'sandbox' | 'production'; auth: Record<string, string>; settings: Record<string, unknown>;
    chat: ChatMapping | null; is_target_access: boolean; import_warnings: string[]; secrets: SecretInfo[];
    orphaned: boolean;
};
export type ChatMapping = {
    operation_id: string; input_mode: 'text' | 'messages'; input_field: string; answer_path: string;
    extra_body: Record<string, unknown>;
};
export type OperationRow = {
    operation_id: string; method: string; path: string; summary: string; changes_data: boolean;
    allowed: boolean; changes_data_confirmed: boolean; patterns: Record<string, unknown>; component_pids: string[];
};
export type ImportAnswer = {
    operations: OperationRow[]; warnings: string[]; auth: Record<string, string>;
    detected_secrets: string[]; chat: ChatMapping | null;
};
export type TestAnswer = {
    outcome: string; status: number | null; latency_ms?: number; content_type?: string | null;
    body_json?: unknown; body_text?: string; binary?: boolean; size?: number; message?: string;
};
export type Publication = {
    published: boolean; view_url?: string; openai_base_url?: string | null; secret_key?: string;
    resource_component_pid?: string; llm_component_pid?: string | null;
};
export type PublishAnswer = {
    token: string; secret_key: string; view_url: string; openai_base_url: string | null;
    ollama_url: string | null; resource_component_pid: string; llm_component_pid: string | null;
};
export type CallRow = {
    operation_id: string | null; via: string; outcome: string; target_status: number | null;
    latency_ms: number; at: string;
};
```

`apps/webapp/src/api/connectors.ts`:

```ts
import { API_VERSION_PREFIX } from '../config';
import type {
    Catalogue, ChatMapping, Connector, CallRow, ImportAnswer, OperationRow, Publication, PublishAnswer, TestAnswer,
} from '../models/connectors';

// Same base as the engine API, so the token-patched fetch signs these calls; Caddy routes the prefix.
const BASE = import.meta.env.VITE_API_URL + API_VERSION_PREFIX + '/connectors';

export class ConnectorsError extends Error {
    status: number;
    needsSignIn: boolean;
    constructor(status: number, message: string) {
        super(message);
        this.status = status;
        this.needsSignIn = status === 401;
    }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(BASE + path, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    });
    if (response.status === 204) return undefined as T;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = (body as { detail?: unknown }).detail;
        throw new ConnectorsError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail ?? body));
    }
    return body as T;
}

const send = (method: string, body?: unknown): RequestInit =>
    ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const connectorsApi = {
    types: () => call<Catalogue>('/types'),
    list: (projectPid: string) => call<Connector[]>(`?project_pid=${projectPid}`),
    readiness: (projectPid: string) => call<{ has_target_access: boolean }>(`/projects/${projectPid}/readiness`),
    create: (body: { project_pid: string; name: string; environment: string }) => call<Connector>('', send('POST', body)),
    get: (cid: string) => call<Connector>(`/${cid}`),
    patch: (cid: string, body: Record<string, unknown>) => call<Connector>(`/${cid}`, send('PATCH', body)),
    remove: (cid: string) => call<void>(`/${cid}`, send('DELETE')),
    makeTargetAccess: (cid: string) => call<Connector>(`/${cid}/target-access`, send('POST')),
    setAuth: (cid: string, auth: Record<string, string>) => call<Connector>(`/${cid}/auth`, send('PUT', auth)),
    setServer: (cid: string, url: string) => call<Connector>(`/${cid}/server`, send('PUT', { url })),
    putSecret: (cid: string, name: string, value: string) => call<unknown>(`/${cid}/secrets/${name}`, send('PUT', { value })),
    deleteSecret: (cid: string, name: string) => call<void>(`/${cid}/secrets/${name}`, send('DELETE')),
    importSource: (cid: string, body: Record<string, unknown>) => call<ImportAnswer>(`/${cid}/import`, send('POST', body)),
    operations: (cid: string) => call<OperationRow[]>(`/${cid}/operations`),
    patchOperation: (cid: string, operationId: string, body: Record<string, unknown>) =>
        call<OperationRow>(`/${cid}/operations/${encodeURIComponent(operationId)}`, send('PATCH', body)),
    testOperation: (cid: string, operationId: string, body: Record<string, unknown>) =>
        call<TestAnswer>(`/${cid}/operations/${encodeURIComponent(operationId)}/test`, send('POST', body)),
    setChat: (cid: string, mapping: ChatMapping) => call<Connector>(`/${cid}/chat`, send('PUT', mapping)),
    view: (cid: string) => call<Record<string, unknown>>(`/${cid}/view`),
    publication: (cid: string) => call<Publication>(`/${cid}/publish`),
    publish: (cid: string) => call<PublishAnswer>(`/${cid}/publish`, send('POST')),
    unpublish: (cid: string) => call<void>(`/${cid}/publish`, send('DELETE')),
    calls: (cid: string) => call<CallRow[]>(`/${cid}/calls`),
};
```

`apps/webapp/src/auth/useIsAdmin.ts`:

```ts
import { useAuth } from '../context/AuthContext';

/** Whether to show admin-only UI. The service enforces it; this only hides what would be refused. */
export function useIsAdmin(): boolean {
    return (useAuth().roles ?? []).includes('admin');
}
```

`apps/webapp/src/components/connectors/testUtils.tsx`:

```tsx
import { act } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

export function render(ui: ReactNode) {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() => { root.render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>); });
    return { container, unmount: () => act(() => root.unmount()) };
}

export async function flush() {
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

export function click(element: Element | null) {
    act(() => { (element as HTMLElement).click(); });
}

export function type(input: Element | null, value: string) {
    const el = input as HTMLInputElement | HTMLTextAreaElement;
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')!.set!;
    act(() => { setter.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); });
}
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/webapp && npx vitest run src/api/connectors.test.ts src/auth/useIsAdmin.test.tsx`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C apps/webapp add src/models/connectors.ts src/api/connectors.ts src/api/connectors.test.ts src/auth/useIsAdmin.ts src/auth/useIsAdmin.test.tsx src/components/connectors/testUtils.tsx
git -C apps/webapp commit -m "Connectors page foundations: types, API client, admin check"
```

---

### Task 4: The list and "New connector"

**Files:**
- Create: `apps/webapp/src/components/connectors/FieldsForm.tsx`
- Create: `apps/webapp/src/pages/Connectors.tsx`
- Test: `apps/webapp/src/components/connectors/FieldsForm.test.tsx`, `apps/webapp/src/pages/Connectors.test.tsx`

**Interfaces:**
- Consumes: `connectorsApi.types/list/readiness/create/importSource`, `useProject().projectUUID`, `useNavigate`.
- Produces: `FieldsForm({fields, values, onChange})`, rendering one MUI control per `Field` with `data-field={name}`; `ConnectorsPage` (default export of `pages/Connectors.tsx`): a readiness warning (`data-testid="no-target-access"`), a table of connectors (`data-testid="connector-row"` per row, name, type label, environment, "Target access" chip, "Orphaned" chip), and a "New connector" dialog (type select `data-testid="type-select"`, name, environment, the type's fields, "Connect" button). "Connect" calls `create` then `importSource` and navigates to `./<pid>`; an import error is shown in the dialog and the created connector stays (the admin can retry on its detail page).

- [ ] **Step 1: Write the failing tests**

`apps/webapp/src/components/connectors/FieldsForm.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import FieldsForm from './FieldsForm';
import { render, type } from './testUtils';

it('renders one control per field and reports changes', () => {
    const onChange = vi.fn();
    const { container } = render(<FieldsForm values={{}} onChange={onChange} fields={[
        { name: 'url', label: 'Where', type: 'url', required: true },
        { name: 'text', label: 'Paste', type: 'textarea', required: false },
    ]} />);
    expect(container.querySelectorAll('[data-field]').length).toBe(2);
    type(container.querySelector('[data-field="url"] input'), 'http://x');
    expect(onChange).toHaveBeenCalledWith({ url: 'http://x' });
});
```

`apps/webapp/src/pages/Connectors.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi, beforeEach } from 'vitest';
import { render, flush, click, type } from '../components/connectors/testUtils';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
vi.mock('../context/ProjectContext', () => ({ useProject: () => ({ projectUUID: 'p1' }) }));
vi.mock('../api/connectors', () => ({
    connectorsApi: {
        types: vi.fn(), list: vi.fn(), readiness: vi.fn(), create: vi.fn(), importSource: vi.fn(),
    },
    ConnectorsError: class extends Error {},
}));
import { connectorsApi } from '../api/connectors';
import ConnectorsPage from './Connectors';

const api = connectorsApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const catalogue = {
    connector_types: [{ kind: 'openapi', label: 'OpenAPI or Swagger', description: 'd',
                        fields: [{ name: 'url', label: 'Where', type: 'url', required: false }] }],
    auth_schemes: [],
};

beforeEach(() => {
    vi.clearAllMocks();
    api.types.mockResolvedValue(catalogue);
});

it('warns when no connector gives target access', async () => {
    api.list.mockResolvedValue([]);
    api.readiness.mockResolvedValue({ has_target_access: false });
    const { container } = render(<ConnectorsPage />);
    await flush();
    expect(container.querySelector('[data-testid="no-target-access"]')).not.toBeNull();
});

it('lists connectors with their badges', async () => {
    api.list.mockResolvedValue([{ pid: 'c1', name: 'MCAS', kind: 'openapi', environment: 'sandbox',
                                  is_target_access: true, orphaned: false }]);
    api.readiness.mockResolvedValue({ has_target_access: true });
    const { container } = render(<ConnectorsPage />);
    await flush();
    const row = container.querySelector('[data-testid="connector-row"]');
    expect(row?.textContent).toContain('MCAS');
    expect(row?.textContent).toContain('OpenAPI or Swagger');
    expect(row?.textContent).toContain('Target access');
    expect(container.querySelector('[data-testid="no-target-access"]')).toBeNull();
});

it('creates, imports and opens the new connector', async () => {
    api.list.mockResolvedValue([]);
    api.readiness.mockResolvedValue({ has_target_access: false });
    api.create.mockResolvedValue({ pid: 'c9' });
    api.importSource.mockResolvedValue({ operations: [], warnings: [] });
    const { container } = render(<ConnectorsPage />);
    await flush();
    click(document.querySelector('[data-testid="new-connector"]'));
    type(document.querySelector('[data-testid="connector-name"] input'), 'MCAS');
    type(document.querySelector('[data-field="url"] input'), 'http://172.17.0.1:8500/openapi.json');
    click(document.querySelector('[data-testid="connect"]'));
    await flush();
    expect(api.create).toHaveBeenCalledWith({ project_pid: 'p1', name: 'MCAS', environment: 'sandbox' });
    expect(api.importSource).toHaveBeenCalledWith('c9', { kind: 'openapi', url: 'http://172.17.0.1:8500/openapi.json' });
    expect(navigate).toHaveBeenCalledWith('c9');
    expect(container).toBeTruthy();
});

it('shows an import failure in the dialog', async () => {
    api.list.mockResolvedValue([]);
    api.readiness.mockResolvedValue({ has_target_access: false });
    api.create.mockResolvedValue({ pid: 'c9' });
    api.importSource.mockRejectedValue(new Error('the spec names no server: give the base URL'));
    render(<ConnectorsPage />);
    await flush();
    click(document.querySelector('[data-testid="new-connector"]'));
    type(document.querySelector('[data-testid="connector-name"] input'), 'X');
    click(document.querySelector('[data-testid="connect"]'));
    await flush();
    expect(document.body.textContent).toContain('give the base URL');
    expect(navigate).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/webapp && npx vitest run src/components/connectors/FieldsForm.test.tsx src/pages/Connectors.test.tsx`
Expected: FAIL, `Failed to resolve import "./FieldsForm"`.

- [ ] **Step 3: Implement**

`apps/webapp/src/components/connectors/FieldsForm.tsx`:

```tsx
import { FormControlLabel, MenuItem, Stack, Switch, TextField } from '@mui/material';
import type { Field } from '../../models/connectors';

type Props = { fields: Field[]; values: Record<string, string>; onChange: (values: Record<string, string>) => void };

/** One control per field the service describes. No rules here: the service validates. */
export default function FieldsForm({ fields, values, onChange }: Props) {
    const set = (name: string, value: string) => onChange({ ...values, [name]: value });
    return (
        <Stack spacing={2}>
            {fields.map((f) => f.type === 'boolean' ? (
                <FormControlLabel key={f.name} data-field={f.name} label={f.label} control={
                    <Switch checked={values[f.name] === 'true'} onChange={(e) => set(f.name, String(e.target.checked))} />} />
            ) : (
                <TextField key={f.name} data-field={f.name} label={f.label} required={f.required} helperText={f.help}
                    value={values[f.name] ?? ''} onChange={(e) => set(f.name, e.target.value)}
                    select={f.type === 'select'} multiline={f.type === 'textarea'} minRows={f.type === 'textarea' ? 4 : undefined}
                    type={f.type === 'url' ? 'url' : 'text'} fullWidth>
                    {(f.options ?? []).map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                </TextField>
            ))}
        </Stack>
    );
}
```

`apps/webapp/src/pages/Connectors.tsx`:

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
    Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Table, TableBody,
    TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material';
import { connectorsApi } from '../api/connectors';
import { useProject } from '../context/ProjectContext';
import FieldsForm from '../components/connectors/FieldsForm';

export default function ConnectorsPage() {
    const { projectUUID } = useProject();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const catalogue = useQuery({ queryKey: ['connectors', 'types'], queryFn: connectorsApi.types });
    const list = useQuery({ queryKey: ['connectors', projectUUID], queryFn: () => connectorsApi.list(projectUUID!),
                            enabled: !!projectUUID });
    const readiness = useQuery({ queryKey: ['connectors', projectUUID, 'readiness'],
                                 queryFn: () => connectorsApi.readiness(projectUUID!), enabled: !!projectUUID });
    const [open, setOpen] = useState(false);
    const [kind, setKind] = useState('openapi');
    const [name, setName] = useState('');
    const [environment, setEnvironment] = useState('sandbox');
    const [values, setValues] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const types = catalogue.data?.connector_types ?? [];
    const chosen = types.find((t) => t.kind === kind);
    const labelOf = (k: string) => types.find((t) => t.kind === k)?.label ?? k;

    async function connect() {
        setBusy(true);
        setError(null);
        try {
            const created = await connectorsApi.create({ project_pid: projectUUID!, name, environment });
            await queryClient.invalidateQueries({ queryKey: ['connectors', projectUUID] });
            await connectorsApi.importSource(created.pid, { kind, ...values });
            navigate(created.pid);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }

    const failure = [list.error, readiness.error, catalogue.error].find(Boolean) as { needsSignIn?: boolean; message?: string } | undefined;
    return (
        <Box sx={{ p: 3 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                <Typography variant="h5">Connectors</Typography>
                <Button variant="contained" data-testid="new-connector" onClick={() => setOpen(true)}>New connector</Button>
            </Stack>
            {failure && <Alert severity="error" sx={{ mb: 2 }}>
                {failure.needsSignIn ? 'Your session has ended: sign in again.' : failure.message}</Alert>}
            {readiness.data && !readiness.data.has_target_access && (
                <Alert severity="warning" data-testid="no-target-access" sx={{ mb: 2 }}>
                    No connector gives access to the assessed system yet. Create one: the first becomes the target access.
                </Alert>)}
            <Table size="small">
                <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Type</TableCell>
                    <TableCell>Environment</TableCell><TableCell /></TableRow></TableHead>
                <TableBody>
                    {(list.data ?? []).map((c) => (
                        <TableRow key={c.pid} hover data-testid="connector-row" sx={{ cursor: 'pointer' }}
                            onClick={() => navigate(c.pid)}>
                            <TableCell>{c.name}</TableCell>
                            <TableCell>{labelOf(c.kind)}</TableCell>
                            <TableCell>{c.environment}</TableCell>
                            <TableCell>
                                {c.is_target_access && <Chip size="small" color="primary" label="Target access" />}
                                {c.orphaned && <Chip size="small" color="warning" label="Orphaned" sx={{ ml: 1 }} />}
                            </TableCell>
                        </TableRow>))}
                </TableBody>
            </Table>
            <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
                <DialogTitle>New connector</DialogTitle>
                <DialogContent>
                    <Stack spacing={2} sx={{ mt: 1 }}>
                        <TextField select label="Connector type" value={kind} data-testid="type-select"
                            onChange={(e) => { setKind(e.target.value); setValues({}); }}>
                            {types.map((t) => <MenuItem key={t.kind} value={t.kind}>{t.label}</MenuItem>)}
                        </TextField>
                        {chosen && <Typography variant="body2" color="text.secondary">{chosen.description}</Typography>}
                        <TextField label="Name" value={name} data-testid="connector-name" onChange={(e) => setName(e.target.value)} />
                        <TextField select label="Environment" value={environment} onChange={(e) => setEnvironment(e.target.value)}>
                            <MenuItem value="sandbox">Sandbox (test system)</MenuItem>
                            <MenuItem value="production">Production</MenuItem>
                        </TextField>
                        {chosen && <FieldsForm fields={chosen.fields} values={values} onChange={setValues} />}
                        {error && <Alert severity="error">{error}</Alert>}
                    </Stack>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setOpen(false)}>Cancel</Button>
                    <Button variant="contained" data-testid="connect" disabled={busy} onClick={connect}>Connect</Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/webapp && npx vitest run src/components/connectors/FieldsForm.test.tsx src/pages/Connectors.test.tsx`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git -C apps/webapp add src/components/connectors/FieldsForm.tsx src/components/connectors/FieldsForm.test.tsx src/pages/Connectors.tsx src/pages/Connectors.test.tsx
git -C apps/webapp commit -m "Connectors page: list, readiness warning, new connector from any type"
```

---

### Task 5: Detail view, part 1: credentials and operations

**Files:**
- Create: `apps/webapp/src/components/connectors/CredentialsPanel.tsx`, `apps/webapp/src/components/connectors/OperationsPanel.tsx`
- Create: `apps/webapp/src/pages/ConnectorDetail.tsx`
- Test: `apps/webapp/src/components/connectors/CredentialsPanel.test.tsx`, `apps/webapp/src/components/connectors/OperationsPanel.test.tsx`

**Interfaces:**
- Consumes: `connectorsApi.get/types/setAuth/putSecret/operations/patchOperation`; the engine AI system's components come from the existing engine route `GET ${VITE_API_URL}/api/v1/projects/{projectUUID}/aisystem` (read with plain `fetch`, never through the frozen `src/api/api.tsx`).
- Produces:
  - `CredentialsPanel({connector, catalogue, onSaved})`: scheme select, the scheme's fields (`FieldsForm`), one password field per secret showing `masked` as placeholder, "Save" (calls `setAuth`, then `putSecret` for every non-empty secret field, then clears them).
  - `OperationsPanel({connectorPid, components})`: a filter box (`data-testid="operation-filter"`), rows sorted by path then method (`data-testid="operation-row"`), an allow switch (`data-testid="allow-<operation_id>"`), a "may change data" chip, a component multi-select, and a confirm dialog (`data-testid="confirm-dialog"`) that shows the service's 409 sentence and retries with `confirm_changes_data: true` and `confirm_production: true`.
  - `ConnectorDetailPage` (default export): reads `:connector_pid`, shows name, environment, target-access button, warnings, then tabs: Credentials, Operations, Test, OpenAPI view, Chat, Publish (the last four are placeholders until Task 6).

- [ ] **Step 1: Write the failing tests**

`apps/webapp/src/components/connectors/OperationsPanel.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi, beforeEach } from 'vitest';
import { render, flush, click, type } from './testUtils';

vi.mock('../../api/connectors', () => ({
    connectorsApi: { operations: vi.fn(), patchOperation: vi.fn() },
    ConnectorsError: class extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s; } },
}));
import { connectorsApi, ConnectorsError } from '../../api/connectors';
import OperationsPanel from './OperationsPanel';

const api = connectorsApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const row = (operation_id: string, method: string, path: string, changes_data = false) => ({
    operation_id, method, path, summary: '', changes_data, allowed: false, changes_data_confirmed: false,
    patterns: {}, component_pids: [],
});

beforeEach(() => vi.clearAllMocks());

it('operations are sorted and filterable', async () => {
    api.operations.mockResolvedValue([row('b', 'post', '/score', true), row('a', 'get', '/health'), row('c', 'post', '/chat', true)]);
    const { container } = render(<OperationsPanel connectorPid="c1" components={[]} />);
    await flush();
    const paths = () => [...container.querySelectorAll('[data-testid="operation-row"]')].map((r) => r.getAttribute('data-path'));
    expect(paths()).toEqual(['/chat', '/health', '/score']);
    type(container.querySelector('[data-testid="operation-filter"] input'), 'sco');
    expect(paths()).toEqual(['/score']);
});

it('a 409 on allow asks for confirmation and retries', async () => {
    api.operations.mockResolvedValue([row('chat', 'post', '/chat', true)]);
    api.patchOperation
        .mockRejectedValueOnce(new (ConnectorsError as unknown as new (s: number, m: string) => Error)(409, 'chat may change data in the target: confirm to allow it'))
        .mockResolvedValueOnce({ ...row('chat', 'post', '/chat', true), allowed: true });
    const { container } = render(<OperationsPanel connectorPid="c1" components={[]} />);
    await flush();
    click(container.querySelector('[data-testid="allow-chat"] input'));
    await flush();
    const dialog = document.querySelector('[data-testid="confirm-dialog"]');
    expect(dialog?.textContent).toContain('may change data');
    click(document.querySelector('[data-testid="confirm-yes"]'));
    await flush();
    expect(api.patchOperation).toHaveBeenLastCalledWith('c1', 'chat',
        { allowed: true, confirm_changes_data: true, confirm_production: true });
});
```

`apps/webapp/src/components/connectors/CredentialsPanel.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import { render, flush, click, type } from './testUtils';

vi.mock('../../api/connectors', () => ({
    connectorsApi: { setAuth: vi.fn().mockResolvedValue({}), putSecret: vi.fn().mockResolvedValue({}) },
}));
import { connectorsApi } from '../../api/connectors';
import CredentialsPanel from './CredentialsPanel';

const catalogue = { connector_types: [], auth_schemes: [
    { scheme: 'none', label: 'No credentials', fields: [], secrets: [] },
    { scheme: 'bearer', label: 'Bearer token', fields: [], secrets: [{ name: 'token', label: 'Token', multiline: false }] },
] };

it('saves the scheme, then only the secrets that were typed, and never shows a stored value', async () => {
    const connector = { pid: 'c1', auth: { scheme: 'bearer' }, secrets: [{ name: 'token', masked: 'sk****90', updated_at: '' }] };
    const { container } = render(<CredentialsPanel connector={connector as never} catalogue={catalogue} onSaved={() => {}} />);
    const secret = container.querySelector('[data-secret="token"] input') as HTMLInputElement;
    expect(secret.value).toBe('');
    expect(secret.placeholder).toBe('sk****90');
    type(secret, 'new-token');
    click(container.querySelector('[data-testid="save-credentials"]'));
    await flush();
    expect(connectorsApi.setAuth).toHaveBeenCalledWith('c1', { scheme: 'bearer' });
    expect(connectorsApi.putSecret).toHaveBeenCalledWith('c1', 'token', 'new-token');
    expect(secret.value).toBe('');
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/webapp && npx vitest run src/components/connectors/OperationsPanel.test.tsx src/components/connectors/CredentialsPanel.test.tsx`
Expected: FAIL, `Failed to resolve import "./OperationsPanel"`.

- [ ] **Step 3: Implement the panels**

`apps/webapp/src/components/connectors/CredentialsPanel.tsx`:

```tsx
import { useState } from 'react';
import { Alert, Button, MenuItem, Stack, TextField } from '@mui/material';
import { connectorsApi } from '../../api/connectors';
import type { Catalogue, Connector } from '../../models/connectors';
import FieldsForm from './FieldsForm';

type Props = { connector: Connector; catalogue: Catalogue; onSaved: () => void };

/** Secrets are write-only: the field starts empty, the masked value is only a hint. */
export default function CredentialsPanel({ connector, catalogue, onSaved }: Props) {
    const [auth, setAuth] = useState<Record<string, string>>(connector.auth ?? { scheme: 'none' });
    const [secrets, setSecrets] = useState<Record<string, string>>({});
    const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
    const scheme = catalogue.auth_schemes.find((s) => s.scheme === auth.scheme);
    const masked = (name: string) => connector.secrets.find((s) => s.name === name)?.masked ?? '';
    const { scheme: _scheme, ...fieldValues } = auth;

    async function save() {
        try {
            await connectorsApi.setAuth(connector.pid, auth);
            for (const [name, value] of Object.entries(secrets)) {
                if (value) await connectorsApi.putSecret(connector.pid, name, value);
            }
            setSecrets({});
            setMessage({ ok: true, text: 'Saved.' });
            onSaved();
        } catch (e) {
            setMessage({ ok: false, text: (e as Error).message });
        }
    }

    return (
        <Stack spacing={2} sx={{ maxWidth: 560 }}>
            <TextField select label="Credentials" value={auth.scheme} onChange={(e) => setAuth({ scheme: e.target.value })}>
                {catalogue.auth_schemes.map((s) => <MenuItem key={s.scheme} value={s.scheme}>{s.label}</MenuItem>)}
            </TextField>
            {scheme && <FieldsForm fields={scheme.fields} values={fieldValues}
                onChange={(v) => setAuth({ scheme: auth.scheme, ...v })} />}
            {scheme?.secrets.map((s) => (
                <TextField key={s.name} data-secret={s.name} label={s.label} type={s.multiline ? 'text' : 'password'}
                    multiline={s.multiline} minRows={s.multiline ? 4 : undefined} placeholder={masked(s.name)}
                    value={secrets[s.name] ?? ''} onChange={(e) => setSecrets({ ...secrets, [s.name]: e.target.value })}
                    helperText={masked(s.name) ? 'Stored. Type a new value to replace it.' : 'Not set.'} />))}
            {message && <Alert severity={message.ok ? 'success' : 'error'}>{message.text}</Alert>}
            <Button variant="contained" data-testid="save-credentials" onClick={save}>Save</Button>
        </Stack>
    );
}
```

`apps/webapp/src/components/connectors/OperationsPanel.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
    Alert, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Switch, Table, TableBody,
    TableCell, TableHead, TableRow, TextField,
} from '@mui/material';
import { connectorsApi, ConnectorsError } from '../../api/connectors';
import type { OperationRow } from '../../models/connectors';

type Component = { pid: string; name: string };
type Props = { connectorPid: string; components: Component[] };

export default function OperationsPanel({ connectorPid, components }: Props) {
    const queryClient = useQueryClient();
    const key = ['connectors', connectorPid, 'operations'];
    const ops = useQuery({ queryKey: key, queryFn: () => connectorsApi.operations(connectorPid) });
    const [filter, setFilter] = useState('');
    const [pending, setPending] = useState<{ op: OperationRow; question: string } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const rows = useMemo(() => [...(ops.data ?? [])]
        .sort((a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method))
        .filter((o) => `${o.method} ${o.path} ${o.summary} ${o.operation_id}`.toLowerCase().includes(filter.toLowerCase())),
        [ops.data, filter]);

    async function change(op: OperationRow, body: Record<string, unknown>) {
        setError(null);
        try {
            await connectorsApi.patchOperation(connectorPid, op.operation_id, body);
            await queryClient.invalidateQueries({ queryKey: key });
        } catch (e) {
            if (e instanceof ConnectorsError && (e as ConnectorsError).status === 409) {
                setPending({ op, question: e.message });
            } else {
                setError((e as Error).message);
            }
        }
    }

    async function confirm() {
        const op = pending!.op;
        setPending(null);
        await change(op, { allowed: true, confirm_changes_data: true, confirm_production: true });
    }

    return (
        <Stack spacing={2}>
            <TextField data-testid="operation-filter" size="small" label="Filter" value={filter}
                onChange={(e) => setFilter(e.target.value)} sx={{ maxWidth: 320 }} />
            {error && <Alert severity="error">{error}</Alert>}
            <Table size="small">
                <TableHead><TableRow><TableCell>Allowed</TableCell><TableCell>Operation</TableCell>
                    <TableCell>Exercises</TableCell></TableRow></TableHead>
                <TableBody>
                    {rows.map((o) => (
                        <TableRow key={o.operation_id} data-testid="operation-row" data-path={o.path}>
                            <TableCell>
                                <Switch data-testid={`allow-${o.operation_id}`} checked={o.allowed}
                                    onChange={(e) => change(o, { allowed: e.target.checked })} />
                            </TableCell>
                            <TableCell>
                                <b>{o.method.toUpperCase()}</b> {o.path} {o.summary && `: ${o.summary}`}
                                {o.changes_data && <Chip size="small" color="warning" label="may change data" sx={{ ml: 1 }} />}
                            </TableCell>
                            <TableCell>
                                <TextField select size="small" value={o.component_pids} sx={{ minWidth: 200 }}
                                    SelectProps={{ multiple: true }}
                                    onChange={(e) => change(o, { component_pids: e.target.value as unknown as string[] })}>
                                    {components.map((c) => <MenuItem key={c.pid} value={c.pid}>{c.name}</MenuItem>)}
                                </TextField>
                            </TableCell>
                        </TableRow>))}
                </TableBody>
            </Table>
            <Dialog open={!!pending} onClose={() => setPending(null)} data-testid="confirm-dialog">
                <DialogTitle>Confirm</DialogTitle>
                <DialogContent>{pending?.question}</DialogContent>
                <DialogActions>
                    <Button onClick={() => setPending(null)}>Cancel</Button>
                    <Button variant="contained" color="warning" data-testid="confirm-yes" onClick={confirm}>Allow it</Button>
                </DialogActions>
            </Dialog>
        </Stack>
    );
}
```

`apps/webapp/src/pages/ConnectorDetail.tsx`:

```tsx
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Box, Button, Chip, Stack, Tab, Tabs, TextField, Typography } from '@mui/material';
import { connectorsApi } from '../api/connectors';
import { API_VERSION_PREFIX } from '../config';
import { useProject } from '../context/ProjectContext';
import CredentialsPanel from '../components/connectors/CredentialsPanel';
import OperationsPanel from '../components/connectors/OperationsPanel';

const ENGINE = import.meta.env.VITE_API_URL + API_VERSION_PREFIX;

export default function ConnectorDetailPage() {
    const { connector_pid: cid } = useParams();
    const { projectUUID } = useProject();
    const queryClient = useQueryClient();
    const [tab, setTab] = useState(0);
    const [server, setServer] = useState<string | null>(null);
    const connector = useQuery({ queryKey: ['connectors', cid], queryFn: () => connectorsApi.get(cid!), enabled: !!cid });
    const catalogue = useQuery({ queryKey: ['connectors', 'types'], queryFn: connectorsApi.types });
    const system = useQuery({
        queryKey: ['aisystem', projectUUID], enabled: !!projectUUID,
        queryFn: async () => (await fetch(`${ENGINE}/projects/${projectUUID}/aisystem`)).json(),
    });
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['connectors', cid] });
    if (!connector.data || !catalogue.data) return <Box sx={{ p: 3 }}>{connector.error?.message ?? 'Loading...'}</Box>;
    const c = connector.data;
    const components = (system.data?.components ?? []) as { pid: string; name: string }[];
    return (
        <Box sx={{ p: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                <Typography variant="h5">{c.name}</Typography>
                <Chip label={c.environment} color={c.environment === 'production' ? 'error' : 'default'} />
                {c.is_target_access
                    ? <Chip color="primary" label="Target access" />
                    : <Button size="small" onClick={async () => { await connectorsApi.makeTargetAccess(c.pid); refresh(); }}>
                        Make this the target access</Button>}
            </Stack>
            {c.import_warnings.map((w) => <Alert key={w} severity="info" sx={{ mb: 1 }}>{w}</Alert>)}
            <Stack direction="row" spacing={1} sx={{ mb: 2, maxWidth: 640 }}>
                <TextField size="small" fullWidth label="Server the connector calls" placeholder="https://api.example.com"
                    value={server ?? ''} onChange={(e) => setServer(e.target.value)}
                    helperText="Leave empty to keep the address from the import." />
                <Button disabled={!server} onClick={async () => { await connectorsApi.setServer(c.pid, server!); setServer(null); refresh(); }}>
                    Save</Button>
            </Stack>
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
                <Tab label="Credentials" /><Tab label="Operations" /><Tab label="Test" />
                <Tab label="OpenAPI view" /><Tab label="Chat" /><Tab label="Publish" />
            </Tabs>
            {tab === 0 && <CredentialsPanel connector={c} catalogue={catalogue.data} onSaved={refresh} />}
            {tab === 1 && <OperationsPanel connectorPid={c.pid} components={components} />}
            {tab >= 2 && <Typography color="text.secondary">Coming in the next task.</Typography>}
        </Box>
    );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/webapp && npx vitest run src/components/connectors/`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git -C apps/webapp add src/components/connectors/CredentialsPanel.tsx src/components/connectors/CredentialsPanel.test.tsx src/components/connectors/OperationsPanel.tsx src/components/connectors/OperationsPanel.test.tsx src/pages/ConnectorDetail.tsx
git -C apps/webapp commit -m "Connector detail: write-only credentials, operations with confirmations and component links"
```

---

### Task 6: Detail view, part 2: test, OpenAPI view, chat, publish

**Files:**
- Create: `apps/webapp/src/components/connectors/TestPanel.tsx`, `OpenApiView.tsx`, `ChatPanel.tsx`, `PublishPanel.tsx`
- Modify: `apps/webapp/src/pages/ConnectorDetail.tsx` (replace the placeholder for tabs 2 to 5)
- Test: `apps/webapp/src/components/connectors/TestPanel.test.tsx`, `OpenApiView.test.tsx`, `PublishPanel.test.tsx`

**Interfaces:**
- Consumes: `connectorsApi.operations/testOperation/view/setChat/publication/publish/unpublish/calls`.
- Produces:
  - `TestPanel({connectorPid})`: operation select, JSON body editor (`data-testid="test-body"`), path/query params as `name=value` lines, a "may change data" confirmation checkbox, "Run" (`data-testid="run-test"`), and the answer: outcome chip (`data-testid="outcome"`), status, latency, JSON or text body; below, the recent calls table.
  - `OpenApiView({connectorPid})`: one line per path and method (`data-testid="view-operation"`) with summary; a "Raw JSON" toggle (`data-testid="raw-toggle"`) showing the document in a `<pre>`; a "Copy" button.
  - `ChatPanel({connector, onSaved})`: operation select (allowed operations only), input mode, input field, answer path, extra body JSON, "Save".
  - `PublishPanel({connector})`: when unpublished, "Publish to the AI system" (`data-testid="publish"`); after publish, a one-time box (`data-testid="one-time-token"`) with the token, view URL, OpenAI base URL and (if any) Ollama URL, with the sentence "Shown once: copy it now."; when published, the URLs, secret key name and "Unpublish". The token lives only in this component's state.

- [ ] **Step 1: Write the failing tests**

`apps/webapp/src/components/connectors/TestPanel.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import { render, flush, click, type } from './testUtils';

vi.mock('../../api/connectors', () => ({
    connectorsApi: {
        operations: vi.fn().mockResolvedValue([{ operation_id: 'chat', method: 'post', path: '/chat', summary: '',
            changes_data: true, allowed: true, changes_data_confirmed: true, patterns: {}, component_pids: [] }]),
        testOperation: vi.fn().mockResolvedValue({ outcome: 'auth', status: 401, latency_ms: 12,
            content_type: 'application/json', body_json: { error: 'bad key' } }),
        calls: vi.fn().mockResolvedValue([]),
    },
}));
import { connectorsApi } from '../../api/connectors';
import TestPanel from './TestPanel';

it('runs the operation with a JSON body and shows the named outcome', async () => {
    const { container } = render(<TestPanel connectorPid="c1" />);
    await flush();
    type(container.querySelector('[data-testid="test-body"] textarea'), '{"question": "hi"}');
    click(container.querySelector('[data-testid="confirm-changes"] input'));
    click(container.querySelector('[data-testid="run-test"]'));
    await flush();
    expect(connectorsApi.testOperation).toHaveBeenCalledWith('c1', 'chat', expect.objectContaining({
        body: { question: 'hi' }, confirm_changes_data: true }));
    expect(container.querySelector('[data-testid="outcome"]')?.textContent).toContain('auth');
    expect(container.textContent).toContain('bad key');
});

it('refuses a body that is not JSON before calling the service', async () => {
    const { container } = render(<TestPanel connectorPid="c1" />);
    await flush();
    type(container.querySelector('[data-testid="test-body"] textarea'), '{nope');
    click(container.querySelector('[data-testid="run-test"]'));
    await flush();
    expect(container.textContent).toContain('not JSON');
});
```

`apps/webapp/src/components/connectors/OpenApiView.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import { render, flush, click } from './testUtils';

vi.mock('../../api/connectors', () => ({
    connectorsApi: { view: vi.fn().mockResolvedValue({
        openapi: '3.1.0', servers: [{ url: 'http://connectors:8097/gw/c1' }],
        paths: { '/chat': { post: { summary: 'Chat' } }, '/score': { post: { summary: 'Score' } } } }) },
}));
import OpenApiView from './OpenApiView';

it('lists the operations plugins can call and shows the raw document on demand', async () => {
    const { container } = render(<OpenApiView connectorPid="c1" />);
    await flush();
    const lines = [...container.querySelectorAll('[data-testid="view-operation"]')].map((e) => e.textContent);
    expect(lines).toEqual(['POST /chat Chat', 'POST /score Score']);
    expect(container.textContent).toContain('http://connectors:8097/gw/c1');
    expect(container.querySelector('pre')).toBeNull();
    click(container.querySelector('[data-testid="raw-toggle"] input'));
    expect(container.querySelector('pre')?.textContent).toContain('"openapi": "3.1.0"');
});
```

`apps/webapp/src/components/connectors/PublishPanel.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import { render, flush, click } from './testUtils';

vi.mock('../../api/connectors', () => ({
    connectorsApi: {
        publication: vi.fn().mockResolvedValue({ published: false }),
        publish: vi.fn().mockResolvedValue({ token: 'aisc_ct_secret', secret_key: 'CONNECTOR_MCAS_TOKEN',
            view_url: 'http://connectors:8097/gw/c1/openapi.json', openai_base_url: null, ollama_url: null,
            resource_component_pid: 'r1', llm_component_pid: null }),
        unpublish: vi.fn(),
    },
}));
import PublishPanel from './PublishPanel';

it('the publish token is shown once and not cached', async () => {
    const first = render(<PublishPanel connector={{ pid: 'c1' } as never} />);
    await flush();
    click(first.container.querySelector('[data-testid="publish"]'));
    await flush();
    expect(first.container.querySelector('[data-testid="one-time-token"]')?.textContent).toContain('aisc_ct_secret');
    first.unmount();
    const second = render(<PublishPanel connector={{ pid: 'c1' } as never} />);
    await flush();
    expect(second.container.textContent).not.toContain('aisc_ct_secret');
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/webapp && npx vitest run src/components/connectors/TestPanel.test.tsx src/components/connectors/OpenApiView.test.tsx src/components/connectors/PublishPanel.test.tsx`
Expected: FAIL, `Failed to resolve import "./TestPanel"`.

- [ ] **Step 3: Implement the panels**

`apps/webapp/src/components/connectors/TestPanel.tsx`:

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Checkbox, Chip, FormControlLabel, MenuItem, Stack, Table, TableBody, TableCell, TableRow,
         TextField, Typography } from '@mui/material';
import { connectorsApi } from '../../api/connectors';
import type { TestAnswer } from '../../models/connectors';

const lines = (text: string) => Object.fromEntries(text.split('\n').map((l) => l.split('=')).filter((p) => p.length === 2)
    .map(([k, v]) => [k.trim(), v.trim()]));

export default function TestPanel({ connectorPid }: { connectorPid: string }) {
    const ops = useQuery({ queryKey: ['connectors', connectorPid, 'operations'], queryFn: () => connectorsApi.operations(connectorPid) });
    const calls = useQuery({ queryKey: ['connectors', connectorPid, 'calls'], queryFn: () => connectorsApi.calls(connectorPid) });
    const [chosen, setChosen] = useState<string>('');
    const [body, setBody] = useState('');
    const [params, setParams] = useState('');
    const [confirm, setConfirm] = useState(false);
    const [answer, setAnswer] = useState<TestAnswer | null>(null);
    const [error, setError] = useState<string | null>(null);
    const operationId = chosen || ops.data?.[0]?.operation_id || '';

    async function run() {
        setError(null);
        let parsed: unknown = undefined;
        if (body.trim()) {
            try { parsed = JSON.parse(body); } catch { setError('The body is not JSON.'); return; }
        }
        try {
            setAnswer(await connectorsApi.testOperation(connectorPid, operationId, {
                body: parsed, path_params: lines(params), confirm_changes_data: confirm }));
            calls.refetch();
        } catch (e) { setError((e as Error).message); }
    }

    return (
        <Stack spacing={2} sx={{ maxWidth: 820 }}>
            <TextField select label="Operation" value={operationId} onChange={(e) => setChosen(e.target.value)}>
                {(ops.data ?? []).map((o) => <MenuItem key={o.operation_id} value={o.operation_id}>
                    {o.method.toUpperCase()} {o.path}</MenuItem>)}
            </TextField>
            <TextField label="Path parameters (name=value, one per line)" multiline minRows={2} value={params}
                onChange={(e) => setParams(e.target.value)} />
            <TextField data-testid="test-body" label="Body (JSON)" multiline minRows={5} value={body}
                onChange={(e) => setBody(e.target.value)} />
            <FormControlLabel data-testid="confirm-changes" label="I know this may change data in the target"
                control={<Checkbox checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />} />
            <Button variant="contained" data-testid="run-test" onClick={run} sx={{ alignSelf: 'flex-start' }}>Run</Button>
            {error && <Alert severity="error">{error}</Alert>}
            {answer && (
                <Stack spacing={1}>
                    <Stack direction="row" spacing={1} alignItems="center">
                        <Chip data-testid="outcome" color={answer.outcome === 'ok' ? 'success' : 'error'} label={answer.outcome} />
                        {answer.status !== null && <Typography>HTTP {answer.status}</Typography>}
                        {answer.latency_ms !== undefined && <Typography color="text.secondary">{answer.latency_ms} ms</Typography>}
                    </Stack>
                    {answer.message && <Alert severity="warning">{answer.message}</Alert>}
                    <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f7f9', padding: 12 }}>
                        {answer.body_json !== undefined ? JSON.stringify(answer.body_json, null, 2)
                            : answer.binary ? `binary answer, ${answer.size} bytes` : answer.body_text}
                    </pre>
                </Stack>)}
            <Typography variant="subtitle2">Recent calls</Typography>
            <Table size="small"><TableBody>
                {(calls.data ?? []).map((c, i) => <TableRow key={i}><TableCell>{c.at}</TableCell><TableCell>{c.via}</TableCell>
                    <TableCell>{c.operation_id}</TableCell><TableCell>{c.outcome}</TableCell>
                    <TableCell>{c.target_status}</TableCell><TableCell>{c.latency_ms} ms</TableCell></TableRow>)}
            </TableBody></Table>
        </Stack>
    );
}
```

`apps/webapp/src/components/connectors/OpenApiView.tsx`:

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, FormControlLabel, Stack, Switch, Typography } from '@mui/material';
import { connectorsApi } from '../../api/connectors';

type Doc = { servers?: { url: string }[]; paths?: Record<string, Record<string, { summary?: string }>> };

/** Exactly the document plugins get from the gateway: what they can call, and nothing else. */
export default function OpenApiView({ connectorPid }: { connectorPid: string }) {
    const view = useQuery({ queryKey: ['connectors', connectorPid, 'view'], queryFn: () => connectorsApi.view(connectorPid) });
    const [raw, setRaw] = useState(false);
    const doc = (view.data ?? {}) as Doc;
    const entries = Object.entries(doc.paths ?? {}).flatMap(([path, item]) =>
        Object.entries(item).map(([method, op]) => ({ path, method, summary: op.summary ?? '' })));
    const text = JSON.stringify(view.data ?? {}, null, 2);
    return (
        <Stack spacing={1}>
            <Typography>Plugins call <code>{doc.servers?.[0]?.url}</code> with the connector token.</Typography>
            {entries.length === 0 && <Typography color="text.secondary">No operation is allowed yet.</Typography>}
            {entries.map((e) => <Typography key={`${e.method} ${e.path}`} data-testid="view-operation">
                {`${e.method.toUpperCase()} ${e.path} ${e.summary}`.trim()}</Typography>)}
            <Stack direction="row" spacing={2}>
                <FormControlLabel data-testid="raw-toggle" label="Raw JSON"
                    control={<Switch checked={raw} onChange={(e) => setRaw(e.target.checked)} />} />
                <Button onClick={() => navigator.clipboard?.writeText(text)}>Copy</Button>
            </Stack>
            {raw && <pre style={{ background: '#f6f7f9', padding: 12, overflow: 'auto' }}>{text}</pre>}
        </Stack>
    );
}
```

`apps/webapp/src/components/connectors/ChatPanel.tsx`:

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { connectorsApi } from '../../api/connectors';
import type { ChatMapping, Connector } from '../../models/connectors';

export default function ChatPanel({ connector, onSaved }: { connector: Connector; onSaved: () => void }) {
    const ops = useQuery({ queryKey: ['connectors', connector.pid, 'operations'], queryFn: () => connectorsApi.operations(connector.pid) });
    const [mapping, setMapping] = useState<ChatMapping>(connector.chat ?? {
        operation_id: '', input_mode: 'text', input_field: '', answer_path: '', extra_body: {} });
    const [extra, setExtra] = useState(JSON.stringify(mapping.extra_body ?? {}));
    const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
    const set = (k: keyof ChatMapping, v: string) => setMapping({ ...mapping, [k]: v });

    async function save() {
        try {
            await connectorsApi.setChat(connector.pid, { ...mapping, extra_body: JSON.parse(extra || '{}') });
            setMessage({ ok: true, text: 'Saved.' });
            onSaved();
        } catch (e) { setMessage({ ok: false, text: (e as Error).message }); }
    }

    return (
        <Stack spacing={2} sx={{ maxWidth: 560 }}>
            <Typography color="text.secondary">
                Optional. Lets plugins that only speak LLM chat (OpenAI or Ollama style) use this connector.
            </Typography>
            <TextField select label="Chat operation" value={mapping.operation_id} onChange={(e) => set('operation_id', e.target.value)}>
                {(ops.data ?? []).filter((o) => o.allowed).map((o) =>
                    <MenuItem key={o.operation_id} value={o.operation_id}>{o.method.toUpperCase()} {o.path}</MenuItem>)}
            </TextField>
            <TextField select label="The question goes in as" value={mapping.input_mode} onChange={(e) => set('input_mode', e.target.value)}>
                <MenuItem value="text">the last user message, as text</MenuItem>
                <MenuItem value="messages">the whole message list</MenuItem>
            </TextField>
            <TextField label="Field of the request body (e.g. question)" value={mapping.input_field} onChange={(e) => set('input_field', e.target.value)} />
            <TextField label="Where the answer is (JMESPath, e.g. answer)" value={mapping.answer_path} onChange={(e) => set('answer_path', e.target.value)} />
            <TextField label="Fixed extra body (JSON)" value={extra} onChange={(e) => setExtra(e.target.value)} />
            {message && <Alert severity={message.ok ? 'success' : 'error'}>{message.text}</Alert>}
            <Button variant="contained" onClick={save} sx={{ alignSelf: 'flex-start' }}>Save</Button>
        </Stack>
    );
}
```

`apps/webapp/src/components/connectors/PublishPanel.tsx`:

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import { connectorsApi } from '../../api/connectors';
import type { Connector, PublishAnswer } from '../../models/connectors';

function Line({ label, value }: { label: string; value?: string | null }) {
    if (!value) return null;
    return <Typography sx={{ wordBreak: 'break-all' }}><b>{label}:</b> <code>{value}</code></Typography>;
}

/** The token is kept in this component's state only, never in the query cache (shown once). */
export default function PublishPanel({ connector }: { connector: Connector }) {
    const publication = useQuery({ queryKey: ['connectors', connector.pid, 'publication'],
                                   queryFn: () => connectorsApi.publication(connector.pid) });
    const [fresh, setFresh] = useState<PublishAnswer | null>(null);
    const [error, setError] = useState<string | null>(null);

    async function publish() {
        setError(null);
        try { setFresh(await connectorsApi.publish(connector.pid)); publication.refetch(); }
        catch (e) { setError((e as Error).message); }
    }
    async function unpublish() {
        setError(null);
        try { await connectorsApi.unpublish(connector.pid); setFresh(null); publication.refetch(); }
        catch (e) { setError((e as Error).message); }
    }

    const p = publication.data;
    return (
        <Stack spacing={2} sx={{ maxWidth: 820 }}>
            {error && <Alert severity="error">{error}</Alert>}
            {fresh && (
                <Box data-testid="one-time-token" sx={{ border: '1px solid #f0c36d', p: 2, borderRadius: 1 }}>
                    <Typography sx={{ mb: 1 }}><b>Shown once: copy it now.</b> Plugins get it as the project secret
                        {' '}<code>{fresh.secret_key}</code>.</Typography>
                    <Line label="Token" value={fresh.token} />
                    <Line label="Ollama URL (older plugins)" value={fresh.ollama_url} />
                </Box>)}
            {p?.published ? (
                <>
                    <Line label="OpenAPI view" value={p.view_url} />
                    <Line label="OpenAI base URL" value={p.openai_base_url} />
                    <Line label="Secret key in the project" value={p.secret_key} />
                    <Button color="error" onClick={unpublish} sx={{ alignSelf: 'flex-start' }}>Unpublish</Button>
                </>
            ) : (
                <>
                    <Typography>Publishing adds this connector to the AI system, so plugins can select it.</Typography>
                    <Button variant="contained" data-testid="publish" onClick={publish} sx={{ alignSelf: 'flex-start' }}>
                        Publish to the AI system</Button>
                </>
            )}
        </Stack>
    );
}
```

In `apps/webapp/src/pages/ConnectorDetail.tsx`, import the four panels and replace the placeholder line `{tab >= 2 && ...}` with:

```tsx
            {tab === 2 && <TestPanel connectorPid={c.pid} />}
            {tab === 3 && <OpenApiView connectorPid={c.pid} />}
            {tab === 4 && <ChatPanel connector={c} onSaved={refresh} />}
            {tab === 5 && <PublishPanel connector={c} />}
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/webapp && npx vitest run src/components/connectors/ && npx tsc -b --noEmit`
Expected: all pass; no type errors.

- [ ] **Step 5: Commit**

```bash
git -C apps/webapp add src/components/connectors/TestPanel.tsx src/components/connectors/TestPanel.test.tsx src/components/connectors/OpenApiView.tsx src/components/connectors/OpenApiView.test.tsx src/components/connectors/ChatPanel.tsx src/components/connectors/PublishPanel.tsx src/components/connectors/PublishPanel.test.tsx src/pages/ConnectorDetail.tsx
git -C apps/webapp commit -m "Connector detail: test operations, the unified OpenAPI view, chat mapping, publish once"
```

---

### Task 7: Route and menu, admin only

**Files:**
- Modify: `apps/webapp/src/MyApp.tsx` (two entries in `navs`)
- Modify: `apps/webapp/src/components/LeftBar.tsx` ("Connectors" in the Project section)
- Create: `apps/webapp/src/pages/AdminOnly.tsx`
- Test: `apps/webapp/src/pages/AdminOnly.test.tsx`

**Interfaces:**
- Produces: `AdminOnly({children})` rendering `children` for admins, otherwise a notice `data-testid="admins-only"` (children not mounted, so no calls are made). Routes `/projects/:project_name/connectors` -> `<ProjectContextWrapper><AdminOnly><ConnectorsPage/></AdminOnly></ProjectContextWrapper>` and `/projects/:project_name/connectors/:connector_pid` -> the same with `ConnectorDetailPage`.

- [ ] **Step 1: Write the failing test**

`apps/webapp/src/pages/AdminOnly.test.tsx`:

```tsx
// @vitest-environment jsdom
import { it, expect, vi } from 'vitest';
import { render } from '../components/connectors/testUtils';

vi.mock('../auth/useIsAdmin', () => ({ useIsAdmin: vi.fn() }));
import { useIsAdmin } from '../auth/useIsAdmin';
import AdminOnly from './AdminOnly';

it('a non-admin sees a notice and no calls are made', () => {
    (useIsAdmin as unknown as ReturnType<typeof vi.fn>).mockReturnValue(false);
    const child = vi.fn(() => <span>secret page</span>);
    const Child = () => child();
    const { container } = render(<AdminOnly><Child /></AdminOnly>);
    expect(container.querySelector('[data-testid="admins-only"]')).not.toBeNull();
    expect(child).not.toHaveBeenCalled();
});

it('an admin sees the page', () => {
    (useIsAdmin as unknown as ReturnType<typeof vi.fn>).mockReturnValue(true);
    const { container } = render(<AdminOnly><span>page</span></AdminOnly>);
    expect(container.textContent).toBe('page');
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/webapp && npx vitest run src/pages/AdminOnly.test.tsx`
Expected: FAIL, `Failed to resolve import "./AdminOnly"`.

- [ ] **Step 3: Implement**

`apps/webapp/src/pages/AdminOnly.tsx`:

```tsx
import type { ReactNode } from 'react';
import { Alert, Box } from '@mui/material';
import { useIsAdmin } from '../auth/useIsAdmin';

/** Hides what the server would refuse anyway; the connectors service is the one that enforces it. */
export default function AdminOnly({ children }: { children: ReactNode }) {
    if (!useIsAdmin()) {
        return <Box sx={{ p: 3 }}><Alert severity="info" data-testid="admins-only">Connectors are managed by platform admins.</Alert></Box>;
    }
    return <>{children}</>;
}
```

In `apps/webapp/src/MyApp.tsx`, import `ConnectorsPage from './pages/Connectors'`, `ConnectorDetailPage from './pages/ConnectorDetail'`, `AdminOnly from './pages/AdminOnly'`, and append to the `navs` array:

```tsx
        { id: 12, name: 'Connectors', path: '/projects/:project_name/connectors', element: <ProjectContextWrapper><AdminOnly><ConnectorsPage /></AdminOnly></ProjectContextWrapper> },
        { id: 13, name: 'Connector', path: '/projects/:project_name/connectors/:connector_pid', element: <ProjectContextWrapper><AdminOnly><ConnectorDetailPage /></AdminOnly></ProjectContextWrapper> },
```

In `apps/webapp/src/components/LeftBar.tsx`, import `CableIcon from '@mui/icons-material/Cable'` and `{ useIsAdmin } from '../auth/useIsAdmin'`; inside the component body call `const isAdmin = useIsAdmin();`; change the Project section's `items` to:

```tsx
                        items={[
                            { text: 'Overview', icon: <DashboardIcon />, target: `/projects/${projectName}/overview` },
                            { text: 'Settings', icon: <SettingsIcon />, target: `/projects/${projectName}/settings` },
                            ...(isAdmin ? [{ text: 'Connectors', icon: <CableIcon />, target: `/projects/${projectName}/connectors` }] : []),
                        ]}
```

- [ ] **Step 4: Run the webapp checks**

Run: `cd apps/webapp && npx vitest run && npx tsc -b --noEmit && npx eslint src/pages src/components/connectors src/api/connectors.ts src/auth src/MyApp.tsx src/components/LeftBar.tsx`
Expected: every test passes, no type or lint errors.

Then prove the frozen webapp files did not move:

Run: `cd ~/aisc-install && GUARD_SOURCE=worktree scripts/guard-frozen.sh --only G4`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C apps/webapp add src/pages/AdminOnly.tsx src/pages/AdminOnly.test.tsx src/MyApp.tsx src/components/LeftBar.tsx
git -C apps/webapp commit -m "Connectors in the project menu and routes, for admins only"
```

---

### Task 8: Acceptance: MCAS-lite, SOAP and GraphQL through the unified view, called by a real plugin

**Files:**
- Modify: `apps/connectors/pyproject.toml` (dev dependencies and a `path` source for the plugin interface)
- Create: `apps/connectors/tests/acceptance/__init__.py`, `conftest.py`, `stub_engine.py`, `stub_graphql.py`, `connector_probe/__init__.py`, `test_acceptance.py`

**Interfaces:**
- Consumes: everything in plan 1 and Task 1; `apps/eval/aisc_eval/plugin_runtime.py` (read-only, frozen); `shared/plugin-interface` (read-only, frozen); MCAS-lite at `http://localhost:8500` (running; its `/chat` uses its own LLM backend).
- Produces: `uv run pytest tests/acceptance -v` runs the spec's acceptance items 1 to 5 against a real uvicorn process; the module is skipped when MCAS-lite does not answer `/health`.

- [ ] **Step 1: Add the acceptance dependencies**

In `apps/connectors/pyproject.toml`, extend the dev group and add a source for the plugin interface (read only, installed from its folder):

```toml
[dependency-groups]
dev = ["pytest>=8.0", "respx>=0.21", "ollama>=0.4", "openai>=1.40", "aisc-plugin-interface"]

[tool.uv.sources]
aisc-plugin-interface = { path = "../../shared/plugin-interface" }
```

Run: `cd apps/connectors && uv sync`
Expected: resolves and installs `ollama`, `openai`, `aisc-plugin-interface`.

- [ ] **Step 2: Write the stubs and the probe plugin**

`apps/connectors/tests/acceptance/__init__.py`: empty.

`apps/connectors/tests/acceptance/stub_engine.py`:

```python
"""The engine API, as the connectors service uses it, kept in memory (the real engine is frozen)."""
import uuid

from fastapi import FastAPI

PROJECT = uuid.UUID("11111111-1111-1111-1111-111111111111")
SYSTEM = uuid.UUID("22222222-2222-2222-2222-222222222222")
state = {"components": {}, "secrets": {}}
app = FastAPI()


@app.get("/api/v1/projects/{pid}/aisystem")
def aisystem(pid: uuid.UUID):
    return {"pid": str(SYSTEM), "name": "MCAS-lite",
            "components": [{"pid": k, **v} for k, v in state["components"].items()]}


@app.post("/api/v1/project/settings/{pid}")
def create_secret(pid: uuid.UUID, body: dict):
    key = str(uuid.uuid4())
    state["secrets"][key] = body
    return {"pid": key, "key": body["key"], "name": body["name"], "masked_value": "****", "json_value": {},
            "category": "secrets"}


@app.delete("/api/v1/project/settings/{pid}/{cfg}", status_code=204)
def delete_secret(pid: uuid.UUID, cfg: str):
    state["secrets"].pop(cfg, None)


@app.post("/api/v1/projects/{pid}/components")
def create_component(pid: uuid.UUID, body: dict):
    key = str(uuid.uuid4())
    state["components"][key] = {"name": body["name"], "component_type": body["component_type"],
                                "json_value": body["json_value"]}
    return {"pid": key, **state["components"][key]}


@app.delete("/api/v1/components/{cid}", status_code=204)
def delete_component(cid: str):
    state["components"].pop(cid, None)
```

`apps/connectors/tests/acceptance/stub_graphql.py`:

```python
"""A tiny GraphQL service for acceptance: the same schema as the unit tests, with resolvers."""
from fastapi import FastAPI
from graphql import build_schema, graphql_sync

from tests.test_import_graphql import SDL

schema = build_schema(SDL)
root = {
    "health": lambda info: "ok",
    "applicant": lambda info, id: {"id": id, "name": "A. Applicant", "decisions": []},
    "score": lambda info, amount, market=None: {"recommendation": "Approve" if amount <= 5000 else "Reject",
                                                "score": 900 if amount <= 5000 else 100},
}
app = FastAPI()


@app.post("/graphql")
def endpoint(body: dict):
    result = graphql_sync(schema, body["query"], root_value=root, variable_values=body.get("variables"),
                          operation_name=body.get("operationName"))
    out = {"data": result.data}
    if result.errors:
        out["errors"] = [{"message": e.message} for e in result.errors]
    return out
```

`apps/connectors/tests/acceptance/connector_probe/__init__.py`:

```python
"""A real AISC plugin: it gets the connector as a resource input and its token as a project secret,
reads the unified OpenAPI view and calls one operation through it. It knows nothing about the target."""
import httpx
from pydantic import BaseModel

from aisc_plugin_interface import (BaseEvaluationPlugin, ConfigCategory, InputType, Measure, evaluation_input,
                                   metric, project_config)


class ProbeConfig(BaseModel):
    path: str = "/chat"
    body: dict = {"question": "Can I ask a person to review a rejected application?"}


@project_config(key="connector_token", name="Connector token", category=ConfigCategory.SECRETS)
@evaluation_input(name="target", label="Target", input_type=InputType.RESOURCE)
class ConnectorProbe(BaseEvaluationPlugin[ProbeConfig]):
    plugin_name = "Connector probe"

    def evaluate(self, config_data):
        config = self.validate_config_form_data(config_data)
        view_url = self.get_resource_config("target").value
        headers = {"Authorization": f"Bearer {self.require_secret('connector_token')}"}
        view = httpx.get(view_url, headers=headers, timeout=30).json()
        answer = httpx.post(view["servers"][0]["url"] + config.path, headers=headers, json=config.body, timeout=120)
        return {"paths": sorted(view["paths"]), "status": answer.status_code, "answer": answer.json()}

    @metric("Answered through the connector")
    def answered(self, output):
        return [Measure(name="Answered through the connector", score=1.0 if output["status"] == 200 else 0.0,
                        description=",".join(output["paths"])[:250])]
```

- [ ] **Step 3: Write the fixtures**

`apps/connectors/tests/acceptance/conftest.py`:

```python
"""A real connectors process (uvicorn) on a throwaway database, plus stubs for everything that is
not the system under test. Nothing here touches the running aisc stack."""
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest
import uvicorn

ROOT = pathlib.Path(__file__).resolve().parents[4]
MCAS = os.environ.get("ACCEPTANCE_MCAS_URL", "http://localhost:8500")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app) -> str:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=0.2)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}"


def pytest_collection_modifyitems(config, items):
    try:
        up = httpx.get(f"{MCAS}/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        up = False
    if not up:
        for item in items:
            item.add_marker(pytest.mark.skip(reason=f"MCAS-lite is not answering at {MCAS}"))


@pytest.fixture(scope="session")
def engine_url():
    from tests.acceptance.stub_engine import app

    return _serve(app)


@pytest.fixture(scope="session")
def graphql_url():
    from tests.acceptance.stub_graphql import app

    return _serve(app) + "/graphql"


@pytest.fixture(scope="session")
def service(database_url, engine_url):
    from cryptography.fernet import Fernet

    port = _free_port()
    env = {**os.environ, "CONNECTORS_DATABASE_URL": database_url, "CONNECTOR_SECRETS_KEY": Fernet.generate_key().decode(),
           "ENGINE_API_URL": engine_url + "/api/v1", "GATEWAY_BASE_URL": f"http://127.0.0.1:{port}",
           "AUTH_ENABLED": "false", "AUTH_DEV_ROLES": "admin",
           "PYTHONPATH": f"{ROOT / 'apps' / 'connectors'}:{ROOT / 'shared' / 'identity'}"}
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "aisc_connectors.app:app", "--host", "127.0.0.1",
                                "--port", str(port), "--no-access-log"], env=env, cwd=ROOT / "apps" / "connectors")
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield base
    process.terminate()
    process.wait(10)
```

- [ ] **Step 4: Write the acceptance test**

`apps/connectors/tests/acceptance/test_acceptance.py`:

```python
"""Spec acceptance 1 to 5, end to end. Items 6 and 7 are Task 9's guard run and the unit tests."""
import json
import pathlib
import subprocess
import sys

import httpx
import pytest

from tests import stub_soap
from tests.acceptance.conftest import MCAS, ROOT
from tests.acceptance.stub_engine import PROJECT

API = "/api/v1/connectors"
FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def admin(service):
    return httpx.Client(base_url=service, timeout=120)


def new_connector(client, name, kind, **payload):
    cid = client.post(API, json={"project_pid": str(PROJECT), "name": name}).json()["pid"]
    imported = client.post(f"{API}/{cid}/import", json={"kind": kind, **payload})
    assert imported.status_code == 200, imported.text
    return cid, {o["path"]: o for o in imported.json()["operations"]}


def allow(client, cid, op):
    answer = client.patch(f"{API}/{cid}/operations/{op['operation_id']}",
                          json={"allowed": True, "confirm_changes_data": True})
    assert answer.status_code == 200, answer.text


@pytest.fixture(scope="module")
def mcas(service):
    client = admin(service)
    cid, ops = new_connector(client, "MCAS lite", "openapi", url=f"{MCAS}/openapi.json")
    for path in ("/score", "/explain", "/chat"):
        allow(client, cid, ops[path])
    client.patch(f"{API}/{cid}", json={"settings": {"ollama_facade": True, "timeout_s": 120}})
    client.put(f"{API}/{cid}/chat", json={"operation_id": ops["/chat"]["operation_id"], "input_mode": "text",
                                          "input_field": "question", "answer_path": "answer"})
    published = client.post(f"{API}/{cid}/publish").json()
    return client, cid, ops, published


def test_1_mcas_is_connected_and_only_allowed_operations_are_in_the_view(mcas):
    client, cid, ops, published = mcas
    assert len(ops) == 10
    view = httpx.get(published["view_url"], headers={"Authorization": f"Bearer {published['token']}"}).json()
    assert set(view["paths"]) == {"/score", "/explain", "/chat"}
    for denied in ("/halt", "/resume", "/override"):
        answer = httpx.post(view["servers"][0]["url"] + denied, json={},
                            headers={"Authorization": f"Bearer {published['token']}"})
        assert answer.status_code == 403 and answer.json()["error"]["kind"] == "not_allowed"


def test_2_test_shows_mcas_answer_and_names_failures(mcas, service):
    client, cid, ops, _ = mcas
    shown = client.post(f"{API}/{cid}/operations/{ops['/chat']['operation_id']}/test",
                        json={"body": {"question": "Can I ask a person to review a rejected application?"},
                              "confirm_changes_data": True}).json()
    assert shown["outcome"] == "ok", shown
    assert "POL-" in shown["body_json"]["answer"]
    dead, dead_ops = new_connector(client, "Nowhere", "manual", method="GET", url="http://127.0.0.1:9/x",
                                   operation_id="x")
    assert client.post(f"{API}/{dead}/operations/x/test", json={}).json()["outcome"] == "connection"


def test_3_a_real_plugin_process_uses_the_connector(mcas, tmp_path):
    _, cid, _, published = mcas
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "input" / "target.json").write_text(json.dumps({"value": published["view_url"]}))
    (tmp_path / "config.json").write_text(json.dumps({
        "plugin_source": "connector_probe:ConnectorProbe", "input_mapping": {"target": "target.json"},
        "project_settings": {}, "plugin_config": {}}))
    env = {"PATH": "/usr/bin:/bin", "AISC_SECRET_CONNECTOR_TOKEN": published["token"],
           "PYTHONPATH": str(pathlib.Path(__file__).parent)}
    run = subprocess.run([sys.executable, str(ROOT / "apps" / "eval" / "aisc_eval" / "plugin_runtime.py")],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr
    (measure,) = json.loads((tmp_path / "output" / "measures.json").read_text())
    assert measure["score"] == 1.0
    assert "/chat" in measure["description"]


def test_4_ollama_and_openai_clients_get_mcas_answers(mcas):
    import ollama
    import openai

    _, cid, _, published = mcas
    question = [{"role": "user", "content": "Can I ask a person to review a rejected application?"}]
    via_ollama = ollama.Client(host=published["ollama_url"]).chat(model="mcas", messages=question)
    assert "POL-" in via_ollama.message.content
    via_openai = openai.OpenAI(base_url=published["openai_base_url"], api_key=published["token"]) \
        .chat.completions.create(model="mcas", messages=question)
    assert "POL-" in via_openai.choices[0].message.content


def test_5_soap_and_graphql_targets_through_the_same_gateway(service, graphql_url):
    client = admin(service)
    soap_url, soap_server = stub_soap.start()
    try:
        cid, ops = new_connector(client, "Calculator", "wsdl", text=(FIXTURES / "calc.wsdl").read_text())
        # the WSDL names soap.test:8080; point the connector at the local stub
        assert client.put(f"{API}/{cid}/server", json={"url": soap_url}).status_code == 200
        allow(client, cid, ops["/soap/Add"])
        published = client.post(f"{API}/{cid}/publish").json()
        headers = {"Authorization": f"Bearer {published['token']}"}
        view = httpx.get(published["view_url"], headers=headers).json()
        answer = httpx.post(view["servers"][0]["url"] + "/soap/Add", json={"a": 2, "b": 3}, headers=headers)
        assert answer.json() == {"result": 5}
    finally:
        soap_server.shutdown()
    gql, gql_ops = new_connector(client, "Scoring GraphQL", "graphql", url=graphql_url)
    allow(client, gql, gql_ops["/graphql/score"])
    published = client.post(f"{API}/{gql}/publish").json()
    headers = {"Authorization": f"Bearer {published['token']}"}
    view = httpx.get(published["view_url"], headers=headers).json()
    answer = httpx.post(view["servers"][0]["url"] + "/graphql/score", json={"amount": 2500}, headers=headers)
    assert answer.json() == {"recommendation": "Approve", "score": 900}
```

- [ ] **Step 5: Run the acceptance run**

Run: `cd apps/connectors && uv run pytest tests/acceptance -v`

Expected: 5 passed (MCAS-lite's `/chat` answers through its LLM backend, so allow a minute). If MCAS-lite is not running, the acceptance module reports 5 skipped with the reason.

- [ ] **Step 6: Commit**

```bash
git add apps/connectors/pyproject.toml apps/connectors/uv.lock apps/connectors/tests/acceptance
git commit -m "Connectors acceptance: MCAS-lite, SOAP and GraphQL through the unified view, called by a real plugin process"
```

---

### Task 9: Freeze check, documentation, and the stop before the live stack

**Files:**
- Modify: `apps/connectors/README.md` (how to connect a system, for admins)
- Create: `docs/superpowers/specs/2026-09-24-connectors-rollout.md` (the commands the user may choose to run)

- [ ] **Step 1: Run the full freeze guard**

Run: `cd ~/aisc-install && scripts/guard-frozen.sh`
Expected: exit 0, G1 to G5 PASS (committed trees).

- [ ] **Step 2: Run every suite this work touches**

Run:

```bash
cd ~/aisc-install/apps/connectors && uv run pytest -q
cd ~/aisc-install/apps/webapp && npx vitest run && npx tsc -b --noEmit
```

Expected: all green. Paste the summary lines into the final report.

- [ ] **Step 3: Write the admin how-to**

Append to `apps/connectors/README.md`:

```markdown
## Connecting a system (admins)

1. Project menu, Connectors, New connector. Pick how the system describes itself: an OpenAPI or
   Swagger spec (most REST APIs), a cURL command, a Postman collection, a WSDL (SOAP), a GraphQL
   endpoint, an LLM API (OpenAI-compatible, Ollama, Hugging Face), or describe one call by hand.
2. Credentials: choose the scheme and type the secret. It is stored encrypted and never shown again.
3. Operations: nothing is callable until you allow it. Operations that may change data, and every
   operation of a production connector, ask for a confirmation.
4. Test: run an operation and read the outcome (ok, auth, timeout, ...).
5. OpenAPI view: exactly what plugins will see and call.
6. Publish: adds the connector to the AI system (a resource component, a project secret with the
   token, and an llm component when a chat operation is set). The token is shown once.

The first connector of a project is its target access; keep at least one.
```

- [ ] **Step 4: Write the rollout note, then STOP**

`docs/superpowers/specs/2026-09-24-connectors-rollout.md`:

```markdown
# Connectors: rolling out on the running stack (needs the user's go-ahead)

Nothing below has been run. The running compose project `aisc` was built on 2026-09-21 and does not
contain feat/unified-modules; the connectors page also needs the webapp rebuilt from this branch.

1. `scripts/secrets.sh` (adds CONNECTOR_SECRETS_KEY and CONNECTOR_DB_PASSWORD to env.secrets).
2. `docker compose -p aisc --env-file env.runtime -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d postgres-setup`
   (creates role connector_rw and schema connector on the existing volume; idempotent).
3. `docker compose -p aisc ... build connectors aisc-webapp && docker compose -p aisc ... up -d connectors aisc-webapp caddy`.
4. Check: `docker exec connectors python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8097/health').read())"`.

Rollback: `docker compose -p aisc ... stop connectors`; the schema can stay (nothing else reads it).
```

Then report to the user: what was built, the test and guard summaries, and ask whether to run the rollout note (it rebuilds images of the live stack, which the rules reserve for them). Do not run it.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors/README.md docs/superpowers/specs/2026-09-24-connectors-rollout.md
git commit -m "Connectors: admin how-to and the rollout note for the live stack"
```

---

## Self-review notes (for the reviewer of this plan)

- Spec coverage: "The page" (Tasks 3 to 7), D1 wiring and D7 Caddy/admin (Task 2), acceptance 1 to 5 (Task 8), 6 (Tasks 7, 9), 7 (plan 1 Task 5 tests, Task 7 here), rollout gate (Task 9).
- The dev-mode caveat: with `vite dev` and `VITE_API_URL=http://localhost:8000` (the backend directly), connector calls reach the backend and 404. Run the dev server with `VITE_API_URL` pointing at Caddy (`http://localhost`) to use the page in development.
