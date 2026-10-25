"""The protocol doors' pure translations (connection_facade): the parameters a request may carry, the
error answers, the scrubbing of keys from error text, the capabilities a connection advertises and the
OpenAI door's mapping of messages, tools and tool calls. No database, no network."""
from __future__ import annotations

import json

import pytest

from platform_service import connection_facade as facade

OPENAI_LIST = ("temperature, top_p, max_tokens, max_completion_tokens, stop, seed, presence_penalty, "
               "frequency_penalty, logit_bias, response_format, user, tools, tool_choice, parallel_tool_calls")
TOOL = {"type": "function", "function": {"name": "get_balance", "parameters": {"type": "object"}}}
TOOLS = [TOOL]
CALL = {"id": "call_1", "type": "function", "function": {"name": "get_balance", "arguments": "{\"iban\": \"LU12\"}"}}
SYSTEM = {"role": "system", "content": "You are a bank agent."}
USER = {"role": "user", "content": "q"}


def interface():
    from aisc_plugin_interface import connections
    return connections


def _not_json_message():
    try:
        json.dumps({"x": object()})
    except TypeError as exc:
        return f"params: not JSON: {str(exc)[:100]}"


def _size_message():
    params = {"lang": "x" * 262_144}
    return f"params: {len(json.dumps(params).encode())} bytes as JSON, more than 262144"


TOOLS_MESSAGE = ("params: tools[0] needs type 'function' and a function with a name (letters, digits, _ and -, "
                 "up to 64)")
CHECK_PARAMS_REFUSALS = [
    ("rest", False, {"x": object()}, _not_json_message()),
    ("rest", False, {"lang": "x" * 262_144}, _size_message()),
    ("rest", False, {f"p{i}": 1 for i in range(65)}, "params: 65 parameters, more than 64"),
    ("rest", False, {"a-b": 1}, "params: 'a-b' is not a parameter name"),
    ("rest", False, {"tools": TOOLS},
     "params: a rest connection does not carry tools; only an OpenAI-compatible one does"),
    ("openai", False, {"tools": TOOLS}, "params: this connection does not carry tools (it carries text, history)"),
    ("openai", True, {"tools": []}, "params: tools is a list of functions"),
    ("openai", True, {"tools": [TOOL] * 129}, "params: 129 tools, more than 128"),
    ("openai", True, {"tools": [{"type": "function", "function": {"name": "bad name"}}]}, TOOLS_MESSAGE),
    ("openai", True, {"tools": [{"type": "function", "function": {"name": "f", "parameters": []}}]},
     "params: tools[0].function.parameters is a JSON schema object"),
    ("openai", True, {"tools": TOOLS, "tool_choice": "sometimes"},
     "params: tool_choice is none, auto, required or {type: function, function: {name}}"),
    ("openai", True, {"tools": TOOLS, "parallel_tool_calls": "yes"}, "params: parallel_tool_calls is true or false"),
    ("openai", False, {"stream": True},
     f"params: 'stream' is not a parameter an OpenAI-compatible connection takes ({OPENAI_LIST})"),
]


# check_params
@pytest.mark.parametrize("kind,supports_tools,params,message", CHECK_PARAMS_REFUSALS,
                         ids=["not-json", "size", "count", "name", "tools-on-rest", "tools-without-flag",
                              "tools-empty", "tools-count", "tool-name", "tool-parameters", "tool-choice",
                              "parallel", "unknown-openai"])
def test_check_params_cases(kind, supports_tools, params, message):
    with pytest.raises(facade.BadRequest) as refused:
        facade.check_params(kind, supports_tools, params)
    assert str(refused.value) == message


def test_check_params_returns_a_copy_of_what_passes():
    given = {"lang": "en"}
    out = facade.check_params("rest", False, given)
    assert out == {"lang": "en"} and out is not given
    tools = {"tools": [TOOL], "tool_choice": "auto", "parallel_tool_calls": False}
    assert facade.check_params("openai", True, tools) == tools


# error answers and scrubbing
def test_ask_failure_maps_the_classes():
    c = interface()
    cases = [(getattr(c, name), code) for name, code in facade.ERROR_CODES]
    cases += [(c.EndpointError, "error"), (c.TargetHasNoEndpoint, "error")]
    for cls, code in cases:
        assert facade.ask_failure(cls("L: x KEY", status=409), ["KEY"]) == (
            502, {"error": code, "status": 409, "detail": "L: x ***"}), cls.__name__
    assert facade.ask_failure(c.EndpointError("L: x", status=True), [])[1]["status"] is None
    assert facade.ask_failure(c.BadRequest("history: a list of messages"), []) == (
        400, {"detail": "history: a list of messages"})
    long = "a" * 298 + "KEY" + "b" * 99                    # 400 characters, the key across the cut
    assert facade.ask_failure(c.EndpointError(long), ["KEY"])[1]["detail"] == ("a" * 298 + "***" + "b" * 99)[:300]


def test_the_error_codes_are_the_probes():
    assert facade.ERROR_CODES == (("BlockedAddress", "blocked"), ("EndpointAuthError", "auth"),
                                  ("EndpointNotFound", "not_found"), ("EndpointTimeout", "timeout"),
                                  ("EndpointBadResponse", "bad_response"))
    assert facade.ASK_SHAPE == "{input, history?: [messages], params?: {}}"
    assert facade.MAX_ASK_BYTES == 2_097_152


def test_scrub_replaces_the_longest_value_first():
    assert facade.scrub("ab abc", ["ab", "abc"]) == "*** ***"
    assert facade.scrub("x", ["", None]) == "x"


# capabilities
def test_capabilities():
    assert facade.capabilities("openai", True) == ["text", "history", "tools"]
    assert facade.capabilities("openai", False) == ["text", "history"]
    assert facade.capabilities("rest", True) == ["text", "history"]


# the OpenAI door
def test_openai_to_core_cases():
    assert facade.openai_to_core({"messages": [SYSTEM, USER]}, "openai", False) == ("q", [SYSTEM], {})
    loop = [SYSTEM, {"role": "user", "content": "My balance?"},
            {"role": "assistant", "content": None, "tool_calls": [CALL]},
            {"role": "tool", "tool_call_id": "call_1", "content": "{\"balance\": 10}"}]
    assert facade.openai_to_core({"messages": loop, "tools": TOOLS}, "openai", True) == (None, loop, {"tools": TOOLS})
    kept = facade.openai_to_core({"messages": [USER], "temperature": 0, "n": 1, "model": "x"}, "openai", False)
    assert kept == ("q", [], {"temperature": 0})
    assert facade.openai_to_core({"messages": [USER], "temperature": 0}, "rest", False) == ("q", [], {})


@pytest.mark.parametrize("body,kind,message", [
    ({"stream": True, "messages": [USER]}, "openai", "streaming is not supported; send stream: false"),
    ({"messages": []}, "openai", "messages is required"),
    ({}, "openai", "messages is required"),
    ({"messages": [{"role": "developer", "content": "x"}]}, "openai",
     "messages[0]: role 'developer' is not one of system, user, assistant, tool"),
    ({"messages": [USER, {"role": "assistant", "content": "a"}]}, "openai",
     "the last message must be the user's, or a tool's result"),
    ({"messages": [USER, {"role": "assistant", "content": None, "tool_calls": [CALL]},
                   {"role": "tool", "tool_call_id": "call_1", "content": "x"}]}, "rest",
     "a tool's result can only be sent to an OpenAI-compatible connection"),
    ({"messages": [USER], "tools": TOOLS}, "rest",
     "params: a rest connection does not carry tools; only an OpenAI-compatible one does"),
], ids=["stream", "empty", "absent", "role", "last-assistant", "tool-on-rest", "tools-on-rest"])
def test_openai_to_core_refusals(body, kind, message):
    with pytest.raises(facade.BadRequest) as refused:
        facade.openai_to_core(body, kind, False)
    assert str(refused.value) == message


def test_core_to_openai_cases():
    Answer = interface().Answer
    calls = facade.core_to_openai("m", Answer(None, False, None, 200, 5, tool_calls=[CALL]))["choices"][0]
    assert calls["message"] == {"role": "assistant", "content": None, "refusal": None, "tool_calls": [CALL]}
    assert calls["finish_reason"] == "tool_calls"
    both = facade.core_to_openai("m", Answer("Checking.", False, None, 200, 5, tool_calls=[CALL]))["choices"][0]
    assert both["message"]["content"] == "Checking." and both["message"]["tool_calls"] == [CALL]
    for none in ([], None):
        text = facade.core_to_openai("m", Answer("hi", False, None, 200, 5, tool_calls=none))["choices"][0]
        assert text["message"] == {"role": "assistant", "content": "hi", "refusal": None}
        assert text["finish_reason"] == "stop"
    refused = facade.core_to_openai("m", Answer(None, True, "no clause", 502, 5))["choices"][0]
    assert refused["finish_reason"] == "content_filter" and refused["message"]["refusal"] == "no clause"


def test_ask_answer_has_tool_calls():
    Answer = interface().Answer
    assert facade.ask_answer(Answer("t", False, None, 200, 5)) == {
        "output": "t", "refused": False, "refusal_reason": None, "status": 200, "latency_ms": 5, "tool_calls": None}


def test_the_module_imports_only_the_standard_library_and_the_interface():
    """The integrator's trial gateway loads it by file path, outside the platform."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(facade.__file__).read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            roots.add("." * node.level + (node.module or ""))
    import sys
    outside = {r for r in roots if r != "aisc_plugin_interface" and r not in sys.stdlib_module_names}
    assert outside <= {"__future__"}, outside
