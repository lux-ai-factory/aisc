"""The engine, reached only through its public API and only with the admin's own token.

Nothing here touches the engine's database: its schema is frozen, grants included (spec D2).
"""
from __future__ import annotations

import uuid

import httpx

from aisc_connectors.settings import settings


class EngineError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"engine answered {status}: {detail}")
        self.status = status
        self.detail = detail


class NotFound(EngineError):
    pass


class EngineClient:
    def __init__(self, token: str | None, base: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(base_url=base or settings().engine_api_url, headers=headers,
                                  timeout=15, transport=transport)

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == 404:
            raise NotFound(404, "not found")
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail", response.text))
            except ValueError:
                detail = response.text[:300]
            raise EngineError(response.status_code, detail)
        return response

    def aisystem(self, project_pid: uuid.UUID) -> dict:
        return self._check(self._http.get(f"/projects/{project_pid}/aisystem")).json()

    def create_secret(self, project_pid: uuid.UUID, key: str, name: str, value: str) -> str:
        body = {"category": "secrets", "key": key, "name": name, "value": value}
        return self._check(self._http.post(f"/project/settings/{project_pid}", json=body)).json()["pid"]

    def delete_secret(self, project_pid: uuid.UUID, config_pid: uuid.UUID) -> None:
        self._check(self._http.delete(f"/project/settings/{project_pid}/{config_pid}"))

    def create_component(self, project_pid: uuid.UUID, name: str, component_type: str,
                         json_value: dict) -> str:
        body = {"name": name, "component_type": component_type, "json_value": json_value}
        return self._check(self._http.post(f"/projects/{project_pid}/components", json=body)).json()["pid"]

    def delete_component(self, component_pid: uuid.UUID) -> None:
        self._check(self._http.delete(f"/components/{component_pid}"))
