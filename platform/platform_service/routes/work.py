"""Who does what: a task's parts and who holds them, and taking, releasing, handing over and taking over a part.

Anyone in the project reads a task. An editor or owner takes a part nobody holds; the holder releases it or
offers it to another editor or owner, who accepts or declines; an owner takes a part over, or gives it to
someone else, with a reason. Every change is an event in the project's ledger, in the same transaction.
"""
from __future__ import annotations

from typing import Annotated

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from platform_service import db
from platform_service.ledger import outbox
from aisc_identity.access import Refused

from platform_service.routes.admission import admitted
from platform_service.work import holds
from platform_service.work.kinds import KINDS

router = APIRouter()
_STRICT = ConfigDict(extra="forbid")
_PART = "/projects/{project}/work/{kind}/{subject}/parts/{part}"


class ToIn(BaseModel):
    model_config = _STRICT
    to: StrictStr = Field(max_length=200)


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


@router.get("/projects/{project}/work/{kind}/{subject}")
def read_task(project: str, kind: str, subject: str, caller: Annotated[Caller, Depends(caller_dependency)]):
    with db.project_connection(_admit(project, caller, "viewer")) as conn:
        task = conn.execute("select id, state from work.task where kind = %s and subject = %s",
                            (_kind(kind), subject)).fetchone()
        if task is None:
            raise HTTPException(status_code=404, detail="No such task.")
        parts = conn.execute("select p.key, p.label, h.holder_subject, h.holder_name, h.since, h.offered_to_subject"
                             "  from work.part p left join work.hold h on h.task = p.task and h.part = p.key"
                             " where p.task = %s order by p.key", (task["id"],)).fetchall()
    return {"kind": kind, "subject": subject, "state": task["state"], "parts": [dict(p) for p in parts]}


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
