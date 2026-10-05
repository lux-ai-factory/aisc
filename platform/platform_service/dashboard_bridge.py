"""Tell the dashboard that a project was made or is about to go.

The dashboard keeps one set of objects per project (a connection to its
database, two datasets, a role and a dashboard); its bridge makes or removes
them. Called here, after a project's database exists and before it is dropped.

Best-effort by design: a dashboard that is down, slow or not configured never
stops a project being made or deleted. A failed registration is remembered by
the caller and tried again by `db.provision_all`.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


def _call(method: str, pid: str, body: dict | None = None) -> bool:
    base = (os.environ.get("DASHBOARD_BRIDGE_URL") or "").rstrip("/")
    if not base:
        return True  # no dashboard configured: nothing to tell
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base}/api/v1/aisc_project/{pid}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-AISC-Bridge-Token": os.environ.get("DASHBOARD_BRIDGE_TOKEN", ""),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read()
        return True
    except Exception:
        logger.warning("the dashboard bridge did not take %s of project %s", method, pid, exc_info=True)
        return False


def register(pid, slug: str, name: str) -> bool:
    """The project exists: make its dashboard objects. False when the bridge did not take it."""
    return _call("POST", str(pid), {"slug": slug, "name": name})


def unregister(pid) -> bool:
    """The project is about to go: remove its dashboard objects."""
    return _call("DELETE", str(pid))


class BridgeUnavailable(RuntimeError):
    """The dashboard did not take a plugin's tile."""


def sync_plugin(pid, body: dict) -> dict:
    """Make or update one plugin's tile from its default charts (plugin dashboards 2026-10-04):
    PUT /api/v1/aisc_project/<pid>/plugins. {"slug", "charts"}; BridgeUnavailable when it is not taken."""
    base = (os.environ.get("DASHBOARD_BRIDGE_URL") or "").rstrip("/")
    if not base:
        raise BridgeUnavailable("no dashboard is configured (DASHBOARD_BRIDGE_URL)")
    request = urllib.request.Request(
        f"{base}/api/v1/aisc_project/{pid}/plugins", data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={"Content-Type": "application/json", "X-AISC-Bridge-Token": os.environ.get("DASHBOARD_BRIDGE_TOKEN", "")})
    try:
        # a sync imports through Superset: longer than registration's few seconds
        with urllib.request.urlopen(request, timeout=60) as response:
            answer = json.loads(response.read() or b"{}")
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("the dashboard did not take %s of project %s", body.get("plugin"), pid, exc_info=True)
        raise BridgeUnavailable(f"the dashboard did not take {body.get('label') or body.get('plugin')}: "
                                f"{type(exc).__name__}") from None
    return {"slug": answer["slug"], "charts": int(answer.get("charts", 0))}
