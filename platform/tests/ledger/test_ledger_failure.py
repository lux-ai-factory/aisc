"""F1-F3: no event is lost while a part is down (I6, spec 5.3, R5.2). The gateway half (platform down:
witnessed requests fail, others work) is the real-Caddy suite, scripts/tests/test_ledger_gateway.py."""
from __future__ import annotations



from tests.ledger.conftest import log_of, needs_db, MEMBER, entries, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db


def ratings(pid):
    return f"/control-objectives/p/{pid}/api/projects/a1/ratings"


def rated(request_id, n):
    return {"event_id": f"00000000-0000-4000-8000-{n:012d}", "request_id": request_id, "action": "risk.rated",
            "item_type": "risk", "item_id": f"r{n}"}


def test_an_immudb_outage_blocks_nothing_and_loses_nothing(project, witnessed, memory_ledger, mode):
    mode("enforce")
    memory_ledger.down = True
    ids = [witnessed(MEMBER, "POST", "control_objectives", ratings(project["pid"])) for _ in range(3)]
    for n, request_id in enumerate(ids, 1):
        emit(project["pid"], "control_objectives_rw", rated(request_id, n))
    assert relay_all(project["pid"]).pending >= 6
    memory_ledger.down = False
    relay_all(project["pid"])
    db = log_of(project["pid"])
    assert len([e for e in entries(memory_ledger, db) if e.action == "risk.rated"]) == 3
    assert len([e for e in entries(memory_ledger, db) if e.action == "request.witnessed"]) == 3


def test_an_internal_event_is_queued_when_immudb_is_down(client, project, witnessed, memory_ledger, mode,
                                                         monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_ENGINE_TOKEN", "engine-token-0123456789")
    memory_ledger.down = True
    request_id = witnessed(MEMBER, "POST", "engine", "/api/v1/evaluation/", project_header=project["pid"])
    r = client.post(f"/internal/projects/{project['pid']}/ledger/events",
                    json={"event_id": "00000000-0000-4000-8000-0000000000e1", "request_id": request_id,
                          "action": "engine.evaluation.run_requested", "item_type": "evaluation", "item_id": "ev1",
                          "run_id": "00000000-0000-4000-8000-0000000000f1"},
                    headers={"X-AISC-Service-Token": "engine-token-0123456789"})
    assert r.status_code == 202
    memory_ledger.down = False
    relay_all(project["pid"])
    assert [e.item_id for e in entries(memory_ledger, log_of(project["pid"]))
            if e.action == "engine.evaluation.run_requested"] == ["ev1"]


def test_in_enforce_an_app_refuses_a_write_with_no_request_id(client, as_user, project, mode):
    """Defence in depth (spec 5.3): a write that reached an app without passing Caddy changes nothing."""
    mode("enforce")
    r = client.put(f"/projects/{project['slug']}/evidence", json={"links": []}, headers=as_user(MEMBER))
    assert r.status_code == 401
