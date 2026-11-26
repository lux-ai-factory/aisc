"""Holding a part of a task: take, release, hand over, take over.

One person holds a part at a time and only that person saves on it. The apps check that in their own
transaction (work.require_holder); the platform changes who holds what. Taking is an insert that two people
cannot both win: the second waits for the first to commit, then finds the part held.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Hold:
    holder_subject: str
    holder: str
    since: datetime


class AlreadyHeld(Exception):
    """Someone already holds the part."""

    def __init__(self, holder_name: str, since: datetime):
        super().__init__(f"{holder_name} holds this part since {since:%d %b %H:%M}")
        self.holder_name = holder_name
        self.since = since


class NoSuchPart(LookupError):
    """No task of that kind about that subject, or no such part of it."""


def _task(conn, kind: str, subject: str):
    row = conn.execute("select id from work.task where kind = %s and subject = %s", (kind, subject)).fetchone()
    if row is None:
        raise NoSuchPart(f"no {kind} task about {subject}")
    return row[0]


def take(conn, *, kind: str, subject: str, part: str, person_subject: str, person_name: str) -> Hold:
    """Hold a part nobody holds. AlreadyHeld when someone does (even the same person: nothing changes)."""
    task = _task(conn, kind, subject)
    if conn.execute("select 1 from work.part where task = %s and key = %s", (task, part)).fetchone() is None:
        raise NoSuchPart(f"the task has no part {part}")
    row = conn.execute("insert into work.hold (task, part, holder_subject, holder_name) values (%s, %s, %s, %s)"
                       " on conflict (task, part) do nothing returning since",
                       (task, part, person_subject, person_name)).fetchone()
    if row is None:
        held = conn.execute("select holder_name, since from work.hold where task = %s and part = %s",
                            (task, part)).fetchone()
        raise AlreadyHeld(held[0], held[1])
    return Hold(person_subject, person_name, row[0])



class NotHolder(Exception):
    """The person is not the holder of the part."""


class NotOffered(Exception):
    """No hand-over of the part is waiting for this person."""


def _held(conn, kind: str, subject: str, part: str, lock: str = "for update"):
    task = _task(conn, kind, subject)
    row = conn.execute(f"select holder_subject, holder_name, since, offered_to_subject from work.hold"
                       f" where task = %s and part = %s {lock}", (task, part)).fetchone()
    return task, row


def release(conn, *, kind: str, subject: str, part: str, person_subject: str) -> None:
    """The holder lets the part go."""
    task, row = _held(conn, kind, subject, part)
    if row is None or row[0] != person_subject:
        raise NotHolder(f"{person_subject} does not hold this part")
    conn.execute("delete from work.hold where task = %s and part = %s", (task, part))


def offer(conn, *, kind: str, subject: str, part: str, person_subject: str, to_subject: str, to_name: str) -> None:
    """The holder offers the part to someone; it stays the holder's until they accept."""
    task, row = _held(conn, kind, subject, part)
    if row is None or row[0] != person_subject:
        raise NotHolder(f"{person_subject} does not hold this part")
    conn.execute("update work.hold set offered_to_subject = %s, offered_to_name = %s where task = %s and part = %s",
                 (to_subject, to_name, task, part))


def accept(conn, *, kind: str, subject: str, part: str, person_subject: str) -> Hold:
    """The person the part was offered to takes it."""
    task, row = _held(conn, kind, subject, part)
    if row is None or row[3] != person_subject:
        raise NotOffered(f"no hand-over of this part is waiting for {person_subject}")
    since = conn.execute("update work.hold set holder_subject = offered_to_subject, holder_name = offered_to_name,"
                         " since = now(), offered_to_subject = null, offered_to_name = null"
                         " where task = %s and part = %s returning holder_name, since", (task, part)).fetchone()
    return Hold(person_subject, since[0], since[1])


def decline(conn, *, kind: str, subject: str, part: str, person_subject: str) -> None:
    """The person the part was offered to says no; it stays with its holder."""
    task, row = _held(conn, kind, subject, part)
    if row is None or row[3] != person_subject:
        raise NotOffered(f"no hand-over of this part is waiting for {person_subject}")
    conn.execute("update work.hold set offered_to_subject = null, offered_to_name = null"
                 " where task = %s and part = %s", (task, part))


def take_over(conn, *, kind: str, subject: str, part: str, to_subject: str, to_name: str) -> Hold | None:
    """Give the part to `to`, whoever holds it now. Who may do this (an owner, with a reason) is decided by the
    route. Waits for a save in progress: the save holds the row FOR SHARE until it commits. Answers the hold as it
    was before, or None when nobody held the part."""
    task, row = _held(conn, kind, subject, part)
    if conn.execute("select 1 from work.part where task = %s and key = %s", (task, part)).fetchone() is None:
        raise NoSuchPart(f"the task has no part {part}")
    conn.execute("insert into work.hold (task, part, holder_subject, holder_name) values (%s, %s, %s, %s)"
                 " on conflict (task, part) do update set holder_subject = excluded.holder_subject,"
                 " holder_name = excluded.holder_name, since = now(), offered_to_subject = null,"
                 " offered_to_name = null", (task, part, to_subject, to_name))
    return Hold(row[0], row[1], row[2]) if row else None
