"""The engine asks whether a card target can be reached, before it stores an evaluation of it.

GET /internal/projects/{pid}/targets/{key}/reachable answers {"connected", "protocol"} and never a
key: the engine refuses a run whose plugin calls a target that has no connection. Guarded like the
other internal routes (never through the gateway), with a token of the engine's own,
PLATFORM_ENGINE_TOKEN. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import uuid

import pytest

from platform_service import target_store
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, new_secret
from tests.http_stub import Stub

pytestmark = needs_database
ENGINE_TOKEN = "engine-reachable-token-for-tests"
K1 = "0b9c7a1e-0000-4000-8000-000000000001"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)


@pytest.fixture
def project(make_project):
    made = make_project()
    target_store.upsert_component(made["pid"], f"component:{K1}", "Scoring model", "model", 1)
    return made


def connect_system(client, project, admin, stub):
    b = {"label": "MCAS chat", "kind": "rest", "base_url": stub.base, "path": "/chat",
         "body_template": {"question": "{{input}}"}, "response_path": "answer", "timeout_s": 5,
         "secret": new_secret(), "target": "system"}
    r = client.put(f"/projects/{project['slug']}/connections/mcas-chat", json=b, headers=admin)
    assert r.status_code in (200, 201), r.text


def reachable(client, pid, key, token=ENGINE_TOKEN, **headers):
    return client.get(f"/internal/projects/{pid}/targets/{key}/reachable",
                      headers={"X-AISC-Service-Token": token, **headers})


def test_a_connected_target_says_so_with_its_protocol_and_no_key(client, admin, project, stub):
    connect_system(client, project, admin, stub)
    r = reachable(client, project["pid"], "system")
    assert r.status_code == 200, r.text
    assert r.json() == {"connected": True, "protocol": "rest"}


def test_a_target_without_a_connection_says_so(client, project):
    r = reachable(client, project["pid"], f"component:{K1}")
    assert r.status_code == 200, r.text
    assert r.json() == {"connected": False, "protocol": None}


def test_an_unknown_target_is_404(client, project):
    assert reachable(client, project["pid"], f"component:{uuid.uuid4()}").status_code == 404
    assert reachable(client, project["pid"], "not-a-key").status_code == 404


def test_an_unknown_project_is_404(client):
    assert reachable(client, str(uuid.uuid4()), "system").status_code == 404


def test_the_engine_token_is_needed(client, project):
    assert reachable(client, project["pid"], "system", token="wrong").status_code == 401
    # the connections token is the worker's, not the engine's
    assert reachable(client, project["pid"], "system", token=CONNECTIONS_TOKEN).status_code == 401


def test_not_through_the_gateway(client, project):
    assert reachable(client, project["pid"], "system", **{"X-Forwarded-For": "1.2.3.4"}).status_code == 404


def test_closed_without_the_engine_token(client, project, monkeypatch):
    monkeypatch.delenv("PLATFORM_ENGINE_TOKEN")
    assert reachable(client, project["pid"], "system").status_code == 503
