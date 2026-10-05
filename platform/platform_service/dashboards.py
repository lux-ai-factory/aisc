"""A project's plugin dashboards in the results dashboard (plugin dashboards 2026-10-04, T6).

Each engine plugin installed in the project gets a tile (a Superset dashboard) made from its default charts.
A plugin declares them in its contract (aisc-plugin-interface: get_metric_visualizations), and the engine
serves them with each run's results. So the platform:
1. reads the project's plugins and each one's latest finished run (the engine's tables, as the sandbox tiles
   read them, evidence.py);
2. asks the engine for that run's default charts, with the caller's own token, so the engine checks and
   records that person as if they had used the engine;
3. hands them to the dashboard's bridge (dashboard_bridge.sync_plugin), which makes or updates the tile.
A plugin with no run, or whose results the engine refuses, gets a tile saying to run it."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx

from platform_service import dashboard_bridge, engine_components, evidence

logger = logging.getLogger(__name__)

#: each plugin with its latest finished, not archived, run (none when it never ran)
_LATEST_RUNS = (
    "SELECT DISTINCT ON (pl.id) pl.package_name, pl.name, pl.version,"
    " COALESCE(NULLIF(pl.display_name, ''), pl.name, pl.package_name) AS label,"
    " ep.pid::text AS evaluation_plugin_pid, e.pid::text AS evaluation_pid"
    " FROM engine.aisc_backend_plugin pl"
    " LEFT JOIN engine.aisc_backend_pluginconfig pc ON pc.plugin_id = pl.id"
    " LEFT JOIN engine.aisc_backend_evaluationplugin ep ON ep.plugin_config_id = pc.id AND ep.status = 'Done'"
    " LEFT JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id AND e.status <> 'Archived'"
    " ORDER BY pl.id, (e.id IS NULL), e.created_at DESC, e.id DESC"
)


def latest_runs(pid) -> list[dict]:
    """[{plugin, label, version, evaluation_plugin_pid, evaluation_pid}], by label; the pids are None when the
    plugin never finished a run."""
    with evidence._reader(pid) as conn:
        rows = evidence._rows(conn, _LATEST_RUNS)
    out = []
    for r in rows:
        ran = r["evaluation_pid"] is not None
        out.append({"plugin": f"{r['package_name']}::{r['name']}", "label": r["label"], "version": r["version"],
                    "evaluation_plugin_pid": r["evaluation_plugin_pid"] if ran else None,
                    "evaluation_pid": r["evaluation_pid"] if ran else None})
    return sorted(out, key=lambda p: p["label"].lower())


def visualizations(pid, token: str, run: dict) -> list[dict]:
    """The run's default charts, as the engine serves them with its results."""
    path = f"/api/v1/plugins/{run['evaluation_plugin_pid']}/evaluations/{run['evaluation_pid']}/result"
    answer = engine_components._call("GET", path, pid, token)
    return list(answer.get("metric_visualizations") or [])


def public_url() -> str:
    return (os.environ.get("DASHBOARD_PUBLIC_URL") or "http://localhost:8188").rstrip("/")


def sync(pid, project_name: str, token: str) -> dict:
    """Every plugin's tile, made or updated: {"dashboards": [{plugin, label, slug, url, charts}], "warnings"}.
    dashboard_bridge.BridgeUnavailable when the dashboard does not take them."""
    dashboards, warnings = [], []
    for run in latest_runs(pid):
        charts = []
        if run["evaluation_pid"]:
            try:
                charts = visualizations(pid, token, run)
            except engine_components.EngineUnavailable as exc:
                warnings.append(f"{run['label']}: its default charts were not read ({exc}); its tile says to run it")
        made = dashboard_bridge.sync_plugin(pid, {"plugin": run["plugin"], "label": run["label"],
                                                  "version": run["version"], "project_name": project_name,
                                                  "visualizations": charts})
        dashboards.append({"plugin": run["plugin"], "label": run["label"], "slug": made["slug"],
                           "url": f"{public_url()}/superset/dashboard/{made['slug']}/", "charts": made["charts"]})
    return {"dashboards": dashboards, "warnings": warnings}


def _rison(value: str) -> str:
    """A string in rison, as results.html quotes it."""
    return "'" + value.replace("!", "!!").replace("'", "!'") + "'"


def target_mask(label: str) -> str:
    """The Target filter set to one target, in the URL form Superset reads (native_filters)."""
    v = _rison(label)
    return ("(NATIVE_FILTER-target:(id:NATIVE_FILTER-target,extraFormData:(filters:!((col:target_label,op:IN,"
            f"val:!({v})))),filterState:(value:!({v})),ownState:()))")


def open_url(dashboards: list[dict], plugin_label: str | None, target: str | None) -> str | None:
    """Where to send the person: the plugin's tile (with the target set), or every tile of theirs when no
    plugin is named; None for a plugin the project does not have."""
    if not plugin_label:
        return f"{public_url()}/dashboard/list/?viewMode=card"
    found = next((d for d in dashboards if d["label"] == plugin_label or d["plugin"] == plugin_label), None)
    if found is None:
        return None
    return found["url"] + (f"?native_filters={quote(target_mask(target), safe='')}" if target else "")
