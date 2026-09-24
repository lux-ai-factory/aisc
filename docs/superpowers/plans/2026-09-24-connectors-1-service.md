# Connectors, plan 1 of 2: the connectors service

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new Python service, `apps/connectors`, that stores admin-defined connectors to company systems, imports every supported technology into one canonical OpenAPI document, executes allowed operations securely, and serves the unified OpenAPI view plus gateway that plugins call.

**Architecture:** FastAPI + psycopg 3 on a new `connector` schema in the shared `platform` database (role `connector_rw`). Admin routes under `/api/v1/connectors` require the realm role `admin` (`shared/identity`). Plugin routes under `/gw` require a connector access token. Importers turn OpenAPI 3.x, Swagger 2, cURL, Postman, manual input, WSDL, GraphQL and presets into a canonical OpenAPI 3.1 document whose operations carry an `x-aisc-binding`; one executor runs those bindings (HTTP, SOAP, GraphQL, with session / async / stream patterns). The engine is only ever called over its public API with the admin's own token.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, psycopg[binary,pool] 3, httpx, cryptography (Fernet), jmespath, PyYAML, openapi-spec-validator, zeep, graphql-core, PyJWT; tests with pytest, respx, a throwaway `postgres:14-alpine` container.

**Spec:** `docs/superpowers/specs/2026-09-24-connectors-design.md`

## Global Constraints

- Branch `feat/unified-modules` in every repo. Local commits only; NEVER push.
- NEVER run `docker compose` against the running stack (compose project `aisc`); never migrate, write to or drop anything in its live databases. `docker run --rm` throwaway containers are fine.
- Frozen, must stay byte-identical: the engine data model (apps/backend models, schema `engine`, including its GRANTs), Sean's files of 2026-09-23 in apps/backend, apps/webapp, apps/eval, shared/plugin-interface, the vendored AIRO/VAIR files, qualification `knowledge_graph` and `QualificationRisk`. Do not edit shared/plugin-manager.
- No grant, foreign key or trigger on any `engine.*` object. Engine rows are referenced by pid and checked through the engine API.
- TDD: every task writes its failing test first.
- Prose in docs and comments: no em dashes.
- Business logic in Python; the webapp (plan 2) only renders what the service prepares.
- Service port 8097, compose hostname `connectors`, schema `connector`, role `connector_rw`, key env `CONNECTOR_SECRETS_KEY` (comma-separated Fernet keys, newest first).
- Admin API prefix `/api/v1/connectors`; gateway prefix `/gw/{connector_pid}`; reserved gateway sub-paths: `openapi.json`, `openai/`, `k/`.
- Secrets never appear in any API response, log line, error message or unified view.
- Run tests from `apps/connectors` with `uv run pytest`.

## Review Focus

1. A real-world spec that is slightly invalid (missing `operationId`, a validator complaint, a relative server URL) must still import, with the problems listed as warnings, and synthesized operation ids must be stable across re-imports so allow decisions survive. (Task 6, `test_invalid_but_usable_spec_imports_with_warnings`, `test_synthesized_ids_are_stable`.)
2. Literal path segments must win over templated ones (`/users/me` before `/users/{id}`), or a plugin silently calls the wrong operation. (Task 17, `test_literal_path_beats_template`.)
3. A target that answers with a large or binary body (a PDF, an image) must pass through untouched up to the size cap and fail with `bad_mapping`-free, clear `target_too_large` above it, never by loading everything into memory. (Task 13, `test_binary_body_passes_through`, `test_oversized_response_is_refused`.)
4. A target that answers an error with HTML or plain text must not crash Test or the gateway; the admin sees the status and a text excerpt. (Task 16, `test_html_error_page_is_shown_as_text`.)
5. Sessions are keyed by connector and session key: two connectors with the same `X-AISC-Session` value must not share a conversation id, and an expired session starts a new one. (Task 14, `test_sessions_are_isolated_per_connector`, `test_expired_session_starts_fresh`.)

---

## File structure

```
apps/connectors/
  pyproject.toml                  dependencies, pytest config (pythonpath includes shared/identity)
  Dockerfile                      python:3.12-slim + uv, uvicorn on 8097
  README.md                       what the service is, how to run its tests
  aisc_connectors/
    __init__.py
    settings.py                   env-driven settings
    app.py                        FastAPI app, includes the routers
    db.py                         pool + migration runner
    migrations/0001_connectors.sql
    store.py                      SQL for connectors, policies, tokens, publications, call log
    vault.py                      encrypted, write-only secrets
    auth.py                       admin dependency (+ the admin's token for the engine)
    engine.py                     engine API client
    slug.py                       names -> slugs and secret keys
    model.py                      canonical document: operations, matching
    importers/
      __init__.py                 import_source(kind, payload) dispatcher
      errors.py                   ImportFailed
      fetch.py                    bounded, guarded download of a spec
      openapi.py                  OpenAPI 3.x normalisation
      swagger2.py                 Swagger 2.0 -> OpenAPI 3.1
      build.py                    one-operation document builder (cURL, Postman, manual)
      curl.py
      postman.py
      manual.py
      presets.py                  OpenAI-compatible, Ollama, Hugging Face
      wsdl.py
      graphql.py
    executor/
      __init__.py                 run(): policy, rate limit, dispatch, patterns, call log
      errors.py                   GatewayFailure, outcome kinds
      guard.py                    outbound host checks, rate limiter
      auth.py                     auth appliers (httpx and requests), OAuth2 token cache
      http.py                     REST execution
      patterns.py                 session, async polling, stream collection
      soap.py
      graphql.py
    tokens.py                     gateway access tokens
    view.py                       unified OpenAPI view
    routes_admin.py               /api/v1/connectors
    routes_gateway.py             /gw
    facades.py                    OpenAI and Ollama facades
    publish.py                    publish/unpublish to the engine
  tests/
    conftest.py                   throwaway Postgres, keys, tokens, clients
    fixtures/mcas_openapi.json    MCAS-lite's real spec
    fixtures/calc.wsdl            a small SOAP service
    fixtures/petstore_swagger2.json
    fixtures/postman_collection.json
    stub_soap.py                  a tiny threaded SOAP server for tests
    test_*.py                     one file per module
init/connectors-db.sql            role + schema (superuser, idempotent)
```

---

### Task 1: Service scaffold with a health route

**Files:**
- Create: `apps/connectors/pyproject.toml`
- Create: `apps/connectors/aisc_connectors/__init__.py`, `settings.py`, `app.py`
- Create: `apps/connectors/Dockerfile`, `apps/connectors/README.md`
- Test: `apps/connectors/tests/test_health.py`

**Interfaces:**
- Produces: `aisc_connectors.settings.settings() -> Settings` with fields `database_url: str`, `secrets_key: str`, `engine_api_url: str`, `gateway_base_url: str`, `max_response_bytes: int`, `max_spec_bytes: int`; `aisc_connectors.app.app: FastAPI`.

- [ ] **Step 1: Write the project file**

`apps/connectors/pyproject.toml`:

```toml
[project]
name = "aisc-connectors"
version = "0.1.0"
description = "Connectors: reach any assessed system through one OpenAPI view."
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "psycopg[binary,pool]>=3.2",
    "httpx>=0.27",
    "cryptography>=43",
    "jmespath>=1.0",
    "pyyaml>=6.0",
    "openapi-spec-validator>=0.7",
    "zeep>=4.2",
    "graphql-core>=3.2",
    # aisc_identity is mounted from shared/; its one dependency is installed here
    "pyjwt[crypto]>=2.8",
]

[dependency-groups]
dev = ["pytest>=8.0", "respx>=0.21"]

[tool.pytest.ini_options]
# aisc_identity is shared by every Python service, mounted from shared/ (as report-composer)
pythonpath = [".", "../../shared/identity"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

`apps/connectors/tests/test_health.py`:

```python
from fastapi.testclient import TestClient


def test_health_answers_without_a_token():
    from aisc_connectors.app import app

    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_have_safe_defaults(monkeypatch):
    for name in ("CONNECTORS_DATABASE_URL", "CONNECTOR_SECRETS_KEY", "ENGINE_API_URL", "GATEWAY_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    from aisc_connectors.settings import settings

    s = settings()
    assert s.engine_api_url == "http://aisc-backend:8000/api/v1"
    assert s.gateway_base_url == "http://connectors:8097"
    assert s.secrets_key == ""
    assert s.max_response_bytes == 20 * 1024 * 1024
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd apps/connectors && uv sync && uv run pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors'`.

- [ ] **Step 4: Implement**

`apps/connectors/aisc_connectors/__init__.py`: empty file.

`apps/connectors/aisc_connectors/settings.py`:

```python
"""Everything the service reads from its environment, read in one place."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    #: Comma-separated Fernet keys, newest first. Only this service holds them.
    secrets_key: str
    #: The engine's public API, called with the admin's own token.
    engine_api_url: str
    #: How plugins on the backend network reach this service.
    gateway_base_url: str
    max_response_bytes: int
    max_spec_bytes: int


def settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "CONNECTORS_DATABASE_URL", "postgresql://connector_rw:connector_rw@postgres:5432/platform"
        ),
        secrets_key=os.environ.get("CONNECTOR_SECRETS_KEY", ""),
        engine_api_url=os.environ.get("ENGINE_API_URL", "http://aisc-backend:8000/api/v1").rstrip("/"),
        gateway_base_url=os.environ.get("GATEWAY_BASE_URL", "http://connectors:8097").rstrip("/"),
        max_response_bytes=int(os.environ.get("CONNECTORS_MAX_RESPONSE_BYTES", str(20 * 1024 * 1024))),
        max_spec_bytes=int(os.environ.get("CONNECTORS_MAX_SPEC_BYTES", str(5 * 1024 * 1024))),
    )
```

`apps/connectors/aisc_connectors/app.py`:

```python
"""The connectors service: admin routes, the gateway plugins call, and a health check."""
from fastapi import FastAPI

app = FastAPI(title="AISC connectors")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

`apps/connectors/Dockerfile`:

```dockerfile
# The connectors service. shared/identity is mounted at /app/shared/identity by docker compose.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY aisc_connectors ./aisc_connectors
ENV PYTHONPATH=/app:/app/shared/identity PATH=/app/.venv/bin:$PATH
EXPOSE 8097
CMD ["uvicorn", "aisc_connectors.app:app", "--host", "0.0.0.0", "--port", "8097"]
```

`apps/connectors/README.md`:

```markdown
# Connectors

Admin-defined connections to the systems AISC assesses. Every technology (OpenAPI, Swagger 2,
cURL, Postman, SOAP, GraphQL, OpenAI-compatible, Ollama, Hugging Face) is imported into one
OpenAPI document; plugins call the unified OpenAPI view at `/gw/<connector>/openapi.json`.
Design: `docs/superpowers/specs/2026-09-24-connectors-design.md`.

Tests: `uv run pytest`. They start a throwaway `postgres:14-alpine` with `docker run --rm`
unless `CONNECTORS_TEST_DATABASE_URL` points at one (never the live database).
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_health.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd apps/connectors && uv lock && cd ../..
git add apps/connectors
git commit -m "Connectors service: scaffold, settings and health"
```

---

### Task 2: Schema, role and migrations on a throwaway database

**Files:**
- Create: `init/connectors-db.sql`
- Create: `apps/connectors/aisc_connectors/db.py`, `apps/connectors/aisc_connectors/migrations/0001_connectors.sql`
- Create: `apps/connectors/tests/conftest.py`
- Test: `apps/connectors/tests/test_db.py`

**Interfaces:**
- Produces: `db.migrate(dsn: str) -> list[str]` (names applied), `db.pool() -> ConnectionPool` (dict rows, migrates on first use), `db.reset_pool() -> None`; pytest fixtures `database_url` (session), `db` (a pool on a clean schema), `secrets_key`.

- [ ] **Step 1: Write the role and schema script**

`init/connectors-db.sql`:

```sql
-- The connectors service's role and schema (spec 2026-09-24-connectors-design.md, D1).
-- Superuser. Runs on a fresh volume from docker-entrypoint-initdb.d (80-connectors-db.sql) and on
-- every start from postgres-setup, which passes the password as a psql variable. Idempotent.
-- Deliberately no grant on schema engine: the freeze guard (G1) dumps engine's GRANTs too.
\if :{?connector_password}
\else
\set connector_password connector_rw
\endif

SELECT 'CREATE ROLE connector_rw LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'connector_rw') \gexec
SELECT format('ALTER ROLE connector_rw WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'connector_password') \gexec

GRANT CONNECT ON DATABASE platform TO connector_rw;
\connect platform
CREATE SCHEMA IF NOT EXISTS connector AUTHORIZATION connector_rw;
ALTER ROLE connector_rw IN DATABASE platform SET search_path = connector;
```

- [ ] **Step 2: Write the test fixtures**

Create an empty `apps/connectors/tests/__init__.py` (later tests import helpers from sibling test modules, e.g. `from tests.test_admin_connectors import FakeEngine`).

`apps/connectors/tests/conftest.py`:

```python
"""A throwaway Postgres, a secrets key, tokens and clients, for the tests that need them.

The database is a `docker run --rm` container on a port the kernel picks, removed at the end.
It is never the live stack: a CONNECTORS_TEST_DATABASE_URL on port 5432 is refused.
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import time
import uuid

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
ISSUER = "http://keycloak:8080/realms/aisc"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def database_url():
    given = os.environ.get("CONNECTORS_TEST_DATABASE_URL")
    if given:
        assert ":5432/" not in given, "refusing a database on the live port 5432"
        yield given
        return
    name = f"connectors-test-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    subprocess.run(
        ["docker", "run", "--rm", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=pw",
         "-e", "POSTGRES_DB=platform", "-p", f"127.0.0.1:{port}:5432", "postgres:14-alpine"],
        check=True, capture_output=True,
    )
    try:
        superuser = f"postgresql://postgres:pw@127.0.0.1:{port}/platform"
        for _ in range(120):
            try:
                psycopg.connect(superuser, connect_timeout=1).close()
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        time.sleep(1)  # the image restarts once after initdb
        for _ in range(60):
            try:
                psycopg.connect(superuser, connect_timeout=1).close()
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        subprocess.run(
            ["docker", "exec", "-i", name, "psql", "-U", "postgres", "-d", "platform", "-v", "ON_ERROR_STOP=1"],
            input=(ROOT / "init" / "connectors-db.sql").read_bytes(), check=True, capture_output=True,
        )
        yield f"postgresql://connector_rw:connector_rw@127.0.0.1:{port}/platform"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def secrets_key(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", key)
    return key


@pytest.fixture
def db(database_url, monkeypatch, secrets_key):
    monkeypatch.setenv("CONNECTORS_DATABASE_URL", database_url)
    from aisc_connectors import db as dbm

    dbm.reset_pool()
    pool = dbm.pool()
    yield pool
    with pool.connection() as conn:
        conn.execute("TRUNCATE connector.connector, connector.call_log CASCADE")
    dbm.reset_pool()


@pytest.fixture(scope="session")
def rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def as_user(rsa_key):
    """Headers for a caller, signed with the test key."""
    import jwt

    def make(subject="alice", roles=("admin",)):
        token = jwt.encode(
            {"sub": subject, "email": f"{subject}@localhost", "preferred_username": subject,
             "iss": ISSUER, "exp": int(time.time()) + 300, "realm_access": {"roles": list(roles)}},
            rsa_key, algorithm="RS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def auth_on(monkeypatch, rsa_key):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.setattr("aisc_identity.service.key_for_jwks", lambda url: (lambda _t: rsa_key.public_key()))
```

- [ ] **Step 3: Write the failing test**

`apps/connectors/tests/test_db.py`:

```python
import uuid

import psycopg
import pytest


def test_migrations_create_the_tables(db):
    with db.connection() as conn:
        names = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'connector'"
        )}
    assert {"connector", "secret", "operation_policy", "access_token", "publication",
            "call_log", "schema_migration"} <= names


def test_migrate_is_idempotent(database_url, db):
    from aisc_connectors import db as dbm

    assert dbm.migrate(database_url) == []


def test_one_target_access_connector_per_project(db):
    project = uuid.uuid4()
    insert = ("INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind,"
              " environment, is_target_access, created_by) VALUES (%s, %s, %s, %s, %s, 'manual',"
              " 'sandbox', true, 'test')")
    with db.connection() as conn:
        conn.execute(insert, (uuid.uuid4(), project, uuid.uuid4(), "A", "a"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.connection() as conn:
            conn.execute(insert, (uuid.uuid4(), project, uuid.uuid4(), "B", "b"))

```

- [ ] **Step 4: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'db' from 'aisc_connectors'`.

- [ ] **Step 5: Implement the migration and runner**

`apps/connectors/aisc_connectors/migrations/0001_connectors.sql`:

```sql
-- Connectors (spec 2026-09-24). project_pid, ai_system_pid and component_pids are ENGINE pids,
-- referenced softly and checked through the engine API: no foreign key into schema engine (D2).
CREATE TABLE connector.connector (
    pid              uuid PRIMARY KEY,
    project_pid      uuid NOT NULL,
    ai_system_pid    uuid NOT NULL,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    slug             text NOT NULL,
    kind             text NOT NULL,
    environment      text NOT NULL CHECK (environment IN ('sandbox', 'production')),
    document         jsonb NOT NULL DEFAULT '{}'::jsonb,
    import_warnings  jsonb NOT NULL DEFAULT '[]'::jsonb,
    auth             jsonb NOT NULL DEFAULT '{"scheme": "none"}'::jsonb,
    settings         jsonb NOT NULL DEFAULT '{}'::jsonb,
    chat             jsonb,
    is_target_access boolean NOT NULL DEFAULT false,
    created_by       text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_pid, slug)
);
CREATE UNIQUE INDEX one_target_access_per_project
    ON connector.connector (project_pid) WHERE is_target_access;

CREATE TABLE connector.secret (
    connector_pid uuid NOT NULL REFERENCES connector.connector (pid) ON DELETE CASCADE,
    name          text NOT NULL,
    ciphertext    text NOT NULL,
    masked        text NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connector_pid, name)
);

CREATE TABLE connector.operation_policy (
    connector_pid          uuid NOT NULL REFERENCES connector.connector (pid) ON DELETE CASCADE,
    operation_id           text NOT NULL,
    allowed                boolean NOT NULL DEFAULT false,
    changes_data           boolean NOT NULL,
    changes_data_confirmed boolean NOT NULL DEFAULT false,
    patterns               jsonb NOT NULL DEFAULT '{}'::jsonb,
    component_pids         uuid[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (connector_pid, operation_id)
);

CREATE TABLE connector.access_token (
    pid           uuid PRIMARY KEY,
    connector_pid uuid NOT NULL REFERENCES connector.connector (pid) ON DELETE CASCADE,
    token_hash    text NOT NULL UNIQUE,
    label         text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    revoked_at    timestamptz
);

CREATE TABLE connector.publication (
    connector_pid          uuid PRIMARY KEY REFERENCES connector.connector (pid) ON DELETE CASCADE,
    token_pid              uuid NOT NULL REFERENCES connector.access_token (pid),
    secret_key             text NOT NULL,
    secret_config_pid      uuid NOT NULL,
    resource_component_pid uuid NOT NULL,
    llm_component_pid      uuid,
    published_at           timestamptz NOT NULL DEFAULT now()
);

-- One row per gateway or test call. Bodies are never stored (D7).
CREATE TABLE connector.call_log (
    id            bigserial PRIMARY KEY,
    connector_pid uuid NOT NULL,
    operation_id  text,
    token_pid     uuid,
    via           text NOT NULL,
    outcome       text NOT NULL,
    target_status integer,
    latency_ms    integer NOT NULL,
    at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX call_log_by_connector ON connector.call_log (connector_pid, at DESC);
```

`apps/connectors/aisc_connectors/db.py`:

```python
"""The connection pool, and the migrations it applies before it hands out a connection."""
from __future__ import annotations

import pathlib

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from aisc_connectors.settings import settings

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
#: Two services starting at once must not both apply 0001.
_LOCK = 0x636F6E6E
_pool: ConnectionPool | None = None


def migrate(dsn: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS connector.schema_migration"
            " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM connector.schema_migration")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO connector.schema_migration (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
    return applied


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        dsn = settings().database_url
        migrate(dsn)
        _pool = ConnectionPool(dsn, kwargs={"row_factory": dict_row}, open=True)
    return _pool


def reset_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_db.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add init/connectors-db.sql apps/connectors
git commit -m "Connectors service: its own role, schema and migrations, tested on a throwaway database"
```

---

### Task 3: Write-only secrets

**Files:**
- Create: `apps/connectors/aisc_connectors/vault.py`
- Test: `apps/connectors/tests/test_vault.py`

**Interfaces:**
- Consumes: `db.pool()`, `settings().secrets_key`.
- Produces: `vault.SECRET_NAMES: frozenset[str]` = `{"api_key", "token", "password", "client_secret", "client_cert", "client_key", "ca_bundle"}`; `vault.put(connector_pid, name, value) -> dict` (`{name, masked, updated_at}`); `vault.describe(connector_pid) -> list[dict]`; `vault.delete(connector_pid, name) -> bool`; `vault.plain(connector_pid, name) -> str | None` (executor only); `vault.rotate() -> int`; exceptions `VaultMisconfigured`, `UnknownSecretName`.

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_vault.py`:

```python
import uuid

import pytest


@pytest.fixture
def connector(db):
    pid = uuid.uuid4()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind,"
            " environment, created_by) VALUES (%s, %s, %s, 'X', 'x', 'manual', 'sandbox', 't')",
            (pid, uuid.uuid4(), uuid.uuid4()),
        )
    return pid


def test_put_then_plain_round_trips(connector):
    from aisc_connectors import vault

    vault.put(connector, "api_key", "sk-live-1234567890")
    assert vault.plain(connector, "api_key") == "sk-live-1234567890"


def test_describe_never_returns_the_value(connector):
    from aisc_connectors import vault

    vault.put(connector, "api_key", "sk-live-1234567890")
    described = vault.describe(connector)
    assert [d["name"] for d in described] == ["api_key"]
    assert "sk-live-1234567890" not in repr(described)
    assert described[0]["masked"] == "sk****90"


def test_short_values_are_fully_masked(connector):
    from aisc_connectors import vault

    assert vault.put(connector, "password", "abc")["masked"] == "****"


def test_the_ciphertext_is_not_the_value(db, connector):
    from aisc_connectors import vault

    vault.put(connector, "token", "plain-token-value")
    with db.connection() as conn:
        row = conn.execute("SELECT ciphertext FROM connector.secret").fetchone()
    assert "plain-token-value" not in row["ciphertext"]


def test_unknown_names_are_refused(connector):
    from aisc_connectors import vault

    with pytest.raises(vault.UnknownSecretName):
        vault.put(connector, "anything", "x")


def test_no_key_is_a_misconfiguration(connector, monkeypatch):
    from aisc_connectors import vault

    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", "")
    with pytest.raises(vault.VaultMisconfigured):
        vault.put(connector, "token", "x")


def test_rotation_reencrypts_under_the_newest_key(connector, monkeypatch, secrets_key):
    from cryptography.fernet import Fernet

    from aisc_connectors import vault

    vault.put(connector, "token", "keep-me")
    newest = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", f"{newest},{secrets_key}")
    assert vault.rotate() == 1
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", newest)
    assert vault.plain(connector, "token") == "keep-me"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_vault.py -v`
Expected: FAIL with `ImportError: cannot import name 'vault'`.

- [ ] **Step 3: Implement**

`apps/connectors/aisc_connectors/vault.py`:

```python
"""Credentials of the systems we connect to: encrypted at rest, never read back (spec D7).

Only the executor calls plain(). Every other caller gets the masked form.
"""
from __future__ import annotations

import uuid

from cryptography.fernet import Fernet, MultiFernet

from aisc_connectors import db
from aisc_connectors.settings import settings

SECRET_NAMES = frozenset(
    {"api_key", "token", "password", "client_secret", "client_cert", "client_key", "ca_bundle"}
)


class VaultMisconfigured(RuntimeError):
    """No usable CONNECTOR_SECRETS_KEY."""


class UnknownSecretName(ValueError):
    pass


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings().secrets_key.split(",") if k.strip()]
    if not keys:
        raise VaultMisconfigured("CONNECTOR_SECRETS_KEY is not set")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as exc:
        raise VaultMisconfigured("CONNECTOR_SECRETS_KEY is not a list of Fernet keys") from exc


def mask(value: str) -> str:
    return "****" if len(value) <= 8 else f"{value[:2]}****{value[-2:]}"


def put(connector_pid: uuid.UUID, name: str, value: str) -> dict:
    if name not in SECRET_NAMES:
        raise UnknownSecretName(f"{name!r} is not one of {sorted(SECRET_NAMES)}")
    ciphertext = _fernet().encrypt(value.encode()).decode()
    with db.pool().connection() as conn:
        return conn.execute(
            "INSERT INTO connector.secret (connector_pid, name, ciphertext, masked)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (connector_pid, name) DO UPDATE"
            "   SET ciphertext = excluded.ciphertext, masked = excluded.masked, updated_at = now()"
            " RETURNING name, masked, updated_at",
            (connector_pid, name, ciphertext, mask(value)),
        ).fetchone()


def describe(connector_pid: uuid.UUID) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT name, masked, updated_at FROM connector.secret WHERE connector_pid = %s ORDER BY name",
            (connector_pid,),
        ).fetchall()


def delete(connector_pid: uuid.UUID, name: str) -> bool:
    with db.pool().connection() as conn:
        return conn.execute(
            "DELETE FROM connector.secret WHERE connector_pid = %s AND name = %s", (connector_pid, name)
        ).rowcount == 1


def plain(connector_pid: uuid.UUID, name: str) -> str | None:
    with db.pool().connection() as conn:
        row = conn.execute(
            "SELECT ciphertext FROM connector.secret WHERE connector_pid = %s AND name = %s",
            (connector_pid, name),
        ).fetchone()
    return None if row is None else _fernet().decrypt(row["ciphertext"].encode()).decode()


def rotate() -> int:
    fernet = _fernet()
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT connector_pid, name, ciphertext FROM connector.secret").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE connector.secret SET ciphertext = %s WHERE connector_pid = %s AND name = %s",
                (fernet.rotate(row["ciphertext"].encode()).decode(), row["connector_pid"], row["name"]),
            )
    return len(rows)
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_vault.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: write-only secrets, Fernet with rotation"
```

---

### Task 4: Admin guard and the engine client

**Files:**
- Create: `apps/connectors/aisc_connectors/auth.py`, `apps/connectors/aisc_connectors/engine.py`, `apps/connectors/aisc_connectors/slug.py`
- Test: `apps/connectors/tests/test_auth.py`, `apps/connectors/tests/test_engine.py`, `apps/connectors/tests/test_slug.py`

**Interfaces:**
- Produces:
  - `auth.Admin` dataclass (`caller: Caller`, `token: str | None`); dependency `auth.admin_call(request) -> Admin` (401 without token, 403 without realm role `admin`).
  - `engine.EngineClient(token: str | None, base: str | None = None, transport: httpx.BaseTransport | None = None)` with `aisystem(project_pid) -> dict` (`{"pid", "name", "components": [{"pid", "name", "component_type", ...}]}`), `create_secret(project_pid, key, name, value) -> str`, `delete_secret(project_pid, config_pid) -> None`, `create_component(project_pid, name, component_type, json_value) -> str`, `delete_component(component_pid) -> None`; exceptions `engine.NotFound`, `engine.EngineError(status, detail)`.
  - `slug.slugify(name) -> str` (lowercase `[a-z0-9_]`, max 40), `slug.secret_key(slug) -> str` (`CONNECTOR_<SLUG>_TOKEN`).

- [ ] **Step 1: Write the failing tests**

`apps/connectors/tests/test_slug.py`:

```python
def test_slugs_are_safe_for_urls_and_secret_keys():
    from aisc_connectors.slug import secret_key, slugify

    assert slugify("MCAS lite, prod!") == "mcas_lite_prod"
    assert slugify("  ") == "connector"
    assert slugify("9 lives") == "c_9_lives"
    assert secret_key("mcas_lite_prod") == "CONNECTOR_MCAS_LITE_PROD_TOKEN"
    assert len(slugify("x" * 200)) == 40
```

`apps/connectors/tests/test_auth.py`:

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _app():
    from aisc_connectors.auth import Admin, admin_call

    app = FastAPI()

    @app.get("/who")
    def who(admin: Admin = Depends(admin_call)):
        return {"subject": admin.caller.subject, "forwarded": admin.token is not None}

    return TestClient(app)


def test_no_token_is_401(auth_on):
    assert _app().get("/who").status_code == 401


def test_a_user_without_admin_is_403(auth_on, as_user):
    assert _app().get("/who", headers=as_user("bob", ("primary-user",))).status_code == 403


def test_an_admin_passes_and_its_token_is_kept_for_the_engine(auth_on, as_user):
    response = _app().get("/who", headers=as_user("alice", ("admin",)))
    assert response.status_code == 200
    assert response.json() == {"subject": "alice", "forwarded": True}
```

`apps/connectors/tests/test_engine.py`:

```python
import uuid

import httpx
import pytest
import respx

BASE = "http://engine.test/api/v1"


@pytest.fixture
def engine():
    from aisc_connectors.engine import EngineClient

    return EngineClient("tok", base=BASE)


@respx.mock
def test_aisystem_sends_the_admins_token(engine):
    project = uuid.uuid4()
    route = respx.get(f"{BASE}/projects/{project}/aisystem").mock(
        return_value=httpx.Response(200, json={"pid": str(uuid.uuid4()), "name": "S", "components": []})
    )
    assert engine.aisystem(project)["name"] == "S"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_unknown_project_is_not_found(engine):
    project = uuid.uuid4()
    respx.get(f"{BASE}/projects/{project}/aisystem").mock(return_value=httpx.Response(404))
    from aisc_connectors.engine import NotFound

    with pytest.raises(NotFound):
        engine.aisystem(project)


@respx.mock
def test_create_secret_posts_a_secrets_category(engine):
    project, pid = uuid.uuid4(), uuid.uuid4()
    route = respx.post(f"{BASE}/project/settings/{project}").mock(
        return_value=httpx.Response(200, json={"pid": str(pid), "key": "K", "name": "n",
                                                "masked_value": "****", "json_value": {}, "category": "secrets"})
    )
    assert engine.create_secret(project, "K", "n", "v") == str(pid)
    sent = route.calls[0].request.read()
    assert b'"category":"secrets"' in sent.replace(b" ", b"")


@respx.mock
def test_create_component_returns_its_pid(engine):
    project, pid = uuid.uuid4(), uuid.uuid4()
    respx.post(f"{BASE}/projects/{project}/components").mock(
        return_value=httpx.Response(200, json={"pid": str(pid), "name": "n", "component_type": "resource",
                                                "json_value": {"value": "u"}})
    )
    assert engine.create_component(project, "n", "resource", {"value": "u"}) == str(pid)


@respx.mock
def test_engine_errors_keep_status_and_detail(engine):
    from aisc_connectors.engine import EngineError

    respx.delete(url__regex=rf"{BASE}/components/.*").mock(
        return_value=httpx.Response(403, json={"detail": "no"})
    )
    with pytest.raises(EngineError) as info:
        engine.delete_component(uuid.uuid4())
    assert info.value.status == 403
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/connectors && uv run pytest tests/test_slug.py tests/test_auth.py tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError` for `aisc_connectors.slug`, `.auth`, `.engine`.

- [ ] **Step 3: Implement**

`apps/connectors/aisc_connectors/slug.py`:

```python
"""Names people type, turned into what URLs and engine secret keys accept."""
import re


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40].strip("_")
    if not slug:
        return "connector"
    return f"c_{slug}"[:40] if slug[0].isdigit() else slug


def secret_key(slug: str) -> str:
    # engine ProjectConfig keys must match ^[A-Za-z][A-Za-z0-9_]*$
    return f"CONNECTOR_{slug.upper()}_TOKEN"
```

`apps/connectors/aisc_connectors/auth.py`:

```python
"""Admin only, and the admin's own token kept to call the engine with (spec D2, D7)."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from aisc_identity.caller import Caller
from aisc_identity.fastapi import requires_role
from aisc_identity.headers import token_from_headers

_admin = requires_role("admin")


@dataclass(frozen=True)
class Admin:
    caller: Caller
    token: str | None


def admin_call(request: Request, caller: Caller = Depends(_admin)) -> Admin:
    return Admin(caller=caller, token=token_from_headers(request.headers))
```

`apps/connectors/aisc_connectors/engine.py`:

```python
"""The engine, reached only through its public API and only with the admin's own token.

Nothing here touches the engine's database: its schema is frozen, grants included (spec D2).
"""
from __future__ import annotations

import uuid

import httpx

from aisc_connectors.settings import settings


class EngineError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"engine answered {status}: {detail}")
        self.status = status
        self.detail = detail


class NotFound(EngineError):
    pass


class EngineClient:
    def __init__(self, token: str | None, base: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(base_url=base or settings().engine_api_url, headers=headers,
                                  timeout=15, transport=transport)

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == 404:
            raise NotFound(404, "not found")
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail", response.text))
            except ValueError:
                detail = response.text[:300]
            raise EngineError(response.status_code, detail)
        return response

    def aisystem(self, project_pid: uuid.UUID) -> dict:
        return self._check(self._http.get(f"/projects/{project_pid}/aisystem")).json()

    def create_secret(self, project_pid: uuid.UUID, key: str, name: str, value: str) -> str:
        body = {"category": "secrets", "key": key, "name": name, "value": value}
        return self._check(self._http.post(f"/project/settings/{project_pid}", json=body)).json()["pid"]

    def delete_secret(self, project_pid: uuid.UUID, config_pid: uuid.UUID) -> None:
        self._check(self._http.delete(f"/project/settings/{project_pid}/{config_pid}"))

    def create_component(self, project_pid: uuid.UUID, name: str, component_type: str,
                         json_value: dict) -> str:
        body = {"name": name, "component_type": component_type, "json_value": json_value}
        return self._check(self._http.post(f"/projects/{project_pid}/components", json=body)).json()["pid"]

    def delete_component(self, component_pid: uuid.UUID) -> None:
        self._check(self._http.delete(f"/components/{component_pid}"))
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_slug.py tests/test_auth.py tests/test_engine.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: admin-only guard, engine API client, slugs"
```

---

### Task 5: Connector records, target access and readiness

**Files:**
- Create: `apps/connectors/aisc_connectors/store.py`, `apps/connectors/aisc_connectors/routes_admin.py`
- Modify: `apps/connectors/aisc_connectors/app.py` (include the admin router)
- Test: `apps/connectors/tests/test_admin_connectors.py`

**Interfaces:**
- Consumes: `auth.admin_call`, `engine.EngineClient`, `vault`, `slug`.
- Produces:
  - `store.create_connector(project_pid, ai_system_pid, name, slug, kind, environment, created_by) -> dict`, `store.get(connector_pid) -> dict | None`, `store.list_for_project(project_pid) -> list[dict]`, `store.update(connector_pid, **fields) -> dict`, `store.delete(connector_pid) -> None`, `store.make_target_access(connector_pid) -> None`, `store.target_access_count(project_pid) -> int`.
  - `routes_admin.router` (APIRouter, prefix `/api/v1/connectors`) and dependency `routes_admin.engine_for(admin) -> EngineClient` (tests override it).
  - Connector JSON returned by the API: `{pid, project_pid, ai_system_pid, name, slug, kind, environment, auth, settings, chat, is_target_access, import_warnings, secrets: [{name, masked, updated_at}], orphaned}`. `document` is never returned by these routes.
  - `AUTH_SCHEMES` validation: `none`; `api_key` (`in`: header|query, `name`); `bearer`; `basic` (`username`); `oauth2_client_credentials` (`token_url`, `client_id`, optional `scope`); `mtls`.
  - `SETTINGS_KEYS`: `timeout_s` (1..300, default 30), `rate_limit_per_minute` (1..6000, default 60), `verify_tls` (bool, default true), `ollama_facade` (bool, default false).

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_admin_connectors.py`:

```python
import uuid

import pytest
from fastapi.testclient import TestClient


class FakeEngine:
    """The engine as the service sees it: one project with an AI system and two components."""

    def __init__(self):
        self.project = uuid.uuid4()
        self.system = uuid.uuid4()
        self.components = [uuid.uuid4(), uuid.uuid4()]
        self.known = {self.project}

    def aisystem(self, project_pid):
        from aisc_connectors.engine import NotFound

        if uuid.UUID(str(project_pid)) not in self.known:
            raise NotFound(404, "not found")
        return {"pid": str(self.system), "name": "S",
                "components": [{"pid": str(c), "name": f"c{i}", "component_type": "model"}
                               for i, c in enumerate(self.components)]}


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def api(db, auth_on, engine):
    from aisc_connectors import routes_admin
    from aisc_connectors.app import app

    app.dependency_overrides[routes_admin.engine_for] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def create(api, as_user, engine, name="MCAS", environment="sandbox"):
    return api.post("/api/v1/connectors", headers=as_user(),
                    json={"project_pid": str(engine.project), "name": name, "environment": environment})


def test_non_admins_are_refused_everywhere(api, as_user, engine):
    user = as_user("bob", ("primary-user",))
    assert api.get(f"/api/v1/connectors?project_pid={engine.project}", headers=user).status_code == 403
    assert api.post("/api/v1/connectors", headers=user, json={}).status_code == 403


def test_the_first_connector_becomes_target_access(api, as_user, engine):
    first = create(api, as_user, engine).json()
    second = create(api, as_user, engine, name="Other").json()
    assert first["is_target_access"] is True
    assert second["is_target_access"] is False
    assert first["ai_system_pid"] == str(engine.system)


def test_an_unknown_project_is_refused(api, as_user, engine):
    response = api.post("/api/v1/connectors", headers=as_user(),
                        json={"project_pid": str(uuid.uuid4()), "name": "X", "environment": "sandbox"})
    assert response.status_code == 404


def test_the_last_target_access_connector_cannot_be_deleted(api, as_user, engine):
    first = create(api, as_user, engine).json()
    response = api.delete(f"/api/v1/connectors/{first['pid']}", headers=as_user())
    assert response.status_code == 409
    second = create(api, as_user, engine, name="Other").json()
    assert api.post(f"/api/v1/connectors/{second['pid']}/target-access", headers=as_user()).status_code == 200
    assert api.delete(f"/api/v1/connectors/{first['pid']}", headers=as_user()).status_code == 204


def test_an_orphaned_connector_can_be_deleted(api, as_user, engine):
    first = create(api, as_user, engine).json()
    engine.known.clear()
    listed = api.get(f"/api/v1/connectors/{first['pid']}", headers=as_user()).json()
    assert listed["orphaned"] is True
    assert api.delete(f"/api/v1/connectors/{first['pid']}", headers=as_user()).status_code == 204


def test_readiness_says_whether_a_target_access_connector_exists(api, as_user, engine):
    url = f"/api/v1/connectors/projects/{engine.project}/readiness"
    assert api.get(url, headers=as_user()).json() == {"has_target_access": False}
    create(api, as_user, engine)
    assert api.get(url, headers=as_user()).json() == {"has_target_access": True}


def test_secrets_are_write_only(api, as_user, engine):
    first = create(api, as_user, engine).json()
    put = api.put(f"/api/v1/connectors/{first['pid']}/secrets/api_key", headers=as_user(),
                  json={"value": "sk-abcdefghijk"})
    assert put.status_code == 200
    shown = api.get(f"/api/v1/connectors/{first['pid']}", headers=as_user()).text
    assert "sk-abcdefghijk" not in shown
    assert "sk****jk" in shown


def test_auth_scheme_fields_are_checked(api, as_user, engine):
    first = create(api, as_user, engine).json()
    bad = api.put(f"/api/v1/connectors/{first['pid']}/auth", headers=as_user(),
                  json={"scheme": "api_key", "in": "cookie", "name": "X"})
    assert bad.status_code == 422
    good = api.put(f"/api/v1/connectors/{first['pid']}/auth", headers=as_user(),
                   json={"scheme": "api_key", "in": "header", "name": "X-API-Key"})
    assert good.status_code == 200
    assert good.json()["auth"] == {"scheme": "api_key", "in": "header", "name": "X-API-Key"}


def test_settings_are_bounded(api, as_user, engine):
    first = create(api, as_user, engine).json()
    assert api.patch(f"/api/v1/connectors/{first['pid']}", headers=as_user(),
                     json={"settings": {"timeout_s": 0}}).status_code == 422
    ok = api.patch(f"/api/v1/connectors/{first['pid']}", headers=as_user(),
                   json={"settings": {"timeout_s": 10, "ollama_facade": True}})
    assert ok.json()["settings"]["timeout_s"] == 10
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_admin_connectors.py -v`
Expected: FAIL with `ImportError: cannot import name 'routes_admin'`.

- [ ] **Step 3: Implement the store**

`apps/connectors/aisc_connectors/store.py`:

```python
"""SQL for the connector records. Every function opens its own short transaction."""
from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb

from aisc_connectors import db

_COLUMNS = ("pid, project_pid, ai_system_pid, name, slug, kind, environment, auth, settings, chat,"
            " is_target_access, import_warnings, created_at, updated_at")
_JSON = {"auth", "settings", "chat", "document", "import_warnings"}


def create_connector(project_pid, ai_system_pid, name, slug, kind, environment, created_by) -> dict:
    with db.pool().connection() as conn:
        first = conn.execute(
            "SELECT NOT EXISTS (SELECT 1 FROM connector.connector WHERE project_pid = %s AND is_target_access)"
            " AS first", (project_pid,),
        ).fetchone()["first"]
        return conn.execute(
            f"INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind, environment,"
            f" is_target_access, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
            (uuid.uuid4(), project_pid, ai_system_pid, name, slug, kind, environment, first, created_by),
        ).fetchone()


def get(connector_pid, with_document: bool = False) -> dict | None:
    columns = _COLUMNS + (", document" if with_document else "")
    with db.pool().connection() as conn:
        return conn.execute(f"SELECT {columns} FROM connector.connector WHERE pid = %s",
                            (connector_pid,)).fetchone()


def list_for_project(project_pid) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            f"SELECT {_COLUMNS} FROM connector.connector WHERE project_pid = %s ORDER BY created_at",
            (project_pid,),
        ).fetchall()


def update(connector_pid, **fields) -> dict:
    sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = now()"
    values = [Jsonb(v) if k in _JSON and v is not None else v for k, v in fields.items()]
    with db.pool().connection() as conn:
        return conn.execute(
            f"UPDATE connector.connector SET {sets} WHERE pid = %s RETURNING {_COLUMNS}",
            (*values, connector_pid),
        ).fetchone()


def delete(connector_pid) -> None:
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM connector.connector WHERE pid = %s", (connector_pid,))


def make_target_access(connector_pid) -> None:
    with db.pool().connection() as conn:
        project = conn.execute("SELECT project_pid FROM connector.connector WHERE pid = %s",
                               (connector_pid,)).fetchone()["project_pid"]
        conn.execute("UPDATE connector.connector SET is_target_access = false"
                     " WHERE project_pid = %s AND is_target_access", (project,))
        conn.execute("UPDATE connector.connector SET is_target_access = true WHERE pid = %s", (connector_pid,))


def target_access_count(project_pid) -> int:
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM connector.connector WHERE project_pid = %s AND is_target_access",
            (project_pid,),
        ).fetchone()["n"]
```

- [ ] **Step 4: Implement the routes**

`apps/connectors/aisc_connectors/routes_admin.py`:

```python
"""Admin routes: /api/v1/connectors. Every route depends on admin_call (spec D7)."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from aisc_connectors import engine as engine_api
from aisc_connectors import store, vault
from aisc_connectors.auth import Admin, admin_call
from aisc_connectors.slug import slugify

router = APIRouter(prefix="/api/v1/connectors")

SETTINGS_DEFAULTS = {"timeout_s": 30, "rate_limit_per_minute": 60, "verify_tls": True, "ollama_facade": False}
SETTINGS_BOUNDS = {"timeout_s": (1, 300), "rate_limit_per_minute": (1, 6000)}


def engine_for(admin: Admin = Depends(admin_call)) -> engine_api.EngineClient:
    return engine_api.EngineClient(admin.token)


class NewConnector(BaseModel):
    project_pid: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    environment: Literal["sandbox", "production"] = "sandbox"


class ConnectorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    environment: Literal["sandbox", "production"] | None = None
    settings: dict[str, Any] | None = None


class SecretValue(BaseModel):
    value: str = Field(min_length=1, max_length=65536)


def check_auth(auth: dict) -> dict:
    scheme = auth.get("scheme")
    required = {
        "none": [], "bearer": [], "mtls": [],
        "api_key": ["in", "name"], "basic": ["username"],
        "oauth2_client_credentials": ["token_url", "client_id"],
    }
    if scheme not in required:
        raise HTTPException(422, f"unknown auth scheme {scheme!r}")
    missing = [f for f in required[scheme] if not auth.get(f)]
    if missing:
        raise HTTPException(422, f"auth scheme {scheme} needs {missing}")
    if scheme == "api_key" and auth["in"] not in ("header", "query"):
        raise HTTPException(422, "api_key goes in a header or the query")
    allowed = {"scheme", *required[scheme], "scope"}
    return {k: v for k, v in auth.items() if k in allowed}


def check_settings(current: dict, patch: dict) -> dict:
    merged = {**SETTINGS_DEFAULTS, **current, **patch}
    unknown = set(patch) - set(SETTINGS_DEFAULTS)
    if unknown:
        raise HTTPException(422, f"unknown settings {sorted(unknown)}")
    for key, (low, high) in SETTINGS_BOUNDS.items():
        if not isinstance(merged[key], int) or not low <= merged[key] <= high:
            raise HTTPException(422, f"{key} must be an integer between {low} and {high}")
    for key in ("verify_tls", "ollama_facade"):
        if not isinstance(merged[key], bool):
            raise HTTPException(422, f"{key} must be true or false")
    return merged


def loaded(connector_pid: uuid.UUID) -> dict:
    found = store.get(connector_pid)
    if found is None:
        raise HTTPException(404, "no such connector")
    return found


def orphaned(row: dict, engine: engine_api.EngineClient) -> bool:
    try:
        engine.aisystem(row["project_pid"])
        return False
    except engine_api.NotFound:
        return True


def shown(row: dict, engine: engine_api.EngineClient) -> dict:
    return {**{k: row[k] for k in ("pid", "project_pid", "ai_system_pid", "name", "slug", "kind", "environment",
                                   "auth", "chat", "is_target_access", "import_warnings")},
            "settings": {**SETTINGS_DEFAULTS, **(row["settings"] or {})},
            "secrets": vault.describe(row["pid"]),
            "orphaned": orphaned(row, engine)}


@router.post("")
def create(body: NewConnector, admin: Admin = Depends(admin_call),
           engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    try:
        system = engine.aisystem(body.project_pid)
    except engine_api.NotFound:
        raise HTTPException(404, "the engine knows no such project")
    row = store.create_connector(body.project_pid, uuid.UUID(system["pid"]), body.name, slugify(body.name),
                                 "manual", body.environment, admin.caller.subject)
    return shown(row, engine)


@router.get("")
def list_connectors(project_pid: uuid.UUID, admin: Admin = Depends(admin_call),
                    engine: engine_api.EngineClient = Depends(engine_for)) -> list[dict]:
    return [shown(row, engine) for row in store.list_for_project(project_pid)]


@router.get("/projects/{project_pid}/readiness")
def readiness(project_pid: uuid.UUID, admin: Admin = Depends(admin_call)) -> dict:
    return {"has_target_access": store.target_access_count(project_pid) > 0}


@router.get("/{connector_pid}")
def read(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
         engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    return shown(loaded(connector_pid), engine)


@router.patch("/{connector_pid}")
def patch(connector_pid: uuid.UUID, body: ConnectorPatch, admin: Admin = Depends(admin_call),
          engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    row = loaded(connector_pid)
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields.update(name=body.name, slug=slugify(body.name))
    if body.environment is not None:
        fields["environment"] = body.environment
    if body.settings is not None:
        fields["settings"] = check_settings(row["settings"] or {}, body.settings)
    return shown(store.update(connector_pid, **fields) if fields else row, engine)


@router.delete("/{connector_pid}", status_code=204)
def remove(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
           engine: engine_api.EngineClient = Depends(engine_for)) -> Response:
    row = loaded(connector_pid)
    if row["is_target_access"] and not orphaned(row, engine):
        raise HTTPException(409, "this is the project's target-access connector: mark another one first")
    store.delete(connector_pid)
    return Response(status_code=204)


@router.post("/{connector_pid}/target-access")
def target_access(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
                  engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    loaded(connector_pid)
    store.make_target_access(connector_pid)
    return shown(loaded(connector_pid), engine)


@router.put("/{connector_pid}/auth")
def set_auth(connector_pid: uuid.UUID, body: dict, admin: Admin = Depends(admin_call),
             engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    loaded(connector_pid)
    return shown(store.update(connector_pid, auth=check_auth(body)), engine)


@router.put("/{connector_pid}/secrets/{name}")
def put_secret(connector_pid: uuid.UUID, name: str, body: SecretValue, admin: Admin = Depends(admin_call)) -> dict:
    loaded(connector_pid)
    try:
        return vault.put(connector_pid, name, body.value)
    except vault.UnknownSecretName as exc:
        raise HTTPException(422, str(exc))


@router.delete("/{connector_pid}/secrets/{name}", status_code=204)
def delete_secret(connector_pid: uuid.UUID, name: str, admin: Admin = Depends(admin_call)) -> Response:
    loaded(connector_pid)
    vault.delete(connector_pid, name)
    return Response(status_code=204)
```

Modify `apps/connectors/aisc_connectors/app.py`: after `app = FastAPI(...)` add

```python
from aisc_connectors import routes_admin  # noqa: E402

app.include_router(routes_admin.router)
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_admin_connectors.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: records, target access, readiness, auth and write-only secrets over the admin API"
```

---

### Task 6: The canonical document and the OpenAPI 3.x importer

**Files:**
- Create: `apps/connectors/aisc_connectors/model.py`
- Create: `apps/connectors/aisc_connectors/importers/__init__.py`, `errors.py`, `fetch.py`, `openapi.py`
- Create: `apps/connectors/tests/fixtures/mcas_openapi.json`
- Test: `apps/connectors/tests/test_model.py`, `apps/connectors/tests/test_import_openapi.py`

**Interfaces:**
- Produces:
  - `model.Operation` dataclass: `operation_id: str`, `method: str` (lowercase), `path: str`, `summary: str`, `changes_data: bool`, `binding: dict`, `spec: dict` (the raw operation object).
  - `model.operations(document) -> list[Operation]` in document order; `model.find(document, operation_id) -> Operation | None`; `model.server_url(document) -> str`; `model.strip_aisc(obj)` (removes every `x-aisc-*` key, recursively, returns a copy).
  - `importers.errors.ImportFailed(message)`; `importers.ImportResult` dataclass (`document: dict`, `warnings: list[str]`, `auth_suggestion: dict | None`, `detected_secrets: dict[str, str]`, `chat_suggestion: dict | None`).
  - `importers.openapi.import_openapi(text: str, source_url: str | None = None, base_url: str | None = None) -> ImportResult`.
  - `importers.fetch.fetch_text(url: str) -> str` (limit `settings().max_spec_bytes`, 20 s timeout, refuses link-local hosts).
  - Canonical rules every importer follows: `openapi: "3.1.0"`; exactly one entry in `servers`; every operation has `operationId` and `x-aisc-binding` with at least `{"protocol": ...}`; HTTP bindings are `{"protocol": "http", "method", "path", "static_headers": {}}`.

- [ ] **Step 1: Save MCAS-lite's real spec as a fixture**

Run (MCAS-lite is running on the host; this only reads its spec):

```bash
mkdir -p apps/connectors/tests/fixtures
curl -s localhost:8500/openapi.json | python3 -m json.tool > apps/connectors/tests/fixtures/mcas_openapi.json
python3 -c "import json;d=json.load(open('apps/connectors/tests/fixtures/mcas_openapi.json'));print(len([m for p in d['paths'].values() for m in p]))"
```

Expected: `10`.

- [ ] **Step 2: Write the failing tests**

`apps/connectors/tests/test_model.py`:

```python
def doc():
    return {
        "openapi": "3.1.0", "servers": [{"url": "http://t.example"}],
        "paths": {
            "/users/{id}": {"get": {"operationId": "getUser",
                                    "x-aisc-binding": {"protocol": "http", "method": "get", "path": "/users/{id}"}}},
            "/users": {"post": {"operationId": "createUser", "summary": "Create",
                                "x-aisc-binding": {"protocol": "http", "method": "post", "path": "/users"}}},
        },
    }


def test_operations_list_every_method_with_its_side_effect_flag():
    from aisc_connectors.model import operations

    ops = {o.operation_id: o for o in operations(doc())}
    assert ops["getUser"].changes_data is False
    assert ops["createUser"].changes_data is True
    assert ops["createUser"].summary == "Create"


def test_strip_aisc_removes_extensions_everywhere():
    from aisc_connectors.model import strip_aisc

    stripped = strip_aisc({**doc(), "x-aisc-auth": {"scheme": "bearer"}})
    assert "x-aisc-auth" not in stripped
    assert "x-aisc-binding" not in stripped["paths"]["/users"]["post"]


def test_server_url():
    from aisc_connectors.model import server_url

    assert server_url(doc()) == "http://t.example"
```

`apps/connectors/tests/test_import_openapi.py`:

```python
import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def mcas_text():
    return (FIXTURES / "mcas_openapi.json").read_text()


def test_mcas_imports_all_ten_operations():
    from aisc_connectors.importers.openapi import import_openapi
    from aisc_connectors.model import operations

    result = import_openapi(mcas_text(), source_url="http://172.17.0.1:8500/openapi.json")
    ops = {o.path: o for o in operations(result.document)}
    assert len(ops) == 10
    assert result.document["servers"] == [{"url": "http://172.17.0.1:8500"}]
    assert ops["/chat"].binding == {"protocol": "http", "method": "post", "path": "/chat", "static_headers": {}}
    assert ops["/health"].changes_data is False
    assert ops["/halt"].changes_data is True


def test_a_missing_server_needs_a_base_url():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.openapi import import_openapi

    with pytest.raises(ImportFailed, match="base URL"):
        import_openapi(mcas_text())
    assert import_openapi(mcas_text(), base_url="http://h:1").document["servers"] == [{"url": "http://h:1"}]


def test_invalid_but_usable_spec_imports_with_warnings():
    from aisc_connectors.importers.openapi import import_openapi

    spec = {"openapi": "3.0.3", "info": {"title": "t"},  # no version: invalid
            "servers": [{"url": "/v1"}],
            "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}}}
    result = import_openapi(json.dumps(spec), source_url="https://api.example.com/spec.json")
    assert result.document["servers"] == [{"url": "https://api.example.com/v1"}]
    assert any("not valid" in w for w in result.warnings)
    assert result.document["paths"]["/ping"]["get"]["operationId"] == "get_ping"


def test_synthesized_ids_are_stable():
    from aisc_connectors.importers.openapi import import_openapi

    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "http://h"}],
                       "paths": {"/a/{id}/b": {"get": {}, "post": {}}, "/a_id_b": {"get": {}}}})
    first = import_openapi(spec).document
    second = import_openapi(spec).document
    ids = [first["paths"]["/a/{id}/b"]["get"]["operationId"], first["paths"]["/a/{id}/b"]["post"]["operationId"],
           first["paths"]["/a_id_b"]["get"]["operationId"]]
    assert len(set(ids)) == 3
    assert ids[0] == second["paths"]["/a/{id}/b"]["get"]["operationId"]


def test_a_spec_cannot_smuggle_in_bindings():
    from aisc_connectors.importers.openapi import import_openapi

    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "http://h"}],
                       "paths": {"/x": {"get": {"operationId": "x",
                                                "x-aisc-binding": {"protocol": "http", "path": "//evil"}}}}})
    op = import_openapi(spec).document["paths"]["/x"]["get"]
    assert op["x-aisc-binding"]["path"] == "/x"


def test_yaml_is_accepted():
    from aisc_connectors.importers.openapi import import_openapi

    text = "openapi: 3.1.0\ninfo: {title: t, version: '1'}\nservers: [{url: 'http://h'}]\npaths:\n  /p:\n    get: {operationId: p}\n"
    assert import_openapi(text).document["paths"]["/p"]["get"]["operationId"] == "p"


def test_security_schemes_become_an_auth_suggestion():
    from aisc_connectors.importers.openapi import import_openapi

    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "http://h"}],
                       "components": {"securitySchemes": {"k": {"type": "apiKey", "in": "header", "name": "X-Key"}}},
                       "paths": {}})
    assert import_openapi(spec).auth_suggestion == {"scheme": "api_key", "in": "header", "name": "X-Key"}


def test_swagger_two_is_routed_to_the_converter(monkeypatch):
    from aisc_connectors.importers import openapi

    called = {}
    monkeypatch.setattr("aisc_connectors.importers.swagger2.convert",
                        lambda d: called.setdefault("yes", {"openapi": "3.1.0", "info": {"title": "t", "version": "1"},
                                                            "servers": [{"url": "http://h"}], "paths": {}}))
    openapi.import_openapi(json.dumps({"swagger": "2.0", "info": {}, "paths": {}}))
    assert "yes" in called


def test_other_documents_are_refused():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.openapi import import_openapi

    with pytest.raises(ImportFailed):
        import_openapi("<html>not a spec</html>")
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd apps/connectors && uv run pytest tests/test_model.py tests/test_import_openapi.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.model'`.

- [ ] **Step 4: Implement the model**

`apps/connectors/aisc_connectors/model.py`:

```python
"""The canonical document: OpenAPI 3.1 whose operations carry x-aisc-binding (spec D3)."""
from __future__ import annotations

import copy
from dataclasses import dataclass

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
SAFE_METHODS = {"get", "head", "options"}


@dataclass(frozen=True)
class Operation:
    operation_id: str
    method: str
    path: str
    summary: str
    changes_data: bool
    binding: dict
    spec: dict


def operations(document: dict) -> list[Operation]:
    found = []
    for path, item in (document.get("paths") or {}).items():
        for method in HTTP_METHODS:
            op = (item or {}).get(method)
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            found.append(Operation(op["operationId"], method, path, op.get("summary") or "",
                                   method not in SAFE_METHODS or op.get("x-aisc-binding", {}).get("protocol") == "soap",
                                   op.get("x-aisc-binding") or {}, op))
    return found


def find(document: dict, operation_id: str) -> Operation | None:
    return next((o for o in operations(document) if o.operation_id == operation_id), None)


def server_url(document: dict) -> str:
    return document["servers"][0]["url"].rstrip("/")


def strip_aisc(obj):
    if isinstance(obj, dict):
        return {k: strip_aisc(v) for k, v in obj.items() if not str(k).startswith("x-aisc")}
    if isinstance(obj, list):
        return [strip_aisc(v) for v in obj]
    return copy.deepcopy(obj)
```

- [ ] **Step 5: Implement the importer package**

`apps/connectors/aisc_connectors/importers/errors.py`:

```python
class ImportFailed(ValueError):
    """The source cannot become a connector; the message says what to change."""
```

`apps/connectors/aisc_connectors/importers/__init__.py`:

```python
"""Every technology becomes the same canonical OpenAPI document (spec D3)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportResult:
    document: dict
    warnings: list[str] = field(default_factory=list)
    auth_suggestion: dict | None = None
    #: Secret values found in the source (a cURL Authorization header, say). They are offered to
    #: the admin to store in the vault and are never written into the document.
    detected_secrets: dict[str, str] = field(default_factory=dict)
    #: For LLM-shaped connectors: how the facades should call the chat operation.
    chat_suggestion: dict | None = None
```

`apps/connectors/aisc_connectors/importers/fetch.py`:

```python
"""Downloading a spec: bounded in size and time, and never from a metadata address."""
from __future__ import annotations

import httpx

from aisc_connectors.executor.guard import refuse_metadata_host
from aisc_connectors.importers.errors import ImportFailed
from aisc_connectors.settings import settings


def fetch_text(url: str) -> str:
    refuse_metadata_host(url)
    limit = settings().max_spec_bytes
    try:
        with httpx.stream("GET", url, timeout=20, follow_redirects=True) as response:
            if response.status_code >= 400:
                raise ImportFailed(f"{url} answered {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ImportFailed(f"the document is larger than {limit} bytes")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise ImportFailed(f"could not download {url}: {exc}") from exc
    return b"".join(chunks).decode("utf-8", errors="replace")
```

(`refuse_metadata_host` is created in Task 13; until then create `apps/connectors/aisc_connectors/executor/__init__.py` empty and `apps/connectors/aisc_connectors/executor/guard.py` with only this function:)

```python
"""Outbound safety for everything that leaves this service (spec D7)."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from aisc_connectors.executor.errors import GatewayFailure

_METADATA = [ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("fd00:ec2::254/128")]


def refuse_metadata_host(url: str) -> None:
    host = urlsplit(url).hostname
    if not host:
        raise GatewayFailure("invalid_input", f"{url!r} has no host")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise GatewayFailure("dns", f"{host} does not resolve") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if any(ip in net for net in _METADATA):
            raise GatewayFailure("not_allowed", f"{host} resolves to a link-local metadata address")
```

and `apps/connectors/aisc_connectors/executor/errors.py`:

```python
"""What can go wrong, in words a person can act on (spec D8)."""
from __future__ import annotations

#: Target-side kinds: the target answered, and this is what its answer means.
TARGET_KINDS = {"ok", "auth", "not_found", "rate_limited", "target_rejected", "target_error"}
#: Gateway-side kinds and the status the gateway answers with.
GATEWAY_STATUS = {
    "not_allowed": 403, "invalid_input": 422, "rate_limited": 429, "timeout": 504,
    "tls": 502, "dns": 502, "connection": 502, "bad_mapping": 502, "target_too_large": 502,
}


class GatewayFailure(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message

    @property
    def status(self) -> int:
        return GATEWAY_STATUS.get(self.kind, 502)

    def body(self) -> dict:
        return {"error": {"kind": self.kind, "message": self.message}}


def kind_for_status(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "target_rejected"
    if status >= 500:
        return "target_error"
    return "ok"
```

`apps/connectors/aisc_connectors/importers/openapi.py`:

```python
"""OpenAPI 3.x (and Swagger 2.0, via the converter) into the canonical document."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

import yaml
from openapi_spec_validator import validate

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.errors import ImportFailed
from aisc_connectors.model import HTTP_METHODS, strip_aisc


def _parse(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ImportFailed("this is neither JSON nor YAML") from exc
    if not isinstance(data, dict):
        raise ImportFailed("this is not an OpenAPI or Swagger document")
    return data


def _synth_id(method: str, path: str) -> str:
    return method + "_" + (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root")


def _server(doc: dict, source_url: str | None, base_url: str | None, warnings: list[str]) -> str:
    if base_url:
        return base_url.rstrip("/")
    servers = doc.get("servers") or []
    url = servers[0]["url"] if servers and servers[0].get("url") else None
    if len(servers) > 1:
        warnings.append(f"the spec lists {len(servers)} servers; using the first, {url}")
    if url and "{" in url:
        for name, var in (servers[0].get("variables") or {}).items():
            url = url.replace("{" + name + "}", str(var.get("default", "")))
    if url and not urlsplit(url).scheme:
        if not source_url:
            raise ImportFailed(f"the server URL {url!r} is relative: give the base URL")
        url = urljoin(source_url, url)
    if not url:
        if not source_url:
            raise ImportFailed("the spec names no server: give the base URL")
        parts = urlsplit(source_url)
        url = f"{parts.scheme}://{parts.netloc}"
        warnings.append(f"the spec names no server; using {url}, where it was downloaded from")
    return url.rstrip("/")


def _auth_suggestion(doc: dict) -> dict | None:
    for scheme in ((doc.get("components") or {}).get("securitySchemes") or {}).values():
        kind = scheme.get("type")
        if kind == "apiKey" and scheme.get("in") in ("header", "query"):
            return {"scheme": "api_key", "in": scheme["in"], "name": scheme["name"]}
        if kind == "http" and scheme.get("scheme", "").lower() == "bearer":
            return {"scheme": "bearer"}
        if kind == "http" and scheme.get("scheme", "").lower() == "basic":
            return {"scheme": "basic", "username": ""}
        if kind == "oauth2" and "clientCredentials" in (scheme.get("flows") or {}):
            return {"scheme": "oauth2_client_credentials",
                    "token_url": scheme["flows"]["clientCredentials"].get("tokenUrl", ""), "client_id": ""}
        if kind == "mutualTLS":
            return {"scheme": "mtls"}
    return None


def import_openapi(text: str, source_url: str | None = None, base_url: str | None = None) -> ImportResult:
    raw = _parse(text)
    if str(raw.get("swagger", "")).startswith("2"):
        from aisc_connectors.importers import swagger2

        raw = swagger2.convert(raw)
    elif not str(raw.get("openapi", "")).startswith("3."):
        raise ImportFailed("this is not an OpenAPI 3.x or Swagger 2.0 document")
    warnings: list[str] = []
    try:
        validate(raw)
    except Exception as exc:  # the validator raises many types; all mean "imperfect"
        warnings.append(f"the spec is not valid OpenAPI ({str(exc).splitlines()[0][:200]}); importing what can be used")
    doc = strip_aisc(raw)
    doc["openapi"] = "3.1.0"
    doc["servers"] = [{"url": _server(raw, source_url, base_url, warnings)}]
    used: set[str] = set()
    for path, item in (doc.get("paths") or {}).items():
        for method in HTTP_METHODS:
            op = (item or {}).get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or _synth_id(method, path)
            while op_id in used:
                op_id += "_"
            used.add(op_id)
            op["operationId"] = op_id
            if op.get("servers"):
                warnings.append(f"{op_id} names its own server; the connector's server is used instead")
            op["x-aisc-binding"] = {"protocol": "http", "method": method, "path": path, "static_headers": {}}
    return ImportResult(document=doc, warnings=warnings, auth_suggestion=_auth_suggestion(raw))
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_model.py tests/test_import_openapi.py -v`
Expected: all pass except `test_swagger_two_is_routed_to_the_converter`, which fails with `ModuleNotFoundError: aisc_connectors.importers.swagger2` (Task 7 creates it). Create `apps/connectors/aisc_connectors/importers/swagger2.py` now with

```python
def convert(doc: dict) -> dict:
    raise NotImplementedError("Task 7")
```

and rerun: 13 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: canonical OpenAPI document and the OpenAPI 3.x importer, MCAS spec as fixture"
```

---

### Task 7: Swagger 2.0 converter

**Files:**
- Modify: `apps/connectors/aisc_connectors/importers/swagger2.py`
- Create: `apps/connectors/tests/fixtures/petstore_swagger2.json`
- Test: `apps/connectors/tests/test_import_swagger2.py`

**Interfaces:**
- Produces: `swagger2.convert(doc: dict) -> dict` (an OpenAPI 3.1 document, not yet canonical; `import_openapi` finishes it).

- [ ] **Step 1: Write the fixture**

`apps/connectors/tests/fixtures/petstore_swagger2.json`:

```json
{
  "swagger": "2.0",
  "info": {"title": "Petstore", "version": "1"},
  "host": "petstore.example.com",
  "basePath": "/v2",
  "schemes": ["https"],
  "consumes": ["application/json"],
  "produces": ["application/json"],
  "securityDefinitions": {"key": {"type": "apiKey", "in": "header", "name": "api_key"}},
  "paths": {
    "/pet": {"post": {"operationId": "addPet",
      "parameters": [{"in": "body", "name": "body", "required": true, "schema": {"$ref": "#/definitions/Pet"}}],
      "responses": {"200": {"description": "ok", "schema": {"$ref": "#/definitions/Pet"}}}}},
    "/pet/{petId}": {"get": {"operationId": "getPetById",
      "parameters": [{"in": "path", "name": "petId", "required": true, "type": "integer", "format": "int64"}],
      "responses": {"200": {"description": "ok", "schema": {"$ref": "#/definitions/Pet"}}}}},
    "/pet/{petId}/uploadImage": {"post": {"operationId": "uploadFile", "consumes": ["multipart/form-data"],
      "parameters": [{"in": "path", "name": "petId", "required": true, "type": "integer"},
                     {"in": "formData", "name": "file", "type": "file"},
                     {"in": "formData", "name": "note", "type": "string"}],
      "responses": {"200": {"description": "ok"}}}}
  },
  "definitions": {"Pet": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}}
}
```

- [ ] **Step 2: Write the failing test**

`apps/connectors/tests/test_import_swagger2.py`:

```python
import json
import pathlib

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "petstore_swagger2.json"


def converted():
    from aisc_connectors.importers.swagger2 import convert

    return convert(json.loads(FIXTURE.read_text()))


def test_host_base_path_and_scheme_become_the_server():
    assert converted()["servers"] == [{"url": "https://petstore.example.com/v2"}]


def test_body_parameters_become_a_request_body_with_rewritten_refs():
    op = converted()["paths"]["/pet"]["post"]
    assert op["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Pet"}
    assert "parameters" not in op or all(p["in"] != "body" for p in op["parameters"])


def test_path_parameters_get_a_schema():
    param = converted()["paths"]["/pet/{petId}"]["get"]["parameters"][0]
    assert param == {"in": "path", "name": "petId", "required": True, "schema": {"type": "integer", "format": "int64"}}


def test_form_data_becomes_multipart():
    body = converted()["paths"]["/pet/{petId}/uploadImage"]["post"]["requestBody"]["content"]
    schema = body["multipart/form-data"]["schema"]
    assert schema["properties"]["file"] == {"type": "string", "format": "binary"}


def test_responses_and_definitions_and_security_move_to_openapi_3():
    doc = converted()
    assert doc["openapi"] == "3.1.0"
    assert "Pet" in doc["components"]["schemas"]
    assert doc["components"]["securitySchemes"]["key"] == {"type": "apiKey", "in": "header", "name": "api_key"}
    ok = doc["paths"]["/pet/{petId}"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Pet"}


def test_it_imports_end_to_end():
    from aisc_connectors.importers.openapi import import_openapi
    from aisc_connectors.model import operations

    result = import_openapi(FIXTURE.read_text())
    assert {o.operation_id for o in operations(result.document)} == {"addPet", "getPetById", "uploadFile"}
    assert result.auth_suggestion == {"scheme": "api_key", "in": "header", "name": "api_key"}
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_import_swagger2.py -v`
Expected: FAIL with `NotImplementedError: Task 7`.

- [ ] **Step 4: Implement**

`apps/connectors/aisc_connectors/importers/swagger2.py`:

```python
"""Swagger 2.0 into OpenAPI 3.1: the common subset real APIs use."""
from __future__ import annotations

import copy
import json

from aisc_connectors.model import HTTP_METHODS

_SCHEMA_KEYS = ("type", "format", "items", "enum", "default", "minimum", "maximum", "pattern")


def _refs(obj):
    text = json.dumps(obj).replace("#/definitions/", "#/components/schemas/").replace(
        "#/parameters/", "#/components/parameters/")
    return json.loads(text)


def _param_schema(param: dict) -> dict:
    schema = {k: param[k] for k in _SCHEMA_KEYS if k in param}
    if schema.get("type") == "file":
        return {"type": "string", "format": "binary"}
    return schema


def _operation(op: dict, consumes: list[str], produces: list[str]) -> dict:
    out = {k: v for k, v in op.items() if k not in ("parameters", "responses", "consumes", "produces")}
    consumes = op.get("consumes") or consumes or ["application/json"]
    produces = op.get("produces") or produces or ["application/json"]
    params, form = [], {}
    for param in op.get("parameters") or []:
        where = param.get("in")
        if where == "body":
            out["requestBody"] = {"required": bool(param.get("required")),
                                  "content": {consumes[0]: {"schema": param.get("schema", {})}}}
        elif where == "formData":
            form[param["name"]] = _param_schema(param)
        else:
            params.append({k: param[k] for k in ("in", "name", "required", "description") if k in param}
                          | {"schema": _param_schema(param)})
    if form:
        media = "multipart/form-data" if "multipart/form-data" in consumes else "application/x-www-form-urlencoded"
        out["requestBody"] = {"content": {media: {"schema": {"type": "object", "properties": form}}}}
    if params:
        out["parameters"] = params
    responses = {}
    for code, response in (op.get("responses") or {}).items():
        converted = {"description": response.get("description", "")}
        if "schema" in response:
            converted["content"] = {produces[0]: {"schema": response["schema"]}}
        responses[str(code)] = converted
    out["responses"] = responses
    return out


def _security(definitions: dict) -> dict:
    schemes = {}
    for name, d in definitions.items():
        if d.get("type") == "apiKey":
            schemes[name] = {"type": "apiKey", "in": d["in"], "name": d["name"]}
        elif d.get("type") == "basic":
            schemes[name] = {"type": "http", "scheme": "basic"}
        elif d.get("type") == "oauth2" and d.get("flow") == "application":
            schemes[name] = {"type": "oauth2", "flows": {"clientCredentials": {
                "tokenUrl": d.get("tokenUrl", ""), "scopes": d.get("scopes", {})}}}
    return schemes


def convert(doc: dict) -> dict:
    doc = copy.deepcopy(doc)
    scheme = (doc.get("schemes") or ["https"])[0]
    servers = [{"url": f"{scheme}://{doc['host']}{doc.get('basePath', '')}".rstrip("/")}] if doc.get("host") else []
    paths = {}
    for path, item in (doc.get("paths") or {}).items():
        shared = item.get("parameters") or []
        paths[path] = {}
        for method in HTTP_METHODS:
            if method in item:
                op = dict(item[method])
                op["parameters"] = shared + (op.get("parameters") or [])
                paths[path][method] = _operation(op, doc.get("consumes") or [], doc.get("produces") or [])
    out = {
        "openapi": "3.1.0",
        "info": doc.get("info") or {"title": "imported", "version": "1"},
        "servers": servers,
        "paths": paths,
        "components": {
            "schemas": doc.get("definitions") or {},
            "securitySchemes": _security(doc.get("securityDefinitions") or {}),
        },
    }
    return _refs(out)
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_import_swagger2.py tests/test_import_openapi.py -v`
Expected: all pass (`test_swagger_two_is_routed_to_the_converter` still monkeypatches `convert`, so it passes too).

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: Swagger 2.0 converted to OpenAPI 3.1"
```

---

### Task 8: One-operation builders: cURL, manual, and the LLM presets

**Files:**
- Create: `apps/connectors/aisc_connectors/importers/build.py`, `curl.py`, `manual.py`, `presets.py`
- Test: `apps/connectors/tests/test_import_curl.py`, `apps/connectors/tests/test_import_manual_and_presets.py`

**Interfaces:**
- Produces:
  - `build.one_operation(method, url, headers: dict[str, str], body: str | None, content_type: str | None, operation_id: str, summary: str = "", example_response: str | None = None) -> ImportResult`. It recognises `Authorization: Bearer x` (bearer, secret `token`), `Authorization: Basic b64` (basic, username + secret `password`), and headers named `x-api-key`, `api-key`, `apikey` (api_key header, secret `api_key`); those values go to `detected_secrets`, never into the document. Other headers go to `x-aisc-binding.static_headers` (except `content-type`, `content-length`, `host`, `accept-encoding`). Query parameters become optional query parameters with the value as `example`. A JSON body becomes an `application/json` request body with the parsed body as `example` and an inferred schema.
  - `build.infer_schema(value) -> dict`.
  - `build.merge(results: list[ImportResult]) -> ImportResult` (same server required; others dropped with a warning).
  - `curl.import_curl(command: str) -> ImportResult`.
  - `manual.import_manual(method: str, url: str, example_request: str | None, example_response: str | None, content_type: str | None = "application/json", operation_id: str = "call") -> ImportResult`.
  - `presets.openai(base_url, model="") / presets.ollama(base_url, model="") / presets.huggingface(model_url) -> ImportResult`, each with `chat_suggestion` = `{"operation_id", "input_mode": "messages" | "text", "input_field", "answer_path", "extra_body"}`.

- [ ] **Step 1: Write the failing tests**

`apps/connectors/tests/test_import_curl.py`:

```python
def test_a_json_post_becomes_one_operation():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    result = import_curl(
        "curl -s -X POST https://api.acme.test/v1/chat?lang=en "
        "-H 'Content-Type: application/json' -H 'X-Tenant: 42' "
        "-H 'Authorization: Bearer sk-secret-123' -d '{\"question\": \"hi\"}'"
    )
    op = operations(result.document)[0]
    assert result.document["servers"] == [{"url": "https://api.acme.test"}]
    assert (op.method, op.path, op.operation_id) == ("post", "/v1/chat", "post_v1_chat")
    assert op.binding["static_headers"] == {"X-Tenant": "42"}
    assert op.spec["requestBody"]["content"]["application/json"]["example"] == {"question": "hi"}
    assert op.spec["parameters"] == [{"in": "query", "name": "lang", "required": False,
                                      "schema": {"type": "string"}, "example": "en"}]
    assert result.auth_suggestion == {"scheme": "bearer"}
    assert result.detected_secrets == {"token": "sk-secret-123"}
    assert "sk-secret-123" not in str(result.document)


def test_data_without_method_is_a_form_post():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    op = operations(import_curl("curl https://h.test/login --data 'a=1&b=2'").document)[0]
    assert op.method == "post"
    assert "application/x-www-form-urlencoded" in op.spec["requestBody"]["content"]


def test_user_flag_is_basic_auth():
    from aisc_connectors.importers.curl import import_curl

    result = import_curl("curl -u svc:pa55 https://h.test/x")
    assert result.auth_suggestion == {"scheme": "basic", "username": "svc"}
    assert result.detected_secrets == {"password": "pa55"}


def test_api_key_headers_are_recognised():
    from aisc_connectors.importers.curl import import_curl

    result = import_curl("curl https://h.test/x -H 'x-api-key: abc'")
    assert result.auth_suggestion == {"scheme": "api_key", "in": "header", "name": "x-api-key"}
    assert result.detected_secrets == {"api_key": "abc"}


def test_json_flag_and_line_continuations():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    op = operations(import_curl("curl https://h.test/x \\\n  --json '{\"a\": 1}'").document)[0]
    assert op.method == "post"
    assert op.spec["requestBody"]["content"]["application/json"]["schema"] == {
        "type": "object", "properties": {"a": {"type": "integer"}}}


def test_not_a_curl_command_is_refused():
    import pytest

    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.importers.errors import ImportFailed

    with pytest.raises(ImportFailed):
        import_curl("wget https://h.test")
```

`apps/connectors/tests/test_import_manual_and_presets.py`:

```python
def test_manual_builds_an_operation_with_a_response_schema():
    from aisc_connectors.importers.manual import import_manual
    from aisc_connectors.model import operations

    result = import_manual("POST", "http://172.17.0.1:8500/score", '{"amount_eur": 2500}',
                           '{"recommendation": "Approve", "score": 812}', operation_id="score")
    op = operations(result.document)[0]
    assert op.operation_id == "score"
    schema = op.spec["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["properties"]["score"] == {"type": "integer"}


def test_the_openai_preset_suggests_a_chat_mapping():
    from aisc_connectors.importers.presets import openai
    from aisc_connectors.model import operations

    result = openai("https://llm.acme.test/v1", model="acme-7b")
    ids = {o.operation_id for o in operations(result.document)}
    assert ids == {"chat_completions", "list_models"}
    assert result.document["servers"] == [{"url": "https://llm.acme.test/v1"}]
    assert result.chat_suggestion == {"operation_id": "chat_completions", "input_mode": "messages",
                                      "input_field": "messages", "answer_path": "choices[0].message.content",
                                      "extra_body": {"model": "acme-7b"}}
    assert result.auth_suggestion == {"scheme": "bearer"}


def test_the_ollama_and_huggingface_presets():
    from aisc_connectors.importers.presets import huggingface, ollama

    o = ollama("http://gpu.acme.test:11434", model="llama3.1")
    assert o.chat_suggestion["answer_path"] == "message.content"
    assert o.chat_suggestion["extra_body"] == {"model": "llama3.1", "stream": False}
    h = huggingface("https://api-inference.huggingface.co/models/acme/model")
    assert h.chat_suggestion["input_mode"] == "text"
    assert h.chat_suggestion["answer_path"] == "[0].generated_text"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/connectors && uv run pytest tests/test_import_curl.py tests/test_import_manual_and_presets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.importers.curl'`.

- [ ] **Step 3: Implement the builder**

`apps/connectors/aisc_connectors/importers/build.py`:

```python
"""A canonical document with one operation, from what a person can paste (spec D3)."""
from __future__ import annotations

import base64
import json
import re
from collections import Counter
from urllib.parse import parse_qsl, urlsplit

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.errors import ImportFailed

_DROP_HEADERS = {"content-type", "content-length", "host", "accept-encoding"}
_KEY_HEADERS = {"x-api-key", "api-key", "apikey"}


def infer_schema(value) -> dict:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array", "items": infer_schema(value[0]) if value else {}}
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: infer_schema(v) for k, v in value.items()}}
    return {}


def _content(body: str, content_type: str) -> dict:
    if "json" in content_type:
        try:
            example = json.loads(body)
        except ValueError as exc:
            raise ImportFailed("the body says it is JSON but does not parse") from exc
        return {content_type: {"schema": infer_schema(example), "example": example}}
    if content_type == "application/x-www-form-urlencoded":
        fields = dict(parse_qsl(body, keep_blank_values=True))
        return {content_type: {"schema": {"type": "object", "properties": {k: {"type": "string"} for k in fields}},
                               "example": fields}}
    return {content_type: {"schema": {"type": "string"}, "example": body}}


def one_operation(method: str, url: str, headers: dict[str, str], body: str | None, content_type: str | None,
                  operation_id: str, summary: str = "", example_response: str | None = None) -> ImportResult:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ImportFailed(f"{url!r} is not an http(s) URL")
    method = method.lower()
    auth, secrets, static = None, {}, {}
    for name, value in headers.items():
        low = name.lower()
        if low == "authorization" and value.lower().startswith("bearer "):
            auth, secrets["token"] = {"scheme": "bearer"}, value[7:].strip()
        elif low == "authorization" and value.lower().startswith("basic "):
            user, _, password = base64.b64decode(value[6:].strip()).decode().partition(":")
            auth, secrets["password"] = {"scheme": "basic", "username": user}, password
        elif low in _KEY_HEADERS:
            auth, secrets["api_key"] = {"scheme": "api_key", "in": "header", "name": name}, value
        elif low == "content-type":
            content_type = content_type or value.split(";")[0].strip()
        elif low not in _DROP_HEADERS:
            static[name] = value
    op: dict = {"operationId": operation_id, "summary": summary,
                "x-aisc-binding": {"protocol": "http", "method": method, "path": parts.path or "/",
                                   "static_headers": static},
                "responses": {"200": {"description": "the answer"}}}
    query = parse_qsl(parts.query, keep_blank_values=True)
    if query:
        op["parameters"] = [{"in": "query", "name": k, "required": False, "schema": {"type": "string"}, "example": v}
                            for k, v in query]
    if body is not None:
        op["requestBody"] = {"content": _content(body, content_type or "application/json")}
    if example_response:
        try:
            parsed = json.loads(example_response)
            op["responses"]["200"]["content"] = {"application/json": {"schema": infer_schema(parsed),
                                                                      "example": parsed}}
        except ValueError:
            op["responses"]["200"]["content"] = {"text/plain": {"schema": {"type": "string"}}}
    document = {"openapi": "3.1.0", "info": {"title": parts.netloc, "version": "1"},
                "servers": [{"url": f"{parts.scheme}://{parts.netloc}"}], "paths": {parts.path or "/": {method: op}}}
    return ImportResult(document=document, auth_suggestion=auth, detected_secrets=secrets)


def synth_id(method: str, url: str) -> str:
    path = urlsplit(url).path
    return method.lower() + "_" + (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root")


def merge(results: list[ImportResult]) -> ImportResult:
    if not results:
        raise ImportFailed("nothing to import")
    servers = Counter(r.document["servers"][0]["url"] for r in results)
    server = servers.most_common(1)[0][0]
    merged = {**results[0].document, "servers": [{"url": server}], "paths": {}}
    out = ImportResult(document=merged)
    used: set[str] = set()
    for result in results:
        if result.document["servers"][0]["url"] != server:
            out.warnings.append(f"skipped a request to {result.document['servers'][0]['url']}: "
                                f"a connector talks to one server ({server})")
            continue
        for path, item in result.document["paths"].items():
            for method, op in item.items():
                while op["operationId"] in used:
                    op["operationId"] += "_"
                used.add(op["operationId"])
                merged["paths"].setdefault(path, {})[method] = op
        out.auth_suggestion = out.auth_suggestion or result.auth_suggestion
        out.detected_secrets.update(result.detected_secrets)
        out.warnings.extend(result.warnings)
    return out
```

- [ ] **Step 4: Implement cURL, manual and presets**

`apps/connectors/aisc_connectors/importers/curl.py`:

```python
"""A pasted cURL command into one operation."""
from __future__ import annotations

import base64
import shlex

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.build import one_operation, synth_id
from aisc_connectors.importers.errors import ImportFailed

_DATA = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}


def import_curl(command: str) -> ImportResult:
    try:
        words = shlex.split(command.replace("\\\n", " "))
    except ValueError as exc:
        raise ImportFailed(f"the command does not parse: {exc}") from exc
    if not words or words[0] != "curl":
        raise ImportFailed("paste a command that starts with curl")
    method, url, headers, body, content_type = None, None, {}, None, None
    i = 1
    while i < len(words):
        word = words[i]
        value = words[i + 1] if i + 1 < len(words) else None
        if word in ("-X", "--request"):
            method, i = value, i + 2
        elif word in ("-H", "--header"):
            name, _, header_value = (value or "").partition(":")
            headers[name.strip()] = header_value.strip()
            i += 2
        elif word in _DATA:
            body, i = value, i + 2
            content_type = content_type or "application/x-www-form-urlencoded"
        elif word == "--json":
            body, content_type, i = value, "application/json", i + 2
        elif word in ("-u", "--user"):
            headers["Authorization"] = "Basic " + base64.b64encode((value or "").encode()).decode()
            i += 2
        elif word == "--url":
            url, i = value, i + 2
        elif word.startswith("-"):
            i += 1  # flags without meaning here: -s, -v, -L, -k, --compressed ...
        else:
            url, i = word, i + 1
    if not url:
        raise ImportFailed("the command has no URL")
    method = method or ("POST" if body is not None else "GET")
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), content_type)
    return one_operation(method, url, headers, body, content_type, synth_id(method, url))
```

`apps/connectors/aisc_connectors/importers/manual.py`:

```python
"""A guided form: method, URL, an example request and an example answer."""
from __future__ import annotations

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.build import one_operation


def import_manual(method: str, url: str, example_request: str | None, example_response: str | None,
                  content_type: str | None = "application/json", operation_id: str = "call") -> ImportResult:
    return one_operation(method, url, {}, example_request, content_type if example_request else None,
                         operation_id, example_response=example_response)
```

`apps/connectors/aisc_connectors/importers/presets.py`:

```python
"""Ready-made connectors for the LLM APIs most systems expose, with a chat mapping."""
from __future__ import annotations

from aisc_connectors.importers import ImportResult


def _doc(base_url: str, title: str, paths: dict) -> dict:
    return {"openapi": "3.1.0", "info": {"title": title, "version": "1"},
            "servers": [{"url": base_url.rstrip("/")}], "paths": paths}


def _op(op_id: str, method: str, path: str, summary: str, body_schema: dict | None = None) -> dict:
    op = {"operationId": op_id, "summary": summary, "responses": {"200": {"description": "ok"}},
          "x-aisc-binding": {"protocol": "http", "method": method, "path": path, "static_headers": {}}}
    if body_schema:
        op["requestBody"] = {"content": {"application/json": {"schema": body_schema}}}
    return op


_MESSAGES = {"type": "object", "properties": {"model": {"type": "string"}, "messages": {"type": "array", "items": {
    "type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}}}}


def openai(base_url: str, model: str = "") -> ImportResult:
    doc = _doc(base_url, "OpenAI-compatible", {
        "/chat/completions": {"post": _op("chat_completions", "post", "/chat/completions", "Chat", _MESSAGES)},
        "/models": {"get": _op("list_models", "get", "/models", "Models")},
    })
    return ImportResult(document=doc, auth_suggestion={"scheme": "bearer"}, chat_suggestion={
        "operation_id": "chat_completions", "input_mode": "messages", "input_field": "messages",
        "answer_path": "choices[0].message.content", "extra_body": {"model": model}})


def ollama(base_url: str, model: str = "") -> ImportResult:
    doc = _doc(base_url, "Ollama", {"/api/chat": {"post": _op("chat", "post", "/api/chat", "Chat", _MESSAGES)}})
    return ImportResult(document=doc, chat_suggestion={
        "operation_id": "chat", "input_mode": "messages", "input_field": "messages",
        "answer_path": "message.content", "extra_body": {"model": model, "stream": False}})


def huggingface(model_url: str) -> ImportResult:
    schema = {"type": "object", "properties": {"inputs": {"type": "string"}}}
    doc = _doc(model_url, "Hugging Face Inference", {"/": {"post": _op("infer", "post", "/", "Inference", schema)}})
    return ImportResult(document=doc, auth_suggestion={"scheme": "bearer"}, chat_suggestion={
        "operation_id": "infer", "input_mode": "text", "input_field": "inputs",
        "answer_path": "[0].generated_text", "extra_body": {}})
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_import_curl.py tests/test_import_manual_and_presets.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: cURL, manual and LLM presets as one-operation documents"
```

---

### Task 9: Postman collection v2.1

**Files:**
- Create: `apps/connectors/aisc_connectors/importers/postman.py`
- Create: `apps/connectors/tests/fixtures/postman_collection.json`
- Test: `apps/connectors/tests/test_import_postman.py`

**Interfaces:**
- Consumes: `build.one_operation`, `build.merge`.
- Produces: `postman.import_postman(text: str) -> ImportResult`.

- [ ] **Step 1: Write the fixture**

`apps/connectors/tests/fixtures/postman_collection.json`:

```json
{
  "info": {"name": "Acme", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
  "variable": [{"key": "baseUrl", "value": "https://api.acme.test"}],
  "item": [
    {"name": "Score applicant", "request": {"method": "POST", "url": {"raw": "{{baseUrl}}/score"},
      "header": [{"key": "Content-Type", "value": "application/json"}],
      "body": {"mode": "raw", "raw": "{\"amount\": 100}"}}},
    {"name": "Folder", "item": [
      {"name": "Health", "request": {"method": "GET", "url": "{{baseUrl}}/health"}},
      {"name": "Elsewhere", "request": {"method": "GET", "url": "https://other.test/x"}}
    ]}
  ]
}
```

- [ ] **Step 2: Write the failing test**

`apps/connectors/tests/test_import_postman.py`:

```python
import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "postman_collection.json"


def test_requests_in_folders_become_operations_on_one_server():
    from aisc_connectors.importers.postman import import_postman
    from aisc_connectors.model import operations

    result = import_postman(FIXTURE.read_text())
    ops = {o.operation_id: o for o in operations(result.document)}
    assert set(ops) == {"score_applicant", "health"}
    assert result.document["servers"] == [{"url": "https://api.acme.test"}]
    assert ops["score_applicant"].spec["requestBody"]["content"]["application/json"]["example"] == {"amount": 100}
    assert any("other.test" in w for w in result.warnings)


def test_unresolved_variables_are_named():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.postman import import_postman

    collection = json.loads(FIXTURE.read_text())
    collection["variable"] = []
    with pytest.raises(ImportFailed, match="baseUrl"):
        import_postman(json.dumps(collection))


def test_bearer_auth_is_detected():
    from aisc_connectors.importers.postman import import_postman

    collection = {"info": {"name": "x"}, "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "tkn"}]},
                  "item": [{"name": "Ping", "request": {"method": "GET", "url": "https://h.test/ping"}}]}
    result = import_postman(json.dumps(collection))
    assert result.auth_suggestion == {"scheme": "bearer"}
    assert result.detected_secrets == {"token": "tkn"}
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_import_postman.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.importers.postman'`.

- [ ] **Step 4: Implement**

`apps/connectors/aisc_connectors/importers/postman.py`:

```python
"""A Postman collection (v2.1) into one operation per request."""
from __future__ import annotations

import json
import re

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.build import merge, one_operation
from aisc_connectors.importers.errors import ImportFailed

_VAR = re.compile(r"\{\{([^}]+)\}\}")


def _requests(items: list, trail: str = ""):
    for item in items:
        if "item" in item:
            yield from _requests(item["item"], trail + item.get("name", "") + " ")
        elif "request" in item:
            yield item.get("name") or trail.strip() or "request", item["request"]


def _auth_header(auth: dict | None) -> dict[str, str]:
    if not auth:
        return {}
    values = {entry["key"]: entry.get("value", "") for entry in auth.get(auth.get("type"), []) or []}
    if auth.get("type") == "bearer":
        return {"Authorization": f"Bearer {values.get('token', '')}"}
    if auth.get("type") == "apikey" and values.get("in", "header") == "header":
        return {values.get("key", "x-api-key"): values.get("value", "")}
    return {}


def import_postman(text: str) -> ImportResult:
    try:
        collection = json.loads(text)
    except ValueError as exc:
        raise ImportFailed("this is not a Postman collection (JSON)") from exc
    variables = {v["key"]: v.get("value", "") for v in collection.get("variable") or []}

    def resolve(value: str) -> str:
        missing = [m for m in _VAR.findall(value) if m not in variables]
        if missing:
            raise ImportFailed(f"the collection uses variables it does not define: {sorted(set(missing))}")
        return _VAR.sub(lambda m: str(variables[m.group(1)]), value)

    results = []
    for name, request in _requests(collection.get("item") or []):
        url = request["url"]["raw"] if isinstance(request.get("url"), dict) else request.get("url", "")
        headers = {h["key"]: resolve(h.get("value", "")) for h in request.get("header") or [] if not h.get("disabled")}
        headers.update(_auth_header(request.get("auth") or collection.get("auth")))
        body, content_type = None, None
        raw_body = request.get("body") or {}
        if raw_body.get("mode") == "raw":
            body = resolve(raw_body.get("raw", ""))
        elif raw_body.get("mode") == "urlencoded":
            body = "&".join(f"{p['key']}={p.get('value', '')}" for p in raw_body["urlencoded"])
            content_type = "application/x-www-form-urlencoded"
        op_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "request"
        results.append(one_operation(request.get("method", "GET"), resolve(url), headers, body, content_type,
                                     op_id, summary=name))
    return merge(results)
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_import_postman.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: Postman collections"
```

---

### Task 10: SOAP from a WSDL

**Files:**
- Create: `apps/connectors/aisc_connectors/importers/wsdl.py`
- Create: `apps/connectors/tests/fixtures/calc.wsdl`
- Test: `apps/connectors/tests/test_import_wsdl.py`

**Interfaces:**
- Produces: `wsdl.import_wsdl(text: str) -> ImportResult`. Each SOAP operation becomes `POST /soap/{Operation}` with a JSON request-body schema built from the input message; binding `{"protocol": "soap", "operation": name, "binding": "{ns}BindingName"}`; the WSDL text is kept at document level under `x-aisc-wsdl` (stripped from the unified view); the server is the port's `soap:address`.

- [ ] **Step 1: Write the fixture**

`apps/connectors/tests/fixtures/calc.wsdl`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"
             xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
             xmlns:tns="http://example.org/calc"
             xmlns:xsd="http://www.w3.org/2001/XMLSchema"
             targetNamespace="http://example.org/calc" name="Calc">
  <types>
    <xsd:schema targetNamespace="http://example.org/calc" elementFormDefault="qualified">
      <xsd:element name="Add">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="a" type="xsd:int"/>
          <xsd:element name="b" type="xsd:int"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="AddResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="result" type="xsd:int"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
    </xsd:schema>
  </types>
  <message name="AddIn"><part name="parameters" element="tns:Add"/></message>
  <message name="AddOut"><part name="parameters" element="tns:AddResponse"/></message>
  <portType name="CalcPort">
    <operation name="Add"><input message="tns:AddIn"/><output message="tns:AddOut"/></operation>
  </portType>
  <binding name="CalcBinding" type="tns:CalcPort">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <operation name="Add">
      <soap:operation soapAction="http://example.org/calc/Add"/>
      <input><soap:body use="literal"/></input>
      <output><soap:body use="literal"/></output>
    </operation>
  </binding>
  <service name="CalcService">
    <port name="CalcPortSoap" binding="tns:CalcBinding">
      <soap:address location="http://soap.test:8080/calc"/>
    </port>
  </service>
</definitions>
```

- [ ] **Step 2: Write the failing test**

`apps/connectors/tests/test_import_wsdl.py`:

```python
import pathlib

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "calc.wsdl"


def test_each_soap_operation_becomes_a_json_operation():
    from aisc_connectors.importers.wsdl import import_wsdl
    from aisc_connectors.model import operations

    result = import_wsdl(FIXTURE.read_text())
    (op,) = operations(result.document)
    assert (op.operation_id, op.method, op.path) == ("Add", "post", "/soap/Add")
    assert op.binding == {"protocol": "soap", "operation": "Add", "binding": "{http://example.org/calc}CalcBinding"}
    assert op.spec["requestBody"]["content"]["application/json"]["schema"] == {
        "type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}
    assert result.document["servers"] == [{"url": "http://soap.test:8080/calc"}]
    assert result.document["x-aisc-wsdl"].startswith("<?xml")
    assert op.changes_data is True


def test_a_broken_wsdl_is_refused():
    import pytest

    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.wsdl import import_wsdl

    with pytest.raises(ImportFailed):
        import_wsdl("<definitions>")
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_import_wsdl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.importers.wsdl'`.

- [ ] **Step 4: Implement**

`apps/connectors/aisc_connectors/importers/wsdl.py`:

```python
"""SOAP: a WSDL into JSON operations; the gateway builds the XML envelope (spec D3)."""
from __future__ import annotations

import hashlib
import pathlib
import tempfile

import zeep

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.errors import ImportFailed

_XSD_TO_JSON = {"int": "integer", "integer": "integer", "long": "integer", "short": "integer",
                "decimal": "number", "double": "number", "float": "number",
                "boolean": "boolean", "string": "string", "date": "string", "dateTime": "string"}


def _schema(xsd_type, depth: int = 0) -> dict:
    elements = getattr(xsd_type, "elements", None)
    if elements and depth < 4:
        return {"type": "object",
                "properties": {name: _schema(element.type, depth + 1) for name, element in elements}}
    name = getattr(xsd_type, "name", None) or ""
    return {"type": _XSD_TO_JSON.get(name, "string")}


def wsdl_file(text: str) -> str:
    """zeep reads WSDL from a path; the same text always lands on the same file."""
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    path = pathlib.Path(tempfile.gettempdir()) / f"aisc-connector-{digest}.wsdl"
    if not path.exists():
        path.write_text(text)
    return str(path)


def import_wsdl(text: str) -> ImportResult:
    try:
        client = zeep.Client(wsdl_file(text))
    except Exception as exc:  # zeep raises XML, transport and schema errors alike
        raise ImportFailed(f"the WSDL could not be read: {exc}") from exc
    paths, warnings, address = {}, [], None
    for service in client.wsdl.services.values():
        for port in service.ports.values():
            port_address = port.binding_options.get("address")
            if address is None:
                address = port_address
            elif port_address != address:
                warnings.append(f"skipped port {port.name} at {port_address}: a connector talks to one server")
                continue
            for name, operation in port.binding._operations.items():
                body = getattr(operation.input, "body", None)
                schema = _schema(body.type) if body is not None else {"type": "object"}
                paths[f"/soap/{name}"] = {"post": {
                    "operationId": name, "summary": f"SOAP {name}",
                    "requestBody": {"content": {"application/json": {"schema": schema}}},
                    "responses": {"200": {"description": "the SOAP answer, as JSON"}},
                    "x-aisc-binding": {"protocol": "soap", "operation": name, "binding": str(port.binding.name)},
                }}
    if not address:
        raise ImportFailed("the WSDL names no soap:address")
    document = {"openapi": "3.1.0", "info": {"title": "SOAP service", "version": "1"},
                "servers": [{"url": address}], "paths": paths, "x-aisc-wsdl": text}
    return ImportResult(document=document, warnings=warnings)
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_import_wsdl.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: SOAP services from a WSDL"
```

---

### Task 11: GraphQL from introspection

**Files:**
- Create: `apps/connectors/aisc_connectors/importers/graphql.py`
- Test: `apps/connectors/tests/test_import_graphql.py`

**Interfaces:**
- Produces: `graphql.import_graphql(endpoint: str, headers: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None) -> ImportResult`; `graphql.from_introspection(endpoint: str, introspection: dict) -> ImportResult`. Each root field becomes `POST /graphql/{field}` whose JSON body is the variables object; binding `{"protocol": "graphql", "endpoint_path": "/graphql", "document": "...", "root": "query" | "mutation", "field": name}`. Fields with required arguments that cannot be expressed are still included (their arguments become variables).

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_import_graphql.py`:

```python
import httpx
import respx
from graphql import build_schema, get_introspection_query, graphql_sync

SDL = """
type Query { applicant(id: ID!): Applicant  health: String }
type Mutation { score(amount: Int!, market: String): Decision }
type Applicant { id: ID! name: String decisions: [Decision] }
type Decision { recommendation: String score: Int }
"""


def introspection():
    return graphql_sync(build_schema(SDL), get_introspection_query()).data


def test_root_fields_become_operations_with_variables_as_body():
    from aisc_connectors.importers.graphql import from_introspection
    from aisc_connectors.model import operations

    result = from_introspection("https://api.acme.test/graphql", introspection())
    ops = {o.operation_id: o for o in operations(result.document)}
    assert set(ops) == {"query_applicant", "query_health", "mutation_score"}
    assert result.document["servers"] == [{"url": "https://api.acme.test"}]
    score = ops["mutation_score"]
    assert score.path == "/graphql/score"
    assert score.changes_data is True
    assert ops["query_health"].changes_data is True  # every GraphQL call is a POST
    assert score.binding["root"] == "mutation"
    assert score.binding["document"] == (
        "mutation score($amount: Int!, $market: String) { score(amount: $amount, market: $market) "
        "{ recommendation score } }")
    body = score.spec["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["amount"]


def test_nested_selections_stop_at_depth_two():
    from aisc_connectors.importers.graphql import from_introspection
    from aisc_connectors.model import find

    doc = from_introspection("https://h.test/graphql", introspection()).document
    assert "decisions { recommendation score }" in find(doc, "query_applicant").binding["document"]


@respx.mock
def test_it_asks_the_endpoint_itself():
    from aisc_connectors.importers.graphql import import_graphql

    respx.post("https://h.test/graphql").mock(return_value=httpx.Response(200, json={"data": introspection()}))
    assert len(import_graphql("https://h.test/graphql").document["paths"]) == 3
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_import_graphql.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.importers.graphql'`.

- [ ] **Step 3: Implement**

`apps/connectors/aisc_connectors/importers/graphql.py`:

```python
"""GraphQL: one fixed-document operation per root field, variables as the JSON body (spec D3)."""
from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from graphql import (build_client_schema, get_introspection_query, get_named_type, is_enum_type,
                     is_non_null_type, is_scalar_type)

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.errors import ImportFailed

_SCALARS = {"Int": "integer", "Float": "number", "Boolean": "boolean"}


def _selection(gql_type, depth: int) -> str | None:
    named = get_named_type(gql_type)
    if is_scalar_type(named) or is_enum_type(named):
        return ""
    if depth == 0:
        return None
    parts = []
    for name, field in named.fields.items():
        if any(is_non_null_type(a.type) for a in field.args.values()):
            continue
        sub = _selection(field.type, depth - 1)
        if sub == "":
            parts.append(name)
        elif sub:
            parts.append(f"{name} {sub}")
    return "{ " + " ".join(parts) + " }" if parts else None


def _json_type(gql_type) -> dict:
    return {"type": _SCALARS.get(get_named_type(gql_type).name, "string")}


def from_introspection(endpoint: str, introspection: dict) -> ImportResult:
    try:
        schema = build_client_schema(introspection)
    except Exception as exc:
        raise ImportFailed(f"the introspection result is not a GraphQL schema: {exc}") from exc
    parts = urlsplit(endpoint)
    paths = {}
    for root, root_type in (("query", schema.query_type), ("mutation", schema.mutation_type)):
        if root_type is None:
            continue
        for name, field in root_type.fields.items():
            args = field.args
            var_defs = ", ".join(f"${a}: {arg.type}" for a, arg in args.items())
            call_args = ", ".join(f"{a}: ${a}" for a in args)
            selection = _selection(field.type, 2)
            document = (f"{root} {name}" + (f"({var_defs})" if var_defs else "") + " { " + name
                        + (f"({call_args})" if call_args else "") + (f" {selection}" if selection else "") + " }")
            body = {"type": "object", "properties": {a: _json_type(arg.type) for a, arg in args.items()}}
            required = [a for a, arg in args.items() if is_non_null_type(arg.type)]
            if required:
                body["required"] = required
            paths[f"/graphql/{name}"] = {"post": {
                "operationId": f"{root}_{name}", "summary": field.description or f"GraphQL {root} {name}",
                "requestBody": {"content": {"application/json": {"schema": body}}},
                "responses": {"200": {"description": f"data.{name}"}},
                "x-aisc-binding": {"protocol": "graphql", "endpoint_path": parts.path or "/", "document": document,
                                   "root": root, "field": name},
            }}
    document = {"openapi": "3.1.0", "info": {"title": "GraphQL API", "version": "1"},
                "servers": [{"url": f"{parts.scheme}://{parts.netloc}"}], "paths": paths}
    return ImportResult(document=document)


def import_graphql(endpoint: str, headers: dict[str, str] | None = None,
                   transport: httpx.BaseTransport | None = None) -> ImportResult:
    try:
        with httpx.Client(timeout=20, transport=transport) as client:
            response = client.post(endpoint, json={"query": get_introspection_query()}, headers=headers or {})
        data = response.json().get("data")
    except (httpx.HTTPError, ValueError) as exc:
        raise ImportFailed(f"could not introspect {endpoint}: {exc}") from exc
    if not data:
        raise ImportFailed(f"{endpoint} did not answer the introspection query (is introspection disabled?)")
    return from_introspection(endpoint, data)
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_import_graphql.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: GraphQL APIs from introspection"
```

---

### Task 12: Import through the API; operation policies, links, patterns and the chat mapping

**Files:**
- Modify: `apps/connectors/aisc_connectors/importers/__init__.py` (add `import_source`)
- Modify: `apps/connectors/aisc_connectors/store.py` (policies)
- Modify: `apps/connectors/aisc_connectors/routes_admin.py` (import, operations, chat routes)
- Test: `apps/connectors/tests/test_admin_import_and_policies.py`

**Interfaces:**
- Consumes: every importer; `model.operations`; `store`; `engine_for`.
- Produces:
  - `importers.KINDS` = `("openapi", "curl", "postman", "manual", "wsdl", "graphql", "openai", "ollama", "huggingface")`; `importers.import_source(kind: str, payload: dict) -> ImportResult` where payload keys are: openapi `{url?|text?, base_url?}`; curl `{text}`; postman `{text}`; manual `{method, url, example_request?, example_response?, content_type?, operation_id?}`; wsdl `{url?|text?}`; graphql `{url}`; openai/ollama `{url, model?}`; huggingface `{url}`.
  - `store.sync_policies(connector_pid, ops: list[Operation]) -> None` (new ops denied, vanished ops removed, kept ops keep their decisions), `store.policies(connector_pid) -> dict[str, dict]`, `store.update_policy(connector_pid, operation_id, **fields) -> dict`.
  - Routes: `POST /api/v1/connectors/{cid}/import` `{kind, ...payload}` -> `{operations, warnings, auth, detected_secrets: [names], chat}` (detected secret VALUES are stored straight into the vault, only their names are returned); `GET /api/v1/connectors/{cid}/operations` -> list of `{operation_id, method, path, summary, changes_data, allowed, changes_data_confirmed, patterns, component_pids}`; `PATCH /api/v1/connectors/{cid}/operations/{operation_id}` `{allowed?, confirm_changes_data?, confirm_production?, patterns?, component_pids?}`; `PUT /api/v1/connectors/{cid}/chat` `{operation_id, input_mode, input_field, answer_path, extra_body}`; `PUT /api/v1/connectors/{cid}/server` `{url}` (replaces the document's one server; needed when a spec or WSDL names an address that is not reachable as written).
  - Pattern shapes validated here and used by Task 14: `session: {id_path: str (JMESPath), inject_in: "body"|"header"|"query", inject_name: str}`; `async: {status_from: "header:<Name>" | "body:<JMESPath>", done_when: str (JMESPath), result_path: str | null, interval_s: 1..60, timeout_s: 1..600}`; `stream: {format: "sse"|"ndjson", delta_path: str (JMESPath), done_marker: str | null}`.

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_admin_import_and_policies.py`:

```python
import pathlib

import pytest
from fastapi.testclient import TestClient

from tests.test_admin_connectors import FakeEngine

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def api(db, auth_on, engine):
    from aisc_connectors import routes_admin
    from aisc_connectors.app import app

    app.dependency_overrides[routes_admin.engine_for] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def mcas(api, as_user, engine):
    cid = api.post("/api/v1/connectors", headers=as_user(),
                   json={"project_pid": str(engine.project), "name": "MCAS"}).json()["pid"]
    imported = api.post(f"/api/v1/connectors/{cid}/import", headers=as_user(),
                        json={"kind": "openapi", "text": (FIXTURES / "mcas_openapi.json").read_text(),
                              "base_url": "http://172.17.0.1:8500"})
    assert imported.status_code == 200, imported.text
    return cid


def ops(api, as_user, cid):
    return {o["operation_id"]: o for o in api.get(f"/api/v1/connectors/{cid}/operations", headers=as_user()).json()}


def test_imported_operations_start_denied(api, as_user, mcas):
    listed = ops(api, as_user, mcas)
    assert len(listed) == 10
    assert not any(o["allowed"] for o in listed.values())


def test_allowing_an_operation_that_changes_data_needs_confirmation(api, as_user, mcas):
    chat = next(o for o in ops(api, as_user, mcas).values() if o["path"] == "/chat")
    url = f"/api/v1/connectors/{mcas}/operations/{chat['operation_id']}"
    assert api.patch(url, headers=as_user(), json={"allowed": True}).status_code == 409
    ok = api.patch(url, headers=as_user(), json={"allowed": True, "confirm_changes_data": True})
    assert ok.json()["allowed"] is True


def test_production_connectors_need_a_second_confirmation(api, as_user, mcas):
    api.patch(f"/api/v1/connectors/{mcas}", headers=as_user(), json={"environment": "production"})
    health = next(o for o in ops(api, as_user, mcas).values() if o["path"] == "/health")
    url = f"/api/v1/connectors/{mcas}/operations/{health['operation_id']}"
    assert api.patch(url, headers=as_user(), json={"allowed": True}).status_code == 409
    assert api.patch(url, headers=as_user(), json={"allowed": True, "confirm_production": True}).status_code == 200


def test_reimport_keeps_decisions_for_operations_that_still_exist(api, as_user, mcas):
    health = next(o for o in ops(api, as_user, mcas).values() if o["path"] == "/health")
    api.patch(f"/api/v1/connectors/{mcas}/operations/{health['operation_id']}", headers=as_user(),
              json={"allowed": True})
    api.post(f"/api/v1/connectors/{mcas}/import", headers=as_user(),
             json={"kind": "openapi", "text": (FIXTURES / "mcas_openapi.json").read_text(),
                   "base_url": "http://172.17.0.1:8500"})
    assert ops(api, as_user, mcas)[health["operation_id"]]["allowed"] is True


def test_component_links_must_be_components_of_the_ai_system(api, as_user, mcas, engine):
    health = next(o for o in ops(api, as_user, mcas).values() if o["path"] == "/health")
    url = f"/api/v1/connectors/{mcas}/operations/{health['operation_id']}"
    assert api.patch(url, headers=as_user(), json={"component_pids": ["00000000-0000-0000-0000-000000000000"]}
                     ).status_code == 422
    linked = api.patch(url, headers=as_user(), json={"component_pids": [str(engine.components[0])]})
    assert linked.json()["component_pids"] == [str(engine.components[0])]


def test_patterns_are_validated(api, as_user, mcas):
    chat = next(o for o in ops(api, as_user, mcas).values() if o["path"] == "/chat")
    url = f"/api/v1/connectors/{mcas}/operations/{chat['operation_id']}"
    bad = api.patch(url, headers=as_user(), json={"patterns": {"stream": {"format": "xml", "delta_path": "a"}}})
    assert bad.status_code == 422
    good = api.patch(url, headers=as_user(), json={"patterns": {"session": {
        "id_path": "request_id", "inject_in": "body", "inject_name": "request_id"}}})
    assert good.status_code == 200


def test_curl_secrets_go_to_the_vault_not_the_answer(api, as_user, engine):
    cid = api.post("/api/v1/connectors", headers=as_user(),
                   json={"project_pid": str(engine.project), "name": "Curl"}).json()["pid"]
    answer = api.post(f"/api/v1/connectors/{cid}/import", headers=as_user(),
                      json={"kind": "curl", "text": "curl https://h.test/x -H 'Authorization: Bearer s3cr3t-value'"})
    assert "s3cr3t-value" not in answer.text
    assert answer.json()["detected_secrets"] == ["token"]
    assert answer.json()["auth"] == {"scheme": "bearer"}
    from aisc_connectors import vault

    assert vault.plain(cid, "token") == "s3cr3t-value"


def test_the_chat_mapping_needs_an_allowed_operation(api, as_user, mcas):
    chat = next(o for o in ops(api, as_user, mcas).values() if o["path"] == "/chat")
    mapping = {"operation_id": chat["operation_id"], "input_mode": "text", "input_field": "question",
               "answer_path": "answer", "extra_body": {}}
    assert api.put(f"/api/v1/connectors/{mcas}/chat", headers=as_user(), json=mapping).status_code == 409
    api.patch(f"/api/v1/connectors/{mcas}/operations/{chat['operation_id']}", headers=as_user(),
              json={"allowed": True, "confirm_changes_data": True})
    assert api.put(f"/api/v1/connectors/{mcas}/chat", headers=as_user(), json=mapping).status_code == 200
    bad = {**mapping, "answer_path": "[[["}
    assert api.put(f"/api/v1/connectors/{mcas}/chat", headers=as_user(), json=bad).status_code == 422


def test_the_server_url_can_be_replaced(api, as_user, mcas):
    assert api.put(f"/api/v1/connectors/{mcas}/server", headers=as_user(), json={"url": "ftp://x"}).status_code == 422
    assert api.put(f"/api/v1/connectors/{mcas}/server", headers=as_user(),
                   json={"url": "http://mcas.internal:8500/"}).status_code == 200
    from aisc_connectors import store

    assert store.get(mcas, with_document=True)["document"]["servers"] == [{"url": "http://mcas.internal:8500"}]


def test_an_import_that_fails_says_why(api, as_user, engine):
    cid = api.post("/api/v1/connectors", headers=as_user(),
                   json={"project_pid": str(engine.project), "name": "Bad"}).json()["pid"]
    answer = api.post(f"/api/v1/connectors/{cid}/import", headers=as_user(), json={"kind": "curl", "text": "wget x"})
    assert answer.status_code == 422
    assert "curl" in answer.json()["detail"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_admin_import_and_policies.py -v`
Expected: FAIL with 404 on `/import` (route missing).

- [ ] **Step 3: Add the dispatcher**

Append to `apps/connectors/aisc_connectors/importers/__init__.py`:

```python
KINDS = ("openapi", "curl", "postman", "manual", "wsdl", "graphql", "openai", "ollama", "huggingface")


def import_source(kind: str, payload: dict) -> ImportResult:
    from aisc_connectors.importers import curl, manual, openapi, postman, presets, wsdl
    from aisc_connectors.importers import graphql as gql
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.fetch import fetch_text

    def text_or_url() -> str:
        if payload.get("text"):
            return payload["text"]
        if payload.get("url"):
            return fetch_text(payload["url"])
        raise ImportFailed("give either the document's text or its URL")

    if kind == "openapi":
        return openapi.import_openapi(text_or_url(), source_url=payload.get("url"), base_url=payload.get("base_url"))
    if kind == "curl":
        return curl.import_curl(payload.get("text") or "")
    if kind == "postman":
        return postman.import_postman(text_or_url())
    if kind == "manual":
        return manual.import_manual(payload.get("method", "POST"), payload.get("url", ""),
                                    payload.get("example_request"), payload.get("example_response"),
                                    payload.get("content_type", "application/json"),
                                    payload.get("operation_id") or "call")
    if kind == "wsdl":
        return wsdl.import_wsdl(text_or_url())
    if kind == "graphql":
        return gql.import_graphql(payload.get("url", ""))
    if kind in ("openai", "ollama"):
        return getattr(presets, kind)(payload.get("url", ""), payload.get("model", ""))
    if kind == "huggingface":
        return presets.huggingface(payload.get("url", ""))
    raise ImportFailed(f"unknown connector type {kind!r}; one of {', '.join(KINDS)}")
```

- [ ] **Step 4: Add the policy SQL**

Append to `apps/connectors/aisc_connectors/store.py`:

```python
from psycopg.types.json import Jsonb as _Jsonb  # noqa: E402

_POLICY = "operation_id, allowed, changes_data, changes_data_confirmed, patterns, component_pids"


def sync_policies(connector_pid, ops) -> None:
    ids = [o.operation_id for o in ops]
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM connector.operation_policy WHERE connector_pid = %s AND NOT operation_id = ANY(%s)",
                     (connector_pid, ids))
        for op in ops:
            conn.execute(
                "INSERT INTO connector.operation_policy (connector_pid, operation_id, changes_data)"
                " VALUES (%s, %s, %s) ON CONFLICT (connector_pid, operation_id)"
                " DO UPDATE SET changes_data = excluded.changes_data",
                (connector_pid, op.operation_id, op.changes_data),
            )


def policies(connector_pid) -> dict[str, dict]:
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT {_POLICY} FROM connector.operation_policy WHERE connector_pid = %s",
                            (connector_pid,)).fetchall()
    return {r["operation_id"]: r for r in rows}


def update_policy(connector_pid, operation_id, **fields) -> dict:
    sets = ", ".join(f"{k} = %s" for k in fields)
    values = [_Jsonb(v) if k == "patterns" else v for k, v in fields.items()]
    with db.pool().connection() as conn:
        return conn.execute(
            f"UPDATE connector.operation_policy SET {sets} WHERE connector_pid = %s AND operation_id = %s"
            f" RETURNING {_POLICY}", (*values, connector_pid, operation_id),
        ).fetchone()
```

- [ ] **Step 5: Add the routes**

Append to `apps/connectors/aisc_connectors/routes_admin.py`:

```python
import jmespath  # noqa: E402

from aisc_connectors import importers  # noqa: E402
from aisc_connectors.importers.errors import ImportFailed  # noqa: E402
from aisc_connectors.executor.errors import GatewayFailure  # noqa: E402
from aisc_connectors.model import find, operations  # noqa: E402


def _compiles(expression: str) -> bool:
    try:
        jmespath.compile(expression)
        return True
    except jmespath.exceptions.JMESPathError:
        return False


def check_patterns(patterns: dict) -> dict:
    unknown = set(patterns) - {"session", "async", "stream"}
    if unknown:
        raise HTTPException(422, f"unknown patterns {sorted(unknown)}")
    if "session" in patterns:
        s = patterns["session"]
        if s.get("inject_in") not in ("body", "header", "query") or not s.get("inject_name") \
                or not _compiles(s.get("id_path", "")):
            raise HTTPException(422, "session needs id_path (JMESPath), inject_in (body|header|query), inject_name")
    if "async" in patterns:
        a = patterns["async"]
        source = str(a.get("status_from", ""))
        if not (source.startswith("header:") or (source.startswith("body:") and _compiles(source[5:]))) \
                or not _compiles(a.get("done_when", "")) \
                or (a.get("result_path") and not _compiles(a["result_path"])) \
                or not 1 <= int(a.get("interval_s", 2)) <= 60 or not 1 <= int(a.get("timeout_s", 120)) <= 600:
            raise HTTPException(422, "async needs status_from (header:Name or body:path), done_when, "
                                     "interval_s 1..60, timeout_s 1..600")
    if "stream" in patterns:
        s = patterns["stream"]
        if s.get("format") not in ("sse", "ndjson") or not _compiles(s.get("delta_path", "")):
            raise HTTPException(422, "stream needs format (sse|ndjson) and delta_path (JMESPath)")
    return patterns


def _with_document(connector_pid: uuid.UUID) -> dict:
    row = store.get(connector_pid, with_document=True)
    if row is None:
        raise HTTPException(404, "no such connector")
    return row


def _operation_list(row: dict) -> list[dict]:
    policy = store.policies(row["pid"])
    listed = []
    for op in operations(row["document"]):
        p = policy.get(op.operation_id, {})
        listed.append({"operation_id": op.operation_id, "method": op.method, "path": op.path, "summary": op.summary,
                       "changes_data": op.changes_data, "allowed": p.get("allowed", False),
                       "changes_data_confirmed": p.get("changes_data_confirmed", False),
                       "patterns": p.get("patterns", {}),
                       "component_pids": [str(c) for c in p.get("component_pids", [])]})
    return listed


@router.post("/{connector_pid}/import")
def import_into(connector_pid: uuid.UUID, body: dict, admin: Admin = Depends(admin_call)) -> dict:
    row = _with_document(connector_pid)
    kind = body.get("kind", "")
    try:
        result = importers.import_source(kind, body)
    except (ImportFailed, GatewayFailure) as exc:
        raise HTTPException(422, str(exc))
    for name, value in result.detected_secrets.items():
        vault.put(connector_pid, name, value)
    fields: dict = {"document": result.document, "import_warnings": result.warnings, "kind": kind}
    if result.auth_suggestion and (row["auth"] or {}).get("scheme", "none") == "none":
        fields["auth"] = result.auth_suggestion
    if result.chat_suggestion and not row["chat"]:
        fields["chat"] = result.chat_suggestion
    updated = store.update(connector_pid, **fields)
    store.sync_policies(connector_pid, operations(result.document))
    return {"operations": _operation_list(_with_document(connector_pid)), "warnings": result.warnings,
            "auth": updated["auth"], "detected_secrets": sorted(result.detected_secrets), "chat": updated["chat"]}


@router.get("/{connector_pid}/operations")
def list_operations(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call)) -> list[dict]:
    return _operation_list(_with_document(connector_pid))


class PolicyPatch(BaseModel):
    allowed: bool | None = None
    confirm_changes_data: bool = False
    confirm_production: bool = False
    patterns: dict | None = None
    component_pids: list[uuid.UUID] | None = None


@router.patch("/{connector_pid}/operations/{operation_id}")
def patch_operation(connector_pid: uuid.UUID, operation_id: str, body: PolicyPatch,
                    admin: Admin = Depends(admin_call),
                    engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    row = _with_document(connector_pid)
    op = find(row["document"], operation_id)
    if op is None:
        raise HTTPException(404, "no such operation")
    fields: dict = {}
    if body.allowed is True:
        if op.changes_data and not body.confirm_changes_data:
            raise HTTPException(409, f"{operation_id} may change data in the target: confirm to allow it")
        if row["environment"] == "production" and not body.confirm_production:
            raise HTTPException(409, "this connector reaches a production system: confirm to allow it")
        fields.update(allowed=True, changes_data_confirmed=op.changes_data)
    elif body.allowed is False:
        fields.update(allowed=False, changes_data_confirmed=False)
    if body.patterns is not None:
        fields["patterns"] = check_patterns(body.patterns)
    if body.component_pids is not None:
        known = {c["pid"] for c in engine.aisystem(row["project_pid"])["components"]}
        unknown = [str(c) for c in body.component_pids if str(c) not in known]
        if unknown:
            raise HTTPException(422, f"not components of this AI system: {unknown}")
        fields["component_pids"] = body.component_pids
    if fields:
        store.update_policy(connector_pid, operation_id, **fields)
    return next(o for o in _operation_list(_with_document(connector_pid)) if o["operation_id"] == operation_id)


class ServerUrl(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.put("/{connector_pid}/server")
def set_server(connector_pid: uuid.UUID, body: ServerUrl, admin: Admin = Depends(admin_call),
               engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    from urllib.parse import urlsplit

    parts = urlsplit(body.url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(422, "the server must be an http(s) URL")
    document = _with_document(connector_pid)["document"]
    document["servers"] = [{"url": body.url.rstrip("/")}]
    return shown(store.update(connector_pid, document=document), engine)


class ChatMapping(BaseModel):
    operation_id: str
    input_mode: Literal["text", "messages"]
    input_field: str = Field(min_length=1)
    answer_path: str = Field(min_length=1)
    extra_body: dict = {}


@router.put("/{connector_pid}/chat")
def set_chat(connector_pid: uuid.UUID, body: ChatMapping, admin: Admin = Depends(admin_call),
             engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    _with_document(connector_pid)
    if not store.policies(connector_pid).get(body.operation_id, {}).get("allowed"):
        raise HTTPException(409, f"allow {body.operation_id} before using it for chat")
    if not _compiles(body.answer_path):
        raise HTTPException(422, "answer_path is not a JMESPath expression")
    return shown(store.update(connector_pid, chat=body.model_dump()), engine)
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_admin_import_and_policies.py tests/test_admin_connectors.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: import from any connector type, default-deny operations, links, patterns, chat mapping"
```

---

### Task 13: Executing REST operations: auth, outbound safety, rate limits, errors

**Files:**
- Modify: `apps/connectors/aisc_connectors/executor/guard.py` (host check, rate limiter)
- Create: `apps/connectors/aisc_connectors/executor/auth.py`, `apps/connectors/aisc_connectors/executor/http.py`
- Test: `apps/connectors/tests/test_executor_http.py`, `apps/connectors/tests/test_executor_auth.py`

**Interfaces:**
- Produces:
  - `executor.http.Call` dataclass: `path_params: dict[str, str]`, `query: list[tuple[str, str]]`, `headers: dict[str, str]`, `body: bytes | None`, `content_type: str | None`, `session_key: str | None = None`.
  - `executor.http.Result` dataclass: `outcome: str`, `status: int`, `content_type: str | None`, `body: bytes`, `latency_ms: int`, `headers: dict` (lower-cased response headers, default empty).
  - `executor.http.execute(connector: dict, op: Operation, call: Call, secret: Callable[[str], str | None], transport: httpx.BaseTransport | None = None) -> Result` (raises `GatewayFailure`).
  - `executor.auth.httpx_auth(auth: dict, secret) -> tuple[dict[str, str], list[tuple[str, str]], dict]` returning extra headers, extra query pairs, and httpx client kwargs (`cert`, `verify`); `executor.auth.requests_session(auth, secret, verify_tls) -> requests.Session` (for zeep); `executor.auth.oauth_token(auth, secret, transport=None) -> str` (cached per token URL + client id until 30 s before expiry).
  - `executor.guard.check_target(url: str, server: str) -> None` (same scheme+host+port as the server, no metadata host), `executor.guard.RateLimiter.allow(connector_pid, per_minute) -> bool`, module instance `executor.guard.limiter`.

- [ ] **Step 1: Write the failing tests**

`apps/connectors/tests/test_executor_auth.py`:

```python
import httpx
import respx


def secrets(**values):
    return lambda name: values.get(name)


def test_api_key_in_a_header_and_in_the_query():
    from aisc_connectors.executor.auth import httpx_auth

    headers, query, _ = httpx_auth({"scheme": "api_key", "in": "header", "name": "X-Key"}, secrets(api_key="k1"))
    assert headers == {"X-Key": "k1"} and query == []
    headers, query, _ = httpx_auth({"scheme": "api_key", "in": "query", "name": "key"}, secrets(api_key="k1"))
    assert headers == {} and query == [("key", "k1")]


def test_bearer_and_basic():
    from aisc_connectors.executor.auth import httpx_auth

    assert httpx_auth({"scheme": "bearer"}, secrets(token="t"))[0] == {"Authorization": "Bearer t"}
    basic = httpx_auth({"scheme": "basic", "username": "u"}, secrets(password="p"))[0]
    assert basic == {"Authorization": "Basic dTpw"}


def test_a_missing_secret_is_an_auth_failure():
    import pytest

    from aisc_connectors.executor.auth import httpx_auth
    from aisc_connectors.executor.errors import GatewayFailure

    with pytest.raises(GatewayFailure) as info:
        httpx_auth({"scheme": "bearer"}, secrets())
    assert info.value.kind == "invalid_input"
    assert "token" in info.value.message


@respx.mock
def test_oauth2_client_credentials_is_fetched_once_and_cached():
    from aisc_connectors.executor import auth

    auth._tokens.clear()
    route = respx.post("https://idp.test/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600}))
    cfg = {"scheme": "oauth2_client_credentials", "token_url": "https://idp.test/token", "client_id": "c"}
    for _ in range(3):
        headers, _, _ = auth.httpx_auth(cfg, secrets(client_secret="s"))
        assert headers == {"Authorization": "Bearer at"}
    assert route.call_count == 1


@respx.mock
def test_a_refused_oauth2_client_is_an_auth_failure():
    import pytest

    from aisc_connectors.executor import auth
    from aisc_connectors.executor.errors import GatewayFailure

    auth._tokens.clear()
    respx.post("https://idp.test/token").mock(return_value=httpx.Response(401, json={"error": "invalid_client"}))
    cfg = {"scheme": "oauth2_client_credentials", "token_url": "https://idp.test/token", "client_id": "c"}
    with pytest.raises(GatewayFailure) as info:
        auth.httpx_auth(cfg, secrets(client_secret="bad"))
    assert info.value.kind == "auth"


def test_mtls_writes_the_pair_to_private_files():
    import os

    from aisc_connectors.executor.auth import httpx_auth

    _, _, kwargs = httpx_auth({"scheme": "mtls"}, secrets(client_cert="CERT", client_key="KEY"))
    cert_path, key_path = kwargs["cert"]
    assert open(cert_path).read() == "CERT"
    assert oct(os.stat(key_path).st_mode & 0o777) == "0o600"
```

`apps/connectors/tests/test_executor_http.py`:

```python
import httpx
import pytest
import respx

from aisc_connectors.importers.build import one_operation
from aisc_connectors.model import operations


def connector(url="https://api.acme.test/v1/users/{id}", method="GET", auth=None, max_bytes=None):
    result = one_operation(method, url.replace("{id}", "x"), {"X-Tenant": "42"}, None, None, "op")
    doc = result.document
    item = doc["paths"].pop(next(iter(doc["paths"])))
    item[method.lower()]["x-aisc-binding"]["path"] = "/v1/users/{id}"
    item[method.lower()]["parameters"] = [{"in": "path", "name": "id", "required": True},
                                          {"in": "query", "name": "q", "required": False},
                                          {"in": "header", "name": "X-Trace", "required": False}]
    doc["paths"]["/v1/users/{id}"] = item
    return ({"pid": "00000000-0000-0000-0000-000000000001", "document": doc,
             "auth": auth or {"scheme": "none"}, "settings": {"timeout_s": 5, "verify_tls": True}},
            operations(doc)[0])


def call(**kw):
    from aisc_connectors.executor.http import Call

    return Call(path_params=kw.get("path_params", {"id": "42"}), query=kw.get("query", []),
                headers=kw.get("headers", {}), body=kw.get("body"), content_type=kw.get("content_type"))


@pytest.fixture(autouse=True)
def resolvable(monkeypatch):
    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)


@respx.mock
def test_path_query_headers_and_static_headers_reach_the_target():
    from aisc_connectors.executor.http import execute

    route = respx.get("https://api.acme.test/v1/users/42").mock(return_value=httpx.Response(200, json={"id": 42}))
    conn, op = connector()
    result = execute(conn, op, call(query=[("q", "x"), ("undeclared", "y")],
                                    headers={"X-Trace": "t1", "Cookie": "steal"}), lambda n: None)
    sent = route.calls[0].request
    assert result.outcome == "ok" and result.status == 200
    assert sent.url.params.get("q") == "x" and "undeclared" not in sent.url.params
    assert sent.headers["X-Trace"] == "t1" and "Cookie" not in sent.headers
    assert sent.headers["X-Tenant"] == "42"


@respx.mock
def test_path_parameters_are_encoded_so_they_cannot_escape_the_path():
    from aisc_connectors.executor.http import execute

    route = respx.get(url__regex=r"https://api\.acme\.test/v1/users/.*").mock(return_value=httpx.Response(200))
    conn, op = connector()
    execute(conn, op, call(path_params={"id": "../../admin?x=1"}), lambda n: None)
    assert route.calls[0].request.url.raw_path == b"/v1/users/..%2F..%2Fadmin%3Fx%3D1"


def test_a_missing_path_parameter_is_invalid_input():
    from aisc_connectors.executor.errors import GatewayFailure
    from aisc_connectors.executor.http import execute

    conn, op = connector()
    with pytest.raises(GatewayFailure) as info:
        execute(conn, op, call(path_params={}), lambda n: None)
    assert info.value.kind == "invalid_input"


@respx.mock
def test_target_statuses_are_classified_and_passed_through():
    from aisc_connectors.executor.http import execute

    conn, op = connector()
    for status, kind in ((401, "auth"), (404, "not_found"), (422, "target_rejected"), (429, "rate_limited"),
                         (503, "target_error")):
        respx.get("https://api.acme.test/v1/users/42").mock(return_value=httpx.Response(status, text="no"))
        result = execute(conn, op, call(), lambda n: None)
        assert (result.status, result.outcome, result.body) == (status, kind, b"no")


@respx.mock
def test_timeouts_and_refused_connections_are_named():
    from aisc_connectors.executor.errors import GatewayFailure
    from aisc_connectors.executor.http import execute

    conn, op = connector()
    respx.get("https://api.acme.test/v1/users/42").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(GatewayFailure) as info:
        execute(conn, op, call(), lambda n: None)
    assert info.value.kind == "timeout"
    respx.get("https://api.acme.test/v1/users/42").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(GatewayFailure) as info:
        execute(conn, op, call(), lambda n: None)
    assert info.value.kind == "connection"


@respx.mock
def test_redirects_are_not_followed_to_other_hosts():
    from aisc_connectors.executor.http import execute

    respx.get("https://api.acme.test/v1/users/42").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.test/"}))
    evil = respx.get("https://evil.test/").mock(return_value=httpx.Response(200))
    conn, op = connector()
    result = execute(conn, op, call(), lambda n: None)
    assert result.status == 302 and evil.call_count == 0


@respx.mock
def test_binary_body_passes_through():
    from aisc_connectors.executor.http import execute

    pdf = b"%PDF-1.7\x00\x01\x02" * 1000
    respx.get("https://api.acme.test/v1/users/42").mock(
        return_value=httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"}))
    conn, op = connector()
    result = execute(conn, op, call(), lambda n: None)
    assert result.body == pdf and result.content_type == "application/pdf"


@respx.mock
def test_oversized_response_is_refused(monkeypatch):
    from aisc_connectors.executor.errors import GatewayFailure
    from aisc_connectors.executor.http import execute

    monkeypatch.setenv("CONNECTORS_MAX_RESPONSE_BYTES", "1000")
    respx.get("https://api.acme.test/v1/users/42").mock(return_value=httpx.Response(200, content=b"x" * 5000))
    conn, op = connector()
    with pytest.raises(GatewayFailure) as info:
        execute(conn, op, call(), lambda n: None)
    assert info.value.kind == "target_too_large"


def test_the_rate_limiter_counts_per_connector():
    from aisc_connectors.executor.guard import RateLimiter

    limiter = RateLimiter()
    assert all(limiter.allow("a", 3) for _ in range(3))
    assert limiter.allow("a", 3) is False
    assert limiter.allow("b", 3) is True


def test_check_target_refuses_another_host():
    from aisc_connectors.executor.errors import GatewayFailure
    from aisc_connectors.executor.guard import check_target

    check_target("https://api.acme.test/v1/x", "https://api.acme.test/v1")
    with pytest.raises(GatewayFailure):
        check_target("https://evil.test/x", "https://api.acme.test/v1")
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/connectors && uv run pytest tests/test_executor_auth.py tests/test_executor_http.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.executor.auth'`.

- [ ] **Step 3: Implement the guard additions**

Append to `apps/connectors/aisc_connectors/executor/guard.py`:

```python
import threading  # noqa: E402
import time  # noqa: E402


def _origin(url: str) -> tuple:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def check_target(url: str, server: str) -> None:
    if _origin(url) != _origin(server):
        raise GatewayFailure("not_allowed", "the request would leave the connector's own server")
    refuse_metadata_host(url)


class RateLimiter:
    """A sliding one-minute window per connector, in this process (one replica)."""

    def __init__(self):
        self._calls: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, connector_pid, per_minute: int) -> bool:
        now = time.monotonic()
        key = str(connector_pid)
        with self._lock:
            recent = [t for t in self._calls.get(key, []) if now - t < 60]
            if len(recent) >= per_minute:
                self._calls[key] = recent
                return False
            recent.append(now)
            self._calls[key] = recent
            return True


limiter = RateLimiter()
```

- [ ] **Step 4: Implement the auth appliers**

`apps/connectors/aisc_connectors/executor/auth.py`:

```python
"""Credentials applied to outgoing calls. Values come from the vault and go nowhere else."""
from __future__ import annotations

import base64
import os
import tempfile
import threading
import time
from typing import Callable

import httpx

from aisc_connectors.executor.errors import GatewayFailure

Secret = Callable[[str], "str | None"]
_tokens: dict[tuple[str, str], tuple[str, float]] = {}
_lock = threading.Lock()


def _need(secret: Secret, name: str) -> str:
    value = secret(name)
    if not value:
        raise GatewayFailure("invalid_input", f"the connector's credentials lack {name!r}")
    return value


def oauth_token(auth: dict, secret: Secret, transport: httpx.BaseTransport | None = None) -> str:
    key = (auth["token_url"], auth["client_id"])
    with _lock:
        cached = _tokens.get(key)
        if cached and cached[1] > time.time() + 30:
            return cached[0]
    data = {"grant_type": "client_credentials", "client_id": auth["client_id"],
            "client_secret": _need(secret, "client_secret")}
    if auth.get("scope"):
        data["scope"] = auth["scope"]
    try:
        response = httpx.post(auth["token_url"], data=data, timeout=15, transport=transport)
    except httpx.HTTPError as exc:
        raise GatewayFailure("connection", f"the token endpoint did not answer: {exc}") from exc
    if response.status_code >= 400:
        raise GatewayFailure("auth", f"the token endpoint refused the client ({response.status_code})")
    payload = response.json()
    with _lock:
        _tokens[key] = (payload["access_token"], time.time() + float(payload.get("expires_in", 300)))
    return payload["access_token"]


def _private_file(content: str) -> str:
    handle, path = tempfile.mkstemp(prefix="aisc-connector-", suffix=".pem")
    os.fchmod(handle, 0o600)
    with os.fdopen(handle, "w") as f:
        f.write(content)
    return path


def httpx_auth(auth: dict, secret: Secret) -> tuple[dict[str, str], list[tuple[str, str]], dict]:
    scheme = auth.get("scheme", "none")
    headers: dict[str, str] = {}
    query: list[tuple[str, str]] = []
    kwargs: dict = {}
    if scheme == "api_key":
        value = _need(secret, "api_key")
        if auth["in"] == "header":
            headers[auth["name"]] = value
        else:
            query.append((auth["name"], value))
    elif scheme == "bearer":
        headers["Authorization"] = f"Bearer {_need(secret, 'token')}"
    elif scheme == "basic":
        pair = f"{auth['username']}:{_need(secret, 'password')}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
    elif scheme == "oauth2_client_credentials":
        headers["Authorization"] = f"Bearer {oauth_token(auth, secret)}"
    elif scheme == "mtls":
        kwargs["cert"] = (_private_file(_need(secret, "client_cert")), _private_file(_need(secret, "client_key")))
    ca = secret("ca_bundle")
    if ca:
        kwargs["verify"] = _private_file(ca)
    return headers, query, kwargs


def requests_session(auth: dict, secret: Secret, verify_tls: bool):
    """The same credentials for zeep, which speaks requests rather than httpx."""
    import requests

    session = requests.Session()
    headers, query, kwargs = httpx_auth(auth, secret)
    session.headers.update(headers)
    session.params = dict(query)
    if "cert" in kwargs:
        session.cert = kwargs["cert"]
    session.verify = kwargs.get("verify", verify_tls)
    return session
```

- [ ] **Step 5: Implement the REST executor**

`apps/connectors/aisc_connectors/executor/http.py`:

```python
"""One REST operation against the real system: exactly what the binding allows, nothing more."""
from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from aisc_connectors.executor import guard
from aisc_connectors.executor.auth import Secret, httpx_auth
from aisc_connectors.executor.errors import GatewayFailure, kind_for_status
from aisc_connectors.model import Operation, server_url
from aisc_connectors.settings import settings


@dataclass
class Call:
    path_params: dict[str, str]
    query: list[tuple[str, str]]
    headers: dict[str, str]
    body: bytes | None
    content_type: str | None
    session_key: str | None = None


@dataclass
class Result:
    outcome: str
    status: int
    content_type: str | None
    body: bytes
    latency_ms: int
    #: lower-cased response headers; the async pattern reads Location from here
    headers: dict = field(default_factory=dict)


def _declared(op: Operation, where: str) -> set[str]:
    return {p["name"].lower() if where == "header" else p["name"]
            for p in op.spec.get("parameters") or [] if p.get("in") == where}


def build_url(connector: dict, op: Operation, call: Call) -> str:
    path = op.binding["path"]
    for name in _declared(op, "path"):
        if name not in call.path_params:
            raise GatewayFailure("invalid_input", f"the path parameter {name!r} is missing")
        path = path.replace("{" + name + "}", quote(str(call.path_params[name]), safe=""))
    return server_url(connector["document"]) + path


def execute(connector: dict, op: Operation, call: Call, secret: Secret,
            transport: httpx.BaseTransport | None = None) -> Result:
    url = build_url(connector, op, call)
    guard.check_target(url, server_url(connector["document"]))
    allowed_query = _declared(op, "query")
    query = [(k, v) for k, v in call.query if k in allowed_query]
    allowed_headers = _declared(op, "header")
    headers = {k: v for k, v in call.headers.items() if k.lower() in allowed_headers}
    headers.update(op.binding.get("static_headers") or {})
    if call.content_type:
        headers["Content-Type"] = call.content_type
    auth_headers, auth_query, client_kwargs = httpx_auth(connector["auth"] or {"scheme": "none"}, secret)
    headers.update(auth_headers)
    options = connector.get("settings") or {}
    client_kwargs.setdefault("verify", options.get("verify_tls", True))
    limit = settings().max_response_bytes
    started = time.monotonic()
    try:
        with httpx.Client(timeout=options.get("timeout_s", 30), follow_redirects=False, transport=transport,
                          **client_kwargs) as client:
            with client.stream(op.method.upper(), url, params=query + auth_query, headers=headers,
                               content=call.body) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise GatewayFailure("target_too_large", f"the answer is larger than {limit} bytes")
                    chunks.append(chunk)
    except httpx.TimeoutException as exc:
        raise GatewayFailure("timeout", "the system did not answer in time") from exc
    except httpx.ConnectError as exc:
        if isinstance(exc.__cause__, ssl.SSLError) or "SSL" in str(exc) or "certificate" in str(exc):
            raise GatewayFailure("tls", f"TLS failed: {exc}") from exc
        raise GatewayFailure("connection", f"could not connect: {exc}") from exc
    except httpx.HTTPError as exc:
        raise GatewayFailure("connection", f"the call failed: {exc}") from exc
    return Result(outcome=kind_for_status(response.status_code), status=response.status_code,
                  content_type=response.headers.get("content-type"), body=b"".join(chunks),
                  latency_ms=int((time.monotonic() - started) * 1000),
                  headers={k.lower(): v for k, v in response.headers.items()})
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_executor_auth.py tests/test_executor_http.py -v`
Expected: 17 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: REST execution with auth schemes, outbound safety, size cap and named failures"
```

---

### Task 14: Session, async and stream patterns

**Files:**
- Create: `apps/connectors/aisc_connectors/executor/patterns.py`
- Test: `apps/connectors/tests/test_patterns.py`

**Interfaces:**
- Consumes: `executor.http.execute`, `Call`, `Result`, `executor.auth.httpx_auth`, `guard.check_target`.
- Produces: `patterns.run_with_patterns(connector, op, call, patterns: dict, secret, transport=None) -> Result`; `patterns.sessions` (a `SessionStore` with `get(connector_pid, key) -> str | None`, `put(connector_pid, key, value)`, TTL 3600 s, `ttl` attribute settable in tests).

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_patterns.py`:

```python
import json

import httpx
import pytest
import respx

from aisc_connectors.importers.build import one_operation
from aisc_connectors.model import operations


@pytest.fixture(autouse=True)
def resolvable(monkeypatch):
    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)


def connector(pid="00000000-0000-0000-0000-00000000000a"):
    doc = one_operation("POST", "https://bot.acme.test/chat", {}, '{"message": "hi"}', "application/json",
                        "chat").document
    return {"pid": pid, "document": doc, "auth": {"scheme": "none"}, "settings": {"timeout_s": 5}}, operations(doc)[0]


def call(body, session_key=None):
    from aisc_connectors.executor.http import Call

    return Call({}, [], {}, json.dumps(body).encode(), "application/json", session_key=session_key)


SESSION = {"session": {"id_path": "conversation_id", "inject_in": "body", "inject_name": "conversation_id"}}


@respx.mock
def test_a_session_id_is_captured_then_injected():
    from aisc_connectors.executor.patterns import run_with_patterns, sessions

    sessions.clear()
    route = respx.post("https://bot.acme.test/chat").mock(side_effect=[
        httpx.Response(200, json={"conversation_id": "c-1", "reply": "hello"}),
        httpx.Response(200, json={"conversation_id": "c-1", "reply": "again"}),
    ])
    conn, op = connector()
    run_with_patterns(conn, op, call({"message": "hi"}, "k1"), SESSION, lambda n: None)
    run_with_patterns(conn, op, call({"message": "more"}, "k1"), SESSION, lambda n: None)
    assert "conversation_id" not in json.loads(route.calls[0].request.content)
    assert json.loads(route.calls[1].request.content)["conversation_id"] == "c-1"


@respx.mock
def test_sessions_are_isolated_per_connector():
    from aisc_connectors.executor.patterns import run_with_patterns, sessions

    sessions.clear()
    route = respx.post("https://bot.acme.test/chat").mock(
        return_value=httpx.Response(200, json={"conversation_id": "c-1"}))
    first, op = connector("00000000-0000-0000-0000-00000000000a")
    second, _ = connector("00000000-0000-0000-0000-00000000000b")
    run_with_patterns(first, op, call({"m": 1}, "same"), SESSION, lambda n: None)
    run_with_patterns(second, op, call({"m": 2}, "same"), SESSION, lambda n: None)
    assert "conversation_id" not in json.loads(route.calls[1].request.content)


@respx.mock
def test_expired_session_starts_fresh():
    from aisc_connectors.executor.patterns import run_with_patterns, sessions

    sessions.clear()
    sessions.ttl = 0
    try:
        route = respx.post("https://bot.acme.test/chat").mock(
            return_value=httpx.Response(200, json={"conversation_id": "c-1"}))
        conn, op = connector()
        run_with_patterns(conn, op, call({"m": 1}, "k"), SESSION, lambda n: None)
        run_with_patterns(conn, op, call({"m": 2}, "k"), SESSION, lambda n: None)
        assert "conversation_id" not in json.loads(route.calls[1].request.content)
    finally:
        sessions.ttl = 3600


@respx.mock
def test_async_jobs_are_polled_until_done():
    from aisc_connectors.executor.patterns import run_with_patterns

    respx.post("https://bot.acme.test/chat").mock(
        return_value=httpx.Response(202, headers={"Location": "https://bot.acme.test/jobs/7"}))
    respx.get("https://bot.acme.test/jobs/7").mock(side_effect=[
        httpx.Response(200, json={"state": "running"}),
        httpx.Response(200, json={"state": "done", "result": {"answer": 42}}),
    ])
    conn, op = connector()
    patterns = {"async": {"status_from": "header:Location", "done_when": "state == 'done'",
                          "result_path": "result", "interval_s": 1, "timeout_s": 10}}
    result = run_with_patterns(conn, op, call({"m": 1}), patterns, lambda n: None, sleep=lambda s: None)
    assert result.status == 200 and json.loads(result.body) == {"answer": 42}


@respx.mock
def test_async_polling_never_leaves_the_server():
    from aisc_connectors.executor.errors import GatewayFailure
    from aisc_connectors.executor.patterns import run_with_patterns

    respx.post("https://bot.acme.test/chat").mock(
        return_value=httpx.Response(202, headers={"Location": "https://evil.test/jobs/7"}))
    conn, op = connector()
    patterns = {"async": {"status_from": "header:Location", "done_when": "state == 'done'", "interval_s": 1,
                          "timeout_s": 10}}
    with pytest.raises(GatewayFailure) as info:
        run_with_patterns(conn, op, call({"m": 1}), patterns, lambda n: None, sleep=lambda s: None)
    assert info.value.kind == "not_allowed"


@respx.mock
def test_sse_deltas_are_joined_into_one_answer():
    from aisc_connectors.executor.patterns import run_with_patterns

    stream = (b'data: {"delta": "Hel"}\n\n'
              b'data: {"delta": "lo"}\n\n'
              b'data: [DONE]\n\n')
    respx.post("https://bot.acme.test/chat").mock(
        return_value=httpx.Response(200, content=stream, headers={"Content-Type": "text/event-stream"}))
    conn, op = connector()
    patterns = {"stream": {"format": "sse", "delta_path": "delta", "done_marker": "[DONE]"}}
    result = run_with_patterns(conn, op, call({"m": 1}), patterns, lambda n: None)
    assert json.loads(result.body) == {"text": "Hello", "events": 2}
    assert result.content_type == "application/json"


@respx.mock
def test_a_stream_without_the_delta_is_bad_mapping():
    from aisc_connectors.executor.errors import GatewayFailure
    from aisc_connectors.executor.patterns import run_with_patterns

    respx.post("https://bot.acme.test/chat").mock(
        return_value=httpx.Response(200, content=b'{"other": 1}\n', headers={"Content-Type": "application/x-ndjson"}))
    conn, op = connector()
    with pytest.raises(GatewayFailure) as info:
        run_with_patterns(conn, op, call({"m": 1}), {"stream": {"format": "ndjson", "delta_path": "delta"}},
                          lambda n: None)
    assert info.value.kind == "bad_mapping"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_patterns.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.executor.patterns'`.

- [ ] **Step 3: Implement**

`apps/connectors/aisc_connectors/executor/patterns.py`:

```python
"""What turns a conversation, a job or a stream into one request and one JSON answer (spec D3)."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from urllib.parse import urljoin

import httpx
import jmespath

from aisc_connectors.executor import guard
from aisc_connectors.executor.auth import httpx_auth
from aisc_connectors.executor.errors import GatewayFailure, kind_for_status
from aisc_connectors.executor.http import Call, Result, execute
from aisc_connectors.model import server_url


class SessionStore:
    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._values: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, connector_pid, key: str) -> str | None:
        with self._lock:
            found = self._values.get((str(connector_pid), key))
        if not found or time.monotonic() - found[1] >= self.ttl:
            return None
        return found[0]

    def put(self, connector_pid, key: str, value: str) -> None:
        with self._lock:
            self._values[(str(connector_pid), key)] = (value, time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


sessions = SessionStore()


def _json(body: bytes):
    try:
        return json.loads(body or b"null")
    except ValueError:
        return None


def _inject(call: Call, where: str, name: str, value: str) -> Call:
    if where == "header":
        return replace(call, headers={**call.headers, name: value})
    if where == "query":
        return replace(call, query=[*call.query, (name, value)])
    body = _json(call.body) or {}
    if not isinstance(body, dict):
        raise GatewayFailure("invalid_input", "a session id can only be added to a JSON object body")
    return replace(call, body=json.dumps({**body, name: value}).encode(), content_type="application/json")


def _poll(connector, first: Result, spec: dict, secret, transport, sleep) -> Result:
    source = spec["status_from"]
    if source.startswith("header:"):
        location = first.headers.get(source[7:].lower())
    else:
        location = jmespath.search(source[5:], _json(first.body))
    if not location:
        raise GatewayFailure("bad_mapping", f"the job answer has no status URL at {source}")
    url = urljoin(server_url(connector["document"]) + "/", str(location))
    guard.check_target(url, server_url(connector["document"]))
    headers, query, kwargs = httpx_auth(connector["auth"] or {"scheme": "none"}, secret)
    deadline = time.monotonic() + int(spec.get("timeout_s", 120))
    with httpx.Client(timeout=(connector.get("settings") or {}).get("timeout_s", 30), follow_redirects=False,
                      transport=transport, **kwargs) as client:
        while True:
            response = client.get(url, headers=headers, params=query)
            body = response.json() if response.content else None
            if response.status_code >= 400:
                return Result(kind_for_status(response.status_code), response.status_code,
                              response.headers.get("content-type"), response.content, first.latency_ms)
            if jmespath.search(spec["done_when"], body):
                value = jmespath.search(spec["result_path"], body) if spec.get("result_path") else body
                return Result("ok", 200, "application/json", json.dumps(value).encode(), first.latency_ms)
            if time.monotonic() >= deadline:
                raise GatewayFailure("timeout", "the job did not finish in time")
            sleep(int(spec.get("interval_s", 2)))


def _collect(result: Result, spec: dict) -> Result:
    deltas = []
    for line in result.body.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if spec["format"] == "sse":
            if not line.startswith("data:"):
                continue
            line = line[5:].strip()
        if not line or line == spec.get("done_marker"):
            continue
        piece = jmespath.search(spec["delta_path"], _json(line.encode()))
        if piece is not None:
            deltas.append(str(piece))
    if not deltas:
        raise GatewayFailure("bad_mapping", f"no event had a value at {spec['delta_path']}")
    body = json.dumps({"text": "".join(deltas), "events": len(deltas)}).encode()
    return Result(result.outcome, result.status, "application/json", body, result.latency_ms)


def run_with_patterns(connector: dict, op, call: Call, patterns: dict, secret, transport=None,
                      sleep=time.sleep) -> Result:
    session = patterns.get("session")
    if session and call.session_key:
        known = sessions.get(connector["pid"], call.session_key)
        if known:
            call = _inject(call, session["inject_in"], session["inject_name"], known)
    result = execute(connector, op, call, secret, transport=transport)
    if session and call.session_key and result.outcome == "ok":
        found = jmespath.search(session["id_path"], _json(result.body))
        if found is not None:
            sessions.put(connector["pid"], call.session_key, str(found))
    if patterns.get("async") and result.status == 202:
        result = _poll(connector, result, patterns["async"], secret, transport, sleep)
    if patterns.get("stream") and result.outcome == "ok":
        result = _collect(result, patterns["stream"])
    return result

```

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_patterns.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: sessions, async job polling and stream collection behind one request"
```

---

### Task 15: SOAP and GraphQL execution, and the one entry point `run()`

**Files:**
- Create: `apps/connectors/aisc_connectors/executor/soap.py`, `apps/connectors/aisc_connectors/executor/graphql.py`
- Modify: `apps/connectors/aisc_connectors/executor/__init__.py` (the `run` entry point)
- Modify: `apps/connectors/aisc_connectors/store.py` (call log)
- Create: `apps/connectors/tests/stub_soap.py`
- Test: `apps/connectors/tests/test_executor_soap_graphql.py`, `apps/connectors/tests/test_run.py`

**Interfaces:**
- Consumes: Tasks 13 and 14; `vault.plain`; `store.policies`; `guard.limiter`.
- Produces:
  - `executor.soap.execute(connector, op, call, secret) -> Result` (JSON in, JSON out; a non-object answer becomes `{"result": value}`; SOAP faults become outcome `target_rejected` with `{"fault": message}`).
  - `executor.graphql.execute(connector, op, call, secret, transport=None) -> Result` (body = variables; answer = `data.<field>`; GraphQL `errors` become `target_rejected` with the errors list).
  - `executor.run(connector_pid, operation_id, call, via: str, token_pid=None, allow_denied: bool = False, transport=None) -> Result`. `via` is one of `gateway`, `openai_facade`, `ollama_facade`, `admin_test`. Denied operations raise `not_allowed` unless `allow_denied`. The rate limit applies to every `via`. One call-log row per call, including failures.
  - `store.log_call(connector_pid, operation_id, token_pid, via, outcome, target_status, latency_ms) -> None`, `store.recent_calls(connector_pid, limit=50) -> list[dict]`.

- [ ] **Step 1: Write the SOAP stub**

`apps/connectors/tests/stub_soap.py`:

```python
"""A tiny SOAP server for the calculator WSDL: Add(a, b) answers a + b; b = -1 answers a fault."""
from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ENVELOPE = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>{}'
            '</soap:Body></soap:Envelope>')


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        text = self.rfile.read(int(self.headers["Content-Length"])).decode()
        a = int(re.search(r"<(?:\w+:)?a>(-?\d+)<", text).group(1))
        b = int(re.search(r"<(?:\w+:)?b>(-?\d+)<", text).group(1))
        if b == -1:
            body, status = ("<soap:Fault><faultcode>soap:Client</faultcode><faultstring>b must not be -1"
                            "</faultstring></soap:Fault>"), 500
        else:
            body, status = f'<AddResponse xmlns="http://example.org/calc"><result>{a + b}</result></AddResponse>', 200
        payload = ENVELOPE.format(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def start() -> tuple[str, HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/calc", server
```

- [ ] **Step 2: Write the failing tests**

`apps/connectors/tests/test_executor_soap_graphql.py`:

```python
import json
import pathlib

import httpx
import pytest
import respx

from tests import stub_soap
from tests.test_import_graphql import introspection

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def soap_connector():
    from aisc_connectors.importers.wsdl import import_wsdl
    from aisc_connectors.model import find

    url, server = stub_soap.start()
    doc = import_wsdl((FIXTURES / "calc.wsdl").read_text()).document
    doc["servers"] = [{"url": url}]
    yield {"pid": "p", "document": doc, "auth": {"scheme": "none"}, "settings": {"timeout_s": 5}}, find(doc, "Add")
    server.shutdown()


def call(body):
    from aisc_connectors.executor.http import Call

    return Call({}, [], {}, json.dumps(body).encode(), "application/json")


def test_soap_takes_json_and_answers_json(soap_connector):
    from aisc_connectors.executor import soap

    conn, op = soap_connector
    result = soap.execute(conn, op, call({"a": 2, "b": 3}), lambda n: None)
    assert result.outcome == "ok"
    assert json.loads(result.body) == {"result": 5}


def test_a_soap_fault_is_a_rejection_with_its_message(soap_connector):
    from aisc_connectors.executor import soap

    conn, op = soap_connector
    result = soap.execute(conn, op, call({"a": 2, "b": -1}), lambda n: None)
    assert result.outcome == "target_rejected"
    assert "b must not be -1" in json.loads(result.body)["fault"]


@respx.mock
def test_graphql_sends_the_fixed_document_with_variables(monkeypatch):
    from aisc_connectors.executor import graphql
    from aisc_connectors.importers.graphql import from_introspection
    from aisc_connectors.model import find

    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)
    doc = from_introspection("https://api.acme.test/graphql", introspection()).document
    route = respx.post("https://api.acme.test/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"score": {"recommendation": "Approve", "score": 900}}}))
    conn = {"pid": "p", "document": doc, "auth": {"scheme": "none"}, "settings": {}}
    result = graphql.execute(conn, find(doc, "mutation_score"), call({"amount": 100}), lambda n: None)
    sent = json.loads(route.calls[0].request.content)
    assert sent["variables"] == {"amount": 100} and sent["operationName"] == "score"
    assert json.loads(result.body) == {"recommendation": "Approve", "score": 900}


@respx.mock
def test_graphql_errors_are_rejections(monkeypatch):
    from aisc_connectors.executor import graphql
    from aisc_connectors.importers.graphql import from_introspection
    from aisc_connectors.model import find

    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)
    doc = from_introspection("https://api.acme.test/graphql", introspection()).document
    respx.post("https://api.acme.test/graphql").mock(
        return_value=httpx.Response(200, json={"data": None, "errors": [{"message": "amount too low"}]}))
    conn = {"pid": "p", "document": doc, "auth": {"scheme": "none"}, "settings": {}}
    result = graphql.execute(conn, find(doc, "mutation_score"), call({"amount": 1}), lambda n: None)
    assert result.outcome == "target_rejected"
    assert json.loads(result.body) == {"errors": [{"message": "amount too low"}]}
```

`apps/connectors/tests/test_run.py`:

```python
import json
import uuid

import httpx
import pytest
import respx


@pytest.fixture
def stored(db, monkeypatch):
    """A stored connector with one allowed and one denied operation."""
    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)
    from aisc_connectors import store, vault
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.importers.build import merge
    from aisc_connectors.model import operations

    result = merge([import_curl("curl https://api.acme.test/ok -H 'Authorization: Bearer tk'"),
                    import_curl("curl -X POST https://api.acme.test/danger")])
    row = store.create_connector(uuid.uuid4(), uuid.uuid4(), "Acme", "acme", "curl", "sandbox", "t")
    store.update(row["pid"], document=result.document, auth=result.auth_suggestion,
                 settings={"rate_limit_per_minute": 2})
    vault.put(row["pid"], "token", "tk")
    store.sync_policies(row["pid"], operations(result.document))
    store.update_policy(row["pid"], "get_ok", allowed=True)
    from aisc_connectors.executor.guard import limiter

    limiter._calls.clear()
    return row["pid"]


def call():
    from aisc_connectors.executor.http import Call

    return Call({}, [], {}, None, None)


@respx.mock
def test_an_allowed_operation_runs_with_vault_credentials_and_is_logged(stored):
    from aisc_connectors import store
    from aisc_connectors.executor import run

    route = respx.get("https://api.acme.test/ok").mock(return_value=httpx.Response(200, json={"fine": True}))
    result = run(stored, "get_ok", call(), via="gateway")
    assert result.outcome == "ok"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tk"
    (logged,) = store.recent_calls(stored)
    assert (logged["operation_id"], logged["outcome"], logged["target_status"]) == ("get_ok", "ok", 200)


def test_a_denied_operation_is_not_allowed_and_is_logged(stored):
    from aisc_connectors import store
    from aisc_connectors.executor import run
    from aisc_connectors.executor.errors import GatewayFailure

    with pytest.raises(GatewayFailure) as info:
        run(stored, "post_danger", call(), via="gateway")
    assert info.value.kind == "not_allowed"
    assert store.recent_calls(stored)[0]["outcome"] == "not_allowed"


@respx.mock
def test_the_rate_limit_applies(stored):
    from aisc_connectors.executor import run
    from aisc_connectors.executor.errors import GatewayFailure

    respx.get("https://api.acme.test/ok").mock(return_value=httpx.Response(200))
    run(stored, "get_ok", call(), via="gateway")
    run(stored, "get_ok", call(), via="gateway")
    with pytest.raises(GatewayFailure) as info:
        run(stored, "get_ok", call(), via="gateway")
    assert info.value.kind == "rate_limited"


def test_an_unknown_operation_is_not_allowed(stored):
    from aisc_connectors.executor import run
    from aisc_connectors.executor.errors import GatewayFailure

    with pytest.raises(GatewayFailure) as info:
        run(stored, "nope", call(), via="gateway")
    assert info.value.kind == "not_allowed"
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd apps/connectors && uv run pytest tests/test_executor_soap_graphql.py tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.executor.soap'`.

- [ ] **Step 4: Implement SOAP and GraphQL**

`apps/connectors/aisc_connectors/executor/soap.py`:

```python
"""SOAP through zeep: JSON in, XML envelope out, JSON back."""
from __future__ import annotations

import json
import time

import zeep
from zeep.exceptions import Fault, TransportError
from zeep.helpers import serialize_object
from zeep.transports import Transport

from aisc_connectors.executor import guard
from aisc_connectors.executor.auth import requests_session
from aisc_connectors.executor.errors import GatewayFailure
from aisc_connectors.executor.http import Call, Result
from aisc_connectors.importers.wsdl import wsdl_file
from aisc_connectors.model import server_url


def execute(connector: dict, op, call: Call, secret) -> Result:
    address = server_url(connector["document"])
    guard.check_target(address, address)
    try:
        payload = json.loads(call.body or b"{}")
    except ValueError as exc:
        raise GatewayFailure("invalid_input", "a SOAP operation takes a JSON object") from exc
    options = connector.get("settings") or {}
    session = requests_session(connector["auth"] or {"scheme": "none"}, secret, options.get("verify_tls", True))
    timeout = options.get("timeout_s", 30)
    client = zeep.Client(wsdl_file(connector["document"]["x-aisc-wsdl"]),
                         transport=Transport(session=session, timeout=timeout, operation_timeout=timeout))
    service = client.create_service(op.binding["binding"], address)
    started = time.monotonic()
    try:
        value = serialize_object(service[op.binding["operation"]](**payload), dict)
    except Fault as fault:
        body = json.dumps({"fault": str(fault.message)}).encode()
        return Result("target_rejected", 500, "application/json", body, int((time.monotonic() - started) * 1000))
    except TransportError as exc:
        return Result("target_error", exc.status_code or 502, "text/plain", str(exc).encode(),
                      int((time.monotonic() - started) * 1000))
    except TypeError as exc:
        raise GatewayFailure("invalid_input", f"the SOAP operation does not take these fields: {exc}") from exc
    except Exception as exc:  # requests connection errors and the like
        raise GatewayFailure("connection", f"the SOAP call failed: {exc}") from exc
    body = value if isinstance(value, dict) else {"result": value}
    return Result("ok", 200, "application/json", json.dumps(body, default=str).encode(),
                  int((time.monotonic() - started) * 1000))
```

`apps/connectors/aisc_connectors/executor/graphql.py`:

```python
"""GraphQL: the fixed document of the operation, the call's body as its variables."""
from __future__ import annotations

import json
from dataclasses import replace

from aisc_connectors.executor import http
from aisc_connectors.executor.http import Call, Result
from aisc_connectors.model import Operation


def execute(connector: dict, op: Operation, call: Call, secret, transport=None) -> Result:
    try:
        variables = json.loads(call.body or b"{}")
    except ValueError:
        variables = {}
    binding = op.binding
    request = {"query": binding["document"], "variables": variables, "operationName": binding["field"]}
    endpoint = Operation(op.operation_id, "post", binding["endpoint_path"], op.summary, True,
                         {"protocol": "http", "method": "post", "path": binding["endpoint_path"], "static_headers": {}},
                         {})
    result = http.execute(connector, endpoint, replace(call, body=json.dumps(request).encode(),
                                                       content_type="application/json", query=[], headers={}),
                          secret, transport=transport)
    if result.outcome != "ok":
        return result
    answer = json.loads(result.body or b"{}")
    if answer.get("errors"):
        return Result("target_rejected", result.status, "application/json",
                      json.dumps({"errors": answer["errors"]}).encode(), result.latency_ms)
    data = (answer.get("data") or {}).get(binding["field"])
    return Result("ok", 200, "application/json", json.dumps(data).encode(), result.latency_ms)
```

- [ ] **Step 5: Implement `run` and the call log**

Append to `apps/connectors/aisc_connectors/store.py`:

```python
def log_call(connector_pid, operation_id, token_pid, via, outcome, target_status, latency_ms) -> None:
    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO connector.call_log (connector_pid, operation_id, token_pid, via, outcome, target_status,"
            " latency_ms) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (connector_pid, operation_id, token_pid, via, outcome, target_status, latency_ms),
        )


def recent_calls(connector_pid, limit: int = 50) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT operation_id, via, outcome, target_status, latency_ms, at FROM connector.call_log"
            " WHERE connector_pid = %s ORDER BY at DESC, id DESC LIMIT %s", (connector_pid, limit),
        ).fetchall()
```

`apps/connectors/aisc_connectors/executor/__init__.py`:

```python
"""The one way any operation is executed: policy, rate limit, protocol, patterns, audit (spec D7)."""
from __future__ import annotations

import time

from aisc_connectors import store, vault
from aisc_connectors.executor import graphql as graphql_exec
from aisc_connectors.executor import soap as soap_exec
from aisc_connectors.executor.errors import GatewayFailure
from aisc_connectors.executor.guard import limiter
from aisc_connectors.executor.http import Call, Result
from aisc_connectors.executor.patterns import run_with_patterns
from aisc_connectors.model import find


def run(connector_pid, operation_id: str, call: Call, via: str, token_pid=None, allow_denied: bool = False,
        transport=None) -> Result:
    started = time.monotonic()
    try:
        connector = store.get(connector_pid, with_document=True)
        if connector is None:
            raise GatewayFailure("not_found", "no such connector")
        op = find(connector["document"], operation_id)
        policy = store.policies(connector_pid).get(operation_id)
        if op is None or policy is None or (not policy["allowed"] and not allow_denied):
            raise GatewayFailure("not_allowed", f"{operation_id} is not an allowed operation of this connector")
        per_minute = (connector["settings"] or {}).get("rate_limit_per_minute", 60)
        if not limiter.allow(connector_pid, per_minute):
            raise GatewayFailure("rate_limited", f"more than {per_minute} calls a minute to this connector")
        secret = lambda name: vault.plain(connector_pid, name)  # noqa: E731
        protocol = op.binding.get("protocol")
        if protocol == "soap":
            result = soap_exec.execute(connector, op, call, secret)
        elif protocol == "graphql":
            result = graphql_exec.execute(connector, op, call, secret, transport=transport)
        else:
            result = run_with_patterns(connector, op, call, policy["patterns"] or {}, secret, transport=transport)
    except GatewayFailure as failure:
        store.log_call(connector_pid, operation_id, token_pid, via, failure.kind, None,
                       int((time.monotonic() - started) * 1000))
        raise
    store.log_call(connector_pid, operation_id, token_pid, via, result.outcome, result.status, result.latency_ms)
    return result
```

(`store.get` returns `None` for an unknown pid; `store.policies` of an unknown connector is `{}`.)

- [ ] **Step 6: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_executor_soap_graphql.py tests/test_run.py -v`
Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: SOAP and GraphQL execution, one run() with policy, rate limit and call log"
```

---

### Task 16: "Test" an operation from the admin API

**Files:**
- Modify: `apps/connectors/aisc_connectors/routes_admin.py`
- Test: `apps/connectors/tests/test_admin_test_operation.py`

**Interfaces:**
- Consumes: `executor.run(..., via="admin_test", allow_denied=True)`.
- Produces: `POST /api/v1/connectors/{cid}/operations/{operation_id}/test` with body `{path_params?: {}, query?: {}, headers?: {}, body?: any, body_text?: str, content_type?: str, session_key?: str, confirm_changes_data?: bool}` -> `{outcome, status, latency_ms, content_type, body_json | body_text}` (text truncated to 64 KiB, binary answered as `{"binary": true, "size": n}`); gateway-side failures answer 200 with `{outcome: kind, status: null, message}` so the page can show them; `GET /api/v1/connectors/{cid}/calls` -> recent call log.

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_admin_test_operation.py`:

```python
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.test_admin_connectors import FakeEngine


@pytest.fixture
def api(db, auth_on, monkeypatch):
    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)
    from aisc_connectors import routes_admin
    from aisc_connectors.app import app
    from aisc_connectors.executor.guard import limiter

    limiter._calls.clear()
    engine = FakeEngine()
    app.dependency_overrides[routes_admin.engine_for] = lambda: engine
    yield TestClient(app), engine
    app.dependency_overrides.clear()


@pytest.fixture
def connector(api, as_user):
    client, engine = api
    cid = client.post("/api/v1/connectors", headers=as_user(),
                      json={"project_pid": str(engine.project), "name": "Acme"}).json()["pid"]
    client.post(f"/api/v1/connectors/{cid}/import", headers=as_user(), json={"kind": "manual", "method": "POST",
                "url": "https://api.acme.test/chat", "example_request": '{"q": "hi"}', "operation_id": "chat"})
    return cid


@respx.mock
def test_a_json_answer_is_shown_as_json(api, as_user, connector):
    client, _ = api
    respx.post("https://api.acme.test/chat").mock(return_value=httpx.Response(200, json={"answer": "hello"}))
    shown = client.post(f"/api/v1/connectors/{connector}/operations/chat/test", headers=as_user(),
                        json={"body": {"q": "hi"}, "confirm_changes_data": True}).json()
    assert shown["outcome"] == "ok" and shown["status"] == 200 and shown["body_json"] == {"answer": "hello"}


def test_testing_an_operation_that_changes_data_needs_confirmation(api, as_user, connector):
    client, _ = api
    answer = client.post(f"/api/v1/connectors/{connector}/operations/chat/test", headers=as_user(),
                         json={"body": {"q": "hi"}})
    assert answer.status_code == 409


@respx.mock
def test_html_error_page_is_shown_as_text(api, as_user, connector):
    client, _ = api
    respx.post("https://api.acme.test/chat").mock(
        return_value=httpx.Response(502, text="<html><body>Bad Gateway</body></html>",
                                    headers={"Content-Type": "text/html"}))
    shown = client.post(f"/api/v1/connectors/{connector}/operations/chat/test", headers=as_user(),
                        json={"body": {"q": "hi"}, "confirm_changes_data": True}).json()
    assert shown["outcome"] == "target_error" and shown["status"] == 502
    assert "Bad Gateway" in shown["body_text"]


@respx.mock
def test_a_wrong_key_is_named_auth(api, as_user, connector):
    client, _ = api
    respx.post("https://api.acme.test/chat").mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    shown = client.post(f"/api/v1/connectors/{connector}/operations/chat/test", headers=as_user(),
                        json={"body": {}, "confirm_changes_data": True}).json()
    assert shown["outcome"] == "auth"


@respx.mock
def test_an_unreachable_target_is_named_and_the_call_is_logged(api, as_user, connector):
    client, _ = api
    respx.post("https://api.acme.test/chat").mock(side_effect=httpx.ConnectError("refused"))
    shown = client.post(f"/api/v1/connectors/{connector}/operations/chat/test", headers=as_user(),
                        json={"body": {}, "confirm_changes_data": True}).json()
    assert shown == {"outcome": "connection", "status": None, "message": shown["message"]}
    calls = client.get(f"/api/v1/connectors/{connector}/calls", headers=as_user()).json()
    assert calls[0]["via"] == "admin_test" and calls[0]["outcome"] == "connection"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_admin_test_operation.py -v`
Expected: FAIL with 404 or 405 on `/test`.

- [ ] **Step 3: Implement**

Append to `apps/connectors/aisc_connectors/routes_admin.py`:

```python
import json as _json  # noqa: E402

from aisc_connectors import executor  # noqa: E402
from aisc_connectors.executor.http import Call  # noqa: E402

_TEXT_LIMIT = 64 * 1024


class TestCall(BaseModel):
    path_params: dict[str, str] = {}
    query: dict[str, str] = {}
    headers: dict[str, str] = {}
    body: Any = None
    body_text: str | None = None
    content_type: str | None = None
    session_key: str | None = None
    confirm_changes_data: bool = False


def shown_answer(result) -> dict:
    out = {"outcome": result.outcome, "status": result.status, "latency_ms": result.latency_ms,
           "content_type": result.content_type}
    content_type = (result.content_type or "").lower()
    if "json" in content_type:
        try:
            return {**out, "body_json": _json.loads(result.body or b"null")}
        except ValueError:
            pass
    try:
        return {**out, "body_text": result.body.decode("utf-8")[:_TEXT_LIMIT]}
    except UnicodeDecodeError:
        return {**out, "binary": True, "size": len(result.body)}


@router.post("/{connector_pid}/operations/{operation_id}/test")
def test_operation(connector_pid: uuid.UUID, operation_id: str, body: TestCall,
                   admin: Admin = Depends(admin_call)) -> dict:
    row = _with_document(connector_pid)
    op = find(row["document"], operation_id)
    if op is None:
        raise HTTPException(404, "no such operation")
    if op.changes_data and not body.confirm_changes_data:
        raise HTTPException(409, f"{operation_id} may change data in the target: confirm to test it")
    if body.body_text is not None:
        payload, content_type = body.body_text.encode(), body.content_type or "text/plain"
    elif body.body is not None:
        payload, content_type = _json.dumps(body.body).encode(), body.content_type or "application/json"
    else:
        payload, content_type = None, None
    call = Call(body.path_params, list(body.query.items()), body.headers, payload, content_type, body.session_key)
    try:
        return shown_answer(executor.run(connector_pid, operation_id, call, via="admin_test", allow_denied=True))
    except GatewayFailure as failure:
        return {"outcome": failure.kind, "status": None, "message": failure.message}


@router.get("/{connector_pid}/calls")
def calls(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call)) -> list[dict]:
    loaded(connector_pid)
    return store.recent_calls(connector_pid)
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_admin_test_operation.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: test any operation from the admin API, with readable answers and the call log"
```

---

### Task 17: Access tokens, the unified OpenAPI view and the gateway

**Files:**
- Create: `apps/connectors/aisc_connectors/tokens.py`, `apps/connectors/aisc_connectors/view.py`, `apps/connectors/aisc_connectors/routes_gateway.py`
- Modify: `apps/connectors/aisc_connectors/model.py` (`match`), `apps/connectors/aisc_connectors/app.py` (include the gateway router), `apps/connectors/aisc_connectors/routes_admin.py` (view preview)
- Test: `apps/connectors/tests/test_tokens.py`, `apps/connectors/tests/test_view.py`, `apps/connectors/tests/test_gateway.py`, `apps/connectors/tests/test_model.py` (add matching tests)

**Interfaces:**
- Produces:
  - `tokens.create(connector_pid, label) -> tuple[uuid.UUID, str]` (plaintext starts with `aisc_ct_`, shown once), `tokens.verify(connector_pid, plaintext) -> uuid.UUID | None`, `tokens.revoke(token_pid) -> None`.
  - `model.match(document, method, path, allowed: set[str]) -> tuple[Operation, dict[str, str]] | None` (literal segments beat `{param}` segments; only allowed operations).
  - `view.unified_view(connector: dict, allowed: set[str], gateway_base: str) -> dict`.
  - Gateway routes (all need `Authorization: Bearer <token>` of that connector, else 401): `GET /gw/{cid}/openapi.json`; any method on `/gw/{cid}/{path:path}` -> the target's answer with header `X-AISC-Outcome`. Request header `X-AISC-Session` becomes `Call.session_key`.
  - Admin preview: `GET /api/v1/connectors/{cid}/view` -> the same unified view.

- [ ] **Step 1: Write the failing tests**

`apps/connectors/tests/test_tokens.py`:

```python
import uuid


def connector(db):
    from aisc_connectors import store

    return store.create_connector(uuid.uuid4(), uuid.uuid4(), "T", "t", "manual", "sandbox", "x")["pid"]


def test_a_token_verifies_only_for_its_connector_and_until_revoked(db):
    from aisc_connectors import tokens

    mine, other = connector(db), connector(db)
    pid, plaintext = tokens.create(mine, "plugins")
    assert plaintext.startswith("aisc_ct_")
    assert tokens.verify(mine, plaintext) == pid
    assert tokens.verify(other, plaintext) is None
    assert tokens.verify(mine, plaintext + "x") is None
    tokens.revoke(pid)
    assert tokens.verify(mine, plaintext) is None


def test_the_plaintext_is_not_stored(db):
    from aisc_connectors import tokens

    _, plaintext = tokens.create(connector(db), "plugins")
    with db.connection() as conn:
        stored = conn.execute("SELECT token_hash FROM connector.access_token").fetchone()["token_hash"]
    assert plaintext not in stored
```

Add to `apps/connectors/tests/test_model.py`:

```python
def test_literal_path_beats_template():
    from aisc_connectors.model import match

    document = {"paths": {
        "/users/{id}": {"get": {"operationId": "byId"}},
        "/users/me": {"get": {"operationId": "me"}},
    }}
    op, params = match(document, "GET", "/users/me", {"byId", "me"})
    assert op.operation_id == "me" and params == {}
    op, params = match(document, "GET", "/users/42", {"byId", "me"})
    assert op.operation_id == "byId" and params == {"id": "42"}


def test_match_only_sees_allowed_operations():
    from aisc_connectors.model import match

    document = {"paths": {"/x": {"post": {"operationId": "x"}}}}
    assert match(document, "POST", "/x", set()) is None
    assert match(document, "GET", "/x", {"x"}) is None
```

`apps/connectors/tests/test_view.py`:

```python
import pathlib

from aisc_connectors.importers.openapi import import_openapi

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def mcas():
    doc = import_openapi((FIXTURES / "mcas_openapi.json").read_text(), base_url="http://172.17.0.1:8500").document
    return {"pid": "c1", "name": "MCAS", "document": doc}


def test_the_view_holds_only_allowed_operations_behind_the_gateway():
    from aisc_connectors.model import operations
    from aisc_connectors.view import unified_view

    conn = mcas()
    allowed = {o.operation_id for o in operations(conn["document"]) if o.path in ("/chat", "/score")}
    view = unified_view(conn, allowed, "http://connectors:8097")
    assert set(view["paths"]) == {"/chat", "/score"}
    assert view["servers"] == [{"url": "http://connectors:8097/gw/c1"}]
    assert view["security"] == [{"gateway": []}]
    assert view["components"]["securitySchemes"] == {"gateway": {"type": "http", "scheme": "bearer"}}
    assert "x-aisc" not in str(view)
    assert view["info"]["title"] == "MCAS"
    assert "ScoreRequest" in view["components"]["schemas"]


def test_stream_operations_answer_text_and_events():
    from aisc_connectors.model import operations
    from aisc_connectors.view import unified_view

    conn = mcas()
    chat = next(o for o in operations(conn["document"]) if o.path == "/chat")
    view = unified_view(conn, {chat.operation_id}, "http://g", {chat.operation_id: {"stream": {"format": "sse"}}})
    schema = view["paths"]["/chat"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["properties"] == {"text": {"type": "string"}, "events": {"type": "integer"}}


def test_session_operations_document_the_session_header():
    from aisc_connectors.model import operations
    from aisc_connectors.view import unified_view

    conn = mcas()
    chat = next(o for o in operations(conn["document"]) if o.path == "/chat")
    view = unified_view(conn, {chat.operation_id}, "http://g", {chat.operation_id: {"session": {}}})
    names = [p["name"] for p in view["paths"]["/chat"]["post"]["parameters"]]
    assert "X-AISC-Session" in names
```

`apps/connectors/tests/test_gateway.py`:

```python
import json
import pathlib
import uuid

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def gateway(db, monkeypatch):
    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)
    from aisc_connectors import store, tokens
    from aisc_connectors.app import app
    from aisc_connectors.executor.guard import limiter
    from aisc_connectors.importers.openapi import import_openapi
    from aisc_connectors.model import operations

    limiter._calls.clear()
    doc = import_openapi((FIXTURES / "mcas_openapi.json").read_text(), base_url="http://mcas.test:8500").document
    row = store.create_connector(uuid.uuid4(), uuid.uuid4(), "MCAS", "mcas", "openapi", "sandbox", "t")
    store.update(row["pid"], document=doc)
    store.sync_policies(row["pid"], operations(doc))
    for op in operations(doc):
        if op.path in ("/chat", "/health"):
            store.update_policy(row["pid"], op.operation_id, allowed=True)
    _, token = tokens.create(row["pid"], "plugins")
    return TestClient(app), row["pid"], {"Authorization": f"Bearer {token}"}


def test_no_token_no_gateway(gateway):
    client, cid, _ = gateway
    assert client.get(f"/gw/{cid}/openapi.json").status_code == 401
    assert client.get(f"/gw/{cid}/openapi.json", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_the_view_is_served_to_token_holders(gateway):
    client, cid, auth = gateway
    view = client.get(f"/gw/{cid}/openapi.json", headers=auth).json()
    assert set(view["paths"]) == {"/chat", "/health"}


@respx.mock
def test_a_plugin_calls_the_view_path_and_gets_the_targets_answer(gateway):
    client, cid, auth = gateway
    route = respx.post("http://mcas.test:8500/chat").mock(
        return_value=httpx.Response(200, json={"answer": "Yes, see POL-FAIR-002"}))
    answer = client.post(f"/gw/{cid}/chat", headers=auth, json={"question": "can I ask for a review?"})
    assert answer.status_code == 200
    assert answer.json() == {"answer": "Yes, see POL-FAIR-002"}
    assert answer.headers["X-AISC-Outcome"] == "ok"
    assert json.loads(route.calls[0].request.content) == {"question": "can I ask for a review?"}
    assert "authorization" not in {k.lower() for k in route.calls[0].request.headers.keys()}


@respx.mock
def test_target_errors_pass_through_with_their_kind(gateway):
    client, cid, auth = gateway
    respx.post("http://mcas.test:8500/chat").mock(return_value=httpx.Response(422, json={"detail": "too short"}))
    answer = client.post(f"/gw/{cid}/chat", headers=auth, json={"question": "x"})
    assert answer.status_code == 422
    assert answer.headers["X-AISC-Outcome"] == "target_rejected"


def test_denied_operations_are_403_not_allowed(gateway):
    client, cid, auth = gateway
    answer = client.post(f"/gw/{cid}/halt", headers=auth, json={"reason": "x"})
    assert answer.status_code == 403
    assert answer.json() == {"error": {"kind": "not_allowed", "message": answer.json()["error"]["message"]}}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/connectors && uv run pytest tests/test_tokens.py tests/test_view.py tests/test_gateway.py tests/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aisc_connectors.tokens'`.

- [ ] **Step 3: Implement tokens and matching**

`apps/connectors/aisc_connectors/tokens.py`:

```python
"""Gateway access tokens: shown once, stored as a hash, one connector each, revocable (spec D7)."""
from __future__ import annotations

import hashlib
import secrets
import uuid

from aisc_connectors import db


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create(connector_pid, label: str) -> tuple[uuid.UUID, str]:
    plaintext = "aisc_ct_" + secrets.token_urlsafe(32)
    pid = uuid.uuid4()
    with db.pool().connection() as conn:
        conn.execute("INSERT INTO connector.access_token (pid, connector_pid, token_hash, label)"
                     " VALUES (%s, %s, %s, %s)", (pid, connector_pid, _hash(plaintext), label))
    return pid, plaintext


def verify(connector_pid, plaintext: str | None) -> uuid.UUID | None:
    if not plaintext:
        return None
    with db.pool().connection() as conn:
        row = conn.execute("SELECT pid FROM connector.access_token WHERE token_hash = %s AND connector_pid = %s"
                           " AND revoked_at IS NULL", (_hash(plaintext), connector_pid)).fetchone()
    return None if row is None else row["pid"]


def revoke(token_pid) -> None:
    with db.pool().connection() as conn:
        conn.execute("UPDATE connector.access_token SET revoked_at = now() WHERE pid = %s AND revoked_at IS NULL",
                     (token_pid,))
```

Append to `apps/connectors/aisc_connectors/model.py`:

```python
def match(document: dict, method: str, path: str, allowed: set[str]):
    """The allowed operation a call is for. Literal segments win over {param} segments."""
    wanted = [s for s in path.strip("/").split("/") if s != ""]
    best = None
    for template, item in (document.get("paths") or {}).items():
        op_spec = (item or {}).get(method.lower())
        if not isinstance(op_spec, dict) or op_spec.get("operationId") not in allowed:
            continue
        parts = [s for s in template.strip("/").split("/") if s != ""]
        if len(parts) != len(wanted):
            continue
        params, literals = {}, 0
        for part, value in zip(parts, wanted):
            if part.startswith("{") and part.endswith("}"):
                params[part[1:-1]] = value
            elif part == value:
                literals += 1
            else:
                break
        else:
            if best is None or literals > best[2]:
                best = (op_spec, params, literals, template)
    if best is None:
        return None
    op = find(document, best[0]["operationId"])
    return op, best[1]
```

- [ ] **Step 4: Implement the view and the gateway**

`apps/connectors/aisc_connectors/view.py`:

```python
"""The unified OpenAPI view: what every plugin sees and calls (spec D4)."""
from __future__ import annotations

import copy

from aisc_connectors.model import operations, strip_aisc

_STREAM_ANSWER = {"type": "object", "properties": {"text": {"type": "string"}, "events": {"type": "integer"}}}
_SESSION_HEADER = {"in": "header", "name": "X-AISC-Session", "required": False, "schema": {"type": "string"},
                   "description": "Any value: calls that share it continue the same conversation."}


def unified_view(connector: dict, allowed: set[str], gateway_base: str, patterns: dict | None = None) -> dict:
    patterns = patterns or {}
    source = connector["document"]
    paths: dict = {}
    for op in operations(source):
        if op.operation_id not in allowed:
            continue
        spec = strip_aisc(op.spec)
        spec.pop("security", None)
        spec.pop("servers", None)
        mine = patterns.get(op.operation_id) or {}
        if "stream" in mine:
            spec["responses"] = {"200": {"description": "the streamed answer, joined",
                                         "content": {"application/json": {"schema": _STREAM_ANSWER}}}}
        if "session" in mine:
            spec["parameters"] = [*(spec.get("parameters") or []), _SESSION_HEADER]
        paths.setdefault(op.path, {})[op.method] = spec
    components = copy.deepcopy(strip_aisc(source.get("components") or {}))
    components["securitySchemes"] = {"gateway": {"type": "http", "scheme": "bearer"}}
    return {
        "openapi": "3.1.0",
        "info": {"title": connector["name"], "version": "1",
                 "description": "Reached through the AISC connectors gateway; only allowed operations are listed."},
        "servers": [{"url": f"{gateway_base}/gw/{connector['pid']}"}],
        "security": [{"gateway": []}],
        "paths": paths,
        "components": components,
    }
```

`apps/connectors/aisc_connectors/routes_gateway.py`:

```python
"""/gw: the only door plugins have, on the internal network only (spec D1, D4)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from aisc_connectors import executor, store, tokens
from aisc_connectors.executor.errors import GatewayFailure
from aisc_connectors.executor.http import Call
from aisc_connectors.model import match
from aisc_connectors.settings import settings
from aisc_connectors.view import unified_view

router = APIRouter(prefix="/gw")


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    return value[7:].strip() if value.lower().startswith("bearer ") else None


def _allowed(connector_pid) -> tuple[set[str], dict]:
    policies = store.policies(connector_pid)
    allowed = {op_id for op_id, p in policies.items() if p["allowed"]}
    return allowed, {op_id: p["patterns"] for op_id, p in policies.items()}


def failure_response(failure: GatewayFailure) -> JSONResponse:
    return JSONResponse(failure.body(), status_code=failure.status, headers={"X-AISC-Outcome": failure.kind})


def target_response(result) -> Response:
    return Response(content=result.body, status_code=result.status, media_type=result.content_type,
                    headers={"X-AISC-Outcome": result.outcome})


@router.get("/{connector_pid}/openapi.json")
def view(connector_pid: uuid.UUID, request: Request):
    if tokens.verify(connector_pid, _bearer(request)) is None:
        return JSONResponse({"error": {"kind": "auth", "message": "a connector token is needed"}}, status_code=401)
    connector = store.get(connector_pid, with_document=True)
    allowed, patterns = _allowed(connector_pid)
    return unified_view(connector, allowed, settings().gateway_base_url, patterns)


async def call_from(request: Request, path_params: dict) -> Call:
    body = await request.body()
    return Call(path_params=path_params, query=list(request.query_params.multi_items()),
                headers=dict(request.headers), body=body or None,
                content_type=request.headers.get("content-type"), session_key=request.headers.get("x-aisc-session"))


@router.api_route("/{connector_pid}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def invoke(connector_pid: uuid.UUID, path: str, request: Request):
    token_pid = tokens.verify(connector_pid, _bearer(request))
    if token_pid is None:
        return JSONResponse({"error": {"kind": "auth", "message": "a connector token is needed"}}, status_code=401)
    connector = store.get(connector_pid, with_document=True)
    allowed, _ = _allowed(connector_pid)
    found = match(connector["document"], request.method, "/" + path, allowed)
    if found is None:
        store.log_call(connector_pid, None, token_pid, "gateway", "not_allowed", None, 0)
        return failure_response(GatewayFailure("not_allowed", f"{request.method} /{path} is not an allowed operation"))
    op, path_params = found
    call = await call_from(request, path_params)
    try:
        result = executor.run(connector_pid, op.operation_id, call, via="gateway", token_pid=token_pid)
    except GatewayFailure as failure:
        return failure_response(failure)
    return target_response(result)
```

Note: `executor.run` does blocking I/O. In an `async def` route it would block the event loop, so run it in the threadpool: replace the `executor.run(...)` call with

```python
        from starlette.concurrency import run_in_threadpool

        result = await run_in_threadpool(executor.run, connector_pid, op.operation_id, call, "gateway", token_pid)
```

Modify `apps/connectors/aisc_connectors/app.py`: add

```python
from aisc_connectors import routes_gateway  # noqa: E402

app.include_router(routes_gateway.router)
```

Append to `apps/connectors/aisc_connectors/routes_admin.py`:

```python
from aisc_connectors.settings import settings as _settings  # noqa: E402
from aisc_connectors.view import unified_view  # noqa: E402


@router.get("/{connector_pid}/view")
def view_preview(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call)) -> dict:
    row = _with_document(connector_pid)
    policies = store.policies(connector_pid)
    allowed = {op_id for op_id, p in policies.items() if p["allowed"]}
    return unified_view(row, allowed, _settings().gateway_base_url,
                        {op_id: p["patterns"] for op_id, p in policies.items()})
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_tokens.py tests/test_view.py tests/test_gateway.py tests/test_model.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: access tokens, the unified OpenAPI view and the gateway plugins call"
```

---

### Task 18: OpenAI and Ollama facades

**Files:**
- Create: `apps/connectors/aisc_connectors/facades.py`
- Modify: `apps/connectors/aisc_connectors/app.py` (include the facades router BEFORE the gateway router)
- Test: `apps/connectors/tests/test_facades.py`

**Interfaces:**
- Consumes: the connector's `chat` mapping (Task 12), `executor.run`, `tokens.verify`.
- Produces:
  - `POST /gw/{cid}/openai/v1/chat/completions` (bearer token) -> OpenAI chat completion JSON; `stream: true` -> 422 `invalid_input`.
  - `GET /gw/{cid}/openai/v1/models` (bearer token) -> `{"object": "list", "data": [{"id": <slug>, "object": "model", "owned_by": "aisc-connectors"}]}`.
  - `POST /gw/{cid}/k/{token}/ollama/api/chat` -> Ollama chat JSON `{model, created_at, message: {role, content}, done: true, done_reason: "stop"}`; 404 unless the connector's `settings.ollama_facade` is true.
  - `facades.build_input(chat: dict, messages: list[dict]) -> bytes` and `facades.answer(chat: dict, body: bytes) -> str` (raises `GatewayFailure("bad_mapping")`).

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_facades.py`:

```python
import json
import uuid

import httpx
import pytest
import respx
from fastapi.testclient import TestClient


@pytest.fixture
def chat_connector(db, monkeypatch):
    monkeypatch.setattr("aisc_connectors.executor.guard.refuse_metadata_host", lambda url: None)
    from aisc_connectors import store, tokens
    from aisc_connectors.app import app
    from aisc_connectors.executor.guard import limiter
    from aisc_connectors.importers.manual import import_manual
    from aisc_connectors.model import operations

    limiter._calls.clear()
    doc = import_manual("POST", "http://mcas.test:8500/chat", '{"question": "x"}', '{"answer": "y"}',
                        operation_id="chat").document
    row = store.create_connector(uuid.uuid4(), uuid.uuid4(), "MCAS", "mcas", "manual", "sandbox", "t")
    store.update(row["pid"], document=doc, settings={"ollama_facade": True},
                 chat={"operation_id": "chat", "input_mode": "text", "input_field": "question",
                       "answer_path": "answer", "extra_body": {"request_id": "langbite"}})
    store.sync_policies(row["pid"], operations(doc))
    store.update_policy(row["pid"], "chat", allowed=True)
    _, token = tokens.create(row["pid"], "plugins")
    return TestClient(app), row["pid"], token


@respx.mock
def test_openai_chat_is_mapped_onto_the_chat_operation(chat_connector):
    client, cid, token = chat_connector
    route = respx.post("http://mcas.test:8500/chat").mock(return_value=httpx.Response(200, json={"answer": "No."}))
    answer = client.post(f"/gw/{cid}/openai/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
                         json={"model": "anything", "messages": [{"role": "system", "content": "be brief"},
                                                                 {"role": "user", "content": "Is age used?"}]})
    assert json.loads(route.calls[0].request.content) == {"request_id": "langbite", "question": "Is age used?"}
    body = answer.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "No."}
    assert body["model"] == "mcas"


def test_openai_models_lists_the_connector(chat_connector):
    client, cid, token = chat_connector
    models = client.get(f"/gw/{cid}/openai/v1/models", headers={"Authorization": f"Bearer {token}"}).json()
    assert models["data"][0]["id"] == "mcas"


def test_openai_needs_the_token_and_refuses_streaming(chat_connector):
    client, cid, token = chat_connector
    assert client.post(f"/gw/{cid}/openai/v1/chat/completions", json={"messages": []}).status_code == 401
    streamed = client.post(f"/gw/{cid}/openai/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
                           json={"messages": [{"role": "user", "content": "x"}], "stream": True})
    assert streamed.status_code == 422


@respx.mock
def test_ollama_chat_with_the_token_in_the_path(chat_connector):
    client, cid, token = chat_connector
    respx.post("http://mcas.test:8500/chat").mock(return_value=httpx.Response(200, json={"answer": "Yes."}))
    answer = client.post(f"/gw/{cid}/k/{token}/ollama/api/chat",
                         json={"model": "m", "stream": False, "messages": [{"role": "user", "content": "Q?"}]})
    body = answer.json()
    assert body["message"] == {"role": "assistant", "content": "Yes."}
    assert body["done"] is True


def test_ollama_is_off_unless_enabled(chat_connector):
    from aisc_connectors import store

    client, cid, token = chat_connector
    store.update(cid, settings={"ollama_facade": False})
    assert client.post(f"/gw/{cid}/k/{token}/ollama/api/chat", json={"messages": []}).status_code == 404


@respx.mock
def test_an_answer_without_the_mapped_field_is_bad_mapping(chat_connector):
    client, cid, token = chat_connector
    respx.post("http://mcas.test:8500/chat").mock(return_value=httpx.Response(200, json={"other": 1}))
    answer = client.post(f"/gw/{cid}/openai/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
                         json={"messages": [{"role": "user", "content": "x"}]})
    assert answer.status_code == 502
    assert answer.json()["error"]["kind"] == "bad_mapping"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_facades.py -v`
Expected: FAIL (the catch-all gateway answers 403 `not_allowed` for `/openai/...`).

- [ ] **Step 3: Implement**

`apps/connectors/aisc_connectors/facades.py`:

```python
"""Plugins that only speak LLM chat can still use any connector (spec D4)."""
from __future__ import annotations

import copy
import json
import time
import uuid
from datetime import datetime, timezone

import jmespath
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from aisc_connectors import executor, store, tokens
from aisc_connectors.executor.errors import GatewayFailure
from aisc_connectors.executor.http import Call
from aisc_connectors.routes_gateway import _bearer, failure_response

router = APIRouter(prefix="/gw")


def _set(body: dict, dotted: str, value) -> dict:
    target = body
    keys = dotted.split(".")
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value
    return body


def build_input(chat: dict, messages: list[dict]) -> bytes:
    body = copy.deepcopy(chat.get("extra_body") or {})
    if chat["input_mode"] == "messages":
        value = messages
    else:
        value = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    return json.dumps(_set(body, chat["input_field"], value)).encode()


def answer(chat: dict, body: bytes) -> str:
    try:
        found = jmespath.search(chat["answer_path"], json.loads(body or b"null"))
    except ValueError:
        found = None
    if found is None:
        raise GatewayFailure("bad_mapping", f"the answer has nothing at {chat['answer_path']}")
    return found if isinstance(found, str) else json.dumps(found)


async def _chat(connector_pid, token_pid, messages: list[dict], via: str) -> tuple[dict, str]:
    connector = store.get(connector_pid)
    if connector is None or not connector["chat"]:
        raise GatewayFailure("not_allowed", "this connector has no chat operation")
    chat = connector["chat"]
    call = Call({}, [], {}, build_input(chat, messages), "application/json")
    result = await run_in_threadpool(executor.run, connector_pid, chat["operation_id"], call, via, token_pid)
    if result.outcome != "ok":
        raise GatewayFailure("bad_mapping", f"the chat operation answered {result.status} ({result.outcome})")
    return connector, answer(chat, result.body)


@router.post("/{connector_pid}/openai/v1/chat/completions")
async def openai_chat(connector_pid: uuid.UUID, request: Request):
    token_pid = tokens.verify(connector_pid, _bearer(request))
    if token_pid is None:
        return JSONResponse({"error": {"kind": "auth", "message": "a connector token is needed"}}, status_code=401)
    body = await request.json()
    if body.get("stream"):
        return failure_response(GatewayFailure("invalid_input", "streaming is not offered by this facade"))
    try:
        connector, text = await _chat(connector_pid, token_pid, body.get("messages") or [], "openai_facade")
    except GatewayFailure as failure:
        return failure_response(failure)
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
            "model": connector["slug"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


@router.get("/{connector_pid}/openai/v1/models")
def openai_models(connector_pid: uuid.UUID, request: Request):
    if tokens.verify(connector_pid, _bearer(request)) is None:
        return JSONResponse({"error": {"kind": "auth", "message": "a connector token is needed"}}, status_code=401)
    connector = store.get(connector_pid)
    return {"object": "list", "data": [{"id": connector["slug"], "object": "model", "owned_by": "aisc-connectors"}]}


@router.post("/{connector_pid}/k/{token}/ollama/api/chat")
async def ollama_chat(connector_pid: uuid.UUID, token: str, request: Request):
    connector = store.get(connector_pid)
    if connector is None or not (connector["settings"] or {}).get("ollama_facade"):
        raise HTTPException(404, "not found")
    token_pid = tokens.verify(connector_pid, token)
    if token_pid is None:
        return JSONResponse({"error": "a connector token is needed"}, status_code=401)
    body = await request.json()
    try:
        connector, text = await _chat(connector_pid, token_pid, body.get("messages") or [], "ollama_facade")
    except GatewayFailure as failure:
        return failure_response(failure)
    return {"model": body.get("model") or connector["slug"],
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "message": {"role": "assistant", "content": text}, "done": True, "done_reason": "stop"}
```

Modify `apps/connectors/aisc_connectors/app.py` so the facades are registered before the gateway's catch-all route:

```python
from aisc_connectors import facades, routes_admin, routes_gateway  # noqa: E402

app.include_router(routes_admin.router)
app.include_router(facades.router)
app.include_router(routes_gateway.router)
```

(Remove the earlier separate `include_router` lines for `routes_admin` and `routes_gateway`.)

Also redact the Ollama token from uvicorn's access log: in `apps/connectors/Dockerfile` change the `CMD` to add `"--no-access-log"`, and log gateway calls only through `connector.call_log` (which never stores paths).

- [ ] **Step 4: Run the tests**

Run: `cd apps/connectors && uv run pytest tests/test_facades.py tests/test_gateway.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: OpenAI and Ollama facades onto a connector's chat operation"
```

---

### Task 19: Publish to the AI system, and unpublish

**Files:**
- Create: `apps/connectors/aisc_connectors/publish.py`
- Modify: `apps/connectors/aisc_connectors/store.py` (publication rows), `apps/connectors/aisc_connectors/routes_admin.py` (routes)
- Test: `apps/connectors/tests/test_publish.py`

**Interfaces:**
- Consumes: `engine.EngineClient` (create/delete secret and component), `tokens`, `slug.secret_key`, `settings().gateway_base_url`.
- Produces:
  - `publish.publish(connector: dict, engine) -> dict` -> `{"token": plaintext (once), "secret_key", "view_url", "openai_base_url" | None, "ollama_url" | None, "resource_component_pid", "llm_component_pid" | None}`; on any engine failure it removes what it created, revokes the token and raises `engine.EngineError`.
  - `publish.unpublish(connector: dict, engine) -> None`.
  - `store.save_publication(...)`, `store.publication(connector_pid) -> dict | None`, `store.delete_publication(connector_pid)`.
  - Routes: `POST /api/v1/connectors/{cid}/publish` (409 if already published), `DELETE /api/v1/connectors/{cid}/publish`, `GET /api/v1/connectors/{cid}/publish` -> `{published, view_url, openai_base_url, secret_key, resource_component_pid, llm_component_pid}` (never the token).
  - Deleting a published connector unpublishes it first.

- [ ] **Step 1: Write the failing test**

`apps/connectors/tests/test_publish.py`:

```python
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.test_admin_connectors import FakeEngine


class PublishingEngine(FakeEngine):
    def __init__(self, fail_on=None):
        super().__init__()
        self.secrets, self.created, self.deleted = {}, {}, []
        self.fail_on = fail_on

    def create_secret(self, project_pid, key, name, value):
        pid = str(uuid.uuid4())
        self.secrets[pid] = (key, value)
        return pid

    def delete_secret(self, project_pid, config_pid):
        self.deleted.append(str(config_pid))

    def create_component(self, project_pid, name, component_type, json_value):
        from aisc_connectors.engine import EngineError

        if component_type == self.fail_on:
            raise EngineError(500, "boom")
        pid = str(uuid.uuid4())
        self.created[pid] = (component_type, json_value)
        return pid

    def delete_component(self, component_pid):
        self.deleted.append(str(component_pid))


@pytest.fixture
def setup(db, auth_on):
    from aisc_connectors import routes_admin
    from aisc_connectors.app import app

    engine = PublishingEngine()
    app.dependency_overrides[routes_admin.engine_for] = lambda: engine
    yield TestClient(app), engine
    app.dependency_overrides.clear()


def chat_ready(client, as_user, engine):
    cid = client.post("/api/v1/connectors", headers=as_user(),
                      json={"project_pid": str(engine.project), "name": "MCAS lite"}).json()["pid"]
    client.post(f"/api/v1/connectors/{cid}/import", headers=as_user(), json={
        "kind": "manual", "method": "POST", "url": "http://mcas.test:8500/chat", "example_request": '{"question":"x"}',
        "example_response": '{"answer":"y"}', "operation_id": "chat"})
    client.patch(f"/api/v1/connectors/{cid}/operations/chat", headers=as_user(),
                 json={"allowed": True, "confirm_changes_data": True})
    client.put(f"/api/v1/connectors/{cid}/chat", headers=as_user(), json={
        "operation_id": "chat", "input_mode": "text", "input_field": "question", "answer_path": "answer"})
    return cid


def test_publish_creates_a_secret_a_resource_and_an_llm_component(setup, as_user):
    client, engine = setup
    cid = chat_ready(client, as_user, engine)
    published = client.post(f"/api/v1/connectors/{cid}/publish", headers=as_user()).json()
    assert published["secret_key"] == "CONNECTOR_MCAS_LITE_TOKEN"
    assert published["view_url"] == f"http://connectors:8097/gw/{cid}/openapi.json"
    kinds = {v[0]: v[1] for v in engine.created.values()}
    assert kinds["resource"] == {"value": published["view_url"]}
    assert kinds["llm"] == {"endpoint_url": f"http://connectors:8097/gw/{cid}/openai/v1",
                            "secret_key": "CONNECTOR_MCAS_LITE_TOKEN"}
    ((key, value),) = engine.secrets.values()
    assert key == "CONNECTOR_MCAS_LITE_TOKEN" and value == published["token"]
    from aisc_connectors import tokens

    assert tokens.verify(cid, published["token"]) is not None


def test_the_token_is_shown_once(setup, as_user):
    client, engine = setup
    cid = chat_ready(client, as_user, engine)
    token = client.post(f"/api/v1/connectors/{cid}/publish", headers=as_user()).json()["token"]
    assert token not in client.get(f"/api/v1/connectors/{cid}/publish", headers=as_user()).text
    assert client.post(f"/api/v1/connectors/{cid}/publish", headers=as_user()).status_code == 409


def test_a_failed_publish_leaves_nothing_behind(db, auth_on, as_user):
    from aisc_connectors import routes_admin, tokens
    from aisc_connectors.app import app

    engine = PublishingEngine(fail_on="llm")
    app.dependency_overrides[routes_admin.engine_for] = lambda: engine
    try:
        client = TestClient(app)
        cid = chat_ready(client, as_user, engine)
        assert client.post(f"/api/v1/connectors/{cid}/publish", headers=as_user()).status_code == 502
        assert set(engine.deleted) == set(engine.created) | set(engine.secrets)
        with db.connection() as conn:
            assert conn.execute("SELECT count(*) AS n FROM connector.access_token WHERE revoked_at IS NULL"
                                ).fetchone()["n"] == 0
        assert client.get(f"/api/v1/connectors/{cid}/publish", headers=as_user()).json()["published"] is False
    finally:
        app.dependency_overrides.clear()


def test_unpublish_removes_everything_and_revokes_the_token(setup, as_user):
    client, engine = setup
    cid = chat_ready(client, as_user, engine)
    token = client.post(f"/api/v1/connectors/{cid}/publish", headers=as_user()).json()["token"]
    assert client.delete(f"/api/v1/connectors/{cid}/publish", headers=as_user()).status_code == 204
    assert set(engine.deleted) == set(engine.created) | set(engine.secrets)
    from aisc_connectors import tokens

    assert tokens.verify(cid, token) is None


def test_the_ollama_url_is_offered_only_when_enabled(setup, as_user):
    client, engine = setup
    cid = chat_ready(client, as_user, engine)
    client.patch(f"/api/v1/connectors/{cid}", headers=as_user(), json={"settings": {"ollama_facade": True}})
    published = client.post(f"/api/v1/connectors/{cid}/publish", headers=as_user()).json()
    assert published["ollama_url"] == f"http://connectors:8097/gw/{cid}/k/{published['token']}/ollama"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/connectors && uv run pytest tests/test_publish.py -v`
Expected: FAIL with 404/405 on `/publish`.

- [ ] **Step 3: Implement**

Append to `apps/connectors/aisc_connectors/store.py`:

```python
def save_publication(connector_pid, token_pid, secret_key, secret_config_pid, resource_component_pid,
                     llm_component_pid) -> None:
    with db.pool().connection() as conn:
        conn.execute(
            "INSERT INTO connector.publication (connector_pid, token_pid, secret_key, secret_config_pid,"
            " resource_component_pid, llm_component_pid) VALUES (%s, %s, %s, %s, %s, %s)",
            (connector_pid, token_pid, secret_key, secret_config_pid, resource_component_pid, llm_component_pid),
        )


def publication(connector_pid) -> dict | None:
    with db.pool().connection() as conn:
        return conn.execute("SELECT * FROM connector.publication WHERE connector_pid = %s",
                            (connector_pid,)).fetchone()


def delete_publication(connector_pid) -> None:
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM connector.publication WHERE connector_pid = %s", (connector_pid,))
```

`apps/connectors/aisc_connectors/publish.py`:

```python
"""Publishing a connector: what plugins need, created in the engine through its API (spec D5)."""
from __future__ import annotations

from aisc_connectors import store, tokens
from aisc_connectors.engine import EngineClient, EngineError
from aisc_connectors.settings import settings
from aisc_connectors.slug import secret_key


def urls(connector: dict) -> dict:
    base = f"{settings().gateway_base_url}/gw/{connector['pid']}"
    return {"view_url": f"{base}/openapi.json",
            "openai_base_url": f"{base}/openai/v1" if connector.get("chat") else None}


def publish(connector: dict, engine: EngineClient) -> dict:
    key = secret_key(connector["slug"])
    project = connector["project_pid"]
    links = urls(connector)
    token_pid, token = tokens.create(connector["pid"], "published to the AI system")
    created_components: list[str] = []
    secret_pid = None
    try:
        secret_pid = engine.create_secret(project, key, f"{connector['name']} connector token", token)
        resource = engine.create_component(project, f"{connector['name']} (connector)", "resource",
                                           {"value": links["view_url"]})
        created_components.append(resource)
        llm = None
        if links["openai_base_url"]:
            llm = engine.create_component(project, f"{connector['name']} (connector, chat)", "llm",
                                          {"endpoint_url": links["openai_base_url"], "secret_key": key})
            created_components.append(llm)
    except EngineError:
        for pid in created_components:
            try:
                engine.delete_component(pid)
            except EngineError:
                pass
        if secret_pid:
            try:
                engine.delete_secret(project, secret_pid)
            except EngineError:
                pass
        tokens.revoke(token_pid)
        raise
    store.save_publication(connector["pid"], token_pid, key, secret_pid, resource, llm)
    ollama = None
    if (connector.get("settings") or {}).get("ollama_facade"):
        ollama = f"{settings().gateway_base_url}/gw/{connector['pid']}/k/{token}/ollama"
    return {"token": token, "secret_key": key, **links, "ollama_url": ollama,
            "resource_component_pid": resource, "llm_component_pid": llm}


def unpublish(connector: dict, engine: EngineClient) -> None:
    found = store.publication(connector["pid"])
    if found is None:
        return
    for pid in (found["llm_component_pid"], found["resource_component_pid"]):
        if pid:
            try:
                engine.delete_component(pid)
            except EngineError as exc:
                if exc.status != 404:
                    raise
    try:
        engine.delete_secret(connector["project_pid"], found["secret_config_pid"])
    except EngineError as exc:
        if exc.status != 404:
            raise
    tokens.revoke(found["token_pid"])
    store.delete_publication(connector["pid"])
```

Append to `apps/connectors/aisc_connectors/routes_admin.py`:

```python
from aisc_connectors import publish as publishing  # noqa: E402


@router.post("/{connector_pid}/publish")
def publish_route(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
                  engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    row = loaded(connector_pid)
    if store.publication(connector_pid):
        raise HTTPException(409, "already published: unpublish first to issue a new token")
    try:
        return publishing.publish(row, engine)
    except engine_api.EngineError as exc:
        raise HTTPException(502, f"the engine refused: {exc.detail}")


@router.get("/{connector_pid}/publish")
def publication_route(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call)) -> dict:
    row = loaded(connector_pid)
    found = store.publication(connector_pid)
    if found is None:
        return {"published": False}
    return {"published": True, **publishing.urls(row), "secret_key": found["secret_key"],
            "resource_component_pid": found["resource_component_pid"],
            "llm_component_pid": found["llm_component_pid"]}


@router.delete("/{connector_pid}/publish", status_code=204)
def unpublish_route(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
                    engine: engine_api.EngineClient = Depends(engine_for)) -> Response:
    try:
        publishing.unpublish(loaded(connector_pid), engine)
    except engine_api.EngineError as exc:
        raise HTTPException(502, f"the engine refused: {exc.detail}")
    return Response(status_code=204)
```

In the existing `remove` route (Task 5), before `store.delete(connector_pid)`, add:

```python
    if store.publication(connector_pid) and not orphaned(row, engine):
        publishing.unpublish(row, engine)
```

- [ ] **Step 4: Run the whole suite**

Run: `cd apps/connectors && uv run pytest -v`
Expected: every test passes.

- [ ] **Step 5: Check nothing frozen moved**

Run: `cd ~/aisc-install && GUARD_SOURCE=worktree scripts/guard-frozen.sh --only G1,G3,G4,G5`
Expected: exit status 0, every selected check PASS. (This plan only adds `apps/connectors` and `init/connectors-db.sql`.)

- [ ] **Step 6: Commit**

```bash
git add apps/connectors
git commit -m "Connectors: publish to the AI system through the engine API, and unpublish"
```

---

## Self-review notes (for the reviewer of this plan)

- Spec coverage: D1 (Tasks 1, 2, 17), D2 (Tasks 4, 5, 12), D3 (Tasks 6 to 12, 14, 15), D4 (Tasks 17, 18), D5 (Task 19), D6 (Task 5), D7 (Tasks 3, 4, 13, 15, 17, 18), D8 (Tasks 13, 16, 17). The page, the compose/Caddy wiring and the acceptance run are plan 2.
- Known simplification: rate limits and sessions live in process memory, so the service must run as one replica (stated in `executor/guard.py` and `patterns.py`).
- Known risk carried from the spec: plugins inherit the worker's environment (D7). Not addressed here, by design.
