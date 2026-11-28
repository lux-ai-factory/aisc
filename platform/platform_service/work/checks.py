"""Submitting a task for check, and signing it off.

A doer of the task's current round submits it. The task row is locked first, so a save in progress (which
holds it FOR SHARE in work.claim_for_save) commits before, and every save after sees the task in check. The
content hash (work.content_hash) and the card state (work.card_state) are stored with it, and the number of
checkers is copied from the rule, so changing the rule later does not change a check under way.

Anyone in the project who is not a doer of the current round signs: agree, or send back with a reason, on
the content hash the page showed. The hash is compared with the content as it is now, in the same
transaction. The task is done when the agreements of the current round on the submitted content reach
checkers_needed. A send back opens the task again in the same round, each part with its last holder.

Both stamp a card state, so no card may be stored between reading it and committing (section 3 of the spec).
For every kind but the card they take the card lock shared, first. The card's own task is the exception: every
card store claims it, holding its row FOR SHARE until it commits, and a correction takes the card lock only after
its claim, so a submit holding the lock while it waits for that claim would deadlock with it. Locking the task
row FOR UPDATE already keeps every card store out until the submit or sign-off commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from platform_service.work import staffing


def _run(conn, statement: str, params=()):
    return conn.cursor(row_factory=tuple_row).execute(statement, params)


@dataclass(frozen=True)
class Held:
    part: str
    label: str
    holder_subject: str
    holder: str
    since: datetime


class NoSuchTask(LookupError):
    """No task of that kind about that subject."""


class NotOpen(Exception):
    """The task is in check or done, so it cannot be submitted."""

    def __init__(self, state: str, by: str | None, at: datetime | None):
        super().__init__(state)
        self.state, self.by, self.at = state, by, at


class NotADoer(Exception):
    """Only a doer of the current round submits."""


class HeldByOthers(Exception):
    """Someone else holds a part: they release it, or an owner takes it over."""

    def __init__(self, held: list[Held]):
        super().__init__(", ".join(f"{h.holder} holds {h.label}" for h in held))
        self.held = held


class CardMoved(Exception):
    """The card state moved since the page the submit came from was drawn: the person is asked once."""

    def __init__(self, now: dict):
        super().__init__(f"the card is now version {now['number']} revision {now['revision']}")
        self.now = now


class NoContentHash(Exception):
    """This kind of task has no content to check yet."""


class NotInCheck(Exception):
    """The task is not waiting for a check."""


class IsADoer(Exception):
    """A doer of the current round does not check it."""


class AlreadyAgreed(Exception):
    """The person already agreed to this content in this round."""


class ContentMoved(Exception):
    """The content is not the one the page showed, or not the one submitted."""


@dataclass(frozen=True)
class Outcome:
    state: str
    round: int
    checkers_needed: int
    content_hash: str


def _card_lock_shared(conn, kind: str) -> None:
    """The card lock, shared, for every kind but the card itself (see the module's docstring)."""
    if kind != "describe_system":
        _run(conn, "select pg_advisory_xact_lock_shared(hashtext('project.system'))")


def _locked_task(conn, kind: str, subject: str):
    row = _run(conn, "select id, state, round, submitted_by_name, submitted_at, checkers_needed, content_hash"
                     "  from work.task where kind = %s and subject = %s for update", (kind, subject)).fetchone()
    if row is None:
        raise NoSuchTask(f"no {kind} task about {subject}")
    return row


def _is_doer(conn, task, round_: int, person_subject: str) -> bool:
    return _run(conn, "select 1 from work.doer where task = %s and round = %s and person_subject = %s limit 1",
                (task, round_, person_subject)).fetchone() is not None


def _content_hash(conn, kind: str, subject: str) -> str:
    _run(conn, "savepoint content_hash")
    try:
        value = _run(conn, "select work.content_hash(%s, %s)", (kind, subject)).fetchone()[0]
    except Exception as error:
        if getattr(error, "sqlstate", None) != "AH003":
            raise
        _run(conn, "rollback to savepoint content_hash")
        raise NoContentHash(kind) from None
    _run(conn, "release savepoint content_hash")
    return value


def _card_moved(conn, drawn: dict | None) -> None:
    """CardMoved when `drawn` ({"version", "revision"}, the card state the page was drawn on) is not the latest
    card state; nothing when the page named none."""
    if drawn is None:
        return
    now = _run(conn, "select work.card_change()").fetchone()[0]
    if now is None:
        return
    if (str(drawn.get("version")), drawn.get("revision")) != (now["version"], now["revision"]):
        raise CardMoved(now)


def submit(conn, *, kind: str, subject: str, person_subject: str, person_name: str,
           drawn_card_state: dict | None = None) -> Outcome:
    """Submit the task for check, or finish it when its kind needs no checker. `drawn_card_state` is the card
    state the submitting page was drawn on: when the card moved since, CardMoved, and nothing changes."""
    _card_lock_shared(conn, kind)
    task, state, round_, by, at, _, _ = _locked_task(conn, kind, subject)
    if state != "open":
        raise NotOpen(state, by, at)
    if not _is_doer(conn, task, round_, person_subject):
        raise NotADoer(person_subject)
    holds = _run(conn, "select h.part, p.label, h.holder_subject, h.holder_name, h.since from work.hold h"
                       "  join work.part p on p.task = h.task and p.key = h.part"
                       " where h.task = %s order by h.part for update of h", (task,)).fetchall()
    others = [Held(*row) for row in holds if row[2] != person_subject]
    if others:
        raise HeldByOthers(others)
    _card_moved(conn, drawn_card_state)
    content_hash = _content_hash(conn, kind, subject)
    needed = staffing.checkers(conn, kind)
    state = "done" if needed == 0 else "in_check"
    released = {row[0]: [row[2], row[3]] for row in holds}
    _run(conn, "delete from work.hold where task = %s", (task,))
    _run(conn, "update work.task set state = %s, checkers_needed = %s, content_hash = %s,"
               " card_state = work.card_state(), submitted_by_subject = %s, submitted_by_name = %s,"
               " submitted_at = now(), released = %s where id = %s",
         (state, needed, content_hash, person_subject, person_name, Jsonb(released), task))
    return Outcome(state, round_, needed, content_hash)


def _last_holders(conn, task, round_: int) -> dict[str, tuple[str, str]]:
    """Who held each part last: the holder its submit released, else the doer of the round who came to it
    last."""
    last = {part: (subject, name) for part, subject, name in _run(
        conn, "select distinct on (part) part, person_subject, person_name from work.doer"
              " where task = %s and round = %s order by part, first_saved_at desc", (task, round_)).fetchall()}
    released = _run(conn, "select released from work.task where id = %s", (task,)).fetchone()[0] or {}
    last.update({part: (who[0], who[1]) for part, who in released.items()})
    return last


def sign(conn, *, kind: str, subject: str, person_subject: str, person_name: str, answer: str,
         reason: str | None, content_hash: str) -> Outcome:
    """Record a sign-off; the task is done, or back to open on a send back."""
    _card_lock_shared(conn, kind)
    task, state, round_, _, _, needed, submitted_hash = _locked_task(conn, kind, subject)
    if state != "in_check":
        raise NotInCheck(state)
    if _is_doer(conn, task, round_, person_subject):
        raise IsADoer(person_subject)
    now = _content_hash(conn, kind, subject)
    if content_hash != now or now != submitted_hash:
        raise ContentMoved(kind)
    if answer == "agree" and _run(
            conn, "select 1 from work.sign_off where task = %s and round = %s and signer_subject = %s"
                  " and answer = 'agree' and content_hash = %s", (task, round_, person_subject, now)).fetchone():
        raise AlreadyAgreed(person_subject)
    _run(conn, "insert into work.sign_off (task, round, signer_subject, signer_name, answer, reason, content_hash,"
               " card_state) values (%s, %s, %s, %s, %s, %s, %s, work.card_state())",
         (task, round_, person_subject, person_name, answer, reason, now))
    if answer == "send_back":
        for part, (holder_subject, holder_name) in _last_holders(conn, task, round_).items():
            _run(conn, "insert into work.hold (task, part, holder_subject, holder_name) values (%s, %s, %s, %s)"
                       " on conflict (task, part) do nothing", (task, part, holder_subject, holder_name))
        _run(conn, "update work.task set state = 'open' where id = %s", (task,))
        return Outcome("open", round_, needed, now)
    agreed = _run(conn, "select count(distinct signer_subject) from work.sign_off where task = %s and round = %s"
                        " and answer = 'agree' and content_hash = %s", (task, round_, now)).fetchone()[0]
    if agreed >= needed:
        _run(conn, "update work.task set state = 'done' where id = %s", (task,))
        return Outcome("done", round_, needed, now)
    return Outcome("in_check", round_, needed, now)


def view(conn, *, kind: str, subject: str) -> dict:
    """The task's round, state, checkers needed, last submit, and the doers and sign-offs of its round."""
    row = _run(conn, "select id, state, round, checkers_needed, content_hash, card_state, submitted_by_subject,"
                     " submitted_by_name, submitted_at from work.task where kind = %s and subject = %s",
               (kind, subject)).fetchone()
    if row is None:
        raise NoSuchTask(f"no {kind} task about {subject}")
    task, state, round_, needed, content_hash, card_state, by_subject, by_name, at = row
    doers = _run(conn, "select d.part, p.label, d.person_subject, d.person_name, d.first_saved_at from work.doer d"
                       "  left join work.part p on p.task = d.task and p.key = d.part"
                       " where d.task = %s and d.round = %s order by d.part, d.first_saved_at",
                 (task, round_)).fetchall()
    sign_offs = _run(conn, "select signer_subject, signer_name, answer, reason, content_hash, card_state, at"
                           "  from work.sign_off where task = %s and round = %s order by at, id",
                     (task, round_)).fetchall()
    return {
        "round": round_, "state": state, "checkers_needed": needed, "content_hash": content_hash,
        "card_state": card_state, "submitted_by": by_subject, "submitted_by_name": by_name,
        "submitted_at": at.isoformat() if at else None,
        "doers": [{"part": p, "label": label, "person_subject": s, "person_name": n,
                   "first_saved_at": f.isoformat()} for p, label, s, n, f in doers],
        "sign_offs": [{"signer_subject": s, "signer_name": n, "answer": a, "reason": r, "content_hash": h,
                       "card_state": c, "at": t.isoformat()} for s, n, a, r, h, c, t in sign_offs],
    }
