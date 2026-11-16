"""The assessment targets: listed, refreshed from the card, reached by an uploaded file or by a connection
(the internal routes that resolve a target's endpoint and issue its run keys)."""
from __future__ import annotations

import hashlib
import logging
import os
import re

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from aisc_identity.headers import token_from_headers
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from platform_service import (connection_store, run_passes, target_store, targets)
from platform_service.routes.admission import _internal, project_for
from platform_service.routes.connections import _resolve_connection
from platform_service.routes.run_passes import _internal_gate, _issue_run_key

router = APIRouter()

logger = logging.getLogger(__name__)


def _endpoint_of_target(pid: str, key: str) -> tuple[str | None, JSONResponse | None]:
    """The name of the connection that is this target's endpoint, or the answer why there is none."""
    target = target_store.get(pid, key) if targets.is_key(key) else None
    if target is None:
        return None, _internal(404, {"detail": f"no target {key!r}"})
    name = connection_store.holder_of(pid, key)
    if name is None:
        # reason: the one 404 a plugin may read as "skip an optional target" (plugin-interface is_no_endpoint)
        return None, _internal(404, {"detail": f"{target['label']} has no endpoint: set one under Manage,"
                                               " Components and connections", "reason": "no_endpoint"})
    return name, None


@router.get("/internal/projects/{pid}/targets/{key}/connection")
def resolve_target_connection(pid: str, key: str, request: Request) -> JSONResponse:
    """The endpoint of an assessment target, as resolve_connection gives a connection by name."""
    refused = _internal_gate(pid, request, "target", key)
    if refused:
        return refused
    name, missing = _endpoint_of_target(pid, key)
    return missing or _resolve_connection(pid, name, request.headers.get(run_passes.HEADER))


@router.post("/internal/projects/{pid}/targets/{key}/run-keys")
def issue_target_run_key(pid: str, key: str, request: Request) -> JSONResponse:
    """A run key for the endpoint of an assessment target."""
    refused = _internal_gate(pid, request, "target", key)
    if refused:
        return refused
    name, missing = _endpoint_of_target(pid, key)
    return missing or _issue_run_key(pid, name, request.headers.get(run_passes.HEADER))


# ── Assessment targets ────────────────────────────────────────────────────────
# What each evaluation is about: the system, or one component of its AI card. Any member reads
# them; an editor refreshes them from the card (the card's own editors add components); the
# qualification app calls the refresh after every card save. Every call to another module is made
# with the caller's own token.

def _targets_answer(pid: str, synced: dict | None = None) -> dict:
    from platform_service import db as _db

    _exists, latest = _db.latest_version(str(pid))
    number = latest["number"] if latest else None
    return {"targets": targets.view(pid, number), "latest_card": number,
            "reason": (synced or {}).get("reason")}


@router.get("/projects/{slug}/targets")
def list_targets(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    found = project_for(slug, caller, "target.read")
    targets.ensure_system(found["pid"], found["name"])
    return _targets_answer(found["pid"])


@router.post("/projects/{slug}/targets/sync")
def sync_targets(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    found = project_for(slug, caller, "target.sync")
    targets.ensure_system(found["pid"], found["name"])
    synced = targets.sync(found["pid"], token_from_headers(request.headers) or "")
    return _targets_answer(found["pid"], synced)


#: the largest file that may reach a target, in MB (TARGET_FILE_MAX_MB)
TARGET_FILE_MAX_MB = 2048
#: the engine's answers that refuse the file itself (too large, wrong type, empty): passed on as they are
ENGINE_FILE_REFUSALS = frozenset({413, 415, 422})
#: what a target file's name may be: the name the person's file had, without folders
TARGET_FILE_NAME = re.compile(r"[^/\\\x00-\x1f]{1,255}")


def target_file_name_ok(name: str) -> bool:
    """A target file's name is the person's file name, without folders, and never "." or ".." (spaces around
    them included), which name a folder rather than a file."""
    return bool(TARGET_FILE_NAME.fullmatch(name)) and name.strip() not in {".", ".."}


def _target_file_cap() -> int:
    try:
        return int(os.environ.get("TARGET_FILE_MAX_MB") or TARGET_FILE_MAX_MB) * 1024 * 1024
    except ValueError:
        return TARGET_FILE_MAX_MB * 1024 * 1024


@router.put("/projects/{slug}/targets/{key}/file")
async def upload_target_file(slug: str, key: str, request: Request, name: str = "",
                             caller: Caller = Depends(caller_dependency)) -> dict:
    """Reach a model or data component of the AI card by an uploaded file (the body, named `name`) instead
    of an endpoint. Who manages connections may. Read once, hashed as it comes and never more than the
    cap kept; the engine then holds the bytes (targets.upload_file)."""
    import tempfile

    from starlette.concurrency import run_in_threadpool

    from platform_service import engine_components

    pid = (await run_in_threadpool(project_for, slug, caller, "target.file"))["pid"]
    if not target_file_name_ok(name or ""):
        raise HTTPException(status_code=422, detail="name: the file's name, without folders, up to 255 characters")
    if not targets.is_key(key):
        raise HTTPException(status_code=404, detail=f"no target {key} in this project")
    cap = _target_file_cap()
    digest, size = hashlib.sha256(), 0
    with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as spool:
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                raise HTTPException(status_code=413, detail=f"a file is at most {cap // (1024 * 1024)} MB")
            digest.update(chunk)
            spool.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="the file is empty")
        spool.seek(0)
        try:
            await run_in_threadpool(targets.upload_file, pid, key, token_from_headers(request.headers) or "", name,
                                    spool, size, digest.hexdigest(), caller.subject)
        except targets.NoSuchTarget:
            raise HTTPException(status_code=404, detail=f"no target {key} in this project") from None
        except targets.TakesNoFile:
            raise HTTPException(status_code=422, detail=f"{key} is reached through an endpoint only: only a model"
                                                        " or a data component takes a file") from None
        except engine_components.EngineUnavailable as exc:
            logger.warning("file of target %s of project %s not stored: %s", key, pid, exc)
            if exc.status in ENGINE_FILE_REFUSALS:
                raise HTTPException(status_code=exc.status, detail="the engine refused the file: "
                                    + (exc.detail or f"it answered {exc.status}")[:200]) from None
            raise HTTPException(status_code=502, detail="the engine did not take the file: try again later") from None
    return {"key": key, "name": name, "size": size, "sha256": digest.hexdigest()}


@router.get("/projects/{slug}/targets/assessable-by")
def targets_assessable_by(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """Per target, the installed tests that can assess it, from what the engine says each declares
    (asked with the caller's own token), and whether some of them call their target (so need a
    connection). An engine that does not answer lists none, and says so."""
    from platform_service import engine_components

    found = project_for(slug, caller, "target.read")
    targets.ensure_system(found["pid"], found["name"])
    rows = targets.view(found["pid"], None)
    try:
        plugins = engine_components.plugin_declarations(found["pid"], token_from_headers(request.headers) or "")
    except engine_components.EngineUnavailable as exc:
        logger.warning("installed tests of project %s not read: %s", found["pid"], exc)
        return {"assessable_by": {t["key"]: [] for t in rows}, "some_need_a_connection": False,
                "reason": "the installed tests could not be read: try again later"}
    return {"assessable_by": targets.assessable_by(rows, plugins),
            "some_need_a_connection": targets.some_need_a_connection(plugins), "reason": None}
