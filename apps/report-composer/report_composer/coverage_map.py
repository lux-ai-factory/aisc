"""One coverage map per layout (report run v2, R-U1.1 to R-U1.5, R-U2.1, R-U2.5).

The map is a list of {objective_id, tests, checklists}: which tests and checklists cover which
control objective. The renderer answers what the map may name for a version (POST
/v1/coverage-choices); this module checks the map, resets it and computes the grid the editor draws.
The page only draws what `grid` returns; the script only collects the ticked boxes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_ENTRIES = 200
KINDS = ("tests", "checklists")
BAD_REFERENCE = "is not available for this project and version"


def _problem(code, pointer, message) -> dict:
    return {"instance_id": None, "code": code, "pointer": pointer, "message": message}


def shape_problems(coverage) -> list[dict]:
    """What is wrong with the map's shape (answered 422 invalid_request)."""
    if not isinstance(coverage, list):
        return [_problem("invalid_request", "/coverage", "must be a list")]
    problems = []
    if len(coverage) > MAX_ENTRIES:
        problems.append(_problem("invalid_request", "/coverage", f"holds at most {MAX_ENTRIES} objectives"))
    seen: set = set()
    for i, entry in enumerate(coverage):
        if not isinstance(entry, dict):
            problems.append(_problem("invalid_request", f"/coverage/{i}", "must be an object"))
            continue
        oid = entry.get("objective_id")
        if not isinstance(oid, str) or not oid:
            problems.append(_problem("invalid_request", f"/coverage/{i}/objective_id", "is required"))
        elif oid in seen:
            problems.append(_problem("invalid_request", f"/coverage/{i}/objective_id", "is listed twice"))
        else:
            seen.add(oid)
        for kind in KINDS:
            values = entry.get(kind, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                problems.append(_problem("invalid_request", f"/coverage/{i}/{kind}", "must be a list of texts"))
        extra = set(entry) - {"objective_id", *KINDS}
        for name in sorted(extra):
            problems.append(_problem("invalid_request", f"/coverage/{i}/{name}", "is not part of a map entry"))
    return problems


def normalised(coverage) -> list[dict]:
    """The map with both lists present (a valid shape assumed)."""
    return [{"objective_id": e["objective_id"], "tests": list(e.get("tests") or []),
             "checklists": list(e.get("checklists") or [])} for e in coverage]


def _values(choices: dict, key: str) -> list:
    return [c.get("value") for c in (choices or {}).get(key) or []]


def reference_problems(coverage, choices) -> list[dict]:
    """Values of the map that are not choices of the pinned version (422 invalid_reference)."""
    objectives = _values(choices, "objectives")
    allowed = {kind: _values(choices, kind) for kind in KINDS}
    problems = []
    for i, entry in enumerate(coverage or []):
        if entry.get("objective_id") not in objectives:
            problems.append(_problem("invalid_reference", f"/coverage/{i}/objective_id", BAD_REFERENCE))
        for kind in KINDS:
            for j, value in enumerate(entry.get(kind) or []):
                if value not in allowed[kind]:
                    problems.append(_problem("invalid_reference", f"/coverage/{i}/{kind}/{j}", BAD_REFERENCE))
    return problems


def reset(coverage, choices) -> list[dict]:
    """The map without values that are not choices; an entry left with nothing, or whose objective
    is not offered, goes."""
    objectives = _values(choices, "objectives")
    allowed = {kind: _values(choices, kind) for kind in KINDS}
    out = []
    for entry in coverage or []:
        if entry.get("objective_id") not in objectives:
            continue
        kept = {kind: [v for v in entry.get(kind) or [] if v in allowed[kind]] for kind in KINDS}
        if kept["tests"] or kept["checklists"]:
            out.append({"objective_id": entry["objective_id"], **kept})
    return out


@dataclass
class Grid:
    groups: list = field(default_factory=list)       # [{"group", "rows": [{"objective_id", "label", "cells"}]}]
    columns: list = field(default_factory=list)      # [{"kind", "value", "label"}]
    unavailable: list = field(default_factory=list)  # [{"objective_id", "cells": [{"kind", "value", "checked"}]}]
    linked: int = 0
    total: int = 0
    message: str = ""


def grid(coverage, choices, version_number=None) -> Grid:
    """Everything the editor draws for the map: rows grouped by requirement group, one column per
    test and checklist, the ticks, what is not available for the version, and the summary counts."""
    choices = choices or {}
    coverage = [e for e in (coverage or []) if isinstance(e, dict)]
    objectives = list(choices.get("objectives") or [])
    columns = [{"kind": kind, "value": c.get("value"), "label": c.get("label") or c.get("value")}
               for kind in KINDS for c in choices.get(kind) or []]
    by_objective = {e.get("objective_id"): e for e in coverage}
    g = Grid(columns=columns, total=len(objectives))
    groups: dict[str, list] = {}
    for o in objectives:
        entry = by_objective.get(o.get("value")) or {}
        cells = [{"kind": c["kind"], "value": c["value"], "checked": c["value"] in (entry.get(c["kind"]) or [])}
                 for c in columns]
        if any(cell["checked"] for cell in cells):
            g.linked += 1
        groups.setdefault(o.get("group") or "", []).append(
            {"objective_id": o.get("value"), "label": o.get("label") or o.get("value"), "cells": cells})
    g.groups = [{"group": name, "rows": rows} for name, rows in groups.items()]
    offered = {o.get("value") for o in objectives}
    allowed = {kind: [c["value"] for c in columns if c["kind"] == kind] for kind in KINDS}
    for entry in coverage:
        oid = entry.get("objective_id")
        gone = [{"kind": kind, "value": v, "checked": True} for kind in KINDS for v in entry.get(kind) or []
                if oid not in offered or v not in allowed[kind]]
        if gone or oid not in offered:
            g.unavailable.append({"objective_id": oid, "cells": gone})
    number = "" if version_number is None else f" {version_number}"
    if not objectives:
        g.message = f"No control objectives for version{number}, so there is nothing to link."
    elif not columns:
        g.message = f"No test results or checklists for version{number} yet."
    return g
