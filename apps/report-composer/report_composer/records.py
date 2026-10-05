"""A project's layouts and templates by id, or the API error a missing one is answered with.

Every helper takes a connection to the project's own database: an id of another project is not in it,
so it is 404 (or 422 when named in a body).
"""
from __future__ import annotations

from . import db
from .errors import ApiError

NO_LAYOUT = "No such layout."
NO_TEMPLATE = "No such template."


def layout_or_404(conn, layout_id, for_update=False) -> dict:
    layout = db.get_layout(conn, layout_id, for_update=for_update)
    if layout is None:
        raise ApiError(404, "not_found", NO_LAYOUT)
    return layout


def template_or_404(conn, template_id, with_logo=False) -> dict:
    t = db.get_template(conn, template_id, with_logo=with_logo)
    if t is None:
        raise ApiError(404, "not_found", NO_TEMPLATE)
    return t


def template_of(conn, layout) -> dict | None:
    """The layout's template with its logo, or None (never chosen, or deleted since)."""
    if not layout.get("template_id"):
        return None
    return db.get_template(conn, layout["template_id"], with_logo=True)


def chosen_template(conn, template_id) -> str | None:
    """One of the project's templates, or None: the platform's default look."""
    if not template_id:
        return None
    t = db.get_template(conn, template_id)
    if t is None:
        raise ApiError(422, "template_not_in_project", "The template is not one of this project's.",
                       [{"pointer": "/template_id", "message": "is not one of this project's templates"}])
    return t["id"]
