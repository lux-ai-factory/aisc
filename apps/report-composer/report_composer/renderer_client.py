"""The composer's side of the renderer.

The renderer is internal: only this client talks to it, with the shared token, which never
appears in a representation, a log line or an answer.
"""
from __future__ import annotations

import json as jsonlib
import threading
import time

import httpx


class RendererError(Exception):
    """The renderer could not answer."""


class RendererUnavailable(RendererError):
    """Not reachable, or it answered with an error of its own."""


class RendererTimeout(RendererError):
    """No answer in time."""


class RendererTooLarge(RendererError):
    """The snapshot is over the renderer's size cap (413, REPORT_RENDER_MAX_BYTES)."""


class RendererBusy(RendererError):
    """Every render slot of the renderer is taken (503 busy, REPORT_RENDER_CONCURRENCY); nothing was rendered,
    so the same request may be sent again shortly."""


class RendererRejected(RendererError):
    """The renderer refused the request (404 or 422)."""

    def __init__(self, status: int, problems=None, message=""):
        self.status = status
        self.problems = problems or []
        super().__init__(message or f"renderer answered {status}")


class HttpRendererClient:
    def __init__(self, base_url, token, timeout=120.0, quick_timeout=2.0):
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self.quick_timeout = quick_timeout    # for calls made while the user edits (the outline)
        self.__token = token

    def __repr__(self):
        return f"HttpRendererClient({self.base_url!r})"

    def _call(self, method: str, path: str, json=None, timeout=None, deadline=None):
        """One call. `timeout` limits each network step; `deadline` (a time.monotonic() value), when given, also
        ends the call once passed while the answer's body is still arriving."""
        timeout = self.timeout if timeout is None else timeout
        headers = {"X-Report-Token": self.__token}
        try:
            with httpx.Client(timeout=timeout) as http:
                if deadline is None:
                    r = http.request(method, self.base_url + path, json=json, headers=headers)
                    return self._answer(r.status_code, r.content)
                with http.stream(method, self.base_url + path, json=json, headers=headers) as r:
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        if time.monotonic() > deadline:
                            raise RendererTimeout("the answer did not arrive in time")
                        body += chunk
                    return self._answer(r.status_code, bytes(body))
        except httpx.TimeoutException:
            raise RendererTimeout(f"no answer within {timeout:g} s") from None
        except httpx.HTTPError as exc:
            raise RendererUnavailable(f"renderer not reachable ({type(exc).__name__})") from None

    @staticmethod
    def _answer(status: int, content: bytes):
        def parsed():
            return jsonlib.loads(content)

        if status in (404, 422):
            try:
                body = parsed()
            except ValueError:
                body = {}
            raise RendererRejected(status, body.get("problems") if isinstance(body, dict) else None)
        if status == 413:
            raise RendererTooLarge("renderer answered 413")
        if status == 503:
            try:
                body = parsed()
            except ValueError:
                body = {}
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict) and error.get("code") == "busy":
                raise RendererBusy("renderer answered 503 busy")
        if status >= 400:          # 401, 5xx and anything else unexpected
            raise RendererUnavailable(f"renderer answered {status}")
        try:
            return parsed()
        except ValueError:         # e.g. a proxy's HTML page: not the renderer's answer
            raise RendererUnavailable("renderer answered something that is not JSON") from None

    def _call_within(self, seconds: float, method: str, path: str, json=None):
        """The call with a deadline for the whole of it: the caller gets an
        answer or RendererTimeout after at most `seconds`, even from a renderer that sends its answer byte by
        byte. The call runs in a helper thread, which itself stops at the next piece of body after the
        deadline, or at the next per-step timeout."""
        end = time.monotonic() + seconds
        done, out = threading.Event(), {}

        def work():
            try:
                out["value"] = self._call(method, path, json, timeout=seconds, deadline=end)
            except BaseException as exc:  # noqa: BLE001 - handed to the caller below
                out["error"] = exc
            finally:
                done.set()

        threading.Thread(target=work, name="renderer-quick-call", daemon=True).start()
        if not done.wait(seconds):
            raise RendererTimeout(f"no answer within {seconds:g} s")
        if "error" in out:
            raise out["error"]
        return out["value"]

    def block_types(self) -> list:
        return self._call("GET", "/v1/block-types")

    def block_types_quick(self) -> list:
        """The block types within the short deadline: the outline route must not wait long for them."""
        return self._call_within(self.quick_timeout, "GET", "/v1/block-types")

    def fonts(self) -> list:
        return self._call("GET", "/v1/fonts")

    def choices(self, project_id, system_id, block_type) -> dict:
        return self._call("POST", "/v1/choices", {"project_id": str(project_id), "system_id": str(system_id),
                                                  "block_type": block_type})

    def render(self, snapshot) -> dict:
        return self._call("POST", "/v1/render", snapshot)
