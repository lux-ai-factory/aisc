"""Test helpers for Manage → Connections (connections plan 2026-09-29). Not a test module.

A local HTTP stub that records requests and serves canned answers per path: it stands in for the
system under test (the Test button) and for the engine (the component the platform mirrors)."""
from __future__ import annotations

import http.server
import json
import threading
import uuid

from cryptography.fernet import Fernet

SECRETS_KEY = Fernet.generate_key().decode()
CONNECTIONS_TOKEN = "pytest-" + "connections-" + uuid.uuid4().hex


def new_secret() -> str:
    return "sk-test-" + uuid.uuid4().hex


class Stub:
    def __init__(self):
        self.routes, self.seen = {}, []
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                stub.seen.append({"method": self.command, "path": self.path,
                                  "headers": {k.lower(): v for k, v in self.headers.items()},
                                  "json": json.loads(body) if body else None})
                plan = stub.routes.get((self.command, self.path.split("?")[0])) or [(404, {"detail": "no route"})]
                status, payload = plan.pop(0) if len(plan) > 1 else plan[0]
                if callable(payload):
                    payload = payload(stub.seen[-1])
                data = json.dumps(payload).encode()
                self.send_response(status); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def route(self, method, path, *responses):
        self.routes[(method, path)] = list(responses)

    def requests(self, method=None, prefix=""):
        return [r for r in self.seen if (method is None or r["method"] == method) and r["path"].startswith(prefix)]

    def stop(self):
        self.server.shutdown()


def engine_component(stub: Stub, pid: str):
    """Make the stub answer the engine's create/patch component routes like the engine does."""
    made = {"pid": str(uuid.uuid4())}
    stub.route("POST", f"/api/v1/projects/{pid}/components",
               (200, lambda r: {"pid": made["pid"], "name": r["json"]["name"], "component_type": "resource",
                                "json_value": r["json"]["json_value"]}))
    stub.route("PATCH", f"/api/v1/components/{made['pid']}", (200, lambda r: {"pid": made["pid"], **r["json"]}))
    return made
