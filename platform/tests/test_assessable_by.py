"""Which installed tests can assess each target, for the target page.

A test can assess a target of the AI card when its target kinds include `card`; one that calls its
target (it needs a connection) only when the target has one. The connection's protocol does not
narrow it: the facade translates a REST, OpenAI-compatible, A2A or OIP connection to the text a
tool speaks. The engine says what each installed test declares (GET /api/v1/plugins/declarations),
asked with the caller's own token."""
from __future__ import annotations

import pytest

from platform_service import target_store, targets
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, EngineFake, new_secret
from tests.http_stub import Stub

ALICE = "00000000-0000-0000-0000-00000000a11c"
K1 = "0b9c7a1e-0000-4000-8000-000000000001"


def plugin(name, kinds=("card",), needs_connection=True, protocols=("openai",)):
    return {"pid": "p-" + name, "name": name, "display_name": name.title(), "package_name": "aisc-" + name,
            "version": "1.0.0", "target_kinds": list(kinds), "card_protocols": list(protocols),
            "card_needs_connection": needs_connection}


CONNECTED = {"key": "system", "endpoint": {"name": "chat", "label": "Chat", "kind": "rest"}}
UNCONNECTED = {"key": f"component:{K1}", "endpoint": None}


# who can assess what

def test_a_test_that_calls_its_target_assesses_only_a_connected_one():
    out = targets.assessable_by([CONNECTED, UNCONNECTED], [plugin("probe")])
    assert out == {"system": ["Probe"], f"component:{K1}": []}


def test_a_test_that_reads_its_inputs_assesses_any_target_connected_or_not():
    out = targets.assessable_by([CONNECTED, UNCONNECTED], [plugin("survey", needs_connection=False, protocols=())])
    assert out == {"system": ["Survey"], f"component:{K1}": ["Survey"]}


def test_a_local_model_test_or_one_that_declares_nothing_assesses_no_card_target():
    out = targets.assessable_by([CONNECTED, UNCONNECTED], [plugin("onnx", kinds=("local_model",), needs_connection=False),
                                                          plugin("plain", kinds=(), needs_connection=False)])
    assert out == {"system": [], f"component:{K1}": []}


def test_a_test_of_both_kinds_counts_as_a_card_test():
    out = targets.assessable_by([CONNECTED, UNCONNECTED], [plugin("both", kinds=("card", "local_model"))])
    assert out == {"system": ["Both"], f"component:{K1}": []}


@pytest.mark.parametrize("kind", ["rest", "openai", "a2a", "oip"])
def test_any_protocol_serves_a_text_tool_through_the_facade(kind):
    target = {"key": "system", "endpoint": {"name": "x", "label": "X", "kind": kind}}
    assert targets.assessable_by([target], [plugin("probe", protocols=("openai",))]) == {"system": ["Probe"]}


# the route

@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture
def _env(monkeypatch, stub):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)


def _connect_system(client, admin, project, stub):
    r = client.put(f"/projects/{project['slug']}/connections/chat", headers=admin, json={
        "label": "Chat", "kind": "rest", "base_url": stub.base, "path": "/chat", "target": "system",
        "body_template": {"q": "{{input}}"}, "response_path": "answer", "timeout_s": 5, "secret": new_secret()})
    assert r.status_code == 200, r.text


@needs_database
def test_the_route_answers_per_target_from_the_engines_declarations(client, as_user, admin, make_project, stub, _env):
    project = make_project()
    target_store.upsert_component(project["pid"], f"component:{K1}", "Scoring model", "model", 1)
    EngineFake(stub, project["pid"])                    # binding a connection renames the mirrors
    _connect_system(client, admin, project, stub)
    stub.route("GET", "/api/v1/plugins/declarations",
               (200, [plugin("probe"), plugin("survey", needs_connection=False, protocols=())]))
    alice = as_user(ALICE)
    r = client.get(f"/projects/{project['slug']}/targets/assessable-by", headers=alice)
    assert r.status_code == 200, r.text
    assert r.json() == {"assessable_by": {"system": ["Probe", "Survey"], f"component:{K1}": ["Survey"]},
                        "reason": None}
    call = stub.requests("GET", "/api/v1/plugins/declarations")[-1]
    assert call["headers"]["authorization"] == alice["Authorization"]
    assert call["headers"]["x-aisc-project"] == str(project["pid"])


@needs_database
def test_an_engine_that_does_not_answer_lists_no_tests_and_says_why(client, as_user, make_project, stub, _env):
    project = make_project()
    stub.route("GET", "/api/v1/plugins/declarations", (503, {"detail": "down"}))
    r = client.get(f"/projects/{project['slug']}/targets/assessable-by", headers=as_user(ALICE))
    assert r.status_code == 200, r.text
    assert r.json()["assessable_by"] == {"system": []}
    assert r.json()["reason"] == "the installed tests could not be read: try again later"


@needs_database
def test_a_stranger_gets_404(client, as_user, make_project, stub, _env):
    project = make_project()
    r = client.get(f"/projects/{project['slug']}/targets/assessable-by",
                   headers=as_user("00000000-0000-0000-0000-000000000e0e"))
    assert r.status_code == 404
