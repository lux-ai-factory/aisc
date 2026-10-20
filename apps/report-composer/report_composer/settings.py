"""A layout's document settings: whether the report has an index, and whether its headings are numbered.

`show_index` and `numbering` sit on the layout. On PUT an absent key keeps the current value, so an older client
does not wipe them. Reports are English only, so a `language` sent by an older client is ignored. Coverage
links are set in step 4 (see evidence_links.py), so a `coverage` sent by an older client is ignored too.
"""
from __future__ import annotations

from .db import DEFAULT_SETTINGS
from .errors import ApiError



def _invalid(pointer: str, message: str) -> ApiError:
    return ApiError(422, "invalid_request", message, [{"pointer": pointer, "message": message}])


def document_settings(body: dict, current: dict | None) -> dict:
    """The settings to store: body values checked, absent ones from `current` (or the defaults). A
    `toc`, `language`, `system_id` or `coverage` sent by an older client is ignored."""
    base = {k: (current or {}).get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    out = dict(base)
    for key in ("show_index", "numbering"):
        if key in body and body[key] is not None:
            if not isinstance(body[key], bool):
                raise _invalid(f"/{key}", f"{key} must be true or false.")
            out[key] = body[key]
    return out


def snapshot_document(layout: dict, report_id: str | None) -> dict:
    """The snapshot's `document` object: the generated report's id (None in a preview) and the settings.
    The renderer takes the index as `toc`, "on" or "off"."""
    return {"id": report_id, "toc": "on" if layout.get("show_index", True) else "off",
            "numbering": bool(layout.get("numbering", True))}
