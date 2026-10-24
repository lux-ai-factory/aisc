"""The engine's events, in the shapes it sends them (apps/backend/aisc_backend/ledger.py, signals/ledger.py,
routers/plugin.py), are accepted by the relay against the REAL registry. The engine posts them to the
internal route with its own token, each citing the witnessed request of its route; the worker's citing the
run its evaluation started."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all

pytestmark = needs_db
TOKEN = "engine-token-0123456789"
P, C, S, PL = (str(uuid.uuid4()) for _ in range(4))


@pytest.fixture(autouse=True)
def _enforce(mode, monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", TOKEN)


def send(client, project, request_id, action, item_type, item_id, **over):
    event = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
             "item_id": item_id, "details": {}, **over}
    r = client.post(f"/internal/projects/{project['pid']}/ledger/events", json=event,
                    headers={"X-AISC-Service-Token": TOKEN})
    assert r.status_code == 202, r.text


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


CASES = [
    ("POST", f"/api/v1/projects/for-platform/{P}", "engine.project.created", "engine_project", P, {}),
    ("POST", "/api/v1/projects", "engine.project.created", "engine_project", P, {}),
    ("PATCH", f"/api/v1/projects/{P}", "engine.project.updated", "engine_project", P,
     {"details": {"changed": ["name"]}}),
    ("POST", f"/api/v1/projects/{P}/models", "engine.component.created", "component", C,
     {"details": {"component_type": "model"}}),
    ("PATCH", f"/api/v1/components/{C}", "engine.component.updated", "component", C,
     {"details": {"changed": ["name"]}}),
    ("PUT", f"/api/v1/components/{C}/data", "engine.component.file_uploaded", "component", C,
     {"details": {"size": 2048}}),
    ("DELETE", f"/api/v1/components/{C}", "engine.component.deleted", "component", C,
     {"details": {"component_type": "model"}}),
    ("POST", f"/api/v1/project/settings/{P}", "engine.setting.created", "setting", S, {"details": {"key": "TEMP"}}),
    ("PATCH", f"/api/v1/project/settings/{P}/{S}", "engine.setting.updated", "setting", S,
     {"details": {"key": "TEMP", "changed": ["value"]}}),
    ("DELETE", f"/api/v1/project/settings/{P}/{S}", "engine.setting.deleted", "setting", S, {"details": {"key": "TEMP"}}),
    ("POST", f"/api/v1/project/settings/{P}", "engine.secret.created", "secret", S, {"details": {"key": "API_KEY"}}),
    ("PATCH", f"/api/v1/project/settings/{P}/{S}", "engine.secret.updated", "secret", S,
     {"details": {"key": "API_KEY", "changed": ["value"]}}),
    ("DELETE", f"/api/v1/project/settings/{P}/{S}", "engine.secret.deleted", "secret", S, {"details": {"key": "API_KEY"}}),
    ("POST", "/api/v1/plugins", "plugin.installed", "plugin", "langbite",
     {"details": {"package": "langbite", "version": "0.2.8", "reused": False}}),
    ("POST", "/api/v1/plugins/refresh", "plugin.refreshed", "plugin", "langbite",
     {"details": {"package": "langbite", "version": "0.2.9"}}),
    ("DELETE", "/api/v1/plugins", "plugin.removed", "plugin", "langbite",
     {"details": {"package": "langbite", "version": "0.2.9"}}),
    ("PATCH", f"/api/v1/plugins/{PL}/enabled", "engine.plugin.toggled", "plugin", PL, {"details": {"enabled": False}}),
]


@pytest.mark.parametrize("method, path, action, item_type, item_id, over", CASES,
                         ids=[f"{c[2]}@{c[0]} {c[1].split('/api/v1')[1]}" for c in CASES])
def test_an_event_as_the_engine_sends_it_is_accepted(client, project, memory_ledger, witnessed, method, path, action,
                                                     item_type, item_id, over):
    request_id = witnessed(MEMBER, method, "engine", path, project_header=project["pid"])
    send(client, project, request_id, action, item_type, item_id, **over)
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == action]
    assert (e.source_app, e.item_id) == ("engine", item_id)


def test_a_plugins_status_in_a_run_is_accepted_as_the_runs(client, project, memory_ledger, witnessed):
    run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    send(client, project, request_id, "engine.evaluation.run_requested", "evaluation", run, run_id=run,
         details={"plugins": 1})
    send(client, project, request_id, "engine.evaluation.plugin_status_changed", "evaluation", run, run_id=run,
         details={"plugin": PL, "status_before": "Running", "status_after": "Completed"})
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert [e.action for e in entries(memory_ledger, log_of(project["pid"])) if e.item_id == run] == [
        "engine.evaluation.run_requested", "engine.evaluation.plugin_status_changed"]


def test_a_run_marked_local_is_accepted_as_the_runs(client, project, memory_ledger, witnessed):
    run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    send(client, project, request_id, "engine.evaluation.run_requested", "evaluation", run, run_id=run,
         details={"plugins": ["DemoPlugin"]})
    send(client, project, request_id, "engine.evaluation.input_marked_local", "evaluation", run, run_id=run,
         details={"input": "model", "file": "model.onnx", "sha256": "ab" * 32})
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert [e.action for e in entries(memory_ledger, log_of(project["pid"])) if e.item_id == run] == [
        "engine.evaluation.run_requested", "engine.evaluation.input_marked_local"]


def test_a_run_local_from_its_creation_is_accepted_with_its_files(client, project, memory_ledger, witnessed):
    run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    send(client, project, request_id, "engine.evaluation.run_requested", "evaluation", run, run_id=run,
         details={"plugins": ["DemoPlugin"],
                  "local_models": [{"plugin": "DemoPlugin", "input": "model", "file": "model.onnx"}]})
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
