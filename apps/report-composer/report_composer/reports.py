"""Generated reports: the snapshot sent to the renderer, the PDF's filename and the generation itself."""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import unicodedata
from datetime import timedelta

from . import db, layouts
from . import templates as looks
from .errors import ApiError, fail_on
from .records import NO_LAYOUT, template_of
from .renderer_calls import block_types, choices_for
from .renderer_client import RendererTimeout

MAX_PDF_BYTES = 25 * 1024 * 1024
GENERATION_WINDOW_MINUTES = 15


def _slugify(value: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "report"


def pdf_filename(slug, number, layout_name, when) -> str:
    return f"{slug}-v{number}-{_slugify(layout_name)}-{when:%Y%m%d-%H%M}.pdf"


def requested_by(caller) -> str:
    return caller.username or caller.email or caller.subject


def snapshot_of(project, layout, mode, caller, template=None) -> dict:
    """What the renderer is sent; `template` (read with its logo) gives the report its look."""
    snap = {"project_id": project["pid"], "system_id": layout["system_id"],
            "layout": {"id": layout["id"], "name": layout["name"], "revision": layout["revision"]},
            "blocks": [{"instance_id": b["instance_id"], "block_type": b["block_type"], "options": b["options"]}
                       for b in layout["blocks"]],
            "mode": mode, "requested_by": requested_by(caller)}
    if template is not None:
        snap["style"] = looks.style(template)
    return snap


def _ref() -> str:
    return secrets.token_hex(4)


def _error(code, message, details=()) -> dict:
    return {"error": {"code": code, "message": message, "details": list(details)}}


def _start(request, conn, project, layout_id, caller) -> tuple[str, dict]:
    """Checks the saved layout and records a running report with its snapshot: (report id, snapshot).

    The layout row stays locked until the caller's transaction ends, so two generations of one
    layout cannot both pass the running-report check.
    """
    clock = request.app.state.clock
    layout = db.get_layout(conn, project["pid"], layout_id, for_update=True)
    if layout is None:
        raise ApiError(404, "not_found", NO_LAYOUT)
    if not layout["blocks"]:
        raise ApiError(422, "empty_layout", "A layout without blocks cannot be generated.")
    fail_on(layouts.validate_layout(layout["blocks"], block_types=block_types(request),
                                    choices=choices_for(request, project["pid"], layout["system_id"])))
    if db.running_report(conn, layout["id"], clock() - timedelta(minutes=GENERATION_WINDOW_MINUTES)):
        raise ApiError(409, "generation_running", "A report of this layout is being generated.")
    # only what is saved is generated, and it is saved with a template: no template, no report
    template = template_of(conn, project["pid"], layout)
    if template is None:
        raise ApiError(422, "template_required", "Choose a template for this layout and save it first.")
    snapshot = snapshot_of(project, layout, "pdf", caller, template)
    report_id = db.insert_report(conn, layout_id=layout["id"], layout_revision=layout["revision"],
                                 project_id=project["pid"], system_id=layout["system_id"], snapshot=snapshot,
                                 created_by=caller.subject, created_at=clock())
    return report_id, snapshot


def generate(request, project, layout_id, caller) -> tuple[int, dict]:
    """One generation at a time per layout; the snapshot is stored before the renderer runs."""
    url, renderer, clock = request.app.state.database_url, request.app.state.renderer, request.app.state.clock
    with db.connect(url) as conn:
        report_id, snapshot = _start(request, conn, project, layout_id, caller)

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
