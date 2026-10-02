"""B1-B2: the browser beacon (spec 3.5, I10). Page views and browser-only moments are best effort: the
beacon request is witnessed, so who sent it is certain; what it says comes from the browser and is
marked so. They are kept in Postgres with a retention limit, never in immudb. Each site has its own
beacon route, and the body is text/plain so no CORS preflight is needed (R3.6)."""
from __future__ import annotations

import json

import pytest

from platform_service.ledger import pageviews

from tests.ledger.conftest import log_of, needs_db, MEMBER, OWNER, entries, person

pytestmark = needs_db


@pytest.fixture
def beacon(client, as_user, project, witnessed, mode):
    mode("enforce")

    def send(body, *, subject=MEMBER, with_request=True, presenter=None):
        headers = {**as_user(presenter or subject), "Content-Type": "text/plain;charset=UTF-8"}
        if with_request:
            headers["X-AISC-Request-Id"] = witnessed(subject, "POST", "platform", "/api/ledger/beacon")
        return client.post("/ledger/beacon", content=json.dumps(body), headers=headers)
    return send


def page(project, **over):
    body = {"project": project["slug"], "action": "page.left",
            "details": {"page": f"/p/{project['slug']}/evidence", "unsaved_changes": True}}
    body.update(over)
    return body


def test_a_page_left_is_kept_as_browser_reported_outside_immudb(beacon, project, memory_ledger):
    assert beacon(page(project)).status_code == 204
    [v] = pageviews.recent(project["pid"])
    assert (v.action, v.reported_by, v.details["unsaved_changes"]) == ("page.left", "browser", True)
    assert person(project["pid"], v.actor_ref)[0] == MEMBER
    assert [e for e in entries(memory_ledger, log_of(project["pid"])) if e.action.startswith("page.")] == []


def test_page_views_expire(beacon, project, settings):
    beacon(page(project, action="page.opened"))
    pageviews.expire(older_than=-settings.PAGE_VIEW_RETENTION)       # everything is older than "the future"
    assert pageviews.recent(project["pid"]) == []


def test_only_beacon_actions_are_accepted(beacon, project):
    assert beacon(page(project, action="risk.rated")).status_code == 422


def test_a_beacon_is_small(beacon, project):
    assert beacon(page(project, details={"page": "x" * 3000})).status_code == 413


def test_a_beacon_without_a_witnessed_request_is_refused(beacon, project):
    assert beacon(page(project), with_request=False).status_code == 401


def test_a_beacon_citing_someone_elses_request_is_refused(beacon, project):
    assert beacon(page(project), subject=OWNER, presenter=MEMBER).status_code == 401


def test_a_flood_of_beacons_is_cut_off(beacon, project, settings):
    codes = [beacon(page(project)).status_code for _ in range(settings.BEACON_PER_MINUTE + 5)]
    assert codes.count(429) >= 5
