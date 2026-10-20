"""What a preview is drawn with: a version and a period, chosen in the editor's preview pane and never
saved in the layout."""
from __future__ import annotations

from dataclasses import dataclass

from . import db, selection


@dataclass(frozen=True)
class PreviewWith:
    system: dict | None          # None: the project has no version yet
    selection: dict              # the snapshot's `selection` object


def parse(conn, body: dict | None) -> PreviewWith:
    """The preview's version (the one asked for, else the latest) and selection; a version that is not
    the project's falls back to the latest, since nothing is stored."""
    body = body or {}
    system = db.system_of_project(conn, body["system_id"]) if body.get("system_id") else None
    if system is None:
        system = db.latest_system(conn)
    sel = selection.parse_dates(body.get("period_from"), body.get("period_to"),
                                str(body.get("other_versions")).lower() in ("true", "on", "1"), None)
    return PreviewWith(system=system, selection=selection.for_snapshot(sel))
