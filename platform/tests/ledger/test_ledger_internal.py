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


def test_a_wrong_token_is_401_even_while_a_caller_is_unconfigured(client, project, run, monkeypatch):
    """Review m4: a prober learns nothing about the configuration."""
    monkeypatch.delenv("PLATFORM_LEDGER_AGENTS_TOKEN")
    assert post(client, project["pid"], ai_event(*run)).status_code == 401


def test_with_no_caller_token_set_the_route_is_closed_503(client, project, run, monkeypatch):
    for name in ("PLATFORM_LEDGER_AGENTS_TOKEN", "PLATFORM_LEDGER_ENGINE_TOKEN", "PLATFORM_LEDGER_DASHBOARD_TOKEN"):
        monkeypatch.delenv(name)
    assert post(client, project["pid"], ai_event(*run)).status_code == 503


def test_two_callers_with_one_token_is_503(client, project, run, monkeypatch):
    """Review m3: equal tokens would file one caller's events as the other's."""
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", AGENTS_TOKEN)
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


# phase 4 review M2, M5, m2, m17, m18 -----------------------------------------------------------------

def test_the_same_event_sent_twice_is_accepted_once(client, project, memory_ledger, run):
    event = ai_event(*run)
    assert post(client, project["pid"], event).status_code == 202
    assert post(client, project["pid"], event).status_code == 202   # a retry after a lost answer
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


@pytest.mark.parametrize("change", [{"item_id": "q2"}, {"model": "other/model"}])
def test_an_event_id_reused_with_other_content_is_refused_never_dropped(client, project, run, change):
    """M2 / I3: not a silent 202 keeping the first copy."""
    event = ai_event(*run)
    assert post(client, project["pid"], event).status_code == 202
    r = post(client, project["pid"], {**event, **change})
    assert r.status_code == 409 and "event_id" in r.text


def test_an_event_id_reused_by_another_caller_is_refused(client, project, run):
    event = ai_event(*run)
    assert post(client, project["pid"], event).status_code == 202
    assert post(client, project["pid"], event, token=ENGINE_TOKEN).status_code == 409


def test_a_large_body_is_413_and_a_long_field_422(client, project, run):
    """M5: the route caps what reaches the relay."""
    assert post(client, project["pid"], ai_event(*run, details={"flagged": "x" * 40_000})).status_code == 413
    assert post(client, project["pid"], ai_event(*run, item_id="q" * 300)).status_code == 422


def test_an_entry_too_large_for_the_log_is_rejected_and_the_log_goes_on(client, project, memory_ledger, run,
                                                                        settings, monkeypatch):
    """M5: an event the store refuses for size is a `too_large` rejection, never a stall of the log.
    (The cap is lowered for the test, below the route's own body limit.)"""
    relay_all(project["pid"])                                         # the run's start event
    monkeypatch.setattr(settings, "MAX_ENTRY_BYTES", 2048)
    big = ai_event(*run, action="agent.run_failed", item_type="agent_run", details={"error": "e" * 4000})
    assert post(client, project["pid"], big).status_code == 202
    assert post(client, project["pid"], ai_event(*run)).status_code == 202
    relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) == ["too_large"]
    assert len(trusted(memory_ledger, project["pid"])) == 1          # the later event was not held up


@pytest.mark.parametrize("outcome", ["refused", "anything"])
def test_a_caller_may_not_choose_a_refused_outcome(client, project, run, outcome):
    """m2: `refused` is the relay's word; emitters say ok or failed."""
    assert post(client, project["pid"], ai_event(*run, outcome=outcome)).status_code == 422


def test_the_route_is_not_served_through_the_gateway(client, project, run):
    """m17: X-Forwarded-* means it came through Caddy: 404."""
    r = client.post(f"/internal/projects/{project['pid']}/ledger/events", json=ai_event(*run),
                    headers={"X-AISC-Service-Token": AGENTS_TOKEN, "X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 404


def test_the_emitter_is_the_tokens_never_the_bodys(client, project, memory_ledger, run):
    """m18: a body naming another emitter changes nothing about who sent it."""
    post(client, project["pid"], ai_event(*run, emitter="engine", source_app="engine"))
    relay_all(project["pid"])
    assert [e.source_app for e in trusted(memory_ledger, project["pid"])] in ([], ["qualification_agents"])
    assert [e.source_app for e in entries(memory_ledger, log_of(project["pid"]))
            if e.action != "request.witnessed"] != ["engine"]


def test_a_run_whose_index_row_names_another_person_is_rejected(client, project, memory_ledger, run):
    """m12: the run's person is the logged start event's, never the index row's."""
    import psycopg

    from tests.conftest import DSN

    relay_all(project["pid"])
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE ledger.event_index SET actor_ref = %s WHERE run_id = %s",
                     ("actor:" + "9" * 32, run[1]))
    post(client, project["pid"], ai_event(*run))
    relay_all(project["pid"])
    assert trusted(memory_ledger, project["pid"]) == [] and reasons(memory_ledger, project["pid"]) == ["index_mismatch"]
