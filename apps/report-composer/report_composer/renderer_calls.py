"""Calls to the renderer on behalf of a request, its failures answered as API errors."""
from __future__ import annotations

from fastapi import Request

from .errors import ApiError
from .renderer_client import RendererRejected, RendererTimeout, RendererUnavailable


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


def fonts(request: Request) -> list:
    return renderer_call(request.app.state.renderer.fonts)


def choices_for(request: Request, project_pid: str, system_pid: str):
    renderer = request.app.state.renderer
    return lambda block_type: renderer_call(renderer.choices, project_pid, system_pid, block_type)
