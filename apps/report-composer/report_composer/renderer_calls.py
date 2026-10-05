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
    """The renderer's block types, asked now. The fresh answer also refreshes the outline's cache, so a
    renderer restarted with new block types is seen by the outline as soon as the palette, a save, a
    validation, a preview or a generation has asked for them."""
    value = renderer_call(request.app.state.renderer.block_types)
    _outline_cache(request.app.state).put(value)
    return value


def fonts(request: Request) -> list:
    return renderer_call(request.app.state.renderer.fonts)


def choices_for(request: Request, project_pid: str, system_pid: str):
    renderer = request.app.state.renderer
    return lambda block_type: renderer_call(renderer.choices, project_pid, system_pid, block_type)


class BlockTypesCache:
    """The renderer's block types for the outline route, kept for `ttl` seconds. They change only when the
    renderer restarts, and `put` stores any fresher answer. A failure gives [] (the outline then uses its fixed
    list of prose block types) and is kept for the shorter `failure_ttl`, so a hung renderer is not asked again
    on every edit.

    Single flight: only one fetch runs at a time. While it runs, the other
    callers take the older list at once if there is one; otherwise they wait for the fetch, at most `wait`
    seconds, and then use [] if it has not ended."""

    def __init__(self, fetch, *, ttl=60.0, failure_ttl=10.0, wait=3.0, now=time.monotonic):
        self.fetch, self.ttl, self.failure_ttl, self.wait, self.now = fetch, ttl, failure_ttl, wait, now
        self._value, self._until = None, None
        self._flight = None          # an Event while a fetch runs
        self._puts = 0               # counts puts, so a fetch never overwrites a fresher put
        self._lock = threading.Lock()

    def put(self, value) -> None:
        with self._lock:
            self._value, self._until = value, self.now() + self.ttl
            self._puts += 1

    def get(self) -> list:
        with self._lock:
            if self._until is not None and self.now() < self._until:
                return self._value
            flight, older = self._flight, self._value
            if flight is None:
                flight = self._flight = threading.Event()
                puts = self._puts
            elif older is not None:
                return older
            else:
                puts = None
        if puts is None:                       # another caller is fetching: wait for it
            ended = flight.wait(self.wait)
            with self._lock:
                return self._value if ended and self._value is not None else []
        value, keep = [], self.failure_ttl
        try:
            value, keep = self.fetch(), self.ttl
        except RendererError:
            pass
        finally:
            with self._lock:
                if self._puts == puts:
                    self._value, self._until = value, self.now() + keep
                else:
                    value = self._value
                self._flight = None
            flight.set()
        return value


def _outline_cache(state) -> BlockTypesCache:
    cache = getattr(state, "outline_block_types", None)
    if cache is None:
        renderer = state.renderer
        cache = state.outline_block_types = BlockTypesCache(getattr(renderer, "block_types_quick",
                                                                    renderer.block_types))
    return cache


def outline_block_types(request: Request) -> list:
    """The block types for the outline route: cached per app, fetched within the client's short deadline."""
    return _outline_cache(request.app.state).get()
