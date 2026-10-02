"""PF1-PF5, phase 3: provisioning seen from a project's life (I3, I6, R2.10; spec 6.1, 6.4, 7.3;
third review M1, M4). These need the witness (phase 2) and the relay (phase 3)."""
from __future__ import annotations

import uuid


from platform_service.ledger import provision, testing, verify
from tests.ledger.conftest import MEMBER, OWNER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db


def rating(p, witnessed, n):
    request_id = witnessed(MEMBER, "POST", "control_objectives",
                           f"/control-objectives/p/{p['pid']}/api/projects/a1/ratings")
    emit(p["pid"], "control_objectives_rw", {"event_id": str(uuid.uuid4()),
                                             "request_id": request_id, "action": "risk.rated",
                                             "item_type": "risk", "item_id": f"r{n}"})


def test_a_new_project_takes_a_database_from_the_pool(memory_ledger, make_project):
    before = provision.pool_level()
    p = make_project(OWNER)
    assert log_of(p["pid"]) in memory_ledger.databases()
    assert provision.pool_level() == before - 1


def test_with_the_pool_empty_a_projects_events_wait(own_store, make_project, witnessed, mode):
    store = own_store(0)
    p = make_project(OWNER, editors=(MEMBER,))
    assert provision.database_for(p["pid"]) is None
    mode("enforce")
    rating(p, witnessed, 1)
    assert relay_all(p["pid"]).pending >= 1
    testing.fill_pool(store, n=1)
    assert provision.assign_pending(p["pid"]) is True
    relay_all(p["pid"])
    assert [e.item_id for e in entries(store, log_of(p["pid"])) if e.action == "risk.rated"] == ["r1"]


def test_the_assignment_outlives_the_project(memory_ledger, make_project, through_gateway):
    p = make_project(OWNER)
    db = log_of(p["pid"])
    assert through_gateway(OWNER, "DELETE", f"/projects/{p['slug']}").status_code in (200, 204)
    relay_all(p["pid"])
    assert provision.database_for(p["pid"]) == db


def test_a_database_gone_from_immudb_holds_that_project_only(memory_ledger, make_project, witnessed, mode):
    """The relay treats it as pending plus an alarm, and never aborts the batch for the others (M4)."""
    lost, fine = make_project(OWNER, editors=(MEMBER,)), make_project(OWNER, editors=(MEMBER,))
    mode("enforce")
    rating(lost, witnessed, 1)
    rating(fine, witnessed, 2)
    memory_ledger.drop(log_of(lost["pid"]))                       # what the immudb superuser could do
    relay_all()                                                     # every project, as the daemon runs
    assert relay_all(lost["pid"]).pending >= 1                      # its own row waits (fourth review 1)
    assert [e.item_id for e in entries(memory_ledger, log_of(fine["pid"])) if e.action == "risk.rated"] == ["r2"]
    assert verify.verify(lost["pid"]).missing_database is True
    assert verify.verify(fine["pid"]).missing_database is False


def test_the_relay_skips_rows_whose_database_another_store_holds(memory_ledger, own_store, make_project, witnessed,
                                                                 mode):
    """A test suite's leftovers, or a server move: pending and an alarm, never an exception (M4)."""
    p = make_project(OWNER, editors=(MEMBER,))
    mode("enforce")
    rating(p, witnessed, 1)
    own_store(2)                                                    # another server is now current
    relay_all()                                                     # never raises
    assert relay_all(p["pid"]).pending >= 1 and verify.verify(p["pid"]).missing_database is True
