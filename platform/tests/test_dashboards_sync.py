"""A project's plugin dashboards, synced through the platform (plugin dashboards 2026-10-04, T6.1 to T6.4).

The platform knows each plugin installed in the project (the engine's tables, as the sandbox tiles read them)
and its latest finished run. It asks the engine for that run's default charts (the plugin's
get_metric_visualizations, which the engine serves with the run's results), with the caller's own token, and
hands them to the dashboard's bridge, which makes or updates the plugin's tile. Engine and bridge are stubs."""
from __future__ import annotations

import pytest

from tests.connection_support import Stub
from tests.test_evidence import ALICE, VERA, _reader, catalogue, engine, project, sql  # noqa: F401

E1, E2, E3 = ("a0000000-0000-4000-8000-00000000000" + n for n in "123")
EP1, EP2, EP3 = ("b0000000-0000-4000-8000-00000000000" + n for n in "123")
DRIFT_VIZ = [{"chart_type": "bars", "metrics": ["psi"], "title": "PSI per feature", "group_by_dimensions": ["feature"]}]


@pytest.fixture
def runs(engine, dsn):
    """LangBiTe ran twice (the second the latest), Promptfoo never; a third, archived run of LangBiTe is newer
    still and must be ignored."""
    pid = engine["pid"]
    sql(dsn, pid, "ALTER TABLE engine.aisc_backend_evaluation ADD COLUMN IF NOT EXISTS pid uuid;"
                  "ALTER TABLE engine.aisc_backend_evaluationplugin ADD COLUMN IF NOT EXISTS pid uuid")
    plugin = sql(dsn, pid, "SELECT id FROM engine.aisc_backend_plugin WHERE package_name = 'aisc-plugin-langbite'")[0][0]
    config = sql(dsn, pid, "INSERT INTO engine.aisc_backend_pluginconfig (plugin_id, name) VALUES (%s, 'c') RETURNING id",
                 (plugin,))[0][0]
    for e, ep, at, status in ((E1, EP1, "2026-10-04 18:07+00", "Done"), (E2, EP2, "2026-10-04 20:39+00", "Done"),
                              (E3, EP3, "2026-10-04 21:00+00", "Archived")):
        ev = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluation (status, created_at, pid) VALUES (%s, %s, %s) "
                           "RETURNING id", (status, at, e))[0][0]
        sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationplugin (evaluation_id, plugin_config_id, status, pid) "
                      "VALUES (%s, %s, 'Done', %s)", (ev, config, ep))
    return engine


@pytest.fixture
def engine_api(monkeypatch):
    stub = Stub()
    stub.route("GET", f"/api/v1/plugins/{EP2}/evaluations/{E2}/result",
               (200, {"measurements": [], "metric_visualizations": DRIFT_VIZ}))
    monkeypatch.setenv("ENGINE_URL", stub.base)
    yield stub
    stub.stop()


@pytest.fixture
def bridge(monkeypatch):
    stub = Stub()

    def answer(seen):
        body = seen["json"]
        return {"slug": "aisc-x-" + body["plugin"].split("::")[1].lower(), "charts": len(body["visualizations"])}
    stub.route("PUT", "/api/v1/aisc_project/{pid}/plugins", (200, answer))
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.base)
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", "bridge-token")
    monkeypatch.setenv("DASHBOARD_PUBLIC_URL", "http://localhost:8188")
    yield stub
    stub.stop()


def _route(bridge, pid):
    bridge.routes[("PUT", f"/api/v1/aisc_project/{pid}/plugins")] = bridge.routes.pop(
        ("PUT", "/api/v1/aisc_project/{pid}/plugins"))


def sync(client, as_user, project, who=VERA):
    return client.post(f"/projects/{project['slug']}/dashboards/sync", headers=as_user(who))


def test_t6_1_each_plugin_is_synced_with_the_default_charts_of_its_latest_run(client, as_user, runs, engine_api, bridge):
    _route(bridge, runs["pid"])
    r = sync(client, as_user, runs)
    assert r.status_code == 200, r.text
    asked = engine_api.requests("GET", "/api/v1/plugins/")
    assert [a["path"] for a in asked] == [f"/api/v1/plugins/{EP2}/evaluations/{E2}/result"]   # the latest, not archived
    assert asked[0]["headers"]["authorization"].startswith("Bearer ")
    assert asked[0]["headers"]["x-aisc-project"] == runs["pid"]
    sent = {b["json"]["plugin"]: b["json"] for b in bridge.requests("PUT")}
    assert sent["aisc-plugin-langbite::LangBiTePlugin"] == {
        "plugin": "aisc-plugin-langbite::LangBiTePlugin", "label": "LangBiTe", "version": "1.0",
        "project_name": runs["name"], "visualizations": DRIFT_VIZ}
    assert bridge.requests("PUT")[0]["headers"]["x-aisc-bridge-token"] == "bridge-token"


def test_t6_2_a_plugin_with_no_run_is_sent_with_no_charts(client, as_user, runs, engine_api, bridge):
    _route(bridge, runs["pid"])
    sync(client, as_user, runs)
    sent = {b["json"]["plugin"]: b["json"] for b in bridge.requests("PUT")}
    assert sent["aisc-plugin-promptfoo::PromptfooPlugin"]["visualizations"] == []


def test_t6_2_a_run_the_engine_refuses_is_sent_with_no_charts_and_said(client, as_user, runs, monkeypatch, bridge):
    down = Stub()
    monkeypatch.setenv("ENGINE_URL", down.base)          # no route: 404
    _route(bridge, runs["pid"])
    r = sync(client, as_user, runs)
    down.stop()
    assert r.status_code == 200
    sent = {b["json"]["plugin"]: b["json"] for b in bridge.requests("PUT")}
    assert sent["aisc-plugin-langbite::LangBiTePlugin"]["visualizations"] == []
    assert any("LangBiTe" in w for w in r.json()["warnings"])


def test_t6_3_the_answer_lists_each_dashboard(client, as_user, runs, engine_api, bridge):
    _route(bridge, runs["pid"])
    body = sync(client, as_user, runs).json()
    by_label = {d["label"]: d for d in body["dashboards"]}
    assert set(by_label) == {"LangBiTe", "Promptfoo"}
    assert by_label["LangBiTe"]["url"] == "http://localhost:8188/superset/dashboard/aisc-x-langbiteplugin/"
    assert by_label["LangBiTe"]["charts"] == 1 and by_label["Promptfoo"]["charts"] == 0


def test_t6_3_a_bridge_that_is_down_is_502_and_claims_nothing(client, as_user, runs, engine_api, monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", "http://127.0.0.1:9")
    r = sync(client, as_user, runs)
    assert r.status_code == 502 and "dashboard" in r.json()["detail"]


def test_t6_1_a_stranger_gets_404(client, as_user, runs, engine_api, bridge):
    assert sync(client, as_user, runs, who="00000000-0000-0000-0000-00000000dead").status_code == 404


def test_t6_4_open_syncs_then_goes_to_the_plugins_dashboard_with_the_target_set(client, as_user, runs, engine_api, bridge):
    """The Target filter is set in the URL as results.html set it on the project dashboard (rison masks)."""
    from urllib.parse import unquote, urlsplit
    _route(bridge, runs["pid"])
    r = client.get(f"/projects/{runs['slug']}/dashboards/open?plugin=LangBiTe&target=Explanation%20assistant",
                   headers=as_user(VERA), follow_redirects=False)
    assert r.status_code == 303
    url = urlsplit(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "http://localhost:8188/superset/dashboard/aisc-x-langbiteplugin/"
    masks = unquote(url.query)
    assert masks.startswith("native_filters=(NATIVE_FILTER-target:(")
    assert "extraFormData:(filters:!((col:target_label,op:IN,val:!('Explanation assistant'))))" in masks
    assert "filterState:(value:!('Explanation assistant'))" in masks
    assert bridge.requests("PUT")                                       # synced first


def test_t6_4_with_no_target_there_is_no_mask(client, as_user, runs, engine_api, bridge):
    _route(bridge, runs["pid"])
    r = client.get(f"/projects/{runs['slug']}/dashboards/open?plugin=LangBiTe", headers=as_user(VERA),
                   follow_redirects=False)
    assert r.headers["location"] == "http://localhost:8188/superset/dashboard/aisc-x-langbiteplugin/"


def test_t6_4_open_with_no_plugin_goes_to_the_projects_tiles(client, as_user, runs, engine_api, bridge):
    _route(bridge, runs["pid"])
    r = client.get(f"/projects/{runs['slug']}/dashboards/open", headers=as_user(VERA), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "http://localhost:8188/dashboard/list/?viewMode=card"


def test_t6_4_an_unknown_plugin_is_404(client, as_user, runs, engine_api, bridge):
    _route(bridge, runs["pid"])
    r = client.get(f"/projects/{runs['slug']}/dashboards/open?plugin=Nope", headers=as_user(VERA), follow_redirects=False)
    assert r.status_code == 404
