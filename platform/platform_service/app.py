"""The platform API: the projects every module comes to reference.

Authentication is the gateway's job and is checked again here, because the
gateway's word is one hop away from a mistake. Authorisation is this service's
job, and it is the whole of it: a project belongs to the people in it, and
every endpoint that returns a project, or anything inside one, goes through the
same two questions. Is this person in it, and are they enough for this.

A stranger is answered 404 rather than 403. The slug of a project is its name,
often the name of a customer, and 403 would confirm it exists.

This module is the application: the ledger's request middleware, the error
answers, and the routers of platform_service.routes, one per area.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from platform_service.membership import InvalidMembership
from platform_service.projects import InvalidProject
from platform_service.routes import ROUTERS
from platform_service.routes.admission import _ledger_presented
from platform_service.systems import InvalidSystem

logger = logging.getLogger(__name__)

app = FastAPI(title="AISC platform", docs_url="/docs")
# The ledger's relay worker: idle while LEDGER_MODE is off.
from platform_service.ledger import worker as _ledger_worker  # noqa: E402

app.router.on_startup.append(_ledger_worker.start)

#: What the ledger's defence in depth checks: every write, but not the internal and authz routes,
#: which carry service tokens or are Caddy's own.
_LEDGER_WRITES = {"POST", "PUT", "PATCH", "DELETE"}
_LEDGER_EXEMPT = ("/internal/", "/authz/", "/docs", "/openapi.json")


@app.middleware("http")
async def ledger_request(request: Request, call_next):
    """The witnessed request this one is (X-AISC-Request-Id), for the platform's own events; in `enforce`,
    a write without a matching one is refused."""
    from starlette.concurrency import run_in_threadpool

    from platform_service.ledger import outbox, witness as ledger_witness

    request_id = request.headers.get("x-aisc-request-id") or None
    mode = ledger_witness.mode()
    if (request.method in _LEDGER_WRITES and not request.url.path.startswith(_LEDGER_EXEMPT)
            and mode != "off"):
        problem = await run_in_threadpool(_ledger_presented, request, request_id)
        if problem and mode == "enforce":
            return JSONResponse({"detail": problem}, status_code=401)
        if problem and request_id:                                    # record: never cite a request that
            logger.warning("ledger: a presented request id was not used: %s", problem)   # isn't this one
            request_id = None
    token = outbox.current_request.set(request_id)
    try:
        return await call_next(request)
    finally:
        outbox.current_request.reset(token)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


for _router in ROUTERS:
    app.include_router(_router)


@app.exception_handler(RequestValidationError)
def validation_without_values(_request, exc: RequestValidationError) -> JSONResponse:
    """422 for a malformed request, without pydantic's `input` and `ctx`: the value
    sent (a key, say) is never echoed back."""
    detail = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


def invalid_input(_, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for _invalid in (InvalidProject, InvalidSystem, InvalidMembership):
    app.add_exception_handler(_invalid, invalid_input)
