"""Reports of a built-in layout: a built-in generates reports like the project's own layouts.

A report belongs to a layout of the project (report_composer.generated_report.layout_id), and a built-in
is not stored in the project. So each built-in gets one record per project (layout.builtin_id), made at its
first report and brought in step with the built-in at every later one: when the platform's built-in
changed, the record takes a new revision, so each report still names the revision it was made from. Both
are recorded in the ledger (report.layout.created, report.layout.updated), as every layout write is. The
record is never listed, edited or deleted as a layout (db.get_layout leaves it out unless asked).
"""
from __future__ import annotations

import psycopg

from . import builtin_layouts, db, ledger


def _state(layout: dict) -> tuple:
    blocks = tuple((b["instance_id"], b["block_type"], repr(sorted((b.get("options") or {}).items())))
                   for b in layout["blocks"])
    return (layout["name"], layout.get("description") or "", bool(layout.get("show_index")),
            bool(layout.get("numbering")), blocks)


def record_for(conn, builtin: dict, who: str, now) -> str:
    """The id of the built-in's record in this project, made or brought in step with it."""
    settings = {"show_index": builtin["show_index"], "numbering": builtin["numbering"]}
    blocks = [{"instance_id": b["instance_id"], "block_type": b["block_type"], "options": b["options"]}
              for b in builtin["blocks"]]
    lid = db.builtin_record(conn, builtin["id"])
    if lid is None:
        try:
            with conn.transaction():                     # a savepoint: the caller's transaction goes on
                lid = db.insert_layout(conn, template_id=None, name=builtin["name"],
                                       description=builtin["description"], blocks=blocks, who=who, now=now,
                                       settings=settings, builtin_id=builtin["id"])
                saved = ledger.layout_state(db.get_layout(conn, lid, builtin_ok=True))
                ledger.emit(conn, "report.layout.created", item_type="layout", item_id=lid, item_version="1",
                            details={"from": "builtin", "builtin_id": builtin["id"]}, content=saved, after=saved)
                return lid
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name != "layout_builtin_id_key":
                raise
            # another first report made the record meanwhile (and has committed): use it
            lid = db.builtin_record(conn, builtin["id"])
    current = db.get_layout(conn, lid, for_update=True, builtin_ok=True)
    if _state(current) != _state({**builtin, "blocks": blocks}):
        new = db.update_layout(conn, lid, based_on=current["revision"], name=builtin["name"],
                               description=builtin["description"], template_id=None, blocks=blocks, who=who,
                               now=now, settings=settings)
        saved = ledger.layout_state(db.get_layout(conn, lid, builtin_ok=True))
        ledger.emit(conn, "report.layout.updated", item_type="layout", item_id=lid, item_version=str(new),
                    details={"revision": new, "from": "builtin"}, content=saved,
                    before=ledger.layout_state(current), after=saved)
    return lid


def resolve(request, project: dict, layout_id: str, who: str, block_types) -> str:
    """A built-in's id becomes its record's id (made or brought in step); any other id is returned as is."""
    builtin = builtin_layouts.get(layout_id, block_types)
    if builtin is None:
        return layout_id
    with request.app.state.projects.connect(project["pid"]) as conn:
        return record_for(conn, builtin, who, request.app.state.clock())


def record_of(conn, layout_id: str) -> str | None:
    """For a built-in's id, its record's id (None before its first report)."""
    return db.builtin_record(conn, layout_id) if layout_id.startswith(builtin_layouts.PREFIX) else None
