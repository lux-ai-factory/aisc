"""The composer's screens, drawn in Python.

Same rights as the API (the guard of api.py); errors come back as the error page. The only
script is static/composer.js, which reads the page's data-* attributes and calls the API.
"""
from __future__ import annotations

import os
import uuid

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from . import builtin_layouts, db, forms, groups, layouts, preview_with, prose, reports
from . import templates as looks
from .errors import ApiError
from .guards import guard
from .jinja_env import env
from .records import layout_or_404
from .renderer_calls import block_types, fonts, renderer_call

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


def _templates(conn) -> list[dict]:
    return [looks.view(x) for x in db.list_templates(conn)]


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
    """The layouts: the five built-in ones, then the project's (report modules spec 2026-09-28, 4 and 5)."""
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return _by_slug(request, g.project, "/")
    with request.app.state.projects.connect(g.project["pid"]) as conn:
        rows = db.list_layouts(conn)
    return _page("layouts.html.j2", request, project=g.project, layouts=rows,
                 builtins=builtin_layouts.all_layouts(block_types(request)), editor=g.access.may_write)


def _form_for(block_type: dict, options: dict, choices: dict) -> list[dict]:
    values = {**(block_type.get("default_options") or {}), **(options or {})}
    return forms.form_fields(block_type["options_schema"], values, choices)


def _reference_choices(request: Request, project: dict, layout: dict, by_type: dict, system_pid) -> dict[str, dict]:
    """The values each reference option of the layout's block types may take, by block type."""
    renderer = request.app.state.renderer
    choices: dict[str, dict] = {}
    for t in {b["block_type"] for b in layout["blocks"]}:
        if t in by_type and layouts.reference_options(by_type[t]):
            choices[t] = renderer_call(renderer.choices, project["pid"], system_pid, t) or {} if system_pid else {}
    return choices


def _outline_entry(block: dict, block_type: dict | None, choices: dict, editor: bool, depth: int = 0,
                   empty_chapter: bool = False, problems=(), number: str = "") -> dict:
    """A block as the editor's outline draws it; an editor also gets its configure form. A block still
    holding the placeholder in a prose option gets the unwritten hint (R2-D3.8.3)."""
    unwritten = prose.unwritten(block["block_type"], block["options"] or {}, block_type)
    return {"instance_id": block["instance_id"], "block_type": block["block_type"],
            "title": (block["options"] or {}).get("title") or (block_type["title"] if block_type else None),
            "known": block_type is not None, "depth": depth, "empty_chapter": empty_chapter, "number": number,
            "unwritten_hint": prose.unwritten_hint(block["block_type"], unwritten),
            "problems": [p["message"] for p in problems],
            "fields": _form_for(block_type, block["options"], choices.get(block["block_type"], {}))
            if (block_type and editor) else []}


NO_VERSION = "This project has no AI card version yet. Save the AI card in qualification first."
EMPTY_LAYOUT = {"id": "", "name": "", "description": "", "revision": 0, "template_id": None, "show_index": True,
                "numbering": True, "blocks": []}


def _report_view(row: dict) -> dict:
    """A generated report as the editor lists it: what it covered, in words."""
    last = reports.report_row(row)["last_day"]
    start = row["period_from"].date().isoformat() if row.get("period_from") else None
    if start or last:
        period = f"{start or 'the start'} to {last or 'today'}"
    else:
        period = "All runs"
    return {**row, "period": period, "other": "Yes" if row.get("other_versions") else "No",
            "compare": f"Version {row['compare_number']}" if row.get("compare_number") else ""}


def _preview_query(request: Request) -> dict:
    q = request.query_params
    return {k: q.get(k) for k in ("system_id", "period_from", "period_to", "other_versions") if q.get(k)}


@router.get("/p/{ref}/layouts/{layout_id}")
def editor_page(request: Request, ref: str, layout_id: str):
    """One editor for a saved layout, a new one (`new`, nothing saved until Save) and a built-in one
    (read-only); the preview is drawn with the version and period of `?system_id=&period_from=...`,
    never saved (report modules spec 2026-09-28, section 5)."""
    g = guard(request, ref, "editor" if layout_id == "new" else "viewer")
    if _is_pid(ref):
        return _by_slug(request, g.project, f"/layouts/{layout_id}")
    types = block_types(request)
    builtin = builtin_layouts.get(layout_id, types)
    with request.app.state.projects.connect(g.project["pid"]) as conn:
        if layout_id == "new":
            layout, report_rows = dict(EMPTY_LAYOUT), []
        elif builtin is not None:
            layout, report_rows = builtin, []
        else:
            layout = layout_or_404(conn, layout_id)
            report_rows = db.list_reports(conn, layout["id"])
        systems = db.systems(conn)
        templates = _templates(conn)
        asked = _preview_query(request)
        pw = preview_with.parse(conn, asked)
    read_only = builtin is not None
    editor = g.access.may_write and not read_only
    system_pid = pw.system["pid"] if pw.system else None
    by_type = {t["type_id"]: t for t in types}
    choices = _reference_choices(request, g.project, layout, by_type, system_pid) if editor else {}
    problems = layouts.validate_layout(layout["blocks"], block_types=types, choices=lambda t: choices.get(t, {})) \
        if editor and system_pid else []
    by_block: dict[str, list] = {}
    for p in problems:
        by_block.setdefault(p.get("instance_id"), []).append(p)
    depths = layouts.outline_depths(layout["blocks"])
    numbers = layouts.outline_numbers(layout["blocks"], bool(layout.get("numbering")))
    blocks = [_outline_entry(b, by_type.get(b["block_type"]), choices, editor, depth, empty,
                             by_block.get(b["instance_id"], ()), number)
              for b, (depth, empty), number in zip(layout["blocks"], depths, numbers)]
    palette = [{"label": grp["label"], "types": [
        {"type_id": t["type_id"], "title": t["title"], "description": t.get("description") or "",
         "fields": _form_for(t, t.get("new_instance_options") or {}, {})} for t in grp["types"]]}
        for grp in groups.palette(types)] if editor else []
    template_ids = {t["id"] for t in templates}
    shown = {**asked, "system_id": system_pid}
    preview_src = (f"{_root(request)}/api/p/{g.project['slug']}/"
                   + (f"builtin-layouts/{layout['id']}" if read_only else f"layouts/{layout['id']}") + "/preview"
                   + ("?" + urlencode(shown) if system_pid else ""))
    return _page("editor.html.j2", request, project=g.project, layout=layout, blocks=blocks, systems=systems,
                 reports=[_report_view(r) for r in report_rows], palette=palette, editor=editor, templates=templates,
                 layout_problems=by_block.get(None, []), is_new=layout_id == "new", read_only=read_only,
                 may_write=g.access.may_write, preview_with=shown, preview_src=preview_src, no_version=NO_VERSION,
                 template_known=layout.get("template_id") in template_ids)


def _problem_lines(details, layout: dict, types: list[dict]) -> list[str]:
    """Each refused option as "<module title>: <option>: <message>", in the layout's order (final review I1)."""
    titles = {t["type_id"]: t["title"] for t in types}
    names = {b["instance_id"]: (b.get("options") or {}).get("title") or titles.get(b["block_type"], b["block_type"])
             for b in layout["blocks"]}
    order = {b["instance_id"]: i for i, b in enumerate(layout["blocks"])}
    rows = [d for d in details if isinstance(d, dict) and d.get("message") and d.get("instance_id")]
    rows.sort(key=lambda d: order.get(d.get("instance_id"), len(order)))
    return [": ".join(x for x in (names.get(d.get("instance_id"), "Layout"), (d.get("pointer") or "").strip("/"),
                                  d["message"]) if x) for d in rows]


def generate_context(layout: dict, systems: list, error: str | None = None, form: dict | None = None,
                     problems: list | None = None) -> dict:
    """What the Generate report page shows: the versions newest first, Compare with only when the layout
    compares versions, and the message of a project without a version (report modules spec, section 6)."""
    return {"systems": systems, "has_changes_since": any(b["block_type"] == "changes_since" for b in layout["blocks"]),
            "message": None if systems else NO_VERSION, "error": error, "form": form or {}, "problems": problems or []}


def _generate_page(request: Request, g, layout: dict, systems, status_code=200, **kw) -> HTMLResponse:
    page = _page("generate.html.j2", request, project=g.project, layout=layout,
                 **generate_context(layout, systems, **kw))
    page.status_code = status_code
    return page


@router.get("/p/{ref}/layouts/{layout_id}/generate")
def generate_page(request: Request, ref: str, layout_id: str):
    g = guard(request, ref, "editor")
    with request.app.state.projects.connect(g.project["pid"]) as conn:
        layout = layout_or_404(conn, layout_id)
        systems = db.systems(conn)
    return _generate_page(request, g, layout, systems)


@router.post("/p/{ref}/layouts/{layout_id}/generate")
async def generate_submit(request: Request, ref: str, layout_id: str):
    """The Generate form, handled in Python: the report is made, then the layout's page opens on its
    reports; a refused choice draws the form again with the message and what was typed."""
    g = guard(request, ref, "editor")                  # refuses a foreign Origin before anything is read
    form = await request.form()
    typed = {k: (form.get(k) or "") for k in ("system_id", "period_from", "period_to", "compare_to", "format")}
    typed["other_versions"] = form.get("other_versions") == "on"
    choice = {k: typed[k] or None for k in ("system_id", "period_from", "period_to", "compare_to")}
    choice["other_versions"] = typed["other_versions"]
    fmt = typed["format"] if typed["format"] in reports.FORMATS else "pdf"
    try:
        status, body = await run_in_threadpool(reports.generate, request, g.project, layout_id, g.caller, fmt,
                                               choice=choice)
    except ApiError as e:
        with request.app.state.projects.connect(g.project["pid"]) as conn:
            layout, systems = layout_or_404(conn, layout_id), db.systems(conn)
        problems = _problem_lines(e.details, layout, block_types(request))
        return _generate_page(request, g, layout, systems, status_code=e.status,
                              error="The report was not generated:" if problems else e.message, form=typed,
                              problems=problems)
    if status >= 400:
        with request.app.state.projects.connect(g.project["pid"]) as conn:
            layout, systems = layout_or_404(conn, layout_id), db.systems(conn)
        return _generate_page(request, g, layout, systems, status_code=status,
                              error=body["error"]["message"], form=typed)
    return RedirectResponse(f"{_root(request)}/p/{g.project['slug']}/layouts/{layout_id}#reports", status_code=303)


@router.get("/p/{ref}/templates")
def templates_page(request: Request, ref: str, new: str | None = None, edit: str | None = None):
    """The templates list, and one template editor beside it while it is used: `?new=1` opens it empty
    for a new template, `?edit=<id>` on that template (a card's Edit, and where Create and Import land).
    Without either, or with an id that is not one of the project's templates, there is no editor."""
    g = guard(request, ref, "viewer")
    if _is_pid(ref):
        return _by_slug(request, g.project, "/templates")
    with request.app.state.projects.connect(g.project["pid"]) as conn:
        rows = _templates(conn)
    font_list = fonts(request)
    labels = {f["id"]: f["label"] for f in font_list}
    editing = next((t for t in rows if t["id"] == edit), None) if g.access.may_write else None
    creating = g.access.may_write and editing is None and new is not None
    return _page("templates.html.j2", request, project=g.project, templates=rows, fonts=font_list, labels=labels,
                 editor=g.access.may_write, editing=editing, creating=creating, here="templates")
