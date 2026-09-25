"""Calls to the renderer on behalf of a request, its failures answered as API errors."""
from __future__ import annotations

import threading
import time

from fastapi import Request

from .errors import ApiError
from .renderer_client import RendererError, RendererRejected, RendererTimeout, RendererUnavailable


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


NO_COVERAGE_CHOICES = {"objectives": [], "tests": [], "checklists": []}


def coverage_choices_for(request: Request, project_pid: str, system_pid: str) -> dict:
    """What the coverage map may name for the version: objectives, tests, checklists."""
    renderer = request.app.state.renderer
    if not hasattr(renderer, "coverage_choices"):
        return {k: [] for k in NO_COVERAGE_CHOICES}
    got = renderer_call(renderer.coverage_choices, project_pid, system_pid) or {}
    return {k: list(got.get(k) or []) for k in NO_COVERAGE_CHOICES}


class BlockTypesCache:
    """The renderer's block types for the outline route, kept for `ttl` seconds. They change only when the
    renderer restarts. A failure gives [] (the outline then uses the fixed prose list, DV12-6) and is kept for
    the shorter `failure_ttl`, so a hung renderer is not asked again on every edit (finding 1 of
    14-verify-part2.md)."""

    def __init__(self, fetch, *, ttl=60.0, failure_ttl=10.0, now=time.monotonic):
        self.fetch, self.ttl, self.failure_ttl, self.now = fetch, ttl, failure_ttl, now
        self._value, self._until = None, None
        self._lock = threading.Lock()

    def get(self) -> list:
        with self._lock:
            if self._until is not None and self.now() < self._until:
                return self._value
        try:
            value, keep = self.fetch(), self.ttl
        except RendererError:
            value, keep = [], self.failure_ttl
        with self._lock:
            self._value, self._until = value, self.now() + keep
        return value


def outline_block_types(request: Request) -> list:
    """The block types for the outline route: cached per app, fetched with the client's short timeout."""
    state = request.app.state
    cache = getattr(state, "outline_block_types", None)
    if cache is None:
        renderer = state.renderer
        cache = state.outline_block_types = BlockTypesCache(getattr(renderer, "block_types_quick",
                                                                    renderer.block_types))
    return cache.get()
