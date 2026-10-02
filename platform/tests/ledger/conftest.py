"""Shared pieces of the ledger tests (docs/superpowers/ledger-2026-10-02/04-test-plan.md, spec v2).

The ledger is written by the platform alone. The witness is called the way Caddy calls it, header for
header (06-spike.md G8): the gateway secret, the app named by the handle, the unstripped original URI,
the stripped X-Forwarded-Uri. Witness records live in the platform's Postgres; the relay copies them
and the apps' events into immudb. These tests use an in-memory ledger except the immudb store tests,
which need a throwaway immudb 1.11.1 (LEDGER_TEST_IMMUDB_URL, host:port, and its superuser password in
LEDGER_TEST_IMMUDB_ADMIN_PASSWORD). With LEDGER_TESTS_REQUIRED=1 a missing service fails instead of
skipping (spec section 9). Nothing here touches the live stack.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

IMMUDB_URL = os.environ.get("LEDGER_TEST_IMMUDB_URL")
IMMUDB_ADMIN_PASSWORD = os.environ.get("LEDGER_TEST_IMMUDB_ADMIN_PASSWORD")
SUPERUSER_DSN = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
REQUIRED = os.environ.get("LEDGER_TESTS_REQUIRED") == "1"

GATEWAY_SECRET = "test-gateway-secret-0123456789abcdef"
LEDGER_KEY = "test-ledger-key-0123456789abcdef0123456789"
GATEWAY_CLIENT = "aisc-gateway"

OWNER = "00000000-0000-0000-0000-0000000000a1"
MEMBER = "00000000-0000-0000-0000-0000000000b2"
STRANGER = "00000000-0000-0000-0000-0000000000c3"

#: The site each app is served on, as X-Forwarded-Host shows it (port kept, G1).
HOSTS = {"launcher": "localhost:8100", "platform": "localhost:8100", "schema": "localhost:8100",
         "pgadmin": "localhost:8100", "dashboard": "localhost:8088"}
#: The prefix Caddy's handle_path strips before forward_auth runs (G1).
STRIPPED = {"control_objectives": "/control-objectives", "report_composer": "/report-composer",
            "platform": "/api", "schema": "/inspect/schema"}


def need(condition, reason: str):
    """Skip without a service, or fail when the run says every service is there (spec section 9)."""
    if not condition:
        if REQUIRED:
            pytest.fail(f"LEDGER_TESTS_REQUIRED=1 but {reason}")
        pytest.skip(reason)


@pytest.fixture(autouse=True)
def _ledger_settings(monkeypatch):
    monkeypatch.setenv("AISC_WITNESS_GATEWAY_SECRET", GATEWAY_SECRET)
    monkeypatch.setenv("PLATFORM_LEDGER_KEY", LEDGER_KEY)
    monkeypatch.setenv("AISC_GATEWAY_CLIENT_ID", GATEWAY_CLIENT)


@pytest.fixture
def settings():
    """The named settings (WINDOW, CLOCK_SKEW, ...): tests use them, never the numbers (R6.8)."""
    from platform_service.ledger import settings

    return settings


@pytest.fixture
def memory_ledger():
    """The platform's ledger, in memory, for one test."""
    from platform_service import ledger
    from platform_service.ledger.store import MemoryLedger

    store = MemoryLedger()
    previous = ledger.use(store)
    yield store
    ledger.use(previous)


def fresh_databases(n: int) -> list[str]:
    """New immudb databases made the way the operator's pool script makes them (spec 7.1), with
    aisc_ledger granted RW; unique per test, so a persistent server never shares them (R4.4)."""
    from platform_service.ledger import pool

    names = ["ledger" + uuid.uuid4().hex for _ in range(n)]
    pool.create_databases(IMMUDB_URL, admin_password=IMMUDB_ADMIN_PASSWORD, names=names,
                          grantee="aisc_ledger", grantee_password=LEDGER_USER_PASSWORD)
    return names


LEDGER_USER_PASSWORD = "Ledger-test-pw-123!"


@pytest.fixture(params=["memory", "immudb"])
def any_store(request):
    """Each store test runs on both stores: the behaviour is the contract, not the backend. The immudb
    store logs in as aisc_ledger, never the superuser (R3.1). Returns (store, [db, db])."""
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger, MemoryLedger

    if request.param == "memory":
        store = MemoryLedger()
        dbs = ["ledger" + uuid.uuid4().hex, "ledger" + uuid.uuid4().hex]
        for db in dbs:
            store.create(db)                       # what the pool script does, in memory
        return store, dbs
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD,
         "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set (a throwaway immudb 1.11.1)")
    dbs = fresh_databases(2)
    return ImmudbLedger(IMMUDB_URL, user="aisc_ledger", password=LEDGER_USER_PASSWORD,
                        state_store=MemoryStateStore()), dbs


@pytest.fixture
def mode(monkeypatch):
    """Set LEDGER_MODE for one test: mode('enforce')."""
    return lambda value: monkeypatch.setenv("LEDGER_MODE", value)


@pytest.fixture
def project(client, as_user, unique):
    """A project owned by OWNER with MEMBER as editor: {"pid", "slug"}."""
    made = client.post("/projects", json={"name": unique("ledger")}, headers=as_user(OWNER))
    assert made.status_code == 201, made.text
    p = made.json()
    r = client.post(f"/projects/{p['slug']}/members", json={"subject": MEMBER, "role": "editor"},
                    headers=as_user(OWNER))
    assert r.status_code in (200, 201), r.text
    return {"pid": p["pid"], "slug": p["slug"]}


@pytest.fixture
def gateway_token(key):
    """A token as oauth2-proxy forwards it: issued to the gateway's client (azp)."""
    import jwt

    from tests.conftest import ISSUER

    def make(subject, *, username=None, roles=("primary-user",), **claims):
        body = {"sub": subject, "email": f"{subject}@localhost", "preferred_username": username or subject,
                "iss": ISSUER, "azp": GATEWAY_CLIENT, "exp": int(time.time()) + 300,
                "realm_access": {"roles": list(roles)}}
        body.update(claims)
        return jwt.encode(body, key, algorithm="RS256")
    return make


def caddy_headers(token: str | None, method: str, app: str, original_uri: str, *, gateway=GATEWAY_SECRET,
                  bearer: str | None = None, project_header: str | None = None,
                  next_action: str | None = None) -> dict:
    """Exactly what Caddy's witness forward_auth sends to /authz/witness (06-spike.md G8)."""
    prefix = STRIPPED.get(app, "")
    stripped = original_uri[len(prefix):] if prefix and original_uri.startswith(prefix) else original_uri
    headers = {"X-Forwarded-Method": method, "X-Forwarded-Uri": stripped or "/",
               "X-Forwarded-Host": HOSTS.get(app, "localhost"), "X-Forwarded-Proto": "http",
               "X-AISC-App": app, "X-AISC-Original-Uri": original_uri}
    if gateway is not None:
        headers["X-AISC-Gateway"] = gateway
    if token is not None:
        headers["X-Auth-Request-Access-Token"] = token
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if project_header is not None:
        headers["X-AISC-Project"] = project_header
    if next_action is not None:
        headers["Next-Action"] = next_action
    return headers


def witness_path(original_uri: str) -> str:
    """forward_auth appends the client's query to the witness URI (G10)."""
    _, _, query = original_uri.partition("?")
    return "/authz/witness" + (f"?{query}" if query else "")


@pytest.fixture
def call_witness(client):
    """Call the witness the way Caddy does; returns the response."""
    def run(token, method, app, original_uri, **kw):
        return client.get(witness_path(original_uri), headers=caddy_headers(token, method, app, original_uri, **kw))
    return run


@pytest.fixture
def witnessed(call_witness, gateway_token):
    """A request the witness accepted; returns the request id it gave."""
    def run(subject: str, method: str, app: str, original_uri: str, *, username: str | None = None, **kw) -> str:
        r = call_witness(gateway_token(subject, username=username), method, app, original_uri, **kw)
        assert r.status_code == 200, r.text
        request_id = r.headers.get("X-AISC-Request-Id")
        assert request_id and uuid.UUID(request_id)
        return request_id
    return run


def record(request_id: str):
    """The witness record of one request (platform Postgres, `ledger.witness`), or None."""
    from platform_service.ledger import witness

    return witness.record(request_id)


def person(pid: str | None, actor_ref: str | None):
    """Who an actor reference stands for, while the mapping exists: (sub, name) or None (I10)."""
    from platform_service.ledger import actors

    return actors.resolve(pid, actor_ref)


def relay_all(pid: str | None = None):
    from platform_service.ledger import relay

    return relay.relay_once(pid)


def entries(store, db: str) -> list:
    """Every entry of one ledger database, oldest first."""
    return store.scan(db, after_seq=0, limit=10_000)
