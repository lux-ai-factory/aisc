"""The composer's API under /api (report run 2026-09-23, R4.3, R4.4, D11, D12).

Rights come from two dependencies: `signed_in` (a verified caller, else 401) and
`project_guard(right)` (the project by slug or pid, the caller's role in it read on every
request, and for writes the same-origin check).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, Response

from aisc_identity.caller import IdentityMissing
from aisc_identity.service import Misconfigured, NotAuthenticated, caller_from_headers

from . import access, db, layouts, reports
from .errors import ApiError
from .renderer_client import RendererRejected, RendererTimeout, RendererUnavailable

router = APIRouter(prefix="/api")
NO_PROJECT = "No such project."
PREVIEW_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"


def platform_origin() -> str:
    return os.environ.get("PLATFORM_ORIGIN", "http://localhost")


def signed_in(request: Request):
    try:
        return caller_from_headers(request.headers)
    except (NotAuthenticated, IdentityMissing):
        raise ApiError(401, "not_signed_in", "Sign in first.") from None
    except Misconfigured:
        raise ApiError(500, "misconfigured", "Sign-in cannot be checked on this service.") from None


def check_origin(request: Request) -> None:
    if request.method.upper() not in access.SAFE_METHODS and not access.same_origin(request.headers,
                                                                                   platform_origin()):
        raise ApiError(403, "forbidden", "Cross-origin request refused.")


@dataclass(frozen=True)
class Guarded:
    caller: object
    project: dict
    access: access.Access


def guard(request: Request, ref: str, right: str, origin_check: bool = True) -> Guarded:
    caller = signed_in(request)
    database_url = request.app.state.database_url
    try:
        project = access.find_project(database_url, ref)
    except psycopg.Error:
        raise ApiError(503, "unavailable", "Who may be here cannot be established just now.") from None
    if project is None:
        raise ApiError(404, "not_found", NO_PROJECT)
    a = access.access_for(database_url, project, caller)
    verdict = access.decide("GET" if right == "viewer" else "POST", a)
    if verdict == "unavailable":
        raise ApiError(503, "unavailable", "Who may be here cannot be established just now.")
    if verdict == "not-found":
        raise ApiError(404, "not_found", NO_PROJECT)
    if verdict == "forbidden":
        raise ApiError(403, "forbidden", "You can read this project but not change it.")
    if origin_check:
        check_origin(request)
    return Guarded(caller, project, a)


def project_guard(right: str, origin_check: bool = True):
    def dependency(request: Request, ref: str) -> Guarded:
        return guard(request, ref, right, origin_check)

    return dependency


def requested_by(caller) -> str:
    return caller.username or caller.email or caller.subject


def snapshot_of(project, layout, mode, caller) -> dict:
    return {"project_id": project["pid"], "system_id": layout["system_id"],
            "layout": {"id": layout["id"], "name": layout["name"], "revision": layout["revision"]},
            "blocks": [{"instance_id": b["instance_id"], "block_type": b["block_type"], "options": b["options"]}
                       for b in layout["blocks"]],
            "mode": mode, "requested_by": requested_by(caller)}


def renderer_call(fn, *args):
    try:
        return fn(*args)
    except RendererTimeout:
        raise ApiError(504, "renderer_timeout", "The report renderer did not answer in time.") from None
    except RendererUnavailable:
        raise ApiError(502, "renderer_unavailable", "The report renderer is not available.") from None
    except RendererRejected as exc:
        if exc.status == 404:
            raise ApiError(404, "not_found", "Not found.") from None
        raise ApiError(422, "invalid_snapshot", "The renderer refused the layout.", exc.problems) from None


def block_types(request: Request) -> list:
    return renderer_call(request.app.state.renderer.block_types)


def choices_for(request: Request, project_pid: str, system_pid: str):
    renderer = request.app.state.renderer
    return lambda block_type: renderer_call(renderer.choices, project_pid, system_pid, block_type)


def fail_on(problems) -> None:
    if problems:
        raise ApiError(422, problems[0]["code"], problems[0]["message"] or "The layout is not valid.", problems)


def layout_view(layout: dict) -> dict:
    return {k: layout[k] for k in ("id", "project_id", "name", "description", "system_id", "revision", "blocks",
                                   "created_at", "updated_at")}


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


# ── versions, block types, choices ───────────────────────────────────────────

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


# ── layouts ──────────────────────────────────────────────────────────────────

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
        template = None
        if body.get("template_id") is not None:
            template = db.get_template(conn, body["template_id"])
            if template is None:
                raise ApiError(404, "not_found", "No such template.")
    types = block_types(request)
    if template is not None:
        blocks = layouts.from_template(template["blocks"])
    elif "blocks" in body and body["blocks"] is not None:
        blocks = _blocks(body)
    else:
        blocks = layouts.default_blocks(types)
    fail_on(layouts.validate_layout(blocks, block_types=types, choices=choices_for(request, pid, system["pid"]),
                                    allow_missing_references=template is not None))
    now = request.app.state.clock()
    try:
        with db.connect(url) as conn:
            lid = db.insert_layout(conn, project_pid=pid, system_pid=system["pid"], name=name,
                                   description=description, blocks=blocks, who=g.caller.subject, now=now)
            return layout_view(db.get_layout(conn, pid, lid))
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A layout of this project already has this name.") from None


def _layout_or_404(conn, pid, layout_id, for_update=False) -> dict:
    layout = db.get_layout(conn, pid, layout_id, for_update=for_update)
    if layout is None:
        raise ApiError(404, "not_found", "No such layout.")
    return layout


@router.get("/p/{ref}/layouts/{layout_id}")
def get_layout(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        return layout_view(_layout_or_404(conn, g.project["pid"], layout_id))


@router.put("/p/{ref}/layouts/{layout_id}")
def put_layout(request: Request, layout_id: str, body: dict = Body(...),
               g: Guarded = Depends(project_guard("editor"))):
    pid = g.project["pid"]
    url = request.app.state.database_url
    with db.connect(url) as conn:
        current = _layout_or_404(conn, pid, layout_id)
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
                                   system_pid=system["pid"], blocks=blocks, who=g.caller.subject,
                                   now=request.app.state.clock())
            if new is None:
                latest = _layout_or_404(conn, pid, layout_id)
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
            raise ApiError(404, "not_found", "No such layout.")
    return Response(status_code=204)


@router.post("/p/{ref}/layouts/{layout_id}/validate")
def validate(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer", origin_check=False))):
    with db.connect(request.app.state.database_url) as conn:
        layout = _layout_or_404(conn, g.project["pid"], layout_id)
    problems = layouts.validate_layout(layout["blocks"], block_types=block_types(request),
                                       choices=choices_for(request, g.project["pid"], layout["system_id"]))
    return {"valid": not problems, "problems": problems}


@router.get("/p/{ref}/layouts/{layout_id}/preview")
def preview(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        layout = _layout_or_404(conn, g.project["pid"], layout_id)
    result = renderer_call(request.app.state.renderer.render, snapshot_of(g.project, layout, "preview", g.caller))
    return HTMLResponse(result["html"], headers={"Content-Security-Policy": PREVIEW_CSP,
                                                 "X-Content-Type-Options": "nosniff"})


# ── reports ──────────────────────────────────────────────────────────────────

@router.post("/p/{ref}/layouts/{layout_id}/reports")
def post_report(request: Request, layout_id: str, g: Guarded = Depends(project_guard("editor"))):
    status, body = reports.generate(request, g.project, layout_id, g.caller)
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status, content=body)


@router.get("/p/{ref}/layouts/{layout_id}/reports")
def get_reports(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        layout = _layout_or_404(conn, g.project["pid"], layout_id)
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


# ── templates ────────────────────────────────────────────────────────────────

def _template_row(t: dict) -> dict:
    return {"id": t["id"], "name": t["name"], "description": t["description"],
            "block_types": [b["block_type"] for b in t["blocks"]],
            **({"created_by": t["created_by"], "created_at": t["created_at"]} if "created_by" in t else {})}


@router.post("/p/{ref}/layouts/{layout_id}/template", status_code=201)
def post_template(request: Request, layout_id: str, body: dict = Body(...),
                  g: Guarded = Depends(project_guard("editor"))):
    name = _text(body, "name", required=True, max_len=120)
    description = _text(body, "description", required=False, max_len=2000)
    url = request.app.state.database_url
    with db.connect(url) as conn:
        layout = _layout_or_404(conn, g.project["pid"], layout_id)
    blocks = layouts.to_template(layout["blocks"], block_types(request), keep_text=bool(body.get("keep_text")))
    try:
        with db.connect(url) as conn:
            t = db.insert_template(conn, name=name, description=description, blocks=blocks,
                                   source_project_id=g.project["pid"], created_by=g.caller.subject,
                                   now=request.app.state.clock())
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A template already has this name.") from None
    return {"id": t["id"], "name": t["name"], "description": t["description"],
            "block_types": [b["block_type"] for b in t["blocks"]]}


@router.get("/templates")
def get_templates(request: Request, caller=Depends(signed_in)):
    with db.connect(request.app.state.database_url) as conn:
        return [_template_row(t) for t in db.list_templates(conn)]


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(request: Request, template_id: str, caller=Depends(signed_in)):
    check_origin(request)
    with db.connect(request.app.state.database_url) as conn:
        t = db.get_template(conn, template_id)
        if t is None:
            raise ApiError(404, "not_found", "No such template.")
        if t["created_by"] != caller.subject and not caller.has_role(access.ADMIN_ROLE):
            raise ApiError(403, "forbidden", "Only the template's creator or an admin may delete it.")
        db.delete_template(conn, t["id"])
    return Response(status_code=204)
