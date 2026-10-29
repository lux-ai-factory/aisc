"""The ledger: reading, export, administration, the internal event route and the beacon."""
from __future__ import annotations

import logging
import threading
import uuid

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency, requires_role
from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import db
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import ADMIN_ROLE, _internal, _ledger_presented, no_project, role_or_404

router = APIRouter()

logger = logging.getLogger(__name__)


_EVENT_FILTERS = {"step": "step", "app": "source_app", "action": "action", "item_type": "item_type",
                  "item_id": "item_id", "card_version": "card_version", "outcome": "outcome"}
_PAGE = 100


def _ledger_project(slug: str, caller: Caller) -> tuple[dict, str, str]:
    """(project, role, its log) for a member; a stranger gets 404, and so does a project with no log."""
    from platform_service.ledger import provision

    role = role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    log = provision.database_for(str(found["pid"]))
    if log is None:
        from platform_service.ledger import witness as ledger_witness

        if ledger_witness.mode() == "off":
            raise HTTPException(status_code=404, detail="the ledger is off on this install (LEDGER_MODE=off):"
                                                        " nothing is recorded")
        raise HTTPException(status_code=404, detail="this project is waiting for its ledger database: the"
                                                    " pool had none free when it was made; the ledger-pool"
                                                    " service gives it one at the stack's next start, and"
                                                    " its events are kept until then")
    return found, role, log


def _ledger_unavailable(exc) -> HTTPException:
    return HTTPException(status_code=503, detail=f"the ledger can't be read now: {exc.__class__.__name__}")


def _ledger_failure(log: str, exc) -> HTTPException:
    """A read that failed in the store: a tamper alarm is 409, as on one entry; any other ledger error is
    503, never a bare 500."""
    from platform_service.ledger.store import TamperAlarm

    if isinstance(exc, TamperAlarm):
        logger.error("ledger %s: the log failed verification: %s", log, exc)
        return HTTPException(status_code=409, detail="tamper alarm: the log doesn't verify")
    return _ledger_unavailable(exc)


def _person(pid: str, ref: str | None) -> dict | None:
    from platform_service.ledger import actors

    if not ref:
        return None
    try:
        who = actors.resolve(pid, ref)
    except actors.MappingAlarm:
        return {"ref": ref, "sub": None, "name": None, "alarm": "mapping"}
    if who is None:
        return {"ref": ref, "sub": None, "name": None, "erased": True}
    return {"ref": ref, "sub": who[0], "name": who[1]}


def _shown(pid: str, entry) -> dict:
    data = entry.as_dict()
    data["actor"] = {"kind": entry.actor_kind, **(_person(pid, entry.actor_ref) or {"ref": None})}
    if data.get("on_behalf_of_ref"):
        data["on_behalf_of"] = _person(pid, data["on_behalf_of_ref"])
    data["verified"] = True
    return data


def _verified_entry(log: str, seq: int):
    from platform_service import ledger
    from platform_service.ledger.store import LedgerUnavailable, TamperAlarm

    try:
        return ledger.current().get(log, seq)
    except TamperAlarm as exc:
        logger.error("ledger %s: entry %s failed verification: %s", log, seq, exc)
        raise HTTPException(status_code=409, detail=f"tamper alarm: entry {seq} doesn't verify") from None
    except LedgerUnavailable as exc:
        raise _ledger_unavailable(exc) from None
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no entry {seq}") from None


def _index_complete(pid: str, log: str) -> bool:
    """Every seq of the log has its index row: count, min and max against the store's head.
    A row may be missing for a moment between the relay's append and its index (a crash there too): the
    relay is run once for this log before this says no, waiting (at most relay.READ_WAIT_S, then
    LedgerUnavailable) for the relay worker if it is on the log (its append and its index row are a
    moment apart)."""
    from platform_service import ledger
    from platform_service.ledger import relay

    def counted():
        with db.pool().connection() as conn:
            row = conn.execute("SELECT count(*) AS n, coalesce(min(seq), 1) AS lo, coalesce(max(seq), 0) AS hi"
                               " FROM ledger.event_index WHERE log = %s", (log,)).fetchone()
        head = ledger.current().head(log).seq
        return row["n"] == head and row["hi"] == head and row["lo"] == 1 or (head == 0 and row["n"] == 0)
    if counted():
        return True
    relay.relay_once(pid, wait=relay.READ_WAIT_S)       # bounded: a stuck relay is a 503, not a hung read
    return counted()


def _filters(q) -> list[tuple[str, object]]:
    """The query's filters, checked: a malformed one is 422, never a database error."""
    from datetime import datetime

    out = []
    for name, column in _EVENT_FILTERS.items():
        value = q.get(name)
        if not value:
            continue
        if name == "step":
            if not value.isdigit():
                raise HTTPException(status_code=422, detail="step: a number")
            value = int(value)
        if name == "card_version":
            try:
                value = str(uuid.UUID(value))
            except ValueError:
                raise HTTPException(status_code=422, detail="card_version: a version id") from None
        out.append((f"{column} = %s", value))
    for name, op in (("from", ">="), ("to", "<=")):
        if q.get(name):
            try:
                out.append((f"occurred_at {op} %s", datetime.fromisoformat(q[name])))
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{name}: an ISO 8601 time") from None
    if q.get("cursor"):
        if not q["cursor"].isdigit():
            raise HTTPException(status_code=422, detail="cursor: a seq")
        out.append(("seq < %s", int(q["cursor"])))
    return out


def _page_size(q) -> int:
    """`limit`: how many entries a page holds, 1 to _PAGE (the Activity log asks for 20); _PAGE without it."""
    value = q.get("limit")
    if not value:
        return _PAGE
    if not value.isdigit() or not 1 <= int(value) <= _PAGE:
        raise HTTPException(status_code=422, detail=f"limit: a number from 1 to {_PAGE}")
    return int(value)


@router.get("/projects/{slug}/ledger/events")
def ledger_events(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """The project's entries, newest first, filtered on the read index, each verified against the store
    before it is shown. `actor` is a subject; `ai=true` keeps AI actions; `from`/`to` bound occurred_at;
    `cursor` is the last seq of the previous page; `limit` is the page size (1 to 100, 100 without it).
    409 "tamper alarm" when the log doesn't verify, 409 "index alarm" when the read index misses entries
    of the log, 503 when the ledger can't be read (also when the relay holds the log over
    relay.READ_WAIT_S)."""
    from platform_service.ledger import actors

    from platform_service.ledger import index as ledger_index
    from platform_service.ledger.store import LedgerError

    found, _, log = _ledger_project(slug, caller)
    pid = str(found["pid"])
    q = request.query_params
    where, args = ["log = %s"], [log]
    page = _page_size(q)
    for clause, value in _filters(q):
        where.append(clause)
        args.append(value)
    try:
        complete = _index_complete(pid, log)
    except LedgerError as exc:
        raise _ledger_failure(log, exc) from None
    if not complete:
        logger.error("ledger %s: the read index doesn't account for every entry", log)
        raise HTTPException(status_code=409, detail="index alarm: the read index is missing entries of the log")
    if q.get("actor"):
        ref = actors.ref_of(pid, q["actor"])
        if ref is None:
            return {"events": [], "next": None}
        where.append("actor_ref = %s")
        args.append(ref)
    if q.get("ai") in ("1", "true"):
        where.append("actor_kind = 'ai'")
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT * FROM ledger.event_index WHERE {' AND '.join(where)}"
                            f" ORDER BY seq DESC LIMIT {page}", args).fetchall()
    events = []
    for row in rows:
        entry = _verified_entry(log, row["seq"])
        logged = entry.as_dict()
        if not ledger_index.agrees(row, logged):
            logger.error("ledger %s: index row %s disagrees with the log", log, row["seq"])
            raise HTTPException(status_code=409, detail=f"index alarm: row {row['seq']} disagrees with the log")
        events.append(_shown(pid, entry))
    return {"events": events, "next": rows[-1]["seq"] if len(rows) == page else None}



@router.get("/projects/{slug}/ledger/head")
def ledger_head(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """The project log's newest entry, verified: its seq and the sha256 of its canonical form. A generated
    report prints it, and verify-ledger-export.py --anchor finds it in an export.
    404 while the log is empty, 409 "tamper alarm" when it doesn't verify, 503 when it can't be read."""
    import hashlib

    from platform_service import ledger
    from platform_service.ledger.canonical import canonical
    from platform_service.ledger.store import LedgerError

    _, _, log = _ledger_project(slug, caller)
    try:
        seq = ledger.current().head(log).seq
    except LedgerError as exc:
        raise _ledger_failure(log, exc) from None
    if seq == 0:
        raise HTTPException(status_code=404, detail="the project's log has no entry yet")
    return {"seq": seq, "entry_sha256": hashlib.sha256(canonical(_verified_entry(log, seq).as_dict())).hexdigest()}


@router.get("/projects/{slug}/ledger/export")
def ledger_export(slug: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """The whole log as JSON lines, for scripts/verify-ledger-export.py (EXPORT_ROLES only)."""
    import json as _json

    from platform_service.ledger import export, settings as ledger_settings
    from platform_service.ledger.store import LedgerUnavailable, TamperAlarm

    found, role, _ = _ledger_project(slug, caller)
    if role not in ledger_settings.EXPORT_ROLES:
        raise HTTPException(status_code=403, detail="the export is for the project's owners")
    try:
        lines = export.lines(str(found["pid"]))
    except TamperAlarm as exc:
        raise HTTPException(status_code=409, detail=f"tamper alarm: {exc}") from None
    except LedgerUnavailable as exc:
        raise _ledger_unavailable(exc) from None
    logger.info("project %s: ledger exported by %s (%d entries)", found["pid"], caller.subject, len(lines) - 1)
    body = "\n".join(_json.dumps(line, separators=(",", ":"), ensure_ascii=False) for line in lines) + "\n"
    return Response(body, media_type="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="ledger-{found["slug"]}.jsonl"',
                             "Cache-Control": "no-store"})


@router.get("/ledger/projects")
def ledger_projects(caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> dict:
    """Every project's log for a platform admin: the head it verifies to (or the alarm), what the server
    holds now (`server_head`, not trusted: what a re-anchor would trust), and the platform log's own."""
    from platform_service import ledger
    from platform_service.ledger import provision
    from platform_service.ledger.naming import PLATFORM_DB
    from platform_service.ledger.store import LedgerError

    store = ledger.current()

    def heads(log: str) -> dict:
        row = {"log": log, "head": None, "server_head": None, "trusted_head": None}
        try:
            row["server_head"], row["trusted_head"] = store.server_head(log), store.trusted_head(log)
            head = store.head(log)
            row["head"] = {"seq": head.seq, "state_hash": head.state_hash}
        except LedgerError as exc:
            row["error"] = exc.__class__.__name__
        return row
    out = []
    for p in db.list_projects():
        pid = str(p["pid"])
        log = provision.database_for(pid)
        out.append({"pid": pid, "slug": p["slug"], **(heads(log) if log else {"log": None, "head": None})})
    return {"projects": out, "platform": heads(PLATFORM_DB)}


class HeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tx: int
    hash: StrictStr


class ReanchorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pid: StrictStr                                                    # a project's pid, or "platform"
    expected_head: HeadIn                                             # the server_head the admin checked


@router.post("/ledger/reanchor")
def ledger_reanchor(body: ReanchorIn, caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> dict:
    """After an immudb restore (runbook ledger-restore.md): trust the server's current state for one log,
    if it is the head the admin checked (GET /ledger/projects). Recorded in the platform log as
    `ledger.reanchored` with both heads, whatever LEDGER_MODE says, and recorded FIRST: if the platform
    log can't take the record, nothing changes. A restored platform log is re-anchored first
    (pid "platform"), then recorded in itself."""
    from datetime import datetime, timezone

    from platform_service import ledger
    from platform_service.ledger import actors, outbox, provision, registry, relay
    from platform_service.ledger.naming import PLATFORM_DB
    from platform_service.ledger.store import HeadChanged, LedgerError, LedgerUnavailable, UnknownDatabase

    if body.pid == "platform":
        log = PLATFORM_DB
    else:
        if not looks_like_pid(body.pid) or db.get_project(body.pid) is None:
            raise no_project(body.pid)
        log = provision.database_for(body.pid)
        if log is None:
            raise HTTPException(status_code=404, detail="this project has no ledger")
    store = ledger.current()
    expected = body.expected_head.model_dump()

    def record(old, new):
        entry = {"event_id": str(uuid.uuid4()), "occurred_at": relay._iso(datetime.now(timezone.utc)),
                 "project_pid": None, "step": 0, "source_app": "platform", "action": "ledger.reanchored",
                 "actor_kind": "user",
                 "actor_ref": actors.ref_for(None, caller.subject, caller.username or caller.subject),
                 "request_id": outbox.current_request.get(), "item_type": "ledger", "item_id": log, "outcome": "ok",
                 "details": {"old_head": old, "new_head": new, "project": body.pid}, "verified": True,
                 "registry_version": registry.VERSION}
        seq = store.append(PLATFORM_DB, entry)
        relay._index(PLATFORM_DB, seq, entry, None)
        return seq

    try:
        with relay._log_lock(log):
            if store.server_head(log) != expected:
                raise HeadChanged(log)
            if log == PLATFORM_DB:
                before = store.state(log)
                old, new = store.reanchor(log, expected)
                try:
                    seq = record(old, new)
                except LedgerError:
                    store.set_state(log, before)                      # not recorded: not trusted either
                    raise
            else:
                old = store.trusted_head(log)
                with relay._log_lock(PLATFORM_DB):
                    seq = record(old, expected)                       # the record first
                old, new = store.reanchor(log, expected)
    except HeadChanged:
        raise HTTPException(status_code=409, detail="the server's head is not the one you checked: look again") from None
    except UnknownDatabase:
        raise HTTPException(status_code=404, detail="the store has no such log") from None
    except LedgerUnavailable as exc:
        raise _ledger_unavailable(exc) from None
    except LedgerError as exc:
        raise HTTPException(status_code=409, detail=f"the re-anchor could not be recorded ({exc.__class__.__name__}):"
                            " re-anchor the platform log first") from None
    logger.warning("ledger %s re-anchored by %s: %s -> %s", log, caller.subject, old, new)
    return {"log": log, "old_head": old, "new_head": new, "recorded": seq}


# The internal route: callers without an outbox. Each caller has its own token and
# is the event's emitter; the relay checks it may emit that action and that the run is real.
LEDGER_CALLERS = {"qualification_agents": "PLATFORM_LEDGER_AGENTS_TOKEN", "engine": "PLATFORM_LEDGER_ENGINE_TOKEN",
                  "dashboard": "PLATFORM_LEDGER_DASHBOARD_TOKEN"}
_INTERNAL_COLUMNS = ("event_id", "request_id", "run_id", "action", "item_type", "item_id", "item_version",
                     "card_version", "content", "before", "after", "details", "outcome", "model", "registry_version")


def _ledger_caller(request: Request) -> tuple[str | None, JSONResponse | None]:
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return None, _internal(404, {"detail": "not here"})
    try:
        return identify(request.headers.get(SERVICE_TOKEN_HEADER), LEDGER_CALLERS), None
    except ServiceRefused as refused:
        if refused.status == 503:
            logger.error("ledger: the internal route is closed: %s", refused.detail)
        return None, _internal(refused.status, {"detail": refused.detail})


#: What the internal route takes: the body, and the free-text identifiers.
LEDGER_EVENT_MAX_BYTES = 32 * 1024
LEDGER_FIELD_MAX = 256
#: The outcomes an emitter may state; `refused` is the relay's own word.
EMITTER_OUTCOMES = ("ok", "failed")


def _malformed(event) -> str | None:
    from platform_service.ledger import registry

    if not isinstance(event, dict):
        return "the body must be one event object"
    action = registry.REGISTRY.get(event.get("action")) if isinstance(event.get("action"), str) else None
    for field in ("event_id", "request_id"):
        if field == "request_id" and event.get(field) is None and action is not None and "user" in action.actor_kinds:
            # a person's event with no request id (the witness gave none): the relay records it as rejected
            # (missing_request), so it shows in the Activity log, as an app outbox's event with no request
            # does. An AI or worker event still needs one here.
            continue
        try:
            uuid.UUID(str(event.get(field)))
        except ValueError:
            return f"{field}: a UUID is needed"
    if not isinstance(event.get("action"), str) or not event["action"]:
        return "action: needed"
    if not isinstance(event.get("details", {}), dict):
        return "details: an object"
    for field in ("action", "item_type", "item_id", "item_version", "model", "card_version"):
        value = event.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > LEDGER_FIELD_MAX):
            return f"{field}: text of at most {LEDGER_FIELD_MAX} characters"
    if event.get("registry_version") is not None and (not isinstance(event["registry_version"], int)
                                                      or isinstance(event["registry_version"], bool)):
        return "registry_version: a number"
    if event.get("outcome", "ok") not in EMITTER_OUTCOMES:
        return f"outcome: one of {', '.join(EMITTER_OUTCOMES)}"
    if action is not None and {"ai", "worker"} & set(action.actor_kinds) and "user" not in action.actor_kinds:
        try:
            uuid.UUID(str(event.get("run_id")))
        except ValueError:
            return "run_id: an AI or worker event belongs to a run"
        if "ai" in action.actor_kinds and not (isinstance(event.get("model"), str) and event["model"]):
            return "model: an AI event names its model"
    return None


@router.post("/internal/projects/{pid}/ledger/events", status_code=202)
async def ledger_internal_event(pid: str, request: Request) -> JSONResponse:
    """Queue one event in core.outbox, its emitter the caller; accepted or rejected by the relay (202)."""
    from starlette.concurrency import run_in_threadpool

    caller, refused = _ledger_caller(request)
    if refused:
        return refused
    if not looks_like_pid(pid):
        return _internal(404, {"detail": f"no project {pid!r}"})
    raw = b""
    async for chunk in request.stream():                              # never more than the cap in memory
        raw += chunk
        if len(raw) > LEDGER_EVENT_MAX_BYTES:
            return _internal(413, {"detail": f"an event is at most {LEDGER_EVENT_MAX_BYTES} bytes"})
    try:
        import json as _json

        event = _json.loads(raw)
    except ValueError:
        return _internal(422, {"detail": "the body must be JSON"})
    problem = _malformed(event)
    if problem:
        return _internal(422, {"detail": problem})
    return await run_in_threadpool(_queue_internal, pid, caller, event)


_OUTBOX_SENT = ("emitter", "project_pid", "request_id", "run_id", "action", "item_type", "item_id", "item_version", "registry_version",
                "card_version", "content", "before", "after", "details", "outcome", "model", "extra")


def _sent_form(row: dict) -> dict:
    """An outbox row, or a new event, in one comparable form (uuids as text, JSON round-tripped)."""
    import json as _json

    return _json.loads(_json.dumps({k: (None if row.get(k) is None else row.get(k)) for k in _OUTBOX_SENT},
                                   default=str, sort_keys=True))


def _with_config_masked(row: dict) -> dict:
    """A configuration event's row with its config's secrets masked; any other row as it is."""
    from platform_service.ledger.config_secrets import masked_for_ledger

    content = row.get("content")
    if row.get("action") != "engine.plugin.configured" or not isinstance(content, dict) or "config" not in content:
        return row
    return {**row, "content": {**content, "config": masked_for_ledger(content["config"])}}


def _queue_internal(pid: str, caller: str, event: dict) -> JSONResponse:
    from psycopg import errors as pg_errors

    from platform_service.ledger import outbox

    if db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    extra = {k: v for k, v in event.items() if k not in _INTERNAL_COLUMNS}
    fields = dict(item_type=event.get("item_type"), item_id=event.get("item_id"), details=event.get("details") or {},
                  content=event.get("content"), before=event.get("before"), after=event.get("after"),
                  item_version=event.get("item_version"), card_version=event.get("card_version"),
                  request_id=event.get("request_id"), emitter=caller, run_id=event.get("run_id"), model=event.get("model"),
                  event_id=event["event_id"], outcome=event.get("outcome") or "ok", extra=extra,
                  registry_version=event.get("registry_version"))
    with db.pool().connection() as conn:
        try:
            with conn.transaction():
                outbox.emit(conn, event["action"], project_pid=pid, **fields)
            return _internal(202, {"queued": event["event_id"]})
        except pg_errors.UniqueViolation:
            pass
        stored = conn.execute("SELECT * FROM core.outbox WHERE event_id = %s", (event["event_id"],)).fetchone()
    sent = {**fields, "action": event["action"], "project_pid": pid}
    for key in ("request_id", "run_id", "card_version"):
        sent[key] = None if sent[key] is None else str(uuid.UUID(str(sent[key])))
    if stored is not None and _sent_form(stored) == _sent_form(sent):
        return _internal(202, {"queued": event["event_id"], "replay": True})   # a retry: the same event
    if stored is not None and _sent_form(_with_config_masked(stored)) == _sent_form(sent):
        # the engine masks a configuration's secrets on delivery: its masked re-send of an event the platform
        # holds unmasked is the same event, a retry; the stored row stays as it is
        return _internal(202, {"queued": event["event_id"], "replay": True})
    logger.error("ledger: event %s re-sent by %s with other content (or by another caller)", event["event_id"], caller)
    return _internal(409, {"detail": "this event_id was already sent with other content or by another caller"})


# The beacon: what only the browser knows. Witnessed, small, best effort, kept outside
# immudb for PAGE_VIEW_RETENTION, every row marked as the browser's word.
BEACON_MAX_BYTES = 2048
BEACON_VALUE_MAX = 512
_beacon_times: dict[str, list[float]] = {}
_beacon_lock = threading.Lock()


def _beacon_allowed(subject: str, per_minute: int) -> bool:
    """Per person, across projects, counted and taken under one lock. Per process: with N
    platform workers a person gets at most N times the allowance, which is still bounded."""
    import time

    now = time.monotonic()
    with _beacon_lock:
        recent = [t for t in _beacon_times.get(subject, []) if now - t < 60]
        if len(recent) >= per_minute:
            _beacon_times[subject] = recent
            return False
        _beacon_times[subject] = recent + [now]
        return True


@router.post("/ledger/beacon", status_code=204)
async def ledger_beacon(request: Request, caller: Caller = Depends(caller_dependency)) -> Response:
    import json as _json

    from starlette.concurrency import run_in_threadpool

    from platform_service.ledger import witness as ledger_witness

    raw = b""
    async for chunk in request.stream():                              # never more than the cap in memory
        raw += chunk
        if len(raw) > BEACON_MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"a beacon is at most {BEACON_MAX_BYTES} bytes")
    if ledger_witness.mode() == "off":
        return Response(status_code=204)
    request_id = request.headers.get("x-aisc-request-id")
    problem = await run_in_threadpool(_ledger_presented, request, request_id)
    if problem:                                                       # in record mode too: the beacon is only
        raise HTTPException(status_code=401, detail=problem)          # worth what its witness is worth
    try:
        body = _json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="the beacon is one JSON object") from None
    if not isinstance(body, dict) or not isinstance(body.get("project"), str):
        raise HTTPException(status_code=422, detail="project: needed")
    action, details = body.get("action"), body.get("details") or {}
    if not isinstance(action, str) or not action.startswith("page.") or not isinstance(details, dict):
        raise HTTPException(status_code=422, detail="only page.* moments come through the beacon")
    await run_in_threadpool(_keep_beacon, body["project"], caller, action, details, request_id)
    return Response(status_code=204)


def _keep_beacon(project: str, caller: Caller, action: str, details: dict, request_id: str) -> None:
    from platform_service.ledger import actors, pageviews, registry, settings as ledger_settings

    if action not in registry.REGISTRY or registry.REGISTRY[action].origin != "browser":
        raise HTTPException(status_code=422, detail=f"{action} isn't a beacon moment")
    unknown = sorted(set(details) - set(registry.REGISTRY[action].details_keys))
    if unknown:
        raise HTTPException(status_code=422, detail=f"{action} carries no {', '.join(unknown)}")
    for key, value in details.items():                                # short scalars, nothing secret
        if not isinstance(value, (str, int, float, bool)) or (isinstance(value, str) and len(value) > BEACON_VALUE_MAX):
            raise HTTPException(status_code=422, detail=f"{key}: a short text, number or yes/no")
        if registry._holds_secret(value):
            raise HTTPException(status_code=422, detail=f"{key}: looks like a secret")
    role_or_404(project, caller)
    found = db.get_project(project)
    pid = str(found["pid"])
    if not _beacon_allowed(caller.subject, ledger_settings.BEACON_PER_MINUTE):
        raise HTTPException(status_code=429, detail="too many beacons")
    ref = actors.ref_of(pid, caller.subject) or actors.ref_for(pid, caller.subject, caller.username or caller.subject)
    try:
        pageviews.record(pid, ref, action, details, request_id)
    except pageviews.AlreadyUsed:
        raise HTTPException(status_code=409, detail="this request already carried a beacon") from None
