"""Who does what: a task's parts and who holds them, how many people check it, and its submit and sign-offs.

Anyone in the project reads a task. An editor or owner takes a part nobody holds; the holder releases it or
offers it to another editor or owner, who accepts or declines; an owner takes a part over, or gives it to
someone else, with a reason. Owners set how many people check each kind of task. A doer of the task's current
round submits it; anyone in the project who is not one signs it off. Every change is an event in the project's
ledger, in the same transaction.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from platform_service import db
from platform_service.ledger import outbox
from aisc_identity.access import Refused

from platform_service.routes.admission import admitted
from platform_service.work import checks, holds, presets, staffing
from platform_service.work.kinds import KINDS, LABELS

router = APIRouter()
_STRICT = ConfigDict(extra="forbid")
_TASK = "/projects/{project}/work/{kind}/{subject}"
_PART = _TASK + "/parts/{part}"


class ToIn(BaseModel):
    model_config = _STRICT
    to: StrictStr = Field(max_length=200)


class SwitchIn(BaseModel):
    model_config = _STRICT
    on: StrictBool


class CheckersIn(BaseModel):
    model_config = _STRICT
    checkers: StrictInt = Field(ge=0, le=5)


class PresetIn(BaseModel):
    model_config = _STRICT
    preset: StrictStr = Field(max_length=40)

    @field_validator("preset")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in presets.NAMES:
            raise ValueError(f"the presets are {', '.join(presets.NAMES)}")
        return value


class SignIn(BaseModel):
    model_config = _STRICT
    answer: Literal["agree", "send_back"]
    reason: StrictStr | None = Field(default=None, max_length=2000)
    content_hash: StrictStr = Field(max_length=128)

    @field_validator("reason")
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _send_back_says_why(self) -> "SignIn":
        if self.answer == "send_back" and not self.reason:
            raise ValueError("say why the task goes back")
        return self


class TakeOverIn(BaseModel):
    model_config = _STRICT
    to: StrictStr | None = Field(default=None, max_length=200)
    reason: StrictStr = Field(max_length=2000)

    @field_validator("reason")
    @classmethod
    def _said(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("say why the part changes hands")
        return value.strip()


def _admit(project: str, caller: Caller, needed: str) -> str:
    """The project's pid, or the refusal: 404 for a stranger, 403 for too low a rank."""
    try:
        return admitted(project, caller, needed).pid
    except Refused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.message) from None


def _name(caller: Caller) -> str:
    return getattr(caller, "name", None) or caller.username or caller.email or caller.subject


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="No such kind of task.")
    return kind


def _writer(project: str, subject: str) -> dict:
    """The member `subject` as an editor or owner of the project, or 422."""
    for member in db.members(project):
        if member["subject"] == subject:
            if member["role"] in ("editor", "owner"):
                return member
            break
    raise HTTPException(status_code=422, detail="A part can only be held by an editor or owner of the project.")


def _refusal(code: str, message: str, **current) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message, "current": current})


def _event(conn, action: str, kind: str, subject: str, part: str, details: dict, content=None) -> None:
    outbox.emit_project(conn, action, item_type="task_part", item_id=f"{kind}/{subject}/{part}",
                        details={"kind": kind, "part": part, **details}, content=content)


def _where(kind, subject, part):
    return dict(kind=kind, subject=subject, part=part)


def _at(moment: datetime | None) -> str:
    """A time as refusals say it: UTC, to the minute."""
    if moment is None:
        return "an unknown time"
    return f"{moment.astimezone(timezone.utc):%d %b %H:%M} UTC"


def _task_event(conn, action: str, kind: str, subject: str, details: dict, content=None) -> None:
    outbox.emit_project(conn, action, item_type="task", item_id=f"{kind}/{subject}",
                        details={"kind": kind, **details}, content=content)


def _holding(conn) -> bool:
    row = conn.execute("select enabled from work.setting where name = 'holds'").fetchone()
    return bool(row and row["enabled"])


@router.put("/projects/{project}/work/holds")
def switch_holding(project: str, body: SwitchIn, caller: Annotated[Caller, Depends(caller_dependency)]):
    """Holding on or off for the project: while off, saves neither take nor check a part (work.claim_for_save)."""
    pid = _admit(project, caller, "owner")
    with db.project_connection(pid) as conn, conn.transaction():
        conn.execute("insert into work.setting (name, enabled) values ('holds', %s)"
                     " on conflict (name) do update set enabled = excluded.enabled, changed_at = now()", (body.on,))
        outbox.emit_project(conn, "work.holds_switched", item_type="project", item_id=pid, details={"on": body.on})
    return {"on": body.on}


@router.get("/projects/{project}/work/rules")
def read_rules(project: str, caller: Annotated[Caller, Depends(caller_dependency)]):
    """How many people check each kind of task, in the order of the steps."""
    with db.project_connection(_admit(project, caller, "viewer")) as conn:
        found = staffing.rules(conn)
    return {"rules": [{"kind": r.kind, "label": LABELS[r.kind], "checkers": r.checkers, "set_by": r.set_by,
                       "set_at": r.set_at.isoformat() if r.set_at else None} for r in found]}


@router.put("/projects/{project}/work/rules/{kind}")
def change_rule(project: str, kind: str, body: CheckersIn, caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "owner")
    with db.project_connection(pid) as conn, conn.transaction():
        staffing.set_checkers(conn, _kind(kind), body.checkers, by_subject=caller.subject, by_name=_name(caller))
        outbox.emit_project(conn, "staffing.rule_changed", item_type="project", item_id=pid,
                            details={"kind": kind, "checkers": body.checkers})
    return {"kind": kind, "checkers": body.checkers}


@router.post("/projects/{project}/work/preset")
def apply_preset(project: str, body: PresetIn, caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "owner")
    with db.project_connection(pid) as conn, conn.transaction():
        numbers = staffing.apply_preset(conn, body.preset, by_subject=caller.subject, by_name=_name(caller))
        outbox.emit_project(conn, "staffing.preset_applied", item_type="project", item_id=pid,
                            details={"preset": body.preset})
    return {"preset": body.preset, "rules": numbers}


@router.get(_TASK)
def read_task(project: str, kind: str, subject: str, caller: Annotated[Caller, Depends(caller_dependency)]):
    """The task: its round and state, the checkers it needs, its parts and who holds them, and the doers and
    sign-offs of its current round."""
    with db.project_connection(_admit(project, caller, "viewer")) as conn:
        try:
            task = checks.view(conn, kind=_kind(kind), subject=subject)
        except checks.NoSuchTask:
            raise HTTPException(status_code=404, detail="No such task.") from None
        parts = conn.execute("select p.key, p.label, h.holder_subject, h.holder_name, h.since, h.offered_to_subject"
                             "  from work.part p join work.task t on t.id = p.task"
                             "  left join work.hold h on h.task = p.task and h.part = p.key"
                             " where t.kind = %s and t.subject = %s order by p.key", (kind, subject)).fetchall()
        holding = _holding(conn)
    return {"kind": kind, "subject": subject, **task, "holding": holding, "parts": [dict(p) for p in parts]}


@router.post(_TASK + "/submit")
def submit(project: str, kind: str, subject: str, caller: Annotated[Caller, Depends(caller_dependency)]):
    """A doer of the current round submits the task for check: refused while someone else holds a part."""
    pid = _admit(project, caller, "editor")
    label = LABELS[_kind(kind)]
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            done = checks.submit(conn, kind=kind, subject=subject, person_subject=caller.subject,
                                 person_name=_name(caller))
        except checks.NoSuchTask:
            raise HTTPException(status_code=404, detail="No such task.") from None
        except checks.NotOpen as not_open:
            if not_open.state == "done":
                message = f"{label} is done: {not_open.by} submitted it at {_at(not_open.at)}."
            else:
                message = f"{not_open.by} submitted {label} for check at {_at(not_open.at)}; it is in check."
            raise _refusal("not_final", message, changed_by=not_open.by,
                           changed_at=not_open.at.isoformat() if not_open.at else None) from None
        except checks.NotADoer:
            raise HTTPException(status_code=403,
                                detail="Only someone who worked on this task in this round can submit it.") from None
        except checks.HeldByOthers as held:
            names = "; ".join(f"{h.holder} holds {h.label} since {_at(h.since)}" for h in held.held)
            refusal = _refusal("not_holder", f"{names}. They release it, or an owner takes it over, before {label}"
                                             " is submitted.", changed_by=held.held[0].holder,
                               changed_at=held.held[0].since.isoformat())
            refusal.detail["held"] = [{"part": h.part, "label": h.label, "holder_subject": h.holder_subject,
                                       "holder": h.holder, "since": h.since.isoformat()} for h in held.held]
            raise refusal from None
        except checks.NoContentHash:
            raise HTTPException(status_code=422, detail=f"{label} cannot be submitted for check yet.") from None
        _task_event(conn, "task.submitted", kind, subject, {"round": done.round,
                                                            "checkers_needed": done.checkers_needed})
        if done.state == "done":
            _task_event(conn, "task.done", kind, subject, {"round": done.round})
    return {"state": done.state, "round": done.round, "checkers_needed": done.checkers_needed,
            "content_hash": done.content_hash}


@router.post(_TASK + "/sign")
def sign(project: str, kind: str, subject: str, body: SignIn, caller: Annotated[Caller, Depends(caller_dependency)]):
    """Agree, or send back with a reason, on the content the page showed; a doer of the round cannot sign."""
    pid = _admit(project, caller, "viewer")
    label = LABELS[_kind(kind)]
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            done = checks.sign(conn, kind=kind, subject=subject, person_subject=caller.subject,
                               person_name=_name(caller), answer=body.answer, reason=body.reason,
                               content_hash=body.content_hash)
        except checks.NoSuchTask:
            raise HTTPException(status_code=404, detail="No such task.") from None
        except checks.NotInCheck as not_in_check:
            raise _refusal("not_in_check", f"{label} is not waiting for a check: it is {not_in_check}.") from None
        except checks.IsADoer:
            raise HTTPException(status_code=403,
                                detail="You worked on this task in this round, so someone else checks it.") from None
        except checks.ContentMoved:
            raise _refusal("upstream_moved", f"The content of {label} changed since it was shown to you. Open it"
                                             " again and check what it says now.") from None
        except checks.AlreadyAgreed:
            raise _refusal("already_exists", f"You already agreed to {label} as it is now.") from None
        except checks.NoContentHash:
            raise HTTPException(status_code=422, detail=f"{label} cannot be checked yet.") from None
        if body.answer == "send_back":
            _task_event(conn, "task.sent_back", kind, subject, {"round": done.round},
                        content={"reason": body.reason})
        else:
            _task_event(conn, "task.signed", kind, subject, {"round": done.round})
        if done.state == "done":
            _task_event(conn, "task.done", kind, subject, {"round": done.round})
    return {"state": done.state, "round": done.round, "checkers_needed": done.checkers_needed}


@router.post(_PART + "/take")
def take(project: str, kind: str, subject: str, part: str, caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "editor")
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            hold = holds.take(conn, **_where(_kind(kind), subject, part), person_subject=caller.subject,
                              person_name=_name(caller))
        except holds.NoSuchPart as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from None
        except holds.AlreadyHeld as held:
            raise _refusal("not_holder", f"{held.holder_name} holds this part since {held.since:%d %b %H:%M}.",
                           holder=held.holder_name, since=held.since.isoformat()) from None
        _event(conn, "hold.taken", kind, subject, part, {})
    return {"holder_subject": hold.holder_subject, "holder": hold.holder, "since": hold.since.isoformat()}


@router.post(_PART + "/release")
def release(project: str, kind: str, subject: str, part: str,
            caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "viewer")
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            holds.release(conn, **_where(_kind(kind), subject, part), person_subject=caller.subject)
        except holds.NoSuchPart as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from None
        except holds.NotHolder:
            raise _refusal("not_holder", "Only the person holding this part can release it.") from None
        _event(conn, "hold.released", kind, subject, part, {})
    return {"released": True}


@router.post(_PART + "/offer")
def offer(project: str, kind: str, subject: str, part: str, body: ToIn,
          caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "editor")
    to = _writer(project, body.to)
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            holds.offer(conn, **_where(_kind(kind), subject, part), person_subject=caller.subject,
                        to_subject=to["subject"], to_name=to["email"] or to["subject"])
        except holds.NoSuchPart as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from None
        except holds.NotHolder:
            raise _refusal("not_holder", "Only the person holding this part can hand it over.") from None
        _event(conn, "hold.offered", kind, subject, part, {})
    return {"offered_to": to["subject"]}


@router.post(_PART + "/accept")
def accept(project: str, kind: str, subject: str, part: str, caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "editor")
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            hold = holds.accept(conn, **_where(_kind(kind), subject, part), person_subject=caller.subject)
        except holds.NoSuchPart as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from None
        except holds.NotOffered:
            raise _refusal("not_holder", "This part was not offered to you.") from None
        _event(conn, "hold.handed_over", kind, subject, part, {})
    return {"holder_subject": hold.holder_subject, "since": hold.since.isoformat()}


@router.post(_PART + "/decline")
def decline(project: str, kind: str, subject: str, part: str,
            caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "viewer")
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            holds.decline(conn, **_where(_kind(kind), subject, part), person_subject=caller.subject)
        except holds.NoSuchPart as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from None
        except holds.NotOffered:
            raise _refusal("not_holder", "This part was not offered to you.") from None
        _event(conn, "hold.offer_declined", kind, subject, part, {})
    return {"declined": True}


@router.post(_PART + "/take-over")
def take_over(project: str, kind: str, subject: str, part: str, body: TakeOverIn,
              caller: Annotated[Caller, Depends(caller_dependency)]):
    pid = _admit(project, caller, "owner")
    to = _writer(project, body.to) if body.to else {"subject": caller.subject, "email": _name(caller)}
    with db.project_connection(pid) as conn, conn.transaction():
        try:
            before = holds.take_over(conn, **_where(_kind(kind), subject, part), to_subject=to["subject"],
                                     to_name=to["email"] or to["subject"])
        except holds.NoSuchPart as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from None
        _event(conn, "hold.taken_over", kind, subject, part, {"had_holder": before is not None},
               content={"reason": body.reason})
    return {"holder_subject": to["subject"], "previous_holder_subject": before.holder_subject if before else None}
