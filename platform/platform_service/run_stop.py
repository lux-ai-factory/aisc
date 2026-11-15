"""When the platform stops a run whose calls keep failing (routes/facade.py, before each call).

Per run, from its trace (run_trace), counting questions: the calls actually sent to the system under test
(outcome answered or failed; a request a door refused for its own reason does not count), one question per
request, so a plugin that asks a question again after it failed (its own retry, the same input, history and
params) asks one question, whose outcome is that of its latest call. The run is stopped when its last
PLATFORM_RUN_STOP_IN_A_ROW questions all failed (default 3), or when at least PLATFORM_RUN_STOP_AFTER questions
were sent (default 20) and more than PLATFORM_RUN_STOP_RATE of them failed (default 0.05). IN_A_ROW 0 or RATE 0
turns that rule off; AFTER is only the rate rule's minimum count, so AFTER 0 lets it stop a run on its first
failed call. Once
stopped, a run stays stopped: its stopped calls are not sent, so its counts no longer change. A new run starts
from zero. Every plugin's runs are held to it; no plugin does anything for it.
"""
from __future__ import annotations

import os

from platform_service import projectdb

IN_A_ROW_DEFAULT, RATE_DEFAULT, AFTER_DEFAULT = 3, 0.05, 20


class RunStopped(Exception):
    """A call the platform did not send because the run was stopped; its text is the reason."""


def _number(name: str, default, cast):
    try:
        value = cast(os.environ.get(name) or default)
    except ValueError:
        return default
    return value if value >= 0 else default


def in_a_row() -> int:
    return _number("PLATFORM_RUN_STOP_IN_A_ROW", IN_A_ROW_DEFAULT, int)


def rate() -> float:
    return _number("PLATFORM_RUN_STOP_RATE", RATE_DEFAULT, float)


def after() -> int:
    return _number("PLATFORM_RUN_STOP_AFTER", AFTER_DEFAULT, int)


#: each question of the run once, as its latest sent call left it: the same request again is the same question
_QUESTIONS = ("WITH questions AS (SELECT DISTINCT ON (md5(request::text)) seq, outcome, error FROM trace.call"
              " WHERE run = %s AND outcome IN ('answered', 'failed') ORDER BY md5(request::text), seq DESC)")


def _code(error) -> str:
    """A failed call's short code (auth, timeout, ...), as its trace row keeps it."""
    if isinstance(error, dict) and error.get("code"):
        return error["code"]
    return "error"


def reason(pid, run_id: str) -> str | None:
    """Why the run's next call must not be sent, or None to send it."""
    row_limit, share, minimum = in_a_row(), rate(), after()
    if not row_limit and not share:
        return None
    with projectdb.connect(pid) as conn:
        rows = conn.execute(_QUESTIONS + " SELECT count(*) AS sent, count(*) FILTER (WHERE outcome = 'failed')"
                            " AS failed FROM questions", (run_id,)).fetchone()
        last = conn.execute(_QUESTIONS + " SELECT outcome, error FROM questions ORDER BY seq DESC LIMIT %s",
                            (run_id, max(row_limit, 1))).fetchall()
        sent, failed = rows["sent"], rows["failed"]
        if not failed:
            return None
        last_failed = next((r["error"] for r in last if r["outcome"] == "failed"), None)
        if not last_failed:
            found = conn.execute(_QUESTIONS + " SELECT error FROM questions WHERE outcome = 'failed'"
                                 " ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
            last_failed = found["error"] if found else None
    stopped = "the platform stopped this run: "
    if row_limit and len(last) >= row_limit and all(r["outcome"] == "failed" for r in last):
        return f"{stopped}{row_limit} questions in a row failed; the last: {_code(last_failed)}"
    if share and sent >= minimum and failed / sent > share:
        return (f"{stopped}{failed} of {sent} questions failed (more than {share:.0%}); "
                f"the last: {_code(last_failed)}")
    return None
