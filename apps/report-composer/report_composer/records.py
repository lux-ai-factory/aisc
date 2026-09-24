"""A project's layouts and templates by id, or the API error a missing one is answered with."""
from __future__ import annotations

from . import db
from .errors import ApiError

NO_LAYOUT = "No such layout."
NO_TEMPLATE = "No such template."


def layout_or_404(conn, pid, layout_id, for_update=False) -> dict:
    layout = db.get_layout(conn, pid, layout_id, for_update=for_update)
    if layout is None:
        raise ApiError(404, "not_found", NO_LAYOUT)
    return layout


def template_or_404(conn, pid, template_id, with_logo=False) -> dict:
    t = db.get_template(conn, pid, template_id, with_logo=with_logo)
    if t is None:
        raise ApiError(404, "not_found", NO_TEMPLATE)
    return t


def template_of(conn, project_pid, layout) -> dict | None:
    """The layout's template with its logo, or None (never chosen, or deleted since)."""
    if not layout.get("template_id"):
        return None
    return db.get_template(conn, project_pid, layout["template_id"], with_logo=True)


def chosen_template(conn, project_pid, template_id) -> str:
    """A layout is saved only with one of its project's templates."""
    if not template_id:
        raise ApiError(422, "template_required", "Choose one of this project's templates before saving.",
                       [{"pointer": "/template_id", "message": "is required"}])
    t = db.get_template(conn, project_pid, template_id)
    if t is None:
        raise ApiError(422, "template_not_in_project", "The template is not one of this project's.",
                       [{"pointer": "/template_id", "message": "is not one of this project's templates"}])
    return t["id"]
