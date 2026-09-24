"""The composer's screens, drawn in Python.

Same rights as the API (the guard of api.py); errors come back as the error page. The only
script is static/composer.js, which reads the page's data-* attributes and calls the API.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import jinja2
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db, forms, layouts
from .api import ApiError, block_types, fonts, guard, renderer_call
from . import templates as looks

router = APIRouter()
_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
                          autoescape=True)
# The launcher, where the header's mark and "Back" lead, as in the other modules.
_env.globals["launcher"] = os.environ.get("LAUNCHER_URL", "http://localhost:8100/").rstrip("/") + "/"


def _root(request: Request) -> str:
    return request.scope.get("root_path", "") or ""


def _is_pid(ref: str) -> bool:
    try:
        uuid.UUID(ref)
        return True
    except ValueError:
        return False


def _page(name: str, request: Request, **context) -> HTMLResponse:
    return HTMLResponse(_env.get_template(name).render(root=_root(request), **context))


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
        return RedirectResponse(f"{_root(request)}/p/{g.project['slug']}/", status_code=303)
    url = request.app.state.database_url
    with db.connect(url) as conn:
        rows = db.list_layouts(conn, g.project["pid"])
        systems = db.systems(conn, g.project["pid"])
        templates = [looks.view(x) for x in db.list_templates(conn, g.project["pid"])]
    return _page("layouts.html.j2", request, project=g.project, layouts=rows, systems=systems,
                 templates=templates, editor=g.access.may_write)


def _form_for(block_type: dict, options: dict, choices: dict) -> list[dict]:
    values = {**(block_type.get("default_options") or {}), **(options or {})}
    return forms.form_fields(block_type["options_schema"], values, choices)


@router.get("/p/{ref}/layouts/{layout_id}")
def editor_page(request: Request, ref: str, layout_id: str):
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return RedirectResponse(f"{_root(request)}/p/{g.project['slug']}/layouts/{layout_id}", status_code=303)
    url = request.app.state.database_url
    with db.connect(url) as conn:
        layout = db.get_layout(conn, g.project["pid"], layout_id)
        if layout is None:
            raise ApiError(404, "not_found", "No such layout.")
        systems = db.systems(conn, g.project["pid"])
        report_rows = db.list_reports(conn, layout["id"])
        templates = [looks.view(x) for x in db.list_templates(conn, g.project["pid"])]
    editor = g.access.may_write
    types = block_types(request)
    by_type = {t["type_id"]: t for t in types}
    choices: dict[str, dict] = {}
    if editor:
        renderer = request.app.state.renderer
        for t in {b["block_type"] for b in layout["blocks"]}:
            if t in by_type and layouts.reference_options(by_type[t]):
                choices[t] = renderer_call(renderer.choices, g.project["pid"], layout["system_id"], t) or {}
    blocks = []
    for b in layout["blocks"]:
        t = by_type.get(b["block_type"])
        blocks.append({"instance_id": b["instance_id"], "block_type": b["block_type"],
                       "title": (b["options"] or {}).get("title") or (t["title"] if t else None), "known": t is not None,
                       "fields": _form_for(t, b["options"], choices.get(b["block_type"], {})) if (t and editor) else []})
    palette = [{"type_id": t["type_id"], "title": t["title"], "fields": _form_for(t, {}, {})} for t in types] \
        if editor else []
    return _page("editor.html.j2", request, project=g.project, layout=layout, blocks=blocks, systems=systems,
                 reports=report_rows, palette=palette, editor=editor, templates=templates)


@router.get("/p/{ref}/templates")
def templates_page(request: Request, ref: str):
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return RedirectResponse(f"{_root(request)}/p/{g.project['slug']}/templates", status_code=303)
    with db.connect(request.app.state.database_url) as conn:
        rows = [looks.view(x) for x in db.list_templates(conn, g.project["pid"])]
    font_list = fonts(request)
    labels = {f["id"]: f["label"] for f in font_list}
    return _page("templates.html.j2", request, project=g.project, templates=rows, fonts=font_list, labels=labels,
                 editor=g.access.may_write, here="templates")
