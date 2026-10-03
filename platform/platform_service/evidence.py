"""Collect evidence (evidence links plan 2026-09-30, step B): the links between the control
objectives selected in step 2 and the tests and controls installed in step 3.

The links are the platform's own (schema `evidence`, template 0016). What may be linked belongs to
the other steps and is read from the same project database as report_ro (D4), the role the report
already reads those tables with, through EVIDENCE_READER_DATABASE_URL (`{database}` is replaced by
the project's database). Nothing of theirs is written.

The objectives are named from the control-objectives service's public catalogue
(CONTROL_OBJECTIVES_URL, on the internal network), kept for a while; when it does not answer they
are listed by id alone.

Dimensions (2026-10-01): each objective is in the trustworthiness dimension of its macro-requirement,
the `macro_id` the objectives catalogue gives it (O7 is in R2); unknown when that catalogue does not
answer; each test and control is in the dimensions its tags name in the tools catalogue
(CATALOGUE_URL, the catalogue's API), a sub-dimension counting as its parent. A new link must join an
objective and an item of the same dimension. When the catalogue does not answer, the items'
dimensions are unknown (None) and no link is refused for them.

Stale (D7): a link is kept when its objective is no longer selected ("not selected"), its plugin is
disabled ("disabled") or uninstalled ("removed"), or its checklist is gone ("deleted"). It is shown
with that reason, and no new link may be made to such an objective or item.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from platform_service import connection_store, projectdb

logger = logging.getLogger(__name__)

KINDS = ("test", "control")
DEFAULT_CATALOGUE = "http://control-objectives:8090"
TITLES_TTL_S = 600
_titles: dict = {"at": 0.0, "by_id": {}, "macros": {}, "dims": {}}
_tools: dict = {"at": 0.0, "by_slug": {}, "by_package": {}}

#: The eleven macro-requirements of the control-objectives paper, each a dimension of the catalogue.
DIMENSIONS = (
    ("R1", "Human Agency and Oversight", "human-agency-oversight"),
    ("R2", "Technical Robustness and Safety", "technical-robustness-safety"),
    ("R3", "Privacy and Data Governance", "privacy-data-governance"),
    ("R4", "Transparency", "transparency"),
    ("R5", "Diversity, Non-Discrimination and Fairness", "diversity-non-discrimination-fairness"),
    ("R6", "Societal and Environmental Well-being", "societal-environmental-wellbeing"),
    ("R7", "Accountability", "accountability"),
    ("R8", "Quality Management", "quality-management"),
    ("R9", "Risk Management", "risk-management"),
    ("R10", "Technical Documentation", "technical-documentation"),
    ("R11", "Record-keeping and Documentation Retention", "record-keeping"),
)
_BY_SLUG = {slug: rid for rid, _, slug in DIMENSIONS}
_TITLE = {rid: title for rid, title, _ in DIMENSIONS}

#: The project's AI card versions, latest first (2026-10-02: step 4's links belong to one of them).
_VERSIONS = "SELECT pid::text AS pid, number FROM project.system ORDER BY number DESC"
#: What one card version's assessment takes forward: its step 2 matrix.
_SELECTED = (
    "SELECT sel.objective_ids FROM control_objectives.objective_selection sel"
    " JOIN control_objectives.project a ON a.id = sel.project_id"
    " WHERE a.system_id::text = %s"
)
_PLUGINS = ("SELECT package_name, display_name, enabled, catalogue_slug, name FROM engine.aisc_backend_plugin"
            " ORDER BY display_name, package_name")
#: The engine's workspace of this project (its pages are /projects/<name>/...); one row per database.
_WORKSPACE = "SELECT name FROM engine.aisc_backend_project ORDER BY id LIMIT 1"
#: Step 4's test tiles (2026-10-03): each installed test's runs on one card version, as the engine's
#: per-plugin rows count them; an archived evaluation is hidden in the engine, so it is not counted.
_RUNS = (
    "SELECT pl.package_name, count(*) FILTER (WHERE ep.status = 'Done') AS executed,"
    " count(*) FILTER (WHERE ep.status = 'Failed') AS failed,"
    " count(*) FILTER (WHERE ep.status IN ('Pending', 'Running')) AS running"
    " FROM engine.aisc_backend_evaluationplugin ep"
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id"
    " JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id"
    " JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
    " WHERE e.system_id::text = %s AND e.status <> 'Archived'"
    " GROUP BY pl.package_name"
)
_CHECKLISTS = 'SELECT id, title, "catalogueId" FROM controls.checklist ORDER BY title, id'
#: The project's own objectives (objective sets, 2026-10-01), each as its latest published version words it.
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
    #: the engine's workspace name, None before the engine has made it
    workspace: str | None = None


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
    raise UnknownVersion(f"no card version {version} in this project")


def choices(pid, version_pid: str | None) -> Choices:
    with _reader(pid) as conn:
        selected = _rows(conn, _SELECTED, (version_pid,)) if version_pid else []
        plugins = _rows(conn, _PLUGINS)
        checklists = _rows(conn, _CHECKLISTS)
        own = _rows(conn, _OWN_OBJECTIVES)
        runs = _rows(conn, _RUNS, (version_pid,)) if version_pid else []
        workspace = _rows(conn, _WORKSPACE)
    return Choices(
        selected=sorted(selected[0]["objective_ids"], key=_objective_order) if selected else [],
        plugins={r["package_name"]: (r["display_name"] or r["package_name"], r["enabled"]) for r in plugins},
        checklists={r["id"]: r["title"] for r in checklists},
        plugin_slugs={r["package_name"]: r["catalogue_slug"] for r in plugins},
        checklist_slugs={r["id"]: r["catalogueId"] for r in checklists},
        own={r["objective_id"]: (r["label"], r["dimension"]) for r in own},
        plugin_names={r["package_name"]: r.get("name") for r in plugins},
        runs={r["package_name"]: {k: r[k] for k in ("executed", "failed", "running")} for r in runs},
        workspace=workspace[0]["name"] if workspace else None,
    )


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
    """objective id -> its dimension (R1 ... R11); {} when the catalogue does not answer."""
    return _titles["dims"] if titles() else {}


def dimension_titles() -> dict[str, str]:
    """R-id -> the dimension's name: the objectives catalogue's, else the paper's."""
    titles()
    return {**_TITLE, **_titles["macros"]}


def forget_dimensions() -> None:
    _tools.update(at=0.0, by_slug={}, by_package={})


def _dimensions_of(tags: list[dict]) -> list[str]:
    """A tool's dimensions, a sub-dimension tag counting as its parent, in R order."""
    found = set()
    for tag in tags or []:
        if tag.get("section") == "dimension":
            found.add(_BY_SLUG.get(tag.get("slug")))
        elif tag.get("parent_dimension_slug"):
            found.add(_BY_SLUG.get(tag["parent_dimension_slug"]))
    found.discard(None)
    return sorted(found, key=lambda rid: int(rid[1:]))


def tool_dimensions() -> tuple[dict, dict] | None:
    """(slug -> dimensions, package name -> dimensions) from the tools catalogue; None when it does
    not answer or is not configured."""
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
        for earlier in all_versions[1:]:
            rows = links(pid, earlier["pid"])
            if rows:
                kept = [r for r in rows if r["objective_id"] in found.selected
                        and item_stale(found, r["kind"], r["item_key"]) is None]
                if kept:
                    stored, carried_from = kept, earlier["number"]
                break
    objectives = list(found.selected) + sorted(
        {r["objective_id"] for r in stored} - set(found.selected), key=_objective_order)
    no_runs = {"executed": 0, "failed": 0, "running": 0}
    tests = [{"key": k, "label": label, "stale": None if enabled else "disabled",
              "engine_name": found.plugin_names.get(k), "runs": found.runs.get(k, no_runs)}
             for k, (label, enabled) in found.plugins.items()]
    tests += [{"key": k, "label": k, "stale": "removed", "engine_name": None, "runs": None}
              for k in sorted({r["item_key"] for r in stored if r["kind"] == "test"} - set(found.plugins))]
    controls = [{"key": k, "label": title, "stale": None} for k, title in found.checklists.items()]
    controls += [{"key": k, "label": k, "stale": "deleted"}
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
        "dimensions": [{"id": rid, "title": dim_titles[rid]} for rid, _, _ in DIMENSIONS],
        "dimensions_known": catalogue is not None and bool(dims),
        "objectives": [{"id": o, "title": names.get(o, ""), "dimension": dims.get(o),
                        "stale": None if o in found.selected else "not selected"}
                       for o in objectives],
        "tests": tests,
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
    is changed). An older version is OlderVersion: it is kept as it was."""
    all_versions = versions(pid)
    current = _version(all_versions, version)
    if current is None:
        raise Refused("this project has no AI card version yet")
    if current["pid"] != all_versions[0]["pid"]:
        raise OlderVersion(f"version {current['number']} is kept as it was: links change only on the latest"
                           f" AI card version, {all_versions[0]['number']}")
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
