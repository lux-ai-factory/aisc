"""B1: the browser beacon (page left, unsaved changes, dialogs). The beacon request is witnessed, so
who sent it is certain; what it says comes from the browser and is marked so."""
from __future__ import annotations

import pytest

from platform_service.ledger.naming import database_name
from tests.conftest import needs_database
from tests.ledger.conftest import MEMBER, entries

pytestmark = needs_database


@pytest.fixture
def beacon(client, as_user, project, witnessed, mode):
    mode("enforce")

    def send(body, *, with_request=True):
        path = f"/projects/{project['slug']}/ledger/beacon"
        headers = as_user(MEMBER)
        if with_request:
            headers["X-AISC-Request-Id"] = witnessed(MEMBER, "POST", "/api" + path)
        return client.post(path, json=body, headers=headers)
    return send


def test_a_page_left_with_unsaved_changes_is_recorded_as_browser_reported(beacon, project, memory_ledger):
    r = beacon({"action": "page.left", "details": {"page": "/p/x/evidence", "unsaved_changes": True}})
    assert r.status_code == 204, r.text
    [e] = [x for x in entries(memory_ledger, database_name(project["pid"])) if x.action == "page.left"]
    assert (e.actor_sub, e.reported_by) == (MEMBER, "browser")
    assert e.details["unsaved_changes"] is True


def test_only_beacon_actions_are_accepted(beacon):
    assert beacon({"action": "risk.rated", "details": {}}).status_code == 422


def test_a_beacon_is_small(beacon):
    assert beacon({"action": "page.left", "details": {"page": "x" * 3000}}).status_code == 413


def test_a_beacon_without_a_witnessed_request_is_refused(beacon):
    assert beacon({"action": "page.left", "details": {}}, with_request=False).status_code == 401
