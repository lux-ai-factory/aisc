"""I1-I3: the internal route for callers without an outbox: the engine backend, the dashboard, the AI
services (I2, T3, T17; spec 4.4, 6.3). The caller is known by its own token, and each token may emit
only its own actions. An AI or worker event belongs to a run: it cites the person's request and the
run id of an accepted start event, inside the run window. The person it acted for is that start
event's, never a field it sends. A refused event is recorded (202 + `ledger.rejected`), as I2 says."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest


from tests.ledger.conftest import log_of, needs_db, MEMBER, entries, person, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
AGENTS_TOKEN = "test-agents-token-0123456789"
ENGINE_TOKEN = "test-engine-token-0123456789"


@pytest.fixture(autouse=True)
def _tokens(monkeypatch, mode):
    monkeypatch.setenv("PLATFORM_LEDGER_AGENTS_TOKEN", AGENTS_TOKEN)
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", ENGINE_TOKEN)
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", "test-dashboard-token-0123456789")
    mode("enforce")


def post(client, pid, event, token=AGENTS_TOKEN):
    headers = {"X-AISC-Service-Token": token} if token else {}
    return client.post(f"/internal/projects/{pid}/ledger/events", json=event, headers=headers)


def ai_event(request_id, run_id, **over):
    e = {"event_id": str(uuid.uuid4()), "action": "card.augmented_by_ai", "item_type": "qualification",
         "item_id": "q1", "request_id": request_id, "run_id": run_id, "model": "openai/gpt-4o-mini",
         "details": {}}
    e.update(over)
    return e


@pytest.fixture
def run(project, witnessed):
    """A person asks the AI to refine the card: the witnessed request and its start event."""
    request_id = witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/qualify/q1",
                           username="bob", next_action="7f01")
    run_id = str(uuid.uuid4())
    emit(project["pid"], "qualification_rw", {"event_id": str(uuid.uuid4()), "request_id": request_id,
                                               "run_id": run_id, "action": "card.ai_refinement_requested",
                                               "item_type": "qualification", "item_id": "q1", "details": {}})
    return request_id, run_id


def trusted(store, pid, action="card.augmented_by_ai"):
    return [e for e in entries(store, log_of(pid)) if e.action == action]


def reasons(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


def test_an_ai_event_names_the_program_the_model_and_the_person_who_started_the_run(client, project, memory_ledger, run):
    assert post(client, project["pid"], ai_event(*run)).status_code == 202
    relay_all(project["pid"])
    [e] = trusted(memory_ledger, project["pid"])
    assert (e.actor_kind, e.program, e.model, e.source_app) == ("ai", "qualification_agents", "openai/gpt-4o-mini",
                                                                "qualification_agents")
    assert person(project["pid"], e.on_behalf_of_ref) == (MEMBER, "bob") and e.run_id == run[1]


@pytest.mark.parametrize("given, status", [(None, 401), ("wrong", 401)])
def test_the_route_needs_the_callers_own_token(client, project, run, given, status):
    """(`given`, not `token`: a parameter named like the `token` fixture replaces it for `client`.)"""
    assert post(client, project["pid"], ai_event(*run), token=given).status_code == status


def test_an_unset_token_is_503(client, project, run, monkeypatch):
    """While a caller's token is unset, an unknown token may be that caller's: 503 says "not configured",
    not "wrong token". With every token set, an unknown one is 401 (above)."""
    monkeypatch.delenv("PLATFORM_LEDGER_AGENTS_TOKEN")
    assert post(client, project["pid"], ai_event(*run)).status_code == 503


@pytest.mark.parametrize("missing", ["model", "request_id", "run_id", "event_id"])
def test_a_malformed_ai_event_is_422(client, project, run, missing):
    event = ai_event(*run)
    del event[missing]
    assert post(client, project["pid"], event).status_code == 422


def test_an_ai_event_without_a_start_event_is_rejected(client, project, memory_ledger, run):
    post(client, project["pid"], ai_event(run[0], str(uuid.uuid4())))   # a run nobody started
    relay_all(project["pid"])
    assert trusted(memory_ledger, project["pid"]) == [] and reasons(memory_ledger, project["pid"]) == ["run"]


def test_an_ai_event_after_the_run_window_is_rejected(client, project, memory_ledger, run, settings):
    """The AI event comes RUN_WINDOW + 1 h after its start. (Moving the start back instead would make the
    start itself early for its request, and reject it as `early_event`.)"""
    import psycopg

    from tests.conftest import DSN

    relay_all(project["pid"])                                         # the start event, accepted
    event = ai_event(*run)
    assert post(client, project["pid"], event).status_code == 202
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE core.outbox SET occurred_at = occurred_at + %s WHERE event_id = %s",
                     (settings.RUN_WINDOW + timedelta(hours=1), event["event_id"]))
    relay_all(project["pid"])
    assert trusted(memory_ledger, project["pid"]) == [] and reasons(memory_ledger, project["pid"]) == ["run_window"]


def test_an_action_the_run_does_not_produce_is_rejected(client, project, memory_ledger, run):
    """An action the agents may emit, but not one this run produces. Every agents action today belongs to
    the refinement run, so the test adds one (ai.mapping.completed is the risk mapper's: `emitter`)."""
    from dataclasses import replace

    from platform_service.ledger import registry

    other = replace(registry.REGISTRY["agent.run_started"], name="agent.other_run_step")
    with registry.override({"agent.other_run_step": other}):
        post(client, project["pid"], ai_event(*run, action="agent.other_run_step", item_type="agent_run"))
        relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) == ["run"]


def test_a_token_may_emit_only_its_own_apps_actions(client, project, memory_ledger, run):
    """The agents' token can't pass off an engine event (R4.10)."""
    post(client, project["pid"], ai_event(*run, action="engine.measures.recorded", item_type="evaluation"))
    relay_all(project["pid"])
    assert "emitter" in reasons(memory_ledger, project["pid"])


def test_an_event_for_another_project_is_rejected(client, make_project, project, memory_ledger, run):
    other = make_project(MEMBER)
    post(client, other["pid"], ai_event(*run))
    relay_all(other["pid"])
    assert "project_mismatch" in reasons(memory_ledger, other["pid"])


def test_an_ai_event_naming_a_person_is_rejected(client, project, memory_ledger, run):
    post(client, project["pid"], ai_event(*run, on_behalf_of_ref="actor:" + "0" * 32))
    relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) == ["actor_supplied"]
