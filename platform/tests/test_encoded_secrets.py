"""Every place a secret is scrubbed takes the same forms of it: as it is, base64 (standard and URL-safe) and
URL-encoded. A system's error text (the doors' 502 detail, the warning log, the Test button and its
capability checks, the stored last test) loses each form of the key and of every secret header value, and an
encoded value across the client's 300-character cut leaves no part behind. The Test button's own successful
answer and refusal are scrubbed the same way before they are returned or stored. Runs on the throwaway; the
system under test is a local stub."""
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
    """A key whose encoded forms all differ from itself."""
    return new_secret() + "/+=&"


def _token() -> str:
    return "tok/" + uuid.uuid4().hex + "+=&"


def b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


FORMS = {
    "as-is": lambda v: v,
    "base64": b64,
    "url-safe-base64": lambda v: base64.urlsafe_b64encode(v.encode()).decode(),
    "url-encoded": lambda v: urllib.parse.quote(v, safe=""),
}


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


def press_test(client, admin, project, name):
    return client.post(f"/projects/{project['slug']}/connections/{name}/test", json={}, headers=admin)


def stored(client, admin, project, name) -> dict:
    r = client.get(f"/projects/{project['slug']}/connections", headers=admin)
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["connections"] if c["name"] == name)


def assert_no_form(text, encode, form, **secrets):
    leaked = [what for what, value in secrets.items() if encode(value) in text]
    assert not leaked, f"{form} form of {leaked} answered back in {text[-300:]!r}"


def eight_character_runs(value: str) -> list[str]:
    return [value[i:i + 8] for i in range(len(value) - 7)]


def assert_no_part_of(text, value):
    parts = [p for p in eight_character_runs(value) if p in text]
    assert not parts, f"part of a secret answered back: {parts[:3]} in {text[-80:]!r}"


def failing_with(encode):
    """A system that answers 422 with the credentials it was sent, in one encoding."""
    def answer(seen):
        key = (seen.header("authorization") or "").removeprefix("Bearer ")
        token = seen.header("x-token") or ""
        return Canned(422, f"bad key {encode(key)} token {encode(token)} here".encode())
    return answer


# error texts

@pytest.mark.parametrize("form", sorted(FORMS))
def test_the_aisc_door_and_its_warning_log_hold_no_form_of_an_echoed_credential(
        client, admin, project, stub, caplog, form):  # noqa: F811
    key, token, encode = _key(), _token(), FORMS[form]
    stub.route("POST", "/echo", failing_with(encode))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    with caplog.at_level(logging.WARNING):
        r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"},
                        headers=bearer(run_key(client, project, name)))
    assert r.status_code == 502, r.text
    assert_no_form(r.text, encode, form, key=key, token=token)
    assert r.json()["detail"].endswith("bad key *** token *** here"), r.json()["detail"]
    assert caplog.messages, "the failure is logged"
    for message in caplog.messages:
        assert_no_form(message, encode, form, key=key, token=token)


@pytest.mark.parametrize("form", sorted(FORMS))
def test_the_openai_door_answers_no_form_of_an_echoed_credential(client, admin, project, stub, form):  # noqa: F811
    key, token, encode = _key(), _token(), FORMS[form]
    stub.route("POST", "/echo", failing_with(encode))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    r = client.post(f"{door(project, name)}/openai/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "q"}]}, headers=bearer(run_key(client, project, name)))
    assert r.status_code == 502, r.text
    assert_no_form(r.text, encode, form, key=key, token=token)


@pytest.mark.parametrize("form", sorted(FORMS))
def test_the_test_button_answers_and_stores_no_form_of_an_echoed_credential(
        client, admin, project, stub, form):  # noqa: F811
    key, token, encode = _key(), _token(), FORMS[form]
    stub.route("POST", "/echo", failing_with(encode))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    t = press_test(client, admin, project, name)
    assert t.status_code == 200, t.text
    assert t.json()["ok"] is False
    assert_no_form(t.text, encode, form, key=key, token=token)
    detail = stored(client, admin, project, name)["last_test_detail"]
    assert_no_form(detail, encode, form, key=key, token=token)
    assert "bad key *** token *** here" in detail, detail


TOOLS_PROBE_ROUTE = "/v1/chat/completions"


@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_failed_capability_check_holds_no_form_of_an_echoed_credential(client, admin, project, stub, form):  # noqa: F811
    """The Test button's tools check fails with the system's error text: it is scrubbed like the rest."""
    key, token, encode = _key(), _token(), FORMS[form]
    refuse_tools = failing_with(encode)

    def answer(seen):
        if (seen.json or {}).get("tools"):
            return refuse_tools(seen)
        return Canned(200, json.dumps({"choices": [{"index": 0, "finish_reason": "stop",
                                                    "message": {"role": "assistant", "content": "pong"}}]}).encode())
    stub.route("POST", TOOLS_PROBE_ROUTE, answer)
    name = put(client, admin, project, stub, "agent", {
        "label": "Agent", "kind": "openai", "base_url": stub.base + "/v1", "model": "gpt", "timeout_s": 5,
        "secret": key, "secret_headers": {"X-Token": token}, "supports_tools": True})
    t = press_test(client, admin, project, name)
    assert t.status_code == 200, t.text
    assert t.json()["ok"] is False and t.json()["error"] == "capability_missing", t.text
    assert_no_form(t.text, encode, form, key=key, token=token)
    assert_no_form(stored(client, admin, project, name)["last_test_detail"], encode, form, key=key, token=token)


@pytest.mark.parametrize("filler", [240, 260, 280])
def test_a_base64_secret_header_value_across_the_cut_leaves_no_part_on_the_door_or_the_test_button(
        client, admin, project, stub, caplog, filler):  # noqa: F811
    key = new_secret()
    token = "tok-" + uuid.uuid4().hex + uuid.uuid4().hex
    stub.route("POST", "/echo", (422, b"A" * filler + b64(token).encode()))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    with caplog.at_level(logging.WARNING):
        r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "q"},
                        headers=bearer(run_key(client, project, name)))
    assert r.status_code == 502, r.text
    assert_no_part_of(r.text, b64(token))
    for message in caplog.messages:
        assert_no_part_of(message, b64(token))
    t = press_test(client, admin, project, name)
    assert_no_part_of(t.text, b64(token))
    assert_no_part_of(stored(client, admin, project, name)["last_test_detail"], b64(token))


# the Test button's own answer and refusal

def test_the_test_buttons_text_answer_is_scrubbed_before_it_is_returned_or_stored(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", lambda seen: Canned(200, json.dumps(
        {"answer": f"you sent {seen.header('authorization')} and {seen.header('x-token')}."}).encode()))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    t = press_test(client, admin, project, name)
    assert t.status_code == 200, t.text
    assert t.json()["ok"] is True and t.json()["answer"] == "you sent Bearer *** and ***."
    assert stored(client, admin, project, name)["last_test_detail"] == "you sent Bearer *** and ***."


def test_the_test_buttons_structured_answer_loses_every_form(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()

    def echo(seen):
        sent_key = (seen.header("authorization") or "").removeprefix("Bearer ")
        sent_token = seen.header("x-token") or ""
        return Canned(200, json.dumps({"answer": {
            form: [encode(sent_key), encode(sent_token)] for form, encode in FORMS.items()}}).encode())
    stub.route("POST", "/echo", echo)
    name = put(client, admin, project, stub, "echo", rest(stub, key, token))
    t = press_test(client, admin, project, name)
    assert t.status_code == 200, t.text
    assert t.json()["answer"] == {form: ["***", "***"] for form in FORMS}
    detail = stored(client, admin, project, name)["last_test_detail"]
    for form, encode in FORMS.items():
        assert_no_form(t.text, encode, form, key=key, token=token)
        assert_no_form(detail, encode, form, key=key, token=token)


def test_the_test_buttons_refusal_is_scrubbed_before_it_is_returned_or_stored(client, admin, project, stub):  # noqa: F811
    key, token = _key(), _token()
    stub.route("POST", "/echo", lambda seen: Canned(451, json.dumps(
        {"why": f"{seen.header('authorization')} {b64(seen.header('x-token') or '')}"}).encode()))
    name = put(client, admin, project, stub, "echo", rest(stub, key, token, refusal={"status": [451], "path": "why"}))
    t = press_test(client, admin, project, name)
    assert t.status_code == 200, t.text
    assert t.json()["refused"] is True and t.json()["refusal_reason"] == "Bearer *** ***", t.text
    detail = stored(client, admin, project, name)["last_test_detail"]
    assert detail == "refused: Bearer *** ***", detail


def test_a_test_answer_without_credentials_is_returned_and_stored_as_it_is(client, admin, project, stub):  # noqa: F811
    stub.route("POST", "/echo", (200, {"answer": "Up to 5,000 EUR, ***x."}))
    name = put(client, admin, project, stub, "echo", rest(stub, _key(), _token()))
    t = press_test(client, admin, project, name)
    assert t.status_code == 200, t.text
    assert t.json()["answer"] == "Up to 5,000 EUR, ***x."
    assert stored(client, admin, project, name)["last_test_detail"] == "Up to 5,000 EUR, ***x."
