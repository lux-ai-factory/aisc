"""A project's plugin dashboards in the results dashboard.

Each engine plugin switched on in the project, with a finished run, gets a tile (a Superset dashboard) made from
its default charts (one per plugin, whatever its versions). A tile someone deleted stays deleted (the bridge keeps
that).
A plugin declares them in its contract (aisc-plugin-interface: get_metric_visualizations), and the engine
serves them with each run's results. So the platform:
1. reads the project's plugins and each one's latest finished run (the engine's tables, as the sandbox tiles
   read them, evidence.py);
2. asks the engine for that run's default charts, with the caller's own token, so the engine checks and
   records that person as if they had used the engine;
3. hands them to the dashboard's bridge (dashboard_bridge.sync_plugin), which makes or updates the tile.
A plugin whose results the engine refuses gets a tile saying to run it."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

from platform_service import dashboard_bridge, engine_components, engine_runs, evidence

logger = logging.getLogger(__name__)

#: each plugin with its latest finished run of the assessment record (none when it never ran): not archived,
#: not on a local model file (engine_runs)
_LATEST_RUNS = (
    "SELECT DISTINCT ON (pl.id) pl.package_name, pl.name, pl.version,"
    " COALESCE(NULLIF(pl.display_name, ''), pl.name, pl.package_name) AS label, pl.enabled,"
    " ep.pid::text AS evaluation_plugin_pid, e.pid::text AS evaluation_pid"
    " FROM engine.aisc_backend_plugin pl"
    " LEFT JOIN engine.aisc_backend_pluginconfig pc ON pc.plugin_id = pl.id"
    " LEFT JOIN engine.aisc_backend_evaluationplugin ep ON ep.plugin_config_id = pc.id AND ep.status = 'Done'"
    "  AND " + engine_runs.NOT_LOCAL +
    " LEFT JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id AND " + engine_runs.NOT_ARCHIVED +
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
                    "enabled": bool(r["enabled"]), "evaluation_plugin_pid": r["evaluation_plugin_pid"] if ran else None,
                    "evaluation_pid": r["evaluation_pid"] if ran else None})
    return sorted(out, key=lambda p: p["label"].lower())


def visualizations(pid, token: str, run: dict) -> list[dict]:
    """The run's default charts, as the engine serves them with its results."""
    path = f"/api/v1/plugins/{run['evaluation_plugin_pid']}/evaluations/{run['evaluation_pid']}/result"
    answer = engine_components._call("GET", path, pid, token)
    return list(answer.get("metric_visualizations") or [])


#: each plugin configuration with its latest finished run of the assessment record (the report's declared charts)
_LATEST_RUN_PER_CONFIG = (
    "SELECT DISTINCT ON (pc.id) pc.id AS config_id,"
    " COALESCE(NULLIF(pl.display_name, ''), pl.name, pl.package_name) AS label,"
    " ep.pid::text AS evaluation_plugin_pid, e.pid::text AS evaluation_pid"
    " FROM engine.aisc_backend_pluginconfig pc"
    " JOIN engine.aisc_backend_plugin pl ON pl.id = pc.plugin_id"
    " JOIN engine.aisc_backend_evaluationplugin ep ON ep.plugin_config_id = pc.id AND ep.status = 'Done'"
    "  AND " + engine_runs.NOT_LOCAL +
    " JOIN engine.aisc_backend_evaluation e ON e.id = ep.evaluation_id AND " + engine_runs.NOT_ARCHIVED +
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


def tiles_to_make(runs: list[dict]) -> list[dict]:
    """One entry per plugin that gets a tile: some version of it is switched on and some version finished a run.
    The entry is the newest version that ran (runs lists the versions oldest first)."""
    by_plugin: dict[str, list[dict]] = {}
    for run in runs:
        by_plugin.setdefault(run["plugin"], []).append(run)
    out = []
    for versions in by_plugin.values():
        ran = [v for v in versions if v["evaluation_pid"]]
        if ran and any(v["enabled"] for v in versions):
            out.append(ran[-1])
    return out


def sync(pid, project_name: str, token: str) -> dict:
    """The tiles of the plugins that get one, made or updated: {"dashboards": [{plugin, label, slug, url, charts}],
    "warnings"}. Every plugin is listed; slug and url are None for one with no tile (none due, or deleted by
    someone), so a link to it opens the list of tiles. dashboard_bridge.BridgeUnavailable when the dashboard does
    not take them."""
    dashboards, warnings = [], []
    runs = latest_runs(pid)
    made = {}
    for run in tiles_to_make(runs):
        charts = []
        try:
            charts = visualizations(pid, token, run)
        except engine_components.EngineUnavailable as exc:
            warnings.append(f"{run['label']}: its default charts were not read ({exc}); its tile says to run it")
        made[run["plugin"]] = dashboard_bridge.sync_plugin(pid, {"plugin": run["plugin"], "label": run["label"],
                                                                 "version": run["version"],
                                                                 "project_name": project_name,
                                                                 "visualizations": charts})
    for plugin, label in dict((r["plugin"], r["label"]) for r in runs).items():
        tile = made.get(plugin) or {}
        slug = tile.get("slug")
        dashboards.append({"plugin": plugin, "label": label, "slug": slug,
                           "url": f"{public_url()}/superset/dashboard/{slug}/" if slug else None,
                           "charts": tile.get("charts", 0)})
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
    of theirs when no plugin is named or the plugin has no tile; None for a plugin the project does not have. The link names the project
    (aisc_project), so the dashboard's "← Back" returns to its AI Assessment Sandbox."""
    back = f"aisc_project={quote(str(pid), safe='')}"
    if not plugin_label:
        return f"{public_url()}/dashboard/list/?viewMode=card&{back}"
    named = [d for d in dashboards if d["label"] == plugin_label or d["plugin"] == plugin_label]
    if not named:
        return None
    found = next((d for d in named if d.get("url")), None)
    if found is None:                                 # no tile (none due, or deleted): the tiles there are
        return f"{public_url()}/dashboard/list/?viewMode=card&{back}"
    if not target and version is None:
        return f"{found['url']}?{back}"
    return f"{found['url']}?native_filters={quote(target_mask(target, version), safe='')}&{back}"
