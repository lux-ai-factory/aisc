"""The internal resolve routes answer a connection's descriptor without its key, under a run pass and
under the service token alike. Only the platform's protocol doors (and the Test button) decrypt the
key, to call the system. The fingerprint recorded for a run is the one the plugin-side client computes
from the descriptor it got. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import uuid

import pytest

from platform_service import run_passes
from tests.conftest import needs_database, one
from tests.connection_support import CONNECTIONS_TOKEN, new_secret
from tests.test_run_passes import _env, made_with_endpoints, mint, stub, with_pass  # noqa: F401  (fixtures)

pytestmark = needs_database

PUBLIC_KEYS = {"name", "label", "kind", "base_url", "method", "path", "headers", "secret_header", "body_template",
               "response_path", "refusal", "model", "timeout_s", "protocol_version", "updated_by", "updated_at",
               "target", "has_secret", "allowed_hosts", "denied_addresses"}
LATER_KEYS = {"supports_tools", "supports_logprobs"}


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


def save(client, admin, project, stub, name, secret, target=None, **over):  # noqa: F811
    """Save one of made_with_endpoints' connections again, with this key."""
    body = {"label": name, "kind": "rest", "base_url": stub.base, "path": "/chat",
            "body_template": {"question": "{{input}}"}, "response_path": "answer", "timeout_s": 5,
            "secret": secret}
    if target:
        body["target"] = target
    body.update(over)
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text


def resolve_with_token(client, project, name):
    return client.get(f"/internal/projects/{project['pid']}/connections/{name}",
                      headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})


def test_a_resolve_under_a_run_pass_has_no_secret(client, admin, project, stub):  # noqa: F811
    key = new_secret()
    save(client, admin, project, stub, "system-chat", key, target="system")
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    r = with_pass(client, run_pass, project, "targets/system/connection")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "secret" not in body
    assert body["has_secret"] is True
    assert key not in r.text
    assert set(body) >= PUBLIC_KEYS, PUBLIC_KEYS - set(body)
    assert set(body) - PUBLIC_KEYS <= LATER_KEYS, set(body) - PUBLIC_KEYS


def test_a_resolve_with_the_service_token_has_no_secret(client, admin, project, stub):  # noqa: F811
    key = new_secret()
    save(client, admin, project, stub, "spare", key)
    r = resolve_with_token(client, project, "spare")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "secret" not in body
    assert body["has_secret"] is True
    assert key not in r.text


def test_a_connection_without_a_key_says_so(client, admin, project, stub):  # noqa: F811
    save(client, admin, project, stub, "spare", "")
    r = resolve_with_token(client, project, "spare")
    assert r.status_code == 200, r.text
    assert r.json()["has_secret"] is False


def test_the_fingerprint_is_the_one_the_client_computes(client, admin, project, stub, dsn):  # noqa: F811
    from aisc_plugin_interface.connections import Descriptor

    save(client, admin, project, stub, "system-chat", new_secret(), target="system")
    plugin = str(uuid.uuid4())
    run_pass = client.post("/internal/run-passes",
                           json={"refs": [f"target:{project['pid']}/system"], "evaluation_plugin": plugin},
                           headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN}).json()["pass"]
    r = with_pass(client, run_pass, project, "targets/system/connection")
    assert r.status_code == 200, r.text
    client_side = Descriptor.from_dict(r.json()).fingerprint()
    assert client_side == run_passes.uses_of(plugin)[0]["fingerprint"]
    issued = with_pass(client, run_pass, project, "targets/system/run-keys", "POST")
    assert issued.status_code == 201, issued.text
    stored = one(dsn, project, "select fingerprint from connection.run_key")[0]
    assert stored == client_side


def test_resolve_needs_no_secrets_key(client, admin, project, stub, monkeypatch):  # noqa: F811
    save(client, admin, project, stub, "system-chat", new_secret(), target="system")
    monkeypatch.delenv("PLATFORM_SECRETS_KEY")
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    r = with_pass(client, run_pass, project, "targets/system/connection")
    assert r.status_code == 200, r.text
    assert r.json()["has_secret"] is True
    issued = with_pass(client, run_pass, project, "targets/system/run-keys", "POST")
    assert issued.status_code == 201, issued.text


def test_the_facade_still_calls_with_the_key(client, admin, project, stub):  # noqa: F811
    key = new_secret()
    save(client, admin, project, stub, "system-chat", key, target="system",
         secret_header="Authorization: Bearer {{secret}}")
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    run_key = with_pass(client, run_pass, project, "targets/system/run-keys", "POST").json()["key"]
    r = client.post(f"/internal/facade/{project['pid']}/system-chat/aisc/ask", json={"input": "q"},
                    headers={"Authorization": f"Bearer {run_key}"})
    assert r.status_code == 200, r.text
    assert stub.requests("POST", "/chat")[-1]["headers"]["authorization"] == f"Bearer {key}"
