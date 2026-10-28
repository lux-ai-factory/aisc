"""Connections of an adapter's kind: saved with the adapter's own fields (the secret ones encrypted, never shown),
checked against what the adapter declares, and offered in the list of protocols."""
from __future__ import annotations

import textwrap

import pytest

from platform_service import adapters, targets
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, engine_component
from tests.http_stub import Stub

pytestmark = needs_database

EXAMPLE = '''
PROTOCOL = {
    "name": "example-chat",
    "label": "Example chat site",
    "base_url": "https://chat.example.org",
    "fields": [{"name": "token", "label": "Token", "secret": True, "required": True},
               {"name": "assistant", "label": "Assistant", "required": True},
               {"name": "language", "label": "Language"}],
    "capabilities": ["text", "history"],
}

def call(connection, input, history, params, open):
    return "hello"
'''


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub, tmp_path):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)
    folder = tmp_path / "adapters" / "example"
    folder.mkdir(parents=True)
    (folder / "adapter.py").write_text(textwrap.dedent(EXAMPLE))
    monkeypatch.setenv("PLATFORM_ADAPTERS_DIR", str(tmp_path / "adapters"))
    adapters.reset()
    yield
    adapters.reset()


def example(stub, **over):
    body = {"label": "Example", "kind": "example-chat", "base_url": stub.base, "timeout_s": 5,
            "settings": {"assistant": "a1"}, "secret_settings": {"token": "tok-123"}}
    body.update(over)
    return body


def save(client, admin, project, stub, name="example", **over):
    engine_component(stub, project["pid"])
    return client.put(f"/projects/{project['slug']}/connections/{name}", json=example(stub, **over), headers=admin)


def listed(client, admin, project, name="example"):
    r = client.get(f"/projects/{project['slug']}/connections", headers=admin)
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["connections"] if c["name"] == name), r.text


def test_an_adapter_connection_is_saved_with_its_settings_and_its_secret_masked(client, admin, project, stub):
    r = save(client, admin, project, stub)
    assert r.status_code == 200, r.text
    row, text = listed(client, admin, project)
    assert row["kind"] == "example-chat"
    assert row["settings"] == {"assistant": "a1"}
    assert row["secret_settings"] == ["token"]
    assert "tok-123" not in text and "tok-123" not in r.text


def test_a_secret_setting_absent_from_a_save_is_kept(client, admin, project, stub):
    assert save(client, admin, project, stub).status_code == 200
    body = example(stub)
    del body["secret_settings"]
    r = client.put(f"/projects/{project['slug']}/connections/example", json=body, headers=admin)
    assert r.status_code == 200, r.text
    assert listed(client, admin, project)[0]["secret_settings"] == ["token"]
    r = save(client, admin, project, stub, secret_settings={"token": ""})
    assert r.status_code == 422 and "token" in r.text


@pytest.mark.parametrize("over,named", [
    ({"kind": "nope"}, "kind"),
    ({"path": "/x"}, "path"),
    ({"headers": {"A": "b"}}, "headers"),
    ({"model": "m"}, "model"),
    ({"supports_tools": True}, "supports_tools"),
    ({"secret": "a-key"}, "secret"),
    ({"settings": {"assistant": "a1", "unknown": "x"}}, "unknown"),
    ({"secret_settings": {"token": "t", "other": "x"}}, "other"),
    ({"settings": {"assistant": "a1", "token": "in the clear"}}, "token"),
    ({"settings": {}}, "assistant"),
    ({"settings": {"assistant": "two\nlines"}}, "one line"),
    ({"settings": {"assistant": "x" * 4097}}, "4096"),
], ids=["unknown-kind", "path", "headers", "model", "tools", "single-key", "unknown-field", "unknown-secret",
        "secret-as-plain", "required-missing", "newline", "too-long"])
def test_an_unknown_kind_and_built_in_settings_are_refused(client, admin, project, stub, over, named):
    r = save(client, admin, project, stub, **over)
    assert r.status_code == 422, r.text
    assert named in r.json()["detail"], r.text


def test_adapter_settings_on_a_built_in_kind_are_refused(client, admin, project, stub):
    r = save(client, admin, project, stub, kind="rest", path="/chat", body_template={"q": "{{input}}"},
             response_path="answer", secret_settings=None, settings={"assistant": "a1"})
    assert r.status_code == 422, r.text


def test_a_secret_setting_is_required_on_a_new_connection(client, admin, project, stub):
    body = example(stub)
    del body["secret_settings"]
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/fresh", json=body, headers=admin)
    assert r.status_code == 422 and "token" in r.text


VIEWER = "00000000-0000-0000-0000-0000000000b0"


def test_the_protocols_list_has_the_built_ins_then_the_adapters(client, admin, as_user, make_project):
    project = make_project(viewers=(VIEWER,))
    r = client.get(f"/projects/{project['slug']}/connections/protocols", headers=admin)
    assert r.status_code == 200, r.text
    protocols = r.json()["protocols"]
    assert [p["name"] for p in protocols] == ["openai", "rest", "a2a", "oip", "example-chat"]
    assert protocols[1] == {"name": "rest", "label": "REST API", "adapter": False}
    entry = protocols[-1]
    assert entry["adapter"] is True and entry["label"] == "Example chat site"
    assert [f["name"] for f in entry["fields"]] == ["token", "assistant", "language"]
    assert all("value" not in f for f in entry["fields"])
    viewer = as_user(VIEWER)
    assert client.get(f"/projects/{project['slug']}/connections/protocols", headers=viewer).status_code == 200


def test_a_target_names_the_adapter_protocol():
    assert targets.protocol_name("example-chat") == "Example chat site"
    assert targets.protocol_name("rest") == "REST API"
    assert targets.protocol_name("gone") == "gone"


def test_a_kind_change_never_carries_secrets_from_one_protocol_to_the_other(client, admin, project, stub):
    from platform_service import connection_store
    assert save(client, admin, project, stub).status_code == 200
    # adapter -> REST: the adapter's secret fields do not become headers sent to the system
    rest = {"label": "Example", "kind": "rest", "base_url": stub.base, "path": "/chat",
            "body_template": {"q": "{{input}}"}, "response_path": "answer", "timeout_s": 5}
    r = client.put(f"/projects/{project['slug']}/connections/example", json=rest, headers=admin)
    assert r.status_code == 200, r.text
    row = connection_store.descriptor(project["pid"], "example")
    assert not row.get("secret_header_names") and row.get("secret_headers_ciphertext") is None
    # REST with a key and a secret header -> adapter: neither stays
    rest.update(secret="rest-key", secret_headers={"X-Token": "rest-header"})
    assert client.put(f"/projects/{project['slug']}/connections/example", json=rest, headers=admin).status_code == 200
    assert save(client, admin, project, stub).status_code == 200
    row = connection_store.descriptor(project["pid"], "example")
    assert row.get("secret_header_names") == ["token"]
    assert row.get("secret_ciphertext") is None
