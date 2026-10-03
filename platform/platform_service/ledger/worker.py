"""The relay worker (spec 7.2; phase 4 review M4): what moves witness records and events into the logs.

One per platform process, started with the app. Each pass relays every log (the per-log advisory lock
keeps several processes safe together, as the phase 3 drill shows) and, once a day, deletes page views
older than PAGE_VIEW_RETENTION (D10). Nothing runs while LEDGER_MODE is off; turning it on needs no
restart. A failing pass is logged and the next one runs: the worker never dies of one error.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from platform_service.ledger import settings

logger = logging.getLogger(__name__)
_thread: threading.Thread | None = None
_start_lock = threading.Lock()


@dataclass
class State:
    last_expiry: float | None = None                                  # monotonic time of the last expiry


def one_pass(state: State | None = None):
    """One relay pass over every log, plus the daily expiry when due. None while the ledger is off."""
    from platform_service.ledger import pageviews, relay, witness

    if witness.mode() == "off":
        return None
    stats = relay.relay_once()
    if state is not None:
        now = time.monotonic()
        if state.last_expiry is None or now - state.last_expiry >= settings.EXPIRE_EVERY.total_seconds():
            removed = pageviews.expire(settings.PAGE_VIEW_RETENTION)
            state.last_expiry = now
            if removed:
                logger.info("ledger: %d page views past retention deleted", removed)
    return stats


def _loop(stop: threading.Event) -> None:
    state = State()
    while not stop.is_set():
        try:
            one_pass(state)
        except Exception:                                             # pragma: no cover - logged, then the next pass
            logger.exception("ledger: a relay pass failed")
        stop.wait(settings.RELAY_EVERY.total_seconds())


def start() -> None:
    """Start this process's worker once (the app's startup hook)."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, args=(threading.Event(),), name="ledger-relay", daemon=True)
        _thread.start()
