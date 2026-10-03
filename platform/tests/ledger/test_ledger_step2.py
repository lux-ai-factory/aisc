"""S4: step 2's events, in the shapes apps/control-objectives' handlers send (api/app.py,
api/library_routes.py, api/ledger_events.py), are accepted by the relay against the REAL registry, each
citing the witnessed request of its route, as control_objectives_rw. The AI mapping is one run, written
in the request that asked for it: requested, each model call, then completed."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
A = "a1b2c3d4e5f6"                                                     # an assessment id (uuid hex[:12])


@pytest.fixture(autouse=True)
def _enforce(mode):
    mode("enforce")


def body(request_id, action, item_type, item_id, **over):
    """What aisc_control_objectives.ledger.body writes."""
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
         "item_id": item_id, "details": {}}
    e.update(over)
    return e


def co(project, tail):
    return f"/control-objectives/p/{project['pid']}{tail}"


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


CASES = [
    ("/projects", "assessment.started", "assessment", A,
     {"card_version": str(uuid.uuid4()), "details": {"risks": 5}}),
    (f"/api/projects/{A}/ratings", "risk.rated", "risk", "risk0",
     {"details": {"rating": 8}, "before": {"impact": None, "likelihood": None}, "after": {"impact": 4, "likelihood": 2}}),
    (f"/projects/{A}/severity", "risk.rated", "risk", "risk0", {"details": {"rating": 8}}),
    (f"/api/projects/{A}/severity-comments", "risk.rating_comment.set", "risk", "risk0",
     {"content": {"comment": "see the logs"}}),
    (f"/api/projects/{A}/risks/risk0/mapping", "mapping.risk.edited", "risk", "risk0",
     {"details": {"added": ["O5"], "removed": []}, "before": [], "after": ["O5"]}),
    (f"/projects/{A}/key", "objective.key.set", "assessment", A, {"details": {"added": ["O5"], "removed": []}}),
    (f"/api/projects/{A}/profile", "assessment.profile.switched", "assessment", A,
     {"details": {"version_before": None, "version_after": "v1", "dropped": []}}),
    ("/api/sets", "objective_set.created", "objective_set", "set1", {"details": {"code": "LDG"}, "content": {"code": "LDG"}}),
    ("/sets/set1/objectives", "objective.added", "objective", "LDG1", {"details": {"set": "set1"}, "content": {"text": "x"}}),
    ("/sets/set1/objectives/LDG1", "objective.edited", "objective", "LDG1",
     {"details": {"set": "set1"}, "content": {"text": "y"}, "before": {"text": "x"}, "after": {"text": "y"}}),
    ("/api/sets/set1/objectives/LDG1/retire", "objective.retired", "objective", "LDG1", {"details": {"set": "set1"}}),
    ("/sets/set1/objectives/LDG1/restore", "objective.restored", "objective", "LDG1", {"details": {"set": "set1"}}),
    ("/api/sets/set1/publish", "objective_set.published", "objective_set", "set1",
     {"item_version": "1", "details": {"version": 1}, "content": [{"id": "LDG1"}]}),
    ("/sets/set1/delete", "objective_set.deleted", "objective_set", "set1", {"content": {"code": "LDG"}}),
    ("/api/profiles", "objective_profile.created", "objective_profile", "prof1", {"content": {"picks": ["O1"]}}),
    ("/api/profiles/prof1/versions", "objective_profile.version_saved", "objective_profile", "prof1",
     {"item_version": "2", "details": {"version": 2, "dropped": []}, "content": {"picks": ["O1"]}}),
]


@pytest.mark.parametrize("tail, action, item_type, item_id, over", CASES, ids=[f"{c[1]}@{c[0]}" for c in CASES])
def test_an_event_as_the_app_sends_it_is_accepted(project, memory_ledger, witnessed, tail, action, item_type,
                                                  item_id, over):
    request_id = witnessed(MEMBER, "POST", "control_objectives", co(project, tail))
    emit(project["pid"], "control_objectives_rw", body(request_id, action, item_type, item_id, **over))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == action]
    assert (e.source_app, e.item_id) == ("control_objectives", item_id)


@pytest.mark.parametrize("method, tail, action, item_type, item_id", [
    ("PUT", "/api/sets/set1/objectives/LDG1", "objective.edited", "objective", "LDG1"),
    ("DELETE", "/api/sets/set1", "objective_set.deleted", "objective_set", "set1"),
    ("DELETE", f"/api/projects/{A}", "assessment.deleted", "assessment", A),
])
def test_the_api_verbs_are_causes_too(project, memory_ledger, witnessed, method, tail, action, item_type, item_id):
    request_id = witnessed(MEMBER, method, "control_objectives", co(project, tail))
    extra = {"content": {"x": 1}} if action != "assessment.deleted" else {"content": {"risks": []}}
    emit(project["pid"], "control_objectives_rw", body(request_id, action, item_type, item_id, **extra))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []


def test_an_ai_mapping_is_one_run_written_in_its_request(project, memory_ledger, witnessed):
    request_id = witnessed(MEMBER, "POST", "control_objectives", co(project, f"/api/projects/{A}/map"))
    run_id = str(uuid.uuid4())
    emit(project["pid"], "control_objectives_rw", body(request_id, "ai.mapping.requested", "assessment", A,
                                                       run_id=run_id))
    emit(project["pid"], "control_objectives_rw", body(request_id, "ai.llm_call", "llm_call", f"{run_id}:1",
                                                       run_id=run_id, model="fake/model",
                                                       details={"purpose": "mapping", "round": 1, "latency_ms": 3}))
    emit(project["pid"], "control_objectives_rw", body(request_id, "ai.mapping.completed", "assessment", A,
                                                       run_id=run_id, model="fake/model", details={"attempts": 1},
                                                       content={"risk0": ["O5"]}))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    done = [e for e in entries(memory_ledger, log_of(project["pid"])) if e.action == "ai.mapping.completed"]
    assert [(e.actor_kind, e.run_id, e.model) for e in done] == [("ai", run_id, "fake/model")]
