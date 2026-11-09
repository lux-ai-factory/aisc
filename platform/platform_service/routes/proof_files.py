"""The proof files of checklist answers, for the controls app only (PLATFORM_CONTROLS_TOKEN).

The controls app checks who may attach a file and to what, and keeps the link between an answer and its
files; the rules about the files themselves live here (platform_service.proof_types and proof_store): the
type read from the bytes, the size cap, the SHA-256, and a file that is never replaced or deleted.

POST takes the file's bytes as the body and its name in the `name` query parameter, and answers
{id, name, mime, size, sha256}. GET sends the bytes back. There is no route that changes or deletes one.
"""
from __future__ import annotations

import logging

from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, Request
from minio.error import S3Error
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from platform_service import db, proof_store
from platform_service.projects import looks_like_pid
from platform_service.proof_types import MAX_BYTES, NameRefused, Refused
from platform_service.routes.admission import _internal
from platform_service.routes.connections import _behind_gateway

router = APIRouter()
logger = logging.getLogger(__name__)

#: the only caller, and the variable holding its token
CALLERS = {"controls": "PLATFORM_CONTROLS_TOKEN"}


def _gate(pid: str, request: Request) -> JSONResponse | None:
    """Never through the gateway, only the controls app's token, and a project that exists."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), CALLERS)
    except ServiceRefused as refused:
        if refused.status == 503:
            logger.error("proof files: the internal routes are closed: %s", refused.detail)
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    return None


def _unavailable(exc: Exception) -> JSONResponse:
    logger.error("proof files: %s", exc)
    return _internal(503, {"detail": "the file store is not available just now"})


@router.post("/internal/projects/{pid}/proof-files")
async def store_proof_file(pid: str, request: Request, name: str = "") -> JSONResponse:
    """Check one file and store it in the project's bucket (201), or say why not (413, 415, 422)."""
    refused = await run_in_threadpool(_gate, pid, request)
    if refused:
        return refused
    data = bytearray()
    async for chunk in request.stream():                              # never more than the cap in memory
        data += chunk
        if len(data) > MAX_BYTES:
            return _internal(413, {"detail": f"a file is at most {MAX_BYTES // (1024 * 1024)} MB"})
    try:
        stored = await run_in_threadpool(proof_store.save, pid, name, bytes(data))
    except NameRefused as exc:
        return _internal(422, {"detail": str(exc)})
    except Refused as exc:
        return _internal(415, {"detail": str(exc)})
    except (proof_store.StorageUnavailable, S3Error) as exc:
        return _unavailable(exc)
    return _internal(201, stored)


@router.get("/internal/projects/{pid}/proof-files/{file_id}")
def read_proof_file(pid: str, file_id: str, request: Request):
    """The stored file's bytes, as its own type; 404 when this project has no such file."""
    refused = _gate(pid, request)
    if refused:
        return refused
    try:
        opened = proof_store.open_file(pid, file_id)
    except (proof_store.StorageUnavailable, S3Error) as exc:
        return _unavailable(exc)
    if opened is None:
        return _internal(404, {"detail": "no such file"})

    def chunks():
        try:
            yield from opened.chunks
        finally:
            opened.close()

    return StreamingResponse(chunks(), media_type=opened.mime or "application/octet-stream",
                             headers={"Content-Length": str(opened.size), "Cache-Control": "no-store",
                                      "X-Content-Type-Options": "nosniff",
                                      "X-Proof-File-Sha256": opened.meta.get("sha256", "")})
