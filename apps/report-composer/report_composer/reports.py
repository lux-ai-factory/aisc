"""Generated reports: the PDF's filename and the generation itself (report run 2026-09-23, R4.3.3 to R4.3.5)."""
from __future__ import annotations

import re
import unicodedata

MAX_PDF_BYTES = 25 * 1024 * 1024


def _slugify(value: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "report"


def pdf_filename(slug, number, layout_name, when) -> str:
    return f"{slug}-v{number}-{_slugify(layout_name)}-{when:%Y%m%d-%H%M}.pdf"


GENERATION_WINDOW_MINUTES = 15


def _ref() -> str:
    import secrets

    return secrets.token_hex(4)


def _error(code, message, details=()) -> dict:
    return {"error": {"code": code, "message": message, "details": list(details)}}


def generate(request, project, layout_id, caller) -> tuple[int, dict]:
    """R4.3.3 to R4.3.5: one generation at a time per layout; the snapshot is stored before the renderer runs."""
    import base64
    import hashlib
    from datetime import timedelta

    from . import db, layouts
    from .api import ApiError, block_types, choices_for, fail_on, snapshot_of
    from .renderer_client import RendererTimeout

    url, renderer, clock = request.app.state.database_url, request.app.state.renderer, request.app.state.clock
    with db.connect(url) as conn:
        layout = db.get_layout(conn, project["pid"], layout_id, for_update=True)
        if layout is None:
            raise ApiError(404, "not_found", "No such layout.")
        if not layout["blocks"]:
            raise ApiError(422, "empty_layout", "A layout without blocks cannot be generated.")
        fail_on(layouts.validate_layout(layout["blocks"], block_types=block_types(request),
                                        choices=choices_for(request, project["pid"], layout["system_id"])))
        if db.running_report(conn, layout["id"], clock() - timedelta(minutes=GENERATION_WINDOW_MINUTES)):
            raise ApiError(409, "generation_running", "A report of this layout is being generated.")
        snapshot = snapshot_of(project, layout, "pdf", caller)
        report_id = db.insert_report(conn, layout_id=layout["id"], layout_revision=layout["revision"],
                                     project_id=project["pid"], system_id=layout["system_id"], snapshot=snapshot,
                                     created_by=caller.subject, created_at=clock())

    def failed(status, code, message, **extra):
        ref = _ref()
        with db.connect(url) as conn:
            db.finish_report(conn, report_id, status="failed", finished_at=clock(), error_ref=ref, error_code=code,
                             **extra)
        return status, _error(code, f"{message} (ref {ref})", [{"error_ref": ref, "report_id": report_id}])

    try:
        result = renderer.render(snapshot)
    except RendererTimeout:
        return failed(504, "renderer_timeout", "The report renderer did not answer in time")
    except Exception:
        return failed(502, "renderer_unavailable", "The report renderer is not available")
    try:
        pdf = base64.b64decode(result["pdf_base64"])
        statuses = list(result.get("block_statuses") or [])
    except Exception:
        return failed(502, "renderer_unavailable", "The report renderer answered something unexpected")
    if len(pdf) > MAX_PDF_BYTES:
        return failed(507, "pdf_too_large", "The PDF is larger than 25 MB and was not stored",
                      block_statuses=statuses)
    status = "partial" if any(s.get("status") == "error" for s in statuses) else "done"
    with db.connect(url) as conn:
        db.finish_report(conn, report_id, status=status, finished_at=clock(), pdf=pdf,
                         sha256=hashlib.sha256(pdf).hexdigest(), size_bytes=len(pdf), block_statuses=statuses)
    return 201, {"id": report_id, "status": status, "block_statuses": statuses}
