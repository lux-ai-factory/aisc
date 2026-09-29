"""Manage → Connections on the platform (connections plan 2026-09-29, tests P1 to P10).

The systems a project assesses over the network live in the `connection` schema of the project's
database, owned by the platform like `llm`; the key is Fernet ciphertext, written and never read
back; an admin tests a connection with one probe; the engine sees it as a `resource` component
`connection:<pid>/<name>`, which the platform creates with the admin's own token; the plugin-side
client resolves it on the internal route with PLATFORM_CONNECTIONS_TOKEN. Runs on the throwaway."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, Stub, engine_component, new_secret

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
PLATFORM_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = projectdb.TEMPLATE / "0012_connection.sql"


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
def admin(as_user):
    return as_user("root", roles=("admin",))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("conn")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()


def base(project):
    return f"/projects/{project['slug']}/connections"


def rest_body(stub, **over):
    body = {"label": "MCAS chat", "kind": "rest", "base_url": stub.base, "method": "POST", "path": "/chat",
            "headers": {"X-Client": "aisc"}, "secret_header": "Authorization: Bearer {{secret}}",
            "body_template": {"question": "{{input}}", "history": "{{history}}"}, "response_path": "answer",
            "refusal": {"status": [502], "path": "detail.reason", "match": {"detail.error": "answer_not_grounded"}},
            "timeout_s": 5}
    body.update(over)
    return body


def put(client, project, name, headers, body):
    return client.put(f"{base(project)}/{name}", json=body, headers=headers)


def connect(dsn, project, role=None):
    name = projectdb.database_name(project["pid"])
    if role is None:
        return psycopg.connect(make_conninfo(dsn, dbname=name))
    return psycopg.connect(make_conninfo(dsn, dbname=name, user=role, password=role), autocommit=True)


def one(dsn, project, sql, params=()):
    with connect(dsn, project) as conn:
        return conn.execute(sql, params).fetchone()


def resolve(client, project, name, token=CONNECTIONS_TOKEN, headers=None):
    return client.get(f"/internal/projects/{project['pid']}/connections/{name}",
                      headers={"X-AISC-Service-Token": token, **(headers or {})})


# ── P1 the template file ────────────────────────────────────────────────────

def test_p1_the_template_file_exists_and_is_idempotent_sql():
    assert TEMPLATE_FILE.is_file(), "missing platform/project-template/0012_connection.sql"
    text = TEMPLATE_FILE.read_text()
    creates = re.findall(r"\bCREATE\s+(?:SCHEMA|TABLE|INDEX|UNIQUE\s+INDEX)\b(?!\s+IF\s+NOT\s+EXISTS)", text, re.I)
    assert creates == [], creates
    assert not re.search(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", text, re.I | re.M)


def test_p1_a_new_project_gets_the_schema_and_applying_again_changes_nothing(project, dsn):
    assert one(dsn, project, "select to_regclass('connection.endpoint')") == ("connection.endpoint",)
    assert one(dsn, project, "select 1 from provision.template_migration where name = '0012_connection.sql'")
    with connect(dsn, project) as conn, conn.transaction():
        conn.execute(TEMPLATE_FILE.read_text())


def test_p1_the_schema_is_the_platforms_and_closed_to_everyone_else(project, dsn):
    owner, acl = one(dsn, project, "select pg_get_userbyid(nspowner), nspacl::text from pg_namespace"
                                   " where nspname = 'connection'")
    assert owner == "platform_rw"
    assert set(re.findall(r'(?:^|[{,])"?([^=,{}"]*)=', acl or "")) <= {"platform_rw"}, acl


@pytest.mark.parametrize("role", ["controls_rw", "dashboard_ro", "report_ro", "engine_rw"])
def test_p1_module_and_reader_roles_cannot_read_it(project, dsn, role):
    try:
        conn = connect(dsn, project, role)
    except psycopg.OperationalError as exc:
        if "does not exist" in str(exc) or "password authentication" in str(exc):
            pytest.skip(f"{role} is not in this throwaway database")
        raise
    with conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select * from connection.endpoint")


# ── P7 existing projects get it ─────────────────────────────────────────────

def test_p7_a_project_made_before_0012_gets_it_at_the_next_start(client, as_user, unique, dsn, monkeypatch, tmp_path):
    import shutil
    old = tmp_path / "template"
    old.mkdir()
    for f in sorted(projectdb.TEMPLATE.glob("*.sql")):
        if f.name < "0012":
            shutil.copy(f, old / f.name)
    real = projectdb.TEMPLATE
    monkeypatch.setattr(projectdb, "TEMPLATE", old)
    made = client.post("/projects", json={"name": unique("pre12")}, headers=as_user(ALICE)).json()
    assert one(dsn, made, "select to_regnamespace('connection')") == (None,)
    monkeypatch.setattr(projectdb, "TEMPLATE", real)
    monkeypatch.setattr(db, "_unprovisioned", None)
    db.pool()
    assert one(dsn, made, "select to_regclass('connection.endpoint')") == ("connection.endpoint",)


# ── P3 routes and who may use them ──────────────────────────────────────────

def test_p3_a_member_who_is_not_an_admin_gets_403_everywhere(client, as_user, project, stub):
    alice = as_user(ALICE)
    assert client.get(base(project), headers=alice).status_code == 403
    assert put(client, project, "mcas-chat", alice, rest_body(stub)).status_code == 403
    assert client.post(f"{base(project)}/mcas-chat/test", json={}, headers=alice).status_code == 403
    assert client.delete(f"{base(project)}/mcas-chat", headers=alice).status_code == 403


def test_p3_a_stranger_gets_404(client, as_user, project):
    assert client.get(base(project), headers=as_user("00000000-0000-0000-0000-00000000beef")).status_code == 404


def test_p3_an_admin_creates_reads_updates_and_deletes(client, admin, project, stub):
    engine_component(stub, project["pid"])
    made = put(client, project, "mcas-chat", admin, rest_body(stub, secret=new_secret()))
    assert made.status_code == 200, made.text
    got = client.get(base(project), headers=admin).json()["connections"]
    assert [c["name"] for c in got] == ["mcas-chat"] and got[0]["has_secret"] is True
    assert got[0]["label"] == "MCAS chat" and got[0]["kind"] == "rest" and got[0]["updated_by"] == "root"
    again = put(client, project, "mcas-chat", admin, rest_body(stub, label="MCAS assistant", timeout_s=9))
    assert again.status_code == 200 and again.json()["timeout_s"] == 9 and again.json()["has_secret"] is True
    assert client.delete(f"{base(project)}/mcas-chat", headers=admin).status_code == 204
    assert client.get(base(project), headers=admin).json()["connections"] == []


@pytest.mark.parametrize("over,why", [
    ({"kind": "grpc"}, "kind"),
    ({"base_url": "ftp://x"}, "base_url"),
    ({"method": "DELETE"}, "method"),
    ({"response_path": None}, "response_path"),
    ({"body_template": None}, "body_template"),
    ({"secret_header": "Authorization: Bearer abc"}, "secret_header"),
    ({"headers": {"Authorization": "Bearer abc"}}, "headers"),
    ({"timeout_s": 0}, "timeout_s"),
    ({"refusal": {"status": "502"}}, "refusal"),
])
def test_p3_invalid_rest_connections_are_422(client, admin, project, stub, over, why):
    r = put(client, project, "mcas-chat", admin, rest_body(stub, **over))
    assert r.status_code == 422, (why, r.text)


def test_p3_an_openai_connection_needs_a_model(client, admin, project, stub):
    engine_component(stub, project["pid"])
    body = {"label": "GPT", "kind": "openai", "base_url": stub.base + "/v1"}
    assert put(client, project, "gpt", admin, body).status_code == 422
    assert put(client, project, "gpt", admin, {**body, "model": "gpt-4o-mini"}).status_code == 200


@pytest.mark.parametrize("name", ["MCAS", "a b", "-x", "x" * 64, "ü"])
def test_p3_a_bad_name_is_refused(client, admin, project, stub, name):
    assert put(client, project, name, admin, rest_body(stub)).status_code in (404, 422)


# ── P2, P4 the key: Fernet, write-only ──────────────────────────────────────

def test_p2_the_key_is_stored_only_as_fernet_ciphertext(client, admin, project, stub, dsn):
    engine_component(stub, project["pid"])
    key = new_secret()
    put(client, project, "mcas-chat", admin, rest_body(stub, secret=key))
    token = one(dsn, project, "select secret_ciphertext from connection.endpoint where name = 'mcas-chat'")[0]
    assert key not in token and Fernet(SECRETS_KEY.encode()).decrypt(token.encode()).decode() == key


def test_p2_absent_keeps_the_key_and_empty_removes_it(client, admin, project, stub):
    engine_component(stub, project["pid"])
    put(client, project, "mcas-chat", admin, rest_body(stub, secret=new_secret()))
    assert put(client, project, "mcas-chat", admin, rest_body(stub)).json()["has_secret"] is True
    assert put(client, project, "mcas-chat", admin, rest_body(stub, secret="")).json()["has_secret"] is False


def test_p4_no_route_ever_answers_with_the_key_or_its_ciphertext(client, admin, project, stub, dsn):
    engine_component(stub, project["pid"])
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    key = new_secret()
    answers = [put(client, project, "mcas-chat", admin, rest_body(stub, secret=key)).text,
               client.get(base(project), headers=admin).text,
               client.post(f"{base(project)}/mcas-chat/test", json={}, headers=admin).text]
    token = one(dsn, project, "select secret_ciphertext from connection.endpoint where name = 'mcas-chat'")[0]
    for text in answers:
        assert key not in text and token not in text and "secret_ciphertext" not in text


# ── P5 the Test button ──────────────────────────────────────────────────────

def test_p5_test_calls_the_system_and_stores_the_result(client, admin, project, stub, dsn):
    engine_component(stub, project["pid"])
    key = new_secret()
    stub.route("POST", "/chat", (200, {"answer": "Up to 5,000 EUR (POL-ELIG-001)."}))
    put(client, project, "mcas-chat", admin, rest_body(stub, secret=key))
    r = client.post(f"{base(project)}/mcas-chat/test", json={"input": "How much can I borrow?"}, headers=admin)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True and out["answer"].startswith("Up to 5,000") and out["status"] == 200
    call = stub.requests("POST", "/chat")[-1]
    assert call["json"] == {"question": "How much can I borrow?", "history": []}
    assert call["headers"]["authorization"] == f"Bearer {key}"
    ok, detail = one(dsn, project, "select last_test_ok, last_test_detail from connection.endpoint where name = 'mcas-chat'")
    assert ok is True and "5,000" in detail


def test_p5_a_declared_refusal_is_reported_as_a_refusal(client, admin, project, stub):
    engine_component(stub, project["pid"])
    stub.route("POST", "/chat", (502, {"detail": {"error": "answer_not_grounded", "reason": "no clause"}}))
    put(client, project, "mcas-chat", admin, rest_body(stub))
    out = client.post(f"{base(project)}/mcas-chat/test", json={}, headers=admin).json()
    assert out["ok"] is True and out["refused"] is True and out["refusal_reason"] == "no clause"


@pytest.mark.parametrize("status,error", [(401, "auth"), (404, "not_found"), (200, "bad_response")])
def test_p5_failures_are_reported_with_their_class(client, admin, project, stub, dsn, status, error):
    engine_component(stub, project["pid"])
    stub.route("POST", "/chat", (status, {"reply": "no answer field"}))
    put(client, project, "mcas-chat", admin, rest_body(stub))
    out = client.post(f"{base(project)}/mcas-chat/test", json={}, headers=admin).json()
    assert out["ok"] is False and out["error"] == error
    assert one(dsn, project, "select last_test_ok from connection.endpoint where name = 'mcas-chat'") == (False,)


def test_p5_testing_an_unknown_connection_is_404(client, admin, project):
    assert client.post(f"{base(project)}/nope/test", json={}, headers=admin).status_code == 404


# ── P9 outbound safety on the Test button ───────────────────────────────────

@pytest.mark.parametrize("url", ["http://127.0.0.1:9", "http://10.0.0.1", "http://169.254.169.254",
                                 "http://[::1]:8000", "http://postgres:5432"])
def test_p9_the_test_refuses_internal_addresses(client, admin, project, stub, monkeypatch, url):
    engine_component(stub, project["pid"])
    put(client, project, "inner", admin, rest_body(stub, base_url=url))
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", "")
    out = client.post(f"{base(project)}/inner/test", json={}, headers=admin).json()
    assert out["ok"] is False and out["error"] == "blocked", out


# ── P8 the internal route the plugin-side client uses ───────────────────────

def test_p8_resolve_returns_the_descriptor_with_the_key(client, admin, project, stub):
    engine_component(stub, project["pid"])
    key = new_secret()
    put(client, project, "mcas-chat", admin, rest_body(stub, secret=key))
    r = resolve(client, project, "mcas-chat")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "mcas-chat" and d["secret"] == key and d["kind"] == "rest"
    assert d["body_template"] == {"question": "{{input}}", "history": "{{history}}"} and d["updated_at"]


def test_p8_resolve_is_closed_without_token_and_refuses_a_wrong_one(client, project, monkeypatch):
    assert resolve(client, project, "x", token="wrong").status_code == 401
    monkeypatch.delenv("PLATFORM_CONNECTIONS_TOKEN")
    assert resolve(client, project, "x", token="").status_code == 503


def test_p8_resolve_is_not_reachable_through_the_gateway(client, project):
    assert resolve(client, project, "x", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 404


def test_p8_an_unknown_or_deleted_connection_does_not_resolve(client, admin, project, stub):
    engine_component(stub, project["pid"])
    assert resolve(client, project, "nope").status_code == 404
    put(client, project, "mcas-chat", admin, rest_body(stub))
    client.delete(f"{base(project)}/mcas-chat", headers=admin)
    r = resolve(client, project, "mcas-chat")
    assert r.status_code == 410 and "deleted" in r.text


def test_p8_the_key_never_appears_in_the_service_log(client, admin, project, stub, caplog):
    engine_component(stub, project["pid"])
    key = new_secret()
    put(client, project, "mcas-chat", admin, rest_body(stub, secret=key))
    with caplog.at_level("DEBUG"):
        resolve(client, project, "mcas-chat")
    assert key not in caplog.text


# ── P10 the engine sees it as a resource component ──────────────────────────

# Targets plan v2 (O1): a connection is the endpoint of an assessment target, and evaluations pick
# the target's engine component; a connection no longer makes one of its own
# (test_connection_targets.py, TG9, covers the legacy rename).

def test_p10_saving_a_connection_makes_no_engine_component(client, admin, project, stub, dsn):
    r = put(client, project, "mcas-chat", admin, rest_body(stub))
    assert r.status_code == 200
    assert not stub.requests("POST", "/api/v1/projects/")
    assert one(dsn, project, "select engine_component from connection.endpoint where name = 'mcas-chat'") == (None,)


def test_p10_an_engine_that_does_not_answer_does_not_matter_to_saving(client, admin, project, stub):
    stub.route("POST", f"/api/v1/projects/for-platform/{project['pid']}", (503, {"detail": "down"}))
    assert put(client, project, "mcas-chat", admin, rest_body(stub)).status_code == 200
    assert client.post(f"{base(project)}/mcas-chat/link", headers=admin).status_code == 200


def test_p10_deleting_keeps_the_engine_component(client, admin, project, stub):
    engine_component(stub, project["pid"])
    put(client, project, "mcas-chat", admin, rest_body(stub))
    client.delete(f"{base(project)}/mcas-chat", headers=admin)
    assert stub.requests("DELETE") == []


# ── P6 rotation covers the connection keys ──────────────────────────────────

def test_p6_rotate_re_encrypts_connection_keys_and_prints_counts_only(client, admin, project, stub, dsn, monkeypatch):
    engine_component(stub, project["pid"])
    key = new_secret()
    put(client, project, "mcas-chat", admin, rest_body(stub, secret=key))
    newest = Fernet.generate_key().decode()
    env = {**os.environ, "PLATFORM_DATABASE_URL": dsn, "PLATFORM_SECRETS_KEY": f"{newest},{SECRETS_KEY}",
           "PYTHONPATH": os.pathsep.join([str(PLATFORM_DIR), str(PLATFORM_DIR.parent / "shared/identity")])}
    done = subprocess.run([sys.executable, "-m", "platform_service.llm_store", "rotate"], cwd=PLATFORM_DIR,
                          env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    for secret in (key, newest, SECRETS_KEY):
        assert secret not in done.stdout + done.stderr
    token = one(dsn, project, "select secret_ciphertext from connection.endpoint where name = 'mcas-chat'")[0]
    assert Fernet(newest.encode()).decrypt(token.encode()).decode() == key
