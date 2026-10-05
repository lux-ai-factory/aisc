"""Test helpers for Manage → Connections. Not a test module.

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
    def __init__(self, bind: str = "127.0.0.1"):
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
                # bytes are served as they are (a package index's HTML page), anything else as JSON
                raw = isinstance(payload, bytes)
                data = payload if raw else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html" if raw else "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

        self.server = http.server.ThreadingHTTPServer((bind, 0), H)
        self.port = self.server.server_address[1]
        self.base = f"http://{bind}:{self.port}"
        self.host = f"{bind}:{self.port}"
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


def private_address() -> str | None:
    """This machine's own private, non-loopback IPv4 address (the one it would send from), or None.
    For stubs that must look like an internal system rather than the platform's own loopback."""
    import ipaddress
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))           # TEST-NET: nothing is sent, it only picks a route
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    parsed = ipaddress.ip_address(ip)
    return ip if parsed.is_private and not parsed.is_loopback else None


class EngineFake:
    """The engine's component API as the platform uses it: the engine project
    of a platform project (made on first use, POST /api/v1/projects/for-platform/<pid>, whose pid
    is the engine's own), its components (GET .../aisystem), creating one and renaming one."""

    def __init__(self, stub: Stub, platform_pid: str):
        self.stub, self.platform_pid = stub, str(platform_pid)
        self.engine_pid = str(uuid.uuid4())
        self.components: list[dict] = []
        stub.route("POST", f"/api/v1/projects/for-platform/{self.platform_pid}",
                   (200, lambda r: {"pid": self.engine_pid, "name": "project"}))
        stub.route("GET", f"/api/v1/projects/{self.engine_pid}/aisystem",
                   (200, lambda r: {"pid": str(uuid.uuid4()), "components": [dict(c) for c in self.components]}))
        stub.route("POST", f"/api/v1/projects/{self.engine_pid}/components", (200, self._create))

    def _create(self, request):
        comp = {"pid": str(uuid.uuid4()), "name": request["json"]["name"],
                "component_type": request["json"]["component_type"], "json_value": request["json"].get("json_value")}
        self.components.append(comp)
        self.stub.route("PATCH", f"/api/v1/components/{comp['pid']}", (200, lambda r, c=comp: self._rename(c, r)))
        return comp

    @staticmethod
    def _rename(comp, request):
        comp.update(request["json"])
        return comp

    def named(self, value: str) -> dict | None:
        """The component whose json_value is `value`, if the engine has one."""
        return next((c for c in self.components if (c.get("json_value") or {}).get("value") == value), None)
