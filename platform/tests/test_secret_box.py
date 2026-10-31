"""The platform's encrypted secrets in one place (platform_service.secret_box): the Fernet key list, the
columns rotation walks, rotate's exit code, and the rule that a stored key stays only with the address it
was entered for.

The rule's own cases need no database; the three routes that store a key (an LLM provider, a helper model,
a connection) are checked against the throwaway, with one table.
"""
from __future__ import annotations

import ipaddress

import pytest
from fastapi import HTTPException

from platform_service import secret_box
from tests.conftest import needs_database, one

ALICE = "00000000-0000-0000-0000-00000000a11c"


# The rule: same origin keeps the key, another origin needs it typed again

@pytest.mark.parametrize("before, after", [
    ("https://api.example.com/v1", "https://api.example.com/v2"),          # the path is not the origin
    ("https://api.example.com/v1", "https://API.Example.com./v1"),         # host case, trailing dot
    ("https://api.example.com", "https://api.example.com:443/v1"),         # the default port spelled out
    ("http://api.example.com:80", "http://api.example.com"),
    ("https://bücher.example/v1", "https://xn--bcher-kva.example/v1"),     # the same name, IDNA or not
    ("http://10.0.0.5:8080/a", "http://10.0.0.5:8080/b"),
])
def test_a_stored_key_stays_when_the_origin_is_unchanged(before, after):
    assert secret_box.kept_key(before, after, True) is secret_box.KEEP


@pytest.mark.parametrize("before, after", [
    ("https://api.example.com/v1", "https://evil.example.com/v1"),         # another host
    ("https://api.example.com/v1", "http://api.example.com/v1"),           # another scheme
    ("https://api.example.com/v1", "https://api.example.com:8443/v1"),     # another port
    ("https://api.example.com", "https://api.example.com.evil.net"),
    (None, "https://api.example.com/v1"),                                  # no address before
])
def test_a_stored_key_is_refused_for_another_origin(before, after):
    with pytest.raises(HTTPException) as refused:
        secret_box.kept_key(before, after, True)
    assert refused.value.status_code == 422
    assert "enter the key again" in refused.value.detail


def test_without_a_stored_key_any_address_is_fine():
    assert secret_box.kept_key("https://api.example.com", "https://other.example.net", False) is secret_box.KEEP
    assert secret_box.kept_key(None, "https://other.example.net", False) is secret_box.KEEP


# Rotation

def test_every_encrypted_column_is_rotated():
    """The columns that hold Fernet tokens, each named once; rotate_all walks this list."""
    assert set(secret_box.ENCRYPTED_COLUMNS) == {
        ("llm.provider", "provider", "ciphertext"),
        ("helper.model", "name", "ciphertext"),
        ("connection.endpoint", "name", "secret_ciphertext"),
        ("connection.endpoint", "name", "secret_headers_ciphertext"),
    }


CLEAN = {"rotated": 3, "projects": 1, "unreadable": 0, "without_llm": 0, "unreachable": 0, "changed_meanwhile": 0}


@pytest.mark.parametrize("counts, code", [
    (CLEAN, 0),
    ({**CLEAN, "unreadable": 1}, 1),
    ({**CLEAN, "unreachable": 2}, 1),
])
def test_rotate_fails_while_a_key_may_still_need_the_old_one(monkeypatch, capsys, counts, code):
    """An unreadable key or an unreachable project may still be under the old key: removing it now would lose
    them, so rotate says so and exits 1."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setattr(secret_box, "rotate_all", lambda dsn: dict(counts))
    assert secret_box.main(["rotate"]) == code
    out = capsys.readouterr()
    assert ("do not remove the old key yet" in out.err) is (code == 1)


def test_the_old_entry_point_still_rotates():
    """`python -m platform_service.llm_store rotate` is what the docs and scripts run."""
    from platform_service import llm_store

    assert llm_store.main is secret_box.main
    assert llm_store.rotate_all is secret_box.rotate_all


# The three routes that store a key


@pytest.fixture
def stub():
    from tests.http_stub import Stub

    s = Stub()
    yield s
    s.stop()


@pytest.fixture
def _env(monkeypatch, stub):
    from tests.connection_support import CONNECTIONS_TOKEN
    from tests.llm_support import SECRETS_KEY

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)
    from aisc_plugin_interface import connections as client

    real = client._addresses
    known = {"one.example.com": "93.184.216.34", "two.example.com": "93.184.216.35"}
    monkeypatch.setattr(client, "_addresses",
                        lambda host, port: [ipaddress.ip_address(known[host])] if host in known else real(host, port))


def _llm(client, project, headers, url, key=None):
    body = {"base_url": url, **({"api_key": key} if key else {})}
    return client.put(f"/projects/{project['slug']}/llm/providers/compatible", json=body, headers=headers)


def _helper(client, project, headers, url, key=None):
    body = {"label": "Judge", "endpoint_url": url, "roles": ["judge"], **({"api_key": key} if key else {})}
    return client.put(f"/projects/{project['slug']}/helpers/judge", json=body, headers=headers)


def _connection(client, project, headers, url, key=None):
    body = {"label": "Chat", "kind": "openai", "base_url": url, "model": "m", "timeout_s": 5,
            **({"secret": key} if key else {})}
    return client.put(f"/projects/{project['slug']}/connections/chat", json=body, headers=headers)


ROUTES = {
    "llm provider": (_llm, "select ciphertext from llm.provider where provider = 'compatible'"),
    "helper model": (_helper, "select ciphertext from helper.model where name = 'judge'"),
    "connection": (_connection, "select secret_ciphertext from connection.endpoint where name = 'chat'"),
}


@needs_database
@pytest.mark.parametrize("route", sorted(ROUTES))
def test_each_route_keeps_a_key_only_with_its_origin(client, admin, project, dsn, _env, route):
    from tests.llm_support import new_key

    save, stored = ROUTES[route]
    first = save(client, project, admin, "https://one.example.com/v1", new_key())
    assert first.status_code == 200, first.text
    token = one(dsn, project, stored)[0]

    same_origin = save(client, project, admin, "https://one.example.com/v2")
    assert same_origin.status_code == 200, same_origin.text
    assert one(dsn, project, stored)[0] == token

    moved = save(client, project, admin, "https://two.example.com/v1")
    assert moved.status_code == 422, moved.text
    assert "enter the key again" in moved.json()["detail"]
    assert one(dsn, project, stored)[0] == token, "a refused save changed the stored key"

    retyped = save(client, project, admin, "https://two.example.com/v1", new_key())
    assert retyped.status_code == 200, retyped.text
    assert one(dsn, project, stored)[0] != token


@needs_database
def test_a_connection_keeps_its_secret_headers_only_with_its_origin(client, admin, project, dsn, _env):
    body = {"label": "Chat", "kind": "openai", "base_url": "https://one.example.com/v1", "model": "m",
            "timeout_s": 5, "secret_headers": {"X-Tenant-Key": "tenant-secret-1"}}
    url = f"/projects/{project['slug']}/connections/chat"
    assert client.put(url, json=body, headers=admin).status_code == 200
    moved = client.put(url, json={**body, "base_url": "https://two.example.com/v1", "secret_headers": None},
                       headers=admin)
    assert moved.status_code == 422, moved.text
    resent = client.put(url, json={**body, "base_url": "https://two.example.com/v1"}, headers=admin)
    assert resent.status_code == 200, resent.text
