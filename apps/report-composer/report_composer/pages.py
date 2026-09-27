"""The composer's screens, drawn in Python.

Same rights as the API (the guard of api.py); errors come back as the error page. The only
script is static/composer.js, which reads the page's data-* attributes and calls the API.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import coverage_map, db, forms, layouts, presets, prose
from . import templates as looks
from .api import may_delete_preset
from .guards import guard
from .jinja_env import env
from .records import layout_or_404
from .renderer_calls import block_types, coverage_choices_for, fonts, renderer_call

router = APIRouter()


def _root(request: Request) -> str:
    return request.scope.get("root_path", "") or ""


def _is_pid(ref: str) -> bool:
    try:
        uuid.UUID(ref)
        return True
    except ValueError:
        return False


def _page(name: str, request: Request, **context) -> HTMLResponse:
    return HTMLResponse(env.get_template(name).render(root=_root(request), **context))


def _by_slug(request: Request, project: dict, rest: str) -> RedirectResponse:
    """A page asked for by the project's pid is redirected to the same page by its slug."""
    return RedirectResponse(f"{_root(request)}/p/{project['slug']}{rest}", status_code=303)


def _templates(conn, project_pid) -> list[dict]:
    return [looks.view(x) for x in db.list_templates(conn, project_pid)]


@router.get("/")
def home():
    return RedirectResponse(os.environ.get("LAUNCHER_URL", "http://localhost:8100/"), status_code=303)


@router.get("/p/{ref}")
def layouts_page_without_slash(request: Request, ref: str):
    # The launcher links here without the slash. Starlette's own slash redirect
    # would drop the root path, sending the browser out of the composer.
    return RedirectResponse(f"{_root(request)}/p/{ref}/", status_code=307)


@router.get("/p/{ref}/")
def layouts_page(request: Request, ref: str):
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return _by_slug(request, g.project, "/")
    url = request.app.state.database_url
    with db.connect(url) as conn:
        rows = db.list_layouts(conn, g.project["pid"])
        systems = db.systems(conn, g.project["pid"])
        templates = _templates(conn, g.project["pid"])
        saved = [presets.from_row(r) for r in db.list_presets(conn)]
    saved_presets = [{**presets.summary(p), "may_delete": may_delete_preset(p, g.caller)} for p in saved]
    return _page("layouts.html.j2", request, project=g.project, layouts=rows, systems=systems,
                 templates=templates, editor=g.access.may_write, built_in_presets=presets.built_in(),
                 saved_presets=saved_presets)


def _form_for(block_type: dict, options: dict, choices: dict) -> list[dict]:
    values = {**(block_type.get("default_options") or {}), **(options or {})}
    return forms.form_fields(block_type["options_schema"], values, choices)


def _reference_choices(request: Request, project: dict, layout: dict, by_type: dict) -> dict[str, dict]:
    """The values each reference option of the layout's block types may take, by block type."""
    renderer = request.app.state.renderer
    choices: dict[str, dict] = {}
    for t in {b["block_type"] for b in layout["blocks"]}:
        if t in by_type and layouts.reference_options(by_type[t]):
            choices[t] = renderer_call(renderer.choices, project["pid"], layout["system_id"], t) or {}
    return choices


def _outline_entry(block: dict, block_type: dict | None, choices: dict, editor: bool, depth: int = 0,
                   empty_chapter: bool = False, problems=()) -> dict:
    """A block as the editor's outline draws it; an editor also gets its configure form. A block still
    holding the placeholder in a prose option gets the unwritten hint (R2-D3.8.3)."""
    unwritten = prose.unwritten(block["block_type"], block["options"] or {}, block_type)
    return {"instance_id": block["instance_id"], "block_type": block["block_type"],
            "title": (block["options"] or {}).get("title") or (block_type["title"] if block_type else None),
            "known": block_type is not None, "depth": depth, "empty_chapter": empty_chapter,
            "unwritten_hint": prose.unwritten_hint(block["block_type"], unwritten),
            "problems": [p["message"] for p in problems],
            "fields": _form_for(block_type, block["options"], choices.get(block["block_type"], {}))
            if (block_type and editor) else []}


@router.get("/p/{ref}/layouts/{layout_id}")
def editor_page(request: Request, ref: str, layout_id: str):
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return _by_slug(request, g.project, f"/layouts/{layout_id}")
    url = request.app.state.database_url
    with db.connect(url) as conn:
        layout = layout_or_404(conn, g.project["pid"], layout_id)
        systems = db.systems(conn, g.project["pid"])
        report_rows = db.list_reports(conn, layout["id"])
        templates = _templates(conn, g.project["pid"])
    editor = g.access.may_write
    pid = g.project["pid"]
    types = block_types(request)
    by_type = {t["type_id"]: t for t in types}
    choices = _reference_choices(request, g.project, layout, by_type) if editor else {}
    cover_choices = coverage_choices_for(request, pid, layout["system_id"])
    problems = layouts.validate_layout(layout["blocks"], block_types=types, choices=lambda t: choices.get(t, {}),
                                       coverage=layout.get("coverage"), coverage_choices=cover_choices) \
        if editor else []
    by_block: dict[str, list] = {}
    for p in problems:
        by_block.setdefault(p.get("instance_id"), []).append(p)
    depths = layouts.outline_depths(layout["blocks"])
    blocks = [_outline_entry(b, by_type.get(b["block_type"]), choices, editor, depth, empty,
                             by_block.get(b["instance_id"], ()))
              for b, (depth, empty) in zip(layout["blocks"], depths)]
    palette = [{"type_id": t["type_id"], "title": t["title"], "description": t.get("description") or "",
                "fields": _form_for(t, t.get("new_instance_options") or {}, {})} for t in types] if editor else []
    number = next((s["number"] for s in systems if s["pid"] == layout["system_id"]), None)
    grid = coverage_map.grid(layout.get("coverage"), cover_choices, number)
    template_ids = {t["id"] for t in templates}
    return _page("editor.html.j2", request, project=g.project, layout=layout, blocks=blocks, systems=systems,
                 reports=report_rows, palette=palette, editor=editor, templates=templates,
                 grid=grid, map_problems=by_block.get(None, []),
                 template_known=layout.get("template_id") in template_ids)


@router.get("/p/{ref}/templates")
def templates_page(request: Request, ref: str):
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return _by_slug(request, g.project, "/templates")
    with db.connect(request.app.state.database_url) as conn:
        rows = [looks.view(x) for x in db.list_templates(conn, g.project["pid"])]
    font_list = fonts(request)
    labels = {f["id"]: f["label"] for f in font_list}
    return _page("templates.html.j2", request, project=g.project, templates=rows, fonts=font_list, labels=labels,
                 editor=g.access.may_write, here="templates")
