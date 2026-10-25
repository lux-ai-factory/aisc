"""AISC's own door to a connection, aisc/ask: an input, a full OpenAI-style history (tool calls and
tool results included) and parameters for the request (template values, or an OpenAI-compatible
model's generation settings). What the platform will not send is a 400 with the reason, what the
system did is a 502 with its status and its scrubbed words. Runs on the throwaway; the system under
test is a local stub."""
from __future__ import annotations

import json
import logging
import re

import pytest

from tests.conftest import needs_database
from tests.connection_support import new_secret
from tests.test_connection_facades import _env, base, issue, keyed, mcas, stub  # noqa: F401  (fixtures)

pytestmark = needs_database

OPENAI_LIST = ("temperature, top_p, max_tokens, max_completion_tokens, stop, seed, presence_penalty, "
               "frequency_penalty, logit_bias, response_format, user, tools, tool_choice, parallel_tool_calls")
CALL = {"id": "call_1", "type": "function", "function": {"name": "get_balance", "arguments": "{\"iban\": \"LU12\"}"}}
OPENAI_ANSWER = {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}


def scorer(stub, **over):  # noqa: F811
    body = {"label": "MCAS scorer", "kind": "rest", "base_url": stub.base, "path": "/score",
            "body_template": {"applicant": "{{input}}", "lang": "{{params.lang}}", "explain": "{{params.explain}}"},
            "response_path": "decision", "timeout_s": 5, "secret": new_secret()}
    body.update(over)
    return body


def openai(stub, **over):  # noqa: F811
    body = {"label": "Bank model", "kind": "openai", "base_url": stub.base + "/v1", "model": "gpt-4o-mini",
            "timeout_s": 5, "secret": new_secret()}
    body.update(over)
    return body


def a2a(stub, **over):  # noqa: F811
    body = {"label": "An agent", "kind": "a2a", "base_url": stub.base, "path": "/rpc", "protocol_version": "1.0"}
    body.update(over)
    return body


def connection(client, admin, project, stub, name, body):  # noqa: F811
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return name


def ask(client, project, name, key, payload=None, content=None):
    url = f"{base(project, name)}/aisc/ask"
    if content is not None:
        return client.post(url, content=content, headers={**keyed(key), "Content-Type": "application/json"})
    return client.post(url, json=payload, headers=keyed(key))


def opened(client, admin, project, stub, name, body):  # noqa: F811
    connection(client, admin, project, stub, name, body)
    return issue(client, project, name).json()["key"]


def test_params_fill_the_body_template(client, admin, project, stub):  # noqa: F811
    stub.route("POST", "/score", (200, {"decision": "approve"}))
    key = opened(client, admin, project, stub, "scorer", scorer(stub))
    r = ask(client, project, "scorer", key, {"input": {"amount": 2500}, "params": {"lang": "en", "explain": True}})
    assert r.status_code == 200, r.text
    assert r.json()["output"] == "approve" and r.json()["tool_calls"] is None
    assert stub.requests("POST", "/score")[-1]["json"] == {"applicant": {"amount": 2500}, "lang": "en", "explain": True}


def test_a_missing_template_parameter_is_the_direct_error(client, admin, project, stub):  # noqa: F811
    key = opened(client, admin, project, stub, "scorer", scorer(stub))
    r = ask(client, project, "scorer", key, {"input": {"amount": 2500}, "params": {"explain": True}})
    assert r.status_code == 502, r.text
    assert r.json() == {"error": "error", "status": None, "detail": "the request template needs the parameter 'lang'"}
    assert stub.requests("POST", "/score") == []


def test_openai_extra_params_reach_the_model(client, admin, project, stub):  # noqa: F811
    stub.route("POST", "/v1/chat/completions", (200, OPENAI_ANSWER))
    key = opened(client, admin, project, stub, "bank-model", openai(stub))
    r = ask(client, project, "bank-model", key, {"input": "q", "params": {"temperature": 0, "max_tokens": 20, "seed": 7}})
    assert r.status_code == 200, r.text
    assert r.json()["output"] == "ok"
    assert stub.requests("POST", "/v1/chat/completions")[-1]["json"] == {
        "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "q"}],
        "temperature": 0, "max_tokens": 20, "seed": 7}


@pytest.mark.parametrize("param,value", [("stream", True), ("model", "other"), ("messages", []), ("n", 2),
                                       ("logprobs", True)])
def test_openai_params_outside_the_list_are_refused(client, admin, project, stub, param, value):  # noqa: F811
    stub.route("POST", "/v1/chat/completions", (200, OPENAI_ANSWER))
    run_key = opened(client, admin, project, stub, "bank-model", openai(stub))
    r = ask(client, project, "bank-model", run_key, {"input": "q", "params": {param: value}})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == f"params: {param!r} is not a parameter an OpenAI-compatible connection takes ({OPENAI_LIST})"
    assert stub.requests("POST", "/v1/chat/completions") == []


def test_params_must_be_an_object(client, admin, project, stub):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "q", "params": [1]})
    assert r.status_code == 400 and r.json() == {"detail": "params: an object of parameters"}, r.text
    r = ask(client, project, "mcas-chat", key, {"input": "q", "params": None})
    assert r.status_code == 200, r.text


def test_the_params_caps(client, admin, project, stub):  # noqa: F811
    key = opened(client, admin, project, stub, "scorer", scorer(stub))
    r = ask(client, project, "scorer", key, {"input": "q", "params": {"lang": "x" * 262_144}})
    assert r.status_code == 400, r.text
    assert re.fullmatch(r"params: \d+ bytes as JSON, more than 262144", r.json()["detail"]), r.json()
    r = ask(client, project, "scorer", key, {"input": "q", "params": {f"p{i}": 1 for i in range(65)}})
    assert r.status_code == 400 and r.json()["detail"] == "params: 65 parameters, more than 64", r.text
    r = ask(client, project, "scorer", key, {"input": "q", "params": {"a-b": 1}})
    assert r.status_code == 400 and r.json()["detail"] == "params: 'a-b' is not a parameter name", r.text
    assert stub.requests("POST", "/score") == []


def test_a_full_openai_history_reaches_the_system(client, admin, project, stub):  # noqa: F811
    hist = [{"role": "system", "content": "You are a bank agent."}, {"role": "user", "content": "My balance?"},
            {"role": "assistant", "content": None, "tool_calls": [CALL]},
            {"role": "tool", "tool_call_id": "call_1", "content": "{\"balance\": 10}"}]
    stub.route("POST", "/chat", (200, {"answer": "10"}))
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "And now?", "history": hist})
    assert r.status_code == 200, r.text
    assert stub.requests("POST", "/chat")[-1]["json"]["history"] == hist


@pytest.mark.parametrize("history,message", [
    ([{"role": "developer", "content": "x"}], "history[0]: role 'developer' is not one of system, user, assistant, tool"),
    ([{"role": "user", "content": "x"}] * 201, "history: 201 messages, more than 200"),
    ("x", "history: a list of messages"),
    ([{"role": "tool", "content": "x"}], "history[0]: a tool message needs a tool_call_id and text content"),
], ids=["role", "length", "not-a-list", "tool-without-id"])
def test_a_bad_history_is_400_with_the_interfaces_words(client, admin, project, stub, history, message):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "q", "history": history})
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": message}
    assert stub.requests("POST", "/chat") == []
    assert ask(client, project, "mcas-chat", key, {"input": "q", "history": None}).status_code == 200


@pytest.mark.parametrize("payload", [{}, [], b"not json"], ids=["no-input", "a-list", "not-json"])
def test_a_body_without_input_is_400(client, admin, project, stub, payload):  # noqa: F811
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    if isinstance(payload, bytes):
        r = ask(client, project, "mcas-chat", key, content=payload)
    else:
        r = ask(client, project, "mcas-chat", key, payload)
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": "{input, history?: [messages], params?: {}}"}


def test_a_body_over_two_mebibytes_is_413(client, admin, project, stub):  # noqa: F811
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "x" * 2_097_153})
    assert r.status_code == 413, r.text[:300]
    assert r.json() == {"detail": "the request is more than 2097152 bytes"}
    assert stub.requests("POST", "/chat") == []


@pytest.mark.parametrize("status,expected", [
    (422, {"error": "bad_response", "status": 422,
           "detail": "MCAS chat: the system answered 422: " + json.dumps({"detail": "bad"})}),
    (401, {"error": "auth", "status": 401, "detail": "MCAS chat: the system refused the credentials (401)"}),
    (404, {"error": "not_found", "status": 404, "detail": "MCAS chat: nothing at /chat (404)"}),
    (500, {"error": "bad_response", "status": 500, "detail": "MCAS chat: the system answered 500"}),
])
def test_a_failure_carries_its_status_and_detail(client, admin, project, stub, status, expected):  # noqa: F811
    # a 500 is retried: the stub answers it every time, three times
    stub.route("POST", "/chat", (status, {"detail": "bad"}))
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "q"})
    assert r.status_code == 502, r.text
    assert r.json() == expected
    if status == 500:
        assert len(stub.requests("POST", "/chat")) == 3


def test_a_key_the_system_echoes_is_scrubbed_from_the_detail(client, admin, project, stub, caplog):  # noqa: F811
    secret = new_secret()
    stub.route("POST", "/chat", (422, {"echo": secret}))
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub, secret=secret))
    with caplog.at_level(logging.WARNING, logger="platform_service.app"):
        r = ask(client, project, "mcas-chat", key, {"input": "q"})
    assert r.status_code == 502, r.text
    assert secret not in r.text
    assert "***" in r.json()["detail"]
    assert not [rec.getMessage() for rec in caplog.records if secret in rec.getMessage()]


def test_a_history_sent_to_an_a2a_agent_is_the_direct_error(client, admin, project, stub):  # noqa: F811
    key = opened(client, admin, project, stub, "agent", a2a(stub))
    r = ask(client, project, "agent", key, {"input": "q", "history": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502, r.text
    assert r.json() == {"error": "error", "status": None,
                        "detail": "An agent: an A2A agent keeps its own context; a history cannot be sent to it"}
    assert stub.requests("POST", "/rpc") == []


def test_the_answer_always_carries_tool_calls(client, admin, project, stub):  # noqa: F811
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "q"})
    assert r.status_code == 200, r.text
    assert "tool_calls" in r.json() and r.json()["tool_calls"] is None


def test_a_bad_request_from_call_is_400(client, admin, project, stub, monkeypatch):  # noqa: F811
    from aisc_plugin_interface import connections as client_module

    def refuse(*args, **kwargs):
        raise client_module.BadRequest("history[0]: name is text")

    monkeypatch.setattr(client_module, "call", refuse)
    key = opened(client, admin, project, stub, "mcas-chat", mcas(stub))
    r = ask(client, project, "mcas-chat", key, {"input": "q"})
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": "history[0]: name is text"}
