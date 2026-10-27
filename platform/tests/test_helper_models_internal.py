"""The internal routes for helper models: the engine lists them (no endpoint, no key), the eval worker
resolves one (with its key). Both are for the containers only, each with a token of its own."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN
from tests.llm_support import SECRETS_KEY

pytestmark = needs_database

ENGINE_TOKEN = "engine-helpers-token-for-tests"
KEY = "sk-test-123"
ENDPOINT = "https://judge.example.com/v1"
HEADER = "X-AISC-Service-Token"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    import ipaddress

    from aisc_plugin_interface import connections as client

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)
    monkeypatch.delenv("CONNECTIONS_ALLOWED_HOSTS", raising=False)
    real = client._addresses
    monkeypatch.setattr(client, "_addresses", lambda host, port: [ipaddress.ip_address("93.184.216.34")]
                        if host == "judge.example.com" else real(host, port))


@pytest.fixture
def project(make_project, client, admin):
    made = make_project()
    saved = client.put(f"/projects/{made['slug']}/helpers/judge", headers=admin,
                       json={"label": "Judge", "endpoint_url": ENDPOINT, "roles": ["judge", "grader"], "api_key": KEY})
    assert saved.status_code == 200, saved.text
    return made


def listing(client, pid, token=ENGINE_TOKEN, role="", **headers):
    sent = {HEADER: token, **headers} if token else headers
    return client.get(f"/internal/projects/{pid}/helpers" + (f"?role={role}" if role else ""), headers=sent)


def resolving(client, pid, name="judge", token=CONNECTIONS_TOKEN, **headers):
    sent = {HEADER: token, **headers} if token else headers
    return client.get(f"/internal/projects/{pid}/helpers/{name}/resolve", headers=sent)


def test_engine_list_needs_engine_token(client, project):
    assert listing(client, project["pid"], token=None).status_code in (401, 503)
    assert listing(client, project["pid"], token=CONNECTIONS_TOKEN).status_code == 401
    r = listing(client, project["pid"])
    assert r.status_code == 200, r.text
    [row] = r.json()["helpers"]
    assert row["name"] == "judge" and row["ref"] == f"helper:{project['pid']}/judge"
    assert row["roles"] == ["judge", "grader"] and row["label"] == "Judge"


def test_engine_list_filters_by_role(client, project):
    assert [h["name"] for h in listing(client, project["pid"], role="grader").json()["helpers"]] == ["judge"]
    assert listing(client, project["pid"], role="embedder").json()["helpers"] == []


def test_engine_list_has_no_endpoint_or_key(client, project):
    r = listing(client, project["pid"])
    assert ENDPOINT not in r.text and KEY not in r.text and "ciphertext" not in r.text
    assert r.json()["helpers"][0]["endpoint_host"] == "judge.example.com"
    assert set(r.json()["helpers"][0]) == {"name", "label", "roles", "ref", "endpoint_host"}


def test_resolve_needs_worker_token_and_returns_key(client, project):
    assert resolving(client, project["pid"], token=None).status_code in (401, 503)
    assert resolving(client, project["pid"], token=ENGINE_TOKEN).status_code == 401
    r = resolving(client, project["pid"])
    assert r.status_code == 200, r.text
    assert r.json() == {"label": "Judge", "endpoint_url": ENDPOINT, "roles": ["judge", "grader"], "api_key": KEY}


def test_internal_routes_refuse_forwarded_requests(client, project):
    assert listing(client, project["pid"], **{"X-Forwarded-For": "1.2.3.4"}).status_code == 404
    assert resolving(client, project["pid"], **{"X-Forwarded-For": "1.2.3.4"}).status_code == 404


def test_resolve_removed_helper_is_404(client, admin, project):
    assert resolving(client, project["pid"], name="nobody").status_code == 404
    assert client.delete(f"/projects/{project['slug']}/helpers/judge", headers=admin).status_code == 204
    assert resolving(client, project["pid"]).status_code == 404
    assert listing(client, project["pid"]).json()["helpers"] == []


def test_resolve_unreadable_key_is_409(client, project, monkeypatch):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    r = resolving(client, project["pid"])
    assert r.status_code == 409
    assert r.json() == {"detail": "the stored key for helper judge cannot be decrypted; enter it again"}


def test_unknown_project_is_404(client, project):
    other = "00000000-0000-4000-8000-000000000000"
    assert listing(client, other).status_code == 404
    assert resolving(client, other).status_code == 404


def creating(client, pid, body, token=ENGINE_TOKEN, **headers):
    sent = {HEADER: token, **headers} if token else headers
    return client.post(f"/internal/projects/{pid}/helpers", headers=sent, json=body)


def test_engine_create_route_needs_engine_token_and_refuses_taken_name(client, project):
    pid = project["pid"]
    body = {"name": "old-judge", "label": "Old judge", "endpoint_url": ENDPOINT, "roles": ["judge"],
            "api_key": "sk-moved-456"}
    assert creating(client, pid, body, token=None).status_code in (401, 503)
    assert creating(client, pid, body, token=CONNECTIONS_TOKEN).status_code == 401
    assert creating(client, pid, body, **{"X-Forwarded-For": "1.2.3.4"}).status_code == 404
    assert creating(client, "00000000-0000-4000-8000-000000000000", body).status_code == 404

    made = creating(client, pid, body)
    assert made.status_code == 201, made.text
    assert made.json()["ref"] == f"helper:{pid}/old-judge"
    assert "sk-moved-456" not in made.text and "ciphertext" not in made.text
    assert resolving(client, pid, name="old-judge").json() == {
        "label": "Old judge", "endpoint_url": ENDPOINT, "roles": ["judge"], "api_key": "sk-moved-456"}

    taken = creating(client, pid, {**body, "name": "judge", "api_key": "sk-other"})
    assert taken.status_code == 409
    assert "sk-other" not in taken.text
    assert resolving(client, pid).json()["api_key"] == KEY      # the live helper is left as it was

    assert creating(client, pid, {**body, "name": "Not A Name"}).status_code == 422
    assert creating(client, pid, {**body, "name": "no-roles", "roles": []}).status_code == 422
