"""Saving on a part of a task: one person holds a part at a time, and only that person saves on it.

Every save on the content of a part calls `claim_for_save` in the transaction that writes, before it writes.
The database function work.claim_for_save does the work: while the project's holding switch is off it does
nothing; while it is on, the first save on a part nobody holds takes it, the holder passes, and anyone else is
refused (SQLSTATE AH001, with the holder and since as DETAIL), as is any save on a task in check (AH002, with
who submitted it and when as DETAIL). The hold row is read FOR SHARE, so a take-over waits for this save to
commit.

A refused save raises HoldRefused, whose `refusal` is the refusal object the app answers inside its own
envelope; the transaction is then aborted, so nothing of the save is written. The wording is one case file,
shared/identity/hold-refusal-cases.json, which the TypeScript twin (shared/access-ts/holds.ts) runs too.

`conn` is a psycopg connection (psycopg2's works too); a caller on SQLAlchemy passes the driver's connection.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from aisc_identity.refusal import Current, Refusal

NOT_HOLDER = "AH001"
NOT_FINAL = "AH002"

#: libpq's "idle": connected, no transaction open
_IDLE = 0


class NotInTransaction(RuntimeError):
    """A claim was made outside a transaction: the hold it takes would not guard the write."""


class HoldRefused(Exception):
    """The save may not be written; `refusal` says why, in the words the page shows."""

    def __init__(self, refusal: Refusal):
        super().__init__(refusal.message)
        self.refusal = refusal


def _utc_seconds(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since(moment: datetime, now: datetime) -> str:
    """The time alone when it is today (UTC), else the day and the time."""
    moment, now = moment.astimezone(timezone.utc), now.astimezone(timezone.utc)
    if moment.date() == now.date():
        return f"{moment:%H:%M} UTC"
    return f"{moment.day} {moment:%b %H:%M} UTC"


def refusal_for(sqlstate, detail, *, label, person_name, now: datetime | None = None) -> Refusal | None:
    """The refusal a database error of work.claim_for_save stands for, or None for any other error.
    `detail` is the error's DETAIL text, `label` the part as the page names it."""
    now = now or datetime.now(timezone.utc)
    if sqlstate == NOT_HOLDER:
        held = json.loads(detail or "{}")
        holder = held.get("holder") or "Someone"
        since = datetime.fromisoformat(held["since"]) if held.get("since") else now
        return Refusal(code="not_holder", what=label,
                       message=f"{holder} holds {label} since {_since(since, now)}. Your text is kept below;"
                               " ask them to hand it over, or an owner to give it to you.",
                       current=Current(token="", changed_by=holder, changed_at=_utc_seconds(since)))
    if sqlstate == NOT_FINAL:
        submitted = json.loads(detail or "{}")
        if submitted.get("submitted_by") and submitted.get("submitted_at"):
            at = datetime.fromisoformat(submitted["submitted_at"])
            return Refusal(code="not_final", what=label,
                           message=f"{submitted['submitted_by']} submitted {label} for check at {_since(at, now)},"
                                   " and its content does not change while it is checked. Your text is kept below.",
                           current=Current(token="", changed_by=submitted["submitted_by"],
                                           changed_at=_utc_seconds(at)))
        return Refusal(code="not_final", what=label,
                       message=f"{label} is in check, and its content does not change while it is checked."
                               " Your text is kept below.",
                       current=Current(token="", changed_by=person_name, changed_at=_utc_seconds(now)))
    return None


def _sqlstate(error) -> str | None:
    return getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)


def claim_for_save(conn, kind, subject, part, label, person_subject, person_name) -> None:
    """Claim `part` of the task (`kind`, `subject`) for the person saving, inside the transaction that writes.
    Raises HoldRefused when the save may not be written."""
    if conn.autocommit and conn.info.transaction_status == _IDLE:
        raise NotInTransaction("a claim guards the write only inside the transaction that writes")
    with conn.cursor() as cursor:
        try:
            cursor.execute("SELECT work.claim_for_save(%s, %s, %s, %s, %s, %s)",
                           (kind, subject, part, label, person_subject, person_name))
        except Exception as error:
            refusal = refusal_for(_sqlstate(error), getattr(getattr(error, "diag", None), "message_detail", None),
                                  label=label, person_name=person_name)
            if refusal is None:
                raise
            raise HoldRefused(refusal) from None
