"""Q5: step 1's events, in the shapes apps/qualification/src/server/ledger/emit.ts builds, are accepted by
the relay against the REAL registry (no override): each cites the witnessed request of its route, as
qualification_rw; the agent's draft is the run's (card.augmented_by_ai, emitted by the app on the run
the refinement opened). A shape the app changes without the registry following fails here."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
CARD = "cmcard0000000000000000001"


@pytest.fixture(autouse=True)
def _enforce(mode):
    mode("enforce")


def body(request_id, action, item_type, item_id, **over):
    """What emit.ts eventBody writes."""
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
         "item_id": item_id, "details": {}}
    e.update(over)
    return e


def accepted(store, pid, action):
    return [e for e in entries(store, log_of(pid)) if e.action == action]


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


def page(project, tail=""):
    return f"/qualification/p/{project['slug']}{tail}"


CASES = [
    ("POST", "/qualify/" + CARD, "card.component_linked", "qualification", CARD,
     {"details": {"component": str(uuid.uuid4()), "property": "hasModel"}, "after": {"airoProperty": "hasModel"}}),
    ("POST", "/qualify/" + CARD, "card.component_unlinked", "qualification", CARD,
     {"details": {"component": str(uuid.uuid4()), "property": "hasModel"}, "before": {"airoProperty": "hasModel"}}),
    ("POST", "/qualify/" + CARD, "card.node_corrected", "qualification", CARD,
     {"details": {"node": "n1"}, "content": {"label": "x"}, "after": {"label": "x"}}),
    ("POST", "/qualify/" + CARD, "card.corrections_discarded", "qualification", CARD,
     {"before": {"n1": {"label": "x"}}, "after": {}}),
    ("PUT", f"/api/qualifications/{CARD}/extracted", "card.extracted_replaced_by_user", "qualification", CARD,
     {"content": {"techniques": []}}),
    ("POST", "/system/edit", "qualification.created", "qualification", CARD,     # the form's real page (review B1)
     {"details": {"questionnaire_version": "v1", "risks": 0, "components": 1}, "content": {"systemName": "MCAS"}}),
    ("POST", "/question-sets/new", "question_set.created", "question_set", "s1",
     {"details": {"version": 1}, "content": {"set": {}}}),
    ("POST", "/questionnaires/import", "question_set.created", "question_set", "s2",     # an import's set (M1)
     {"details": {"version": 1}, "content": {"set": {}}}),
    ("POST", "/question-sets/new", "questionnaire.created", "questionnaire", "qn2",       # "also a questionnaire"
     {"details": {"version": 1}, "content": {"q": {}}}),
    ("POST", "/question-sets/s1", "question_set.version_created", "question_set", "s1",
     {"item_version": "2", "details": {"version": 2, "added": 1, "removed": 0, "reworded": 0},
      "content": {"version": {"number": 2}}}),
    ("POST", "/question-sets/s1", "question_set.retired", "question_set", "s1", {}),
    ("POST", "/questionnaires/new", "questionnaire.created", "questionnaire", "qn1",
     {"details": {"version": 1}, "content": {}}),
    ("POST", "/questionnaires/qn1", "questionnaire.version_created", "questionnaire", "qn1",
     {"item_version": "2", "details": {"version": 2, "items": 3, "blocks": 2}, "content": {"version": {"number": 2}}}),
    ("POST", "/questionnaires", "questionnaire.retired", "questionnaire", "qn1", {}),
    ("GET", f"/api/qualifications/{CARD}/ai-card.pdf", "card.pdf_downloaded", "qualification", CARD,
     {"details": {"format": "ai-card.pdf"}}),
    ("GET", "/qualify/" + CARD, "qualification.opened", "qualification", CARD,
     {"details": {"version": "2", "read_only": False}}),
]


@pytest.mark.parametrize("method, tail, action, item_type, item_id, over", CASES,
                         ids=[f"{c[2]}@{c[1]}" for c in CASES])
def test_an_event_as_the_app_sends_it_is_accepted(project, memory_ledger, witnessed, method, tail, action, item_type,
                                                  item_id, over):
    request_id = witnessed(MEMBER, method, "qualification", page(project, tail), next_action="7f01aa")
    emit(project["pid"], "qualification_rw", body(request_id, action, item_type, item_id, **over))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = accepted(memory_ledger, project["pid"], action)
    assert (e.source_app, e.request_id, e.item_id) == ("qualification", request_id, item_id)


def test_a_refinement_run_the_app_opened_takes_the_agents_events_and_the_apps_draft(project, client, memory_ledger,
                                                                                 witnessed, monkeypatch):
    """rerunFill opens the run; the agent posts its own events (internal route); the app records the
    agent's draft in the PUT's transaction, on the same run (card.augmented_by_ai, emitter qualification)."""
    monkeypatch.setenv("PLATFORM_LEDGER_AGENTS_TOKEN", "agents-token-test-0123")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", "engine-token-test-0123")
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", "dashboard-token-test-0123")
    request_id = witnessed(MEMBER, "POST", "qualification", page(project, "/qualify/" + CARD), next_action="7f01bb")
    run_id = str(uuid.uuid4())
    emit(project["pid"], "qualification_rw", body(request_id, "card.ai_refinement_requested", "qualification", CARD,
                                                  run_id=run_id))
    relay_all(project["pid"])
    for action, details in (("agent.run_started", {"model": "openai/gpt-4o-mini"}),
                            ("ai.llm_call", {"purpose": "draft", "property": "hasPurpose", "round": None,
                                             "latency_ms": 12})):
        r = client.post(f"/internal/projects/{project['pid']}/ledger/events",
                        json={"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run_id,
                              "action": action, "item_type": "agent_run" if action.startswith("agent") else "llm_call",
                              "item_id": run_id, "model": "openai/gpt-4o-mini", "details": details},
                        headers={"X-AISC-Service-Token": "agents-token-test-0123"})
        assert r.status_code == 202, r.text
    emit(project["pid"], "qualification_rw", body(request_id, "card.augmented_by_ai", "qualification", CARD,
                                                  run_id=run_id, model="openai/gpt-4o-mini",
                                                  details={"flagged": 1}, content={"techniques": []}))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [draft] = accepted(memory_ledger, project["pid"], "card.augmented_by_ai")
    assert (draft.actor_kind, draft.source_app, draft.run_id, draft.model) == ("ai", "qualification", run_id,
                                                                              "openai/gpt-4o-mini")
    assert {e.action for e in entries(memory_ledger, log_of(project["pid"]))} >= {"agent.run_started", "ai.llm_call"}


@pytest.mark.parametrize("name", ["canonical_vectors.json", "canonical_vectors_random.json"])
def test_the_typescript_twin_checks_the_platforms_own_vectors(name):
    """Q2: the copies the qualification app's tests read are the platform's files, unchanged."""
    from pathlib import Path

    here = Path(__file__).parent / "fixtures" / name
    there = Path(__file__).resolve().parents[3] / "apps/qualification/test/fixtures/ledger" / name
    assert there.read_bytes() == here.read_bytes(), f"copy {here} to {there}"


def test_a_run_with_no_end_after_the_run_window_is_reported(project, memory_ledger, settings):
    """Phase 5 drill, reconciled: an agent killed mid-run leaves a run that never ends."""
    import psycopg

    from platform_service.ledger import testing, verify
    from tests.conftest import DSN

    run_id = str(uuid.uuid4())
    [seq] = testing.seed(project["pid"], [{"event_id": str(uuid.uuid4()), "action": "agent.run_started",
                                          "item_type": "agent_run", "item_id": run_id, "run_id": run_id,
                                          "actor_kind": "ai", "occurred_at": "2026-01-01T00:00:00+00:00"}])
    assert verify.verify(project["pid"]).open_runs == 1
    testing.seed(project["pid"], [{"event_id": str(uuid.uuid4()), "action": "agent.run_failed", "item_type": "agent_run",
                                   "item_id": run_id, "run_id": run_id, "actor_kind": "ai"}])
    assert verify.verify(project["pid"]).open_runs == 0


# phase 5 review -------------------------------------------------------------------------------------

def test_one_save_action_makes_a_set_then_its_next_version(project, memory_ledger, witnessed):
    """M3: saveQuestionSet is one server action (one action id) for both branches."""
    first = witnessed(MEMBER, "POST", "qualification", page(project, "/question-sets/new"), next_action="7f0c01")
    emit(project["pid"], "qualification_rw", body(first, "question_set.created", "question_set", "s1",
                                                  details={"version": 1}, content={"set": {}}))
    relay_all(project["pid"])
    later = witnessed(MEMBER, "POST", "qualification", page(project, "/question-sets/s1/edit"), next_action="7f0c01")
    emit(project["pid"], "qualification_rw", body(later, "question_set.version_created", "question_set", "s1",
                                                  details={"version": 2, "added": 1, "removed": 0, "reworded": 0},
                                                  content={"version": {"number": 2}}))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert len(accepted(memory_ledger, project["pid"], "question_set.version_created")) == 1


def test_an_action_id_still_refuses_an_action_of_another_server_action(project, memory_ledger, witnessed):
    first = witnessed(MEMBER, "POST", "qualification", page(project, "/question-sets/new"), next_action="7f0c02")
    emit(project["pid"], "qualification_rw", body(first, "question_set.created", "question_set", "s1",
                                                  details={"version": 1}, content={"set": {}}))
    relay_all(project["pid"])
    other = witnessed(MEMBER, "POST", "qualification", page(project, "/question-sets/s1"), next_action="7f0c02")
    emit(project["pid"], "qualification_rw", body(other, "question_set.retired", "question_set", "s1"))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == ["action_id"]


def test_a_run_event_for_another_card_than_the_runs_is_rejected(project, memory_ledger, witnessed):
    """m4: the run was opened on CARD; the agent's draft can't land on another card."""
    request_id = witnessed(MEMBER, "POST", "qualification", page(project, "/qualify/" + CARD), next_action="7f0c03")
    run_id = str(uuid.uuid4())
    emit(project["pid"], "qualification_rw", body(request_id, "card.ai_refinement_requested", "qualification", CARD,
                                                  run_id=run_id))
    relay_all(project["pid"])
    emit(project["pid"], "qualification_rw", body(request_id, "card.augmented_by_ai", "qualification", "cmother000",
                                                  run_id=run_id, model="m", details={"flagged": 0},
                                                  content={"techniques": []}))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == ["run"]


def test_a_refinement_whose_run_never_got_going_is_reported(project, memory_ledger):
    """M4, m3: an agent down, busy, or failing before its model is known leaves a start with no end."""
    from platform_service.ledger import testing, verify

    run_id = str(uuid.uuid4())
    testing.seed(project["pid"], [{"event_id": str(uuid.uuid4()), "action": "card.ai_refinement_requested",
                                   "item_type": "qualification", "item_id": CARD, "run_id": run_id,
                                   "actor_kind": "user", "occurred_at": "2026-01-01T00:00:00+00:00"}])
    assert verify.verify(project["pid"]).open_runs == 1
