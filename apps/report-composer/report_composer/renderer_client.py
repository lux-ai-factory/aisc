"""The composer's side of the renderer (report run 2026-09-23, R5.4, R7.2.2).

The renderer is internal: only this client talks to it, with the shared token, which never
appears in a representation, a log line or an answer.
"""
from __future__ import annotations

import httpx


class RendererError(Exception):
    """The renderer could not answer."""


class RendererUnavailable(RendererError):
    """Not reachable, or it answered with an error of its own."""


class RendererTimeout(RendererError):
    """No answer in time."""


class RendererRejected(RendererError):
    """The renderer refused the request (404 or 422)."""

    def __init__(self, status: int, problems=None, message=""):
        self.status = status
        self.problems = problems or []
        super().__init__(message or f"renderer answered {status}")


class HttpRendererClient:
    def __init__(self, base_url, token, timeout=120.0):
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self.__token = token

    def __repr__(self):
        return f"HttpRendererClient({self.base_url!r})"

    def _call(self, method: str, path: str, json=None):
        try:
            with httpx.Client(timeout=self.timeout) as http:
                r = http.request(method, self.base_url + path, json=json, headers={"X-Report-Token": self.__token})
        except httpx.TimeoutException:
            raise RendererTimeout(f"no answer within {self.timeout:g} s") from None
        except httpx.HTTPError as exc:
            raise RendererUnavailable(f"renderer not reachable ({type(exc).__name__})") from None
        if r.status_code in (404, 422):
            try:
                body = r.json()
            except ValueError:
                body = {}
            raise RendererRejected(r.status_code, body.get("problems") if isinstance(body, dict) else None)
        if r.status_code >= 400:          # 401, 5xx and anything else unexpected
            raise RendererUnavailable(f"renderer answered {r.status_code}")
        return r.json()

    def block_types(self) -> list:
        return self._call("GET", "/v1/block-types")

    def choices(self, project_id, system_id, block_type) -> dict:
        return self._call("POST", "/v1/choices", {"project_id": str(project_id), "system_id": str(system_id),
                                                  "block_type": block_type})

    def render(self, snapshot) -> dict:
        return self._call("POST", "/v1/render", snapshot)
