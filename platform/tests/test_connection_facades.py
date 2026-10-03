"""Tools reaching a connection through a standard protocol: run keys
issued to a run, and the AISC-native, OpenAI-compatible, A2A (1.0 and 0.3) and Open Inference
Protocol endpoints in front of one connection; plus the a2a and oip connection kinds. Runs on the
throwaway; the system under test is a local stub."""
from __future__ import annotations

import hashlib
import json

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, Stub, engine_component, new_secret

pytestmark = needs_database
ALICE = "00000000-0000-0000-0000-00000000a11c"


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
    monkeypatch.setenv("PLATFORM_INTERNAL_URL", "http://platform:8000")


@pytest.fixture
def admin(as_user):
    return as_user("root", roles=("admin",))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("facade")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()


def mcas(stub, **over):
    body = {"label": "MCAS chat", "kind": "rest", "base_url": stub.base, "path": "/chat",
            "body_template": {"question": "{{input}}", "history": "{{history}}"}, "response_path": "answer",
            "refusal": {"status": [502], "path": "detail.reason", "match": {"detail.error": "answer_not_grounded"}},
            "timeout_s": 5, "secret": new_secret()}
    body.update(over)
    return body


def connection(client, admin, project, stub, name="mcas-chat", **over):
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=mcas(stub, **over), headers=admin)
    assert r.status_code == 200, r.text
    return name


def issue(client, project, name, token=CONNECTIONS_TOKEN):
    return client.post(f"/internal/projects/{project['pid']}/connections/{name}/run-keys",
                       headers={"X-AISC-Service-Token": token})


def keyed(key):
    return {"Authorization": f"Bearer {key}"}


def base(project, name):
    return f"/internal/facade/{project['pid']}/{name}"


def one(dsn, project, sql, params=()):
    with psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(project["pid"]))) as conn:
        return conn.execute(sql, params).fetchone()


# Run keys
def test_run_keys_are_issued_with_every_protocols_endpoint_and_stored_hashed(client, admin, project, stub, dsn):
    name = connection(client, admin, project, stub)
    r = issue(client, project, name)
    assert r.status_code == 201, r.text
    d = r.json()
    key, pid = d["key"], project["pid"]
    root = f"http://platform:8000/internal/facade/{pid}/{name}"
    assert d["endpoints"] == {
        "aisc": {"ask_url": f"{root}/aisc/ask"},
        "openai": {"base_url": f"{root}/openai/v1", "model": name},
        "a2a": {"agent_card_url": f"{root}/a2a/.well-known/agent-card.json", "rpc_url": f"{root}/a2a"},
        "oip": {"base_url": f"{root}/oip", "model": name},
    }
    assert d["expires_at"]
    stored = one(dsn, project, "select key_hash, name, fingerprint, uses from connection.run_key")
    assert stored[0] == hashlib.sha256(key.encode()).hexdigest() and stored[1] == name and stored[3] == 0
    assert key not in json.dumps([str(x) for x in stored])


def test_run_keys_need_the_service_token_and_an_existing_connection(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    assert issue(client, project, name, token="wrong").status_code == 401
    assert issue(client, project, "nope").status_code == 404


def test_the_endpoints_refuse_a_missing_wrong_expired_or_other_connections_key(client, admin, project, stub, dsn):
    a = connection(client, admin, project, stub, "a-sys")
    b = connection(client, admin, project, stub, "b-sys")
    key_a = issue(client, project, a).json()["key"]
    ask = lambda n, h: client.post(f"{base(project, n)}/aisc/ask", json={"input": "q"}, headers=h)
    assert ask(a, {}).status_code == 401
    assert ask(a, keyed("aisc-run-wrong")).status_code == 401
    assert ask(b, keyed(key_a)).status_code == 401
    with psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(project["pid"]))) as conn:
        conn.execute("update connection.run_key set expires_at = now() - interval '1 second'")
    assert ask(a, keyed(key_a)).status_code == 401


def test_the_endpoints_are_not_reachable_through_the_gateway(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    r = client.post(f"{base(project, name)}/aisc/ask", json={"input": "q"},
                    headers={**keyed(key), "X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 404


def test_every_call_counts_on_its_run_key(client, admin, project, stub, dsn):
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    for _ in range(3):
        client.post(f"{base(project, name)}/aisc/ask", json={"input": "q"}, headers=keyed(key))
    uses, last = one(dsn, project, "select uses, last_used_at from connection.run_key")
    assert uses == 3 and last is not None


# AISC-native
def test_aisc_ask_answers_and_passes_the_history(client, admin, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "Up to 5,000 EUR (POL-ELIG-001)."}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    r = client.post(f"{base(project, name)}/aisc/ask", json={"input": "How much?", "history": hist}, headers=keyed(key))
    assert r.status_code == 200, r.text
    assert r.json()["output"].startswith("Up to 5,000") and r.json()["refused"] is False
    assert stub.requests("POST", "/chat")[-1]["json"] == {"question": "How much?", "history": hist}


def test_aisc_ask_reports_a_refusal_and_an_upstream_failure(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    stub.route("POST", "/chat", (502, {"detail": {"error": "answer_not_grounded", "reason": "no clause"}}))
    out = client.post(f"{base(project, name)}/aisc/ask", json={"input": "q"}, headers=keyed(key)).json()
    assert out["refused"] is True and out["refusal_reason"] == "no clause"
    stub.route("POST", "/chat", (401, {"detail": "bad"}))
    r = client.post(f"{base(project, name)}/aisc/ask", json={"input": "q"}, headers=keyed(key))
    assert r.status_code == 502 and r.json()["error"] == "auth"


# OpenAI-compatible
def test_openai_chat_completions_maps_messages_to_input_and_history(client, admin, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "No, it is not."}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    msgs = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"}, {"role": "user", "content": "Is nationality an input?"}]
    r = client.post(f"{base(project, name)}/openai/v1/chat/completions", json={"model": "anything", "messages": msgs,
                                                                           "temperature": 0}, headers=keyed(key))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["object"] == "chat.completion" and d["model"] == name and d["id"].startswith("chatcmpl-")
    assert d["choices"][0]["message"] == {"role": "assistant", "content": "No, it is not.", "refusal": None}
    assert d["choices"][0]["finish_reason"] == "stop" and d["choices"][0]["index"] == 0 and "usage" in d
    assert stub.requests("POST", "/chat")[-1]["json"] == {"question": "Is nationality an input?", "history": msgs[:3]}


def test_openai_a_refusal_is_content_filter_with_the_reason(client, admin, project, stub):
    stub.route("POST", "/chat", (502, {"detail": {"error": "answer_not_grounded", "reason": "no clause"}}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    d = client.post(f"{base(project, name)}/openai/v1/chat/completions",
                    json={"model": name, "messages": [{"role": "user", "content": "q"}]}, headers=keyed(key)).json()
    choice = d["choices"][0]
    assert choice["finish_reason"] == "content_filter" and choice["message"]["refusal"] == "no clause"
    assert "no clause" in choice["message"]["content"]


def test_openai_streaming_and_a_missing_user_message_are_refused_in_openai_form(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    url = f"{base(project, name)}/openai/v1/chat/completions"
    r = client.post(url, json={"model": name, "stream": True, "messages": [{"role": "user", "content": "q"}]}, headers=keyed(key))
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"
    r = client.post(url, json={"model": name, "messages": [{"role": "system", "content": "x"}]}, headers=keyed(key))
    assert r.status_code == 400
    assert client.post(url, json={"model": name, "messages": []}).status_code == 401


def test_openai_models_lists_the_connection(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    d = client.get(f"{base(project, name)}/openai/v1/models", headers=keyed(key)).json()
    assert d["object"] == "list" and [m["id"] for m in d["data"]] == [name]


# A2A
def test_a2a_agent_card_is_a_1_0_card_with_the_jsonrpc_interface(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    card = client.get(f"{base(project, name)}/a2a/.well-known/agent-card.json", headers=keyed(key)).json()
    for field in ("name", "description", "version", "capabilities", "defaultInputModes", "defaultOutputModes", "skills"):
        assert field in card, field
    assert card["supportedInterfaces"] == [{"url": f"http://platform:8000{base(project, name)}/a2a",
                                            "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]
    assert card["capabilities"]["streaming"] is False
    assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "Bearer"
    assert card["skills"][0]["id"] and card["skills"][0]["tags"]


def test_a2a_sendmessage_answers_with_an_agent_message(client, admin, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "Yes (POL-FAIR-002)."}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    req = {"jsonrpc": "2.0", "id": 7, "method": "SendMessage",
           "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "Can I appeal?"}]}}}
    d = client.post(f"{base(project, name)}/a2a", json=req, headers={**keyed(key), "A2A-Version": "1.0"}).json()
    assert d["jsonrpc"] == "2.0" and d["id"] == 7
    msg = d["result"]["message"]
    assert msg["role"] == "ROLE_AGENT" and msg["parts"] == [{"text": "Yes (POL-FAIR-002)."}] and msg["messageId"]
    assert stub.requests("POST", "/chat")[-1]["json"]["question"] == "Can I appeal?"


def test_a2a_a_refusal_is_a_rejected_task(client, admin, project, stub):
    stub.route("POST", "/chat", (502, {"detail": {"error": "answer_not_grounded", "reason": "no clause"}}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    req = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
           "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "q"}]}}}
    task = client.post(f"{base(project, name)}/a2a", json=req, headers=keyed(key)).json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert task["status"]["message"]["parts"] == [{"text": "no clause"}] and task["id"]


def test_a2a_0_3_message_send_is_answered_in_the_0_3_dialect(client, admin, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    req = {"jsonrpc": "2.0", "id": "x", "method": "message/send",
           "params": {"message": {"kind": "message", "messageId": "m", "role": "user", "parts": [{"kind": "text", "text": "q"}]}}}
    res = client.post(f"{base(project, name)}/a2a", json=req, headers=keyed(key)).json()["result"]
    assert res["kind"] == "message" and res["role"] == "agent" and res["parts"] == [{"kind": "text", "text": "ok"}]


def test_a2a_unknown_methods_bad_params_and_upstream_failures_are_jsonrpc_errors(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    url = f"{base(project, name)}/a2a"
    assert client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "CancelTask", "params": {}}, headers=keyed(key)).json()["error"]["code"] == -32601
    assert client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {}}, headers=keyed(key)).json()["error"]["code"] == -32602
    stub.route("POST", "/chat", (401, {"detail": "bad"}))
    req = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
           "params": {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "q"}]}}}
    err = client.post(url, json=req, headers=keyed(key)).json()["error"]
    assert err["code"] == -32603 and "auth" in err["message"]


# Open Inference Protocol
def test_oip_server_and_model_metadata_and_health(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    b = f"{base(project, name)}/oip"
    assert client.get(f"{b}/v2", headers=keyed(key)).json()["name"]
    assert client.get(f"{b}/v2/health/live", headers=keyed(key)).status_code == 200
    assert client.get(f"{b}/v2/health/ready", headers=keyed(key)).status_code == 200
    meta = client.get(f"{b}/v2/models/{name}", headers=keyed(key)).json()
    assert meta["name"] == name and meta["platform"]
    assert {t["name"]: t["datatype"] for t in meta["inputs"]} == {"input": "BYTES"}
    assert {t["name"]: t["datatype"] for t in meta["outputs"]} == {"output": "BYTES", "refused": "BOOL"}
    assert client.get(f"{b}/v2/models/{name}/ready", headers=keyed(key)).status_code == 200
    r = client.get(f"{b}/v2/models/other", headers=keyed(key))
    assert r.status_code == 404 and "error" in r.json()


def test_oip_infer_answers_a_batch_and_marks_refusals(client, admin, project, stub):
    stub.route("POST", "/chat", (200, {"answer": "A"}),
               (502, {"detail": {"error": "answer_not_grounded", "reason": "no clause"}}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    req = {"id": "r1", "inputs": [{"name": "input", "shape": [2], "datatype": "BYTES", "data": ["q1", "q2"]}]}
    d = client.post(f"{base(project, name)}/oip/v2/models/{name}/infer", json=req, headers=keyed(key)).json()
    assert d["model_name"] == name and d["id"] == "r1"
    outs = {o["name"]: o for o in d["outputs"]}
    assert outs["output"]["datatype"] == "BYTES" and outs["output"]["shape"] == [2]
    assert outs["output"]["data"] == ["A", "no clause"] and outs["refused"]["data"] == [False, True]


def test_oip_a_bad_request_or_an_upstream_failure_is_an_error_object(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    url = f"{base(project, name)}/oip/v2/models/{name}/infer"
    r = client.post(url, json={"inputs": []}, headers=keyed(key))
    assert r.status_code == 400 and "error" in r.json()
    stub.route("POST", "/chat", (401, {"detail": "bad"}))
    r = client.post(url, json={"inputs": [{"name": "input", "shape": [1], "datatype": "BYTES", "data": ["q"]}]}, headers=keyed(key))
    assert r.status_code == 502 and "auth" in r.json()["error"]


# The a2a and oip connection kinds
def test_an_a2a_connection_is_saved_and_tested(client, admin, project, stub):
    stub.route("POST", "/rpc", (200, lambda r: {"jsonrpc": "2.0", "id": r["json"]["id"], "result": {
        "message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "pong"}]}}}))
    engine_component(stub, project["pid"])
    body = {"label": "An agent", "kind": "a2a", "base_url": stub.base, "path": "/rpc", "protocol_version": "1.0"}
    assert client.put(f"/projects/{project['slug']}/connections/agent", json=body, headers=admin).status_code == 200
    out = client.post(f"/projects/{project['slug']}/connections/agent/test", json={}, headers=admin).json()
    assert out["ok"] is True and out["answer"] == "pong"
    bad = client.put(f"/projects/{project['slug']}/connections/agent", json={**body, "protocol_version": "2.0"}, headers=admin)
    assert bad.status_code == 422


def test_an_oip_connection_needs_a_model_and_is_tested(client, admin, project, stub):
    stub.route("POST", "/v2/models/scorer/infer", (200, {"model_name": "scorer", "outputs": [
        {"name": "output", "shape": [1], "datatype": "BYTES", "data": ["Approve"]}]}))
    engine_component(stub, project["pid"])
    body = {"label": "Scorer", "kind": "oip", "base_url": stub.base}
    assert client.put(f"/projects/{project['slug']}/connections/scorer", json=body, headers=admin).status_code == 422
    assert client.put(f"/projects/{project['slug']}/connections/scorer", json={**body, "model": "scorer"}, headers=admin).status_code == 200
    out = client.post(f"/projects/{project['slug']}/connections/scorer/test", json={}, headers=admin).json()
    assert out["ok"] is True and out["answer"] == "Approve"
