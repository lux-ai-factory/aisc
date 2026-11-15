"""A checklist installed with the catalogue's Install button is accepted by the ledger.

The catalogue's dialog posts the install to the controls app. The witness can bind a controls request to its
project only from the path (/controls/p/<slug>/...), so the install is served under the project's path, and
the control.installed event controls writes for it is accepted as that project's.
"""
from __future__ import annotations

import uuid

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db


def test_a_catalogue_install_of_a_checklist_is_accepted(project, memory_ledger, witnessed, mode):
    mode("enforce")
    request_id = witnessed(MEMBER, "POST", "controls", f"/controls/p/{project['slug']}/api/install")
    emit(project["pid"], "controls_rw", {"event_id": str(uuid.uuid4()), "request_id": request_id,
                                         "action": "control.installed", "item_type": "checklist",
                                         "item_id": "accuracy-checklist",
                                         "details": {"package": "accuracy-checklist", "questions": 12}})
    relay_all(project["pid"])
    log = entries(memory_ledger, log_of(project["pid"]))
    assert [e.details["reason"] for e in log if e.action == "ledger.rejected"] == [], (
        "the catalogue's checklist install was refused by the ledger")
    assert [e.request_id for e in log if e.action == "control.installed"] == [request_id]
