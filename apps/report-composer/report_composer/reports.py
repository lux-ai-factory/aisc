"""Generated reports: the snapshot sent to the renderer, the document's filename and the generation itself.

Report run v2: snapshots are version 2 (document settings, coverage links from step 4; no language, reports are
English), a report is a PDF or a Word document (DOCX), and the renderer's fingerprint is stored with it.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import unicodedata
import uuid
from datetime import timedelta

from . import db, evidence_links, layouts
from . import selection as data_selection
from . import templates as looks
from .errors import ApiError, fail_on
from .records import NO_LAYOUT, template_of
from .renderer_calls import block_types, choices_for
from .renderer_client import RendererTimeout
from .settings import snapshot_document

MAX_PDF_BYTES = 25 * 1024 * 1024
FORMATS = ("pdf", "docx")
MEDIA_TYPES = {"pdf": "application/pdf",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
CSP_META = ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:;'
            ' style-src \'unsafe-inline\'">')
GENERATION_WINDOW_MINUTES = 15


def _slugify(value: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "report"


def pdf_filename(slug, number, layout_name, when) -> str:
    return document_filename(slug, number, layout_name, when, "pdf")


def document_filename(slug, number, layout_name, when, fmt) -> str:
    return f"{slug}-v{number}-{_slugify(layout_name)}-{when:%Y%m%d-%H%M}.{fmt}"


def with_csp_meta(html: str) -> str:
    """The HTML with the preview's Content-Security-Policy as the first element of its head."""
    match = re.search(r"<head\b[^>]*>", html, re.I)
    if match:
        return html[:match.end()] + CSP_META + html[match.end():]
    match = re.search(r"<html\b[^>]*>", html, re.I)
    if match:
        return html[:match.end()] + "<head>" + CSP_META + "</head>" + html[match.end():]
    return "<head>" + CSP_META + "</head>" + html


def requested_by(caller) -> str:
    return caller.username or caller.email or caller.subject


def _sent_options(block: dict) -> dict:
    """A block's options as sent: a Summary block's own links from before step 4 are left out (D5)."""
    options = dict(block["options"] or {})
    if block["block_type"] == "summary_coverage":
        options.pop("links", None)
    return options


def snapshot_of(project, layout, mode, caller, template=None, *, system_id, selection=None,
                document_id=None, coverage_links=()) -> dict:
    """What the renderer is sent: the layout, and the data it covers (the anchor version and the
    selection, report modules spec 2026-09-28, section 6); `template` (read with its logo) gives the
    report its look, and none means the platform look. `coverage_links` are the project's step 4 links
    (evidence_links.coverage_links)."""
    snap = {"snapshot_version": 3, "project_id": project["pid"], "system_id": system_id,
            "layout": {"id": layout["id"], "name": layout["name"], "revision": layout["revision"]},
            "blocks": [{"instance_id": b["instance_id"], "block_type": b["block_type"], "options": _sent_options(b)}
                       for b in layout["blocks"]],
            "mode": mode, "requested_by": requested_by(caller),
            "document": snapshot_document(layout, document_id),
            "coverage_links": list(coverage_links),
            "selection": selection or data_selection.for_snapshot(data_selection.parse_dates(None, None, False, None))}
    if template is not None:
        snap["style"] = looks.style(template)
    return snap


def check_choice(conn, choice: dict):
    """The version and the selection a report is generated for (report modules spec, section 6)."""
    if not choice.get("system_id"):
        raise ApiError(422, "invalid_request", "Choose the AI card version to report on.",
                       [{"pointer": "/system_id", "message": "is required"}])
    system = db.system_of_project(conn, choice["system_id"])
    if system is None:
        raise ApiError(422, "system_not_in_project", "The version is not one of this project.")
    compare_to = choice.get("compare_to") or None
    if compare_to is not None:
        older = db.system_of_project(conn, compare_to)
        if older is None or older["number"] >= system["number"]:
            raise ApiError(422, "invalid_request", "Compare with an earlier version of this project.",
                           [{"pointer": "/compare_to", "message": "is not an earlier version"}])
        compare_to = older["pid"]
    sel = data_selection.parse_dates(choice.get("period_from"), choice.get("period_to"),
                                     bool(choice.get("other_versions")), compare_to)
    return system, sel


def report_row(row: dict) -> dict:
    """A generated report as the reports list answers it, with the inclusive last day of its period."""
    return {**row, "last_day": (lambda d: d.isoformat() if d else None)(data_selection.last_day(row.get("period_to")))}


def _ref() -> str:
    return secrets.token_hex(4)


def _error(code, message, details=()) -> dict:
    return {"error": {"code": code, "message": message, "details": list(details)}}


def _start(request, conn, project, layout_id, caller, fmt="pdf", choice=None) -> tuple[str, dict]:
    """Checks the saved layout and records a running report with its snapshot: (report id, snapshot).

    The layout row stays locked until the caller's transaction ends, so two generations of one
    layout cannot both pass the running-report check.
    """
    clock = request.app.state.clock
    layout = db.get_layout(conn, layout_id, for_update=True)
    if layout is None:
        raise ApiError(404, "not_found", NO_LAYOUT)
    if not layout["blocks"]:
        raise ApiError(422, "empty_layout", "A layout without blocks cannot be generated.")
    system, sel = check_choice(conn, choice or {})
    fail_on(layouts.validate_layout(
        layout["blocks"], block_types=block_types(request),
        choices=choices_for(request, project["pid"], system["pid"])))
    if db.running_report(conn, layout["id"], clock() - timedelta(minutes=GENERATION_WINDOW_MINUTES)):
        raise ApiError(409, "generation_running", "A report of this layout is being generated.")
    # only what is saved is generated; without a template it is the platform look (R-U6.1)
    template = template_of(conn, layout)
    report_id = str(uuid.uuid4())
    snapshot = snapshot_of(project, layout, fmt, caller, template, system_id=system["pid"],
                           selection=data_selection.for_snapshot(sel), document_id=report_id,
                           coverage_links=evidence_links.coverage_links(conn))
    db.insert_report(conn, layout_id=layout["id"], layout_revision=layout["revision"],
                     system_id=system["pid"], snapshot=snapshot, created_by=caller.subject, created_at=clock(),
                     fmt=fmt, report_id=report_id, period_from=sel.period_from, period_to=sel.period_to,
                     other_versions=sel.other_versions, compare_to=sel.compare_to)
    return report_id, snapshot


def generate(request, project, layout_id, caller, fmt="pdf", *, choice=None) -> tuple[int, dict]:
    """One generation at a time per layout; the snapshot is stored before the renderer runs. Every
    read and write is in the project's own database."""
    projects, renderer, clock = request.app.state.projects, request.app.state.renderer, request.app.state.clock
    with projects.connect(project["pid"]) as conn:
        report_id, snapshot = _start(request, conn, project, layout_id, caller, fmt, choice)

    def failed(status, code, message, **extra):
        ref = _ref()
        with projects.connect(project["pid"]) as conn:
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
        document = base64.b64decode(result[f"{fmt}_base64"])
        statuses = list(result.get("block_statuses") or [])
        fingerprint = result.get("fingerprint")
    except Exception:
        return failed(502, "renderer_unavailable", "The report renderer answered something unexpected")
    if len(document) > MAX_PDF_BYTES:
        return failed(507, "pdf_too_large", "The document is larger than 25 MB and was not stored",
                      block_statuses=statuses)
    status = "partial" if any(s.get("status") == "error" for s in statuses) else "done"
    with projects.connect(project["pid"]) as conn:
        # the bytes of either format sit in the column named pdf
        db.finish_report(conn, report_id, status=status, finished_at=clock(), pdf=document,
                         sha256=hashlib.sha256(document).hexdigest(), size_bytes=len(document),
                         block_statuses=statuses, fingerprint=fingerprint)
    return 201, {"id": report_id, "status": status, "format": fmt, "block_statuses": statuses,
                 "fingerprint": fingerprint}
