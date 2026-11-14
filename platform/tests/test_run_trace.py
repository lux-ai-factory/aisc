"""Every call a run makes to the system under test is recorded by the platform, whatever the plugin: the
request as sent, the whole answer or the error, the times, in an append-only table of the project's
database, each row chained to the one before it in its run. The worker reads its run's calls back with
the run's pass and keeps them as a file. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from platform_service import run_trace
from tests.conftest import MIGRATE_DSN, needs_database, project_db
from tests.connection_support import CONNECTIONS_TOKEN
from tests.test_run_passes import _env, made_with_endpoints, stub, with_pass  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


def mint(client, project, plugin=None):
    body = {"refs": [f"target:{project['pid']}/system"], "project": project["pid"]}
    if plugin:
        body["evaluation_plugin"] = plugin
    r = client.post("/internal/run-passes", json=body, headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 201, r.text
    return r.json()["pass"]


def run_key(client, project, run_pass):
    r = with_pass(client, run_pass, project, "targets/system/run-keys", "POST")
    assert r.status_code == 201, r.text
    return r.json()["key"]


def door(project, path):
    return f"/internal/facade/{project['pid']}/system-chat{path}"


def keyed(key):
    return {"Authorization": f"Bearer {key}"}


def trace(client, run_pass):
    r = client.get("/internal/run-passes/trace", headers={"X-AISC-Run-Pass": run_pass})
    assert r.status_code == 200, r.text
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def calls_of(lines):
    return [line for line in lines if "seal" not in line]


ASK = {
    "aisc": ("/aisc/ask", {"input": "Who helps with debts?", "history": [{"role": "user", "content": "Hello"},
                                                                       {"role": "assistant", "content": "Hi!"}]}),
    "openai": ("/openai/v1/chat/completions", {"model": "m", "messages": [
        {"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "Who helps with debts?"}]}),
    "a2a": ("/a2a", {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {
        "messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "Who helps with debts?"}]}}}),
    "oip": ("/oip/v2/models/system-chat/infer", {"inputs": [{"name": "input", "shape": [1], "datatype": "BYTES",
                                                             "data": ["Who helps with debts?"]}]}),
}


@pytest.mark.parametrize("name", sorted(ASK))
def test_a_call_through_any_door_is_recorded_with_its_request_and_whole_answer(client, project, stub, name):
    long_answer = "Humanitas Eindhoven. " * 400                  # nothing is cut
    stub.route("POST", "/chat", (200, {"answer": long_answer}))
    run_pass = mint(client, project, str(uuid.uuid4()))
    path, body = ASK[name]
    r = client.post(door(project, path), json=body, headers=keyed(run_key(client, project, run_pass)))
    assert r.status_code == 200, r.text
    (call,) = calls_of(trace(client, run_pass))
    assert call["door"] == name and call["connection"] == "system-chat" and call["seq"] == 1
    assert call["outcome"] == "answered" and call["error"] is None
    assert call["request"]["input"] == "Who helps with debts?"
    assert call["answer"]["output"] == long_answer
    assert call["started_at"] <= call["ended_at"]


def test_the_history_sent_is_recorded_as_sent(client, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    run_pass = mint(client, project)
    path, body = ASK["openai"]
    client.post(door(project, path), json=body, headers=keyed(run_key(client, project, run_pass)))
    (call,) = calls_of(trace(client, run_pass))
    assert call["request"]["history"] == body["messages"][:2]


def test_a_failed_call_is_recorded_with_its_error(client, project, stub):
    stub.route("POST", "/chat", (401, {"detail": "bad"}))
    run_pass = mint(client, project)
    r = client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(run_key(client, project, run_pass)))
    assert r.status_code == 502
    (call,) = calls_of(trace(client, run_pass))
    assert call["outcome"] == "failed" and call["answer"] is None and call["error"]["code"] == "auth"


def test_a_request_the_platform_does_not_send_is_recorded_as_not_sent(client, project, stub):
    run_pass = mint(client, project)
    body = {"model": "m", "stream": True, "messages": [{"role": "user", "content": "q"}]}
    r = client.post(door(project, "/openai/v1/chat/completions"), json=body,
                    headers=keyed(run_key(client, project, run_pass)))
    assert r.status_code == 400
    assert stub.requests("POST", "/chat") == []
    (call,) = calls_of(trace(client, run_pass))
    assert call["outcome"] == "not_sent" and call["request"] == body and call["error"]["detail"]


def test_an_oip_batch_is_one_row_per_input(client, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "A"}), (200, {"answer": "B"}))
    run_pass = mint(client, project)
    body = {"inputs": [{"name": "input", "shape": [2], "datatype": "BYTES", "data": ["q1", "q2"]}]}
    client.post(door(project, "/oip/v2/models/system-chat/infer"), json=body,
                headers=keyed(run_key(client, project, run_pass)))
    calls = calls_of(trace(client, run_pass))
    assert [(c["seq"], c["request"]["input"], c["answer"]["output"]) for c in calls] == [(1, "q1", "A"), (2, "q2", "B")]


def test_a_probe_is_not_a_call(client, project, stub):
    run_pass = mint(client, project)
    client.get(door(project, "/openai/v1/models"), headers=keyed(run_key(client, project, run_pass)))
    assert calls_of(trace(client, run_pass)) == []


def test_the_calls_of_a_run_are_chained_and_the_seal_is_the_last_link(client, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    run_pass, other = mint(client, project), mint(client, project)
    key, other_key = run_key(client, project, run_pass), run_key(client, project, other)
    for i in range(3):
        client.post(door(project, "/aisc/ask"), json={"input": f"q{i}"}, headers=keyed(key))
        client.post(door(project, "/aisc/ask"), json={"input": f"o{i}"}, headers=keyed(other_key))
    lines = trace(client, run_pass)
    calls, seal = calls_of(lines), lines[-1]["seal"]
    assert [c["request"]["input"] for c in calls] == ["q0", "q1", "q2"]
    assert calls[0]["prev_hash"] is None
    assert [c["prev_hash"] for c in calls[1:]] == [c["hash"] for c in calls[:-1]]
    assert seal == {"calls": 3, "digest": calls[-1]["hash"]}
    assert run_trace.verify(lines) is True


def test_an_edited_trace_no_longer_verifies(client, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "Humanitas Eindhoven"}))
    run_pass = mint(client, project)
    key = run_key(client, project, run_pass)
    for _ in range(2):
        client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(key))
    lines = trace(client, run_pass)
    lines[0]["answer"]["output"] = "COC Eindhoven"
    assert run_trace.verify(lines) is False
    lines = trace(client, run_pass)
    del lines[0]
    assert run_trace.verify(lines) is False


def test_a_recorded_call_cannot_be_changed_or_deleted(client, project, stub, dsn):
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    run_pass = mint(client, project)
    client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(run_key(client, project, run_pass)))
    for statement in ("UPDATE trace.call SET answer = '{}'::jsonb", "DELETE FROM trace.call"):
        # the role the platform's requests use may only insert and read
        with project_db(dsn, project) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)
        # and the table's owner is stopped by its trigger
        with project_db(MIGRATE_DSN, project) as conn, pytest.raises(psycopg.Error, match="append-only"):
            conn.execute(statement)


def test_a_call_that_cannot_be_recorded_gets_no_answer(client, project, stub, monkeypatch):
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    run_pass = mint(client, project)
    key = run_key(client, project, run_pass)

    def broken(*args, **kwargs):
        raise psycopg.OperationalError("database gone")
    monkeypatch.setattr(run_trace, "record", broken)
    r = client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(key))
    assert r.status_code == 503 and "recorded" in r.json()["detail"]
    assert "a" != r.text


def test_the_calls_of_the_run_name_its_evaluation_plugin(client, project, stub, dsn):
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    plugin = str(uuid.uuid4())
    run_pass = mint(client, project, plugin)
    client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(run_key(client, project, run_pass)))
    with project_db(dsn, project) as conn:
        row = conn.execute("SELECT evaluation_plugin::text FROM trace.call").fetchone()
    assert row[0] == plugin


def test_a_key_issued_without_a_pass_is_recorded_under_its_own_run(client, project, stub, dsn):
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    r = client.post(f"/internal/projects/{project['pid']}/connections/system-chat/run-keys",
                    headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(r.json()["key"]))
    with project_db(dsn, project) as conn:
        row = conn.execute("SELECT run FROM trace.call").fetchone()
    assert row[0].startswith("key:")


def test_the_trace_route_gives_a_pass_its_own_run_only(client, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    run_pass, other = mint(client, project), mint(client, project)
    client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(run_key(client, project, run_pass)))
    assert calls_of(trace(client, other)) == []
    assert client.get("/internal/run-passes/trace").status_code == 401
    assert client.get("/internal/run-passes/trace", headers={"X-AISC-Run-Pass": "aisc-rp-" + "0" * 64}).status_code == 401
    assert client.get("/internal/run-passes/trace", headers={"X-AISC-Run-Pass": run_pass,
                                                             "X-Forwarded-For": "1.2.3.4"}).status_code == 404


def test_the_trace_keeps_no_secret_the_system_echoes(client, project, stub):
    from platform_service import connection_store
    from platform_service.routes.connections import call_descriptor_of, secret_values

    row = connection_store.descriptor(project["pid"], "system-chat")
    secret = secret_values(call_descriptor_of(row, project["pid"]))[0]
    stub.route("POST", "/chat", (200, {"answer": f"my key is {secret}"}))
    run_pass = mint(client, project)
    client.post(door(project, "/aisc/ask"), json={"input": "q"}, headers=keyed(run_key(client, project, run_pass)))
    assert secret not in json.dumps(trace(client, run_pass))


def test_a_call_with_a_nul_character_is_sent_recorded_and_still_verifies(client, project, stub):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "a\u0000b"}))
    run_pass = mint(client, project)
    r = client.post(door(project, "/aisc/ask"), json={"input": "x\u0000y"},
                    headers=keyed(run_key(client, project, run_pass)))
    assert r.status_code == 200, r.text
    lines = trace(client, run_pass)
    (call,) = calls_of(lines)
    assert call["outcome"] == "answered" and "\u0000" not in json.dumps(call["request"], ensure_ascii=False)
    assert call["request"]["input"].startswith("x") and call["request"]["input"].endswith("y")
    assert run_trace.verify(lines) is True


def test_a_request_with_a_number_json_cannot_store_is_still_recorded(client, project, stub):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "a"}))
    run_pass = mint(client, project)
    body = '{"model": "m", "stream": true, "temperature": NaN, "messages": [{"role": "user", "content": "q"}]}'
    r = client.post(door(project, "/openai/v1/chat/completions"), content=body,
                    headers={**keyed(run_key(client, project, run_pass)), "Content-Type": "application/json"})
    assert r.status_code == 400, r.text                 # refused for streaming, and recorded as it came
    lines = trace(client, run_pass)
    (call,) = calls_of(lines)
    assert call["outcome"] == "not_sent" and call["request"]["temperature"] == "NaN"
    assert run_trace.verify(lines) is True


def test_a_trace_whose_numbers_the_database_rewrites_still_verifies(project):
    run = "key:" + "a" * 64
    started = run_trace.now()
    run_trace.record(project["pid"], run, "system-chat", "aisc", {"input": "q", "params": {"seed": 1e16, "t": 0.1}},
                     "answered", {"output": "ok", "score": 1.0e-7}, None, started, run_trace.now())
    lines = [json.loads(line) for line in run_trace.export(project["pid"], run).splitlines()]
    assert run_trace.verify(lines) is True


def test_ending_a_runs_pass_seals_its_calls_digest_in_the_ledger_in_the_same_step(client, project, stub, monkeypatch):  # noqa: F811
    from tests.conftest import DSN

    stub.route("POST", "/chat", (200, {"answer": "a"}))
    plugin = str(uuid.uuid4())
    run_pass = mint(client, project, plugin)
    key = run_key(client, project, run_pass)
    for i in range(2):
        client.post(door(project, "/aisc/ask"), json={"input": f"q{i}"}, headers=keyed(key))
    seal = trace(client, run_pass)[-1]["seal"]
    monkeypatch.setenv("LEDGER_MODE", "record")
    request_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())

    r = client.delete("/internal/run-passes", headers={"X-AISC-Run-Pass": run_pass, "X-AISC-Request-Id": request_id,
                                                       "X-AISC-Run-Id": run_id})

    assert r.status_code == 204
    with psycopg.connect(DSN) as conn:
        rows = conn.execute("SELECT project_pid::text, item_type, item_id, details, request_id::text, run_id::text, emitter"
                            " FROM core.outbox WHERE action = 'run.trace.sealed'").fetchall()
    assert rows == [(project["pid"], "evaluation_plugin", plugin, {"calls": 2, "digest": seal["digest"]},
                     request_id, run_id, "platform")]
