"""The engine's components, as the platform makes and renames them (targets plan v2).

Every call goes through the engine's own API with the caller's own token, so the engine checks and
records that person as if they had used the engine. The engine keeps its own project row per
platform project, with its own pid: `for-platform` finds it (and makes it on first use).
"""
from __future__ import annotations

import os

import httpx

PROJECT_HEADER = "X-AISC-Project"
TIMEOUT_S = 20


class EngineUnavailable(RuntimeError):
    """The engine did not accept the call."""


def _base() -> str:
    return (os.environ.get("ENGINE_URL") or "http://aisc-backend:8000").rstrip("/")


def _call(method: str, path: str, pid, token: str, body: dict | None = None) -> dict:
    try:
        r = httpx.request(method, f"{_base()}{path}", json=body, timeout=TIMEOUT_S,
                          headers={"Authorization": f"Bearer {token}", PROJECT_HEADER: str(pid)})
    except httpx.HTTPError as exc:
        raise EngineUnavailable(f"the engine could not be reached ({type(exc).__name__})") from None
    if r.status_code >= 300:
        raise EngineUnavailable(f"the engine answered {r.status_code}")
    return r.json()


def engine_project(pid, token: str) -> str:
    """The engine's pid of this platform project."""
    return str(_call("POST", f"/api/v1/projects/for-platform/{pid}", pid, token)["pid"])


def components(pid, token: str, engine_pid: str | None = None) -> list[dict]:
    engine_pid = engine_pid or engine_project(pid, token)
    return list(_call("GET", f"/api/v1/projects/{engine_pid}/aisystem", pid, token).get("components") or [])


def create(pid, token: str, name: str, value: str, engine_pid: str | None = None) -> str:
    """A new `resource` component whose value is `value`; its pid."""
    engine_pid = engine_pid or engine_project(pid, token)
    made = _call("POST", f"/api/v1/projects/{engine_pid}/components", pid, token,
                 {"name": name, "component_type": "resource", "json_value": {"value": value}})
    return str(made["pid"])


def rename(pid, token: str, component: str, name: str) -> None:
    _call("PATCH", f"/api/v1/components/{component}", pid, token, {"name": name})


def value_of(component: dict) -> str | None:
    json_value = component.get("json_value")
    return json_value.get("value") if isinstance(json_value, dict) else None
