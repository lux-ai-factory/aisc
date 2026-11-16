"""One way for a service to call another service of the stack: ServiceClient.

A timeout is always given (there is no default), a redirect is never followed (an answer that points elsewhere
is returned as it is), only a connection that could not be made is tried again (never an answer, whatever its
status), and the request id of the call being served (aisc_identity.logs.request_id) travels on as
X-AISC-Request-Id. Calls to addresses a person configured are not made here: they stay on the guarded transport
of the plugin interface.

Errors, all ServiceError (a RuntimeError):
- ServiceUnreachable: no connection could be made, or it was lost before an answer; a name that does not resolve
  says so, with the host and what to do;
- ServiceTimeout: the service did not answer in time;
- ServiceRefused(status, detail): raised by `checked` for an answer of 4xx or 5xx.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlsplit

import httpx

from aisc_identity import logs

REQUEST_ID_HEADER = "X-AISC-Request-Id"
#: what every call answers with, for a caller's annotations
Response = httpx.Response

#: what an operating system says when a host name has no address
_NO_SUCH_NAME = ("name or service not known", "nodename nor servname", "temporary failure in name resolution",
                 "no address associated with hostname", "getaddrinfo failed", "name does not resolve")
DNS_REMEDY = ("If it resolved before, the stack's DNS is stale: restart this service; otherwise check that the "
              "service runs and its address is right.")


class ServiceError(RuntimeError):
    """A call to another service failed. `cause` names what failed underneath (httpx's error class, such as
    ConnectError or ReadTimeout), for a message that says how; never an address or a credential."""

    def __init__(self, message: str, cause: str | None = None):
        super().__init__(message)
        self.cause = cause or type(self).__name__


class ServiceUnreachable(ServiceError):
    """No connection could be made to the service, or it was lost before an answer."""


class ServiceTimeout(ServiceError):
    """The service did not answer in time."""


class ServiceRefused(ServiceError):
    """The service answered with a 4xx or 5xx status: `status`, and its `detail` when it gave one."""

    def __init__(self, status: int, detail: str | None = None, service: str = "the service",
                 response: httpx.Response | None = None):
        text = f"{service} answered HTTP {status}" + (f": {detail}" if detail else "")
        super().__init__(text, f"HTTP {status}")
        self.status, self.detail, self.response = status, detail, response


def _host(base_url: str) -> str:
    return urlsplit(base_url).hostname or base_url


def _does_not_resolve(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(words in text for words in _NO_SUCH_NAME)


def detail_of(response: httpx.Response, limit: int = 300) -> str | None:
    """The `detail` string of a JSON answer, cut to `limit` characters, or None."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detail[:limit] if isinstance(detail, str) and detail else None


class ServiceClient:
    """Calls to one service at `base_url` (paths are appended to it; a full URL is used as it is).

    `timeout` (seconds, a (connect, read) pair of seconds, or an httpx.Timeout) is required. `token`, when given,
    goes in `token_header`: as `Bearer <token>` in Authorization, as it is in any other header. `retries` are the seconds
    waited before each new try of a call whose connection could not be made; an answer is never tried again.
    `service` names the service in errors (default: its host)."""

    def __init__(self, base_url: str, *, timeout, token: str | None = None, token_header: str = "Authorization",
                 retries: tuple[float, ...] = (), service: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token, self.token_header = token, token_header
        self.retries = tuple(retries)
        self.host = _host(base_url)
        self.service = service or self.host

    def _timeout(self, timeout):
        """httpx's timeout from seconds, httpx's own, or a (connect, read) pair."""
        timeout = self.timeout if timeout is None else timeout
        if isinstance(timeout, tuple) and len(timeout) == 2:
            return httpx.Timeout(timeout[1], connect=timeout[0])
        return timeout

    def url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return self.base_url + (path if path.startswith("/") or not path else "/" + path)

    def headers(self, extra: dict | None = None) -> dict:
        """The call's headers: the token, the request id being served, then `extra`, where a None value takes
        that header out (a caller that must not cite the request it serves names X-AISC-Request-Id as None)."""
        out = {}
        if self.token:
            out[self.token_header] = f"Bearer {self.token}" if self.token_header.lower() == "authorization" \
                else self.token
        request_id = logs.request_id.get()
        if request_id:
            out[REQUEST_ID_HEADER] = request_id
        for name, value in (extra or {}).items():
            out = {k: v for k, v in out.items() if k.lower() != name.lower()}
            if value is not None:
                out[name] = value
        return out

    def request(self, method: str, path: str, *, headers: dict | None = None, timeout=None,
                **kwargs) -> httpx.Response:
        """One call; see the class. `kwargs` are httpx's (json, data, files, params, content)."""
        url = self.url(path)
        waits = list(self.retries)
        while True:
            try:
                with httpx.Client(follow_redirects=False) as http:
                    return http.request(method, url, headers=self.headers(headers), timeout=self._timeout(timeout),
                                        **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if waits:
                    time.sleep(waits.pop(0))
                    continue
                raise self._failure(exc) from None
            except httpx.RequestError as exc:
                raise self._failure(exc) from None

    @contextmanager
    def stream(self, method: str, path: str, *, headers: dict | None = None, timeout=None,
               **kwargs) -> Iterator[httpx.Response]:
        """One call whose answer is read as it arrives (`response.iter_bytes()` inside the block). Not tried
        again; a failure while the body arrives raises as one before it."""
        try:
            with httpx.Client(follow_redirects=False) as http:
                with http.stream(method, self.url(path), headers=self.headers(headers), timeout=self._timeout(timeout),
                                 **kwargs) as response:
                    yield response
        except httpx.RequestError as exc:
            raise self._failure(exc) from None

    def _failure(self, exc: httpx.RequestError) -> ServiceError:
        cause = type(exc).__name__
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            if _does_not_resolve(exc):
                return ServiceUnreachable(f"cannot resolve {self.host}: {DNS_REMEDY}", cause)
            return ServiceUnreachable(f"cannot reach {self.service} ({cause})", cause)
        if isinstance(exc, httpx.TimeoutException):
            return ServiceTimeout(f"{self.service} did not answer in time ({cause})", cause)
        return ServiceUnreachable(f"the connection to {self.service} failed ({cause})", cause)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    def checked(self, response: httpx.Response) -> httpx.Response:
        """`response`, or ServiceRefused for a 4xx or 5xx answer (its detail, never the address)."""
        if response.status_code >= 400:
            raise ServiceRefused(response.status_code, detail_of(response), self.service, response)
        return response
