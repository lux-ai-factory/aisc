"""Test helpers for the per-project LLM keys.

Not a test module. A fake HTTP server on 127.0.0.1 that records every request and
serves canned answers, so no test reaches a real provider or uses a real key, and
the Fernet keys the suite encrypts with.

Test API keys look like `sk-test-<hex>`, so a leak anywhere is greppable.
"""
from __future__ import annotations

import http.server
import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet

#: One Fernet key for the whole session, so every stored key the suite writes can be
#: read by every later test (the rotation test re-encrypts every project's keys).
SECRETS_KEY = Fernet.generate_key().decode()
INTERNAL_TOKEN = "pytest-internal-" + uuid.uuid4().hex  # the card agent's
#: the risk mapper's: each agentic system has a token of its own and resolves only itself
RISK_TOKEN = "pytest-risk-" + uuid.uuid4().hex


def new_key() -> str:
    return "sk-test-" + uuid.uuid4().hex


@dataclass
class Seen:
    method: str
    path: str
    query: dict
    headers: dict
    body: bytes = b""

    def header(self, name: str) -> str | None:
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return None


@dataclass
class Canned:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    delay: float = 0.0


class FakeServer:
    """`reply(path, ...)` sets the answer for GET (or `method`) on a path, the query
    string ignored for matching. A callable answer gets the Seen request and returns a
    Canned. Anything unrouted is 404 with a body the tests grep for."""

    UNROUTED = b"FAKE-SERVER-UNROUTED-BODY"

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.requests: list[Seen] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                seen = Seen(self.command, parts.path, parse_qs(parts.query),
                            dict(self.headers.items()), body)
                fake.requests.append(seen)
                answer = fake.routes.get((self.command, parts.path))
                if answer is None:
                    canned = Canned(404, fake.UNROUTED)
                elif callable(answer):
                    canned = answer(seen)
                else:
                    canned = answer
                if canned.delay:
                    time.sleep(canned.delay)
                try:
                    self.send_response(canned.status)
                    headers = {"Content-Type": "application/json", **canned.headers}
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(canned.body)))
                    self.end_headers()
                    self.wfile.write(canned.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = do_POST = do_PUT = do_DELETE = _serve

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reply(self, path, body=None, status=200, headers=None, method="GET", delay=0.0, raw=None):
        if callable(body):
            self.routes[(method, path)] = body
            return
        data = raw if raw is not None else json.dumps(body if body is not None else {}).encode()
        self.routes[(method, path)] = Canned(status, data, headers or {}, delay)

    def seen(self, path=None) -> list[Seen]:
        return [r for r in self.requests if path is None or r.path == path]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def closed_port_url() -> str:
    """A URL nothing listens on: 'the provider is down'."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def field_of(entry, name):
    """A catalogue entry's field, whether the entry is a mapping or an object."""
    if isinstance(entry, dict):
        return entry[name]
    return getattr(entry, name)
