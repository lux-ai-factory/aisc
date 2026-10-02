"""L3: the event registry (I2, I7, I8, T13).

Every event the ledger accepts is in the registry; the registry says which app may emit it, what it
is about, which witnessed requests may cause it (`caused_by`, which may name another app than the
emitter, spec 4.1), where the code handles it (`routes`, by file and function), who may act, which
details are allowed. `check(event, emitter)` lists the problems of one event; an event with problems
is recorded as `ledger.rejected`, never trusted.
"""
from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from platform_service.ledger.registry import APP_PROJECT_RULES, KNOWN_APPS, REGISTRY, VERSION, check

ACTOR_KINDS = {"user", "ai", "worker", "system", "operator"}
#: Actions the witness or the beacon itself produces: no app emits them, no other request causes them.
WITNESS_BORN = {"request.witnessed", "request.unverified", "flower.request", "pgadmin.request"}
PLATFORM_ONLY = WITNESS_BORN | {"ledger.rejected", "ledger.reanchored"}
GATEWAY_APPS = {"engine", "engine_webapp", "flower", "controls", "qualification", "control_objectives",
                "report_composer", "platform", "launcher", "pgadmin", "schema", "dashboard"}

#: Events the registry must hold whatever else it holds: the ones the user named (opened, closed,
#: versions, by whom, AI vs manual) for each of the six steps, and the ledger's own.
REQUIRED = [
    # ledger and session
    "request.witnessed", "request.unverified", "page.opened", "page.left", "ledger.rejected",
    "ledger.reanchored", "flower.request", "pgadmin.request",
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
    # step 3: only the local installs. The catalogue is hosted elsewhere and never passes this gateway,
    # so its tool and ingest events belong in its own log (spec 3.1, R1.10).
    "plugin.installed", "control.installed",
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


def test_the_registry_imports_only_the_standard_library():
    """The repo-level coverage test loads it with no platform dependencies installed (R3.7)."""
    platform = Path(__file__).resolve().parents[2]
    code = ("import sys; sys.path.insert(0, %r); import platform_service.ledger.registry, "
            "platform_service.ledger.settings, platform_service.ledger.canonical, platform_service.ledger.naming"
            % str(platform))
    r = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_registry_has_a_version():
    assert isinstance(VERSION, int) and VERSION >= 1


def test_every_gateway_app_is_known_and_has_a_project_rule():
    assert GATEWAY_APPS <= set(KNOWN_APPS)
    assert GATEWAY_APPS <= set(APP_PROJECT_RULES)


def test_every_action_is_described_completely():
    for name, action in REGISTRY.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", name), name
        assert action.name == name
        assert action.step in range(0, 7), name
        assert set(action.emitters) <= set(KNOWN_APPS), name
        assert action.emitters or name in PLATFORM_ONLY, name
        assert action.origin in {"app", "platform", "browser"}, name
        assert (action.origin == "platform") == (not action.emitters), f"{name}: no emitters means origin platform"
        assert action.item_type, name
        assert action.actor_kinds and set(action.actor_kinds) <= ACTOR_KINDS, name
        assert not {"actor_sub", "actor_name", "actor_kind", "actor_ref", "user", "subject"} & set(action.details_keys), name


def test_a_user_action_names_the_witnessed_requests_that_may_cause_it():
    for name, action in REGISTRY.items():
        if "user" not in action.actor_kinds or name in WITNESS_BORN | {"session.signed_in", "session.signed_out"}:
            continue
        assert action.caused_by, f"{name}: a user action needs the requests that may cause it"
        for app, method, pattern in action.caused_by:
            assert app in GATEWAY_APPS, f"{name}: {app} is not behind the gateway"
            assert method in {"GET", "POST", "PUT", "PATCH", "DELETE", "ACTION"}, name
            re.compile(pattern)
            assert pattern.startswith("^/"), f"{name}: match the unstripped path from its start"


def test_an_item_group_is_only_where_the_path_names_the_item():
    for name, action in REGISTRY.items():
        for _, _, pattern in action.caused_by:
            assert set(re.compile(pattern).groupindex) <= {"item", "project"}, name


def test_a_witness_born_action_has_no_cause_and_no_route():
    for name in WITNESS_BORN:
        assert not REGISTRY[name].caused_by and not REGISTRY[name].routes, name


def test_every_ai_or_worker_action_belongs_to_a_run_some_user_action_starts():
    started = {r: n for n, a in REGISTRY.items() for r in a.runs}
    for name, action in REGISTRY.items():
        if {"ai", "worker"} & set(action.actor_kinds):
            assert name in started, f"{name}: no start action lists it in its runs"
            assert "user" in REGISTRY[started[name]].actor_kinds, name
    for name, action in REGISTRY.items():
        assert set(action.runs) <= set(REGISTRY), name
        if action.runs:
            assert action.run_window.total_seconds() > 0, name


def test_routes_name_a_file_and_a_function():
    for name, action in REGISTRY.items():
        for app, file, function in action.routes:
            assert app in KNOWN_APPS and "/" in file and re.fullmatch(r"[A-Za-z_]\w*", function), (name, file)


def _event(action="risk.rated", **over):
    a = REGISTRY[action]
    base = {"event_id": str(uuid.uuid4()), "action": action, "item_type": a.item_type, "item_id": "x1",
            "request_id": str(uuid.uuid4()), "details": {}}
    base.update(over)
    return base


def _emitter(action="risk.rated"):
    return REGISTRY[action].emitters[0]


def test_a_well_formed_event_has_no_problem():
    assert check(_event(), emitter=_emitter()) == []


def test_an_unknown_action_is_a_problem():
    assert "unknown_action" in check(_event() | {"action": "risk.invented"}, emitter=_emitter())


def test_an_app_that_may_not_emit_the_action_is_a_problem():
    other = next(app for app in KNOWN_APPS if app not in REGISTRY["risk.rated"].emitters)
    assert "emitter" in check(_event(), emitter=other)


@pytest.mark.parametrize("action", sorted(PLATFORM_ONLY))
def test_no_app_may_emit_the_platforms_own_actions(action):
    assert "emitter" in check({"event_id": str(uuid.uuid4()), "action": action, "item_type": "request",
                               "item_id": "x"}, emitter="controls")


@pytest.mark.parametrize("field", ["event_id", "action", "item_type", "item_id"])
def test_a_missing_field_is_a_problem(field):
    event = _event()
    del event[field]
    assert f"missing:{field}" in check(event, emitter=_emitter())


@pytest.mark.parametrize("key", ["actor_sub", "actor_name", "actor_ref", "user", "subject", "created_by"])
def test_an_app_naming_who_acted_in_details_is_a_problem(key):
    assert "actor_supplied" in check(_event(details={key: "someone"}), emitter=_emitter())


@pytest.mark.parametrize("key", ["actor_sub", "actor_kind", "on_behalf_of_ref", "source_app", "verified"])
def test_an_app_setting_a_platform_field_is_a_problem(key):
    assert "actor_supplied" in check(_event(**{key: "x"}), emitter=_emitter())


@pytest.mark.parametrize("field", ["content_sha256", "before_sha256", "after_sha256", "recorded_at", "seq"])
def test_an_app_sending_what_only_the_platform_computes_is_a_problem(field):
    """Digests are keyed with keys only the platform holds (second review N4)."""
    assert f"platform_field:{field}" in check(_event(**{field: "x"}), emitter=_emitter())


def test_content_may_carry_its_own_authors():
    """A frozen review legitimately says who reviewed it; only details and top-level fields are actor
    fields (R4.3)."""
    name = next(n for n, a in REGISTRY.items() if a.content_required)
    event = _event(name, content={"reviewed_by": "someone"})
    assert "actor_supplied" not in check(event, emitter=_emitter(name))


def test_a_details_key_the_action_does_not_allow_is_a_problem():
    assert "details_key:colour" in check(_event(details={"colour": "red"}), emitter=_emitter())


@pytest.mark.parametrize("value", ["Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig", "sk-abcdefghijklmnopqrstuvwx",
                                   "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln"])
@pytest.mark.parametrize("where", ["details", "content"])
def test_a_secret_in_the_details_or_the_content_is_a_problem(value, where):
    name = next(n for n, a in REGISTRY.items() if a.details_keys and a.content_required)
    key = next(iter(REGISTRY[name].details_keys))
    event = _event(name, details={key: value} if where == "details" else {},
                   content={"note": value} if where == "content" else {"note": "fine"})
    assert any(p.startswith("secret_in:") for p in check(event, emitter=_emitter(name)))


def test_an_action_that_freezes_content_needs_it():
    name = next(n for n, a in REGISTRY.items() if a.content_required)
    assert "content_required" in check(_event(name), emitter=_emitter(name))


def test_override_merges_over_the_real_registry_and_restores_it():
    """Tests declare their own actions; every real action stays known meanwhile (third review M2)."""
    from platform_service.ledger import registry
    from platform_service.ledger.registry import Action

    extra = Action(name="test.only.action", step=0, emitters=("controls",), item_type="x", caused_by=(),
                   routes=(), actor_kinds=("system",), details_keys=(), per_request=None)
    real = dict(REGISTRY)
    with registry.override({extra.name: extra}):
        assert registry.REGISTRY["test.only.action"] is extra
        assert set(real) <= set(registry.REGISTRY)
    assert dict(registry.REGISTRY) == real


def test_browser_reported_actions_have_their_own_origin():
    """`page.*` come through the beacon, never through an app's `ledger.emit` (fourth review 2)."""
    assert {n for n, a in REGISTRY.items() if a.origin == "browser"} >= {"page.opened", "page.left"}
    assert all(a.origin != "app" for n, a in REGISTRY.items() if n.startswith(("page.", "request.", "ledger.")))
