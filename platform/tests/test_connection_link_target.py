"""Linking a connection to a target is its own call, POST /projects/{slug}/connections/{name}/target {key}:
nothing else of the connection is sent, so the Targets page never rebuilds a connection from its list to
link it. The checks are the save's own (one function): the target is the system or a component of the
project, a connection's target is set once, and a target has one connection."""
from __future__ import annotations

import pytest

from platform_service import target_store
from tests.conftest import needs_database, one
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, new_secret
from tests.http_stub import Stub

pytestmark = needs_database
K1 = "0b9c7a1e-0000-4000-8000-000000000011"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)


@pytest.fixture
def project(make_project):
    made = make_project()
    target_store.upsert_component(made["pid"], f"component:{K1}", "Scoring model", "model", 1)
    return made


def make(client, project, name, admin, stub, **over):
    body = {"label": "Chat", "kind": "openai", "base_url": stub.base, "model": "m", "timeout_s": 5,
            "secret": new_secret(), **over}
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def link(client, project, name, headers, key):
    return client.post(f"/projects/{project['slug']}/connections/{name}/target", json={"key": key}, headers=headers)


def test_linking_sets_the_target_and_nothing_else(client, admin, project, stub, dsn):
    made = make(client, project, "chat", admin, stub)
    stored = "select secret_ciphertext, base_url, model from connection.endpoint where name = 'chat'"
    before = one(dsn, project, stored)
    r = link(client, project, "chat", admin, "system")
    assert r.status_code == 200, r.text
    assert r.json()["target"] == {"key": "system", "kind": "system", "label": project["name"]}
    assert one(dsn, project, stored) == before
    assert {k: v for k, v in r.json().items() if k not in ("target", "updated_at")} == \
        {k: v for k, v in made.items() if k not in ("target", "updated_at")}


def test_linking_again_to_the_same_target_is_fine_and_to_another_is_set_once(client, admin, project, stub):
    make(client, project, "chat", admin, stub)
    assert link(client, project, "chat", admin, "system").status_code == 200
    assert link(client, project, "chat", admin, "system").status_code == 200
    moved = link(client, project, "chat", admin, f"component:{K1}")
    assert moved.status_code == 422 and "set once" in moved.json()["detail"]


def test_a_target_with_a_connection_is_refused_naming_it(client, admin, project, stub):
    make(client, project, "chat", admin, stub)
    make(client, project, "api", admin, stub)
    assert link(client, project, "chat", admin, "system").status_code == 200
    taken = link(client, project, "api", admin, "system")
    assert taken.status_code == 409 and "chat" in taken.json()["detail"]


@pytest.mark.parametrize("target", ["nothing", "component:0b9c7a1e-0000-4000-8000-0000000000ff"])
def test_a_target_the_project_does_not_have_is_422(client, admin, project, stub, target):
    make(client, project, "chat", admin, stub)
    assert link(client, project, "chat", admin, target).status_code == 422


def test_an_unknown_connection_is_404(client, admin, project):
    assert link(client, project, "nobody", admin, "system").status_code == 404


def test_only_a_platform_admin_links(client, as_user, project, stub, admin):
    make(client, project, "chat", admin, stub)
    owner = as_user("00000000-0000-0000-0000-00000000a11c")
    assert link(client, project, "chat", owner, "system").status_code == 403


def test_the_body_is_only_the_key(client, admin, project, stub):
    make(client, project, "chat", admin, stub)
    r = client.post(f"/projects/{project['slug']}/connections/chat/target",
                    json={"key": "system", "base_url": "https://elsewhere.example"}, headers=admin)
    assert r.status_code == 422
