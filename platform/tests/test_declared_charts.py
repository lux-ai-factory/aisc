"""The charts each plugin declares (get_metric_visualizations), per plugin configuration, for the report
(2026-10-05). The engine serves them with a run's results and they depend on the plugin and its
configuration only, so the platform asks once per configuration, for its latest finished run, with the
caller's own token. The report composer puts them in the report's snapshot. Engine is a stub."""
from __future__ import annotations

from tests.connection_support import Stub
from tests.test_dashboards_sync import DRIFT_VIZ, E2, EP2, engine_api, runs  # noqa: F401
from tests.test_evidence import ALICE, VERA, _reader, catalogue, engine, project, sql  # noqa: F401


def declared(client, as_user, project, who=VERA):
    return client.get(f"/projects/{project['slug']}/declared-charts", headers=as_user(who))


def config_id(dsn, pid):
    return str(sql(dsn, pid, "SELECT id FROM engine.aisc_backend_pluginconfig WHERE name = 'c'")[0][0])


def test_each_configuration_gets_the_charts_of_its_latest_finished_run(client, as_user, runs, engine_api, dsn):
    r = declared(client, as_user, runs)
    assert r.status_code == 200, r.text
    assert r.json() == {"configs": {config_id(dsn, runs["pid"]): DRIFT_VIZ}, "warnings": []}
    asked = engine_api.requests("GET", "/api/v1/plugins/")
    assert [a["path"] for a in asked] == [f"/api/v1/plugins/{EP2}/evaluations/{E2}/result"]
    assert asked[0]["headers"]["authorization"].startswith("Bearer ")


def test_a_configuration_the_engine_refuses_is_left_out_and_said(client, as_user, runs, monkeypatch):
    down = Stub()
    monkeypatch.setenv("ENGINE_URL", down.base)          # no route: 404
    r = declared(client, as_user, runs)
    down.stop()
    assert r.status_code == 200 and r.json()["configs"] == {}
    assert any("LangBiTe" in w for w in r.json()["warnings"])


def test_a_stranger_gets_404(client, as_user, runs, engine_api):
    assert declared(client, as_user, runs, who="00000000-0000-0000-0000-00000000dead").status_code == 404
