"""The platform's own events (spec 6.4; R2.4): written to core.outbox in the same transaction as the
change they describe, citing the request the witness gave. The relay moves them into the right log.

`request_id` is the request being served, set per request by the platform's ledger middleware
(`app.py`). Nothing is written while LEDGER_MODE is off.
"""
from __future__ import annotations

import contextvars
import json
import uuid

from platform_service.ledger import witness

#: The witnessed request the platform is serving now (X-AISC-Request-Id), or None.
current_request: contextvars.ContextVar[str | None] = contextvars.ContextVar("ledger_request", default=None)


def emit(conn, action: str, *, project_pid, item_type: str, item_id, details: dict | None = None,
         content=None, before=None, after=None, item_version=None, card_version=None,
         request_id: str | None = None, emitter: str = "platform", run_id=None, model=None,
         event_id: str | None = None, outcome: str = "ok", extra: dict | None = None) -> str | None:
    """Queue one event on `conn` (inside the caller's transaction). None while the ledger is off."""
    if witness.mode() == "off":
        return None
    event_id = event_id or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO core.outbox (event_id, emitter, project_pid, request_id, run_id, action, item_type, item_id,"
        " item_version, card_version, content, before, after, details, model, outcome, extra)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (event_id, emitter, str(project_pid) if project_pid else None, request_id or current_request.get(),
         run_id, action, item_type, str(item_id) if item_id is not None else None,
         str(item_version) if item_version is not None else None, card_version,
         _json(content), _json(before), _json(after), json.dumps(details or {}), model, outcome,
         json.dumps(extra or {})))
    return event_id


def _json(value):
    return None if value is None else json.dumps(value)


def emit_project(conn, action: str, *, item_type: str, item_id, details: dict | None = None, content=None,
                 before=None, after=None, item_version=None, card_version=None,
                 request_id: str | None = None) -> str | None:
    """The platform's event about data kept in a project's own database (card versions, LLM keys): written
    with that database's ledger.emit, in the same transaction as the change. None while the ledger is off."""
    if witness.mode() == "off":
        return None
    event = {"event_id": str(uuid.uuid4()), "request_id": request_id or current_request.get(), "action": action,
             "item_type": item_type, "item_id": str(item_id) if item_id is not None else None,
             "details": details or {}}
    for key, value in (("content", content), ("before", before), ("after", after),
                       ("item_version", None if item_version is None else str(item_version)),
                       ("card_version", None if card_version is None else str(card_version))):
        if value is not None:
            event[key] = value
    conn.execute("SELECT ledger.emit(%s::jsonb)", (json.dumps(event),))
    return event["event_id"]
