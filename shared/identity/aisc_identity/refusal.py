"""The refusal: the answer to a save that would replace something the person has not seen.

Nothing in conflict is written, and the answer says what changed, who changed it and when. Each app keeps its
own error envelope; inside it a refusal is the same object everywhere. Its shape is held by
shared/identity/refusal-cases.json, which this module's tests and its TypeScript twin
(shared/access-ts/refusal.ts) both run, so the two cannot drift apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

#: each code and the HTTP status it is answered with
CODES: Mapping[str, int] = {
    "changed_since_opened": 409,   # someone saved this since the page was drawn
    "upstream_moved": 409,         # something the action depends on changed
    "upstream_moved_confirm": 409,  # only the card state moved; the person may confirm and go on
    "already_exists": 409,         # the thing to create is there, with other content
    "cited_by_report": 409,        # a stored report names this record
    "syncing": 409,                # the card is being synchronised; try again in a moment
    "not_final": 409,              # the action marks something complete and it is not
    "token_required": 400,         # a save without a token, on a write that needs one
}

#: a time in UTC to the second, as `current.changed_at` gives it
_UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True)
class Current:
    """What is stored now: the token for the next save, who saved it and when, and the values in conflict."""

    token: str
    changed_by: str
    changed_at: str
    #: the stored values of the items not saved; a secret is given as {"secret": True}, never its value
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Refusal:
    code: str
    #: the thing, in the word the page uses for it
    what: str
    #: one or two sentences a person can act on, naming the fields, the person and the time
    message: str
    current: Current
    #: labels of what the other save changed; empty when the app cannot tell
    changed: tuple[str, ...] = ()
    #: for a form of independent items, which of this person's items were written and which were not
    saved: tuple[str, ...] = ()
    not_saved: tuple[str, ...] = ()

    def __post_init__(self):
        if self.code not in CODES:
            raise ValueError(f"code: {self.code!r} is not one of {', '.join(CODES)}")
        for name in ("what", "message"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name}: a refusal names it in words")
        for name in ("changed", "saved", "not_saved"):
            if not all(isinstance(label, str) for label in getattr(self, name)):
                raise ValueError(f"{name}: a list of labels")
        current = self.current
        if not isinstance(current.token, str):
            raise ValueError("current.token: always a string")
        if not isinstance(current.changed_by, str) or not current.changed_by.strip():
            raise ValueError("current.changed_by: the display name of who saved")
        if not isinstance(current.changed_at, str) or not _UTC_SECONDS.match(current.changed_at):
            raise ValueError("current.changed_at: a time in UTC to the second, such as 2026-01-20T14:32:10Z")
        if not isinstance(current.values, Mapping):
            raise ValueError("current.values: the stored values by label")

    @property
    def status(self) -> int:
        """The HTTP status the refusal is answered with."""
        return CODES[self.code]

    def as_dict(self) -> dict:
        return {"code": self.code, "what": self.what, "message": self.message,
                "changed": list(self.changed), "saved": list(self.saved), "not_saved": list(self.not_saved),
                "current": {"token": self.current.token, "changed_by": self.current.changed_by,
                            "changed_at": self.current.changed_at, "values": dict(self.current.values)}}

    @classmethod
    def from_dict(cls, value: Any) -> "Refusal":
        """The refusal a dict describes; ValueError on a shape a refusal may not have."""
        if not isinstance(value, Mapping):
            raise ValueError("a refusal is an object")
        current = value.get("current")
        if not isinstance(current, Mapping):
            raise ValueError("current: what is stored now is always given")
        lists = {}
        for name in ("changed", "saved", "not_saved"):
            if not isinstance(value.get(name), list):
                raise ValueError(f"{name}: a list of labels")
            lists[name] = tuple(value[name])
        return cls(code=value.get("code"), what=value.get("what"), message=value.get("message"),
                   current=Current(token=current.get("token"), changed_by=current.get("changed_by"),
                                   changed_at=current.get("changed_at"), values=current.get("values")),
                   **lists)
