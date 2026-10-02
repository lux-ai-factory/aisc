"""Shared pieces of the ledger tests (docs/superpowers/ledger-2026-10-02/04-test-plan.md).

The ledger is written by the platform alone. These tests use an in-memory ledger for everything but
the immudb store tests, which need a throwaway immudb (LEDGER_TEST_IMMUDB_URL, host:port) and skip
without one, as the database tests skip without a database. Nothing here touches the live stack.
"""
from __future__ import annotations

import os
import uuid

import pytest

IMMUDB_URL = os.environ.get("LEDGER_TEST_IMMUDB_URL")
SUPERUSER_DSN = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")

OWNER = "00000000-0000-0000-0000-0000000000a1"
MEMBER = "00000000-0000-0000-0000-0000000000b2"
STRANGER = "00000000-0000-0000-0000-0000000000c3"


@pytest.fixture
def memory_ledger():
    """The platform's ledger, in memory, for one test."""
    from platform_service import ledger
    from platform_service.ledger.store import MemoryLedger

    store = MemoryLedger()
    previous = ledger.use(store)
    yield store
    ledger.use(previous)


@pytest.fixture(params=["memory", "immudb"])
def any_store(request, tmp_path):
    """Each store test runs on both stores: the behaviour is the contract, not the backend."""
    from platform_service.ledger.store import ImmudbLedger, MemoryLedger

    if request.param == "memory":
        return MemoryLedger()
    if not IMMUDB_URL:
        pytest.skip("LEDGER_TEST_IMMUDB_URL is not set (a throwaway immudb, host:port)")
    return ImmudbLedger(IMMUDB_URL, user="immudb", password=os.environ.get("LEDGER_TEST_IMMUDB_PASSWORD", "immudb"),
                        state_path=tmp_path / "state")


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


def witness_headers(token: str | None, method: str, uri: str, *, dest: str = "empty",
                    host: str = "localhost") -> dict:
    """What Caddy's forward_auth sends to /authz/witness."""
    headers = {"X-Forwarded-Method": method, "X-Forwarded-Uri": uri, "X-Forwarded-Host": host,
               "Sec-Fetch-Dest": dest}
    if token is not None:
        headers["X-Auth-Request-Access-Token"] = token
    return headers


@pytest.fixture
def witnessed(client, token):
    """Send a request through the witness as Caddy would; returns the request id it gave."""
    def run(subject: str, method: str, uri: str, *, username: str | None = None) -> str:
        r = client.get("/authz/witness", headers=witness_headers(token(subject, username=username), method, uri))
        assert r.status_code == 200, r.text
        request_id = r.headers.get("X-AISC-Request-Id")
        assert request_id and uuid.UUID(request_id)
        return request_id
    return run


def entries(store, db: str) -> list:
    """Every entry of one ledger database, oldest first."""
    return store.scan(db, after_seq=0, limit=10_000)
