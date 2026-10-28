"""Calls to a connection of an adapter's kind: the protocol doors and the Test button reach the system through
the adapter, the run key advertises the adapter's capabilities, and a connection whose adapter is gone fails
its calls but stays listed."""
from __future__ import annotations

import os
import shutil
import textwrap
import threading
import time
from pathlib import Path

import pytest

from platform_service import adapters
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, engine_component
from tests.http_stub import Stub

pytestmark = needs_database

# reaches the stand-in system at {base_url}/turn with the token and the whole conversation
EXAMPLE = '''
import json
import urllib.error
import urllib.request

PROTOCOL = {
    "name": "example-chat",
    "label": "Example chat site",
    "fields": [{"name": "token", "label": "Token", "secret": True, "required": True}],
    "capabilities": CAPABILITIES,
}


class Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def call(connection, input, history, params, open):
    body = {"token": connection["secrets"]["token"], "messages": history + [{"role": "user", "content": input}]}
    request = urllib.request.Request(connection["base_url"] + "/turn", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with open(request, timeout=connection["timeout_s"]) as resp:
            return json.loads(resp.read())["answer"]
    except urllib.error.HTTPError as exc:
        if exc.code == 451:
            raise Failure("refused", "not something I answer") from None
        raise Failure("bad_response", f"the site answered {exc.code}") from None
'''
TOKEN = "tok-example-123"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


def write_example(root: Path, capabilities='["text", "history"]') -> Path:
    folder = root / "example"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "adapter.py").write_text(textwrap.dedent(EXAMPLE).replace("CAPABILITIES", capabilities))
    return folder


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub, tmp_path):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)
    monkeypatch.setenv("PLATFORM_INTERNAL_URL", "http://platform:8000")
    write_example(tmp_path / "adapters")
    monkeypatch.setenv("PLATFORM_ADAPTERS_DIR", str(tmp_path / "adapters"))
    adapters.reset()
    yield
    adapters.reset()


def connection(client, admin, project, stub, name="example"):
    engine_component(stub, project["pid"])
    body = {"label": "Example", "kind": "example-chat", "base_url": stub.base, "timeout_s": 5,
            "secret_settings": {"token": TOKEN}}
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return name


def issue(client, project, name):
    r = client.post(f"/internal/projects/{project['pid']}/connections/{name}/run-keys",
                    headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 201, r.text
    return r.json()


def keyed(key):
    return {"Authorization": f"Bearer {key}"}


def door(project, name):
    return f"/internal/facade/{project['pid']}/{name}"


HISTORY = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]


def test_aisc_ask_reaches_the_system_through_the_adapter(client, admin, project, stub):
    stub.route("POST", "/turn", (200, {"answer": "hi there"}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name)["key"]
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "and you?", "history": HISTORY}, headers=keyed(key))
    assert r.status_code == 200, r.text
    assert r.json()["output"] == "hi there" and r.json()["refused"] is False
    sent = stub.requests("POST", "/turn")[-1]["json"]
    assert sent == {"token": TOKEN, "messages": HISTORY + [{"role": "user", "content": "and you?"}]}


def test_the_openai_door_reaches_the_system_through_the_adapter(client, admin, project, stub):
    stub.route("POST", "/turn", (200, {"answer": "hi there"}))
    name = connection(client, admin, project, stub)
    key = issue(client, project, name)["key"]
    r = client.post(f"{door(project, name)}/openai/v1/chat/completions", headers=keyed(key),
                    json={"model": name, "messages": HISTORY + [{"role": "user", "content": "and you?"}]})
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "hi there"


def test_a_refusal_and_a_failure_through_the_adapter(client, admin, project, stub):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name)["key"]
    stub.route("POST", "/turn", (451, {"detail": "no"}))
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "x"}, headers=keyed(key))
    assert r.status_code == 200 and r.json()["refused"] is True, r.text
    assert r.json()["refusal_reason"] == "not something I answer"
    stub.route("POST", "/turn", (500, {"detail": f"crashed, {TOKEN}"}))
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "x"}, headers=keyed(key))
    assert r.status_code == 502 and r.json()["error"] == "bad_response", r.text
    assert TOKEN not in r.text


def test_the_run_key_advertises_the_adapters_capabilities(client, admin, project, stub, tmp_path):
    write_example(tmp_path / "adapters", capabilities='["text"]')
    adapters.reset()
    stub.route("POST", "/turn", (200, {"answer": "hi there"}))
    name = connection(client, admin, project, stub)
    issued = issue(client, project, name)
    assert issued["capabilities"] == ["text"]
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "x", "history": HISTORY},
                    headers=keyed(issued["key"]))
    assert r.status_code == 400 and "history" in r.text, r.text
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "x"}, headers=keyed(issued["key"]))
    assert r.status_code == 200, r.text


def test_the_test_button_calls_through_the_adapter(client, admin, project, stub):
    stub.route("POST", "/turn", (200, {"answer": "hi there"}))
    name = connection(client, admin, project, stub)
    r = client.post(f"/projects/{project['slug']}/connections/{name}/test", json={"input": "ping"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["answer"] == "hi there"


def test_a_connection_whose_adapter_is_gone_fails_its_calls_and_stays_listed(client, admin, project, stub, tmp_path):
    name = connection(client, admin, project, stub)
    key = issue(client, project, name)["key"]
    shutil.rmtree(tmp_path / "adapters" / "example")
    adapters.reset()
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "x"}, headers=keyed(key))
    assert r.status_code == 502, r.text
    assert "the example-chat adapter is not installed" in r.json()["detail"]
    r = client.post(f"/projects/{project['slug']}/connections/{name}/test", json={"input": "ping"}, headers=admin)
    assert r.status_code == 200 and r.json()["ok"] is False, r.text
    listed = client.get(f"/projects/{project['slug']}/connections", headers=admin).json()["connections"]
    assert [c["name"] for c in listed] == [name]
    assert client.delete(f"/projects/{project['slug']}/connections/{name}", headers=admin).status_code == 204


# an adapter that computes without ever calling open (nothing on the network to time out), and one that
# lets one call at a time through and holds it until the test releases it
STUCK = '''
import time

PROTOCOL = {"name": "stuck-chat", "label": "Stuck", "fields": [], "capabilities": ["text"]}

def call(connection, input, history, params, open):
    time.sleep(6)
    return "too late"
'''
GATED = '''
import threading

PROTOCOL = {"name": "gated-chat", "label": "Gated", "fields": [], "capabilities": ["text"], "max_concurrent": 1}
STARTED, RELEASE = threading.Event(), threading.Event()

def call(connection, input, history, params, open):
    STARTED.set()
    RELEASE.wait(20)
    return "released"
'''


def install(tmp_path, folder, source):
    path = tmp_path / "adapters" / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter.py").write_text(textwrap.dedent(source))
    adapters.reset()


def plain_connection(client, admin, project, stub, name, kind):
    engine_component(stub, project["pid"])
    body = {"label": name, "kind": kind, "base_url": stub.base, "timeout_s": 1}
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return name


def test_a_stuck_adapter_is_answered_with_a_timeout_in_time(client, admin, project, stub, tmp_path, monkeypatch):
    from aisc_plugin_interface import connections as interface
    install(tmp_path, "stuck", STUCK)
    monkeypatch.setattr(interface, "facade_timeout_s", lambda descriptor: 1)
    name = plain_connection(client, admin, project, stub, "stuck", "stuck-chat")
    key = issue(client, project, name)["key"]
    started = time.monotonic()
    r = client.post(f"{door(project, name)}/aisc/ask", json={"input": "x"}, headers=keyed(key))
    assert time.monotonic() - started < 4
    assert r.status_code == 502 and r.json()["error"] == "timeout", r.text


def test_waiting_for_an_adapters_slot_holds_no_thread(client, admin, project, stub, tmp_path, monkeypatch):
    from platform_service.routes import facade
    monkeypatch.setenv("PLATFORM_FACADE_THREADS", "2")
    monkeypatch.setattr(facade, "_FACADE_LIMITER", None, raising=False)
    monkeypatch.setattr(facade, "_RUN_LIMITERS", {})
    install(tmp_path, "gated", GATED)
    gate = adapters.get("gated-chat").call.__globals__
    stub.route("POST", "/turn", (200, {"answer": "hi there"}))
    gated = plain_connection(client, admin, project, stub, "gated", "gated-chat")
    other = connection(client, admin, project, stub, name="other")
    gated_key, other_key = issue(client, project, gated)["key"], issue(client, project, other)["key"]
    answers = []
    with client as shared:
        def ask_gated():
            answers.append(shared.post(f"{door(project, gated)}/aisc/ask", json={"input": "x"}, headers=keyed(gated_key)))
        first = threading.Thread(target=ask_gated)
        first.start()
        assert gate["STARTED"].wait(10)
        queued = [threading.Thread(target=ask_gated) for _ in range(3)]
        for t in queued:
            t.start()
        time.sleep(0.5)
        try:
            started = time.monotonic()
            r = shared.post(f"{door(project, other)}/aisc/ask", json={"input": "x"}, headers=keyed(other_key))
            assert r.status_code == 200 and r.json()["output"] == "hi there", r.text
            assert time.monotonic() - started < 5, "the other connection waited behind the queued adapter calls"
        finally:
            gate["RELEASE"].set()
            for t in [first, *queued]:
                t.join(30)
    assert [a.status_code for a in answers] == [200] * 4


@pytest.mark.skipif(not os.environ.get("AISC_ADAPTER_E2E_DIR"), reason="AISC_ADAPTER_E2E_DIR names a real adapters folder")
def test_a_real_adapter_folder_end_to_end(client, admin, project, stub, monkeypatch):
    """A real adapter folder (AISC_ADAPTER_E2E_DIR) against the stand-in: AISC_ADAPTER_E2E_KIND is its kind,
    AISC_ADAPTER_E2E_ROUTE the path its system answers on, AISC_ADAPTER_E2E_BODY_FILE the raw answer, and
    AISC_ADAPTER_E2E_EXPECT the text the adapter must make of it, AISC_ADAPTER_E2E_SETTINGS (JSON, optional) its
    plain fields."""
    import json

    monkeypatch.setenv("PLATFORM_ADAPTERS_DIR", os.environ["AISC_ADAPTER_E2E_DIR"])
    adapters.reset()
    kind = os.environ["AISC_ADAPTER_E2E_KIND"]
    adapter = adapters.get(kind)
    assert adapter is not None, f"no {kind} adapter in {os.environ['AISC_ADAPTER_E2E_DIR']}"
    stub.route("POST", os.environ["AISC_ADAPTER_E2E_ROUTE"],
               (200, Path(os.environ["AISC_ADAPTER_E2E_BODY_FILE"]).read_bytes()))
    engine_component(stub, project["pid"])
    secrets = {f.name: "e2e-secret" for f in adapter.fields if f.secret}
    body = {"label": "End to end", "kind": kind, "base_url": stub.base, "timeout_s": 10,
            "settings": json.loads(os.environ.get("AISC_ADAPTER_E2E_SETTINGS") or "{}"), "secret_settings": secrets}
    assert client.put(f"/projects/{project['slug']}/connections/e2e", json=body, headers=admin).status_code == 200
    key = issue(client, project, "e2e")["key"]
    r = client.post(f"{door(project, 'e2e')}/aisc/ask", json={"input": "Hallo", "history": HISTORY}, headers=keyed(key))
    assert r.status_code == 200, r.text
    assert r.json()["output"] == os.environ["AISC_ADAPTER_E2E_EXPECT"]
