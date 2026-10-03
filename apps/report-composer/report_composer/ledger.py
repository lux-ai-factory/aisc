"""The composer's ledger events (docs/superpowers/ledger-2026-10-02/02-spec.md 6.4, 6.5; phase 9).

An event is written with the project database's `ledger.emit(jsonb)` on the connection of the write it
describes, inside that write's one transaction (db.connect, projectdb.connect), so a rollback leaves no
event and a committed change always has one (R2.4). The composer never names who acted: it cites the
request the gateway witnessed (`X-AISC-Request-Id`, kept per request by `RequestId`), and the platform's
relay takes the person from that record. It sends plain content (a logo as its sha256, never the image);
the platform computes the keyed digests (N4). Nothing is written while LEDGER_MODE is off (the default).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import math
import os
import uuid
from typing import Any

#: The witnessed request being served, or None outside one.
current_request: contextvars.ContextVar[str | None] = contextvars.ContextVar("ledger_request", default=None)

_MAX_SAFE = 2 ** 53


class NotLedgerSafe(ValueError):
    """A value the ledger can't keep (an integer beyond 2**53, NaN, an infinity, a lone surrogate)."""


def on() -> bool:
    return os.environ.get("LEDGER_MODE", "off").strip().lower() in ("record", "enforce")


def _check(value: Any) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE:
            raise NotLedgerSafe(f"integer beyond 2**53: {value}")
    elif isinstance(value, float):
        if not math.isfinite(value) or (value.is_integer() and abs(value) > _MAX_SAFE):
            raise NotLedgerSafe(f"a number the ledger can't keep: {value}")
    elif isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise NotLedgerSafe("a lone surrogate has no UTF-8 form") from None
    elif isinstance(value, (list, tuple)):
        for v in value:
            _check(v)
    elif isinstance(value, dict):
        for k, v in value.items():
            _check(k)
            _check(v)
    else:
        raise NotLedgerSafe(f"JSON has no form for {type(value).__name__}")


def body(action: str, *, item_type: str, item_id: str | None, details: dict | None = None, content=None,
         before=None, after=None, item_version: str | None = None, card_version: str | None = None) -> dict:
    """The event as `ledger.emit` takes it; NotLedgerSafe for a value the relay would reject later."""
    event: dict[str, Any] = {"event_id": str(uuid.uuid4()), "request_id": current_request.get(),
                             "action": action, "item_type": item_type, "item_id": item_id,
                             "details": details or {}}
    for key, value in (("content", content), ("before", before), ("after", after),
                       ("item_version", item_version), ("card_version", card_version)):
        if value is not None:
            event[key] = value
    _check(event)
    return event


def emit(conn, action: str, **fields) -> str | None:
    """Queue one event on `conn`, inside its open transaction. None while the ledger is off."""
    if not on():
        return None
    event = body(action, **fields)
    conn.execute("SELECT ledger.emit(%s::jsonb)", (json.dumps(event, allow_nan=False, default=str),))
    return event["event_id"]


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


class RequestId:
    """ASGI middleware: the request the gateway witnessed (X-AISC-Request-Id), for this request's events."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        presented = dict(scope.get("headers") or []).get(b"x-aisc-request-id")
        value = None
        if presented:
            try:
                value = str(uuid.UUID(presented.decode("latin-1")))
            except ValueError:
                value = None                                          # never put anything else in an event
        token = current_request.set(value)
        try:
            return await self.app(scope, receive, send)
        finally:
            current_request.reset(token)
