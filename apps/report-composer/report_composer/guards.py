"""Who is calling, and what they may do in the project a route names.

Rights come from two dependencies: `signed_in` (a verified caller, else 401) and
`project_guard(right)` (the project by pid or slug and the caller's role in it,
read on every request through aisc_identity.access, plus for writes the
same-origin check).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import partial

from fastapi import Request

from aisc_identity.access import READS, Admitted, Refused, admit
from aisc_identity.caller import IdentityMissing
from aisc_identity.service import Misconfigured, NotAuthenticated, caller_from_headers

from . import db
from .errors import ApiError

_CODES = {"not-found": "not_found", "forbidden": "forbidden", "unavailable": "unavailable"}


def platform_origin() -> str:
    return os.environ.get("PLATFORM_ORIGIN", "http://localhost")


def signed_in(request: Request):
    try:
        return caller_from_headers(request.headers)
    except (NotAuthenticated, IdentityMissing):
        raise ApiError(401, "not_signed_in", "Sign in first.") from None
    except Misconfigured:
        raise ApiError(500, "misconfigured", "Sign-in cannot be checked on this service.") from None


def same_origin(headers, origin: str) -> bool:
    """A write must come from the platform's own pages."""
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    got = lowered.get("origin")
    if got:
        return got == origin
    referer = lowered.get("referer")
    if referer:
        return referer == origin or referer.startswith(origin + "/")
    return False


def check_origin(request: Request) -> None:
    if request.method.upper() not in READS and not same_origin(request.headers, platform_origin()):
        raise ApiError(403, "forbidden", "Cross-origin request refused.")


@dataclass(frozen=True)
class Guarded:
    caller: object
    project: dict
    access: Admitted


def guard(request: Request, ref: str, right: str, origin_check: bool = True) -> Guarded:
    caller = signed_in(request)
    want = "GET" if right == "viewer" else "POST"
    try:
        admitted = admit(ref, caller, want, connect=partial(db.connect, request.app.state.database_url))
    except Refused as refused:
        raise ApiError(refused.status, _CODES[refused.code], refused.message) from None
    if origin_check:
        check_origin(request)
    return Guarded(caller, {"pid": admitted.pid, "slug": admitted.slug}, admitted)


def project_guard(right: str, origin_check: bool = True):
    def dependency(request: Request, ref: str) -> Guarded:
        return guard(request, ref, right, origin_check)

    return dependency
