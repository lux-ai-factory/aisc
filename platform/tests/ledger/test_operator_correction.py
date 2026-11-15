"""An operator's correction of live data is declared in the project's ledger.

When an operator changes data by hand (a run's status, a removed card version, runs moved between
projects), an admin declares it: POST /api/ledger/corrections names the project, when, what, why, a backup
reference and the items touched. The platform writes operator.correction.declared into that project's log,
with the admin who declared it as the actor.
"""
from __future__ import annotations

import pytest

from tests.ledger.conftest import ADMIN, ADMIN_ROLES, MEMBER, entries, log_of, needs_db, person, relay_all

pytestmark = needs_db


@pytest.fixture
def call(through_gateway, mode):
    mode("enforce")
    return through_gateway


def declaration(project, **over):
    return {"project": project["slug"], "performed_at": "2026-11-05T18:26:00+00:00",
            "what": "status of run 12 set to Failed", "why": "the worker died and left it Running",
            "backup_ref": "dump before the change", "items": ["evaluation:12"], **over}


def test_an_admin_declares_a_correction_into_the_projects_log(call, project, memory_ledger):
    r = call(ADMIN, "POST", "/ledger/corrections", roles=ADMIN_ROLES, json=declaration(project))
    assert r.status_code == 201, f"declaring a correction answered {r.status_code}"
    event_id = r.json()["event_id"]
    relay_all(project["pid"])
    log = entries(memory_ledger, log_of(project["pid"]))
    assert [e.details["reason"] for e in log if e.action == "ledger.rejected"] == []
    [declared] = [e for e in log if e.action == "operator.correction.declared"]
    assert declared.event_id == event_id
    assert person(project["pid"], declared.actor_ref)[0] == ADMIN
    assert declared.details["why"] == "the worker died and left it Running"


def test_a_member_who_is_not_admin_gets_403(call, project):
    r = call(MEMBER, "POST", "/ledger/corrections", json=declaration(project))
    assert r.status_code == 403, f"a project member declaring a correction answered {r.status_code}"


@pytest.mark.parametrize("over", [{"why": ""}, {"surprise": "x"}, {"items": ["i"] * 51}])
def test_unknown_fields_empty_why_and_too_many_items_are_422(call, project, over):
    r = call(ADMIN, "POST", "/ledger/corrections", roles=ADMIN_ROLES, json=declaration(project, **over))
    assert r.status_code == 422, f"a malformed declaration answered {r.status_code}"


def test_a_secret_in_what_is_refused(call, project):
    r = call(ADMIN, "POST", "/ledger/corrections", roles=ADMIN_ROLES,
             json=declaration(project, what="rotated key sk-abcdefghijklmnopqrstuvwx0123"))
    assert r.status_code == 422, f"a declaration holding a key answered {r.status_code}"
