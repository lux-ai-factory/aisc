"""L3: the event registry (I2, I7, I8, T13).

Every event the ledger accepts is in the registry; the registry says which app may emit it, what it
is about, which requests may cause it, who may act, which details are allowed. `check` lists the
problems of one event; an event with problems is recorded as `ledger.rejected`, never trusted.
"""
from __future__ import annotations

import re
import uuid

import pytest

from platform_service.ledger.registry import KNOWN_APPS, REGISTRY, check

ACTOR_KINDS = {"user", "ai", "worker", "system", "operator"}

#: Events the registry must hold whatever else it holds: the ones the user named (opened, closed,
#: versions, by whom, AI vs manual) for each of the six steps, and the ledger's own.
REQUIRED = [
    # ledger and session
    "request.witnessed", "request.unverified", "page.opened", "page.left", "ledger.rejected",
    "session.signed_in", "session.signed_out", "access.refused",
    # platform and Manage
    "project.created", "project.deleted", "member.added", "member.role_changed", "member.removed",
    "card_version.created", "llm.provider.saved", "llm.provider.removed", "llm.choice.saved",
    "connection.saved", "connection.deleted", "connection.tested", "allowlist.host.allowed",
    "allowlist.host.removed",
    # step 1
    "question_set.created", "question_set.version_created", "question_set.retired",
    "questionnaire.created", "questionnaire.version_created", "questionnaire.retired",
    "qualification.opened", "qualification.created", "card.node_corrected", "card.corrections_discarded",
    "card.component_linked", "card.component_unlinked", "card.ai_refinement_requested",
    "card.augmented_by_ai", "agent.run_started", "agent.run_finished", "agent.run_failed", "ai.llm_call",
    "card.pdf_downloaded",
    # step 2
    "assessment.started", "assessment.deleted", "risk.rated", "risk.rating_comment.set",
    "ai.mapping.requested", "ai.mapping.completed", "ai.mapping.failed", "mapping.risk.edited",
    "objective.key.set", "assessment.profile.switched", "objective_set.created", "objective_set.published",
    "objective_profile.created", "objective_profile.version_saved",
    # step 3
    "catalogue.tool.created", "catalogue.tool.updated", "catalogue.tool.deleted",
    "catalogue.control.ingested", "plugin.installed", "control.installed",
    # step 4
    "evidence.links.saved", "engine.evaluation.run_requested", "engine.evaluation.status_changed",
    "engine.measures.recorded", "engine.artifact.uploaded", "engine.plugin.configured",
    "controls.submission.created", "controls.submission.draft_saved", "controls.submission.closed",
    "controls.submission.reopened", "controls.checklist.questions_revised",
    # step 5
    "dashboard.viewed", "dashboard.comment.created", "dashboard.comment.deleted",
    "dashboard.review.requested", "dashboard.review.resolved",
    # step 6
    "report.layout.created", "report.layout.updated", "report.layout.deleted", "report.generated",
    "report.downloaded",
]


@pytest.mark.parametrize("name", REQUIRED)
def test_the_registry_holds_every_event_the_user_asked_for(name):
    assert name in REGISTRY, name


def test_every_action_is_described_completely():
    for name, action in REGISTRY.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", name), name
        assert action.name == name
        assert action.step in range(0, 7), name
        assert action.apps and set(action.apps) <= set(KNOWN_APPS), name
        assert action.item_type, name
        assert action.actor_kinds and set(action.actor_kinds) <= ACTOR_KINDS, name
        assert not {"actor_sub", "actor_name", "actor_kind", "user", "subject"} & set(action.details_keys), name


def test_a_user_action_names_the_requests_that_may_cause_it():
    for name, action in REGISTRY.items():
        if "user" in action.actor_kinds and name not in ("session.signed_in", "session.signed_out"):
            assert action.paths, f"{name}: a user action needs the request paths that may cause it"
            for method, pattern in action.paths:
                assert method in {"GET", "POST", "PUT", "PATCH", "DELETE"}, name
                re.compile(pattern)


def test_an_ai_or_worker_action_names_what_it_may_cite():
    for name, action in REGISTRY.items():
        if {"ai", "worker"} & set(action.actor_kinds):
            assert action.starts, f"{name}: an AI or worker action must cite the request that started it"
            assert set(action.starts) <= set(REGISTRY), name


def _event(**over):
    base = {"event_id": str(uuid.uuid4()), "action": "risk.rated", "item_type": "risk", "item_id": "risk2",
            "request_id": str(uuid.uuid4()), "details": {"impact": 5, "likelihood": 4}}
    base.update(over)
    return base


def test_a_well_formed_event_has_no_problem():
    assert check(_event()) == []


def test_an_unknown_action_is_a_problem():
    assert "unknown_action" in check(_event(action="risk.invented"))


@pytest.mark.parametrize("field", ["event_id", "action", "item_type", "item_id"])
def test_a_missing_field_is_a_problem(field):
    event = _event()
    del event[field]
    assert f"missing:{field}" in check(event)


@pytest.mark.parametrize("key", ["actor_sub", "actor_name", "user", "subject", "created_by"])
def test_an_app_naming_who_acted_is_a_problem(key):
    assert "actor_supplied" in check(_event(details={"impact": 5, key: "someone"}))


def test_a_details_key_the_action_does_not_allow_is_a_problem():
    assert "details_key:colour" in check(_event(details={"impact": 5, "colour": "red"}))


@pytest.mark.parametrize("value", ["Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig", "sk-abcdefghijklmnopqrstuvwx",
                                   "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln"])
def test_a_secret_in_the_details_is_a_problem(value):
    action = next(a for a in REGISTRY.values() if a.details_keys)
    key = next(iter(action.details_keys))
    event = _event(action=action.name, item_type=action.item_type, details={key: value})
    assert f"secret_in:{key}" in check(event)


def test_an_action_that_freezes_content_needs_it():
    name = next(n for n, a in REGISTRY.items() if a.content_required)
    action = REGISTRY[name]
    assert "content_required" in check(_event(action=name, item_type=action.item_type, details={}))
