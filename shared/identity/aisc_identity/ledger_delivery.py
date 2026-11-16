"""One delivery loop for a ledger outbox, and one way to post an event to the platform, for every Python sender.

The engine (aisc_backend/ledger.py) and the results dashboard (aisc_ext/ledger.py) call it with their own outbox
queries and marks; the qualification agents, which cannot import aisc_identity, carry a byte-identical copy
(services/agents/fill/vendor/ledger_delivery.py) that a root test keeps equal. TypeScript has its own one module,
shared/ledger-ts.

`deliver` sends the pending events oldest first. A 2xx marks an event sent. A status in REFUSALS is the platform
refusing the event itself for good: it is marked refused, never sent again, and the next one is sent. Any other
failure stops the pass, so the outbox's order is kept for the next one; a sender that keeps each project's events
in order on its own (the dashboard) may `hold` back the project of an event the platform answered and go on with
the others.

Standard library only.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Iterable

#: The platform's statuses that refuse an event for good. 404 counts only as the platform's own "no project"
#: (a project deleted after its event was queued); a sender returns any other 404, a wrong address, as no answer.
REFUSALS = (404, 409, 413, 422)
#: The platform's internal ledger route of one project.
EVENTS_PATH = "/internal/projects/{pid}/ledger/events"
SERVICE_TOKEN_HEADER = "X-AISC-Service-Token"


def deliver(pending: Callable[[int], Iterable[Any]], mark_sent: Callable[[Any], None],
            mark_refused: Callable[[Any, int, str], None], send: Callable[[Any], tuple[int | None, str]],
            limit: int = 100, *, hold: Callable[[Any, int], None] | None = None,
            stopped: Callable[[Any, int | None], None] | None = None) -> tuple[int, int]:
    """One pass over `pending(limit)` (read as it goes, so `hold` may change what comes next); (sent, refused).

    `send(row)` is (the platform's status or None when it could not be asked, its answer's text). A 2xx calls
    `mark_sent(row)`, a status in REFUSALS `mark_refused(row, status, text)`. Anything else ends the pass, after
    `stopped(row, status)`, unless `hold` is given and the platform answered: then `hold(row, status)` and the
    pass goes on."""
    sent = refused = 0
    for row in pending(limit):
        status, text = send(row)
        if status is not None and 200 <= status < 300:
            mark_sent(row)
            sent += 1
            continue
        if status in REFUSALS:
            mark_refused(row, status, text)
            refused += 1
            continue
        if hold is not None and status is not None:
            hold(row, status)
            continue
        if stopped is not None:
            stopped(row, status)
        break
    return sent, refused


def no_project(text: str | bytes | None) -> bool:
    """Whether a 404's body is the platform's own "no project" answer, not a wrong address's."""
    try:
        detail = json.loads(text or b"{}").get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, str) and detail.startswith("no project ")


def _post(url: str, json_body: Any, headers: dict, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(json_body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def http_sender(url: str, token: str, *, timeout: float = 5.0, retries: tuple[float, ...] = (0.5, 1.0, 2.0),
                post: Callable[..., tuple[int, str]] | None = None) -> Callable[[Any], tuple[int | None, str]]:
    """A `send` that posts an event to `url` with the service token and returns (status, text).

    `post(url, json, headers, timeout)` is (status, text) and raises an OSError (ConnectionError, a refused or
    lost connection) when nothing answered: the event is posted again after each of `retries` seconds, with the
    same event id, and after the last one the answer is (None, the error's name). An answer is never posted
    again, whatever its status. Any other error is the caller's."""
    post = post or _post
    headers = {"Content-Type": "application/json", SERVICE_TOKEN_HEADER: token}

    def send(event: Any) -> tuple[int | None, str]:
        for wait in (*retries, None):
            try:
                return post(url, event, headers, timeout)
            except OSError as exc:
                if wait is None:
                    return None, type(exc).__name__
                time.sleep(wait)
        return None, ""

    return send
