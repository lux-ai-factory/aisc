"""The relay worker: the platform runs one per process, each pass relays every log (the per-log lock makes processes safe
together) and, once a day, expires page views past PAGE_VIEW_RETENTION."""
from __future__ import annotations

import json
from datetime import timedelta

import psycopg

from platform_service.ledger import pageviews, worker
from tests.conftest import DSN
from tests.ledger.conftest import MEMBER, entries, log_of, needs_db

pytestmark = needs_db


def test_a_pass_relays_what_is_pending(project, witnessed, memory_ledger, mode):
    mode("record")
    request_id = witnessed(MEMBER, "POST", "control_objectives",
                           f"/control-objectives/p/{project['pid']}/api/projects/a1/ratings")
    worker.one_pass()
    assert request_id in {e.request_id for e in entries(memory_ledger, log_of(project["pid"]))}


def test_with_the_ledger_off_a_pass_does_nothing(project, mode, monkeypatch):
    mode("off")
    called = []
    monkeypatch.setattr("platform_service.ledger.relay.relay_once", lambda *a: called.append(a))
    assert worker.one_pass() is None and called == []


def test_page_views_past_retention_are_expired_once_a_day(project, memory_ledger, mode, settings):
    mode("record")
    pageviews.record(project["pid"], "actor:" + "1" * 32, "page.opened", {"page": "/x"}, None)
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE ledger.page_view SET at = at - %s WHERE project_pid = %s",
                     (settings.PAGE_VIEW_RETENTION + timedelta(days=1), project["pid"]))
    pageviews.record(project["pid"], "actor:" + "1" * 32, "page.opened", {"page": "/y"}, None)
    state = worker.State()
    worker.one_pass(state)
    assert [v.details for v in pageviews.recent(project["pid"])] == [{"page": "/y"}]
    pageviews.record(project["pid"], "actor:" + "1" * 32, "page.opened", {"page": "/z"}, None)
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE ledger.page_view SET at = at - %s WHERE details = %s",
                     (settings.PAGE_VIEW_RETENTION + timedelta(days=1), json.dumps({"page": "/z"})))
    worker.one_pass(state)                                            # the same day: not again
    assert len(pageviews.recent(project["pid"])) == 2


def test_the_platform_starts_the_worker():
    """Registered on the app's startup; TestClient without `with` never starts it, so tests stay quiet."""
    from platform_service.app import app

    assert worker.start in app.router.on_startup


def test_starting_twice_runs_one_worker(monkeypatch):
    runs = []
    monkeypatch.setattr(worker, "_loop", lambda stop: (runs.append(stop), stop.wait(1)))   # runs, as the real one
    monkeypatch.setattr(worker, "_thread", None)
    worker.start()
    worker.start()
    worker._thread.join(timeout=2)
    assert len(runs) == 1
