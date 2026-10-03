"""The coverage links a report is made with.

Which tests and controls give evidence for which control objective is set per project on the
platform's Collect evidence page (step 4), and kept in the project's own database: table
`evidence.link` (project templates 0016 and 0019), one set per AI card version, readable by this
service's role. Every snapshot carries them as `coverage_links`, one entry per objective: tests by
plugin package, checklists by checklist id. A generated report stores its snapshot, so it keeps the
links it was made with. A database without the table reads as no links.
"""
from __future__ import annotations

import re

import psycopg


def _objective_order(objective_id: str) -> tuple:
    """The built-in set first (O9 before O10), then the project's own sets by code and number; an
    id of any other shape last."""
    found = re.fullmatch(r"(O|[A-Z]{2,6})([1-9][0-9]*)", objective_id)
    if found is None:
        return (2, "", 0, objective_id)
    code, number = found.groups()
    return (0 if code == "O" else 1, code, int(number), "")


def coverage_links(conn, system_id) -> list[dict]:
    """The step 4 links of the AI card version the report is of; [] with no version."""
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
