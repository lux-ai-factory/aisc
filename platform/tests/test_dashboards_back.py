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


# Which plugin gets a tile: switched on, with a finished run.

def row(package, name, version, enabled, ran=True):
    return {"plugin": f"{package}::{name}", "label": name, "version": version, "enabled": enabled,
            "evaluation_plugin_pid": "p" if ran else None, "evaluation_pid": f"e-{version}" if ran else None}


def test_a_plugin_switched_on_with_a_run_gets_a_tile():
    assert [t["version"] for t in dashboards.tiles_to_make([row("a", "A", "1", True)])] == ["1"]


def test_a_plugin_that_never_ran_gets_no_tile():
    assert dashboards.tiles_to_make([row("a", "A", "1", True, ran=False)]) == []


def test_a_plugin_switched_off_gets_no_tile_whatever_it_ran():
    assert dashboards.tiles_to_make([row("old", "A", "1", False)]) == []


def test_several_versions_of_a_plugin_make_one_tile_from_the_newest_that_ran():
    rows = [row("a", "A", "1", False), row("a", "A", "2", False), row("a", "A", "3", True, ran=False)]
    assert [t["version"] for t in dashboards.tiles_to_make(rows)] == ["2"]


def test_the_tile_of_a_plugin_switched_on_is_kept_when_only_an_older_version_is_off():
    rows = [row("a", "A", "1", False), row("a", "A", "2", True)]
    assert [t["evaluation_pid"] for t in dashboards.tiles_to_make(rows)] == ["e-2"]


def test_a_plugin_with_no_tile_opens_the_list_of_tiles():
    no_tile = [{"plugin": "old", "label": "Old", "url": None}]
    assert urlsplit(dashboards.open_url(no_tile, "Old", None, PID)).path.endswith("/dashboard/list/")


def test_of_two_plugins_with_one_label_the_one_with_a_tile_opens():
    two = [{"plugin": "old", "label": "L", "url": None}, {"plugin": "new", "label": "L", "url": "http://dash.test/t2/"}]
    assert urlsplit(dashboards.open_url(two, "L", None, PID)).path == "/t2/"


def test_sync_makes_tiles_only_for_those_and_names_the_others_without_a_url(monkeypatch):
    monkeypatch.setattr(dashboards, "latest_runs", lambda pid: [row("old", "Old", "1", False), row("a", "A", "2", True),
                                                                row("gone", "Gone", "3", True)])
    monkeypatch.setattr(dashboards, "visualizations", lambda pid, token, run: [])
    made = []

    def bridge(pid, body):
        made.append(body["plugin"])
        return {"slug": None if body["plugin"].startswith("gone") else "s", "charts": 0}

    monkeypatch.setattr(dashboards.dashboard_bridge, "sync_plugin", bridge)
    out = {d["plugin"]: d["url"] for d in dashboards.sync(PID, "p", "t")["dashboards"]}
    assert made == ["a::A", "gone::Gone"]
    assert out["old::Old"] is None and out["gone::Gone"] is None and out["a::A"].endswith("/superset/dashboard/s/")
