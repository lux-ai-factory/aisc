"""A system that echoes its own credentials never hands them to the plugin: every protocol door removes the
connection's key and each secret header value, as they are, base64-encoded and URL-encoded, from a
successful answer's output, from a refusal's reason and from tool calls, putting *** in their place. And a
secret header value the system echoes in an error is taken out before the client cuts the text to 300
characters, so not even its first characters reach the plugin, the warning log or the Test button. Runs on
the throwaway; the system under test is a local stub."""
from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import uuid

import pytest

from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, engine_component, new_secret
from tests.http_stub import Canned
from tests.test_connection_facades import _env, stub  # noqa: F401  (fixtures)

pytestmark = needs_database


def _key() -> str:
    """A key whose URL-encoded form differs from itself."""
    return new_secret() + "/+=&"


def _token() -> str:
    return "tok/" + uuid.uuid4().hex + "+=&"


def forms(value: str) -> dict:
    return {"plain": value, "b64": base64.b64encode(value.encode()).decode(),
            "url": urllib.parse.quote(value, safe="")}


def every_form(*values) -> list[str]:
    return [f for v in values for f in forms(v).values()]


def echo(seen):
    """The system answers with the credentials it was sent, in three encodings each."""
    auth = seen.header("authorization") or ""
    key = auth.removeprefix("Bearer ")
    token = seen.header("x-token") or ""
    return Canned(200, json.dumps({"answer": {
        "auth": auth, "key": forms(key), "token": forms(token)}}).encode())


SCRUBBED = {"auth": "Bearer ***", "key": {"plain": "***", "b64": "***", "url": "***"},
            "token": {"plain": "***", "b64": "***", "url": "***"}}


def rest(stub, key, token, **over):  # noqa: F811
    body = {"label": "Echo", "kind": "rest", "base_url": stub.base, "path": "/echo",
            "secret_header": "Authorization: Bearer {{secret}}", "secret_headers": {"X-Token": token},
            "body_template": {"question": "{{input}}"}, "response_path": "answer", "timeout_s": 5, "secret": key}
    body.update(over)
    return body


def put(client, admin, project, stub, name, body):  # noqa: F811
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return name


def run_key(client, project, name):
    r = client.post(f"/internal/projects/{project['pid']}/connections/{name}/run-keys",
                    headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 201, r.text
    return r.json()["key"]


def door(project, name):
    return f"/internal/facade/{project['pid']}/{name}"


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def assert_none_of(text, values):
    leaked = [v for v in values if v in text]
    assert not leaked, f"answered back: {leaked} in {text[:400]}"


def eight_character_runs(value: str) -> list[str]:
    return [value[i:i + 8] for i in range(len(value) - 7)]


def assert_no_part_of(text, value):
    parts = [p for p in eight_character_runs(value) if p in text]
    assert not parts, f"part of a secret answered back: {parts[:3]} in {text[-80:]!r}"


# a 200 answer

def test_the_aisc_door_answers_the_output_with_every_echoed_credential_scrubbed(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", echo)
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"}, headers=bearer(run_key(client, project, name)))
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key, token))
    assert r.json()["output"] == SCRUBBED
    # the system did get the real credentials: only the answer is scrubbed
    sent = stub.requests("POST", "/echo")[-1]
    assert sent["headers"]["authorization"] == f"Bearer {key}" and sent["headers"]["x-token"] == token


def test_the_openai_door_answers_no_echoed_credential(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", echo)
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    r = client.post(f"{door(project, name)}/openai/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "q"}]}, headers=bearer(run_key(client, project, name)))
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key, token))
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == SCRUBBED


def test_the_a2a_door_answers_no_echoed_credential(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", echo)
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    r = client.post(f"{door(project, name)}/a2a", headers=bearer(run_key(client, project, name)), json={
        "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
        "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "q"}]}}})
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key, token))
    assert r.json()["result"]["message"]["parts"] == [{"data": SCRUBBED}]


def test_the_oip_door_answers_no_echoed_credential(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", echo)
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    r = client.post(f"{door(project, name)}/oip/v2/models/{name}/infer", headers=bearer(run_key(client, project, name)),
                    json={"inputs": [{"name": "input", "datatype": "BYTES", "shape": [1], "data": ["q"]}]})
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key, token))
    assert json.loads(r.json()["outputs"][0]["data"][0]) == SCRUBBED


def test_a_text_answer_keeps_its_words_around_the_scrubbed_key(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", lambda seen: Canned(200, json.dumps(
        {"answer": f"you sent {seen.header('authorization')} and {seen.header('x-token')}."}).encode()))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"}, headers=bearer(run_key(client, project, name)))
    assert r.status_code == 200, r.text
    assert r.json()["output"] == "you sent Bearer *** and ***."


# a refusal

def test_a_refusal_reason_that_echoes_the_credentials_is_scrubbed_on_both_doors(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", lambda seen: Canned(451, json.dumps(
        {"why": f"{seen.header('authorization')} {seen.header('x-token')}"}).encode()))
    name = put(client, admin, project, stub, "echo",
               rest(stub, key, token, refusal={"status": [451], "path": "why"}))
    rk = run_key(client, project, name)
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"}, headers=bearer(rk))
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key, token))
    assert r.json()["refused"] is True and r.json()["refusal_reason"] == "Bearer *** ***"
    r = client.post(f"{door(project, name)}/openai/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "q"}]}, headers=bearer(rk))
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key, token))
    assert r.json()["choices"][0]["message"]["refusal"] == "Bearer *** ***"


# tool calls

TOOLS = [{"type": "function", "function": {"name": "get_balance", "parameters": {"type": "object"}}}]


def tool_echo(seen):
    """A model that calls a tool with the Authorization header it was sent as the argument."""
    arguments = json.dumps({"auth": seen.header("authorization")})
    return Canned(200, json.dumps({"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "get_balance", "arguments": arguments}}]}}]}).encode())


def test_tool_calls_that_echo_the_key_are_scrubbed_on_both_doors(client, admin, project, stub):  # noqa: F811
    key = _key()
    stub.route("POST", "/v1/chat/completions", tool_echo)
    name = put(client, admin, project, stub, "agent", {
        "label": "Agent", "kind": "openai", "base_url": stub.base + "/v1", "model": "gpt", "timeout_s": 5,
        "secret": key, "supports_tools": True})
    rk = run_key(client, project, name)
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q", "params": {"tools": TOOLS}},
                    headers=bearer(rk))
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key))
    [call] = r.json()["tool_calls"]
    assert json.loads(call["function"]["arguments"]) == {"auth": "Bearer ***"}
    r = client.post(f"{door(project, name)}/openai/v1/chat/completions", headers=bearer(rk),
                    json={"messages": [{"role": "user", "content": "q"}], "tools": TOOLS})
    assert r.status_code == 200, r.text
    assert_none_of(r.text, every_form(key))
    [call] = r.json()["choices"][0]["message"]["tool_calls"]
    assert json.loads(call["function"]["arguments"]) == {"auth": "Bearer ***"}


def test_an_answer_without_credentials_is_returned_as_it_is(client, admin, project, stub):  # noqa: F811
    stub.route("POST", "/echo", (200, {"answer": {"text": "Up to 5,000 EUR.", "n": 3, "items": ["a", "***x"]}}))
    name = put(client, admin, project, stub, "echo", rest(stub, _key(), _token()))
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"}, headers=bearer(run_key(client, project, name)))
    assert r.status_code == 200, r.text
    assert r.json()["output"] == {"text": "Up to 5,000 EUR.", "n": 3, "items": ["a", "***x"]}


# a secret header value across the client's 300-character cut

def test_a_secret_header_value_across_the_cut_is_not_partly_answered(client, admin, project, stub, caplog):  # noqa: F811
    key = new_secret()
    token = "tok-" + uuid.uuid4().hex + uuid.uuid4().hex
    stub.route("POST", "/echo", (422, b"A" * 250 + token.encode()))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    with caplog.at_level(logging.WARNING):
        r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"},
                        headers=bearer(run_key(client, project, name)))
    assert r.status_code == 502, r.text
    assert_no_part_of(r.text, token)
    for message in caplog.messages:
        assert_no_part_of(message, token)


def test_the_test_button_stores_no_part_of_a_secret_header_value_across_the_cut(client, admin, project, stub):  # noqa: F811
    token = "tok-" + uuid.uuid4().hex + uuid.uuid4().hex
    stub.route("POST", "/echo", (422, b"A" * 250 + token.encode()))
    name = put(client, admin, project, stub, "echo", rest(stub, new_secret(), token))
    r = client.post(f"/projects/{project['slug']}/connections/{name}/test", json={}, headers=admin)
    assert_no_part_of(r.text, token)
    listed = client.get(f"/projects/{project['slug']}/connections", headers=admin)
    assert listed.status_code == 200, listed.text
    assert_no_part_of(listed.text, token)
