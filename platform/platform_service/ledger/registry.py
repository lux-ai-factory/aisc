"""The event registry: every event the ledger accepts, who may emit it, which witnessed
requests may cause it, who may act and which details it may carry.

Standard library only: the repo-level coverage test loads it without the platform's dependencies.

Cause paths are the **unstripped** gateway paths, matched from the start. A named group `item` binds
the event's `item_id` to the path; `project` names the project's place in it. `routes` names where
the code handles each action, for the coverage test; an action whose emitter is not written yet has
none.

The catalogue is hosted elsewhere and never passes this gateway, so its own events
belong in its own log; only the local installs (`plugin.installed`, `control.installed`) are here.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

#: Raised when the registry changes in a way an older platform can't read.
VERSION = 1


@dataclass(frozen=True)
class Action:
    name: str
    step: int
    emitters: tuple = ()
    item_type: str = ""
    caused_by: tuple = ()
    routes: tuple = ()
    actor_kinds: tuple = ("user",)
    details_keys: tuple = ()
    per_request: int | None = 1
    content_required: bool = False
    #: an empty content is still content (a save that removed every link), not a missing one
    empty_content: bool = False
    runs: tuple = ()
    run_window: timedelta = timedelta(hours=24)
    origin: str = "app"
    registry_version: int = VERSION
    #: other actions the SAME server action makes on another branch: an action id bound to
    #: one of them accepts the others too (a save that creates, or saves the next version)
    same_action: tuple = ()


#: Every app the gateway serves, and every app that serves routes inside the network.
GATEWAY_APPS = ("engine", "engine_webapp", "flower", "controls", "qualification", "control_objectives",
                "report_composer", "platform", "launcher", "pgadmin", "schema", "dashboard")
INTERNAL_APPS = ("engine_worker", "report_renderer", "qualification_agents",
                 "qualification_prefill", "qualification_ontology", "qualification_pdf")
KNOWN_APPS = GATEWAY_APPS + INTERNAL_APPS

#: How the witness finds the project of a request, per app, against the unstripped path.
APP_PROJECT_RULES = {
    "qualification": ("slug", r"^/qualification/p/(?P<project>[^/]+)(/|$)"),
    "controls": ("slug", r"^/controls/p/(?P<project>[^/]+)(/|$)"),
    "control_objectives": ("pid", r"^/control-objectives/p/(?P<project>[^/]+)(/|$)"),
    # its pages at /report-composer/p/<slug>, its API at /report-composer/api/p/<slug>
    "report_composer": ("slug", r"^/report-composer(?:/api)?/p/(?P<project>[^/]+)(/|$)"),
    "platform": ("slug", r"^/api/projects/(?P<project>[^/]+)(/|$)"),
    "launcher": ("slug", r"^/p/(?P<project>[^/]+)(/|$)"),
    "engine": ("header", "X-AISC-Project"),
    "dashboard": ("bridge", None),
    "engine_webapp": ("none", None),
    "flower": ("none", None),
    "pgadmin": ("none", None),
    "schema": ("none", None),
}

# Gateway path pieces, unstripped.
_P = r"[^/]+"
_LAUNCH = r"^/api/projects/(?P<project>[^/]+)"
_CO = r"^/control-objectives/p/(?P<project>[^/]+)"
_RC = r"^/report-composer(?:/api)?/p/(?P<project>[^/]+)"
_QU = r"^/qualification/p/(?P<project>[^/]+)"
_CT = r"^/controls/p/(?P<project>[^/]+)"
_EN = r"^/api/v1"
_DB = r"^/api/v1"


def _a(name, step, emitters, item_type, caused_by=(), **kw):
    return Action(name=name, step=step, emitters=tuple(emitters), item_type=item_type,
                  caused_by=tuple(caused_by), **kw)


def _co(method, tail):
    """A control-objectives route, served both as a page form and as its JSON API."""
    return ("control_objectives", method, _CO + r"/(api/)?" + tail + "$")


_ACTIONS = [
    # the ledger's own, and the witness's (origin platform: no app emits them)
    _a("request.witnessed", 0, (), "request", origin="platform", per_request=None),
    _a("request.unverified", 0, (), "request", origin="platform", per_request=None),
    _a("flower.request", 0, (), "request", origin="platform", per_request=None),
    _a("pgadmin.request", 0, (), "request", origin="platform", per_request=None),
    _a("ledger.rejected", 0, (), "event", origin="platform", actor_kinds=("system",), per_request=None,
       details_keys=("reason", "digest")),
    # a frozen content redacted on the operator's word (secret_cleanup.py), appended by the platform itself
    _a("ledger.content.redacted", 0, (), "ledger", origin="platform", actor_kinds=("system",), per_request=None,
       details_keys=("event_ids", "reason", "count")),
    _a("ledger.reanchored", 0, (), "ledger", origin="platform",
       caused_by=(("platform", "POST", r"^/api/ledger/reanchor$"),), details_keys=("old_head", "new_head", "project")),
    # browser-reported, through the beacon
    _a("page.opened", 0, ("platform",), "page", origin="browser", per_request=1, details_keys=("page",),
       caused_by=(("platform", "POST", r"^/api/ledger/beacon$"),)),
    _a("page.left", 0, ("platform",), "page", origin="browser", per_request=1,
       details_keys=("page", "unsaved_changes", "seconds"),
       caused_by=(("platform", "POST", r"^/api/ledger/beacon$"),)),
    # session and refusals (the platform records them)
    _a("session.signed_in", 0, ("platform",), "session", details_keys=("client",), per_request=None),
    _a("session.signed_out", 0, ("platform",), "session", details_keys=("client",), per_request=None),
    _a("access.refused", 0, ("platform",), "request", actor_kinds=("system",), per_request=None,
       details_keys=("status", "path", "role_needed")),
    # step 0: projects and Manage
    _a("project.created", 0, ("platform",), "project", caused_by=(("platform", "POST", r"^/api/projects$"),),
       details_keys=("name",)),
    _a("project.deleted", 0, ("platform",), "project",
       caused_by=(("platform", "DELETE", _LAUNCH + "$"),), details_keys=("members", "versions")),
    _a("member.added", 0, ("platform",), "member",
       caused_by=(("platform", "POST", _LAUNCH + "/members$"),), details_keys=("role",)),
    _a("member.role_changed", 0, ("platform",), "member",
       caused_by=(("platform", "PUT", _LAUNCH + r"/members/(?P<item>[^/]+)$"),),
       details_keys=("role_before", "role_after")),
    _a("member.removed", 0, ("platform",), "member",
       caused_by=(("platform", "DELETE", _LAUNCH + r"/members/(?P<item>[^/]+)$"),), details_keys=("role",)),
    # a card version is saved by the platform, on step 1's submit
    _a("card_version.created", 1, ("platform",), "card_version",
       caused_by=(("qualification", "ACTION", _QU + "/(system/edit|qualify/new)$"),     # the form's page
                  ("platform", "POST", _LAUNCH + "/system-versions$")),
       details_keys=("number", "name", "version", "provider")),
    _a("targets.synced", 0, ("platform",), "project",
       caused_by=(("qualification", "ACTION", _QU + "/(system/edit|qualify/new)$"),
                  ("platform", "POST", _LAUNCH + "/targets/sync$")), details_keys=("added", "renamed")),
    _a("llm.provider.saved", 0, ("platform",), "llm_provider",
       caused_by=(("platform", "PUT", _LAUNCH + r"/llm/providers/(?P<item>[^/]+)$"),),
       details_keys=("key", "base_url_before", "base_url_after")),
    _a("llm.provider.removed", 0, ("platform",), "llm_provider",
       caused_by=(("platform", "DELETE", _LAUNCH + r"/llm/providers/(?P<item>[^/]+)$"),)),
    _a("llm.choice.saved", 0, ("platform",), "llm_choice",
       caused_by=(("platform", "PUT", _LAUNCH + r"/llm/systems/(?P<item>[^/]+)$"),),
       details_keys=("provider_before", "provider_after", "model_before", "model_after")),
    _a("llm.choice.removed", 0, ("platform",), "llm_choice",
       caused_by=(("platform", "DELETE", _LAUNCH + r"/llm/systems/(?P<item>[^/]+)$"),)),
    _a("helper.model.saved", 0, ("platform",), "helper_model",
       caused_by=(("platform", "PUT", _LAUNCH + r"/helpers/(?P<item>[^/]+)$"),),
       details_keys=("key", "endpoint_before", "endpoint_after", "roles")),
    _a("helper.model.removed", 0, ("platform",), "helper_model",
       caused_by=(("platform", "DELETE", _LAUNCH + r"/helpers/(?P<item>[^/]+)$"),)),
    _a("helper.model.tested", 0, ("platform",), "helper_model",
       caused_by=(("platform", "POST", _LAUNCH + r"/helpers/(?P<item>[^/]+)/test$"),),
       details_keys=("ok", "status")),
    _a("connection.saved", 0, ("platform",), "connection",
       caused_by=(("platform", "PUT", _LAUNCH + r"/connections/(?P<item>[^/]+)$"),),
       details_keys=("changed", "secret")),
    _a("connection.deleted", 0, ("platform",), "connection",
       caused_by=(("platform", "DELETE", _LAUNCH + r"/connections/(?P<item>[^/]+)$"),)),
    _a("connection.tested", 0, ("platform",), "connection",
       caused_by=(("platform", "POST", _LAUNCH + r"/connections/(?P<item>[^/]+)/test$"),),
       details_keys=("result",)),
    _a("allowlist.host.allowed", 0, ("platform",), "allowed_host",
       caused_by=(("platform", "PUT", _LAUNCH + r"/allowed-hosts/(?P<item>[^/]+)$"),),
       details_keys=("note_before", "note_after")),
    _a("allowlist.host.removed", 0, ("platform",), "allowed_host",
       caused_by=(("platform", "DELETE", _LAUNCH + r"/allowed-hosts/(?P<item>[^/]+)$"),)),
    # step 1: qualify
    _a("question_set.created", 1, ("qualification",), "question_set",
       caused_by=(("qualification", "ACTION", _QU + r"/question-sets(/.*)?$"),
                  ("qualification", "ACTION", _QU + r"/questionnaires/import$")), details_keys=("version",),
       same_action=("question_set.version_created",),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/question-sets/actions.ts", "saveQuestionSet"), ("qualification", "apps/qualification/src/app/p/[project]/questionnaires/import/actions.ts", "importSelfContained"),)),
    _a("question_set.version_created", 1, ("qualification",), "question_set",
       caused_by=(("qualification", "ACTION", _QU + r"/question-sets(/.*)?$"),),
       same_action=("question_set.created", "questionnaire.created"),
       details_keys=("version", "added", "removed", "reworded"), content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/question-sets/actions.ts", "saveQuestionSet"),)),
    _a("question_set.retired", 1, ("qualification",), "question_set",
       caused_by=(("qualification", "ACTION", _QU + r"/question-sets(/.*)?$"),),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/question-sets/actions.ts", "retireQuestionSet"),)),
    _a("questionnaire.created", 1, ("qualification",), "questionnaire",
       caused_by=(("qualification", "ACTION", _QU + r"/questionnaires(/.*)?$"),
                  ("qualification", "ACTION", _QU + r"/question-sets(/.*)?$")), details_keys=("version",),
       same_action=("questionnaire.version_created", "question_set.version_created"),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/questionnaires/actions.ts", "saveQuestionnaire"), ("qualification", "apps/qualification/src/app/p/[project]/questionnaires/actions.ts", "useQuestionnaireOnce"),)),
    _a("questionnaire.version_created", 1, ("qualification",), "questionnaire",
       caused_by=(("qualification", "ACTION", _QU + r"/questionnaires(/.*)?$"),),
       same_action=("questionnaire.created",),
       details_keys=("version", "items", "blocks"), content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/questionnaires/actions.ts", "saveQuestionnaire"),)),
    _a("questionnaire.retired", 1, ("qualification",), "questionnaire",
       caused_by=(("qualification", "ACTION", _QU + r"/questionnaires(/.*)?$"),),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/questionnaires/actions.ts", "retireQuestionnaire"),)),
    _a("qualification.opened", 1, ("qualification",), "qualification", per_request=None,
       caused_by=(("qualification", "GET", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("version", "read_only")),
    _a("qualification.created", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + "/(system/edit|qualify/new)$"),),     # the form's page
       # the next version's review: what it took from the card before it (content.review names the nodes)
       details_keys=("questionnaire_version", "risks", "components", "review_from_version",
                     "corrections_carried", "corrections_left", "draft", "review_failed"), content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/new/actions.ts", "submitQualification"),)),
    _a("card.node_corrected", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("node",), content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/ontology-actions.ts", "patchOntologyNode"),)),
    _a("card.corrections_discarded", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/ontology-actions.ts", "resetOntology"),)),
    # No longer emitted: the card page links no engine components any more. Kept so the events
    # already in a project's log still read and verify.
    _a("card.component_linked", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("component", "property")),
    _a("card.component_unlinked", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("component", "property")),
    _a("card.extracted_replaced_by_user", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "PUT", _QU + r"/api/qualifications/(?P<item>[^/]+)/extracted$"),),
       content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/api/qualifications/[id]/extracted/route.ts", "PUT"),)),
    _a("card.ai_refinement_requested", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       runs=("agent.run_started", "agent.run_finished", "agent.run_failed", "ai.llm_call",
             "card.augmented_by_ai"),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/fill-actions.ts", "rerunFill"),)),
    _a("agent.run_started", 1, ("qualification_agents",), "agent_run", actor_kinds=("ai",), per_request=None,
       details_keys=("model",)),
    _a("agent.run_finished", 1, ("qualification_agents",), "agent_run", actor_kinds=("ai",), per_request=None,
       details_keys=("rounds", "calls")),
    _a("agent.run_failed", 1, ("qualification_agents",), "agent_run", actor_kinds=("ai",), per_request=None,
       details_keys=("error",)),
    _a("ai.llm_call", 1, ("qualification_agents", "control_objectives"), "llm_call", actor_kinds=("ai",),
       per_request=None, details_keys=("purpose", "property", "round", "latency_ms")),
    _a("card.augmented_by_ai", 1, ("qualification_agents", "qualification"), "qualification", actor_kinds=("ai",),
       per_request=None, details_keys=("flagged",)),
    _a("card.pdf_downloaded", 1, ("qualification",), "qualification", per_request=None,
       caused_by=(("qualification", "GET",
                   _QU + r"/api/qualifications/(?P<item>[^/]+)/(ai-card|system-card)\.pdf$"),),
       details_keys=("format",),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/api/qualifications/[id]/ai-card.pdf/route.ts", "GET"),)),
    # step 2: control objectives
    _a("assessment.started", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", "projects"),),
       # carried_from and carried_risks: the previous version's assessment and how many of its risks came along
       details_keys=("card_version", "risks", "profile_version", "carried_from", "carried_risks"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "start_assessment_form"),)),
    _a("assessment.deleted", 2, ("control_objectives",), "assessment",
       caused_by=(("control_objectives", "DELETE", _CO + r"/api/projects/(?P<item>[^/]+)$"),),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "delete_project"),)),
    # the card of the assessment's version changed since it started, and the assessor took the change in;
    # each risk whose rating, comment or mapping changed with it is written as a person's change would be
    _a("assessment.card_updated", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+)/card"),),
       details_keys=("card_version", "digest_before", "digest_after", "risks", "carried_risks"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "card_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "update_card"),)),
    # a risk's rating, its comment and its mapping are three items, each `<assessment>/risks/<risk>`:
    # risk ids repeat across a project's card versions
    _a("risk.rated", 2, ("control_objectives",), "risk_rating", per_request=None,
       caused_by=(_co("POST", rf"projects/{_P}/(ratings|severity|card)"),),
       details_keys=("rating", "band"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "rate_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "rate"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "card_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "update_card"),)),
    _a("risk.rating_comment.set", 2, ("control_objectives",), "risk_comment", per_request=None,
       caused_by=(_co("POST", rf"projects/{_P}/(severity|severity-comments|card)"),),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "comment_severities"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "card_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "update_card"),)),
    _a("ai.mapping.requested", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+)/map"),),
       runs=("ai.mapping.completed", "ai.mapping.failed", "ai.llm_call"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_risks"),)),
    _a("ai.mapping.completed", 2, ("control_objectives",), "assessment", actor_kinds=("ai",),
       per_request=None, details_keys=("skill", "profile_version", "attempts", "error", "failed_risks"),
       content_required=True),
    _a("ai.mapping.failed", 2, ("control_objectives",), "assessment", actor_kinds=("ai",), per_request=None,
       details_keys=("error", "attempts", "failed_risks")),
    _a("mapping.risk.edited", 2, ("control_objectives",), "risk_mapping", per_request=None,   # a card update: several
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+/risks/[^/]+)/mapping"), _co("POST", rf"projects/{_P}/card")),
       details_keys=("added", "removed"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_by_hand_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_by_hand"),
               ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "card_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "update_card"))),
    _a("objective.key.set", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+)/(key|keys/reset|card)"),), details_keys=("added", "removed"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "key_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "set_keys"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "reset_keys_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "reset_keys"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "card_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "update_card"),)),
    _a("assessment.profile.switched", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+)/profile"),),
       details_keys=("version_before", "version_after", "dropped"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "profile_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "use_profile"),)),
    _a("objective_set.created", 2, ("control_objectives",), "objective_set",
       caused_by=(_co("POST", "sets"),), details_keys=("code",),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "make_set_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "make_set"),)),
    _a("objective_set.published", 2, ("control_objectives",), "objective_set",
       caused_by=(_co("POST", r"sets/(?P<item>[^/]+)/publish"),), details_keys=("version",),
       content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "publish_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "publish"),)),
    _a("objective.added", 2, ("control_objectives",), "objective",
       caused_by=(_co("POST", rf"sets/{_P}/objectives"),), details_keys=("set",), content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "add_objective_form"),
               ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "add_objective"))),
    _a("objective.edited", 2, ("control_objectives",), "objective",
       caused_by=(_co("POST", r"sets/(?P<item>[^/]+/objectives/[^/]+)"),
                  ("control_objectives", "PUT", _CO + r"/api/sets/(?P<item>[^/]+/objectives/[^/]+)$")),
       details_keys=("set",), content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "edit_objective_form"),
               ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "edit_objective"))),
    _a("objective.retired", 2, ("control_objectives",), "objective",
       caused_by=(_co("POST", r"sets/(?P<item>[^/]+/objectives/[^/]+)/retire"),), details_keys=("set",),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "retire_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "retire"))),
    _a("objective.restored", 2, ("control_objectives",), "objective",
       caused_by=(_co("POST", r"sets/(?P<item>[^/]+/objectives/[^/]+)/restore"),), details_keys=("set",),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "retire_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "retire"))),
    _a("objective_set.deleted", 2, ("control_objectives",), "objective_set",
       caused_by=(_co("POST", r"sets/(?P<item>[^/]+)/delete"),
                  ("control_objectives", "DELETE", _CO + r"/api/sets/(?P<item>[^/]+)$")), content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "delete_set_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "delete_set"))),
    _a("objective_profile.created", 2, ("control_objectives",), "objective_profile",
       caused_by=(_co("POST", "profiles"),),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "make_profile_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "make_profile"),)),
    _a("objective_profile.version_saved", 2, ("control_objectives",), "objective_profile",
       caused_by=(_co("POST", r"profiles/(?P<item>[^/]+)(/versions|/newer)?"),), details_keys=("version", "dropped"),
       content_required=True, same_action=("objective_profile.edited",),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "save_profile_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "save_profile"),
               ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "newer_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "take_newer"))),
    # a save that changed only the profile's name or description: no new version
    _a("objective_profile.edited", 2, ("control_objectives",), "objective_profile",
       caused_by=(_co("POST", r"profiles/(?P<item>[^/]+)(/versions)?"),), same_action=("objective_profile.version_saved",),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "save_profile_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "save_profile"))),
    # step 3: local installs
    _a("plugin.installed", 3, ("engine",), "plugin",
       caused_by=(("engine", "POST", _EN + r"/plugins/?$"),), details_keys=("package", "version", "reused"),
       routes=(("engine", "apps/backend/aisc_backend/routers/plugin.py", "create_plugins"),)),
    _a("plugin.refreshed", 3, ("engine",), "plugin",
       caused_by=(("engine", "POST", _EN + r"/plugins/refresh$"),), details_keys=("package", "version"),
       routes=(("engine", "apps/backend/aisc_backend/routers/plugin.py", "refresh_plugins"),)),
    _a("plugin.removed", 3, ("engine",), "plugin",
       caused_by=(("engine", "DELETE", _EN + r"/plugins/?$"),), details_keys=("package", "version"),
       routes=(("engine", "apps/backend/aisc_backend/routers/plugin.py", "delete_plugin"),)),
    _a("control.installed", 3, ("controls",), "checklist",
       caused_by=(("controls", "ACTION", _CT + r"/install$"),
                  ("controls", "ACTION", r"^/controls/install$"),
                  ("controls", "POST", r"^/controls/api/install$")), details_keys=("package", "questions"),
       # the catalogue's Install button (api/install) and the /install page; the controls app has no
       # catalogue page of its own
       routes=(("controls", "apps/controls/src/app/p/[project]/install/actions.ts", "installFromCatalogue"),
               ("controls", "apps/controls/src/app/api/install/route.ts", "POST"))),
    # step 4: evidence, engine, controls
    _a("evidence.links.saved", 4, ("platform",), "evidence",
       caused_by=(("platform", "PUT", _LAUNCH + "/evidence/links$"),),
       details_keys=("added", "removed", "carried", "notes_changed"), content_required=True, empty_content=True),
    _a("evidence.map.reviewed", 4, ("platform",), "evidence",
       caused_by=(("platform", "POST", _LAUNCH + "/evidence/review$"),), details_keys=("links",)),
    _a("engine.evaluation.run_requested", 4, ("engine",), "evaluation",
       caused_by=(("engine", "POST", _EN + r"/evaluations/task$"),), details_keys=("plugins", "local_models"),
       runs=("engine.evaluation.status_changed", "engine.evaluation.plugin_status_changed", "engine.measures.recorded",
             "engine.artifact.uploaded", "engine.evaluation.input_marked_local"),
       routes=(("engine", "apps/backend/aisc_backend/routers/evaluation.py", "create_evaluation_task"),)),
    # the worker's: written by the engine when the worker reports, citing the run its evaluation started
    _a("engine.evaluation.status_changed", 4, ("engine",), "evaluation", actor_kinds=("worker",),
       per_request=None, details_keys=("status_before", "status_after"),
       routes=(("engine", "apps/backend/aisc_backend/routers/internal.py", "update_evaluation_status"), ("engine", "apps/backend/aisc_backend/routers/internal.py", "mark_plugin_failed"))),
    _a("engine.evaluation.plugin_status_changed", 4, ("engine",), "evaluation", actor_kinds=("worker",),
       per_request=None, details_keys=("plugin", "status_before", "status_after"),
       routes=(("engine", "apps/backend/aisc_backend/routers/internal.py", "update_plugin_timestamp"), ("engine", "apps/backend/aisc_backend/routers/internal.py", "mark_plugin_failed"))),
    _a("engine.measures.recorded", 4, ("engine",), "evaluation", actor_kinds=("worker",), per_request=None,
       details_keys=("count",), routes=(("engine", "apps/backend/aisc_backend/routers/internal.py", "create_evaluation_measures"),)),
    _a("engine.artifact.uploaded", 4, ("engine",), "artifact", actor_kinds=("worker",), per_request=None,
       details_keys=("size",), routes=(("engine", "apps/backend/aisc_backend/routers/internal.py", "upload_evaluation_artifact"),)),
    # the local model file a run was on: its name and hash, which keep the run apart from the AI card's
    _a("engine.evaluation.input_marked_local", 4, ("engine",), "evaluation", actor_kinds=("worker",), per_request=None,
       details_keys=("input", "file", "sha256"),
       routes=(("engine", "apps/backend/aisc_backend/routers/internal.py", "store_evaluation_input_value"),)),
    _a("engine.plugin.configured", 4, ("engine",), "plugin",
       caused_by=(("engine", "POST", _EN + r"/plugins/(?P<item>[^/]+)/config$"),
                  ("engine", "POST", _EN + r"/plugins/(?P<item>[^/]+)/configs/[^/]+/restore$")),
       content_required=True,
       routes=(("engine", "apps/backend/aisc_backend/routers/plugin.py", "update_plugin_config_state"), ("engine", "apps/backend/aisc_backend/routers/plugin.py", "restore_plugin_config"))),
    _a("engine.plugin.toggled", 4, ("engine",), "plugin",
       caused_by=(("engine", "PATCH", _EN + r"/plugins/(?P<item>[^/]+)/enabled/?$"),), details_keys=("enabled",),
       routes=(("engine", "apps/backend/aisc_backend/routers/plugin.py", "update_plugin_enabled"),)),
    # the engine's projects, components, settings and secrets, written by its signals (signals/ledger.py)
    # whichever route saved them; a setting or secret names its key, never its value
    _a("engine.project.created", 4, ("engine",), "engine_project",
       caused_by=(("engine", "POST", _EN + r"/projects/for-platform/[^/]+$"), ("engine", "POST", _EN + r"/projects$")),
       routes=(("engine", "apps/backend/aisc_backend/routers/platform_project.py", "project_for_platform"), ("engine", "apps/backend/aisc_backend/routers/project.py", "create_project"))),
    _a("engine.project.updated", 4, ("engine",), "engine_project",
       caused_by=(("engine", "PATCH", _EN + r"/projects/(?P<item>[^/]+)$"),), details_keys=("changed",),
       routes=(("engine", "apps/backend/aisc_backend/routers/project.py", "update_project"),)),
    _a("engine.component.created", 4, ("engine",), "component",
       caused_by=(("engine", "POST", _EN + r"/projects/[^/]+/(components|datasets|models)$"),),
       details_keys=("component_type",),
       routes=(("engine", "apps/backend/aisc_backend/routers/project.py", "create_project_component"), ("engine", "apps/backend/aisc_backend/routers/project.py", "create_project_dataset"),
               ("engine", "apps/backend/aisc_backend/routers/project.py", "create_project_model"))),
    _a("engine.component.updated", 4, ("engine",), "component",
       caused_by=(("engine", "PATCH", _EN + r"/components/(?P<item>[^/]+)$"),), details_keys=("changed",),
       routes=(("engine", "apps/backend/aisc_backend/routers/component.py", "update_component"),)),
    _a("engine.component.file_uploaded", 4, ("engine",), "component",
       caused_by=(("engine", "PUT", _EN + r"/components/(?P<item>[^/]+)/data$"),), details_keys=("size",),
       routes=(("engine", "apps/backend/aisc_backend/routers/component.py", "upload_component_file"),)),
    _a("engine.component.deleted", 4, ("engine",), "component",
       caused_by=(("engine", "DELETE", _EN + r"/components/(?P<item>[^/]+)$"),), details_keys=("component_type",),
       routes=(("engine", "apps/backend/aisc_backend/routers/component.py", "delete_component"),)),
    _a("engine.setting.created", 4, ("engine",), "setting",
       caused_by=(("engine", "POST", _EN + r"/project/settings/[^/]+$"),), details_keys=("key",),
       routes=(("engine", "apps/backend/aisc_backend/routers/project_config.py", "create_project_config"),)),
    _a("engine.setting.updated", 4, ("engine",), "setting",
       caused_by=(("engine", "PATCH", _EN + r"/project/settings/[^/]+/(?P<item>[^/]+)$"),), details_keys=("key", "changed"),
       routes=(("engine", "apps/backend/aisc_backend/routers/project_config.py", "update_project_config"),)),
    _a("engine.setting.deleted", 4, ("engine",), "setting",
       caused_by=(("engine", "DELETE", _EN + r"/project/settings/[^/]+/(?P<item>[^/]+)$"),), details_keys=("key",),
       routes=(("engine", "apps/backend/aisc_backend/routers/project_config.py", "delete_project_config"),)),
    # a plugin configuration save keeps each key field as a project secret, one event per new or changed key,
    # at most 16 per save (the backend refuses a configuration with more key fields)
    _a("engine.secret.created", 4, ("engine",), "secret", per_request=16,
       caused_by=(("engine", "POST", _EN + r"/project/settings/[^/]+$"), ("engine", "POST", _EN + r"/plugins/[^/]+/config$")),
       details_keys=("key",),
       routes=(("engine", "apps/backend/aisc_backend/routers/project_config.py", "create_project_config"),
               ("engine", "apps/backend/aisc_backend/routers/plugin.py", "update_plugin_config_state"))),
    _a("engine.secret.updated", 4, ("engine",), "secret", per_request=16,
       caused_by=(("engine", "PATCH", _EN + r"/project/settings/[^/]+/(?P<item>[^/]+)$"), ("engine", "POST", _EN + r"/plugins/[^/]+/config$")),
       details_keys=("key", "changed"),
       routes=(("engine", "apps/backend/aisc_backend/routers/project_config.py", "update_project_config"),
               ("engine", "apps/backend/aisc_backend/routers/plugin.py", "update_plugin_config_state"))),
    _a("engine.secret.deleted", 4, ("engine",), "secret",
       caused_by=(("engine", "DELETE", _EN + r"/project/settings/[^/]+/(?P<item>[^/]+)$"),), details_keys=("key",),
       routes=(("engine", "apps/backend/aisc_backend/routers/project_config.py", "delete_project_config"),)),
    _a("controls.submission.created", 4, ("controls",), "submission",
       caused_by=(("controls", "ACTION", _CT + rf"/checklists/{_P}/fill$"),), details_keys=("checklist",),
       content_required=True, routes=(("controls", "apps/controls/src/app/p/[project]/checklists/[id]/fill/actions.ts", "submitForm"),)),
    _a("controls.submission.draft_saved", 4, ("controls",), "submission", per_request=None,
       caused_by=(("controls", "ACTION", _CT + r"/submissions/(?P<item>[^/]+)$"),), content_required=True,
       same_action=("controls.submission.closed",),
       routes=(("controls", "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "saveDraft"),)),
    _a("controls.submission.closed", 4, ("controls",), "submission",
       caused_by=(("controls", "ACTION", _CT + r"/submissions/(?P<item>[^/]+)$"),),
       details_keys=("score",), content_required=True, same_action=("controls.submission.draft_saved",)),
    _a("controls.submission.reopened", 4, ("controls",), "submission",
       caused_by=(("controls", "ACTION", _CT + r"/submissions/(?P<item>[^/]+)$"),), details_keys=("next", "version"),
       routes=(("controls", "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "reopenForAmendment"),)),
    _a("controls.submission.archived", 4, ("controls",), "submission",
       caused_by=(("controls", "ACTION", _CT + r"/submissions/(?P<item>[^/]+)$"),),
       routes=(("controls", "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "archiveSubmission"),)),
    _a("controls.submission.restored", 4, ("controls",), "submission",
       caused_by=(("controls", "ACTION", _CT + r"/submissions/(?P<item>[^/]+)$"),),
       routes=(("controls", "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "restoreSubmission"),)),
    _a("controls.submission.discarded", 4, ("controls",), "submission",
       caused_by=(("controls", "ACTION", _CT + r"/submissions/(?P<item>[^/]+)$"),), details_keys=("checklist",),
       routes=(("controls", "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "discardDraft"),)),
    _a("controls.checklist.questions_revised", 4, ("controls",), "checklist",
       caused_by=(("controls", "ACTION", _CT + r"/checklists/(?P<item>[^/]+)/review$"),),
       details_keys=("version", "questions", "added", "reworded", "removed", "moved", "answers_removed",
                     "closed_answers_removed"), content_required=True,
       same_action=("controls.checklist.edited", "controls.submission.answers_removed"),
       routes=(("controls", "apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts", "saveReviewedQuestions"),)),
    # a review that removed questions: each submission that lost answers, before (with them) and after (without)
    _a("controls.submission.answers_removed", 4, ("controls",), "submission", per_request=None,
       caused_by=(("controls", "ACTION", _CT + r"/checklists/[^/]+/review$"),),   # the path names the checklist
       details_keys=("checklist", "version", "answers_removed"),
       same_action=("controls.checklist.questions_revised", "controls.checklist.edited"),
       routes=(("controls", "apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts", "saveReviewedQuestions"),)),
    # the same review when its questions stay as they are: only the checklist's own fields
    _a("controls.checklist.edited", 4, ("controls",), "checklist",
       caused_by=(("controls", "ACTION", _CT + r"/checklists/(?P<item>[^/]+)/review$"),),
       same_action=("controls.checklist.questions_revised",),
       routes=(("controls", "apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts", "saveReviewedQuestions"),)),
    # step 5: dashboard
    # (page views are best effort: dashboard.viewed is declared, not yet sent)
    _a("dashboard.viewed", 5, ("dashboard",), "dashboard", per_request=None,
       caused_by=(("dashboard", "GET", r"^/superset/dashboard/(?P<item>[^/]+)/?$"),)),
    # the dashboard queues these in Superset's database with the change (its own outbox) and posts them
    # through the internal route; its slug, aisc-<pid hex>, names the project
    _a("dashboard.comment.created", 5, ("dashboard",), "comment",
       caused_by=(("dashboard", "POST", _DB + r"/aisc_comment/?$"),), details_keys=("dashboard", "chart"),
       content_required=True, routes=(("dashboard", "apps/results-dashboard/aisc_ext/comments/api.py", "post"),)),
    _a("dashboard.comment.deleted", 5, ("dashboard",), "comment",
       caused_by=(("dashboard", "DELETE", _DB + r"/aisc_comment/(?P<item>[0-9]+)$"),), details_keys=("dashboard",),
       content_required=True, routes=(("dashboard", "apps/results-dashboard/aisc_ext/comments/api.py", "delete"),)),
    _a("dashboard.review.requested", 5, ("dashboard",), "review_request",
       caused_by=(("dashboard", "POST", _DB + r"/aisc_review_request/?$"),), details_keys=("assignee",),
       content_required=True, routes=(("dashboard", "apps/results-dashboard/aisc_ext/reviews/api.py", "post"),)),
    _a("dashboard.review.resolved", 5, ("dashboard",), "review_request",
       caused_by=(("dashboard", "PATCH", _DB + r"/aisc_review_request/(?P<item>[0-9]+)$"),),
       details_keys=("status_before", "status_after"), routes=(("dashboard", "apps/results-dashboard/aisc_ext/reviews/api.py", "patch"),)),
    # step 6: the report
    # a built-in layout gets its record in the project the first time a report is made from it
    _a("report.layout.created", 6, ("report_composer",), "layout",
       caused_by=(("report_composer", "POST", _RC + "/layouts$"),
                  ("report_composer", "POST", _RC + rf"/layouts/{_P}/duplicate$"),
                  ("report_composer", "POST", _RC + rf"/layouts/{_P}/(reports|generate|download-report)$")),
       details_keys=("from", "builtin_id"), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "post_layout"), ("report_composer", "apps/report-composer/report_composer/api.py", "duplicate_layout"))),
    # and is brought in step with the built-in when a report is made from it again
    _a("report.layout.updated", 6, ("report_composer",), "layout",
       caused_by=(("report_composer", "PUT", _RC + r"/layouts/(?P<item>[^/]+)$"),
                  ("report_composer", "POST", _RC + rf"/layouts/{_P}/(reports|generate|download-report)$")),
       details_keys=("revision", "from"), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "put_layout"),)),
    # a deleted layout is hidden and keeps its reports: the event names them, content `reports`
    _a("report.layout.deleted", 6, ("report_composer",), "layout",
       caused_by=(("report_composer", "DELETE", _RC + r"/layouts/(?P<item>[^/]+)$"),),
       details_keys=("reports",), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "delete_layout"),)),
    # a template's delete takes it from each layout drawn in it: that layout's next revision
    _a("report.layout.template_removed", 6, ("report_composer",), "layout", per_request=None,
       caused_by=(("report_composer", "DELETE", _RC + r"/templates/[^/]+$"),), details_keys=("revision", "template"),
       content_required=True, routes=(("report_composer", "apps/report-composer/report_composer/api.py",
                                       "delete_template"),)),
    _a("report.template.created", 6, ("report_composer",), "template",
       caused_by=(("report_composer", "POST", _RC + r"/templates(/import)?$"),),
       details_keys=("from",), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "post_template"), ("report_composer", "apps/report-composer/report_composer/api.py", "import_template"))),
    _a("report.template.updated", 6, ("report_composer",), "template",
       caused_by=(("report_composer", "PUT", _RC + r"/templates/(?P<item>[^/]+)$"),), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "put_template"),)),
    _a("report.template.deleted", 6, ("report_composer",), "template",
       caused_by=(("report_composer", "DELETE", _RC + r"/templates/(?P<item>[^/]+)$"),), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "delete_template"),)),
    # the anchor it prints (`ledger_head`, the seq; the entry's digest in content) and its document's sha256,
    # so the PDF and an export prove each other offline (verify-ledger-export.py --anchor, --document)
    _a("report.generated", 6, ("report_composer",), "report",
       caused_by=(("report_composer", "POST", _RC + rf"/layouts/{_P}/(reports|generate|download-report)$"),),
       details_keys=("card_version", "ledger_head", "blocks", "document_sha256", "format"), content_required=True,
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "post_report"),
               ("report_composer", "apps/report-composer/report_composer/pages.py", "generate_submit"),
               ("report_composer", "apps/report-composer/report_composer/pages.py", "download_report"))),
    _a("report.failed", 6, ("report_composer",), "report",
       caused_by=(("report_composer", "POST", _RC + rf"/layouts/{_P}/(reports|generate|download-report)$"),),
       details_keys=("error", "format"),
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "post_report"),
               ("report_composer", "apps/report-composer/report_composer/pages.py", "generate_submit"),
               ("report_composer", "apps/report-composer/report_composer/pages.py", "download_report"))),
    # Download report on the layout's page generates the report and serves it in the same request
    _a("report.downloaded", 6, ("report_composer",), "report", per_request=None,
       caused_by=(("report_composer", "GET", _RC + r"/reports/(?P<item>[^/]+)/(pdf|download)$"),
                  ("report_composer", "POST", _RC + rf"/layouts/{_P}/download-report$")),
       details_keys=("document_sha256", "format"),
       routes=(("report_composer", "apps/report-composer/report_composer/api.py", "get_pdf"), ("report_composer", "apps/report-composer/report_composer/api.py", "download"))),
]

REGISTRY: dict[str, Action] = {a.name: a for a in _ACTIONS}

# What a check looks for.
_EVENT_FIELDS = ("event_id", "action", "item_type", "item_id")
_ACTOR_KEYS = frozenset({"actor_sub", "actor_name", "actor_kind", "actor_ref", "user", "subject", "created_by",
                         "updated_by", "on_behalf_of", "on_behalf_of_ref", "on_behalf_of_sub", "username"})
_PLATFORM_ACTOR_FIELDS = ("actor_sub", "actor_name", "actor_kind", "actor_ref", "on_behalf_of_ref",
                          "on_behalf_of_sub", "source_app", "verified")
_PLATFORM_FIELDS = ("content_sha256", "before_sha256", "after_sha256", "recorded_at", "seq")
# A secret an event must not carry. A `Bearer`, `Basic` or `Token` value counts only when it looks like a
# credential: 16 characters or more of the base64, hex and URL-safe alphabets, the same rule as
# `config_secrets.CREDENTIAL` ("the bearer of bad news" and "a token of thanks" are prose, not secrets).
_SECRET = re.compile(r"(?i)\b(?:bearer|basic|token)\s+[A-Za-z0-9+/=_.~-]{16,}|\bsk-[A-Za-z0-9_-]{16,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*")


def check(event: dict, emitter: str | None = None) -> list[str]:
    """The problems of one event as `emitter` sent it; empty means it may be relayed."""
    problems = [f"missing:{field}" for field in _EVENT_FIELDS if not event.get(field)]
    name = event.get("action")
    action = REGISTRY.get(name) if isinstance(name, str) else None
    if name and not isinstance(name, str):
        problems.append("unknown_action")
    details = event.get("details") or {}
    if not isinstance(details, dict):
        return problems + ["details_not_object"]
    if event.get("content") is not None and not isinstance(event["content"], (dict, list)):
        problems.append("content_not_object")
    if isinstance(name, str) and name and action is None:
        problems.append("unknown_action")
    if action is not None and emitter is not None and emitter not in action.emitters:
        problems.append("emitter")
    if any(key in _ACTOR_KEYS for key in details) or any(field in event for field in _PLATFORM_ACTOR_FIELDS):
        problems.append("actor_supplied")
    problems += [f"platform_field:{field}" for field in _PLATFORM_FIELDS if field in event]
    if action is not None:
        problems += [f"details_key:{key}" for key in details
                     if key not in action.details_keys and key not in _ACTOR_KEYS]
        content = event.get("content")
        if action.content_required and (content is None if action.empty_content else not content):
            problems.append("content_required")
    problems += [f"secret_in:{key}" for key, value in details.items() if _holds_secret(value)]
    for field in ("content", "before", "after"):                      # states too
        if _holds_secret(event.get(field)):
            problems.append(f"secret_in:{field}")
    return problems


def _holds_secret(value) -> bool:
    if isinstance(value, str):
        return _SECRET.search(value) is not None
    if isinstance(value, dict):
        return any(_holds_secret(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_holds_secret(v) for v in value)
    return False


@contextmanager
def override(actions: dict):
    """Tests only: merge `actions` over the real registry, and restore it afterwards.
    The dict is changed in place, so every module that imported REGISTRY sees the same entries."""
    saved = dict(REGISTRY)
    REGISTRY.update(actions)
    try:
        yield REGISTRY
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)
