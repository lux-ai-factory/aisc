"""The sandbox page's Report column: how many reports one AI card version has and the newest. The report
composer keeps them in tables no reader is granted, so the platform asks it with the caller's own token,
as it asks the engine. Runs on the throwaway; the composer is a stub."""
from __future__ import annotations

import pytest

from tests.conftest import ALICE, needs_database
from tests.http_stub import Stub

pytestmark = needs_database
BOB = "00000000-0000-0000-0000-000000000b0b"
VERSION = "6f1c2d3e-0000-4000-8000-000000000001"
LATEST = {"id": "9a8b7c6d-0000-4000-8000-000000000001", "layout_id": "builtin-summary",
          "layout_name": "Summary report", "format": "pdf", "status": "done",
          "created_at": "2026-10-20T09:00:00+00:00", "download": "/api/p/alpha/reports/9a8b/download"}


@pytest.fixture
def composer(monkeypatch):
    s = Stub()
    monkeypatch.setenv("REPORT_COMPOSER_URL", s.base)
    yield s
    s.stop()


def summary(client, as_user, project, who=ALICE, version=VERSION):
    return client.get(f"/projects/{project['slug']}/reports?version={version}", headers=as_user(who))


def test_the_composers_count_and_newest_report_are_passed_on(client, as_user, project, composer):
    composer.route("GET", f"/api/p/{project['slug']}/reports", (200, {"count": 3, "latest": LATEST}))
    r = summary(client, as_user, project)
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 3, "latest": LATEST}
    asked = composer.requests("GET")
    assert len(asked) == 1 and asked[0].query == {"system_id": [VERSION]}
    assert asked[0].header("authorization").startswith("Bearer ")
    assert asked[0].header("X-Auth-Request-Access-Token") == asked[0].header("authorization").removeprefix("Bearer ")


def test_a_composer_that_does_not_answer_is_a_502(client, as_user, project, composer):
    r = summary(client, as_user, project)          # no route: the stub answers 404
    assert r.status_code == 502 and "report composer" in r.json()["detail"]


def test_a_stranger_gets_404_and_the_composer_is_not_asked(client, as_user, project, composer):
    assert summary(client, as_user, project, who=BOB).status_code == 404
    assert composer.requests("GET") == []
