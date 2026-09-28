"""A layout's document settings and coverage map (report run v2, R-V5.1, R-U2.1, R-D.3; part 2 R2-D1.10;
report modules 2026-09-28: the index is on or off).

`show_index`, `numbering` and `coverage` sit on the layout. On PUT an absent key keeps the current value, so an
older client does not wipe them. Reports are English only: a `language` sent by an older client is ignored.
"""
from __future__ import annotations

from . import coverage_map
from .db import DEFAULT_SETTINGS
from .errors import ApiError



def _invalid(pointer: str, message: str) -> ApiError:
    return ApiError(422, "invalid_request", message, [{"pointer": pointer, "message": message}])


def document_settings(body: dict, current: dict | None) -> dict:
    """The settings to store: body values checked, absent ones from `current` (or the defaults). A
    `toc`, `language` or `system_id` sent by an older client is ignored (report modules spec, 7.2)."""
    base = {k: (current or {}).get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    out = dict(base)
    for key in ("show_index", "numbering"):
        if key in body and body[key] is not None:
            if not isinstance(body[key], bool):
                raise _invalid(f"/{key}", f"{key} must be true or false.")
            out[key] = body[key]
    if "coverage" in body and body["coverage"] is not None:
        problems = coverage_map.shape_problems(body["coverage"])
        if problems:
            raise ApiError(422, "invalid_request", "The coverage map is not valid.", problems)
        out["coverage"] = coverage_map.normalised(body["coverage"])
    return out


def snapshot_document(layout: dict, report_id: str | None) -> dict:
    """The snapshot's `document` object: the generated report's id (None in a preview) and the settings;
    the renderer still speaks toc on/off."""
    return {"id": report_id, "toc": "on" if layout.get("show_index", True) else "off",
            "numbering": bool(layout.get("numbering"))}
