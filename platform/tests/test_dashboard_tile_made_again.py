"""A plugin's tile someone deleted in the results dashboard stays deleted, but the person who opens it learns why
there is no tile and can have it made again.

The sync names a deleted tile (the bridge answers deleted: true); opening it sends the person to the sandbox page,
which says so, instead of the bare list of tiles; asking for it again makes it through the bridge (again: true) and
answers where the new tile is. Engine and bridge are stubs, as in test_dashboards_sync.py."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from platform_service import dashboards
from tests.test_dashboards_sync import _route, bridge, engine_api, runs  # noqa: F401
from tests.test_evidence import BOB, VERA, _reader, catalogue, engine, evidence_project  # noqa: F401

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


def _row(plugin, label, version, enabled, evaluation_pid="e"):
    return {"plugin": f"{plugin}::{label}", "label": label, "version": version, "enabled": enabled,
            "evaluation_pid": evaluation_pid}


def test_the_sync_names_a_tile_someone_deleted(monkeypatch):
    monkeypatch.setattr(dashboards, "latest_runs", lambda pid: [_row("a", "A", "1", True), _row("g", "Gone", "1", True)])
    monkeypatch.setattr(dashboards, "visualizations", lambda pid, token, run: [])
    monkeypatch.setattr(dashboards.dashboard_bridge, "sync_plugin",
                        lambda pid, body: {"slug": None, "charts": 0, "deleted": True} if body["plugin"].startswith("g")
                        else {"slug": "s", "charts": 0, "deleted": False})
    out = {d["plugin"]: d for d in dashboards.sync(PID, "p", "t")["dashboards"]}
    assert out["g::Gone"]["deleted"] is True and out["g::Gone"]["url"] is None
    assert out["a::A"]["deleted"] is False


def test_opening_a_deleted_tile_goes_to_the_sandbox_page_that_says_so():
    tiles = [{"plugin": "g::Gone", "label": "Gone", "url": None, "deleted": True}]
    url = urlsplit(dashboards.open_url(tiles, "Gone", None, PID, slug="demo"))
    assert url.path == "/evidence.html" and not url.netloc
    assert parse_qs(url.query) == {"project": ["demo"], "tile_deleted": ["g::Gone"]}


def test_a_tile_that_is_not_due_still_opens_the_list_of_tiles():
    tiles = [{"plugin": "o::Old", "label": "Old", "url": None, "deleted": False}]
    assert urlsplit(dashboards.open_url(tiles, "Old", None, PID, slug="demo")).path.endswith("/dashboard/list/")


def _deleting_bridge(bridge, pid):  # noqa: F811
    """The bridge as it answers for a tile someone deleted: deleted, unless asked to make it again."""
    _route(bridge, pid)

    def answer(seen):
        body = seen["json"]
        if not body.get("again"):
            return {"slug": None, "charts": 0, "deleted": True}
        return {"slug": "aisc-x-" + body["plugin"].split("::")[1].lower(), "charts": len(body["visualizations"])}
    bridge.routes.pop(("PUT", f"/api/v1/aisc_project/{pid}/plugins"))
    bridge.route("PUT", f"/api/v1/aisc_project/{pid}/plugins", (200, answer))


def test_opening_a_deleted_tile_from_the_sandbox_says_why(client, as_user, runs, engine_api, bridge):  # noqa: F811
    _deleting_bridge(bridge, runs["pid"])
    r = client.get(f"/projects/{runs['slug']}/dashboards/open?plugin=LangBiTe", headers=as_user(VERA),
                   follow_redirects=False)
    assert r.status_code == 303
    url = urlsplit(r.headers["location"])
    assert url.path == "/evidence.html" and parse_qs(url.query)["tile_deleted"] == ["aisc-plugin-langbite::LangBiTePlugin"]


def test_an_editor_has_a_deleted_tile_made_again(client, as_user, runs, engine_api, bridge):  # noqa: F811
    _deleting_bridge(bridge, runs["pid"])
    r = client.post(f"/projects/{runs['slug']}/dashboards/again", json={"plugin": "aisc-plugin-langbite::LangBiTePlugin"},
                    headers=as_user(BOB))
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("http://localhost:8188/superset/dashboard/aisc-x-langbiteplugin/")
    asked = [seen["json"] for seen in bridge.requests("PUT")]
    assert [b["plugin"] for b in asked if b.get("again")] == ["aisc-plugin-langbite::LangBiTePlugin"]


def test_a_viewer_cannot_undo_a_deletion(client, as_user, runs, engine_api, bridge):  # noqa: F811
    _deleting_bridge(bridge, runs["pid"])
    r = client.post(f"/projects/{runs['slug']}/dashboards/again", json={"plugin": "aisc-plugin-langbite::LangBiTePlugin"},
                    headers=as_user(VERA))
    assert r.status_code == 403
    assert not [seen for seen in bridge.requests("PUT") if seen["json"].get("again")]


def test_a_plugin_the_project_does_not_have_is_404(client, as_user, runs, engine_api, bridge):  # noqa: F811
    _deleting_bridge(bridge, runs["pid"])
    r = client.post(f"/projects/{runs['slug']}/dashboards/again", json={"plugin": "nope::Nope"}, headers=as_user(BOB))
    assert r.status_code == 404
