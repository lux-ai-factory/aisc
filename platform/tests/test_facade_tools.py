"""Function calling through the platform: an OpenAI-compatible connection says whether it carries tools
(and log probabilities); the run key advertises tools only then; aisc/ask and the OpenAI door carry
tools and tool results to it and its tool calls back, and refuse tools where they cannot be carried;
the Test button checks each flag with a second probe. Runs on the throwaway; the model is a local stub."""
from __future__ import annotations

import os
import shutil

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import db, llm_store, projectdb
from tests.conftest import ALICE, needs_database, one, project_db
from tests.connection_support import new_secret
from tests.test_connection_facades import _env, base, issue, keyed, mcas, stub  # noqa: F401  (fixtures)

pytestmark = needs_database

CALL = {"id": "call_1", "type": "function", "function": {"name": "get_balance", "arguments": "{\"iban\": \"LU12\"}"}}
TOOLS = [{"type": "function", "function": {"name": "get_balance",
                                           "parameters": {"type": "object", "properties": {"iban": {"type": "string"}}}}}]
PROBE_TOOL = {"type": "function", "function": {"name": "aisc_probe", "description": "Answers that the endpoint calls tools.",
                                               "parameters": {"type": "object", "properties": {}}}}
PROBE_CALL = {"id": "call_p", "type": "function", "function": {"name": "aisc_probe", "arguments": "{}"}}
SYSTEM = {"role": "system", "content": "You are a bank agent."}
USER = {"role": "user", "content": "My balance?"}
TEXT = {"choices": [{"message": {"role": "assistant", "content": "Your balance is 10."}, "finish_reason": "stop"}]}
COMPLETIONS = "/v1/chat/completions"


def calls(call=CALL):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]},
                         "finish_reason": "tool_calls"}]}


def model(seen):
    """Tool calls when the request has tools and does not end in a tool's result; text otherwise."""
    body = seen.json or {}
    if body.get("tools") and (body.get("messages") or [{}])[-1].get("role") != "tool":
        return 200, calls()
    return 200, TEXT


def agent(stub, **over):  # noqa: F811
    body = {"label": "Bank agent", "kind": "openai", "base_url": stub.base + "/v1", "model": "gpt-4o-mini",
            "timeout_s": 5, "secret": new_secret(), "supports_tools": True}
    body.update(over)
    return body


def other_kind(stub, kind):  # noqa: F811
    return {"rest": mcas(stub),
            "a2a": {"label": "An agent", "kind": "a2a", "base_url": stub.base, "path": "/rpc", "protocol_version": "1.0"},
            "oip": {"label": "Scorer", "kind": "oip", "base_url": stub.base, "model": "scorer"}}[kind]


def save(client, admin, project, name, body):
    return client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)


def saved(client, admin, project, name, body):
    r = save(client, admin, project, name, body)
    assert r.status_code == 200, r.text
    return r.json()


def opened(client, admin, project, name, body):
    saved(client, admin, project, name, body)
    return issue(client, project, name).json()["key"]


def door(client, project, name, key, body):
    return client.post(f"{base(project, name)}/openai/v1/chat/completions", json=body, headers=keyed(key))


def ask(client, project, name, key, body):
    return client.post(f"{base(project, name)}/aisc/ask", json=body, headers=keyed(key))


def latest_tested(project):
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"]))) as conn:
        row = conn.execute("select details from ledger.outbox where action = 'connection.tested'"
                           " order by occurred_at desc limit 1").fetchone()
    return row[0] if row else None


def test_the_flags_are_saved_and_shown(client, admin, project, stub):  # noqa: F811
    body = saved(client, admin, project, "bank-agent", agent(stub))
    assert body["supports_tools"] is True and body["supports_logprobs"] is False
    listed = client.get(f"/projects/{project['slug']}/connections", headers=admin).json()["connections"][0]
    assert listed["supports_tools"] is True and listed["supports_logprobs"] is False
    from tests.connection_support import CONNECTIONS_TOKEN
    resolved = client.get(f"/internal/projects/{project['pid']}/connections/bank-agent",
                          headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN}).json()
    assert resolved["supports_tools"] is True and resolved["supports_logprobs"] is False
    without = {k: v for k, v in agent(stub).items() if k not in ("supports_tools", "supports_logprobs")}
    again = saved(client, admin, project, "bank-agent", without)
    assert again["supports_tools"] is False and again["supports_logprobs"] is False


@pytest.mark.parametrize("kind", ["rest", "a2a", "oip"])
@pytest.mark.parametrize("flag,message", [
    ("supports_tools", "supports_tools: only an OpenAI-compatible connection carries tools"),
    ("supports_logprobs", "supports_logprobs: only an OpenAI-compatible connection carries log probabilities"),
])
def test_the_flags_are_for_openai_only(client, admin, project, stub, kind, flag, message):  # noqa: F811
    r = save(client, admin, project, "other", {**other_kind(stub, kind), flag: True})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == message


def test_a_flag_is_a_boolean(client, admin, project, stub):  # noqa: F811
    assert save(client, admin, project, "bank-agent", agent(stub, supports_tools="yes")).status_code == 422


def test_capabilities_follow_the_connection(client, admin, project, stub):  # noqa: F811
    cases = [("with-tools", agent(stub), ["text", "history", "tools"]),
             ("without-tools", agent(stub, supports_tools=False), ["text", "history"]),
             ("logprobs-only", agent(stub, supports_tools=False, supports_logprobs=True), ["text", "history"]),
             ("rest", mcas(stub), ["text", "history"])]
    for name, body, expected in cases:
        saved(client, admin, project, name, body)
        r = issue(client, project, name)
        assert r.status_code == 201, r.text
        assert r.json()["capabilities"] == expected, name


def test_aisc_ask_carries_tools_and_returns_tool_calls(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, model)
    key = opened(client, admin, project, "bank-agent", agent(stub))
    r = ask(client, project, "bank-agent", key, {"input": "My balance?", "params": {"tools": TOOLS, "tool_choice": "auto"}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert isinstance(out.pop("latency_ms"), int)
    assert out == {"output": None, "refused": False, "refusal_reason": None, "status": 200, "tool_calls": [CALL]}
    sent = stub.requests("POST", COMPLETIONS)[-1]["json"]
    assert sent["tools"] == TOOLS and sent["tool_choice"] == "auto"


def test_aisc_ask_refuses_tools_without_the_flag(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, model)
    key = opened(client, admin, project, "bank-agent", agent(stub, supports_tools=False))
    r = ask(client, project, "bank-agent", key, {"input": "My balance?", "params": {"tools": TOOLS}})
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": "params: this connection does not carry tools (it carries text, history)"}
    assert stub.requests("POST", COMPLETIONS) == []


@pytest.mark.parametrize("kind", ["rest", "a2a", "oip"])
def test_rest_a2a_and_oip_refuse_tools(client, admin, project, stub, kind):  # noqa: F811
    key = opened(client, admin, project, "other", other_kind(stub, kind))
    message = f"params: a {kind} connection does not carry tools; only an OpenAI-compatible one does"
    r = ask(client, project, "other", key, {"input": "q", "params": {"tools": TOOLS}})
    assert r.status_code == 400 and r.json() == {"detail": message}, r.text
    r = door(client, project, "other", key, {"model": "x", "messages": [{"role": "user", "content": "q"}], "tools": TOOLS})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["message"] == message
    assert [s for s in stub.seen if not s.path.startswith("/api/")] == []


def test_the_openai_door_forwards_tools_and_returns_tool_calls(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, model)
    key = opened(client, admin, project, "bank-agent", agent(stub))
    r = door(client, project, "bank-agent", key, {"model": "x", "messages": [SYSTEM, USER], "tools": TOOLS,
                                                  "tool_choice": "auto", "parallel_tool_calls": False, "n": 1})
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0] == {"index": 0, "message": {"role": "assistant", "content": None, "refusal": None,
                                                              "tool_calls": [CALL]}, "finish_reason": "tool_calls"}
    assert stub.requests("POST", COMPLETIONS)[-1]["json"] == {
        "model": "gpt-4o-mini", "messages": [SYSTEM, USER], "tools": TOOLS, "tool_choice": "auto",
        "parallel_tool_calls": False}


def test_the_openai_door_continues_after_a_tool_result(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, model)
    key = opened(client, admin, project, "bank-agent", agent(stub))
    messages = [SYSTEM, USER, {"role": "assistant", "content": None, "tool_calls": [CALL]},
                {"role": "tool", "tool_call_id": "call_1", "content": "{\"balance\": 10}"}]
    r = door(client, project, "bank-agent", key, {"model": "x", "messages": messages, "tools": TOOLS})
    assert r.status_code == 200, r.text
    choice = r.json()["choices"][0]
    assert choice["message"]["content"] == "Your balance is 10." and choice["finish_reason"] == "stop"
    assert stub.requests("POST", COMPLETIONS)[-1]["json"]["messages"] == messages


def test_the_openai_door_refuses_a_bad_last_message(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, model)
    key = opened(client, admin, project, "bank-agent", agent(stub))
    r = door(client, project, "bank-agent", key, {"model": "x", "messages": [USER, {"role": "assistant", "content": "a"}]})
    assert r.status_code == 400 and r.json()["error"]["message"] == "the last message must be the user's, or a tool's result"
    rest_key = opened(client, admin, project, "rest-chat", mcas(stub))
    tool_last = [USER, {"role": "assistant", "content": None, "tool_calls": [CALL]},
                 {"role": "tool", "tool_call_id": "call_1", "content": "x"}]
    r = door(client, project, "rest-chat", rest_key, {"model": "x", "messages": tool_last})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "a tool's result can only be sent to an OpenAI-compatible connection"
    r = door(client, project, "bank-agent", key, {"model": "x", "messages": [{"role": "developer", "content": "x"}]})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "messages[0]: role 'developer' is not one of system, user, assistant, tool"
    assert stub.requests("POST", COMPLETIONS) == [] and stub.requests("POST", "/chat") == []


def test_the_probe_checks_tools(client, admin, project, stub, dsn, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LEDGER_MODE", "record")
    stub.route("POST", COMPLETIONS, lambda seen: (200, calls(PROBE_CALL) if (seen.json or {}).get("tools") else TEXT))
    saved(client, admin, project, "bank-agent", agent(stub))
    r = client.post(f"/projects/{project['slug']}/connections/bank-agent/test", json={}, headers=admin)
    assert r.status_code == 200, r.text
    sent = stub.requests("POST", COMPLETIONS)
    assert len(sent) == 2
    assert sent[1]["json"]["tools"] == [PROBE_TOOL]
    assert sent[1]["json"]["tool_choice"] == {"type": "function", "function": {"name": "aisc_probe"}}
    assert r.json()["ok"] is True
    assert r.json()["capabilities"] == {"tools": {"ok": True, "detail": "called aisc_probe"}}

    stub.route("POST", COMPLETIONS, (200, TEXT))
    r = client.post(f"/projects/{project['slug']}/connections/bank-agent/test", json={}, headers=admin)
    missing = "tools: the endpoint answered without calling the function it was asked to call"
    assert r.json() == {"ok": False, "error": "capability_missing", "detail": missing,
                        "capabilities": {"tools": {"ok": False, "detail": missing}}}
    assert one(dsn, project, "select last_test_ok from connection.endpoint where name = 'bank-agent'") == (False,)
    assert latest_tested(project) == {"result": "capability_missing"}


def test_the_probe_checks_logprobs(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, (200, TEXT))
    saved(client, admin, project, "bank-agent", agent(stub, supports_tools=False, supports_logprobs=True))
    r = client.post(f"/projects/{project['slug']}/connections/bank-agent/test", json={}, headers=admin)
    sent = stub.requests("POST", COMPLETIONS)
    assert len(sent) == 2, r.text
    assert sent[1]["json"]["logprobs"] is True and sent[1]["json"]["top_logprobs"] == 1
    assert r.json()["ok"] is True
    assert r.json()["capabilities"] == {"logprobs": {
        "ok": True, "detail": "the endpoint accepted logprobs: true; the log probabilities are not read"}}

    stub.route("POST", COMPLETIONS, lambda seen: (400, {"error": {"message": "no logprobs"}})
               if (seen.json or {}).get("logprobs") else (200, TEXT))
    r = client.post(f"/projects/{project['slug']}/connections/bank-agent/test", json={}, headers=admin)
    assert r.json()["ok"] is False and r.json()["error"] == "capability_missing"
    assert r.json()["detail"] == "logprobs: the endpoint refused logprobs: true (400)"


def test_the_probe_without_flags_is_one_request(client, admin, project, stub):  # noqa: F811
    stub.route("POST", COMPLETIONS, (200, TEXT))
    saved(client, admin, project, "bank-agent", agent(stub, supports_tools=False))
    r = client.post(f"/projects/{project['slug']}/connections/bank-agent/test", json={}, headers=admin)
    assert r.json()["ok"] is True and "capabilities" not in r.json(), r.text
    assert len(stub.requests("POST", COMPLETIONS)) == 1


def test_a_project_made_before_the_capabilities_gets_them_at_the_next_start(client, as_user, unique, dsn, monkeypatch,
                                                                            tmp_path, stub):  # noqa: F811
    old = tmp_path / "template"
    old.mkdir()
    for f in sorted(projectdb.TEMPLATE.glob("*.sql")):
        if f.name < "0024":
            shutil.copy(f, old / f.name)
    real = projectdb.TEMPLATE
    monkeypatch.setattr(projectdb, "TEMPLATE", old)
    made = client.post("/projects", json={"name": unique("pre-tools")}, headers=as_user(ALICE)).json()
    column = ("select count(*) from information_schema.columns where table_schema = 'connection'"
              " and table_name = 'endpoint' and column_name in ('supports_tools', 'supports_logprobs')")
    assert one(dsn, made, column) == (0,)
    with project_db(dsn, made) as conn:
        conn.execute("insert into connection.endpoint (name, label, kind, base_url, model, timeout_s, secret_ciphertext)"
                     " values ('old-model', 'Old', 'openai', %s, 'gpt-4o-mini', 5, %s)",
                     (stub.base + "/v1", llm_store.encrypt(new_secret())))
    monkeypatch.setattr(projectdb, "TEMPLATE", real)
    monkeypatch.setattr(db, "_unprovisioned", None)
    db.pool()
    assert one(dsn, made, column) == (2,)
    assert one(dsn, made, "select supports_tools, supports_logprobs from connection.endpoint"
                          " where name = 'old-model'") == (False, False)
    r = issue(client, made, "old-model")
    assert r.status_code == 201, r.text
    assert r.json()["capabilities"] == ["text", "history"]
