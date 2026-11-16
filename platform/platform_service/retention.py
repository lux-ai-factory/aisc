"""How long a project keeps its runs, and the daily sweep that deletes older ones.

Off unless an owner sets a period (PUT /projects/{slug}/retention, 1 to 3650 days, core.project_retention).
For each project with a period, the sweep asks the project's engine which runs ended before it
(`engine.runs_finished_before`) and deletes each as an owner's deletion does (run_purge.purge_run: a tombstone
and a ledger event, by "retention", with the period as the reason). It then tries again to remove the stored
files earlier deletions left behind.

One sweep a day per stack: every platform process starts the thread, and a session-level advisory lock on the
platform database lets one of them sweep at a time.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from platform_service import db, projectdb, run_purge

logger = logging.getLogger(__name__)

#: the advisory lock the sweeping process holds while it sweeps
_LOCK = 0x7265_7465_6E74   # "retent"
#: how long after start the first sweep runs, then the time between sweeps
FIRST_SWEEP_AFTER = timedelta(minutes=10)
EVERY = timedelta(days=1)

_start_lock = threading.Lock()
_thread: threading.Thread | None = None


def _runs_ended_before(pid, moment: datetime) -> list[str]:
    with projectdb.connect(pid, row_factory=None) as conn:
        if conn.execute("SELECT to_regprocedure('engine.runs_finished_before(timestamptz)')").fetchone()[0] is None:
            return []                                           # the engine has not migrated this project yet
        return [str(r[0]) for r in conn.execute("SELECT engine.runs_finished_before(%s)", (moment,))]


def sweep(now: datetime | None = None) -> dict[str, int]:
    """Delete every run older than its project's period; {project pid: runs deleted}, only projects with some."""
    now = now or datetime.now(timezone.utc)
    swept: dict[str, int] = {}
    for row in db.retention_periods():
        pid, days = str(row["pid"]), int(row["days"])
        try:
            runs = _runs_ended_before(pid, now - timedelta(days=days))
        except Exception:                                       # noqa: BLE001  (one project never stops the rest)
            logger.exception("retention: project %s could not be read", pid)
            continue
        for evaluation in runs:
            try:
                run_purge.purge_run(pid, evaluation, "retention", f"retention: {days} days")
            except Exception:                                   # noqa: BLE001
                logger.exception("retention: run %s of project %s could not be deleted", evaluation, pid)
                continue
            swept[pid] = swept.get(pid, 0) + 1
    try:
        run_purge.retry_leftovers()
    except Exception:                                           # noqa: BLE001
        logger.exception("retention: the files left behind could not be tried again")
    return swept


def _sweep_once_under_lock() -> None:
    import psycopg

    with psycopg.connect(db.dsn(), autocommit=True) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK,)).fetchone()[0]:
            return                                              # another process sweeps
        try:
            swept = sweep()
            if swept:
                logger.info("retention: deleted %s", swept)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK,))


def _loop(stop: threading.Event) -> None:
    wait = FIRST_SWEEP_AFTER
    while not stop.wait(wait.total_seconds()):
        try:
            _sweep_once_under_lock()
        except Exception:                                       # noqa: BLE001
            logger.exception("retention: the sweep failed; it runs again tomorrow")
        wait = EVERY


def start() -> None:
    """Start this process's sweep thread once (the app's startup hook)."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, args=(threading.Event(),), name="retention-sweep", daemon=True)
        _thread.start()
