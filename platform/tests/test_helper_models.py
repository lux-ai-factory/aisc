"""Helper models (judge, attacker, grader, embedder, generator) kept per project: the owner routes,
the store's rules and that a key never leaves in a response, a log or the ledger.

Runs against the throwaway database like test_api_llm.py; the endpoint a Test call reaches is a local stub.
"""
from __future__ import annotations

import ipaddress
import os

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg.conninfo import make_conninfo

from platform_service import helper_store, llm_store, projectdb
from tests.conftest import needs_database, one
from tests.http_stub import Stub
from tests.llm_support import INTERNAL_TOKEN, RISK_TOKEN, SECRETS_KEY

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"   # owns the project, not an admin
BOB = "00000000-0000-0000-0000-0000000000b0"     # an editor
CAROL = "00000000-0000-0000-0000-0000000000c0"   # a viewer
MALLORY = "00000000-0000-0000-0000-0000000000ee"  # a stranger
KEY = "sk-test-123"
ENDPOINT = "https://judge.example.com/v1"


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CARD_AGENT_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("PLATFORM_RISK_MAPPER_TOKEN", RISK_TOKEN)
    monkeypatch.delenv("CONNECTIONS_ALLOWED_HOSTS", raising=False)


@pytest.fixture(autouse=True)
def _names_resolve(monkeypatch):
    """The two hosts the tests name resolve, to a public and to an internal address, so no test needs DNS."""
    from aisc_plugin_interface import connections as client

    real = client._addresses
    known = {"judge.example.com": "93.184.216.34", "postgres": "172.18.0.2"}
    monkeypatch.setattr(client, "_addresses",
                        lambda host, port: [ipaddress.ip_address(known[host])] if host in known else real(host, port))


@pytest.fixture
def project(make_project):
    return make_project(editors=(BOB,), viewers=(CAROL,))


def url(project, name=""):
    return f"/projects/{project['slug']}/helpers" + (f"/{name}" if name else "")


def body(**changes):
    return {"label": "Judge", "endpoint_url": ENDPOINT, "roles": ["judge"], "api_key": KEY, **changes}


def put(client, project, headers, name="judge", **changes):
    return client.put(url(project, name), json=body(**changes), headers=headers)


def listed(client, project, headers):
    r = client.get(url(project), headers=headers)
    assert r.status_code == 200, r.text
    return r


def test_owner_saves_helper_and_key_is_never_returned(client, as_user, project):
    saved = put(client, project, as_user(ALICE))
    assert saved.status_code == 200, saved.text
    after = listed(client, project, as_user(ALICE))
    for r in (saved, after):
        assert KEY not in r.text and "ciphertext" not in r.text
    assert saved.json()["has_key"] is True
    [row] = after.json()["helpers"]
    assert row["name"] == "judge" and row["has_key"] is True
    assert after.json()["can_manage"] is True


def test_key_is_kept_when_omitted_and_cleared_when_empty(client, as_user, project):
    put(client, project, as_user(ALICE))
    kept = client.put(url(project, "judge"), json={"label": "Judge 2", "endpoint_url": ENDPOINT, "roles": ["judge"]},
                      headers=as_user(ALICE))
    assert kept.status_code == 200 and kept.json()["has_key"] is True
    assert kept.json()["label"] == "Judge 2"
    cleared = put(client, project, as_user(ALICE), api_key="")
    assert cleared.status_code == 200 and cleared.json()["has_key"] is False
    assert listed(client, project, as_user(ALICE)).json()["helpers"][0]["has_key"] is False


def test_editor_and_viewer_cannot_save(client, as_user, project):
    assert put(client, project, as_user(BOB)).status_code == 403
    assert put(client, project, as_user(CAROL)).status_code == 403
    assert client.delete(url(project, "judge"), headers=as_user(BOB)).status_code == 403
    viewer = listed(client, project, as_user(CAROL))
    assert viewer.json()["can_manage"] is False
    assert client.get(url(project), headers=as_user(MALLORY)).status_code == 404
    assert put(client, project, as_user(MALLORY)).status_code == 404


def test_a_realm_admin_who_is_not_a_member_can_save(client, as_user, project):
    admin = as_user("root", roles=("admin",))
    assert put(client, project, admin).status_code == 200
    assert listed(client, project, admin).json()["can_manage"] is True


@pytest.mark.parametrize("roles", [[], ["judge", "oracle"], ["Judge"]])
def test_roles_must_be_known_and_not_empty(client, as_user, project, roles):
    assert put(client, project, as_user(ALICE), roles=roles).status_code == 422


def test_name_and_endpoint_are_checked(client, as_user, project):
    assert client.put(url(project, "Not_Valid"), json=body(), headers=as_user(ALICE)).status_code == 422
    assert put(client, project, as_user(ALICE), endpoint_url="ftp://x/v1").status_code == 422
    assert put(client, project, as_user(ALICE), api_key="has space").status_code == 422


def test_list_filters_by_role(client, as_user, project):
    put(client, project, as_user(ALICE), name="a", roles=["judge"])
    put(client, project, as_user(ALICE), name="b", roles=["grader"])
    assert [m["name"] for m in helper_store.list_models(project["pid"], "judge")] == ["a"]
    assert [m["name"] for m in helper_store.list_models(project["pid"])] == ["a", "b"]
    assert all("ciphertext" not in m for m in helper_store.list_models(project["pid"]))


def test_internal_endpoint_is_refused_unless_allowed(client, as_user, project, monkeypatch):
    internal = "http://postgres:5432/v1"
    refused = put(client, project, as_user(ALICE), endpoint_url=internal)
    assert refused.status_code == 422
    assert "internal address" in refused.json()["detail"]
    # the operator's floor is what can allow a host of the stack itself
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", "postgres:5432")
    assert put(client, project, as_user(ALICE), endpoint_url=internal).status_code == 200


def test_a_host_the_project_allows_is_accepted(client, as_user, project):
    private = "http://10.20.30.40:8080/v1"
    assert put(client, project, as_user(ALICE), endpoint_url=private).status_code == 422
    allowed = client.put(f"/projects/{project['slug']}/allowed-hosts/10.20.30.40:8080", json={},
                         headers=as_user(ALICE))
    assert allowed.status_code == 200, allowed.text
    assert put(client, project, as_user(ALICE), endpoint_url=private).status_code == 200


def test_ledger_records_fingerprint_not_key(client, as_user, project, monkeypatch):
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    monkeypatch.setenv("LEDGER_MODE", "record")
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", "v1:" + "a1" * 32)
    assert put(client, project, as_user(ALICE)).status_code == 200
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"]))) as conn:
        row = conn.execute("select details, row_to_json(o)::text from ledger.outbox o"
                           " where action = 'helper.model.saved' order by occurred_at desc limit 1").fetchone()
    assert row, "no helper.model.saved event"
    details, text = row
    assert details["key"] and KEY not in text
    assert details["endpoint_after"] == ENDPOINT and details["roles"] == ["judge"]


def test_rotate_all_rotates_helper_keys(client, as_user, project, dsn, monkeypatch):
    put(client, project, as_user(ALICE))
    before = one(dsn, project, "select ciphertext from helper.model where name = 'judge'")[0]
    newest = Fernet.generate_key().decode()
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", f"{newest},{SECRETS_KEY}")
    counts = llm_store.rotate_all(dsn)
    assert counts["rotated"] >= 1
    after = one(dsn, project, "select ciphertext from helper.model where name = 'judge'")[0]
    assert after != before
    assert Fernet(newest.encode()).decrypt(after.encode()).decode() == KEY


def test_resolve_hands_the_decrypted_key_to_the_store_only(client, as_user, project):
    put(client, project, as_user(ALICE))
    assert helper_store.resolve(project["pid"], "judge") == {
        "label": "Judge", "endpoint_url": ENDPOINT, "roles": ["judge"], "api_key": KEY}
    assert helper_store.resolve(project["pid"], "nobody") is None


def test_removed_helper_is_not_listed_but_kept(client, as_user, project):
    put(client, project, as_user(ALICE))
    assert client.delete(url(project, "judge"), headers=as_user(ALICE)).status_code == 204
    assert listed(client, project, as_user(ALICE)).json()["helpers"] == []
    assert helper_store.get(project["pid"], "judge") is None
    assert helper_store.get(project["pid"], "judge", with_deleted=True)["name"] == "judge"
    assert helper_store.resolve(project["pid"], "judge") is None
    assert client.delete(url(project, "judge"), headers=as_user(ALICE)).status_code == 404


def test_saving_a_removed_helper_again_revives_it(client, as_user, project):
    put(client, project, as_user(ALICE))
    client.delete(url(project, "judge"), headers=as_user(ALICE))
    assert put(client, project, as_user(ALICE)).status_code == 200
    assert [m["name"] for m in listed(client, project, as_user(ALICE)).json()["helpers"]] == ["judge"]


@pytest.fixture
def stub(monkeypatch):
    server = Stub()
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", server.host)
    yield server
    server.close()


def test_helper_test_reports_status_only(client, as_user, project, stub):
    stub.route("POST", "/v1/chat/completions", (401, "secret detail"))
    put(client, project, as_user(ALICE), endpoint_url=f"{stub.base}/v1")
    r = client.post(url(project, "judge") + "/test", json={"model": "gpt-x"}, headers=as_user(ALICE))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "401" in r.json()["detail"] and "secret detail" not in r.text and KEY not in r.text


def test_helper_test_sends_one_small_chat_call(client, as_user, project, stub):
    stub.route("POST", "/v1/chat/completions", (200, {"choices": [{"message": {"content": "OK"}}]}))
    put(client, project, as_user(ALICE), endpoint_url=f"{stub.base}/v1")
    r = client.post(url(project, "judge") + "/test", json={"model": "gpt-x"}, headers=as_user(ALICE))
    assert r.json()["ok"] is True
    [seen] = stub.seen
    assert seen.json["max_tokens"] == 5 and seen.json["model"] == "gpt-x"
    assert seen.json["messages"] == [{"role": "user", "content": "Reply with OK."}]
    assert seen.header("authorization") == f"Bearer {KEY}"
    assert not seen.json.get("stream")


def test_helper_test_needs_a_manager_and_a_saved_helper(client, as_user, project, stub):
    put(client, project, as_user(ALICE), endpoint_url=f"{stub.base}/v1")
    assert client.post(url(project, "judge") + "/test", json={"model": "m"}, headers=as_user(BOB)).status_code == 403
    assert client.post(url(project, "nobody") + "/test", json={"model": "m"},
                       headers=as_user(ALICE)).status_code == 404
