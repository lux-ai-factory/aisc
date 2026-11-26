"""A refusal, answered the platform's way: the refusal object as `detail`, with the status of its code.

The object is the same in every app (aisc_identity.refusal); only the envelope is each app's own, and the
platform's pages already read `detail`.
"""
from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException

from aisc_identity.refusal import Refusal


def raise_refusal(refusal: Refusal) -> NoReturn:
    """Answer the request with `refusal`: 409, or 400 for a save that sent no token."""
    raise HTTPException(status_code=refusal.status, detail=refusal.as_dict())
