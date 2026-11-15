"""Opening the card right after saving it is recorded, not refused.

Saving the AI card is a server action on /qualification/p/<slug>/system/edit that ends in a redirect to the
card's page, which Next renders inside the same POST. The page records qualification.opened citing that
POST's request id; the ledger accepts it as caused by the save, alongside the card's own event.
"""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
CARD = "cmcard0000000000000000077"


@pytest.mark.parametrize("action, details", [
    ("qualification.created", {"questionnaire_version": "v1", "risks": 0, "components": 1}),
    ("qualification.amended", {"revision": 2, "amends": "cmcard0000000000000000076", "reason": "provider name",
                               "requested_by": "the provider", "risks": 0, "components": 1}),
])
def test_the_card_opened_by_the_saves_redirect_is_accepted(project, memory_ledger, witnessed, mode, action, details):
    mode("enforce")
    save = witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/system/edit",
                     next_action="60b7a2efb1d3fb3ac1825abb501965ed2094977777")
    emit(project["pid"], "qualification_rw", {"event_id": str(uuid.uuid4()), "request_id": save, "action": action,
                                              "item_type": "qualification", "item_id": CARD, "details": details,
                                              "content": {"systemName": "MCAS"}})
    emit(project["pid"], "qualification_rw", {"event_id": str(uuid.uuid4()), "request_id": save,
                                              "action": "qualification.opened", "item_type": "qualification",
                                              "item_id": CARD, "details": {"version": "1", "read_only": False}})
    relay_all(project["pid"])
    log = entries(memory_ledger, log_of(project["pid"]))
    assert [e.details["reason"] for e in log if e.action == "ledger.rejected"] == [], (
        "opening the card after its save was refused")
    assert [e.request_id for e in log if e.action == "qualification.opened"] == [save]
