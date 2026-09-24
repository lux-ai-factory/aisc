"""Admin only, and the admin's own token kept to call the engine with (spec D2, D7)."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from aisc_identity.caller import Caller
from aisc_identity.fastapi import requires_role
from aisc_identity.headers import token_from_headers

_admin = requires_role("admin")


@dataclass(frozen=True)
class Admin:
    caller: Caller
    token: str | None


def admin_call(request: Request, caller: Caller = Depends(_admin)) -> Admin:
    return Admin(caller=caller, token=token_from_headers(request.headers))
