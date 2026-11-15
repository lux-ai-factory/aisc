"""What the ledger keeps of a run, from the engine's events in the shapes the engine will send them: the start
names the card version, each plugin's package, version, configuration and its hash, the connections and the
endpoint each reached, and the stored file and hash of each input; the recorded measures are frozen as
content; a run's rename is an event of its own. Old starts (plugins as a list of names) stay readable next to
new ones."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all

pytestmark = needs_db
TOKEN = "engine-token-0123456789"
CARD_VERSION = str(uuid.uuid4())
PLUGINS = [{"name": "DemoPlugin", "package": "demo-pkg", "version": "0.1.0", "plugin_config_id": 22,
            "config_sha256": "cd" * 32}]
CONNECTIONS = [{"ref": "target:system", "connection": "system-chat", "kind": "rest", "endpoint_sha256": "ab" * 32}]
INPUTS = [{"plugin": "DemoPlugin", "input": "dataset", "component": str(uuid.uuid4()), "file": "rows.csv",
           "sha256": "ef" * 32}]
MEASURES = [{"evaluation_plugin": str(uuid.uuid4()), "name": "Accuracy", "score": 0.9, "uncertainty": 0.0,
             "unit": "N/A", "direction": "", "error": "N/A", "dimensions_sha256": None}]


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
    return event


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


def started(client, project, witnessed, **details):
    run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    send(client, project, request_id, "engine.evaluation.run_requested", "evaluation", run, run_id=run,
         card_version=CARD_VERSION, details={"plugins": PLUGINS, **details})
    return run, request_id


def test_new_run_requested_is_accepted_by_the_relay(client, project, memory_ledger, witnessed):
    run, _ = started(client, project, witnessed, connections=CONNECTIONS, inputs=INPUTS)
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.item_id == run]
    assert e.card_version == CARD_VERSION
    assert e.details == {"plugins": PLUGINS, "connections": CONNECTIONS, "inputs": INPUTS}


def test_old_and_new_run_requested_both_render(client, project, memory_ledger, witnessed, through_gateway):
    old_run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    send(client, project, request_id, "engine.evaluation.run_requested", "evaluation", old_run, run_id=old_run,
         details={"plugins": ["DemoPlugin"]})
    new_run, _ = started(client, project, witnessed, connections=CONNECTIONS)
    relay_all(project["pid"])
    shown = through_gateway(MEMBER, "GET", f"/projects/{project['slug']}/ledger/events")
    assert shown.status_code == 200, shown.text
    plugins = {e["item_id"]: e["details"]["plugins"] for e in shown.json()["events"]
               if e["action"] == "engine.evaluation.run_requested"}
    assert plugins == {old_run: ["DemoPlugin"], new_run: PLUGINS}


def test_recorded_measures_without_their_content_are_refused(client, project, memory_ledger, witnessed):
    run, request_id = started(client, project, witnessed)
    send(client, project, request_id, "engine.measures.recorded", "evaluation", run, run_id=run,
         details={"count": 1})
    relay_all(project["pid"])
    assert "content_required" in " ".join(rejected(memory_ledger, project["pid"]))


def test_the_relay_freezes_measure_content(client, project, memory_ledger, witnessed):
    from platform_service.ledger import secrets

    run, request_id = started(client, project, witnessed)
    send(client, project, request_id, "engine.measures.recorded", "evaluation", run, run_id=run,
         details={"count": 1}, content=MEASURES)
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == "engine.measures.recorded"]
    assert e.content_sha256 == secrets.content_digest(project["pid"], MEASURES)


def test_a_run_rename_is_accepted_with_its_names(client, project, memory_ledger, witnessed):
    run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "PATCH", "engine", f"/api/v1/evaluations/{run}/name",
                           project_header=project["pid"])
    send(client, project, request_id, "engine.evaluation.renamed", "evaluation", run,
         details={"name_before": "", "name_after": "Local back-end, 4 Nov"})
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == "engine.evaluation.renamed"]
    assert e.details == {"name_before": "", "name_after": "Local back-end, 4 Nov"}


def test_a_component_file_upload_names_its_hash(client, project, memory_ledger, witnessed):
    component = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "PUT", "engine", f"/api/v1/components/{component}/data",
                           project_header=project["pid"])
    send(client, project, request_id, "engine.component.file_uploaded", "component", component,
         details={"size": 24, "sha256": "ef" * 32})
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
