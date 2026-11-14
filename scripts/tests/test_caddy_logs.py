"""Caddy's logs never hold the access token that forward_auth copies onto proxied requests.

`(strip-and-sign-in)` copies X-Auth-Request-Access-Token from oauth2-proxy's answer onto every request it
passes on, and Caddy writes request headers into its access log and into the error it logs when an upstream
fails mid-response. A global log filter, first in the file, deletes that header, and each site's access log
uses the same filter.

The repo's own Caddyfile runs in a throwaway caddy:2.10.2 with stub upstreams written here: a sign-in stub
that answers with a fake JWT-shaped token and an engine stub that promises a body and closes the connection
early. Its own network and containers (aisc-t-caddylog-*); never the running stack. Nothing printed is a real
secret: the token is made up.
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest

from conftest import ROOT

CADDYFILE = ROOT / "Caddyfile"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhbGljZS10ZXN0In0.c2lnbmF0dXJlLXRlc3Q"
TOKEN_SHAPE = re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}")
HEADER = "X-Auth-Request-Access-Token"

STUB = '''
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROLE = os.environ["ROLE"]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def handle_one(self):
        if ROLE == "auth":
            self.send_response(202)
            self.send_header("X-Auth-Request-User", "alice-sub")
            self.send_header("X-Auth-Request-Email", "alice@example.org")
            self.send_header("X-Auth-Request-Access-Token", os.environ["TOKEN"])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if ROLE == "platform":
            self.send_response(200)
            self.send_header("X-AISC-Request-Id", "rid-from-witness")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # the engine: promises a long body, sends ten bytes and hangs up
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "100000")
        self.end_headers()
        self.wfile.write(b"0123456789")
        self.wfile.flush()
        self.close_connection = True
        self.connection.shutdown(2)
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = handle_one

ThreadingHTTPServer(("0.0.0.0", int(os.environ["PORT"])), H).serve_forever()
'''
STUBS = [("auth", "oauth2-proxy", "auth", 4180), ("platform", "platform", "platform", 8000),
         ("backend", "aisc-backend", "app", 8000)]


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _leading_global_block(text: str) -> tuple[str, str]:
    """The global options block when it is the file's first block (comments before it allowed), and the rest."""
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i == len(lines) or lines[i].strip() != "{":
        return "", text
    depth = 0
    for j in range(i, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth == 0:
            return "".join(lines[: j + 1]), "".join(lines[j + 1:])
    return "", text


def _caddyfile_for_logs(text: str) -> str:
    """The file as a throwaway runs it: the test TLS snippet after the global block, never before it."""
    head, rest = _leading_global_block(text)
    return head + "\n(tls-test) {\n}\n" + rest


def test_the_caddyfile_starts_with_a_global_block_that_drops_the_token_from_logs():
    head, _ = _leading_global_block(CADDYFILE.read_text())
    assert head, "the Caddyfile has no global options block first"
    assert re.search(r"request>headers>" + HEADER + r"\s+delete", head), \
        "the global log does not delete the access token header"


def test_every_site_log_filters_the_token_header():
    _, rest = _leading_global_block(CADDYFILE.read_text())
    blocks = re.findall(r"\n\s*log \{(.*?)\n\s{2}\}", rest, re.S)
    assert blocks, "no site log block found"
    unfiltered = [n for n, block in enumerate(blocks, 1) if HEADER not in block]
    assert not unfiltered, f"site log blocks {unfiltered} keep the access token header"


@pytest.fixture(scope="module")
def caddy(tmp_path_factory):
    if not shutil.which("docker") or docker("info", check=False).returncode != 0:
        pytest.fail("docker is not available")
    tag = f"aisc-t-caddylog-{uuid.uuid4().hex[:6]}"
    work = tmp_path_factory.mktemp("caddy-logs")
    (work / "Caddyfile").write_text(_caddyfile_for_logs(CADDYFILE.read_text()))
    (work / "homepage").mkdir()
    (work / "stub.py").write_text(STUB)
    ports = {"main": _free_port(), "launcher": _free_port(), "dashboard": _free_port()}
    docker("network", "create", tag)
    names = []
    try:
        for name, alias, role, port in STUBS:
            names.append(f"{tag}-{name}")
            docker("run", "-d", "--name", names[-1], "--network", tag, "--network-alias", alias,
                   "-e", f"ROLE={role}", "-e", f"PORT={port}", "-e", f"TOKEN={TOKEN}",
                   "-v", f"{work}/stub.py:/stub.py:ro", "python:3.12-slim", "python", "-u", "/stub.py")
        env = {"CADDY_DOMAIN": "http://localhost", "CADDY_PORT": ports["main"], "HOMEPAGE_PORT": ports["launcher"],
               "DASHBOARD_PORT": ports["dashboard"], "CADDY_ENVIRONMENT": "test", "LOG_FILE": "/tmp/caddy.log",
               "DASHBOARD_UPSTREAM": "dashboard-up:8088", "AISC_WITNESS_GATEWAY_SECRET": "gw-test-secret-0123456789",
               "LEDGER_GATEWAY": "on"}
        names.append(f"{tag}-caddy")
        published = [a for p in ports.values() for a in ("-p", f"127.0.0.1:{p}:{p}")]
        envs = [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
        docker("run", "-d", "--name", names[-1], "--network", tag, *published, *envs, "-v", f"{work}:/w:ro",
               "-v", f"{work}/homepage:/srv/homepage:ro", "caddy:2.10.2",
               "caddy", "run", "--config", "/w/Caddyfile", "--adapter", "caddyfile")
        for _ in range(100):
            if "serving initial configuration" in docker("logs", names[-1], check=False).stderr:
                break
            if docker("inspect", "-f", "{{.State.Running}}", names[-1], check=False).stdout.strip() != "true":
                pytest.fail("caddy did not start:\n" + docker("logs", names[-1], check=False).stderr[-2000:])
            time.sleep(0.2)
        time.sleep(1)
        yield {"caddy": names[-1], "port": ports["main"]}
    finally:
        for name in names:
            docker("rm", "-fv", name, check=False)
        docker("network", "rm", tag, check=False)


def test_an_aborted_response_logs_no_token_shaped_value(caddy):
    port = caddy["port"]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/project/abc", method="GET",
                                 headers={"Host": f"localhost:{port}"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:  # noqa: BLE001 - the stub hangs up mid-body on purpose
        pass
    time.sleep(1)
    logs = docker("logs", caddy["caddy"], check=False)
    text = logs.stdout + logs.stderr + docker("exec", caddy["caddy"], "cat", "/tmp/caddy.log", check=False).stdout
    assert "/api/v1/project/abc" in text, "the request was not logged at all: the check saw nothing"
    found = len(TOKEN_SHAPE.findall(text))
    assert found == 0, f"{found} token-shaped values in Caddy's logs"
    assert HEADER not in text, "the access token header is named in Caddy's logs"
