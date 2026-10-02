"""PV1-PV6: a project's ledger database (I3, I6, I9, T23; spec 6.1, 7.1; second review N1). The
operator's script pre-creates databases (the platform never holds the immudb superuser); a new project
takes one from the pool, and the assignment is kept for ever (D2). Pool rows name the immudb server
they live on, so a database of another server is never handed out. With the pool empty, the project
is still created and its events wait until a database is assigned."""
from __future__ import annotations

import threading

import pytest

from platform_service import ledger
from platform_service.ledger import provision, testing, verify
from platform_service.ledger.store import MemoryLedger
from tests.ledger.conftest import MEMBER, OWNER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db


@pytest.fixture
def own_store(_database_required):
    """A ledger with a pool of the size the test asks for."""
    made = []

    def run(n):
        store = MemoryLedger()
        testing.fill_pool(store, n=n)
        made.append(ledger.use(store))
        return store
    yield run
    for previous in reversed(made):
        ledger.use(previous)


def test_a_new_project_takes_a_database_from_the_pool(memory_ledger, make_project):
    before = provision.pool_level()
    p = make_project(OWNER)
    assert log_of(p["pid"]) in memory_ledger.databases()
    assert provision.pool_level() == before - 1


def test_two_projects_never_share_a_database(make_project):
    assert log_of(make_project(OWNER)["pid"]) != log_of(make_project(OWNER)["pid"])


def test_projects_made_at_once_never_share_a_database(make_project):
    made, errors = [], []

    def run():
        try:
            made.append(make_project(OWNER))
        except Exception as exc:                                     # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len({log_of(p["pid"]) for p in made}) == 4


def test_another_servers_pool_is_never_used(own_store, make_project):
    first = own_store(3)
    second = own_store(0)                                           # this server has no free database
    p = make_project(OWNER)
    assert provision.database_for(p["pid"]) is None                 # not one of `first`'s
    assert first.databases() and not second.databases() - {"ledgerplatform"}


def test_with_the_pool_empty_the_project_is_made_and_its_events_wait(own_store, make_project, witnessed, mode):
    store = own_store(0)
    p = make_project(OWNER, editors=(MEMBER,))
    assert provision.database_for(p["pid"]) is None
    mode("enforce")
    request_id = witnessed(MEMBER, "POST", "control_objectives",
                           f"/control-objectives/p/{p['pid']}/api/projects/a1/ratings")
    emit(p["pid"], "control_objectives_rw", {"event_id": "00000000-0000-4000-8000-0000000000a1",
                                             "request_id": request_id, "action": "risk.rated",
                                             "item_type": "risk", "item_id": "r1"})
    assert relay_all(p["pid"]).pending >= 1
    testing.fill_pool(store, n=2)
    assert provision.assign_pending(p["pid"]) is True               # the operator refilled the pool
    relay_all(p["pid"])
    assert [e.item_id for e in entries(store, log_of(p["pid"])) if e.action == "risk.rated"] == ["r1"]


def test_the_assignment_outlives_the_project(memory_ledger, make_project, through_gateway):
    p = make_project(OWNER)
    db = log_of(p["pid"])
    assert through_gateway(OWNER, "DELETE", f"/projects/{p['slug']}").status_code in (200, 204)
    relay_all()
    assert provision.database_for(p["pid"]) == db


def test_a_database_gone_from_immudb_is_an_alarm(memory_ledger, make_project):
    p = make_project(OWNER)
    memory_ledger.drop(log_of(p["pid"]))                            # test hook: what the immudb superuser could do
    assert verify.verify(p["pid"]).missing_database is True
