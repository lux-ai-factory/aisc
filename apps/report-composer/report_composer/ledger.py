"""The composer's ledger events.

Events are built and checked by aisc_identity.ledger_events, which also keeps the
witnessed request id (RequestId) that every event cites. emit() writes one on the
connection of the write it describes, inside that write's transaction
(db.connect, projectdb.connect). A logo is recorded as its sha256, never the image.
"""
from __future__ import annotations

import hashlib
import json

from aisc_identity.ledger_events import EMIT_SQL, NotLedgerSafe, RequestId, current_request, event, on

__all__ = ["NotLedgerSafe", "RequestId", "current_request", "emit", "layout_state", "on", "template_state"]


def emit(conn, action: str, **fields) -> str | None:
    """Queue one event on `conn`, inside its open transaction. None while the ledger is off."""
    if not on():
        return None
    body = event(action, **fields)
    conn.execute(EMIT_SQL, (json.dumps(body, allow_nan=False),))
    return body["event_id"]


# What the composer's items say, built one way each so an item's chain holds (an event's before is its
# item's previous after).

def layout_state(layout: dict | None) -> dict | None:
    """A layout as its events keep it: its structure and settings, never who saved it."""
    if layout is None:
        return None
    return {"name": layout["name"], "description": layout.get("description") or "",
            "template_id": layout.get("template_id"), "revision": layout["revision"],
            "show_index": layout["show_index"], "numbering": layout["numbering"],
            "blocks": [{"instance_id": b["instance_id"], "block_type": b["block_type"],
                        "options": b.get("options") or {}} for b in layout["blocks"]]}


def template_state(t: dict | None) -> dict | None:
    """A template (read with its logo) as its events keep it: the logo as its sha256."""
    if t is None:
        return None
    logo = bytes(t["logo"]) if t.get("logo") else None
    return {"name": t["name"], "font": t["font"], "font_size_pt": float(t["font_size_pt"]),
            "primary_color": t["primary_color"], "accent_color": t["accent_color"],
            "header_text": t.get("header_text"), "footer_text": t.get("footer_text"),
            "marking": t.get("marking") or "none", "show_document_id": bool(t.get("show_document_id")),
            "logo_mime": t.get("logo_mime"), "logo_sha256": hashlib.sha256(logo).hexdigest() if logo else None}
