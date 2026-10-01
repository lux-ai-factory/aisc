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
from dataclasses import dataclass

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

#: The latest card version's selection: of the highest-numbered version that has one.
_SELECTED = (
    "SELECT sel.objective_ids FROM control_objectives.objective_selection sel"
    " JOIN control_objectives.project a ON a.id = sel.project_id"
    " JOIN project.system s ON s.pid = a.system_id"
    " ORDER BY s.number DESC LIMIT 1"
)
_PLUGINS = ("SELECT package_name, display_name, enabled, catalogue_slug FROM engine.aisc_backend_plugin"
            " ORDER BY display_name, package_name")
_CHECKLISTS = 'SELECT id, title, "catalogueId" FROM controls.checklist ORDER BY title, id'


class NotConfigured(RuntimeError):
    """EVIDENCE_READER_DATABASE_URL is not set."""


class Refused(ValueError):
    """A new link to something that cannot take one; the message says which and why."""


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


def _reader(pid) -> psycopg.Connection:
    url = os.environ.get("EVIDENCE_READER_DATABASE_URL")
    if not url:
        raise NotConfigured("EVIDENCE_READER_DATABASE_URL is not set")
    return psycopg.connect(url.replace("{database}", projectdb.database_name(pid)), row_factory=dict_row)


def _rows(conn, query: str) -> list[dict]:
    """A module's table that is not there yet (its step never ran here) reads as empty."""
    try:
        with conn.transaction():
            return conn.execute(query).fetchall()
    except psycopg.errors.UndefinedTable:
        return []


def choices(pid) -> Choices:
    with _reader(pid) as conn:
        selected = _rows(conn, _SELECTED)
        plugins = _rows(conn, _PLUGINS)
        checklists = _rows(conn, _CHECKLISTS)
    return Choices(
        selected=sorted(selected[0]["objective_ids"], key=_objective_order) if selected else [],
        plugins={r["package_name"]: (r["display_name"] or r["package_name"], r["enabled"]) for r in plugins},
        checklists={r["id"]: r["title"] for r in checklists},
        plugin_slugs={r["package_name"]: r["catalogue_slug"] for r in plugins},
        checklist_slugs={r["id"]: r["catalogueId"] for r in checklists},
    )


def _objective_order(objective_id: str) -> tuple:
    """Catalogue order: O9 before O10; anything else (an old id left behind) after."""
    if re.fullmatch(r"O[1-9][0-9]*", objective_id):
        return (0, int(objective_id[1:]), "")
    return (1, 0, objective_id)


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


def links(pid) -> list[dict]:
    with connection_store.connect(pid) as conn:
        return conn.execute("SELECT objective_id, kind, item_key, created_by, created_at FROM evidence.link"
                            " ORDER BY objective_id, kind, item_key").fetchall()


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


def view(pid) -> dict:
    """The page: the selected objectives, the tests and the controls (each flagged stale when it is
    only there because a link names it), and the links."""
    found = choices(pid)
    stored = links(pid)
    objectives = list(found.selected) + sorted(
        {r["objective_id"] for r in stored} - set(found.selected), key=_objective_order)
    tests = [{"key": k, "label": label, "stale": None if enabled else "disabled"}
             for k, (label, enabled) in found.plugins.items()]
    tests += [{"key": k, "label": k, "stale": "removed"}
              for k in sorted({r["item_key"] for r in stored if r["kind"] == "test"} - set(found.plugins))]
    controls = [{"key": k, "label": title, "stale": None} for k, title in found.checklists.items()]
    controls += [{"key": k, "label": k, "stale": "deleted"}
                 for k in sorted({r["item_key"] for r in stored if r["kind"] == "control"} - set(found.checklists))]
    catalogue = tool_dimensions()
    for item in tests:
        item["dimensions"] = item_dimensions(found, catalogue, "test", item["key"])
    for item in controls:
        item["dimensions"] = item_dimensions(found, catalogue, "control", item["key"])
    names = titles()
    dims = objective_dimensions()
    dim_titles = dimension_titles()
    return {
        "dimensions": [{"id": rid, "title": dim_titles[rid]} for rid, _, _ in DIMENSIONS],
        "dimensions_known": catalogue is not None and bool(dims),
        "objectives": [{"id": o, "title": names.get(o, ""), "dimension": dims.get(o),
                        "stale": None if o in found.selected else "not selected"}
                       for o in objectives],
        "tests": tests,
        "controls": controls,
        "links": [{"objective_id": r["objective_id"], "kind": r["kind"], "key": r["item_key"],
                   "created_by": r["created_by"], "created_at": r["created_at"].isoformat(),
                   "stale": link_stale(found, r["objective_id"], r["kind"], r["item_key"])}
                  for r in stored],
    }


def replace(pid, wanted: list[tuple[str, str, str]], who: str) -> None:
    """Make the links exactly `wanted` ((objective_id, kind, key), ...). A link already there is
    kept as it is, stale or not, with who made it; a new one must be to a selected objective and
    to a test or control that can take it (Refused otherwise, and nothing is changed)."""
    found = choices(pid)
    catalogue = tool_dimensions()
    dims = objective_dimensions()
    wanted_set = set(wanted)
    with connection_store.connect(pid) as conn:
        with conn.transaction():
            have = {(r["objective_id"], r["kind"], r["item_key"]) for r in conn.execute(
                "SELECT objective_id, kind, item_key FROM evidence.link FOR UPDATE").fetchall()}
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
                conn.execute("DELETE FROM evidence.link WHERE objective_id = %s AND kind = %s AND item_key = %s",
                             gone)
            for objective_id, kind, key in sorted(wanted_set - have):
                conn.execute("INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                             " VALUES (%s, %s, %s, %s)", (objective_id, kind, key, who))
