"""The composer's API under /api.

Every route is guarded by `signed_in` or `project_guard(right)` from guards.py.
"""
from __future__ import annotations

import json

import psycopg
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import db, layouts, reports
from . import templates as looks
from .errors import ApiError, fail_on
from .guards import Guarded, project_guard, signed_in
from .records import NO_LAYOUT, NO_TEMPLATE, chosen_template, layout_or_404, template_of, template_or_404
from .renderer_calls import block_types, choices_for, fonts, renderer_call

router = APIRouter(prefix="/api")
PREVIEW_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
LOGO_CSP = "default-src 'none'; style-src 'unsafe-inline'"


def layout_view(layout: dict) -> dict:
    return {k: layout[k] for k in ("id", "project_id", "name", "description", "system_id", "template_id", "revision",
                                   "blocks", "created_at", "updated_at")}


def _text(body: dict, name: str, *, required: bool, max_len: int) -> str:
    value = body.get(name)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > max_len:
        raise ApiError(422, "invalid_request", f"{name} must be text of 1 to {max_len} characters.",
                       [{"pointer": f"/{name}", "message": "is not valid"}])
    return value.strip() if required else value


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
    with db.connect(request.app.state.database_url) as conn:
        return db.systems(conn, g.project["pid"])


@router.get("/block-types")
def get_block_types(request: Request, caller=Depends(signed_in)):
    return block_types(request)


@router.get("/p/{ref}/choices")
def get_choices(request: Request, block_type: str, system_id: str,
                g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        system = db.system_of_project(conn, g.project["pid"], system_id)
    if system is None:
        raise ApiError(404, "not_found", "No such version in this project.")
    return renderer_call(request.app.state.renderer.choices, g.project["pid"], system["pid"], block_type)


# Layouts

@router.get("/p/{ref}/layouts")
def get_layouts(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        return db.list_layouts(conn, g.project["pid"])


@router.post("/p/{ref}/layouts", status_code=201)
def post_layout(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    name = _text(body, "name", required=True, max_len=120)
    description = _text(body, "description", required=False, max_len=2000)
    pid = g.project["pid"]
    url = request.app.state.database_url
    with db.connect(url) as conn:
        if body.get("system_id") is not None:
            system = db.system_of_project(conn, pid, body["system_id"])
            if system is None:
                raise ApiError(422, "system_not_in_project", "The version is not one of this project.")
        else:
            system = db.latest_system(conn, pid)
            if system is None:
                raise ApiError(422, "system_not_in_project", "This project has no system version yet.")
        template_id = chosen_template(conn, pid, body.get("template_id"))
    types = block_types(request)
    if "blocks" in body and body["blocks"] is not None:
        blocks = _blocks(body)
    else:
        blocks = layouts.default_blocks(types)
    fail_on(layouts.validate_layout(blocks, block_types=types, choices=choices_for(request, pid, system["pid"])))
    now = request.app.state.clock()
    try:
        with db.connect(url) as conn:
            lid = db.insert_layout(conn, project_pid=pid, system_pid=system["pid"], template_id=template_id, name=name,
                                   description=description, blocks=blocks, who=g.caller.subject, now=now)
            return layout_view(db.get_layout(conn, pid, lid))
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A layout of this project already has this name.") from None


@router.get("/p/{ref}/layouts/{layout_id}")
def get_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        return layout_view(layout_or_404(conn, g.project["pid"], layout_id))


@router.put("/p/{ref}/layouts/{layout_id}")
def put_layout(request: Request, layout_id: str, body: dict = Body(...),
               g: Guarded = Depends(project_guard("editor"))):
    pid = g.project["pid"]
    url = request.app.state.database_url
    with db.connect(url) as conn:
        current = layout_or_404(conn, pid, layout_id)
    if body.get("project_id") is not None and str(body["project_id"]) != pid:
        raise ApiError(422, "immutable_field", "A layout stays in its project.")
    name = _text(body, "name", required=True, max_len=120)
    description = _text(body, "description", required=False, max_len=2000)
    revision = body.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ApiError(422, "invalid_request", "revision is required.", [{"pointer": "/revision", "message": "is required"}])
    blocks = _blocks(body)
    with db.connect(url) as conn:
        system = db.system_of_project(conn, pid, body.get("system_id") or current["system_id"])
        template_id = chosen_template(conn, pid, body.get("template_id"))
    if system is None:
        raise ApiError(422, "system_not_in_project", "The version is not one of this project.")
    types = block_types(request)
    choices = choices_for(request, pid, system["pid"])
    problems = layouts.validate_layout(blocks, block_types=types, choices=choices)
    if problems and body.get("reset_invalid") and all(p["code"] == "invalid_reference" for p in problems):
        blocks = layouts.reset_invalid(blocks, problems, types)
        problems = layouts.validate_layout(blocks, block_types=types, choices=choices)
    fail_on(problems)
    try:
        with db.connect(url) as conn:
            new = db.update_layout(conn, current["id"], based_on=revision, name=name, description=description,
                                   system_pid=system["pid"], template_id=template_id, blocks=blocks,
                                   who=g.caller.subject,
                                   now=request.app.state.clock())
            if new is None:
                latest = layout_or_404(conn, pid, layout_id)
                raise ApiError(409, "stale_revision",
                               f"The layout was saved meanwhile; the current revision is {latest['revision']}.",
                               [{"current_revision": latest["revision"]}])
            return layout_view(db.get_layout(conn, pid, current["id"]))
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A layout of this project already has this name.") from None


@router.delete("/p/{ref}/layouts/{layout_id}", status_code=204)
def delete_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("editor"))):
    with db.connect(request.app.state.database_url) as conn:
        if not db.delete_layout(conn, g.project["pid"], layout_id):
            raise ApiError(404, "not_found", NO_LAYOUT)
    return Response(status_code=204)


@router.post("/p/{ref}/layouts/{layout_id}/validate")
def validate(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer", origin_check=False))):
    with db.connect(request.app.state.database_url) as conn:
        layout = layout_or_404(conn, g.project["pid"], layout_id)
    problems = layouts.validate_layout(layout["blocks"], block_types=block_types(request),
                                       choices=choices_for(request, g.project["pid"], layout["system_id"]))
    return {"valid": not problems, "problems": problems}


@router.get("/p/{ref}/layouts/{layout_id}/preview")
def preview(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        layout = layout_or_404(conn, g.project["pid"], layout_id)
        template = template_of(conn, g.project["pid"], layout)
    result = renderer_call(request.app.state.renderer.render,
                           reports.snapshot_of(g.project, layout, "preview", g.caller, template))
    return HTMLResponse(result["html"], headers={"Content-Security-Policy": PREVIEW_CSP,
                                                 "X-Content-Type-Options": "nosniff"})


# Reports

@router.post("/p/{ref}/layouts/{layout_id}/reports")
def post_report(request: Request, layout_id: str, g: Guarded = Depends(project_guard("editor"))):
    status, body = reports.generate(request, g.project, layout_id, g.caller)
    return JSONResponse(status_code=status, content=body)


@router.get("/p/{ref}/layouts/{layout_id}/reports")
def get_reports(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        layout = layout_or_404(conn, g.project["pid"], layout_id)
        return db.list_reports(conn, layout["id"])


@router.get("/p/{ref}/reports/{report_id}/pdf")
def get_pdf(request: Request, report_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        report = db.get_report(conn, g.project["pid"], report_id)
    if report is None or report["pdf"] is None:
        raise ApiError(404, "not_found", "No such report.")
    snap = report["snapshot"] or {}
    name = reports.pdf_filename(g.project["slug"], report["system_number"], (snap.get("layout") or {}).get("name", ""),
                                report["created_at"])
    return Response(bytes(report["pdf"]), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# Templates: a report's look

def _save_template(request: Request, g: Guarded, body, template_id=None, rename_if_taken=False):
    look, logo = looks.checked(body, fonts(request))
    url, pid, now = request.app.state.database_url, g.project["pid"], request.app.state.clock()
    try:
        with db.connect(url) as conn:
            if template_id is not None and body.get("keep_logo") and "logo" not in body:
                current = template_or_404(conn, pid, template_id, with_logo=True)
                logo = (current["logo_mime"], bytes(current["logo"])) if current.get("logo") else None
            if rename_if_taken:
                look["name"] = looks.free_name(look["name"], db.template_names(conn, pid))
            if template_id is None:
                template_id = db.insert_template(conn, project_pid=pid, look=look, logo=logo, who=g.caller.subject,
                                                 now=now)
            elif not db.update_template(conn, pid, template_id, look=look, logo=logo, who=g.caller.subject, now=now):
                raise ApiError(404, "not_found", NO_TEMPLATE)
            return looks.view(template_or_404(conn, pid, template_id))
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A template of this project already has this name.") from None


@router.get("/fonts")
def get_fonts(request: Request, caller=Depends(signed_in)):
    return fonts(request)


@router.get("/p/{ref}/templates")
def get_templates(request: Request, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        return [looks.view(t) for t in db.list_templates(conn, g.project["pid"])]


@router.post("/p/{ref}/templates", status_code=201)
def post_template(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    return _save_template(request, g, body)


@router.post("/p/{ref}/templates/import", status_code=201)
def import_template(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    return _save_template(request, g, looks.from_export(body), rename_if_taken=True)


@router.put("/p/{ref}/templates/{template_id}")
def put_template(request: Request, template_id: str, body: dict = Body(...),
                 g: Guarded = Depends(project_guard("editor"))):
    with db.connect(request.app.state.database_url) as conn:
        current = template_or_404(conn, g.project["pid"], template_id)
    return _save_template(request, g, body, template_id=current["id"])


@router.delete("/p/{ref}/templates/{template_id}", status_code=204)
def delete_template(request: Request, template_id: str, g: Guarded = Depends(project_guard("editor"))):
    with db.connect(request.app.state.database_url) as conn:
        if not db.delete_template(conn, g.project["pid"], template_id):
            raise ApiError(404, "not_found", NO_TEMPLATE)
    return Response(status_code=204)


@router.get("/p/{ref}/templates/{template_id}/export")
def export_template(request: Request, template_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        t = template_or_404(conn, g.project["pid"], template_id, with_logo=True)
    return Response(json.dumps(looks.export_doc(t), indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{looks.filename(t["name"])}"'})


@router.get("/p/{ref}/templates/{template_id}/logo")
def template_logo(request: Request, template_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        t = template_or_404(conn, g.project["pid"], template_id, with_logo=True)
    if not t.get("logo"):
        raise ApiError(404, "not_found", "This template has no logo.")
    # an SVG is served as an image only: no script of it runs in this origin
    return Response(bytes(t["logo"]), media_type=t["logo_mime"],
                    headers={"Content-Security-Policy": LOGO_CSP,
                             "X-Content-Type-Options": "nosniff"})
