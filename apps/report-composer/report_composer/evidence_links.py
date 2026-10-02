"""The coverage links a report is made with (evidence links plan 2026-09-30, D5).

Which tests and controls give evidence for which control objective is set once per project, on the
platform's Collect evidence page, and kept in the project's own database (evidence.link, template
0016; this role may read it), one set per AI card version (template 0019). Every snapshot carries them as `coverage_links`, one entry per objective:
tests by plugin package, checklists by checklist id. A generated report stores its snapshot, so it
keeps the links it was made with. A database made before the template reads as no links.
"""
from __future__ import annotations

import re

import psycopg


def _objective_order(objective_id: str) -> tuple:
    """The built-in set first (O9 before O10), then the project's own sets by code, by number
    (2026-10-01); an id from before the rename (R1.1) after."""
    found = re.fullmatch(r"(O|[A-Z]{2,6})([1-9][0-9]*)", objective_id)
    if found is None:
        return (2, "", 0, objective_id)
    code, number = found.groups()
    return (0 if code == "O" else 1, code, int(number), "")


def coverage_links(conn, system_id) -> list[dict]:
    """The step 4 links of one AI card version, the one the report is of (2026-10-02: links belong to a
    card version); [] with no version."""
    if not system_id:
        return []
    try:
        with conn.transaction():
            rows = conn.execute("SELECT objective_id, kind, item_key FROM evidence.link WHERE system_id::text = %s",
                                (str(system_id),)).fetchall()
    except psycopg.errors.UndefinedTable:
        return []
    by_objective: dict[str, dict] = {}
    for r in rows:
        entry = by_objective.setdefault(r["objective_id"], {"objective_id": r["objective_id"], "tests": [],
                                                            "checklists": []})
        entry["tests" if r["kind"] == "test" else "checklists"].append(r["item_key"])
    out = []
    for oid in sorted(by_objective, key=_objective_order):
        entry = by_objective[oid]
        out.append({"objective_id": oid, "tests": sorted(entry["tests"]), "checklists": sorted(entry["checklists"])})
    return out
