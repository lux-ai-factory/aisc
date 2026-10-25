"""Credentials in headers of a connection's own choosing (X-Token and the like): marked secret, stored
as one Fernet token, sent with every call, never answered back (their names are, their values are
masked as *** in the descriptor), scrubbed from every error text, rotated with the key and named
(never valued) in the ledger. A plain header whose name looks like a credential is refused. Runs on
the throwaway; the system under test is a local stub."""
from __future__ import annotations

import json
import os
import shutil
import uuid

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg.conninfo import make_conninfo

from platform_service import connection_store, db, llm_store, projectdb
from tests.conftest import ALICE, needs_database, one, project_db
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, new_secret
from tests.test_connections import _env, base, put, resolve, rest_body, stub  # noqa: F401  (fixtures)

pytestmark = needs_database

NAME = "mcas-chat"


@pytest.fixture
def T():
    return "tok-" + uuid.uuid4().hex


def saved(client, admin, project, stub, **over):  # noqa: F811
    r = put(client, project, NAME, admin, rest_body(stub, **over))
    assert r.status_code == 200, r.text
    return r


def stored(dsn, project):
    return one(dsn, project, "select secret_header_names, secret_headers_ciphertext, headers"
                             " from connection.endpoint where name = %s", (NAME,))


def decrypted(ciphertext):
    return json.loads(Fernet(SECRETS_KEY.encode()).decrypt(ciphertext.encode()))


def token_key(client, project):
    r = client.post(f"/internal/projects/{project['pid']}/connections/{NAME}/run-keys",
                    headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 201, r.text
    return r


def ask(client, project, key):
    return client.post(f"/internal/facade/{project['pid']}/{NAME}/aisc/ask", json={"input": "q"},
                       headers={"Authorization": f"Bearer {key}"})


def test_a_secret_header_is_stored_encrypted(client, admin, project, stub, dsn, T):  # noqa: F811
    r = saved(client, admin, project, stub, secret_headers={"X-Token": T})
    body = r.json()
    assert body["secret_headers"] == ["X-Token"]
    assert body["headers"] == {"X-Client": "aisc"}
    assert T not in r.text
    names, ciphertext, headers = stored(dsn, project)
    assert names == ["X-Token"]
    assert decrypted(ciphertext) == {"X-Token": T}
    rows = one(dsn, project, "select string_agg(row_to_json(e)::text, '') from connection.endpoint e")[0]
    assert T not in rows
    assert "X-Token" not in headers


def test_the_call_carries_it(client, admin, project, stub, T):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    saved(client, admin, project, stub, secret_headers={"X-Token": T})
    key = token_key(client, project).json()["key"]
    assert ask(client, project, key).status_code == 200
    assert stub.requests("POST", "/chat")[-1]["headers"]["x-token"] == T
    tried = client.post(f"{base(project)}/{NAME}/test", json={}, headers=admin)
    assert tried.status_code == 200 and tried.json()["ok"] is True, tried.text
    assert stub.requests("POST", "/chat")[-1]["headers"]["x-token"] == T


def test_resolve_masks_it(client, admin, project, stub, dsn, T):  # noqa: F811
    from aisc_plugin_interface.connections import Descriptor

    saved(client, admin, project, stub, secret_headers={"X-Token": T})
    run_pass = client.post("/internal/run-passes", json={"refs": [f"connection:{project['pid']}/{NAME}"]},
                           headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN}).json()["pass"]
    answers = [resolve(client, project, NAME),
               client.get(f"/internal/projects/{project['pid']}/connections/{NAME}",
                          headers={"X-AISC-Run-Pass": run_pass})]
    token_key(client, project)
    fingerprint = one(dsn, project, "select fingerprint from connection.run_key")[0]
    for r in answers:
        assert r.status_code == 200, r.text
        assert r.json()["headers"] == {"X-Client": "aisc", "X-Token": "***"}
        assert T not in r.text
        assert Descriptor.from_dict(r.json()).fingerprint() == fingerprint


def test_absent_keeps_empty_removes_and_others_merge(client, admin, project, stub, dsn, T):  # noqa: F811
    saved(client, admin, project, stub, secret_headers={"X-Token": T})
    assert saved(client, admin, project, stub).json()["secret_headers"] == ["X-Token"]
    assert saved(client, admin, project, stub, secret_headers=None).json()["secret_headers"] == ["X-Token"]
    assert saved(client, admin, project, stub, secret_headers={"X-Other": "v"}).json()["secret_headers"] == \
        ["X-Other", "X-Token"]
    names, ciphertext, _ = stored(dsn, project)
    assert names == ["X-Other", "X-Token"] and decrypted(ciphertext) == {"X-Other": "v", "X-Token": T}
    assert saved(client, admin, project, stub, secret_headers={"X-Token": ""}).json()["secret_headers"] == ["X-Other"]
    assert decrypted(stored(dsn, project)[1]) == {"X-Other": "v"}
    assert saved(client, admin, project, stub, secret_headers={"X-Other": ""}).json()["secret_headers"] == []
    names, ciphertext, _ = stored(dsn, project)
    assert names == [] and ciphertext is None
    assert saved(client, admin, project, stub, secret_headers={"X-Never": ""}).json()["secret_headers"] == []
    assert stored(dsn, project)[:2] == ([], None)


@pytest.mark.parametrize("over,detail", [
    ({"secret_headers": {"X Token": "v"}}, "secret_headers: 'X Token' is not a header name"),
    ({"secret_headers": {"X-Token": "a\nb"}}, "secret_headers: X-Token: a header value on one line, up to 4096 characters"),
    ({"secret_headers": {"X-Token": "x" * 4097}},
     "secret_headers: X-Token: a header value on one line, up to 4096 characters"),
    # a plain header name that does not look like a credential: x-token would be refused as one first
    ({"headers": {"x-tenant": "a"}, "secret_headers": {"X-Tenant": "v"}}, "secret_headers: X-Tenant is also a plain header"),
    ({"secret_headers": {"Authorization": "v"}, "secret_header": "Authorization: Bearer {{secret}}"},
     "secret_headers: Authorization is where the key goes (secret_header)"),
    ({"secret_headers": {f"X-H{i}": "v" for i in range(21)}}, "secret_headers: up to 20"),
], ids=["name", "newline", "long", "also-plain", "key-header", "too-many"])
def test_bad_secret_headers_are_422(client, admin, project, stub, dsn, over, detail):  # noqa: F811
    r = put(client, project, NAME, admin, rest_body(stub, **over))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == detail
    assert one(dsn, project, "select count(*) from connection.endpoint")[0] == 0


@pytest.mark.parametrize("name", ["X-Session-Token", "X-Auth", "X-Secret", "X-Signature"])
def test_a_credential_looking_plain_header_is_refused(client, admin, project, stub, name):  # noqa: F811
    r = put(client, project, NAME, admin, rest_body(stub, headers={name: "v"}))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == f"headers: {name} looks like a credential; mark it secret (secret_headers)"


def test_the_named_credential_headers_keep_their_message_and_others_pass(client, admin, project, stub):  # noqa: F811
    r = put(client, project, NAME, admin, rest_body(stub, headers={"X-Api-Key": "v"}))
    assert r.status_code == 422 and r.json()["detail"] == "headers: X-Api-Key carries a credential; put it in secret_header"
    assert put(client, project, NAME, admin, rest_body(stub, headers={"X-Client": "v"})).status_code == 200


def test_an_echoed_header_value_is_scrubbed(client, admin, project, stub, dsn, T):  # noqa: F811
    stub.route("POST", "/chat", (422, {"echo": T}))
    saved(client, admin, project, stub, secret_headers={"X-Token": T})
    key = token_key(client, project).json()["key"]
    r = ask(client, project, key)
    assert r.status_code == 502, r.text
    assert "***" in r.json()["detail"] and T not in r.text
    tried = client.post(f"{base(project)}/{NAME}/test", json={}, headers=admin)
    assert tried.json()["ok"] is False and T not in tried.text
    detail = one(dsn, project, "select last_test_detail from connection.endpoint where name = %s", (NAME,))[0]
    assert detail and T not in detail


def test_no_route_answers_the_value_or_its_ciphertext(client, admin, project, stub, dsn, T):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    answers = [saved(client, admin, project, stub, secret_headers={"X-Token": T}, secret=new_secret()).text,
               client.get(base(project), headers=admin).text,
               client.post(f"{base(project)}/{NAME}/test", json={}, headers=admin).text,
               resolve(client, project, NAME).text,
               token_key(client, project).text]
    ciphertext = stored(dsn, project)[1]
    assert ciphertext
    for text in answers:
        assert T not in text and ciphertext not in text and "secret_headers_ciphertext" not in text


def test_rotation_rotates_the_header_set(client, admin, project, stub, dsn, monkeypatch, T):  # noqa: F811
    saved(client, admin, project, stub, secret_headers={"X-Token": T}, secret=new_secret())
    before = stored(dsn, project)[1]
    newest = Fernet.generate_key().decode()
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", f"{newest},{SECRETS_KEY}")
    multi = llm_store.fernet()
    with project_db(dsn, project) as conn:
        counts = connection_store.rotate(conn, multi)
    assert counts == (2, 0, 0)
    after = stored(dsn, project)[1]
    assert after != before
    assert json.loads(Fernet(newest.encode()).decrypt(after.encode())) == {"X-Token": T}


def test_the_ledger_says_the_headers_changed_never_their_value(client, admin, project, stub, monkeypatch, T):  # noqa: F811
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    monkeypatch.setenv("LEDGER_MODE", "record")
    saved(client, admin, project, stub, secret_headers={"X-Token": T})
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"]))) as conn:
        row = conn.execute("select details, row_to_json(o)::text from ledger.outbox o"
                           " where action = 'connection.saved' order by occurred_at desc limit 1").fetchone()
    assert row, "no connection.saved event"
    details, text = row
    assert "secret_headers" in details["changed"]
    assert T not in text


def test_a_project_made_before_secret_headers_gets_them_at_the_next_start(client, as_user, unique, dsn, monkeypatch,
                                                                          tmp_path, stub):  # noqa: F811
    old = tmp_path / "template"
    old.mkdir()
    for f in sorted(projectdb.TEMPLATE.glob("*.sql")):
        if f.name < "0023":
            shutil.copy(f, old / f.name)
    real = projectdb.TEMPLATE
    monkeypatch.setattr(projectdb, "TEMPLATE", old)
    made = client.post("/projects", json={"name": unique("pre-headers")}, headers=as_user(ALICE)).json()
    column = ("select count(*) from information_schema.columns where table_schema = 'connection'"
              " and table_name = 'endpoint' and column_name in ('secret_header_names', 'secret_headers_ciphertext')")
    assert one(dsn, made, column) == (0,)
    with project_db(dsn, made) as conn:
        conn.execute("insert into connection.endpoint (name, label, kind, base_url, path, body_template,"
                     " response_path, timeout_s, secret_ciphertext) values (%s, 'Old', 'rest', %s, '/chat', %s, 'answer',"
                     " 5, %s)", (NAME, stub.base, json.dumps({"question": "{{input}}"}), llm_store.encrypt(new_secret())))
    monkeypatch.setattr(projectdb, "TEMPLATE", real)
    monkeypatch.setattr(db, "_unprovisioned", None)
    db.pool()
    assert one(dsn, made, column) == (2,)
    assert one(dsn, made, "select secret_header_names, secret_headers_ciphertext from connection.endpoint"
                          " where name = %s", (NAME,)) == ([], None)
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    assert resolve(client, made, NAME).status_code == 200
    key = token_key(client, made).json()["key"]
    assert ask(client, made, key).status_code == 200
