"""The charts each plugin declares (get_metric_visualizations, per plugin configuration) travel in the
snapshot, so the renderer draws them in Test results (2026-10-05). The composer asks the platform as the
person generating the report, and only for a layout with Test results. A platform that does not answer
leaves them out; the report is still made. Database tests, fake renderer, the platform call stubbed."""
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

DECLARED = {"configs": {"7": [{"chart_type": "bars", "metrics": ["psi"], "title": "PSI per feature",
                               "group_by_dimensions": ["feature"]}]}, "warnings": []}


@pytest.fixture
def platform(monkeypatch):
    from report_composer import declared_charts

    asked = []

    def fetch(request, project):
        asked.append(project["slug"])
        return DECLARED
    monkeypatch.setattr(declared_charts, "fetch", fetch)
    return asked


def make(client, auth, blocks):
    return new_layout(client, auth, name="With results", system_id=IDS["A_V2"], blocks=blocks)


def test_a_report_with_test_results_carries_the_declared_charts(client, auth, fake_renderer, platform):
    lay = make(client, auth, [blk("cover"), blk("test_results")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    assert fake_renderer.snapshots[-1]["declared_charts"] == DECLARED["configs"]
    assert platform == ["alpha"]


def test_the_preview_carries_them_too(client, auth, fake_renderer, platform):
    lay = make(client, auth, [blk("test_results")])
    assert client.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("victor")).status_code == 200
    assert fake_renderer.snapshots[-1]["declared_charts"] == DECLARED["configs"]


def test_a_layout_without_test_results_asks_nothing(client, auth, fake_renderer, platform):
    lay = make(client, auth, [blk("cover")])
    client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert platform == [] and "declared_charts" not in fake_renderer.snapshots[-1]


def test_a_platform_that_does_not_answer_leaves_them_out(client, auth, fake_renderer, monkeypatch):
    from report_composer import declared_charts

    monkeypatch.setattr(declared_charts, "fetch", lambda request, project: None)
    lay = make(client, auth, [blk("test_results")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code == 201 and "declared_charts" not in fake_renderer.snapshots[-1]


def test_fetch_asks_the_platform_with_the_callers_token(monkeypatch):
    from types import SimpleNamespace

    from report_composer import declared_charts

    seen = {}

    class Client:
        def __init__(self, timeout):
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers):
            seen["url"], seen["auth"] = url, headers["Authorization"]
            return SimpleNamespace(status_code=200, json=lambda: DECLARED)
    monkeypatch.setattr(declared_charts.httpx, "Client", Client)
    monkeypatch.setenv("PLATFORM_URL", "http://platform:8000/")
    request = SimpleNamespace(headers={"authorization": "Bearer tok"})
    assert declared_charts.fetch(request, {"slug": "alpha", "pid": "p"}) == DECLARED
    assert seen["url"] == "http://platform:8000/projects/alpha/declared-charts" and seen["auth"] == "Bearer tok"
