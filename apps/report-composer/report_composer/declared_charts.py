"""The charts each plugin declares, for the report's Test results (2026-10-05).

A plugin declares its charts in its contract (get_metric_visualizations); the engine serves them with a
run's results, and the platform gathers them per plugin configuration (GET /projects/{slug}/declared-charts),
asking the engine as the person who asks. The composer asks at generation and preview, as that person,
and the snapshot carries what came back, so the report records the charts it drew.

Best effort: with no platform, no token or no answer, the snapshot carries none and Test results draws
what it drew before (the tool's own section or the generic table).
"""
from __future__ import annotations

import logging
import os

import httpx

from .anchor import _token

_log = logging.getLogger(__name__)
#: one engine call per plugin configuration, each loading the plugin
TIMEOUT_S = 30.0


def wanted(blocks) -> bool:
    """Only a layout with Test results draws them."""
    return any(b.get("block_type") == "test_results" for b in blocks or ())


def fetch(request, project: dict) -> dict | None:
    """{"configs": {plugin config id: [chart]}, "warnings": [...]}, or None."""
    token = _token(request)
    base = os.environ.get("PLATFORM_URL", "").rstrip("/")
    if not base or not token:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT_S) as http:
            r = http.get(f"{base}/projects/{project['slug']}/declared-charts",
                         headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return None
        answer = r.json()
    except (httpx.HTTPError, ValueError):
        _log.warning("project %s: the declared charts could not be read; Test results draws none", project["pid"])
        return None
    if not isinstance(answer, dict) or not isinstance(answer.get("configs"), dict):
        return None
    for warning in answer.get("warnings") or ():
        _log.info("project %s: %s", project["pid"], warning)
    return answer


def for_snapshot(request, project: dict, blocks) -> dict | None:
    """What the snapshot carries under declared_charts, or None to leave the key out."""
    if not wanted(blocks):
        return None
    answer = fetch(request, project)
    return answer["configs"] if answer else None
