"""Spike stub: oauth2-proxy, the platform witness, or an app. Logs every request as one JSON line and,
for apps, answers with what it received."""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROLE = os.environ["ROLE"]; NAME = os.environ.get("NAME", ROLE)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def handle_one(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode(errors="replace") if n else ""
        seen = {"who": NAME, "method": self.command, "path": self.path,
                "headers": {k: v for k, v in self.headers.items()}, "body": body[:200]}
        print(json.dumps(seen), flush=True)
        test = self.headers.get("X-Test", "")
        if ROLE == "auth":
            if "unauth" in test: return self.reply(401, {})
            return self.reply(202, {"X-Auth-Request-User": "alice-sub", "X-Auth-Request-Email": "alice@x",
                                    "X-Auth-Request-Access-Token": "token-of-alice"})
        if ROLE == "platform" and self.path.startswith("/authz/witness"):
            if "witness-down" in test: time.sleep(0); return self.reply(503, {})
            if "witness-401" in test: return self.reply(401, {})
            if "witness-slow" in test: time.sleep(1.5)
            if "witness-noid" in test: return self.reply(200, {})
            return self.reply(200, {"X-AISC-Request-Id": "rid-from-witness"})
        self.reply(200, {"Content-Type": "application/json"}, json.dumps(seen).encode())
    def reply(self, code, headers, body=b""):
        self.send_response(code)
        for k, v in headers.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = handle_one

port = int(os.environ.get("PORT", "8000"))
ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
