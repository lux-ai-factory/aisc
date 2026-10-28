"""Calling an adapter: what it is given, how its answer, refusal or failure comes back, the secrets taken out,
the calls it takes at once, and the network opener it reaches its system with."""
from __future__ import annotations

import json
import time

import pytest
from aisc_plugin_interface import connections as client

from platform_service import adapters
from tests.http_stub import Stub

CONNECTION = {"name": "example", "label": "Example", "base_url": "https://chat.example.org", "timeout_s": 5,
              "settings": {"assistant": "a1"}, "secrets": {"token": "s3cr3t-value"}}


class Failure(Exception):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        if status is not None:
            self.status = status


def adapter_calling(func, max_concurrent=None, name="example-chat"):
    return adapters.Adapter(name=name, label="Example chat site", fields=(), capabilities=("text", "history"),
                            call=func, max_concurrent=max_concurrent)


def ask(adapter, input="hi", history=None, seconds=5.0):
    return adapters.call(adapter, CONNECTION, input, history or [], {}, deadline=time.monotonic() + seconds)


def test_a_text_and_a_json_answer_come_back_as_answers():
    answer = ask(adapter_calling(lambda *a: "hello"))
    assert (answer.text, answer.refused) == ("hello", False)
    assert isinstance(answer.latency_ms, int)
    assert ask(adapter_calling(lambda *a: {"score": 0.4})).text == {"score": 0.4}


def test_the_adapter_gets_the_connection_input_history_params_and_an_opener():
    seen = {}

    def record(connection, input, history, params, open):
        seen.update(connection=connection, input=input, history=history, params=params, open=open)
        return "ok"

    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    ask(adapter_calling(record), input="and now?", history=history)
    assert seen["connection"] == CONNECTION
    assert (seen["input"], seen["history"], seen["params"]) == ("and now?", history, {})
    assert callable(seen["open"])


def test_a_refusal_is_an_answer_with_its_reason():
    def refuse(*a):
        raise Failure("refused", "out of scope")

    answer = ask(adapter_calling(refuse))
    assert (answer.refused, answer.refusal_reason, answer.text) == (True, "out of scope", None)


@pytest.mark.parametrize("raised,expected", [
    (Failure("auth", "bad token"), client.EndpointAuthError),
    (Failure("not_found", "gone"), client.EndpointNotFound),
    (Failure("timeout", "slow"), client.EndpointTimeout),
    (Failure("bad_response", "garbled"), client.EndpointBadResponse),
    (Failure("weird", "what"), client.EndpointError),
    (ValueError("plain"), client.EndpointError),
])
def test_failure_codes_map_to_the_interface_errors(raised, expected):
    def fail(*a):
        raise raised

    with pytest.raises(client.EndpointError) as caught:
        ask(adapter_calling(fail))
    assert type(caught.value) is expected
    assert str(caught.value).startswith("Example: ")


def test_a_failure_keeps_the_systems_status():
    def fail(*a):
        raise Failure("bad_response", "unavailable", status=503)

    with pytest.raises(client.EndpointBadResponse) as caught:
        ask(adapter_calling(fail))
    assert caught.value.status == 503


def test_secrets_are_scrubbed_from_answers_and_failures():
    assert ask(adapter_calling(lambda *a: "x s3cr3t-value")).text == "x ***"

    def leak(*a):
        raise Failure("auth", "token s3cr3t-value refused")

    with pytest.raises(client.EndpointAuthError) as caught:
        ask(adapter_calling(leak))
    assert "s3cr3t-value" not in str(caught.value) and "***" in str(caught.value)


def test_each_adapter_has_one_limiter_of_its_size():
    limited = adapter_calling(lambda *a: "x", max_concurrent=2, name="two-at-a-time")
    assert adapters.limiter(limited) is adapters.limiter(limited)
    assert adapters.limiter(limited).total_tokens == 2
    assert adapters.limiter(adapter_calling(lambda *a: "x")) is None


def test_the_opener_stops_at_the_deadline_even_without_a_timeout():
    stub = Stub(delay=3.0)
    try:
        stub.route("GET", "/slow", (200, {"ok": True}))
        open = adapters.guarded_open([stub.host], None, deadline=time.monotonic() + 0.5)
        started = time.monotonic()
        with pytest.raises(client.EndpointTimeout):
            open(stub.base + "/slow").read()
        assert time.monotonic() - started < 2.0
        with pytest.raises(client.EndpointTimeout):
            adapters.guarded_open([stub.host], None, deadline=time.monotonic() - 1)(stub.base + "/slow")
    finally:
        stub.stop()


def test_the_opener_refuses_a_private_address():
    with pytest.raises(client.BlockedAddress):
        adapters.guarded_open(allowed_hosts=[], denied_addresses=None)("http://127.0.0.1:9/")


def test_the_opener_reaches_an_allowed_host():
    stub = Stub()
    try:
        stub.route("GET", "/x", (200, {"ok": True}))
        with adapters.guarded_open([stub.host], None)(stub.base + "/x") as resp:
            assert json.loads(resp.read()) == {"ok": True}
    finally:
        stub.stop()
