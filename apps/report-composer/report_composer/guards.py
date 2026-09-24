"""Who is calling, and what they may do in the project a route names.

Rights come from two dependencies: `signed_in` (a verified caller, else 401) and
`project_guard(right)` (the project by slug or pid, the caller's role in it read on every
request, and for writes the same-origin check).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from fastapi import Request

from aisc_identity.caller import IdentityMissing
from aisc_identity.service import Misconfigured, NotAuthenticated, caller_from_headers

from . import access
from .errors import ApiError

NO_PROJECT = "No such project."
_UNAVAILABLE = "Who may be here cannot be established just now."


def platform_origin() -> str:
    return os.environ.get("PLATFORM_ORIGIN", "http://localhost")


def signed_in(request: Request):
    try:
        return caller_from_headers(request.headers)
    except (NotAuthenticated, IdentityMissing):
        raise ApiError(401, "not_signed_in", "Sign in first.") from None
    except Misconfigured:
        raise ApiError(500, "misconfigured", "Sign-in cannot be checked on this service.") from None


def check_origin(request: Request) -> None:
    if request.method.upper() not in access.SAFE_METHODS and not access.same_origin(request.headers,
                                                                                   platform_origin()):
        raise ApiError(403, "forbidden", "Cross-origin request refused.")


@dataclass(frozen=True)
class Guarded:
    caller: object
    project: dict
    access: access.Access


def guard(request: Request, ref: str, right: str, origin_check: bool = True) -> Guarded:
    caller = signed_in(request)
    database_url = request.app.state.database_url
    try:
        project = access.find_project(database_url, ref)
    except psycopg.Error:
        raise ApiError(503, "unavailable", _UNAVAILABLE) from None
    if project is None:
        raise ApiError(404, "not_found", NO_PROJECT)
    a = access.access_for(database_url, project, caller)
    verdict = access.decide("GET" if right == "viewer" else "POST", a)
    if verdict == "unavailable":
        raise ApiError(503, "unavailable", _UNAVAILABLE)
    if verdict == "not-found":
        raise ApiError(404, "not_found", NO_PROJECT)
    if verdict == "forbidden":
        raise ApiError(403, "forbidden", "You can read this project but not change it.")
    if origin_check:
        check_origin(request)
    return Guarded(caller, project, a)


def project_guard(right: str, origin_check: bool = True):
    def dependency(request: Request, ref: str) -> Guarded:
        return guard(request, ref, right, origin_check)

    return dependency
