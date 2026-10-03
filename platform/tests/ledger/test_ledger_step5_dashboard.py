"""The dashboard's events, as its extension sends them (apps/results-dashboard/aisc_ext/ledger.py)
through the internal route with the dashboard's token, are accepted by the relay against the REAL registry,
each citing the witnessed request. A project's dashboard is `aisc-<pid hex>`: the witness finds the project
of a dashboard request from that slug, in the path or in the query (the "bridge" rule)."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, STRANGER, entries, log_of, needs_db, record, relay_all

pytestmark = needs_db
TOKEN = "dashboard-token-" + "d" * 32


@pytest.fixture(autouse=True)
def _enforce(mode, monkeypatch):
    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", TOKEN)


def slug_of(project):
    return "aisc-" + str(project["pid"]).replace("-", "")


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


@pytest.mark.parametrize("uri", [
    "/superset/dashboard/{slug}/",
    "/aiscreviewview/show/{slug}",
    "/api/v1/aisc_comment/?dashboard={slug}",
    "/api/v1/aisc_comment/7?dashboard={slug}",
])
def test_the_witness_finds_the_project_from_the_dashboards_slug(project, witnessed, uri):
    request_id = witnessed(MEMBER, "POST", "dashboard", uri.format(slug=slug_of(project)))
    assert str(record(request_id).project_pid) == str(project["pid"])


@pytest.mark.parametrize("uri", ["/superset/dashboard/12/", "/api/v1/aisc_comment/7",
                                 "/api/v1/aisc_comment/?dashboard=aisc-" + "0" * 32])
def test_a_dashboard_request_naming_no_project_goes_to_the_platform_log(project, witnessed, uri):
    assert record(witnessed(MEMBER, "POST", "dashboard", uri)).project_pid is None


def test_a_strangers_dashboard_request_names_no_project(project, witnessed):
    request_id = witnessed(STRANGER, "POST", "dashboard", f"/api/v1/aisc_comment/?dashboard={slug_of(project)}")
    assert record(request_id).project_pid is None


SAID = {"body": "The bar for MCAS looks off", "chart": 3, "parent": None}
REVIEW = {"message": "Please check", "chart": None, "assignee": "category:legal", "status": "open"}
CASES = [
    ("POST", "/api/v1/aisc_comment/?dashboard={slug}", "dashboard.comment.created", "comment", "7",
     {"details": {"dashboard": "{slug}", "chart": 3}, "content": SAID, "after": SAID}),
    ("DELETE", "/api/v1/aisc_comment/7?dashboard={slug}", "dashboard.comment.deleted", "comment", "7",
     {"details": {"dashboard": "{slug}"}, "content": SAID, "before": SAID}),
    ("POST", "/api/v1/aisc_review_request/?dashboard={slug}", "dashboard.review.requested", "review_request", "4",
     {"details": {"assignee": "category:legal"}, "content": REVIEW, "after": REVIEW}),
    ("PATCH", "/api/v1/aisc_review_request/4?dashboard={slug}", "dashboard.review.resolved", "review_request", "4",
     {"details": {"status_before": "open", "status_after": "done"}, "before": REVIEW,
      "after": {**REVIEW, "status": "done"}}),
]


def _filled(value, slug):
    if isinstance(value, dict):
        return {k: _filled(v, slug) for k, v in value.items()}
    return value.format(slug=slug) if isinstance(value, str) else value


@pytest.mark.parametrize("method, uri, action, item_type, item_id, over", CASES, ids=[c[2] for c in CASES])
def test_an_event_as_the_dashboard_sends_it_is_accepted(client, project, memory_ledger, witnessed, method, uri,
                                                        action, item_type, item_id, over):
    slug = slug_of(project)
    request_id = witnessed(MEMBER, method, "dashboard", uri.format(slug=slug))
    event = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
             "item_id": item_id, **_filled(over, slug)}
    r = client.post(f"/internal/projects/{project['pid']}/ledger/events", json=event,
                    headers={"X-AISC-Service-Token": TOKEN})
    assert r.status_code == 202, r.text
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == action]
    assert (e.source_app, e.item_id, e.actor_kind) == ("dashboard", item_id, "user")


def test_the_path_names_the_project_before_the_query(project, witnessed):
    """A dashboard in the path is the request's dashboard; a slug in the query can't override it."""
    other = "aisc-" + uuid.uuid4().hex
    request_id = witnessed(MEMBER, "POST", "dashboard", f"/superset/dashboard/{slug_of(project)}/?dashboard={other}")
    assert str(record(request_id).project_pid) == str(project["pid"])
