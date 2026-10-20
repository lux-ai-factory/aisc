"""The dashboard opened from the AI Assessment Sandbox learns its project from the link (?aisc_project=<pid>),
so its "← Back" can return to that Sandbox (apps/results-dashboard/aisc_ext/back.py). No database."""
from urllib.parse import parse_qs, urlsplit

from platform_service import dashboards

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
TILES = [{"plugin": "aisc-langbite", "label": "LangBiTe", "url": "http://dash.test/superset/dashboard/t1/"}]


def query(url):
    return parse_qs(urlsplit(url).query)


def test_every_tile_of_the_person_carries_the_project(monkeypatch):
    url = dashboards.open_url(TILES, None, None, PID)
    assert urlsplit(url).path.endswith("/dashboard/list/")
    assert query(url) == {"viewMode": ["card"], "aisc_project": [PID]}


def test_one_plugins_tile_carries_the_project_with_or_without_a_target():
    assert query(dashboards.open_url(TILES, "LangBiTe", None, PID)) == {"aisc_project": [PID]}
    q = query(dashboards.open_url(TILES, "LangBiTe", "the model", PID))
    assert q["aisc_project"] == [PID] and "NATIVE_FILTER-target" in q["native_filters"][0]


def test_a_plugin_the_project_does_not_have_is_still_none():
    assert dashboards.open_url(TILES, "nope", None, PID) is None
