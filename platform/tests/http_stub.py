"""The suite's one local HTTP stub. Not a test module.

A server on 127.0.0.1 (or `bind`) that records every request and serves canned answers per method
and path, the query string ignored for matching. It stands in for an LLM provider (FakeServer), for
the system under test, the engine and the catalogues (Stub), and for the dashboard bridge.

An answer is a `Canned`, a `(status, payload)` pair (bytes are served as they are, as text/html,
anything else as JSON); the answer, or a pair's payload, may be a callable that gets the `Seen` request. A path given
several answers serves them in order and then keeps serving the last. A request nobody routed gets
`default`. `delay` holds every answer back that many seconds (a hanging server).
"""
from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit


@dataclass
class Seen:
    """A request as it arrived. `.path` is the path alone; `seen["path"]` the path with its query."""

    method: str
    target: str
    headers: dict
    body: bytes = b""

    @property
    def path(self) -> str:
        return urlsplit(self.target).path

    @property
    def query(self) -> dict:
        return parse_qs(urlsplit(self.target).query)

    @property
    def json(self):
        return json.loads(self.body) if self.body else None

    def header(self, name: str) -> str | None:
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), None)

    def __getitem__(self, key: str):
        return {"method": self.method, "path": self.target, "json": self.json,
                "headers": {k.lower(): v for k, v in self.headers.items()}}[key]


@dataclass
class Canned:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    delay: float = 0.0


def _canned(answer, seen) -> Canned:
    if callable(answer):
        answer = answer(seen)
    if isinstance(answer, Canned):
        return answer
    status, payload = answer
    if callable(payload):
        payload = payload(seen)
    if isinstance(payload, bytes):
        return Canned(status, payload, {"Content-Type": "text/html"})
    return Canned(status, json.dumps(payload).encode())


class HttpStub:
    protocol_version = "HTTP/1.0"

    def __init__(self, bind: str = "127.0.0.1", default=(404, {"detail": "no route"}), delay: float = 0.0):
        self.routes: dict[tuple[str, str], list] = {}
        self.log: list[Seen] = []
        self.default, self.delay = default, delay
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = stub.protocol_version

            def _serve(self):
                n = int(self.headers.get("Content-Length") or 0)
                seen = Seen(self.command, self.path, dict(self.headers.items()), self.rfile.read(n) if n else b"")
                stub.log.append(seen)
                plan = stub.routes.get((self.command, seen.path)) or [stub.default]
                answer = plan.pop(0) if len(plan) > 1 else plan[0]
                canned = _canned(answer, seen)
                if canned.delay or stub.delay:
                    time.sleep(canned.delay or stub.delay)
                try:
                    self.send_response(canned.status)
                    for k, v in {"Content-Type": "application/json", **canned.headers}.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(canned.body)))
                    self.end_headers()
                    self.wfile.write(canned.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer((bind, 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = self.base = f"http://{bind}:{self.port}"
        self.host = f"{bind}:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def route(self, method, path, *answers):
        self.routes[(method, path)] = list(answers)

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    stop = close


class Stub(HttpStub):
    """`route(method, path, *answers)`; `seen` is every request, `requests(method, prefix)` a filter."""

    @property
    def seen(self) -> list[Seen]:
        return self.log

    def requests(self, method=None, prefix=""):
        return [r for r in self.log if (method is None or r.method == method) and r.target.startswith(prefix)]


class FakeServer(HttpStub):
    """An LLM provider: `reply(path, ...)` sets the answer for GET (or `method`) on a path; `requests`
    is every request, `seen(path)` those on one path. Anything unrouted is 404 with a body the tests
    grep for."""

    protocol_version = "HTTP/1.1"
    UNROUTED = b"FAKE-SERVER-UNROUTED-BODY"

    def __init__(self):
        super().__init__(default=Canned(404, self.UNROUTED))

    @property
    def requests(self) -> list[Seen]:
        return self.log

    def reply(self, path, body=None, status=200, headers=None, method="GET", delay=0.0, raw=None):
        if callable(body):
            self.route(method, path, body)
            return
        data = raw if raw is not None else json.dumps(body if body is not None else {}).encode()
        self.route(method, path, Canned(status, data, headers or {}, delay))

    def seen(self, path=None) -> list[Seen]:
        return [r for r in self.log if path is None or r.path == path]


def closed_port_url() -> str:
    """A URL nothing listens on: a server that is down."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"
