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

from . import coverage_map, db, layouts, presets, reports
from . import templates as looks
from .errors import ApiError, fail_on
from .guards import Guarded, check_origin, project_guard, signed_in
from .records import NO_LAYOUT, NO_TEMPLATE, chosen_template, layout_or_404, template_of, template_or_404
from .renderer_calls import block_types, choices_for, coverage_choices_for, fonts, renderer_call
from .settings import document_settings

router = APIRouter(prefix="/api")
PREVIEW_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
LOGO_CSP = "default-src 'none'; style-src 'unsafe-inline'"
NAME_MAX, DESCRIPTION_MAX = 120, 2000
DRAFT_MAX_BYTES = 1_048_576


def layout_view(layout: dict) -> dict:
    return {k: layout[k] for k in ("id", "project_id", "name", "description", "system_id", "template_id", "revision",
                                   "blocks", "created_at", "updated_at", "toc", "numbering", "coverage")}


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


def _system_not_in_project() -> ApiError:
    return ApiError(422, "system_not_in_project", "The version is not one of this project.")


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


def _preset_named(conn, preset_id) -> presets.Preset:
    """A built-in preset by id or a saved one by uuid, or 422 unknown_preset."""
    found = presets.built_in_by_id(preset_id) if isinstance(preset_id, str) else None
    if found is None and isinstance(preset_id, str):
        row = db.get_preset(conn, preset_id)
        found = presets.from_row(row) if row else None
    if found is None:
        raise ApiError(422, "unknown_preset", "No such preset.", [{"pointer": "/preset", "message": "is not a preset"}])
    return found


def _preset_settings(preset: presets.Preset | None) -> dict:
    """The document settings a preset starts a layout with: toc and numbering (R2-D1.13)."""
    if preset is None:
        return {}
    return {k: v for k, v in (("toc", preset.toc), ("numbering", preset.numbering)) if v is not None}


@router.post("/p/{ref}/layouts", status_code=201)
def post_layout(request: Request, body: dict = Body(...), g: Guarded = Depends(project_guard("editor"))):
    sources = [k for k in ("preset", "preset_file", "blocks") if body.get(k) is not None]
    if len(sources) > 1:
        raise ApiError(422, "invalid_request", "Give at most one of preset, preset_file and blocks.",
                       [{"pointer": "/" + k, "message": "only one source of blocks"} for k in sources])
    pid = g.project["pid"]
    url = request.app.state.database_url
    types = block_types(request)
    preset = None
    with db.connect(url) as conn:
        system = _system_for_new_layout(conn, pid, body.get("system_id"))
        template_id = chosen_template(conn, pid, body.get("template_id"))
        if body.get("preset") == "empty":
            preset = presets.Preset(id="empty", name="Empty layout")
        elif body.get("preset") is not None:
            preset = _preset_named(conn, body["preset"])
        elif body.get("preset_file") is not None:
            preset = presets.from_file(body["preset_file"], types)
        taken = db.layout_names(conn, pid)
    if body.get("name") is None and body.get("preset_file") is not None:
        body = {**body, "name": looks.free_name(preset.name, taken)}
    name, description = _name_and_description(body)
    if preset is not None:
        blocks = presets.blocks_for_layout(preset, types)
    elif body.get("blocks") is not None:
        blocks = _blocks(body)
    else:
        blocks = layouts.default_blocks(types)
    settings = document_settings(body, _preset_settings(preset))
    fail_on(layouts.validate_layout(
        blocks, block_types=types, choices=choices_for(request, pid, system["pid"]),
        allow_missing_references=preset is not None, coverage=settings["coverage"],
        coverage_choices=lambda: coverage_choices_for(request, pid, system["pid"])))
    now = request.app.state.clock()
    try:
        with db.connect(url) as conn:
            lid = db.insert_layout(conn, project_pid=pid, system_pid=system["pid"], template_id=template_id, name=name,
                                   description=description, blocks=blocks, who=g.caller.subject, now=now,
                                   settings=settings)
            view = layout_view(db.get_layout(conn, pid, lid))
    except psycopg.errors.UniqueViolation:
        raise _layout_name_taken() from None
    if body.get("preset_file") is not None:
        view["notices"] = presets.reference_notices(preset.reset, "data that is not in this project")
    return view


def _system_for_new_layout(conn, pid, system_id) -> dict:
    """The version asked for, or the project's latest when none is."""
    if system_id is not None:
        system = db.system_of_project(conn, pid, system_id)
        if system is None:
            raise _system_not_in_project()
        return system
    system = db.latest_system(conn, pid)
    if system is None:
        raise ApiError(422, "system_not_in_project", "This project has no system version yet.")
    return system


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
    name, description = _name_and_description(body)
    revision = _revision(body)
    blocks = _blocks(body)
    with db.connect(url) as conn:
        system = db.system_of_project(conn, pid, body.get("system_id") or current["system_id"])
        template_id = chosen_template(conn, pid, body.get("template_id"))
    if system is None:
        raise _system_not_in_project()
    settings = document_settings(body, current)
    blocks, settings["coverage"] = _checked_blocks(
        blocks, block_types(request), choices_for(request, pid, system["pid"]),
        reset_invalid=bool(body.get("reset_invalid")), coverage=settings["coverage"],
        coverage_choices=_once(lambda: coverage_choices_for(request, pid, system["pid"])))
    try:
        with db.connect(url) as conn:
            new = db.update_layout(conn, current["id"], based_on=revision, name=name, description=description,
                                   system_pid=system["pid"], template_id=template_id, blocks=blocks,
                                   who=g.caller.subject, now=request.app.state.clock(), settings=settings)
            if new is None:
                latest = layout_or_404(conn, pid, layout_id)
                raise ApiError(409, "stale_revision",
                               f"The layout was saved meanwhile; the current revision is {latest['revision']}.",
                               [{"current_revision": latest["revision"]}])
            return layout_view(db.get_layout(conn, pid, current["id"]))
    except psycopg.errors.UniqueViolation:
        raise _layout_name_taken() from None


def _once(fn):
    """fn called at most once, its answer kept."""
    kept = []

    def call():
        if not kept:
            kept.append(fn())
        return kept[0]
    return call


def _checked_blocks(blocks, types, choices, *, reset_invalid: bool, coverage=(), coverage_choices=None):
    """(blocks, coverage map), or a 422 naming their problems. With reset_invalid, a layout whose only
    problems are invalid references has those options reset to their defaults, and the map loses
    the values the version does not offer."""
    coverage = list(coverage or [])
    problems = layouts.validate_layout(blocks, block_types=types, choices=choices, coverage=coverage,
                                       coverage_choices=coverage_choices)
    if problems and reset_invalid and all(p["code"] == "invalid_reference" for p in problems):
        blocks = layouts.reset_invalid(blocks, problems, types)
        if coverage:
            coverage = coverage_map.reset(coverage, coverage_choices())
        problems = layouts.validate_layout(blocks, block_types=types, choices=choices, coverage=coverage,
                                           coverage_choices=coverage_choices)
    fail_on(problems)
    return blocks, coverage


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
    pid = g.project["pid"]
    problems = layouts.validate_layout(
        layout["blocks"], block_types=block_types(request), choices=choices_for(request, pid, layout["system_id"]),
        coverage=layout.get("coverage"),
        coverage_choices=lambda: coverage_choices_for(request, pid, layout["system_id"]))
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


@router.post("/p/{ref}/layouts/{layout_id}/outline")
def outline(request: Request, layout_id: str, body: dict = Body(...),
            g: Guarded = Depends(project_guard("editor"))):
    """Indentation and empty-chapter hints for the editor's current block order; nothing is stored."""
    with db.connect(request.app.state.database_url) as conn:
        layout_or_404(conn, g.project["pid"], layout_id)
    blocks = _blocks(body)
    if len(blocks) > layouts.MAX_BLOCKS:   # the limit of layout save (fix round 2, item 4)
        raise ApiError(422, "too_many_blocks", f"A layout holds at most {layouts.MAX_BLOCKS} blocks.",
                       [{"pointer": "/blocks", "message": f"a layout holds at most {layouts.MAX_BLOCKS} blocks"}])
    if not all(isinstance(b["block_type"], str) for b in blocks):
        raise ApiError(422, "invalid_request", "Every block needs a block_type.",
                       [{"pointer": "/blocks", "message": "is not valid"}])
    return {"outline": layouts.outline(blocks)}


@router.post("/p/{ref}/layouts/{layout_id}/preview")
async def preview_draft(request: Request, layout_id: str, g: Guarded = Depends(project_guard("editor"))):
    """The editor's unsaved state rendered as a preview; nothing is stored (report run v2, R-U3.1)."""
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
    pid = g.project["pid"]
    with db.connect(request.app.state.database_url) as conn:
        current = layout_or_404(conn, pid, layout_id)
        system = db.system_of_project(conn, pid, body.get("system_id") or current["system_id"])
        if system is None:
            raise _system_not_in_project()
        template_id = chosen_template(conn, pid, body.get("template_id"))
        template = db.get_template(conn, pid, template_id, with_logo=True) if template_id else None
    settings = document_settings(body, current)
    blocks = _blocks(body) if body.get("blocks") is not None else current["blocks"]
    problems = layouts.validate_layout(
        blocks, block_types=block_types(request), choices=choices_for(request, pid, system["pid"]),
        coverage=settings["coverage"], coverage_choices=lambda: coverage_choices_for(request, pid, system["pid"]))
    draft = {**current, **settings, "system_id": system["pid"], "blocks": blocks}
    result = renderer_call(request.app.state.renderer.render,
                           reports.snapshot_of(g.project, draft, "preview", g.caller, template))
    return {"html": reports.with_csp_meta(result.get("html") or ""), "problems": problems,
            "block_statuses": list(result.get("block_statuses") or [])}


# Duplicate, export and presets

@router.post("/p/{ref}/layouts/{layout_id}/duplicate", status_code=201)
def duplicate_layout(request: Request, layout_id: str, body: dict | None = Body(None),
                     g: Guarded = Depends(project_guard("editor"))):
    body = body or {}
    pid = g.project["pid"]
    url = request.app.state.database_url
    now = request.app.state.clock()
    try:
        with db.connect(url) as conn:
            src = layout_or_404(conn, pid, layout_id)
            if body.get("name") is not None:
                name = _text(body, "name", required=True, max_len=NAME_MAX)
            else:
                name = presets.copy_name(src["name"], db.layout_names(conn, pid))
            blocks = [{"instance_id": str(uuid.uuid4()), "block_type": b["block_type"], "options": b["options"]}
                      for b in src["blocks"]]
            settings = {k: src[k] for k in ("toc", "numbering", "coverage")}
            lid = db.insert_layout(conn, project_pid=pid, system_pid=src["system_id"], template_id=src["template_id"],
                                   name=name, description=src.get("description") or "", blocks=blocks,
                                   who=g.caller.subject, now=now, settings=settings)
            return layout_view(db.get_layout(conn, pid, lid))
    except psycopg.errors.UniqueViolation:
        raise _layout_name_taken() from None


def _preset_file_response(p: presets.Preset) -> Response:
    slug = reports._slugify(p.name)[:60]
    return Response(json.dumps(presets.export_doc(p), indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="report-preset-{slug}.json"'})


@router.get("/p/{ref}/layouts/{layout_id}/export")
def export_layout(request: Request, layout_id: str, keep_text: bool = False,
                  g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        layout = layout_or_404(conn, g.project["pid"], layout_id)
    return _preset_file_response(presets.from_layout(layout, block_types(request), keep_text=keep_text))


def _insert_preset(conn, p: presets.Preset, *, source_project_id, who, now) -> str:
    return db.insert_preset(conn, name=p.name, description=p.description, toc=p.toc, numbering=p.numbering,
                            blocks=p.blocks, source_project_id=source_project_id, who=who, now=now)


@router.post("/p/{ref}/layouts/{layout_id}/preset", status_code=201)
def save_as_preset(request: Request, layout_id: str, body: dict = Body(...),
                   g: Guarded = Depends(project_guard("editor"))):
    name = presets.checked_name(body.get("name"))
    description = _text(body, "description", required=False, max_len=DESCRIPTION_MAX)
    try:
        with db.connect(request.app.state.database_url) as conn:
            layout = layout_or_404(conn, g.project["pid"], layout_id)
            p = presets.from_layout(layout, block_types(request), keep_text=bool(body.get("keep_text")))
            p.name, p.description = name, description
            p.id = _insert_preset(conn, p, source_project_id=g.project["pid"], who=g.caller.subject,
                                  now=request.app.state.clock())
    except psycopg.errors.UniqueViolation:
        raise ApiError(422, "name_taken", "A preset already has this name.") from None
    return presets.summary(p)


def _all_presets(conn) -> list[presets.Preset]:
    return presets.built_in() + [presets.from_row(r) for r in db.list_presets(conn)]


@router.get("/presets")
def get_presets(request: Request, caller=Depends(signed_in)):
    with db.connect(request.app.state.database_url) as conn:
        return [presets.summary(p) for p in _all_presets(conn)]


@router.post("/presets/import", status_code=201)
def import_preset(request: Request, body=Body(...), caller=Depends(signed_in)):
    check_origin(request)
    p = presets.from_file(body, block_types(request))
    with db.connect(request.app.state.database_url) as conn:
        p.name = looks.free_name(p.name, db.preset_names(conn))
        p.id = _insert_preset(conn, p, source_project_id=None, who=caller.subject, now=request.app.state.clock())
    return {**presets.summary(p), "notices": presets.reference_notices(p.reset, "data of another project or platform")}


def _preset_or_404(conn, preset_id) -> presets.Preset:
    found = presets.built_in_by_id(preset_id)
    if found is None:
        row = db.get_preset(conn, preset_id)
        found = presets.from_row(row) if row else None
    if found is None:
        raise ApiError(404, "not_found", "No such preset.")
    return found


@router.get("/presets/{preset_id}/export")
def export_preset(request: Request, preset_id: str, caller=Depends(signed_in)):
    with db.connect(request.app.state.database_url) as conn:
        return _preset_file_response(_preset_or_404(conn, preset_id))


def may_delete_preset(p: presets.Preset, caller) -> bool:
    """A saved preset is deleted by its creator or a realm admin; a built-in one by nobody."""
    return not p.built_in and (p.created_by == caller.subject or caller.has_role("admin"))


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(request: Request, preset_id: str, caller=Depends(signed_in)):
    check_origin(request)
    with db.connect(request.app.state.database_url) as conn:
        p = _preset_or_404(conn, preset_id)
        if not may_delete_preset(p, caller):
            raise ApiError(403, "forbidden", "Only its creator or an administrator deletes this preset."
                           if not p.built_in else "A built-in preset cannot be deleted.")
        db.delete_preset(conn, preset_id)
    return Response(status_code=204)


# Reports

@router.post("/p/{ref}/layouts/{layout_id}/reports")
def post_report(request: Request, layout_id: str, body: dict | None = Body(None),
                g: Guarded = Depends(project_guard("editor"))):
    fmt = (body or {}).get("format") or "pdf"
    if fmt not in reports.FORMATS:
        raise ApiError(422, "invalid_request", "format must be pdf or docx.",
                       [{"pointer": "/format", "message": "must be one of pdf, docx"}])
    status, answer = reports.generate(request, g.project, layout_id, g.caller, fmt)
    return JSONResponse(status_code=status, content=answer)


@router.get("/p/{ref}/layouts/{layout_id}/reports")
def get_reports(request: Request, layout_id: str, g: Guarded = Depends(project_guard("viewer"))):
    with db.connect(request.app.state.database_url) as conn:
        layout = layout_or_404(conn, g.project["pid"], layout_id)
        return db.list_reports(conn, layout["id"])


def _document(request: Request, g: Guarded, report_id: str, only_pdf: bool) -> Response:
    with db.connect(request.app.state.database_url) as conn:
        report = db.get_report(conn, g.project["pid"], report_id)
    fmt = (report or {}).get("format") or "pdf"
    if report is None or report["pdf"] is None or (only_pdf and fmt != "pdf"):
        raise ApiError(404, "not_found", "No such report.")
    snap = report["snapshot"] or {}
    name = reports.document_filename(g.project["slug"], report["system_number"],
                                     (snap.get("layout") or {}).get("name", ""), report["created_at"], fmt)
    return Response(bytes(report["pdf"]), media_type=reports.MEDIA_TYPES[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/p/{ref}/reports/{report_id}/pdf")
def get_pdf(request: Request, report_id: str, g: Guarded = Depends(project_guard("viewer"))):
    return _document(request, g, report_id, only_pdf=True)


@router.get("/p/{ref}/reports/{report_id}/download")
def download(request: Request, report_id: str, g: Guarded = Depends(project_guard("viewer"))):
    return _document(request, g, report_id, only_pdf=False)


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
