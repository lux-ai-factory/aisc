"""A project's plugin dashboards in the results dashboard.

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


#: each plugin configuration with its latest finished, not archived, run (the report's declared charts)
_LATEST_RUN_PER_CONFIG = (
    "SELECT DISTINCT ON (pc.id) pc.id AS config_id,"
    " COALESCE(NULLIF(pl.display_name, ''), pl.name, pl.package_name) AS label,"
    " ep.pid::text AS evaluation_plugin_pid, e.pid::text AS evaluation_pid"
    " FROM engine.aisc_backend_pluginconfig pc"
    " JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
    " JOIN engine.aisc_backend_evaluationplugin ep ON ep.plugin_config_id = pc.id AND ep.status = 'Done'"
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id AND e.status <> 'Archived'"
    " ORDER BY pc.id, e.created_at DESC, e.id DESC"
)


def declared_charts(pid, token: str) -> dict:
    """{"configs": {config id: [chart]}, "warnings"}: what each plugin configuration's plugin declares
    (get_metric_visualizations), for the report. The charts depend on the plugin and its configuration only,
    so one engine call per configuration, for its latest finished run, with the caller's token."""
    with evidence._reader(pid) as conn:
        rows = evidence._rows(conn, _LATEST_RUN_PER_CONFIG)
    configs, warnings = {}, []
    for r in rows:
        try:
            configs[str(r["config_id"])] = visualizations(pid, token, r)
        except engine_components.EngineUnavailable as exc:
            warnings.append(f"{r['label']}: its declared charts were not read ({exc})")
    return {"configs": configs, "warnings": warnings}


def public_url() -> str:
    """The dashboard as the browser reaches it: the name the launcher (Caddy's /origins.json) and the
    reports (REPORT_SUPERSET_PUBLIC_URL) take it from too."""
    return (os.environ.get("DASHBOARD_EXTERNAL_URL") or "http://localhost:8188").rstrip("/")


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


def _filter(name: str, column: str, value: str) -> str:
    """One native filter set to one value, in the rison form Superset reads."""
    return (f"NATIVE_FILTER-{name}:(id:NATIVE_FILTER-{name},extraFormData:(filters:!((col:{column},op:IN,"
            f"val:!({value})))),filterState:(value:!({value})),ownState:())")


def target_mask(label: str, version: int | None = None) -> str:
    """The Target filter set to one target, and the Version filter to one AI card version when given, in the URL
    form Superset reads (native_filters)."""
    parts = [_filter("target", "target_label", _rison(label))] if label else []
    if version is not None:
        parts.append(_filter("version", "system_version", str(int(version))))
    return "(" + ",".join(parts) + ")"


def open_url(dashboards: list[dict], plugin_label: str | None, target: str | None, pid: str,
             version: int | None = None) -> str | None:
    """Where to send the person: the plugin's tile (with the target and the AI card version set), or every tile
    of theirs when no plugin is named; None for a plugin the project does not have. The link names the project
    (aisc_project), so the dashboard's "← Back" returns to its AI Assessment Sandbox."""
    back = f"aisc_project={quote(str(pid), safe='')}"
    if not plugin_label:
        return f"{public_url()}/dashboard/list/?viewMode=card&{back}"
    found = next((d for d in dashboards if d["label"] == plugin_label or d["plugin"] == plugin_label), None)
    if found is None:
        return None
    if not target and version is None:
        return f"{found['url']}?{back}"
    return f"{found['url']}?native_filters={quote(target_mask(target, version), safe='')}&{back}"
