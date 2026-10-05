"""FastAPI dependencies: one for "who is calling", one for "and are they X".

The status codes are the whole point of this module. 401 means the request did
not say who it is, so signing in would help. 403 means it did, and the answer
is still no.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request

from aisc_identity.caller import Caller
from aisc_identity.service import Misconfigured, NotAuthenticated, caller_from_headers


def caller_dependency(request: Request) -> Caller:
    try:
        return caller_from_headers(request.headers)
    except NotAuthenticated as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Misconfigured as exc:
        # 500, not 401: nothing the caller sends can fix this, and it must not
        # look like a credentials problem to whoever is reading the logs.
        raise HTTPException(status_code=500, detail=str(exc))


def requires_role(role: str) -> Callable[[Caller], Caller]:
    def guard(caller: Caller = Depends(caller_dependency)) -> Caller:
        if not caller.has_role(role):
            raise HTTPException(status_code=403, detail=f"this needs the {role!r} role")
        return caller

    return guard
