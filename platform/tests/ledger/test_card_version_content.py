"""A card version's ledger event freezes what the version said, and its withdrawal is recorded too.

card_version.created carries the version's content (number, name, version, provider, description), so the
ledger alone says what "Version 2" was even if the row changes later. Withdrawing a version made for a card
that was not saved (POST .../system-versions/abandon) writes card_version.abandoned, which the relay accepts
on the same server action as the creation.
"""
from __future__ import annotations

import uuid

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import as_superuser

pytestmark = needs_db


def _submit(witnessed, project, next_action):
    return witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/system/edit",
                     next_action=next_action)


def test_card_version_created_freezes_its_content(project, client, as_user, witnessed, memory_ledger, mode):
    mode("enforce")
    submit = _submit(witnessed, project, "60b7a2efb1d3fb3ac1825abb501965ed2094900001")
    made = client.post(f"/projects/{project['slug']}/system-versions",
                       json={"name": "N", "provider": "P", "description": "D"},
                       headers={**as_user(MEMBER), "X-AISC-Request-Id": submit})
    assert made.status_code == 201, made.text
    [(content,)] = as_superuser(project["pid"], "SELECT content FROM ledger.outbox WHERE action = 'card_version.created'")
    assert content == {"number": 1, "name": "N", "version": None, "provider": "P", "description": "D"}


def test_abandon_after_create_on_one_action_is_accepted_by_the_relay(project, client, as_user, witnessed,
                                                                     memory_ledger, mode):
    mode("enforce")
    action_id = "60b7a2efb1d3fb3ac1825abb501965ed2094900002"
    attempt = str(uuid.uuid4())
    submit = _submit(witnessed, project, action_id)
    made = client.post(f"/projects/{project['slug']}/system-versions", json={"name": "N", "attempt": attempt},
                       headers={**as_user(MEMBER), "X-AISC-Request-Id": submit})
    assert made.status_code == 201, made.text
    withdraw = _submit(witnessed, project, action_id)
    answer = client.post(f"/projects/{project['slug']}/system-versions/abandon",
                         json={"attempt": attempt, "reason": "card not saved"},
                         headers={**as_user(MEMBER), "X-AISC-Request-Id": withdraw})
    assert answer.status_code == 200, f"withdrawing the version answered {answer.status_code}"
    relay_all(project["pid"])
    log = entries(memory_ledger, log_of(project["pid"]))
    assert [e.details["reason"] for e in log if e.action == "ledger.rejected"] == []
    [gone] = [e for e in log if e.action == "card_version.abandoned"]
    assert gone.details == {"number": 1, "reason": "card not saved"}
