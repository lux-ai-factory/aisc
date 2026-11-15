"""A run's events are judged by when they happened, and a late one is never taken and then dropped.

Short run: the engine queues its run_requested when the run starts and delivers it a little later; the
platform seals the test's call trace when the worker ends its pass, which for a short run can come before
that delivery. The run's start is when the engine queued it, so the seal (after the start) is accepted.

Late measures: measures that reach the ledger after their run's window are either accepted or refused at the
door with a status the engine keeps (409), never answered 202 and then refused by the relay, which the engine
reads as delivered.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all

pytestmark = needs_db
TOKEN = "engine-token-0123456789"
MEASURES = [{"evaluation_plugin": str(uuid.uuid4()), "name": "Accuracy", "score": 0.9, "uncertainty": 0.0,
             "unit": "N/A", "direction": "", "error": "N/A", "dimensions_sha256": None}]


@pytest.fixture(autouse=True)
def _enforce(mode, monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", TOKEN)


def post(client, project, event):
    return client.post(f"/internal/projects/{project['pid']}/ledger/events", json=event,
                       headers={"X-AISC-Service-Token": TOKEN})


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


def test_the_seal_of_a_short_run_is_accepted(client, project, memory_ledger, witnessed):
    from platform_service import db
    from platform_service.ledger import outbox

    run, test = str(uuid.uuid4()), str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    queued_at = datetime.now(timezone.utc)                        # the engine queues the start here
    with db.pool().connection() as conn, conn.transaction():      # the run ends: the platform seals its trace
        outbox.emit(conn, "run.trace.sealed", project_pid=project["pid"], item_type="evaluation_plugin",
                    item_id=test, details={"calls": 0, "digest": None}, request_id=request_id, run_id=run)
    time.sleep(3)                                                 # the engine's delivery comes after the seal
    r = post(client, project, {"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run,
                               "action": "engine.evaluation.run_requested", "item_type": "evaluation",
                               "item_id": run, "details": {"plugins": ["DemoPlugin"]},
                               "occurred_at": queued_at.isoformat()})
    assert r.status_code == 202, r.text
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == [], "the seal of a short run was refused"
    assert [e.action for e in entries(memory_ledger, log_of(project["pid"])) if e.run_id == run] == [
        "engine.evaluation.run_requested", "run.trace.sealed"]


def test_late_measures_are_recorded_or_refused_at_the_door(client, project, memory_ledger, witnessed, monkeypatch):
    from platform_service.ledger import settings

    monkeypatch.setattr(settings, "RUN_WINDOW", timedelta(seconds=1))
    run = str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    started = post(client, project, {"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run,
                                     "action": "engine.evaluation.run_requested", "item_type": "evaluation",
                                     "item_id": run, "details": {"plugins": ["DemoPlugin"]}})
    assert started.status_code == 202, started.text
    relay_all(project["pid"])
    time.sleep(2)                                                 # past the run's window
    late = post(client, project, {"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run,
                                  "action": "engine.measures.recorded", "item_type": "evaluation",
                                  "item_id": run, "details": {"count": 1, "part": 1, "parts": 1},
                                  "content": MEASURES})
    relay_all(project["pid"])
    recorded = [e for e in entries(memory_ledger, log_of(project["pid"])) if e.action == "engine.measures.recorded"]
    if late.status_code == 409:
        return                                                    # refused at the door: the engine keeps it
    assert late.status_code == 202 and recorded, (
        f"late measures answered {late.status_code} but the relay refused them: "
        f"{rejected(memory_ledger, project['pid'])}")


def test_a_seal_relayed_before_its_runs_start_arrives_waits_for_it(client, project, memory_ledger, witnessed):
    """The relay can pass between the platform's seal and the engine's delivery of the start: the seal waits."""
    from platform_service import db
    from platform_service.ledger import outbox

    run, test = str(uuid.uuid4()), str(uuid.uuid4())
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    queued_at = datetime.now(timezone.utc)
    with db.pool().connection() as conn, conn.transaction():
        outbox.emit(conn, "run.trace.sealed", project_pid=project["pid"], item_type="evaluation_plugin",
                    item_id=test, details={"calls": 0, "digest": None}, request_id=request_id, run_id=run)
    relay_all(project["pid"])                                     # the start is not there yet
    assert rejected(memory_ledger, project["pid"]) == []
    r = post(client, project, {"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run,
                               "action": "engine.evaluation.run_requested", "item_type": "evaluation",
                               "item_id": run, "details": {"plugins": ["DemoPlugin"]},
                               "occurred_at": queued_at.isoformat()})
    assert r.status_code == 202, r.text
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert [e.action for e in entries(memory_ledger, log_of(project["pid"])) if e.run_id == run] == [
        "engine.evaluation.run_requested", "run.trace.sealed"]


@pytest.mark.parametrize("occurred_at", ["yesterday", "2026-11-15T10:00:00", "2999-01-01T00:00:00+00:00"])
def test_a_time_that_is_not_a_past_moment_with_its_zone_is_422(client, project, witnessed, occurred_at):
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluations/task", project_header=project["pid"])
    run = str(uuid.uuid4())
    r = post(client, project, {"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run,
                               "action": "engine.evaluation.run_requested", "item_type": "evaluation",
                               "item_id": run, "details": {"plugins": ["DemoPlugin"]}, "occurred_at": occurred_at})
    assert r.status_code == 422, r.text
    assert "occurred_at" in r.json()["detail"]
