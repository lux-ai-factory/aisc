"""Errors of the composer, one shape for every route (report run 2026-09-23, R4.3.1).

A path under /api/ answers {"error": {"code", "message", "details"}}; any other path the error
page, with the same status. A message never names the project: a stranger and an unknown project
get the same answer (R4.4.3).
"""
from __future__ import annotations

from pathlib import Path

import os

import jinja2
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
                          autoescape=True)
# The launcher, where the header's mark and "Back" lead, as in the other modules.
_env.globals["launcher"] = os.environ.get("LAUNCHER_URL", "http://localhost:8100/").rstrip("/") + "/"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=()):
        self.status, self.code, self.message, self.details = status, code, message, list(details)
        super().__init__(message)


def _answer(request: Request, status: int, code: str, message: str, details=()):
    root = request.scope.get("root_path", "") or ""
    path = request.url.path[len(root):] if root and request.url.path.startswith(root) else request.url.path
    if path.startswith("/api/") or path == "/api":
        return JSONResponse(status_code=status,
                            content={"error": {"code": code, "message": message, "details": list(details)}})
    html = _env.get_template("error.html.j2").render(status=status, message=message,
                                                     root=request.scope.get("root_path", ""))
    return HTMLResponse(html, status_code=status)


def install(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _answer(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        details = [{"pointer": "/" + "/".join(str(p) for p in e.get("loc", ())[1:]), "message": e.get("msg", "")}
                   for e in exc.errors()]
        return _answer(request, 422, "invalid_request", "The request is not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _answer(request, 404, "not_found", "Not found.")
        if exc.status_code == 405:
            return _answer(request, 405, "method_not_allowed", "This method is not allowed here.")
        return _answer(request, exc.status_code, "error", str(exc.detail))
