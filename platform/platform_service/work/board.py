"""What the work pages show: a project's tasks and who holds their parts, and one person's own list.

The pages decide nothing. What a person may do on a row is said here from the same rules the write routes
enforce: an editor or owner takes a part nobody holds, an owner takes a part over or gives it to someone, and
anyone in the project who is not a doer of the task's current round signs it while it is in check.
"""
from __future__ import annotations

from datetime import datetime

from psycopg.rows import tuple_row

from platform_service.work.kinds import KINDS, LABELS

WRITERS = ("editor", "owner")


def _run(conn, statement: str, params=()):
    return conn.cursor(row_factory=tuple_row).execute(statement, params)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _step(kind: str) -> int:
    return KINDS.index(kind) if kind in KINDS else len(KINDS)


def may(role: str | None) -> dict[str, bool]:
    """What a person of `role` may do on the board's parts."""
    return {"take": role in WRITERS, "take_over": role == "owner"}


def part_actions(state: str, holder_subject: str | None, *, person_subject: str, role: str | None) -> dict:
    """What the person may do on one part, while its task is open: take it when nobody holds it (an editor or
    owner), release it when they hold it, take it over or give it away when someone else holds it or nobody
    does (an owner). Nothing changes hands on a task in check or done."""
    open_ = state == "open"
    return {"can_take": open_ and holder_subject is None and role in WRITERS,
            "can_release": open_ and holder_subject == person_subject,
            "can_take_over": open_ and role == "owner" and holder_subject != person_subject}


def tasks(conn, *, person_subject: str, role: str | None) -> list[dict]:
    """Every task of the project, in the order of the steps, with its parts, who holds them since when, and
    what the person may do on each."""
    found = _run(conn, "select id, kind, subject, state, round, checkers_needed, submitted_by_name, submitted_at,"
                       " created_at from work.task").fetchall()
    parts: dict = {}
    for task, key, label, holder_subject, holder_name, since, offered_subject, offered_name in _run(
            conn, "select p.task, p.key, p.label, h.holder_subject, h.holder_name, h.since, h.offered_to_subject,"
                  " h.offered_to_name from work.part p left join work.hold h on h.task = p.task and h.part = p.key"
                  " order by p.task, p.key").fetchall():
        parts.setdefault(task, []).append({
            "key": key, "label": label, "holder_subject": holder_subject, "holder_name": holder_name,
            "since": _iso(since), "offered_to_subject": offered_subject, "offered_to_name": offered_name})
    ordered = sorted(found, key=lambda row: (_step(row[1]), row[8], row[2]))
    return [{"kind": kind, "kind_label": LABELS.get(kind, kind), "subject": subject, "state": state, "round": round_,
             "checkers_needed": needed, "submitted_by_name": by, "submitted_at": _iso(at),
             "parts": [{**part, **part_actions(state, part["holder_subject"], person_subject=person_subject,
                                               role=role)} for part in parts.get(task, [])]}
            for task, kind, subject, state, round_, needed, by, at, _ in ordered]


def may_sign(conn, *, kind: str, subject: str, person_subject: str) -> bool:
    """Whether the person may sign the task now: it is in check, they are not a doer of its round, and they
    have not agreed to its content yet (checks.sign refuses each of these)."""
    return _run(conn, "select 1 from work.task t where t.kind = %s and t.subject = %s and t.state = 'in_check'"
                      " and not exists (select 1 from work.doer d where d.task = t.id and d.round = t.round"
                      "                  and d.person_subject = %s)"
                      " and not exists (select 1 from work.sign_off s where s.task = t.id and s.round = t.round"
                      "                  and s.signer_subject = %s and s.answer = 'agree'"
                      "                  and s.content_hash = t.content_hash)",
                (kind, subject, person_subject, person_subject)).fetchone() is not None


def sign_why_not(conn, *, kind: str, subject: str, person_subject: str) -> str | None:
    """Why the person may not sign a task in check, in the words the sign-off page shows; None when they may, or
    when the task is not in check (the page says its state)."""
    row = _run(conn, "select t.state,"
                     " exists (select 1 from work.doer d where d.task = t.id and d.round = t.round"
                     "         and d.person_subject = %s),"
                     " exists (select 1 from work.sign_off s where s.task = t.id and s.round = t.round"
                     "         and s.signer_subject = %s and s.answer = 'agree' and s.content_hash = t.content_hash)"
                     " from work.task t where t.kind = %s and t.subject = %s",
               (person_subject, person_subject, kind, subject)).fetchone()
    if row is None or row[0] != "in_check":
        return None
    if row[1]:
        return "You worked on this task in this round, so someone else checks it."
    if row[2]:
        return "You agreed to this content already."
    return None


def mine(conn, *, person_subject: str, role: str) -> dict[str, list[dict]]:
    """One person's work in one project: the parts they hold, the parts offered to them, the tasks waiting for
    their sign-off, the tasks sent back to them, and the parts nobody holds that they could take."""
    held = [{"kind": k, "subject": s, "part": p, "label": label, "since": _iso(since)} for k, s, p, label, since in _run(
        conn, "select t.kind, t.subject, h.part, p.label, h.since from work.hold h join work.task t on t.id = h.task"
              " join work.part p on p.task = h.task and p.key = h.part where h.holder_subject = %s"
              " order by h.since", (person_subject,)).fetchall()]
    offered = [{"kind": k, "subject": s, "part": p, "label": label, "holder_name": holder}
               for k, s, p, label, holder in _run(
        conn, "select t.kind, t.subject, h.part, p.label, h.holder_name from work.hold h"
              " join work.task t on t.id = h.task join work.part p on p.task = h.task and p.key = h.part"
              " where h.offered_to_subject = %s order by h.since", (person_subject,)).fetchall()]
    to_sign = [{"kind": k, "subject": s, "round": r, "content_hash": h, "submitted_by_name": by,
                "submitted_at": _iso(at), "checkers_needed": needed}
               for k, s, r, h, by, at, needed in _run(
        conn, "select t.kind, t.subject, t.round, t.content_hash, t.submitted_by_name, t.submitted_at,"
              " t.checkers_needed from work.task t where t.state = 'in_check'"
              " and not exists (select 1 from work.doer d where d.task = t.id and d.round = t.round"
              "                 and d.person_subject = %s)"
              " and not exists (select 1 from work.sign_off s where s.task = t.id and s.round = t.round"
              "                 and s.signer_subject = %s and s.answer = 'agree' and s.content_hash = t.content_hash)"
              " order by t.submitted_at", (person_subject, person_subject)).fetchall()]
    # sent back: the task is open again in the same round, its latest sign-off is a send back, and the person
    # worked on that round
    sent_back = [{"kind": k, "subject": s, "round": r, "by": by, "reason": reason, "at": _iso(at)}
                 for k, s, r, by, reason, at in _run(
        conn, "select t.kind, t.subject, t.round, l.signer_name, l.reason, l.at from work.task t"
              " join lateral (select answer, signer_name, reason, at from work.sign_off s"
              "               where s.task = t.id and s.round = t.round order by s.at desc, s.id desc limit 1) l"
              "   on l.answer = 'send_back'"
              " where t.state = 'open' and exists (select 1 from work.doer d where d.task = t.id"
              "                                     and d.round = t.round and d.person_subject = %s)"
              " order by l.at", (person_subject,)).fetchall()]
    takeable = []
    if role in WRITERS:
        takeable = [{"kind": k, "subject": s, "part": p, "label": label} for k, s, p, label in _run(
            conn, "select t.kind, t.subject, p.key, p.label from work.part p join work.task t on t.id = p.task"
                  " where t.state = 'open' and not exists (select 1 from work.hold h where h.task = p.task"
                  "                                         and h.part = p.key)"
                  " order by t.created_at, p.key").fetchall()]
    return {"held": held, "offered": offered, "to_sign": to_sign, "sent_back": sent_back, "takeable": takeable}
