"""The engine's view of a connection: one `resource` component of the project's AI system whose
value is `connection:<pid>/<name>`, which an evaluation binds as an input and the plugin-side client
(aisc_plugin_interface.connections) resolves.

The platform creates and renames it through the engine's own API, with the admin's own token (the
one that made the request), so the engine checks and records that person exactly as if they had
used the engine directly. Nothing in the engine changes for this.
"""
from __future__ import annotations

import os

import httpx

PROJECT_HEADER = "X-AISC-Project"
TIMEOUT_S = 20


class EngineUnavailable(RuntimeError):
    """The engine did not accept the call; the connection stays unlinked."""


def _base() -> str:
    return (os.environ.get("ENGINE_URL") or "http://aisc-backend:8000").rstrip("/")


def reference(pid: str, name: str) -> str:
    return f"connection:{str(pid)}/{name}"


def _call(method: str, path: str, pid: str, token: str, body: dict) -> dict:
    try:
        r = httpx.request(method, f"{_base()}{path}", json=body, timeout=TIMEOUT_S,
                          headers={"Authorization": f"Bearer {token}", PROJECT_HEADER: str(pid)})
    except httpx.HTTPError as exc:
        raise EngineUnavailable(f"the engine could not be reached ({type(exc).__name__})") from None
    if r.status_code >= 300:
        raise EngineUnavailable(f"the engine answered {r.status_code}")
    return r.json()


def create(pid: str, name: str, label: str, token: str) -> str:
    """The new component's pid."""
    made = _call("POST", f"/api/v1/projects/{pid}/components", pid, token,
                 {"name": label, "component_type": "resource", "json_value": {"value": reference(pid, name)}})
    return str(made["pid"])


def rename(pid: str, component: str, label: str, token: str) -> None:
    _call("PATCH", f"/api/v1/components/{component}", pid, token, {"name": label})
