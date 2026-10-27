"""Collect evidence: the links between the control
objectives selected in step 2 and the tests and controls installed in step 3.

The links are the platform's own (schema `evidence`, template 0016). What may be linked belongs to
the other steps and is read from the same project database as report_ro, the role the report
already reads those tables with, through EVIDENCE_READER_DATABASE_URL (`{database}` is replaced by
the project's database). Nothing of theirs is written.

The objectives are named from the control-objectives service's public catalogue
(CONTROL_OBJECTIVES_URL, on the internal network), kept for a while; when it does not answer they
are listed by id alone.

Dimensions: each objective is in the trustworthiness dimension of its macro-requirement,
the `macro_id` the objectives catalogue gives it (O7 is in REQ2); unknown when that catalogue does not
answer; each test and control is in the dimensions its tags name in the tools catalogue
(CATALOGUE_URL, the catalogue's API), a sub-dimension counting as its parent. A new link must join an
objective and an item of the same dimension. When the catalogue does not answer, the items'
dimensions are unknown (None) and no link is refused for them.

Stale: a link is kept when its objective is no longer selected ("not selected"), its plugin is
disabled ("disabled") or uninstalled ("removed"), or its checklist is gone ("deleted"). It is shown
with that reason, and no new link may be made to such an objective or item.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from platform_service import connection_store, projectdb, run_passes
from platform_service.local_controls import local_controls
from platform_service.targets import PROTOCOL_NAMES

logger = logging.getLogger(__name__)

KINDS = ("test", "control")
DEFAULT_CATALOGUE = "http://control-objectives:8090"
TITLES_TTL_S = 600
_titles: dict = {"at": 0.0, "by_id": {}, "macros": {}, "dims": {}}
_tools: dict = {"at": 0.0, "by_slug": {}, "by_package": {}}

#: The eleven macro-requirements of the control-objectives paper, each a dimension of the catalogue.
DIMENSIONS = (
    ("REQ1", "Human Agency and Oversight", "human-agency-oversight"),
    ("REQ2", "Technical Robustness and Safety", "technical-robustness-safety"),
    ("REQ3", "Privacy and Data Governance", "privacy-data-governance"),
    ("REQ4", "Transparency", "transparency"),
    ("REQ5", "Diversity, Non-Discrimination and Fairness", "diversity-non-discrimination-fairness"),
    ("REQ6", "Societal and Environmental Well-being", "societal-environmental-wellbeing"),
    ("REQ7", "Accountability", "accountability"),
    ("REQ8", "Quality Management", "quality-management"),
    ("REQ9", "Risk Management", "risk-management"),
    ("REQ10", "Technical Documentation", "technical-documentation"),
    ("REQ11", "Record-keeping and Documentation Retention", "record-keeping"),
)
_BY_SLUG = {slug: rid for rid, _, slug in DIMENSIONS}
_TITLE = {rid: title for rid, title, _ in DIMENSIONS}

#: The project's AI card versions, latest first (step 4's links belong to one of them).
_VERSIONS = "SELECT pid::text AS pid, number FROM project.system ORDER BY number DESC"
#: What one card version's assessment takes forward: its step 2 matrix.
_SELECTED = (
    "SELECT sel.objective_ids FROM control_objectives.objective_selection sel"
    " JOIN control_objectives.project a ON a.id = sel.project_id"
    " WHERE a.system_id::text = %s"
)
_PLUGINS = ("SELECT id, package_name, display_name, enabled, catalogue_slug, name FROM engine.aisc_backend_plugin"
            " ORDER BY display_name, package_name")
#: The engine's workspace of this project (its pages are /projects/<name>/...); one row per database.
_WORKSPACE = "SELECT name FROM engine.aisc_backend_project ORDER BY id LIMIT 1"
#: A run on a local model file: the engine worker stores {"local_model": {"file", "sha256"}} as the value of
#: the plugin's model input. It is not part of the assessment record: never counted with the AI card's
#: runs, whatever else it has, and listed apart (_LOCAL_RUNS, local_runs). A local_model that is not an
#: object is not that marker, and the run is an ordinary one.
_IS_LOCAL_INPUT = "jsonb_typeof(li.value->'local_model') = 'object'"
_LOCAL = ("EXISTS (SELECT 1 FROM engine.aisc_backend_evaluationinput li"
          " WHERE li.evaluation_plugin_id = ep.id AND " + _IS_LOCAL_INPUT + ")")
#: Step 4's test tiles: each installed test's runs on one card version, as the engine's
#: per-plugin rows count them; an archived evaluation is hidden in the engine, so it is not counted.
_RUNS = (
    "SELECT pl.package_name, count(*) FILTER (WHERE ep.status = 'Done') AS executed,"
    " count(*) FILTER (WHERE ep.status = 'Failed') AS failed,"
    " count(*) FILTER (WHERE ep.status IN ('Pending', 'Running')) AS running"
    " FROM engine.aisc_backend_evaluationplugin ep"
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id"
    " JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id"
    " JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
    " WHERE e.system_id::text = %s AND e.status <> 'Archived' AND NOT " + _LOCAL +
    " GROUP BY pl.package_name"
)
#: The same, per engine plugin: a package can ship several (data-monitor: Data Drift and
#: Data Anomaly), and each has its own tile.
_PLUGIN_RUNS = (
    "SELECT pc.plugin_id, count(*) FILTER (WHERE ep.status = 'Done') AS executed,"
    " count(*) FILTER (WHERE ep.status = 'Failed') AS failed,"
    " count(*) FILTER (WHERE ep.status IN ('Pending', 'Running')) AS running"
    " FROM engine.aisc_backend_evaluationplugin ep"
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id"
    " JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id"
    " WHERE e.system_id::text = %s AND e.status <> 'Archived' AND NOT " + _LOCAL +
    " GROUP BY pc.plugin_id"
)
#: Step 4's control tiles: each checklist's question count, and its latest answers as the
#: controls app lists them (the last version of a chain that is not archived; of several chains, the one
#: updated last). A question counts as answered when it has a score or a written answer. A closed
#: submission keeps its answers to questions removed from the template since (their question link is gone),
#: and is counted over today's questions and those, as its own page counts it.
_QUESTIONS = 'SELECT "checklistId" AS checklist_id, count(*) AS n FROM controls.checklist_question GROUP BY 1'
_SUBMISSIONS = (
    'SELECT DISTINCT ON (s."checklistId") s."checklistId" AS checklist_id, s.id, s.version, s.status,'
    ' (SELECT count(*) FROM controls.submission_answer a WHERE a."submissionId" = s.id'
    "   AND (a.score IS NOT NULL OR btrim(coalesce(a.answer, '')) <> '')) AS answered,"
    ' (SELECT avg(a.score) FROM controls.submission_answer a WHERE a."submissionId" = s.id) AS mean_score,'
    ' (SELECT count(*) FROM controls.submission_answer a WHERE a."submissionId" = s.id'
    '   AND a."questionId" IS NULL) AS kept'
    ' FROM controls.submission s'
    ' WHERE s.archived_at IS NULL'
    '   AND NOT EXISTS (SELECT 1 FROM controls.submission n WHERE n."previousVersionId" = s.id)'
    ' ORDER BY s."checklistId", s.updated_at DESC'
)
#: Results navigation: the
#: project's assessment targets, and each tool's runs on each of them on one card version. A run's
#: target is its evaluation input named target, through its engine component, as the dashboard's
#: SQL resolves it; a run with no target input is unassigned; archived evaluations are not counted.
_TARGETS = "SELECT key, kind, component_kind, label, last_card_number FROM target.target"
_TARGET_RUNS = (
    "SELECT t.key AS target_key, ti.id IS NULL AS unassigned, pl.package_name,"
    " COALESCE(pl.display_name, pl.name, pl.package_name) AS label,"
    " count(*) FILTER (WHERE ep.status = 'Done') AS executed,"
    " count(*) FILTER (WHERE ep.status = 'Failed') AS failed,"
    " count(*) FILTER (WHERE ep.status IN ('Pending', 'Running')) AS running,"
    " max(e.created_at) AS last_run"
    " FROM engine.aisc_backend_evaluationplugin ep"
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id"
    " JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id"
    " JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
    " LEFT JOIN engine.aisc_backend_evaluationinput ti ON ti.evaluation_plugin_id = ep.id AND ti.name = 'target'"
    " LEFT JOIN engine.aisc_backend_aicomponent tc ON tc.id = ti.component_id"
    " LEFT JOIN target.target t ON t.engine_component = tc.pid"
    " WHERE e.system_id::text = %s AND e.status <> 'Archived' AND NOT " + _LOCAL +
    " GROUP BY 1, 2, 3, 4"
)
#: The same runs one by one, newest first, with what each was on: its target (as above) or, for a local
#: run, the marker of its model input (the first by name when several are marked); and its helper models,
#: the inputs named helper:<role>, each with the model picked for the run (the endpoint's name when the
#: run's value names none, "unnamed endpoint" when it has none either). The evaluation plugin's pid is
#: what the platform recorded its connection uses by.
_RUN_COLUMNS = (
    "SELECT ep.pid::text AS run, ep.status, e.created_at, pl.package_name,"
    " COALESCE(pl.display_name, pl.name, pl.package_name) AS label,"
    " t.key AS target_key, ti.id IS NULL AS unassigned, t.label AS target_label,"
    " (SELECT li.value->'local_model' FROM engine.aisc_backend_evaluationinput li"
    "   WHERE li.evaluation_plugin_id = ep.id AND " + _IS_LOCAL_INPUT + " ORDER BY li.name LIMIT 1) AS local_model,"
    " (SELECT COALESCE(jsonb_agg(jsonb_build_object('role', substr(hi.name, 8),"
    "                                               'model', COALESCE(NULLIF(hi.value->>'model', ''),"
    "                                                               hi.value->>'label', hc.name,"
    "                                                               'unnamed endpoint'))"
    "                            ORDER BY hi.name), '[]'::jsonb)"
    "   FROM engine.aisc_backend_evaluationinput hi"
    "   LEFT JOIN engine.aisc_backend_aicomponent hc ON hc.id = hi.component_id"
    "   WHERE hi.evaluation_plugin_id = ep.id AND starts_with(hi.name, 'helper:')) AS helpers"
    " FROM engine.aisc_backend_evaluationplugin ep"
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id"
    " JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id"
    " JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
    " LEFT JOIN engine.aisc_backend_evaluationinput ti ON ti.evaluation_plugin_id = ep.id AND ti.name = 'target'"
    " LEFT JOIN engine.aisc_backend_aicomponent tc ON tc.id = ti.component_id"
    " LEFT JOIN target.target t ON t.engine_component = tc.pid"
)
_RUN_DETAILS = (_RUN_COLUMNS + " WHERE e.system_id::text = %s AND e.status <> 'Archived' AND NOT " + _LOCAL +
                " ORDER BY e.created_at DESC, ep.id DESC")
#: The project's local runs, whatever card version they were made on (or none): they are not part of
#: any version's assessment record.
_LOCAL_RUNS = (_RUN_COLUMNS + " WHERE e.status <> 'Archived' AND " + _LOCAL +
               " ORDER BY e.created_at DESC, ep.id DESC")
_CHECKLISTS = 'SELECT id, title, "catalogueId" FROM controls.checklist ORDER BY title, id'
#: The project's own objectives (objective sets), each as its latest published version words it.
_OWN_OBJECTIVES = (
    "SELECT DISTINCT ON (i.objective_id) i.objective_id, i.label, i.dimension"
    " FROM control_objectives.objective_set_version_item i"
    " JOIN control_objectives.objective_set_version v ON v.id = i.set_version_id"
    " ORDER BY i.objective_id, v.number DESC"
)


class NotConfigured(RuntimeError):
    """EVIDENCE_READER_DATABASE_URL is not set."""


class Refused(ValueError):
    """A new link to something that cannot take one; the message says which and why."""


class OlderVersion(ValueError):
    """Links change only on the latest card version; an older one is kept as it was."""


class UnknownVersion(LookupError):
    """No such card version in this project."""


@dataclass
class Choices:
    """What steps 2 and 3 offer right now."""

    selected: list[str]
    #: package_name -> (label, enabled)
    plugins: dict[str, tuple[str, bool]]
    #: checklist id -> title
    checklists: dict[str, str]
    #: package_name -> catalogue slug (None when the install did not record one)
    plugin_slugs: dict[str, str | None]
    #: checklist id -> catalogue slug
    checklist_slugs: dict[str, str | None]
    #: the project's own objectives: id -> (label, dimension)
    own: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: package_name -> the engine's name of the plugin (its configuration page is named by it)
    plugin_names: dict[str, str | None] = field(default_factory=dict)
    #: package_name -> {"executed", "failed", "running"} on the card version asked for
    runs: dict[str, dict[str, int]] = field(default_factory=dict)
    #: every engine plugin, one row each (id, package_name, name, display_name, enabled), by label
    engine_plugins: list[dict] = field(default_factory=list)
    #: engine plugin id -> {"executed", "failed", "running"} on the card version asked for
    plugin_runs: dict[int, dict[str, int]] = field(default_factory=dict)
    #: the engine's workspace name, None before the engine has made it
    workspace: str | None = None
    #: checklist id -> its number of questions
    questions: dict[str, int] = field(default_factory=dict)
    #: checklist id -> its latest answers: {"id", "version", "status", "readiness", "answered"}
    submissions: dict[str, dict] = field(default_factory=dict)
    #: the rows of target.target
    targets: list[dict] = field(default_factory=list)
    #: each tool's runs per target on the card version asked for (_TARGET_RUNS rows)
    target_runs: list[dict] = field(default_factory=list)
    #: the same runs one by one, newest first (_RUN_DETAILS rows)
    run_details: list[dict] = field(default_factory=list)
    #: the runs on a local model file, of any card version, newest first (_LOCAL_RUNS rows)
    local_runs: list[dict] = field(default_factory=list)


def _reader(pid) -> psycopg.Connection:
    url = os.environ.get("EVIDENCE_READER_DATABASE_URL")
    if not url:
        raise NotConfigured("EVIDENCE_READER_DATABASE_URL is not set")
    return psycopg.connect(url.replace("{database}", projectdb.database_name(pid)), row_factory=dict_row)


def _rows(conn, query: str, params=None) -> list[dict]:
    """A module's table that is not there yet (its step never ran here) reads as empty."""
    try:
        with conn.transaction():
            return conn.execute(query, params).fetchall()
    except psycopg.errors.UndefinedTable:
        return []


def versions(pid) -> list[dict]:
    """[{"pid", "number"}, ...], latest first."""
    with _reader(pid) as conn:
        return [{"pid": r["pid"], "number": r["number"]} for r in _rows(conn, _VERSIONS)]


def _version(all_versions: list[dict], version: str | None) -> dict | None:
    """The card version asked for, or the latest when none is; None when the project has none."""
    if version is None:
        return all_versions[0] if all_versions else None
    for v in all_versions:
        if v["pid"] == str(version):
            return v
    raise UnknownVersion(f"no AI card version {version} in this project")


def _per_package(rows: list[dict]) -> dict[str, tuple[str, bool]]:
    """{package: (label, enabled)}: a package with several rows (versions, or plugins) is enabled when any is."""
    out: dict[str, tuple[str, bool]] = {}
    for r in rows:
        label, enabled = out.get(r["package_name"], (r["display_name"] or r["package_name"], False))
        out[r["package_name"]] = (label, enabled or r["enabled"])
    return out


def choices(pid, version_pid: str | None) -> Choices:
    with _reader(pid) as conn:
        selected = _rows(conn, _SELECTED, (version_pid,)) if version_pid else []
        plugins = _rows(conn, _PLUGINS)
        checklists = _rows(conn, _CHECKLISTS)
        own = _rows(conn, _OWN_OBJECTIVES)
        runs = _rows(conn, _RUNS, (version_pid,)) if version_pid else []
        plugin_runs = _rows(conn, _PLUGIN_RUNS, (version_pid,)) if version_pid else []
        workspace = _rows(conn, _WORKSPACE)
        questions = _rows(conn, _QUESTIONS)
        submissions = _rows(conn, _SUBMISSIONS)
        targets = _rows(conn, _TARGETS)
        target_runs = _rows(conn, _TARGET_RUNS, (version_pid,)) if version_pid and targets else []
        run_details = _rows(conn, _RUN_DETAILS, (version_pid,)) if version_pid else []
        local = _rows(conn, _LOCAL_RUNS)
    per_checklist = {r["checklist_id"]: r["n"] for r in questions}
    return Choices(
        selected=sorted(selected[0]["objective_ids"], key=_objective_order) if selected else [],
        plugins=_per_package(plugins),
        checklists={r["id"]: r["title"] for r in checklists},
        plugin_slugs={r["package_name"]: r["catalogue_slug"] for r in plugins},
        checklist_slugs={r["id"]: r["catalogueId"] for r in checklists},
        own={r["objective_id"]: (r["label"], r["dimension"]) for r in own},
        plugin_names={r["package_name"]: r.get("name") for r in plugins},
        runs={r["package_name"]: {k: r[k] for k in ("executed", "failed", "running")} for r in runs},
        engine_plugins=plugins,
        plugin_runs={r["plugin_id"]: {k: r[k] for k in ("executed", "failed", "running")} for r in plugin_runs},
        workspace=workspace[0]["name"] if workspace else None,
        questions=per_checklist,
        submissions={r["checklist_id"]: {"id": r["id"], "version": r["version"], "status": r["status"],
                                         "readiness": readiness(r["mean_score"]), "answered": r["answered"],
                                         "questions": per_checklist.get(r["checklist_id"], 0) + r["kept"]}
                     for r in submissions},
        targets=targets,
        target_runs=target_runs,
        run_details=run_details,
        local_runs=local,
    )


def _connection(use: dict) -> dict:
    return {"name": use["connection"], "protocol": use["protocol"],
            "protocol_name": PROTOCOL_NAMES.get(use["protocol"], use["protocol"]), "fingerprint": use["fingerprint"]}


def _run(row: dict, uses: dict[str, list[dict]]) -> dict:
    """One run as results show it: what it assessed (an AI card target, with the first connection the
    platform recorded it reaching; a local model file, with its hash; None for a run with no target, as
    every run made before targets), its helper models."""
    if row["local_model"] is not None:
        lm = row["local_model"] if isinstance(row["local_model"], dict) else {}
        name = lm.get("file") or "local model"
        assessed = {"family": "local", "label": name, "connection": None,
                    "file": {"name": name, "sha256": lm.get("sha256")}}
    elif row["target_key"] is None:
        assessed = None
    else:
        reached = uses.get(row["run"], [])
        assessed = {"family": "card", "label": row["target_label"],
                    "connection": _connection(reached[0]) if reached else None, "file": None}
    return {"run": row["run"], "status": row["status"], "created_at": row["created_at"].isoformat(),
            "assessed": assessed, "helpers": row["helpers"]}


def local_runs(found: Choices) -> list[dict]:
    """The runs on a local model file, newest first, each with its tool: not part of the assessment record."""
    return [{"key": r["package_name"], "label": r["label"], **_run(r, {})} for r in found.local_runs]


def target_view(found: Choices, latest_number: int | None, uses: dict[str, list[dict]] | None = None) -> list[dict]:
    """The targets with their tools' runs: the system first, then the components by
    label, then, only when some run has no target input, a "No target" entry. Each tool also lists its
    runs one by one (_run), newest first, every connection they reached (each connection as it was, once,
    in the order first reached) and every helper model they used (once each). `uses`: run -> the
    connection uses the platform recorded (run_passes.uses_by_run). A local run is in none of them."""
    uses = uses or {}

    def tools(rows):
        return sorted((tool(r) for r in rows), key=lambda t: t["label"].lower())

    def tool(r):
        mine = [d for d in found.run_details if d["package_name"] == r["package_name"]
                and d["label"] == r["label"] and d["unassigned"] == r["unassigned"]
                and (r["unassigned"] or d["target_key"] == r["target_key"])]
        connections, helpers = [], []
        for d in reversed(mine):                        # the connections in the order first reached
            for use in uses.get(d["run"], []) if not d["unassigned"] else []:
                if _connection(use) not in connections:
                    connections.append(_connection(use))
            helpers += [h for h in d["helpers"] if h not in helpers]
        return {"key": r["package_name"], "label": r["label"], "executed": r["executed"],
                "failed": r["failed"], "running": r["running"],
                "last_run": r["last_run"].isoformat() if r["last_run"] else None,
                "runs": [_run(d, uses) for d in mine], "connections": connections,
                "helpers": sorted(helpers, key=lambda h: (h["role"], h["model"]))}

    out = []
    for t in sorted(found.targets, key=lambda t: (t["kind"] != "system", t["label"].lower())):
        stale = (t["kind"] == "component" and latest_number is not None
                 and t["last_card_number"] is not None and t["last_card_number"] < latest_number)
        out.append({"key": t["key"], "kind": t["kind"], "component_kind": t["component_kind"],
                    "label": t["label"], "stale": stale,
                    "tools": tools(r for r in found.target_runs if not r["unassigned"] and r["target_key"] == t["key"])})
    unassigned = [r for r in found.target_runs if r["unassigned"]]
    if unassigned:
        out.append({"key": None, "kind": "unassigned", "component_kind": None, "label": "No target",
                    "stale": False, "tools": tools(unassigned)})
    return out


def readiness(mean_score) -> int | None:
    """The controls app's readiness: the mean score (1 "Not started" to 5 "Fully implemented") as 0 to 100%,
    (mean - 1) / 4, rounded half up as JavaScript's Math.round does; None when nothing is scored
    (apps/controls/src/lib/scoring.ts)."""
    if mean_score is None:
        return None
    return math.floor((float(mean_score) - 1) / 4 * 100 + 0.5)


def _objective_order(objective_id: str) -> tuple:
    """The built-in set first, then each of the project's sets by code, by number within a set (O9
    before O10, BNK9 before BNK10); anything else (an old id left behind) after."""
    found = re.fullmatch(r"(O|[A-Z]{2,6})([1-9][0-9]*)", objective_id)
    if found is None:
        return (2, "", 0, objective_id)
    code, number = found.groups()
    return (0 if code == "O" else 1, code, int(number), "")


def forget_titles() -> None:
    _titles.update(at=0.0, by_id={}, macros={}, dims={})


def titles() -> dict[str, str]:
    """objective id -> its label in the catalogue; {} when the catalogue does not answer."""
    if _titles["by_id"] and time.monotonic() - _titles["at"] < TITLES_TTL_S:
        return _titles["by_id"]
    base = os.environ.get("CONTROL_OBJECTIVES_URL", DEFAULT_CATALOGUE).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/control-objectives", timeout=3) as res:
            listed = json.loads(res.read())
        by_id = {o["id"]: o.get("sub_requirement_label") or "" for o in listed}
        macros = {o["macro_id"]: o["macro_title"] for o in listed if o.get("macro_id") and o.get("macro_title")}
        dims = {o["id"]: o["macro_id"] for o in listed if o.get("macro_id")}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("the control objectives catalogue did not answer: %s", exc)
        return {}
    _titles.update(at=time.monotonic(), by_id=by_id, macros=macros, dims=dims)
    return by_id


def objective_dimensions() -> dict[str, str]:
    """objective id -> its dimension (REQ1 ... REQ11); {} when the catalogue does not answer."""
    return _titles["dims"] if titles() else {}


def dimension_titles() -> dict[str, str]:
    """REQ id -> the dimension's name: the objectives catalogue's, else the paper's."""
    titles()
    return {**_TITLE, **_titles["macros"]}


def forget_dimensions() -> None:
    _tools.update(at=0.0, by_slug={}, by_package={})


def _dimensions_of(tags: list[dict]) -> list[str]:
    """A tool's dimensions, a sub-dimension tag counting as its parent, in REQ order."""
    found = set()
    for tag in tags or []:
        if tag.get("section") == "dimension":
            found.add(_BY_SLUG.get(tag.get("slug")))
        elif tag.get("parent_dimension_slug"):
            found.add(_BY_SLUG.get(tag["parent_dimension_slug"]))
    found.discard(None)
    return sorted(found, key=lambda rid: int(rid[3:]))


def tool_dimensions() -> tuple[dict, dict] | None:
    """(slug -> dimensions, package name -> dimensions) from the tools catalogue, plus the local controls';
    None when it does not answer or is not configured."""
    if _tools["by_slug"] and time.monotonic() - _tools["at"] < TITLES_TTL_S:
        return _tools["by_slug"], _tools["by_package"]
    base = (os.environ.get("CATALOGUE_URL") or "").rstrip("/")
    if not base:
        logger.warning("CATALOGUE_URL is not set: the dimensions of tests and controls are unknown")
        return None
    try:
        with urllib.request.urlopen(f"{base}/tool/?detailed=true", timeout=5) as res:
            listed = json.loads(res.read())
        by_slug, by_package = {}, {}
        for tool in listed:
            dims = _dimensions_of(tool.get("tags"))
            by_slug[tool["slug"]] = dims
            if tool.get("package_name"):
                by_package[tool["package_name"]] = dims
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("the tools catalogue did not answer: %s", exc)
        return None
    # local controls (local_controls/): their own dimension, unless the catalogue has the slug
    for c in local_controls():
        if c["slug"] not in by_slug:
            parents = [{"slug": c.get("dimension_slug"), "section": "dimension"}]
            by_slug[c["slug"]] = _dimensions_of(parents)
    _tools.update(at=time.monotonic(), by_slug=by_slug, by_package=by_package)
    return by_slug, by_package


def item_dimensions(found: Choices, catalogue, kind: str, key: str) -> list[str] | None:
    """The dimensions of a test or control; [] when the catalogue has none for it, None when the
    catalogue did not answer."""
    if catalogue is None:
        return None
    by_slug, by_package = catalogue
    slug = (found.plugin_slugs if kind == "test" else found.checklist_slugs).get(key)
    if slug and slug in by_slug:
        return by_slug[slug]
    if kind == "test" and key in by_package:
        return by_package[key]
    return []


def links(pid, version_pid: str) -> list[dict]:
    """One card version's links."""
    with connection_store.connect(pid) as conn:
        return conn.execute("SELECT objective_id, kind, item_key, created_by, created_at FROM evidence.link"
                            " WHERE system_id::text = %s ORDER BY objective_id, kind, item_key",
                            (version_pid,)).fetchall()


def item_stale(found: Choices, kind: str, key: str) -> str | None:
    """Why a test or control can take no new link, or None."""
    if kind == "test":
        if key not in found.plugins:
            return "removed"
        return None if found.plugins[key][1] else "disabled"
    return None if key in found.checklists else "deleted"


def link_stale(found: Choices, objective_id: str, kind: str, key: str) -> str | None:
    """The objective's reason first: a link to an unselected objective counts for nothing."""
    if objective_id not in found.selected:
        return "not selected"
    return item_stale(found, kind, key)


def _carried(pid, found, all_versions) -> tuple[int | None, list]:
    """The links the latest version, having none of its own, is offered: those of the nearest earlier
    version that has some, where they still apply; with that version's number (None, [] if none)."""
    for earlier in all_versions[1:]:
        rows = links(pid, earlier["pid"])
        if rows:
            kept = [r for r in rows if r["objective_id"] in found.selected
                    and item_stale(found, r["kind"], r["item_key"]) is None]
            return (earlier["number"], kept) if kept else (None, [])
    return None, []


def view(pid, version: str | None = None) -> dict:
    """The page of one card version (the latest when none is asked for): its matrix's objectives, the
    tests and the controls (each flagged stale when it is only there because a link names it), and
    its links. An older version is read-only. The latest version with no links of its own is offered
    those of the nearest earlier version that has some, only where they still apply (its matrix holds
    the objective, the item is installed), marked carried and not stored until saved."""
    all_versions = versions(pid)
    current = _version(all_versions, version)
    read_only = current is not None and current["pid"] != all_versions[0]["pid"]
    found = choices(pid, current["pid"] if current else None)
    stored = links(pid, current["pid"]) if current else []
    carried_from = None
    if current is not None and not stored and not read_only:
        carried_from, stored = _carried(pid, found, all_versions)
    objectives = list(found.selected) + sorted(
        {r["objective_id"] for r in stored} - set(found.selected), key=_objective_order)
    no_runs = {"executed": 0, "failed": 0, "running": 0}
    tests = [{"key": k, "label": label, "stale": None if enabled else "disabled",
              "engine_name": found.plugin_names.get(k), "runs": found.runs.get(k, no_runs)}
             for k, (label, enabled) in found.plugins.items()]
    tests += [{"key": k, "label": k, "stale": "removed", "engine_name": None, "runs": None}
              for k in sorted({r["item_key"] for r in stored if r["kind"] == "test"} - set(found.plugins))]
    # The tiles: one per engine plugin, keyed by its package like `tests`.
    # The engine keeps a row per installed version (an upgrade disables the old one): one tile per plugin,
    # enabled when any version is, with the runs of all its versions
    tiles: dict[tuple, dict] = {}
    for p in found.engine_plugins:
        runs = found.plugin_runs.get(p["id"], no_runs)
        tile = tiles.setdefault((p["package_name"], p.get("name")), {
            "key": p["package_name"], "engine_name": p.get("name"),
            "label": p["display_name"] or p.get("name") or p["package_name"],
            "stale": "disabled", "runs": dict(no_runs)})
        if p["enabled"]:
            tile["stale"] = None
        tile["runs"] = {k: tile["runs"][k] + runs[k] for k in no_runs}
    plugins = list(tiles.values())
    controls = [{"key": k, "label": title, "stale": None, "questions": found.questions.get(k, 0),
                 "submission": found.submissions.get(k)} for k, title in found.checklists.items()]
    controls += [{"key": k, "label": k, "stale": "deleted", "questions": None, "submission": None}
                 for k in sorted({r["item_key"] for r in stored if r["kind"] == "control"} - set(found.checklists))]
    catalogue = tool_dimensions()
    for item in tests:
        item["dimensions"] = item_dimensions(found, catalogue, "test", item["key"])
    for item in controls:
        item["dimensions"] = item_dimensions(found, catalogue, "control", item["key"])
    names = {**titles(), **{oid: label for oid, (label, _) in found.own.items()}}
    dims = {**objective_dimensions(), **{oid: dim for oid, (_, dim) in found.own.items()}}
    dim_titles = dimension_titles()
    return {
        "version": current,
        "versions": all_versions,
        "read_only": read_only,
        "carried_from": carried_from,
        "engine_workspace": found.workspace,
        "targets": target_view(found, all_versions[0]["number"] if all_versions else None,
                               run_passes.uses_by_run([d["run"] for d in found.run_details if d["target_key"]], pid)),
        "local_runs": local_runs(found),
        "dimensions": [{"id": rid, "title": dim_titles[rid]} for rid, _, _ in DIMENSIONS],
        "dimensions_known": catalogue is not None and bool(dims),
        "objectives": [{"id": o, "title": names.get(o, ""), "dimension": dims.get(o),
                        "stale": None if o in found.selected else "not selected"}
                       for o in objectives],
        "tests": tests,
        "plugins": sorted(plugins, key=lambda p: p["label"].lower()),
        "controls": controls,
        "links": [{"objective_id": r["objective_id"], "kind": r["kind"], "key": r["item_key"],
                   "created_by": r["created_by"], "created_at": r["created_at"].isoformat(),
                   "stale": link_stale(found, r["objective_id"], r["kind"], r["item_key"]),
                   "carried": carried_from is not None}
                  for r in stored],
    }


def replace(pid, wanted: list[tuple[str, str, str]], who: str, version: str | None = None) -> None:
    """Make the latest card version's links exactly `wanted` ((objective_id, kind, key), ...). A link
    already there is kept as it is, stale or not, with who made it; a new one must be to an objective
    in that version's matrix and to a test or control that can take it (Refused otherwise, and nothing
    is changed). An older version is OlderVersion: it is kept as it was. Removing every link is a save
    like any other: its `evidence.links.saved` event has an empty list as content."""
    all_versions = versions(pid)
    current = _version(all_versions, version)
    if current is None:
        raise Refused("this project has no AI card version yet")
    if current["pid"] != all_versions[0]["pid"]:
        raise OlderVersion(f"version {current['number']} is kept as it was: links change only on the latest"
                           f" AI card version, {all_versions[0]['number']}")
    from platform_service.ledger import outbox

    system_id = current["pid"]
    found = choices(pid, system_id)
    catalogue = tool_dimensions()
    dims = {**objective_dimensions(), **{oid: dim for oid, (_, dim) in found.own.items()}}
    wanted_set = set(wanted)
    with connection_store.connect(pid) as conn:
        with conn.transaction():
            have = {(r["objective_id"], r["kind"], r["item_key"]) for r in conn.execute(
                "SELECT objective_id, kind, item_key FROM evidence.link WHERE system_id::text = %s FOR UPDATE",
                (system_id,)).fetchall()}
            problems = []
            for objective_id, kind, key in sorted(wanted_set - have):
                if kind not in KINDS:
                    problems.append(f"{objective_id} {kind} {key}: kind must be test or control")
                elif objective_id not in found.selected:
                    problems.append(f"{objective_id} is not selected in step 2")
                elif (why := item_stale(found, kind, key)) is not None:
                    reason = "not installed" if why in ("removed", "deleted") else why
                    problems.append(f"{kind} {key} is {reason}")
                elif (rid := dims.get(objective_id)) is not None \
                        and (item_dims := item_dimensions(found, catalogue, kind, key)) is not None \
                        and rid not in item_dims:
                    problems.append(f"{kind} {key} is not in {rid} {dimension_titles().get(rid, '')}".rstrip())
            if problems:
                raise Refused("; ".join(problems))
            for gone in have - wanted_set:
                conn.execute("DELETE FROM evidence.link WHERE system_id::text = %s AND objective_id = %s"
                             " AND kind = %s AND item_key = %s", (system_id, *gone))
            for objective_id, kind, key in sorted(wanted_set - have):
                conn.execute("INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                             " VALUES (%s, %s, %s, %s, %s)", (system_id, objective_id, kind, key, who))
            # carried: the page offered the links of an earlier version (this one had none of its own)
            outbox.emit_project(conn, "evidence.links.saved", item_type="evidence", item_id=system_id,
                                card_version=system_id,
                                details={"added": len(wanted_set - have), "removed": len(have - wanted_set),
                                         "carried": not have and _carried(pid, found, all_versions)[0] is not None},
                                content=[list(link) for link in sorted(wanted_set)])
