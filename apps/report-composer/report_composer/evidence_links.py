"""The coverage links a report is made with (evidence links plan 2026-09-30, D5).

Which tests and controls give evidence for which control objective is set once per project, on the
platform's Collect evidence page, and kept in the project's own database (evidence.link, template
0016; this role may read it). Every snapshot carries them as `coverage_links`, one entry per objective:
tests by plugin package, checklists by checklist id. A generated report stores its snapshot, so it
keeps the links it was made with. A database made before the template reads as no links.
"""
from __future__ import annotations

import psycopg


def _objective_order(objective_id: str) -> tuple:
    """R9.9 before R10.1."""
    try:
        return tuple(int(p) for p in objective_id.lstrip("R").split("."))
    except ValueError:
        return (10**6, objective_id)


def coverage_links(conn) -> list[dict]:
    try:
        with conn.transaction():
            rows = conn.execute("SELECT objective_id, kind, item_key FROM evidence.link").fetchall()
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
