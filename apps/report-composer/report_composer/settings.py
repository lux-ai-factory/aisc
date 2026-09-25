"""A layout's document settings and coverage map (report run v2, R-V5.1, R-U2.1, R-D.3; part 2 R2-D1.10).

`toc`, `numbering` and `coverage` sit on the layout. On PUT an absent key keeps the current value, so an
older client does not wipe them. Reports are English only: a `language` sent by an older client is ignored.
"""
from __future__ import annotations

from . import coverage_map
from .db import DEFAULT_SETTINGS
from .errors import ApiError

TOC_VALUES = ("auto", "on", "off")


def _invalid(pointer: str, message: str) -> ApiError:
    return ApiError(422, "invalid_request", message, [{"pointer": pointer, "message": message}])


def document_settings(body: dict, current: dict | None) -> dict:
    """The settings to store: body values checked, absent ones from `current` (or the defaults).
    A `language` key in the body is ignored (R2-D1.10)."""
    base = {k: (current or {}).get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    out = dict(base)
    if "toc" in body and body["toc"] is not None:
        if body["toc"] not in TOC_VALUES:
            raise _invalid("/toc", "toc must be one of auto, on, off.")
        out["toc"] = body["toc"]
    if "numbering" in body and body["numbering"] is not None:
        if not isinstance(body["numbering"], bool):
            raise _invalid("/numbering", "numbering must be true or false.")
        out["numbering"] = body["numbering"]
    if "coverage" in body and body["coverage"] is not None:
        problems = coverage_map.shape_problems(body["coverage"])
        if problems:
            raise ApiError(422, "invalid_request", "The coverage map is not valid.", problems)
        out["coverage"] = coverage_map.normalised(body["coverage"])
    return out


def snapshot_document(layout: dict, report_id: str | None) -> dict:
    """The snapshot's `document` object: the generated report's id (None in a preview) and the settings."""
    return {"id": report_id, "toc": layout.get("toc") or "auto", "numbering": bool(layout.get("numbering"))}
