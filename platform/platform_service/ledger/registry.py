"""The event registry (spec 4.1, 6.1): every event the ledger accepts, who may emit it, which witnessed
requests may cause it, who may act and which details it may carry.

Standard library only: the repo-level coverage test loads it without the platform's dependencies.

Cause paths are the **unstripped** gateway paths (06-spike.md G1), matched from the start. A named
group `item` binds the event's `item_id` to the path; `project` names the project's place in it.
`routes` (where the code handles each action, for the coverage test) are filled in by each app's
phase, when its emitter is written.

The catalogue is hosted elsewhere and never passes this gateway (spec 3.1, R1.10), so its own events
belong in its own log; only the local installs (`plugin.installed`, `control.installed`) are here.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

#: Raised when the registry changes in a way an older platform can't read (spec R2.12).
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
    runs: tuple = ()
    run_window: timedelta = timedelta(hours=24)
    origin: str = "app"
    registry_version: int = VERSION
    #: other actions the SAME server action makes on another branch (spec 4.5): an action id bound to
    #: one of them accepts the others too (a save that creates, or saves the next version)
    same_action: tuple = ()


#: Every app the gateway serves, and every app that serves routes inside the network.
GATEWAY_APPS = ("engine", "engine_webapp", "flower", "controls", "qualification", "control_objectives",
                "report_composer", "platform", "launcher", "pgadmin", "schema", "dashboard")
INTERNAL_APPS = ("engine_worker", "connectors", "report_renderer", "qualification_agents",
                 "qualification_prefill", "qualification_ontology", "qualification_llm", "qualification_pdf")
KNOWN_APPS = GATEWAY_APPS + INTERNAL_APPS

#: How the witness finds the project of a request, per app (spec 3.4), against the unstripped path.
APP_PROJECT_RULES = {
    "qualification": ("slug", r"^/qualification/p/(?P<project>[^/]+)(/|$)"),
    "controls": ("slug", r"^/controls/p/(?P<project>[^/]+)(/|$)"),
    "control_objectives": ("pid", r"^/control-objectives/p/(?P<project>[^/]+)(/|$)"),
    "report_composer": ("slug", r"^/report-composer/p/(?P<project>[^/]+)(/|$)"),
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
_RC = r"^/report-composer/p/(?P<project>[^/]+)"
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
    # --- the ledger's own, and the witness's (origin platform: no app emits them) -------------------
    _a("request.witnessed", 0, (), "request", origin="platform", per_request=None),
    _a("request.unverified", 0, (), "request", origin="platform", per_request=None),
    _a("flower.request", 0, (), "request", origin="platform", per_request=None),
    _a("pgadmin.request", 0, (), "request", origin="platform", per_request=None),
    _a("ledger.rejected", 0, (), "event", origin="platform", actor_kinds=("system",), per_request=None,
       details_keys=("reason", "digest")),
    _a("ledger.reanchored", 0, (), "ledger", origin="platform",
       caused_by=(("platform", "POST", r"^/api/ledger/reanchor$"),), details_keys=("old_head", "new_head", "project")),
    # --- browser-reported, through the beacon (spec 3.5) --------------------------------------------
    _a("page.opened", 0, ("platform",), "page", origin="browser", per_request=1, details_keys=("page",),
       caused_by=(("platform", "POST", r"^/api/ledger/beacon$"),)),
    _a("page.left", 0, ("platform",), "page", origin="browser", per_request=1,
       details_keys=("page", "unsaved_changes", "seconds"),
       caused_by=(("platform", "POST", r"^/api/ledger/beacon$"),)),
    # --- session and refusals (the platform records them) ---------------------------------------------
    _a("session.signed_in", 0, ("platform",), "session", details_keys=("client",), per_request=None),
    _a("session.signed_out", 0, ("platform",), "session", details_keys=("client",), per_request=None),
    _a("access.refused", 0, ("platform",), "request", actor_kinds=("system",), per_request=None,
       details_keys=("status", "path", "role_needed")),
    # --- step 0: projects and Manage ---------------------------------------------------------------
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
    # a card version is saved by the platform, on step 1's submit (spec 4.3)
    _a("card_version.created", 1, ("platform",), "card_version",
       caused_by=(("qualification", "ACTION", _QU + "/(system/edit|qualify/new)$"),     # the form's page (B1)
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
    _a("connection.saved", 0, ("platform",), "connection",
       caused_by=(("platform", "PUT", _LAUNCH + r"/connections/(?P<item>[^/]+)$"),
                  ("platform", "POST", _LAUNCH + r"/connections/(?P<item>[^/]+)/link$")),
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
    # --- step 1: qualify ---------------------------------------------------------------------------
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
       caused_by=(("qualification", "ACTION", _QU + "/(system/edit|qualify/new)$"),),     # the form's page (B1)
       details_keys=("questionnaire_version", "risks", "components"), content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/new/actions.ts", "submitQualification"),)),
    _a("card.node_corrected", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("node",), content_required=True,
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/ontology-actions.ts", "patchOntologyNode"),)),
    _a("card.corrections_discarded", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/ontology-actions.ts", "resetOntology"),)),
    _a("card.component_linked", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("component", "property"),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/component-actions.ts", "linkComponent"),)),
    _a("card.component_unlinked", 1, ("qualification",), "qualification",
       caused_by=(("qualification", "ACTION", _QU + r"/qualify/(?P<item>[^/]+)$"),),
       details_keys=("component", "property"),
       routes=(("qualification", "apps/qualification/src/app/p/[project]/qualify/[id]/component-actions.ts", "unlinkComponent"),)),
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
    # --- step 2: control objectives ----------------------------------------------------------------
    _a("assessment.started", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", "projects"),), details_keys=("card_version", "risks"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "start_assessment_form"),)),
    _a("assessment.deleted", 2, ("control_objectives",), "assessment",
       caused_by=(("control_objectives", "DELETE", _CO + r"/api/projects/(?P<item>[^/]+)$"),),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "delete_project"),)),
    _a("risk.rated", 2, ("control_objectives",), "risk", per_request=None,
       caused_by=(_co("POST", rf"projects/{_P}/(ratings|severity)"),),
       details_keys=("rating", "band"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "rate_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "rate"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "rate_impact"),)),
    _a("risk.rating_comment.set", 2, ("control_objectives",), "risk", per_request=None,
       caused_by=(_co("POST", rf"projects/{_P}/(severity|severity-comments)"),),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "comment_severities"),)),
    _a("ai.mapping.requested", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+)/map"),),
       runs=("ai.mapping.completed", "ai.mapping.failed", "ai.llm_call"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_risks"),)),
    _a("ai.mapping.completed", 2, ("control_objectives",), "assessment", actor_kinds=("ai",),
       per_request=None, details_keys=("skill", "profile_version", "attempts"), content_required=True),
    _a("ai.mapping.failed", 2, ("control_objectives",), "assessment", actor_kinds=("ai",), per_request=None,
       details_keys=("error", "attempts")),
    _a("mapping.risk.edited", 2, ("control_objectives",), "risk",
       caused_by=(_co("POST", rf"projects/{_P}/risks/(?P<item>[^/]+)/mapping"),),
       details_keys=("added", "removed"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_by_hand_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "map_by_hand"),)),
    _a("objective.key.set", 2, ("control_objectives",), "assessment",
       caused_by=(_co("POST", r"projects/(?P<item>[^/]+)/key"),), details_keys=("added", "removed"),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "key_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "set_keys"),)),
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
       caused_by=(_co("POST", rf"sets/{_P}/objectives/(?P<item>[^/]+)"),
                  ("control_objectives", "PUT", _CO + rf"/api/sets/{_P}/objectives/(?P<item>[^/]+)$")),
       details_keys=("set",), content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "edit_objective_form"),
               ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "edit_objective"))),
    _a("objective.retired", 2, ("control_objectives",), "objective",
       caused_by=(_co("POST", rf"sets/{_P}/objectives/(?P<item>[^/]+)/retire"),), details_keys=("set",),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "retire_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "retire"))),
    _a("objective.restored", 2, ("control_objectives",), "objective",
       caused_by=(_co("POST", rf"sets/{_P}/objectives/(?P<item>[^/]+)/restore"),), details_keys=("set",)),
    _a("objective_set.deleted", 2, ("control_objectives",), "objective_set",
       caused_by=(_co("POST", r"sets/(?P<item>[^/]+)/delete"),
                  ("control_objectives", "DELETE", _CO + r"/api/sets/(?P<item>[^/]+)$")), content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "delete_set_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "delete_set"))),
    _a("objective_profile.created", 2, ("control_objectives",), "objective_profile",
       caused_by=(_co("POST", "profiles"),),
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "make_profile_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "make_profile"),)),
    _a("objective_profile.version_saved", 2, ("control_objectives",), "objective_profile",
       caused_by=(_co("POST", r"profiles/(?P<item>[^/]+)(/versions)?"),), details_keys=("version", "dropped"),
       content_required=True,
       routes=(("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "save_profile_form"), ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/library_routes.py", "save_profile"),)),
    # --- step 3: local installs ------------------------------------------------------------------
    _a("plugin.installed", 3, ("engine",), "plugin",
       caused_by=(("engine", "POST", _EN + r"/plugins/?$"),), details_keys=("package", "version", "reused")),
    _a("control.installed", 3, ("controls",), "checklist",
       caused_by=(("controls", "ACTION", _CT + r"/(install|catalogue)$"),
                  ("controls", "ACTION", r"^/controls/install$"),
                  ("controls", "POST", r"^/controls/api/install$")), details_keys=("package", "questions"),
       routes=(("controls", "apps/controls/src/app/p/[project]/catalogue/actions.ts", "installHere"),
               ("controls", "apps/controls/src/app/p/[project]/install/actions.ts", "installFromCatalogue"),
               ("controls", "apps/controls/src/app/api/install/route.ts", "POST"))),
    # --- step 4: evidence, engine, controls --------------------------------------------------------
    _a("evidence.links.saved", 4, ("platform",), "evidence",
       caused_by=(("platform", "PUT", _LAUNCH + "/evidence/links$"),),
       details_keys=("added", "removed", "carried"), content_required=True),
    _a("engine.evaluation.run_requested", 4, ("engine",), "evaluation",
       caused_by=(("engine", "POST", _EN + r"/evaluations/task$"),), details_keys=("plugins",),
       runs=("engine.evaluation.status_changed", "engine.measures.recorded", "engine.artifact.uploaded")),
    _a("engine.evaluation.status_changed", 4, ("engine",), "evaluation", actor_kinds=("worker",),
       per_request=None, details_keys=("status_before", "status_after")),
    _a("engine.measures.recorded", 4, ("engine",), "evaluation", actor_kinds=("worker",), per_request=None,
       details_keys=("count",)),
    _a("engine.artifact.uploaded", 4, ("engine",), "artifact", actor_kinds=("worker",), per_request=None,
       details_keys=("size",)),
    _a("engine.plugin.configured", 4, ("engine",), "plugin",
       caused_by=(("engine", "POST", _EN + r"/plugins/(?P<item>[^/]+)/config$"),
                  ("engine", "POST", _EN + r"/plugins/(?P<item>[^/]+)/configs/[^/]+/restore$")),
       content_required=True),
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
    _a("controls.source.created", 4, ("controls",), "source",
       caused_by=(("controls", "ACTION", _CT + r"/sources/new$"),), content_required=True,
       routes=(("controls", "apps/controls/src/app/p/[project]/sources/new/actions.ts", "createSource"),)),
    _a("controls.checklist.questions_revised", 4, ("controls",), "checklist",
       caused_by=(("controls", "ACTION", _CT + r"/checklists/(?P<item>[^/]+)/review$"),),
       details_keys=("version", "questions", "answers_removed", "closed_answers_removed"), content_required=True,
       same_action=("controls.checklist.edited",),
       routes=(("controls", "apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts", "saveReviewedQuestions"),)),
    # the same review when its questions stay as they are: only the checklist's own fields (phase 7 review M1)
    _a("controls.checklist.edited", 4, ("controls",), "checklist",
       caused_by=(("controls", "ACTION", _CT + r"/checklists/(?P<item>[^/]+)/review$"),),
       same_action=("controls.checklist.questions_revised",),
       routes=(("controls", "apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts", "saveReviewedQuestions"),)),
    # --- step 5: dashboard -----------------------------------------------------------------------
    _a("dashboard.viewed", 5, ("dashboard",), "dashboard", per_request=None,
       caused_by=(("dashboard", "GET", r"^/superset/dashboard/(?P<item>[^/]+)/?$"),)),
    _a("dashboard.comment.created", 5, ("dashboard",), "comment",
       caused_by=(("dashboard", "POST", _DB + r"/aisc_comment/?$"),), content_required=True),
    _a("dashboard.comment.deleted", 5, ("dashboard",), "comment",
       caused_by=(("dashboard", "DELETE", _DB + r"/aisc_comment/(?P<item>[^/]+)$"),)),
    _a("dashboard.review.requested", 5, ("dashboard",), "review_request",
       caused_by=(("dashboard", "POST", _DB + r"/aisc_review_request/?$"),), details_keys=("assignee",)),
    _a("dashboard.review.resolved", 5, ("dashboard",), "review_request",
       caused_by=(("dashboard", "PATCH", _DB + r"/aisc_review_request/(?P<item>[^/]+)$"),),
       details_keys=("status_before", "status_after")),
    # --- step 6: the report ----------------------------------------------------------------------
    _a("report.layout.created", 6, ("report_composer",), "layout",
       caused_by=(("report_composer", "POST", _RC + "/layouts$"),
                  ("report_composer", "POST", _RC + rf"/layouts/{_P}/duplicate$")), content_required=True),
    _a("report.layout.updated", 6, ("report_composer",), "layout",
       caused_by=(("report_composer", "PUT", _RC + r"/layouts/(?P<item>[^/]+)$"),),
       details_keys=("revision",), content_required=True),
    _a("report.layout.deleted", 6, ("report_composer",), "layout",
       caused_by=(("report_composer", "DELETE", _RC + r"/layouts/(?P<item>[^/]+)$"),)),
    _a("report.generated", 6, ("report_composer",), "report",
       caused_by=(("report_composer", "POST", _RC + rf"/layouts/{_P}/(reports|generate)$"),),
       details_keys=("card_version", "ledger_head", "blocks"), content_required=True),
    _a("report.downloaded", 6, ("report_composer",), "report", per_request=None,
       caused_by=(("report_composer", "GET", _RC + r"/reports/(?P<item>[^/]+)/(pdf|download)$"),)),
]

REGISTRY: dict[str, Action] = {a.name: a for a in _ACTIONS}

# What a check looks for.
_EVENT_FIELDS = ("event_id", "action", "item_type", "item_id")
_ACTOR_KEYS = frozenset({"actor_sub", "actor_name", "actor_kind", "actor_ref", "user", "subject", "created_by",
                         "updated_by", "on_behalf_of", "on_behalf_of_ref", "on_behalf_of_sub", "username"})
_PLATFORM_ACTOR_FIELDS = ("actor_sub", "actor_name", "actor_kind", "actor_ref", "on_behalf_of_ref",
                          "on_behalf_of_sub", "source_app", "verified")
_PLATFORM_FIELDS = ("content_sha256", "before_sha256", "after_sha256", "recorded_at", "seq")
_SECRET = re.compile(r"(?i)\bbearer\s+\S+|\bsk-[A-Za-z0-9_-]{16,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*")


def check(event: dict, emitter: str | None = None) -> list[str]:
    """The problems of one event as `emitter` sent it; empty means it may be relayed (spec 6.1)."""
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
        if action.content_required and not event.get("content"):
            problems.append("content_required")
    problems += [f"secret_in:{key}" for key, value in details.items() if _holds_secret(value)]
    for field in ("content", "before", "after"):                      # states too (phase 3 review m6)
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
    """Tests only: merge `actions` over the real registry, and restore it afterwards (third review M2).
    The dict is changed in place, so every module that imported REGISTRY sees the same entries."""
    saved = dict(REGISTRY)
    REGISTRY.update(actions)
    try:
        yield REGISTRY
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)
