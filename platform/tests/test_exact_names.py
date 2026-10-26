"""Names are checked whole: a connection, header, parameter or tool name with a trailing newline (which a
`$` at the end of a pattern lets through) is refused with the field named, never stored and never a 500.
Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import pytest

from platform_service import connection_facade
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, engine_component, new_secret
from tests.test_connection_facades import _env, stub  # noqa: F401  (fixtures)

TOOLS_MESSAGE = ("params: tools[0] needs type 'function' and a function with a name (letters, digits, _ and -, "
                 "up to 64)")
NAME_MESSAGE = "name: lower-case letters, digits and hyphens, up to 63"


def rest(stub, **over):  # noqa: F811
    body = {"label": "N", "kind": "rest", "base_url": stub.base, "path": "/chat",
            "body_template": {"q": "{{input}}", "lang": "{{params.lang}}"}, "response_path": "answer",
            "timeout_s": 5, "secret": new_secret()}
    body.update(over)
    return body


def names(client, admin, project):
    r = client.get(f"/projects/{project['slug']}/connections", headers=admin)
    assert r.status_code == 200, r.text
    return [c["name"] for c in r.json()["connections"]]


# pure checks

def test_a_parameter_name_with_a_trailing_newline_is_refused():
    with pytest.raises(connection_facade.BadRequest) as exc:
        connection_facade.check_params("rest", False, {"lang\n": "en"})
    assert str(exc.value) == "params: 'lang\\n' is not a parameter name"


def test_a_tool_name_with_a_trailing_newline_is_refused():
    tools = [{"type": "function", "function": {"name": "get_balance\n"}}]
    with pytest.raises(connection_facade.BadRequest) as exc:
        connection_facade.check_params("openai", True, {"tools": tools})
    assert str(exc.value) == TOOLS_MESSAGE


def test_names_without_a_newline_still_pass():
    tools = [{"type": "function", "function": {"name": "get_balance"}}]
    assert connection_facade.check_params("openai", True, {"tools": tools, "temperature": 0}) == {
        "tools": tools, "temperature": 0}
    assert connection_facade.check_params("rest", False, {"lang": "en"}) == {"lang": "en"}


# routes

@needs_database
def test_a_connection_named_with_a_trailing_newline_is_a_422(client, admin, project, stub):  # noqa: F811
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/spare%0A", json=rest(stub), headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == NAME_MESSAGE
    assert names(client, admin, project) == []


@needs_database
@pytest.mark.parametrize("field, value, message", [
    ("headers", {"X-Client\n": "aisc"}, "headers: 'X-Client\\n' is not a header name"),
    ("secret_headers", {"X-Tok\n": "v"}, "secret_headers: 'X-Tok\\n' is not a header name"),
])
def test_a_header_named_with_a_trailing_newline_is_a_422(client, admin, project, stub, field, value, message):  # noqa: F811
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/hdr", json=rest(stub, **{field: value}), headers=admin)
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == message
    assert names(client, admin, project) == []


@needs_database
def test_the_internal_routes_answer_a_name_with_a_newline_without_a_500(client, admin, project, stub):  # noqa: F811
    engine_component(stub, project["pid"])
    r = client.put(f"/projects/{project['slug']}/connections/spare", json=rest(stub), headers=admin)
    assert r.status_code == 200, r.text
    token = {"X-AISC-Service-Token": CONNECTIONS_TOKEN}
    r = client.get(f"/internal/projects/{project['pid']}/connections/spare%0A", headers=token)
    assert r.status_code in (404, 422), r.text
    r = client.post(f"/internal/projects/{project['pid']}/connections/spare%0A/run-keys", headers=token)
    assert r.status_code in (404, 422), r.text
    key = client.post(f"/internal/projects/{project['pid']}/connections/spare/run-keys", headers=token).json()["key"]
    r = client.post(f"/internal/facade/{project['pid']}/spare%0A/aisc/ask", json={"input": "q"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code in (401, 404), r.text


@needs_database
def test_the_doors_refuse_a_parameter_or_tool_name_with_a_newline_before_calling(client, admin, project, stub):  # noqa: F811
    engine_component(stub, project["pid"])
    stub.route("POST", "/chat", (200, {"answer": "ok"}))
    stub.route("POST", "/v1/chat/completions", (200, {"choices": [{"index": 0, "finish_reason": "stop",
                                                                   "message": {"role": "assistant", "content": "ok"}}]}))
    assert client.put(f"/projects/{project['slug']}/connections/chat", json=rest(stub),
                      headers=admin).status_code == 200
    assert client.put(f"/projects/{project['slug']}/connections/agent", headers=admin, json={
        "label": "Agent", "kind": "openai", "base_url": stub.base + "/v1", "model": "gpt", "timeout_s": 5,
        "secret": new_secret(), "supports_tools": True}).status_code == 200
    token = {"X-AISC-Service-Token": CONNECTIONS_TOKEN}
    keys = {n: client.post(f"/internal/projects/{project['pid']}/connections/{n}/run-keys", headers=token).json()["key"]
            for n in ("chat", "agent")}
    before = len(stub.seen)
    r = client.post(f"/internal/facade/{project['pid']}/chat/aisc/ask", json={"input": "q", "params": {"lang\n": "en"}},
                    headers={"Authorization": f"Bearer {keys['chat']}"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "params: 'lang\\n' is not a parameter name"
    tools = [{"type": "function", "function": {"name": "get_balance\n"}}]
    r = client.post(f"/internal/facade/{project['pid']}/agent/aisc/ask", json={"input": "q", "params": {"tools": tools}},
                    headers={"Authorization": f"Bearer {keys['agent']}"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == TOOLS_MESSAGE
    r = client.post(f"/internal/facade/{project['pid']}/agent/openai/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "q"}], "tools": tools},
                    headers={"Authorization": f"Bearer {keys['agent']}"})
    assert r.status_code == 400, r.text
    assert TOOLS_MESSAGE in r.text
    assert len(stub.seen) == before
