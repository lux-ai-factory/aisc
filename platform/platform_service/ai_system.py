"""The one AI system of a project, and how an edit lands on its versions.

A project has exactly one AI system. Qualification describes it, the engine
tests it and the dashboard reports on it, so they all point at one of its
versions, and a version they point at must not change under them.

So the latest version is a draft until something depends on it: an evaluation
runs against it, or its AI card is submitted. That freezes it. An edit to a
draft changes the draft; an edit to a frozen version makes the next version, a
copy of the frozen one with the edit applied, and leaves the frozen one alone.

This module is the decision; db.py carries it out. It needs no database.
"""
from __future__ import annotations

#: What a person edits on the system itself. Its parts (datasets, models, LLMs)
#: are the engine's, and reach here only as "I need a draft to change them in".
IDENTITY = ("name", "release", "provider", "description")


class InvalidSystem(ValueError):
    """An edit that cannot be stored as given."""


def _clean(field: str, value):
    text = (value or "").strip() if isinstance(value, str) or value is None else value
    if field == "name" and not text:
        raise InvalidSystem("a system needs a name")
    return text or None


def plan_edit(latest: dict, changes: dict, needs_draft: bool = False) -> dict:
    """What an edit does to the system whose latest version is `latest`.

    One of:
      {"action": "none",   "pid": latest}           nothing to do
      {"action": "update", "pid": latest, "fields"} the draft, changed in place
      {"action": "fork",   "from_pid", "number", "fields"}
                                                   the next version, complete

    `needs_draft` is for a change to the system's parts: no field here moves,
    but the change still needs a version that is not frozen to land in.
    """
    unknown = set(changes) - set(IDENTITY)
    if unknown:
        raise InvalidSystem(f"not something to edit here: {', '.join(sorted(unknown))}")

    cleaned = {field: _clean(field, value) for field, value in changes.items()}
    moved = {f: v for f, v in cleaned.items() if v != latest.get(f)}
    frozen = latest.get("frozen_at") is not None

    if not frozen:
        if not moved:
            return {"action": "none", "pid": latest["pid"]}
        return {"action": "update", "pid": latest["pid"], "fields": moved}

    if not moved and not needs_draft:
        return {"action": "none", "pid": latest["pid"]}
    fields = {f: latest.get(f) for f in IDENTITY}
    fields.update(moved)
    return {"action": "fork", "from_pid": latest["pid"],
            "number": latest["number"] + 1, "fields": fields}
