"""The read index against the log (spec 6.3; I4, T12; phase 4 review M1).

`ledger.event_index` is a convenience for filtering: every row shown is compared with its verified
entry, column by column, including the columns the filters read (time, actor kind, project), so an
edited row is an alarm, not a quietly different answer.
"""
from __future__ import annotations

import uuid
from datetime import datetime

#: The columns that must say what the verified entry says.
COLUMNS = ("event_id", "action", "actor_ref", "actor_kind", "project_pid", "step", "source_app", "item_type",
           "item_id", "card_version", "outcome", "occurred_at", "request_id", "run_id", "before_sha256",
           "after_sha256")


def same(indexed, logged) -> bool:
    if indexed is None or logged is None:
        return indexed is None and logged is None
    if isinstance(indexed, datetime):                                 # compared as instants
        try:
            return indexed == datetime.fromisoformat(str(logged))
        except ValueError:
            return False
    if isinstance(indexed, uuid.UUID):
        return str(indexed) == str(logged).lower()
    return str(indexed) == str(logged)


def agrees(row: dict, entry: dict) -> bool:
    return all(same(row[c], entry.get(c)) for c in COLUMNS)
