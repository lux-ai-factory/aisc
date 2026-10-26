"""A run key issued under a run's pass ends with the pass: the platform deletes the pass's keys when the
worker revokes it, refuses a key whose pass has expired or is gone, and gives the key no later expiry
than its pass's. A key issued with the stack's connections token keeps its own lifetime. Runs on the
throwaway; the system under test is a local stub."""
from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime

import psycopg
import pytest

from platform_service import connection_store, db, projectdb, run_passes
from tests.conftest import ALICE, needs_database, one, project_db
from tests.connection_support import CONNECTIONS_TOKEN
from tests.test_run_passes import _env, made_with_endpoints, mint, stored_pass, stub, with_pass  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


@pytest.fixture(autouse=True)
def _answers(stub):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "ok"}))


def sha(run_pass: str) -> str:
    return hashlib.sha256(run_pass.encode()).hexdigest()


def pass_for(client, *projects):
    """A run's pass for these projects' systems: minted for one project, stored as an older pass for several."""
    refs = [f"target:{p['pid']}/system" for p in projects]
    if len(projects) > 1:
        return stored_pass(refs)
    return mint(client, refs, projects[0]).json()["pass"]


def key_under(client, run_pass, project):
    r = with_pass(client, run_pass, project, "targets/system/run-keys", "POST")
    assert r.status_code == 201, r.text
    return r.json()


def key_with_token(client, project):
    r = client.post(f"/internal/projects/{project['pid']}/connections/system-chat/run-keys",
                    headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 201, r.text
    return r.json()["key"]


def ask(client, project, key):
    return client.post(f"/internal/facade/{project['pid']}/system-chat/aisc/ask", json={"input": "q"},
                       headers={"Authorization": f"Bearer {key}"})


def ask_openai(client, project, key):
    return client.post(f"/internal/facade/{project['pid']}/system-chat/openai/v1/chat/completions",
                       json={"model": "x", "messages": [{"role": "user", "content": "q"}]},
                       headers={"Authorization": f"Bearer {key}"})


def revoke(client, run_pass):
    return client.delete("/internal/run-passes", headers={"X-AISC-Run-Pass": run_pass})


def rows_of_pass(dsn, project, run_pass):
    return one(dsn, project, "select count(*) from connection.run_key where pass_hash = %s", (sha(run_pass),))[0]


def all_rows(dsn, project):
    return one(dsn, project, "select count(*) from connection.run_key")[0]


def test_a_run_key_is_refused_after_its_pass_is_revoked(client, project, dsn):
    run_pass = pass_for(client, project)
    key = key_under(client, run_pass, project)["key"]
    assert ask(client, project, key).status_code == 200
    assert revoke(client, run_pass).status_code == 204
    assert rows_of_pass(dsn, project, run_pass) == 0
    r = ask(client, project, key)
    assert r.status_code == 401 and r.json() == {"detail": "a run key is needed"}, r.text


def test_a_run_key_whose_pass_expired_is_refused(client, project, dsn):
    run_pass = pass_for(client, project)
    key = key_under(client, run_pass, project)["key"]
    with db.pool().connection() as conn:
        conn.execute("update core.run_pass set expires_at = now() - interval '1 second' where pass_hash = %s",
                     (sha(run_pass),))
    r = ask(client, project, key)
    assert r.status_code == 401 and r.json() == {"detail": "the run's pass has ended"}, r.text
    assert one(dsn, project, "select uses from connection.run_key where key_hash = %s", (sha(key),))[0] == 0


def test_a_run_key_whose_pass_row_is_gone_is_refused_even_if_its_row_stayed(client, project, dsn):
    run_pass = pass_for(client, project)
    key = key_under(client, run_pass, project)["key"]
    with db.pool().connection() as conn:
        conn.execute("delete from core.run_pass where pass_hash = %s", (sha(run_pass),))
    assert one(dsn, project, "select count(*) from connection.run_key where key_hash = %s", (sha(key),))[0] == 1
    r = ask(client, project, key)
    assert r.status_code == 401 and r.json() == {"detail": "the run's pass has ended"}, r.text
    r = ask_openai(client, project, key)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["type"] == "authentication_error"
    assert r.json()["error"]["message"] == "the run's pass has ended"


def test_revoking_deletes_the_passs_keys_in_every_project_it_named(client, project, make_project, admin, stub, dsn):  # noqa: F811
    other = made_with_endpoints(make_project, client, admin, stub)
    run_pass = pass_for(client, project, other)
    key_under(client, run_pass, project)
    key_under(client, run_pass, other)
    lasting = key_with_token(client, project)
    assert revoke(client, run_pass).status_code == 204
    assert rows_of_pass(dsn, project, run_pass) == 0 and rows_of_pass(dsn, other, run_pass) == 0
    assert one(dsn, project, "select pass_hash is null from connection.run_key where key_hash = %s",
               (sha(lasting),))[0] is True
    assert ask(client, project, lasting).status_code == 200


def test_another_runs_key_is_unaffected(client, project):
    first, second = pass_for(client, project), pass_for(client, project)
    k1 = key_under(client, first, project)["key"]
    k2 = key_under(client, second, project)["key"]
    assert revoke(client, first).status_code == 204
    assert ask(client, project, k2).status_code == 200
    assert ask(client, project, k1).status_code == 401


def test_the_key_expires_with_its_pass(client, project, dsn, monkeypatch):
    monkeypatch.delenv("CONNECTIONS_RUN_KEY_TTL_S", raising=False)
    run_pass, pass_expires = run_passes.mint([f"target:{project['pid']}/system"], ttl_s=60,
                                                project=project["pid"])
    issued = key_under(client, run_pass, project)
    answered = datetime.fromisoformat(issued["expires_at"])
    assert abs((answered - pass_expires).total_seconds()) <= 1, (answered, pass_expires)
    stored = one(dsn, project, "select expires_at from connection.run_key where key_hash = %s",
                 (sha(issued["key"]),))[0]
    assert abs((stored - pass_expires).total_seconds()) <= 1, (stored, pass_expires)


def test_a_run_key_from_another_project_is_refused(client, project, make_project, admin, stub):  # noqa: F811
    other = made_with_endpoints(make_project, client, admin, stub)
    key = key_with_token(client, project)
    r = client.post(f"/internal/facade/{other['pid']}/system-chat/aisc/ask", json={"input": "q"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 401 and r.json() == {"detail": "a run key is needed"}, r.text


def test_revoking_survives_a_project_database_that_fails(client, project, make_project, admin, stub, monkeypatch,  # noqa: F811
                                                         caplog):
    other = made_with_endpoints(make_project, client, admin, stub)
    run_pass = pass_for(client, project, other)
    key_a = key_under(client, run_pass, project)["key"]
    real = connection_store.revoke_run_keys

    def failing(pid, pass_hash):
        if str(pid) == project["pid"]:
            raise psycopg.OperationalError("the project database is down")
        return real(pid, pass_hash)

    monkeypatch.setattr(connection_store, "revoke_run_keys", failing)
    with caplog.at_level(logging.WARNING):
        assert revoke(client, run_pass).status_code == 204
    warnings = [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.WARNING]
    assert any(project["pid"] in m and "not deleted" in m for m in warnings), warnings
    r = ask(client, project, key_a)
    assert r.status_code == 401 and r.json() == {"detail": "the run's pass has ended"}, r.text


def test_revoking_an_unknown_pass_is_204(client, project, dsn):
    run_pass = pass_for(client, project)
    key_under(client, run_pass, project)
    key_with_token(client, project)
    before = all_rows(dsn, project)
    assert revoke(client, "aisc-rp-nothing").status_code == 204
    assert all_rows(dsn, project) == before == 2


def test_service_token_keys_have_no_pass(client, project, dsn):
    key = key_with_token(client, project)
    assert one(dsn, project, "select pass_hash is null from connection.run_key where key_hash = %s",
               (sha(key),))[0] is True
    assert ask(client, project, key).status_code == 200


def test_a_project_made_before_the_run_key_pass_gets_it_at_the_next_start(client, as_user, unique, dsn, monkeypatch,
                                                                          tmp_path):
    old = tmp_path / "template"
    old.mkdir()
    for f in sorted(projectdb.TEMPLATE.glob("*.sql")):
        if f.name < "0022":
            shutil.copy(f, old / f.name)
    real = projectdb.TEMPLATE
    monkeypatch.setattr(projectdb, "TEMPLATE", old)
    made = client.post("/projects", json={"name": unique("pre-pass")}, headers=as_user(ALICE)).json()
    column = ("select count(*) from information_schema.columns where table_schema = 'connection'"
              " and table_name = 'run_key' and column_name = 'pass_hash'")
    assert one(dsn, made, column) == (0,)
    with project_db(dsn, made) as conn:
        conn.execute("insert into connection.endpoint (name, label, kind, base_url) values"
                     " ('old', 'Old', 'rest', 'https://old.example')")
        conn.execute("insert into connection.run_key (key_hash, name, fingerprint, expires_at) values"
                     " (%s, 'old', 'f', now() + interval '1 hour')", ("0" * 64,))
    monkeypatch.setattr(projectdb, "TEMPLATE", real)
    monkeypatch.setattr(db, "_unprovisioned", None)
    db.pool()
    assert one(dsn, made, column) == (1,)
    assert one(dsn, made, "select pass_hash is null from connection.run_key where key_hash = %s", ("0" * 64,)) == (True,)
