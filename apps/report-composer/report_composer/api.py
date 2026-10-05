"""The composer's API under /api.

Every route is guarded by `signed_in` or `project_guard(right)` from guards.py.
"""
from __future__ import annotations

import json
import uuid

import psycopg
from fastapi import APIRouter, Body, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import builtin_layouts, db, declared_charts, evidence_links, layouts, ledger, presets, preview_with, reports
from . import templates as looks
from .errors import ApiError, fail_on
from .guards import Guarded, project_guard, signed_in
from .records import NO_LAYOUT, NO_TEMPLATE, chosen_template, layout_or_404, template_of, template_or_404
from .renderer_calls import block_types, choices_for, fonts, outline_block_types, renderer_call
from .settings import document_settings

router = APIRouter(prefix="/api")
PREVIEW_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
LOGO_CSP = "default-src 'none'; style-src 'unsafe-inline'"
NAME_MAX, DESCRIPTION_MAX = 120, 2000
DRAFT_MAX_BYTES = 1_048_576


def _project_db(request: Request, g: Guarded):
    """The guarded project's own database: opened only after the guard has decided."""
    return request.app.state.projects.connect(g.project["pid"])


def layout_view(layout: dict, project_pid: str) -> dict:
    """A layout as the API answers it; project_id is the guarded project's (the row has none)."""
    layout = {**layout, "project_id": project_pid}
    return {k: layout[k] for k in ("id", "project_id", "name", "description", "template_id", "revision",
                                   "blocks", "created_at", "updated_at", "show_index", "numbering")}


def _text(body: dict, name: str, *, required: bool, max_len: int) -> str:
    value = body.get(name)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > max_len:
        raise ApiError(422, "invalid_request", f"{name} must be text of 1 to {max_len} characters.",
                       [{"pointer": f"/{name}", "message": "is not valid"}])
    return value.strip() if required else value


def _name_and_description(body: dict) -> tuple[str, str]:
    return (_text(body, "name", required=True, max_len=NAME_MAX),
            _text(body, "description", required=False, max_len=DESCRIPTION_MAX))


def _revision(body: dict) -> int:
    revision = body.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ApiError(422, "invalid_request", "revision is required.", [{"pointer": "/revision", "message": "is required"}])
    return revision


def _layout_name_taken() -> ApiError:
    return ApiError(422, "name_taken", "A layout of this project already has this name.")


def _blocks(body: dict) -> list:
    blocks = body.get("blocks")
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        raise ApiError(422, "invalid_request", "blocks must be a list of blocks.",
                       [{"pointer": "/blocks", "message": "is not valid"}])
    return [{"instance_id": b.get("instance_id"), "block_type": b.get("block_type"),
             "options": b.get("options") if b.get("options") is not None else {}} for b in blocks]


# Versions, block types, choices

@router.get("/p/{ref}/systems")
def get_systems(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        return db.systems(conn)


@router.get("/block-types")
def get_block_types(request: Request, caller=Depends(signed_in)):
    return block_types(request)


@router.get("/p/{ref}/choices")
def get_choices(request: Request, block_type: str, system_id: str,
                g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        system = db.system_of_project(conn, system_id)
    if system is None:
        raise ApiError(404, "not_found", "No such version in this project.")
    return renderer_call(request.app.state.renderer.choices, g.project["pid"], system["pid"], block_type)


# Layouts

@router.get("/p/{ref}/layouts")
def get_layouts(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        return db.list_layouts(conn)


@router.post("/p/{ref}/layouts", status_code=201)
def post_layout(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    """A layout of this project: empty, from its blocks, or from a layout file (`file`; `preset_file` is the
    older name). It holds no data: a version or a toc sent by an older client is ignored."""
    body = {**body, "file": body.get("file", body.get("preset_file"))}
    sources = [k for k in ("file", "blocks") if body.get(k) is not None]
    if len(sources) > 1:
        raise ApiError(422, "invalid_request", "Give at most one of file and blocks.",
                       [{"pointer": "/" + k, "message": "only one source of blocks"} for k in sources])
    pid = g.project["pid"]
    types = block_types(request)
    imported = presets.from_file(body["file"], types) if body.get("file") is not None else None
    with _project_db(request, g) as conn:
        template_id = chosen_template(conn, body.get("template_id"))
        taken = db.layout_names(conn)
    if body.get("name") is None and imported is not None:
        body = {**body, "name": looks.free_name(imported.name, taken)}
    name, description = _name_and_description(body)
    if imported is not None:
        blocks = presets.blocks_for_layout(imported, types)
        start = {k: v for k, v in (("show_index", imported.show_index), ("numbering", imported.numbering))
                 if v is not None}
    else:
        blocks = _blocks(body) if body.get("blocks") is not None else []
        start = {}
    settings = document_settings(body, start)
    fail_on(_shape_problems(blocks, types))
    now = request.app.state.clock()
    try:
        with _project_db(request, g) as conn:
            lid = db.insert_layout(conn, template_id=template_id, name=name, description=description, blocks=blocks,
                                   who=g.caller.subject, now=now, settings=settings)
            saved = db.get_layout(conn, lid)
            ledger.emit(conn, "report.layout.created", item_type="layout", item_id=lid, item_version="1",
                        details={"from": "file" if imported is not None else ("blocks" if blocks else "empty")},
                        content=ledger.layout_state(saved), after=ledger.layout_state(saved))
            view = layout_view(saved, pid)
    except psycopg.errors.UniqueViolation:
        raise _layout_name_taken() from None
    if imported is not None:
        view["notices"] = presets.reference_notices(imported.reset, "data that is not in this project")
    return view


def _shape_problems(blocks, types) -> list[dict]:
    """A saved layout's problems without its references: those are checked against a version, in the
    preview and when a report is generated."""
    return layouts.validate_layout(blocks, block_types=types, choices=None, allow_missing_references=True)


@router.get("/p/{ref}/deleted-layouts")
def get_deleted_layouts(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    """The deleted layouts whose reports stay, each with its reports."""
    with _project_db(request, g) as conn:
        return db.deleted_layouts_with_reports(conn)


@router.get("/p/{ref}/layouts/{layout_id}")
def get_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        return layout_view(layout_or_404(conn, layout_id), g.project["pid"])


@router.put("/p/{ref}/layouts/{layout_id}")
def put_layout(request: Request, layout_id: str, body: dict = Body(...),
               g: Guarded = Depends(project_guard("editor"))):
    pid = g.project["pid"]
    with _project_db(request, g) as conn:
        current = layout_or_404(conn, layout_id)
    if body.get("project_id") is not None and str(body["project_id"]) != pid:
        raise ApiError(422, "immutable_field", "A layout stays in its project.")
    name, description = _name_and_description(body)
    revision = _revision(body)
    blocks = _blocks(body)
    with _project_db(request, g) as conn:
        template_id = chosen_template(conn, body.get("template_id"))
    settings = document_settings(body, current)
    fail_on(_shape_problems(blocks, block_types(request)))
    try:
        with _project_db(request, g) as conn:
            before = ledger.layout_state(db.get_layout(conn, current["id"], for_update=True))
            new = db.update_layout(conn, current["id"], based_on=revision, name=name, description=description,
                                   template_id=template_id, blocks=blocks,
                                   who=g.caller.subject, now=request.app.state.clock(), settings=settings)
            if new is None:
                latest = layout_or_404(conn, layout_id)
                raise ApiError(409, "stale_revision",
                               f"The layout was saved meanwhile; the current revision is {latest['revision']}.",
                               [{"current_revision": latest["revision"]}])
            saved = db.get_layout(conn, current["id"])
            ledger.emit(conn, "report.layout.updated", item_type="layout", item_id=current["id"],
                        item_version=str(new), details={"revision": new}, content=ledger.layout_state(saved),
                        before=before, after=ledger.layout_state(saved))
            return layout_view(saved, pid)
    except psycopg.errors.UniqueViolation:
        raise _layout_name_taken() from None


@router.delete("/p/{ref}/layouts/{layout_id}", status_code=204)
def delete_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("editor"))):
    with _project_db(request, g) as conn:
        layout = db.get_layout(conn, layout_id, for_update=True)
        held = db.reports_of(conn, layout["id"]) if layout is not None else []
        if layout is None or not db.delete_layout(conn, layout_id, request.app.state.clock()):
            raise ApiError(404, "not_found", NO_LAYOUT)
        # hidden, not removed: its revisions (layout_revision) and its reports stay
        ledger.emit(conn, "report.layout.deleted", item_type="layout", item_id=layout["id"],
                    details={"reports": len(held)}, before=ledger.layout_state(layout),
                    content={"layout": ledger.layout_state(layout), "reports": held})
    return Response(status_code=204)


@router.post("/p/{ref}/layouts/{layout_id}/validate")
def validate(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer", origin_check=False))):
    with _project_db(request, g) as conn:
        layout = layout_or_404(conn, layout_id)
        pw = preview_with.parse(conn, None)
    problems = _problems_for(request, g, layout["blocks"], pw)
    return {"valid": not problems, "problems": problems}


def _problems_for(request: Request, g: Guarded, blocks, pw) -> list[dict]:
    """A layout's problems with its references checked against the preview's version (none: shape only)."""
    types = block_types(request)
    if pw.system is None:
        return _shape_problems(blocks, types)
    pid, spid = g.project["pid"], pw.system["pid"]
    return layouts.validate_layout(blocks, block_types=types, choices=choices_for(request, pid, spid))


NO_VERSION = "This project has no AI card version yet. Save the AI card in qualification first."


def _render_preview(request: Request, g: Guarded, layout: dict, template, pw, links) -> dict:
    """The renderer's preview of `layout` for the preview's version and period, with the project's step 4
    `links`; with no version, a page saying so, without calling the renderer."""
    if pw.system is None:
        return {"html": f"<!DOCTYPE html><html><body><p>{NO_VERSION}</p></body></html>", "block_statuses": []}
    snapshot = reports.snapshot_of(g.project, layout, "preview", g.caller, template, system_id=pw.system["pid"],
                                   selection=pw.selection, coverage_links=links,
                                   declared_charts=declared_charts.for_snapshot(request, g.project, layout["blocks"]))
    return renderer_call(request.app.state.renderer.render, snapshot)


@router.get("/p/{ref}/layouts/{layout_id}/preview")
def preview(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        layout = layout_or_404(conn, layout_id)
        template = template_of(conn, layout)
        pw = preview_with.parse(conn, dict(request.query_params))
        links = evidence_links.coverage_links(conn, pw.system["pid"] if pw.system else None)
    result = _render_preview(request, g, layout, template, pw, links)
    return HTMLResponse(result["html"], headers={"Content-Security-Policy": PREVIEW_CSP,
                                                 "X-Content-Type-Options": "nosniff"})


@router.post("/p/{ref}/layouts/{layout_id}/outline")
def outline(request: Request, layout_id: str, body: dict = Body(...),
            g: Guarded = Depends(project_guard("editor"))):
    """Indentation, numbers and empty-chapter hints for the editor's current block order; nothing is stored. `new`
    is the editor of a layout not saved yet."""
    if layout_id != "new":
        with _project_db(request, g) as conn:
            layout_or_404(conn, layout_id)
    blocks = _blocks(body)
    if len(blocks) > layouts.MAX_BLOCKS:   # the same limit as saving a layout
        raise ApiError(422, "too_many_blocks", f"A layout holds at most {layouts.MAX_BLOCKS} blocks.",
                       [{"pointer": "/blocks", "message": f"a layout holds at most {layouts.MAX_BLOCKS} blocks"}])
    if not all(isinstance(b["block_type"], str) for b in blocks):
        raise ApiError(422, "invalid_request", "Every block needs a block_type.",
                       [{"pointer": "/blocks", "message": "is not valid"}])
    numbering = body.get("numbering", False)
    if not isinstance(numbering, bool):
        raise ApiError(422, "invalid_request", "numbering must be true or false.",
                       [{"pointer": "/numbering", "message": "is not valid"}])
    # cached block types, short timeout, [] when the renderer fails: the outline then uses the fixed prose
    # list, so indentation keeps working without the renderer
    return {"outline": layouts.outline(blocks, outline_block_types(request), numbering=numbering)}


@router.post("/p/{ref}/layouts/{layout_id}/preview")
async def preview_draft(request: Request, layout_id: str, g: Guarded = Depends(project_guard("editor"))):
    """The editor's unsaved state rendered as a preview; nothing is stored."""
    raw = await request.body()
    if len(raw) > DRAFT_MAX_BYTES:
        raise ApiError(413, "too_large", "The draft is larger than 1 MB.")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ApiError(422, "invalid_request", "The draft must be a JSON object.")
    return await run_in_threadpool(_draft_preview, request, g, layout_id, body)


def _draft_preview(request: Request, g: Guarded, layout_id: str, body: dict) -> dict:
    with _project_db(request, g) as conn:
        current = layout_or_404(conn, layout_id)
        template_id = chosen_template(conn, body.get("template_id"))
        template = db.get_template(conn, template_id, with_logo=True) if template_id else None
        pw = preview_with.parse(conn, body.get("preview_with") if isinstance(body.get("preview_with"), dict) else None)
        links = evidence_links.coverage_links(conn, pw.system["pid"] if pw.system else None)
    settings = document_settings(body, current)
    blocks = _blocks(body) if body.get("blocks") is not None else current["blocks"]
    problems = _problems_for(request, g, blocks, pw)
    draft = {**current, **settings, "blocks": blocks}
    result = _render_preview(request, g, draft, template, pw, links)
    return {"html": reports.with_csp_meta(result.get("html") or ""), "problems": problems,
            "block_statuses": list(result.get("block_statuses") or [])}


# Duplicate and export

@router.post("/p/{ref}/layouts/{layout_id}/duplicate", status_code=201)
def duplicate_layout(request: Request, layout_id: str, body: dict | None = Body(None),
                     g: Guarded = Depends(project_guard("editor"))):
    body = body or {}
    pid = g.project["pid"]
    now = request.app.state.clock()
    builtin = builtin_layouts.get(layout_id, block_types(request))
    try:
        with _project_db(request, g) as conn:
            src = builtin if builtin is not None else layout_or_404(conn, layout_id)
            if body.get("name") is not None:
                name = _text(body, "name", required=True, max_len=NAME_MAX)
            else:
                name = presets.copy_name(src["name"], db.layout_names(conn))
            blocks = [{"instance_id": str(uuid.uuid4()), "block_type": b["block_type"], "options": b["options"]}
                      for b in src["blocks"]]
            settings = {k: src[k] for k in ("show_index", "numbering")}
            lid = db.insert_layout(conn, template_id=src["template_id"],
                                   name=name, description=src.get("description") or "", blocks=blocks,
                                   who=g.caller.subject, now=now, settings=settings)
            saved = db.get_layout(conn, lid)
            ledger.emit(conn, "report.layout.created", item_type="layout", item_id=lid, item_version="1",
                        details={"from": "duplicate"}, content={**ledger.layout_state(saved), "source": layout_id},
                        after=ledger.layout_state(saved))
            return layout_view(saved, pid)
    except psycopg.errors.UniqueViolation:
        raise _layout_name_taken() from None


def _preset_file_response(p: presets.Preset) -> Response:
    slug = reports._slugify(p.name)[:60]
    return Response(json.dumps(presets.export_doc(p), indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="report-preset-{slug}.json"'})


@router.get("/p/{ref}/builtin-layouts")
def get_builtin_layouts(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    """The five built-in layouts, read-only."""
    return builtin_layouts.all_layouts(block_types(request))


def _builtin_or_404(request: Request, layout_id: str) -> dict:
    found = builtin_layouts.get(layout_id, block_types(request))
    if found is None:
        raise ApiError(404, "not_found", NO_LAYOUT)
    return found


@router.get("/p/{ref}/builtin-layouts/{layout_id}")
def get_builtin_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    return _builtin_or_404(request, layout_id)


@router.get("/p/{ref}/builtin-layouts/{layout_id}/preview")
def preview_builtin_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    """A built-in layout drawn with this project's data, for the preview's version and period."""
    layout = _builtin_or_404(request, layout_id)
    with _project_db(request, g) as conn:
        pw = preview_with.parse(conn, dict(request.query_params))
        links = evidence_links.coverage_links(conn, pw.system["pid"] if pw.system else None)
    result = _render_preview(request, g, layout, None, pw, links)
    return HTMLResponse(result["html"], headers={"Content-Security-Policy": PREVIEW_CSP,
                                                 "X-Content-Type-Options": "nosniff"})


@router.get("/p/{ref}/builtin-layouts/{layout_id}/export")
def export_builtin_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    return _preset_file_response(presets.from_layout(_builtin_or_404(request, layout_id), block_types(request),
                                                     keep_text=True))


@router.get("/p/{ref}/layouts/{layout_id}/export")
def export_layout(request: Request, layout_id: str, keep_text: bool = False,
                  g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        layout = layout_or_404(conn, layout_id)
    return _preset_file_response(presets.from_layout(layout, block_types(request), keep_text=keep_text))


# Reports

@router.post("/p/{ref}/layouts/{layout_id}/reports")
def post_report(request: Request, layout_id: str, body: dict | None = Body(None),
                g: Guarded = Depends(project_guard("editor"))):
    """A report of the layout for a chosen version, period, other-versions switch and compare version."""
    body = body or {}
    fmt = body.get("format") or "pdf"
    if fmt not in reports.FORMATS:
        raise ApiError(422, "invalid_request", "format must be pdf or docx.",
                       [{"pointer": "/format", "message": "must be one of pdf, docx"}])
    choice = {k: body.get(k) for k in ("system_id", "period_from", "period_to", "compare_to")}
    choice["other_versions"] = body.get("other_versions") is True
    status, answer = reports.generate(request, g.project, layout_id, g.caller, fmt, choice=choice,
                                      record=lambda conn, o: ledger.emit(
                                          conn, "report.generated" if o["ok"] else "report.failed",
                                          **reports.outcome_fields(o)))
    return JSONResponse(status_code=status, content=answer)


@router.get("/p/{ref}/layouts/{layout_id}/reports")
def get_reports(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        layout = layout_or_404(conn, layout_id)
        return [reports.report_row(r) for r in db.list_reports(conn, layout["id"])]


def _document(request: Request, g: Guarded, report_id: str, only_pdf: bool, record=None) -> Response:
    """The report's document; with only_pdf its PDF: the document of a PDF report, a Word report's copy."""
    with _project_db(request, g) as conn:
        report = db.get_report(conn, report_id)
    fmt = (report or {}).get("format") or "pdf"
    if report is None or report["pdf"] is None:
        raise ApiError(404, "not_found", "No such report.")
    body, sha256 = report["pdf"], report["sha256"]
    if only_pdf and fmt != "pdf":
        if report.get("pdf_copy") is None:
            raise ApiError(404, "not_found", "This report has no PDF version.")
        fmt, body, sha256 = "pdf", report["pdf_copy"], report["pdf_copy_sha256"]
    snap = report["snapshot"] or {}
    name = reports.document_filename(g.project["slug"], report["system_number"],
                                     (snap.get("layout") or {}).get("name", ""), report["created_at"], fmt)
    if record is not None:
        with _project_db(request, g) as conn:
            record(conn, {**report, "sha256": sha256, "served_copy": body is report.get("pdf_copy")})
    return Response(bytes(body), media_type=reports.MEDIA_TYPES[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _downloaded(conn, r):
    details = {"document_sha256": r["sha256"]}
    if r.get("served_copy"):
        details["format"] = "pdf"                  # the PDF version of a Word report
    ledger.emit(conn, "report.downloaded", item_type="report", item_id=r["id"], details=details)


@router.get("/p/{ref}/reports/{report_id}/pdf")
def get_pdf(request: Request, report_id: str, g: Guarded = Depends(project_guard("viewer"))):
    return _document(request, g, report_id, only_pdf=True, record=_downloaded)


@router.get("/p/{ref}/reports/{report_id}/download")
def download(request: Request, report_id: str, g: Guarded = Depends(project_guard("viewer"))):
    return _document(request, g, report_id, only_pdf=False, record=_downloaded)


# Templates: a report's look

def _save_template(request: Request, g: Guarded, body, template_id=None, rename_if_taken=False, record=None):
    """`record(conn, template_id, before, after)`: the caller's ledger event, in the save's transaction."""
    look, logo = looks.checked(body, fonts(request))
    now = request.app.state.clock()
    try:
        with _project_db(request, g) as conn:
            before = ledger.template_state(db.get_template(conn, template_id, with_logo=True, for_update=True)) \
                if template_id is not None else None
            if template_id is not None and body.get("keep_logo") and "logo" not in body:
                current = template_or_404(conn, template_id, with_logo=True)
                logo = (current["logo_mime"], bytes(current["logo"])) if current.get("logo") else None
            if rename_if_taken:
                look["name"] = looks.free_name(look["name"], db.template_names(conn))
            if template_id is None:
                template_id = db.insert_template(conn, look=look, logo=logo, who=g.caller.subject,
                                                 now=now)
            elif not db.update_template(conn, template_id, look=look, logo=logo, who=g.caller.subject, now=now):
                raise ApiError(404, "not_found", NO_TEMPLATE)
            if record is not None:
                record(conn, template_id, before, ledger.template_state(db.get_template(conn, template_id,
                                                                                       with_logo=True)))
            return looks.view(template_or_404(conn, template_id))
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A template of this project already has this name.") from None


@router.get("/fonts")
def get_fonts(request: Request, caller=Depends(signed_in)):
    return fonts(request)


@router.get("/p/{ref}/templates")
def get_templates(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        return [looks.view(t) for t in db.list_templates(conn)]


@router.post("/p/{ref}/templates", status_code=201)
def post_template(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    return _save_template(request, g, body, record=lambda conn, tid, before, after: ledger.emit(
        conn, "report.template.created", item_type="template", item_id=tid, details={"from": "form"},
        content=after, after=after))


@router.post("/p/{ref}/templates/import", status_code=201)
def import_template(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    return _save_template(request, g, looks.from_export(body), rename_if_taken=True,
                          record=lambda conn, tid, before, after: ledger.emit(
                              conn, "report.template.created", item_type="template", item_id=tid,
                              details={"from": "file"}, content=after, after=after))


@router.put("/p/{ref}/templates/{template_id}")
def put_template(request: Request, template_id: str, body: dict = Body(...),
                 g: Guarded = Depends(project_guard("editor"))):
    with _project_db(request, g) as conn:
        current = template_or_404(conn, template_id)
    return _save_template(request, g, body, template_id=current["id"],
                          record=lambda conn, tid, before, after: ledger.emit(
                              conn, "report.template.updated", item_type="template", item_id=tid, content=after,
                              before=before, after=after))


@router.delete("/p/{ref}/templates/{template_id}", status_code=204)
def delete_template(request: Request, template_id: str, g: Guarded = Depends(project_guard("editor"))):
    with _project_db(request, g) as conn:
        found = db.get_template(conn, template_id, with_logo=True, for_update=True)
        if found is None:
            raise ApiError(404, "not_found", NO_TEMPLATE)
        # its layouts leave it first, each as its next revision, recorded
        for lid in db.layouts_using(conn, found["id"]):
            was = ledger.layout_state(db.get_layout(conn, lid))
            revision = db.drop_template_from(conn, lid, who=g.caller.subject, now=request.app.state.clock())
            now = ledger.layout_state(db.get_layout(conn, lid))
            if was is not None:                                     # (a deleted layout has no state shown)
                ledger.emit(conn, "report.layout.template_removed", item_type="layout", item_id=lid,
                            item_version=str(revision), details={"revision": revision, "template": found["id"]},
                            content=now, before=was, after=now)
        if not db.delete_template(conn, template_id):
            raise ApiError(404, "not_found", NO_TEMPLATE)
        before = ledger.template_state(found)
        ledger.emit(conn, "report.template.deleted", item_type="template", item_id=found["id"],
                    before=before, content=before)
    return Response(status_code=204)


@router.get("/p/{ref}/templates/{template_id}/export")
def export_template(request: Request, template_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        t = template_or_404(conn, template_id, with_logo=True)
    return Response(json.dumps(looks.export_doc(t), indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{looks.filename(t["name"])}"'})


@router.get("/p/{ref}/templates/{template_id}/logo")
def template_logo(request: Request, template_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with _project_db(request, g) as conn:
        t = template_or_404(conn, template_id, with_logo=True)
    if not t.get("logo"):
        raise ApiError(404, "not_found", "This template has no logo.")
    # an SVG is served as an image only: no script of it runs in this origin
    return Response(bytes(t["logo"]), media_type=t["logo_mime"],
                    headers={"Content-Security-Policy": LOGO_CSP,
                             "X-Content-Type-Options": "nosniff"})
