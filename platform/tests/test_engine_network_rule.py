"""The engine reads a project's network rule before it sends an LLM component's key anywhere (its model listing).

GET /internal/projects/{pid}/network-rule answers connection_allowlist.rule(pid): the hosts allowed, the addresses
never reached, the floor. Guarded like the other engine routes (never through the gateway), with the engine's token,
PLATFORM_ENGINE_TOKEN. It holds no key."""
from __future__ import annotations

import uuid

import pytest

from platform_service import connection_allowlist
from tests.conftest import needs_database

pytestmark = needs_database
ENGINE_TOKEN = "engine-network-rule-token-for-tests"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)


def rule(client, pid, token=ENGINE_TOKEN, **headers):
    return client.get(f"/internal/projects/{pid}/network-rule", headers={"X-AISC-Service-Token": token, **headers})


def test_the_engine_reads_the_projects_network_rule(client, make_project):
    project = make_project()
    r = rule(client, project["pid"])
    assert r.status_code == 200, r.text
    assert r.json() == connection_allowlist.rule(project["pid"])
    assert set(r.json()) == {"allowed_hosts", "denied_addresses", "floor_hosts"}


def test_another_token_is_refused(client, make_project):
    project = make_project()
    assert rule(client, project["pid"], token="not-the-engine").status_code in (401, 403)
    assert rule(client, project["pid"], token="").status_code in (401, 403)


def test_an_unknown_project_is_404(client):
    assert rule(client, str(uuid.uuid4())).status_code == 404
