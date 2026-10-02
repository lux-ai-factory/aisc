"""I1: the internal route for apps without an outbox (engine, dashboard, AI services) (I2, T3).
The caller is known by its own token; an AI or worker event cites the request that started it, and
the person it acted for is that request's witness, never a field it sends."""
from __future__ import annotations

import uuid

import pytest

from platform_service.ledger.naming import database_name
from tests.conftest import needs_database
from tests.ledger.conftest import MEMBER, entries

pytestmark = needs_database
AGENTS_TOKEN = "test-agents-token-0123456789"


@pytest.fixture(autouse=True)
def _tokens(monkeypatch):
    monkeypatch.setenv("PLATFORM_LEDGER_AGENTS_TOKEN", AGENTS_TOKEN)


def post(client, pid, event, token=AGENTS_TOKEN):
    headers = {"X-AISC-Service-Token": token} if token else {}
    return client.post(f"/internal/projects/{pid}/ledger/events", json=event, headers=headers)


def ai_event(request_id, **over):
    e = {"event_id": str(uuid.uuid4()), "action": "card.augmented_by_ai", "item_type": "qualification",
         "item_id": "q1", "request_id": request_id, "program": "qualification-agents",
         "model": "openai/gpt-4o-mini", "details": {"flagged": 2}}
    e.update(over)
    return e


@pytest.fixture
def refine(project, witnessed, memory_ledger, mode):
    """The witnessed request of a person asking the AI to refine the card."""
    mode("enforce")
    return witnessed(MEMBER, "POST", f"/qualification/p/{project['pid']}/qualify/q1")


def test_an_ai_event_names_the_program_the_model_and_the_person(client, project, memory_ledger, refine):
    r = post(client, project["pid"], ai_event(refine))
    assert r.status_code in (200, 201, 202), r.text
    [e] = [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "card.augmented_by_ai"]
    assert (e.actor_kind, e.program, e.model, e.on_behalf_of_sub) == ("ai", "qualification-agents",
                                                                      "openai/gpt-4o-mini", MEMBER)
    assert e.source_app == "qualification_agents"


@pytest.mark.parametrize("token, status", [(None, 401), ("wrong", 401)])
def test_the_route_needs_the_callers_own_token(client, project, refine, token, status):
    assert post(client, project["pid"], ai_event(refine), token=token).status_code == status


def test_an_unset_token_is_503(client, project, refine, monkeypatch):
    monkeypatch.delenv("PLATFORM_LEDGER_AGENTS_TOKEN")
    assert post(client, project["pid"], ai_event(refine)).status_code == 503


@pytest.mark.parametrize("missing", ["program", "model", "request_id"])
def test_an_ai_event_without_what_identifies_it_is_refused(client, project, refine, missing):
    event = ai_event(refine)
    del event[missing]
    assert post(client, project["pid"], event).status_code == 422


def test_an_ai_event_citing_a_request_that_does_not_start_it_is_refused(client, project, witnessed, refine):
    unrelated = witnessed(MEMBER, "POST", f"/control-objectives/p/{project['pid']}/projects/a/severity")
    assert post(client, project["pid"], ai_event(unrelated)).status_code == 422


def test_an_ai_event_naming_a_person_is_refused(client, project, refine):
    assert post(client, project["pid"], ai_event(refine, on_behalf_of_sub="someone-else")).status_code == 422
