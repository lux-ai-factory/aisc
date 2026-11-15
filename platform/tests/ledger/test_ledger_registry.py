"""The event registry.

Every event the ledger accepts is in the registry; the registry says which app may emit it, what it
is about, which witnessed requests may cause it (`caused_by`, which may name another app than the
emitter), where the code handles it (`routes`, by file and function), who may act, which
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
PLATFORM_ONLY = WITNESS_BORN | {"ledger.rejected", "ledger.reanchored", "ledger.content.redacted", "ledger.mode",
                                "operator.correction.declared"}
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
    "card_version.created", "card_version.revised", "llm.provider.saved", "llm.provider.removed", "llm.choice.saved",
    "connection.saved", "connection.deleted", "connection.tested", "connection.use.saved", "connection.use.removed",
    "allowlist.host.allowed",
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
    # so its tool and ingest events belong in its own log.
    "plugin.installed", "control.installed",
    # step 4
    "evidence.links.saved", "evidence.map.reviewed", "engine.evaluation.run_requested", "engine.evaluation.status_changed",
    "engine.measures.recorded", "engine.artifact.uploaded", "engine.evaluation.input_marked_local",
    "engine.plugin.configured",
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
    """The repo-level coverage test loads it with no platform dependencies installed."""
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
            assert action.window().total_seconds() > 0, name


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
    """Digests are keyed with keys only the platform holds."""
    assert f"platform_field:{field}" in check(_event(**{field: "x"}), emitter=_emitter())


def test_content_may_carry_its_own_authors():
    """A frozen review legitimately says who reviewed it; only details and top-level fields are actor
    fields."""
    name = next(n for n, a in REGISTRY.items() if a.content_required)
    event = _event(name, content={"reviewed_by": "someone"})
    assert "actor_supplied" not in check(event, emitter=_emitter(name))


def test_a_details_key_the_action_does_not_allow_is_a_problem():
    assert "details_key:colour" in check(_event(details={"colour": "red"}), emitter=_emitter())


def test_opening_a_card_may_say_the_caller_is_a_viewer_apart_from_the_card_being_an_earlier_one():
    event = _event("qualification.opened", details={"version": 3, "read_only": False, "viewer": True})
    assert check(event, emitter=_emitter("qualification.opened")) == []


@pytest.mark.parametrize("value", ["Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig", "sk-abcdefghijklmnopqrstuvwx",
                                   "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln"])
@pytest.mark.parametrize("where", ["details", "content"])
def test_a_secret_in_the_details_or_the_content_is_a_problem(value, where):
    name = next(n for n, a in REGISTRY.items() if a.details_keys and a.content_required)
    key = next(iter(REGISTRY[name].details_keys))
    event = _event(name, details={key: value} if where == "details" else {},
                   content={"note": value} if where == "content" else {"note": "fine"})
    assert any(p.startswith("secret_in:") for p in check(event, emitter=_emitter(name)))


@pytest.mark.parametrize("where", ["details", "content"])
def test_the_word_bearer_in_prose_is_not_a_secret(where):
    """Only a credential-shaped value after `Bearer` counts: "the bearer of bad news" is ordinary text."""
    value = "She was the bearer of bad news."
    name = next(n for n, a in REGISTRY.items() if a.details_keys and a.content_required)
    key = next(iter(REGISTRY[name].details_keys))
    event = _event(name, details={key: value} if where == "details" else {},
                   content={"note": value} if where == "content" else {"note": "fine"})
    assert not [p for p in check(event, emitter=_emitter(name)) if p.startswith("secret_in:")]


@pytest.mark.parametrize("value", ["Bearer abcDEF0123456789xyz", "use Bearer abcdef0123456789 now",
                                   "bearer 0123456789abcdef0123"])
@pytest.mark.parametrize("where", ["details", "content"])
def test_bearer_with_a_credential_shaped_token_is_still_a_secret(value, where):
    name = next(n for n, a in REGISTRY.items() if a.details_keys and a.content_required)
    key = next(iter(REGISTRY[name].details_keys))
    event = _event(name, details={key: value} if where == "details" else {},
                   content={"note": value} if where == "content" else {"note": "fine"})
    assert (f"secret_in:{key}" if where == "details" else "secret_in:content") in check(event, emitter=_emitter(name))


@pytest.mark.parametrize("value", ["Basic dXNlcjpwYXNzd29yZDEyMzQ=", "Token abcdef0123456789",
                                   "use token 0123456789abcdef0123 now", "send basic QWxhZGRpbjpvcGVuIHNlc2FtZQ== here",
                                   "Authorization: Token abcDEF0123456789xyz"])
@pytest.mark.parametrize("where", ["details", "content"])
def test_basic_or_token_with_a_credential_shaped_value_is_a_secret(value, where):
    """`Basic` and `Token` count like `Bearer`: followed by 16 characters or more of the base64, hex and URL-safe
    alphabets."""
    name = next(n for n, a in REGISTRY.items() if a.details_keys and a.content_required)
    key = next(iter(REGISTRY[name].details_keys))
    event = _event(name, details={key: value} if where == "details" else {},
                   content={"note": value} if where == "content" else {"note": "fine"})
    assert (f"secret_in:{key}" if where == "details" else "secret_in:content") in check(event, emitter=_emitter(name))


@pytest.mark.parametrize("value", ["Please accept a token of thanks.", "Token abc", "Basic abc",
                                   "Basic training starts on Monday.", "Token abcdef012345678"])
@pytest.mark.parametrize("where", ["details", "content"])
def test_basic_or_token_in_prose_or_with_a_short_value_is_not_a_secret(value, where):
    """A word after `Token` or `Basic`, or a value under 16 characters, is ordinary text."""
    name = next(n for n, a in REGISTRY.items() if a.details_keys and a.content_required)
    key = next(iter(REGISTRY[name].details_keys))
    event = _event(name, details={key: value} if where == "details" else {},
                   content={"note": value} if where == "content" else {"note": "fine"})
    assert not [p for p in check(event, emitter=_emitter(name)) if p.startswith("secret_in:")]


def test_an_action_that_freezes_content_needs_it():
    name = next(n for n, a in REGISTRY.items() if a.content_required)
    assert "content_required" in check(_event(name), emitter=_emitter(name))


def test_unlinking_every_evidence_link_is_content_not_a_missing_one():
    """An empty set of links is what the save froze; an absent content is still a problem."""
    name = "evidence.links.saved"
    details = {"added": 0, "removed": 1, "carried": False}
    assert "content_required" not in check(_event(name, details=details, content=[]), emitter=_emitter(name))
    assert "content_required" in check(_event(name, details=details), emitter=_emitter(name))


def test_a_recording_of_no_measures_is_content_not_a_missing_one():
    name = "engine.measures.recorded"
    assert "content_required" not in check(_event(name, details={"count": 0}, content=[]), emitter=_emitter(name))
    assert "content_required" in check(_event(name, details={"count": 0}), emitter=_emitter(name))


def test_other_actions_still_take_empty_content_as_missing():
    others = [n for n, a in REGISTRY.items() if a.content_required and not a.empty_content]
    assert others
    for name in others:
        for empty in ({}, []):
            assert "content_required" in check(_event(name, content=empty), emitter=_emitter(name)), name


def test_override_merges_over_the_real_registry_and_restores_it():
    """Tests declare their own actions; every real action stays known meanwhile."""
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
    """`page.*` come through the beacon, never through an app's `ledger.emit`."""
    assert {n for n, a in REGISTRY.items() if a.origin == "browser"} >= {"page.opened", "page.left"}
    assert all(a.origin != "app" for n, a in REGISTRY.items() if n.startswith(("page.", "request.", "ledger.")))


@pytest.mark.parametrize("bad", [{"details": "x"}, {"details": ["a"]}, {"action": ["risk.rated"]},
                                 {"action": {"a": 1}}, {"content": 5}])
def test_a_malformed_event_is_a_problem_never_a_crash(bad):
    """Check() answers for anything an app sends."""
    event = {**_event(), **bad}
    problems = check(event, emitter=_emitter())
    assert problems


SETTINGS_ONLY_SECRET_DELETE = ("engine", "DELETE", r"^/api/v1/project/settings/[^/]+/(?P<item>[^/]+)$")
PLUGIN_CONFIG_SAVE = ("engine", "POST", r"^/api/v1/plugins/[^/]+/config$")


@pytest.mark.parametrize("name", ["engine.secret.created", "engine.secret.updated"])
def test_saving_a_plugin_configuration_may_keep_up_to_sixteen_keys_as_secrets(name):
    """A key typed into a plugin's form is kept as a project secret by the save itself, one event per key."""
    action = REGISTRY[name]
    assert PLUGIN_CONFIG_SAVE in action.caused_by
    assert action.per_request == 16


def test_only_the_settings_route_deletes_a_secret():
    action = REGISTRY["engine.secret.deleted"]
    assert action.caused_by == (SETTINGS_ONLY_SECRET_DELETE,)
    assert action.per_request == 1


def test_a_plot_the_chart_assistant_removes_is_recorded_from_the_message_that_asked_for_it():
    removed = REGISTRY["dashboard.assistant.removed"]
    assert removed.item_type == "chart" and removed.details_keys == ("dashboard",)
    assert removed.routes == (("dashboard", "apps/results-dashboard/aisc_ext/assistant/api.py", "message"),)


def test_a_validated_chart_may_say_which_plot_it_replaced():
    assert "replaces" in REGISTRY["dashboard.assistant.validated"].details_keys



def test_a_plot_the_chart_assistant_changes_in_place_is_recorded_from_the_message_that_asked_for_it():
    changed = REGISTRY["dashboard.assistant.changed"]
    assert changed.item_type == "chart" and changed.details_keys == ("dashboard",)
    assert changed.routes == (("dashboard", "apps/results-dashboard/aisc_ext/assistant/api.py", "message"),)


def test_one_message_may_remove_several_plots_each_with_its_own_event():
    assert REGISTRY["dashboard.assistant.removed"].per_request is None


def test_a_person_stopping_a_run_on_the_engine_is_recorded_from_the_stop_request():
    stopped = REGISTRY["engine.evaluation.stopped"]
    assert stopped.emitters == ("engine",) and stopped.item_type == "evaluation"
    assert stopped.actor_kinds == ("user",) and stopped.per_request == 1
    assert stopped.details_keys == ("status_before", "tests")
    (cause,) = stopped.caused_by
    assert cause[0] == "engine" and cause[1] == "POST"
    m = re.match(cause[2], "/api/v1/evaluations/0b6f3c4e-1111-2222-3333-444455556666/stop")
    assert m and m.group("item") == "0b6f3c4e-1111-2222-3333-444455556666"
    assert stopped.routes == (("engine", "apps/backend/aisc_backend/routers/evaluation.py", "stop_evaluation"),)


def test_deleting_a_connection_may_end_each_of_its_uses_with_its_own_event():
    removed = REGISTRY["connection.use.removed"]
    assert removed.per_request is None
    assert any(app == "platform" and method == "DELETE" and re.match(path, "/api/projects/p/connections/judge-x")
               for app, method, path in removed.caused_by)


# The three events a card revision and a controls amendment emit, in the shapes the code builds them:
# apps/qualification/src/app/p/[project]/qualify/new/actions.ts (submitQualification, the correction branch),
# platform_service/db.py (revise_version) and apps/controls/src/app/p/[project]/submissions/[id]/actions.ts
# (reopenForAmendment).
_AMENDED = {"event_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()), "action": "qualification.amended",
            "item_type": "qualification", "item_id": "cmcard0000000000000000002",
            "details": {"revision": 2, "amends": "cmcard0000000000000000001", "reason": "provider name",
                        "requested_by": "Eindhoven Engine", "risks": 2, "components": 1},
            "content": {"systemName": "MCAS"}}
_REVISED = {"event_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()), "action": "card_version.revised",
            "item_type": "card_version", "item_id": str(uuid.uuid4()), "item_version": 1,
            "details": {"number": 1, "card_revision": 2, "reason": "provider name",
                        "requested_by": "Eindhoven Engine"}}
_REOPENED = {"event_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()),
             "action": "controls.submission.reopened", "item_type": "submission",
             "item_id": "cmsub0000000000000000001",
             "details": {"next": "cmsub0000000000000000002", "version": 2, "reason": "a typo in an answer",
                         "requested_by": "the auditor"},
             "content": {"next": {"label": "Run", "status": "Draft", "answers": []}}}


@pytest.mark.parametrize("event, emitter", [(_AMENDED, "qualification"), (_REVISED, "platform"),
                                            (_REOPENED, "controls")], ids=lambda v: v if isinstance(v, str) else v["action"])
def test_a_correction_or_amendment_event_as_the_code_emits_it_has_no_problem(event, emitter):
    assert check(event, emitter=emitter) == []


def test_an_amendment_without_its_card_is_a_problem():
    assert "content_required" in check({**_AMENDED, "content": None}, emitter="qualification")


def _caused_by(action, app, method, path):
    return any(a == app and m == method and re.match(p, path) for a, m, p in REGISTRY[action].caused_by)


@pytest.mark.parametrize("page", ["/system/edit", "/qualify/new"])
def test_a_card_correction_is_caused_by_the_step_1_form_like_a_new_version(page):
    path = "/qualification/p/proj" + page
    for action in ("qualification.amended", "card_version.revised"):
        assert _caused_by(action, "qualification", "ACTION", path), action
    assert _caused_by("card_version.revised", "platform", "PATCH", "/api/projects/proj/system-versions/abc")


def test_saving_a_new_card_and_correcting_one_are_the_same_server_action():
    assert "qualification.amended" in REGISTRY["qualification.created"].same_action
    assert "qualification.created" in REGISTRY["qualification.amended"].same_action
