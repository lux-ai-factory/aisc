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

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "EngineClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _send(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        # Never let the message name the token or a request/response body: it may
        # carry a secret (create_secret's plaintext value, spec D2/D7).
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise EngineError(504, f"engine request timed out ({type(exc).__name__})") from exc
        except httpx.HTTPError as exc:
            raise EngineError(502, f"engine unreachable ({type(exc).__name__})") from exc

    def _check(self, response: httpx.Response, redact: tuple[str, ...] = ()) -> httpx.Response:
        if response.status_code == 404:
            raise NotFound(404, "not found")
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                detail = response.text
            else:
                # A dict's "detail" (FastAPI/Pydantic's shape) may itself be a list
                # or nested structure that echoes the request; str() covers it. A
                # non-object body (list, string, ...) is used as-is.
                detail = str(body.get("detail", body)) if isinstance(body, dict) else str(body)
            for secret in redact:
                if secret:
                    detail = detail.replace(secret, "****")
            raise EngineError(response.status_code, detail[:300])
        return response

    def aisystem(self, project_pid: uuid.UUID) -> dict:
        return self._check(self._send("GET", f"/projects/{project_pid}/aisystem")).json()

    def create_secret(self, project_pid: uuid.UUID, key: str, name: str, value: str) -> str:
        body = {"category": "secrets", "key": key, "name": name, "value": value}
        response = self._send("POST", f"/project/settings/{project_pid}", json=body)
        return self._check(response, redact=(value,)).json()["pid"]

    def delete_secret(self, project_pid: uuid.UUID, config_pid: uuid.UUID) -> None:
        self._check(self._send("DELETE", f"/project/settings/{project_pid}/{config_pid}"))

    def create_component(self, project_pid: uuid.UUID, name: str, component_type: str,
                         json_value: dict) -> str:
        body = {"name": name, "component_type": component_type, "json_value": json_value}
        response = self._send("POST", f"/projects/{project_pid}/components", json=body)
        return self._check(response).json()["pid"]

    def delete_component(self, component_pid: uuid.UUID) -> None:
        self._check(self._send("DELETE", f"/components/{component_pid}"))
