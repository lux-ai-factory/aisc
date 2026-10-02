"""G1-G8: the gateway on a real Caddy (I1, I6, T18, T19; spec 3.1, 5.3; R5.1). The repo's own
Caddyfile runs in a throwaway caddy:2.10.2 with stub upstreams that echo what they receive (the
spike's setup, 06-spike.md), changed only where it must be: oauth2-proxy's address, TLS, ports. Never
touches the running stack: its own network and containers, aisc-t-gw-*.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from conftest import ROOT

FIXTURES = ROOT / "scripts/tests/fixtures/ledger_gateway"
#: LEDGER_TEST_CADDYFILE runs another file (a reference implementation of spec 3.1).
CADDYFILE = Path(os.environ.get("LEDGER_TEST_CADDYFILE", ROOT / "Caddyfile"))
REQUIRED = os.environ.get("LEDGER_TESTS_REQUIRED") == "1"
SECRET = "gw-test-secret-0123456789"
PORTS = {"main": 28080, "launcher": 28100, "dashboard": 28088}
STUBS = [("auth", "auth", "auth", 4180), ("platform", "platform", "platform", 8000),
         ("backend", "aisc-backend", "app", 8000), ("flower", "aisc-eval-flower", "app", 5555),
         ("controls", "controls-web", "app", 3000), ("qualification", "qualification-web", "app", 3000),
         ("co", "control-objectives", "app", 8090), ("composer", "report-composer", "app", 8095),
         ("webapp", "aisc-webapp", "app", 80), ("pgadmin", "pgadmin", "app", 80),
         ("schema", "schema-docs", "app", 8080), ("dashboard", "dashboard-up", "app", 8088)]


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def caddyfile_for_test(text: str) -> str:
    text = text.replace("host.docker.internal:4180", "auth:4180")
    return "(tls-test) {\n}\n" + text


@pytest.fixture(scope="module", params=["on", "off"])
def gateway(request, tmp_path_factory):
    if not shutil.which("docker") or docker("info", check=False).returncode != 0:
        if REQUIRED:
            pytest.fail("LEDGER_TESTS_REQUIRED=1 but docker is not available")
        pytest.skip("docker is not available")
    tag = f"aisc-t-gw-{uuid.uuid4().hex[:6]}"
    work = tmp_path_factory.mktemp("gateway")
    (work / "Caddyfile").write_text(caddyfile_for_test(CADDYFILE.read_text()))
    (work / "homepage").mkdir()
    for page in ("index.html", "project.html"):
        (work / "homepage" / page).write_text(page)
    shutil.copy(FIXTURES / "stub.py", work / "stub.py")
    docker("network", "create", tag)
    names = []
    try:
        for name, alias, role, port in STUBS:
            names.append(f"{tag}-{name}")
            docker("run", "-d", "--name", names[-1], "--network", tag, "--network-alias", alias, "-e", f"ROLE={role}",
                   "-e", f"NAME={name}", "-e", f"PORT={port}", "-v", f"{work}/stub.py:/stub.py:ro",
                   "python:3.12-slim", "python", "-u", "/stub.py")
        env = {"CADDY_DOMAIN": "http://localhost", "CADDY_PORT": PORTS["main"], "HOMEPAGE_PORT": PORTS["launcher"],
               "DASHBOARD_PORT": PORTS["dashboard"], "CADDY_ENVIRONMENT": "test", "LOG_FILE": "/tmp/caddy.log",
               "DASHBOARD_UPSTREAM": "dashboard-up:8088", "AISC_WITNESS_GATEWAY_SECRET": SECRET,
               "LEDGER_GATEWAY": request.param}
        names.append(f"{tag}-caddy")
        ports = [a for p in PORTS.values() for a in ("-p", f"127.0.0.1:{p}:{p}")]
        envs = [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
        docker("run", "-d", "--name", names[-1], "--network", tag, *ports, *envs, "-v", f"{work}:/w:ro",
               "-v", f"{work}/homepage:/srv/homepage:ro", "caddy:2.10.2",
               "caddy", "run", "--config", "/w/Caddyfile", "--adapter", "caddyfile")
        for _ in range(50):
            if docker("logs", names[-1], check=False).stderr.count("serving initial configuration"):
                break
            if docker("inspect", "-f", "{{.State.Running}}", names[-1], check=False).stdout.strip() != "true":
                pytest.fail("caddy did not start:\n" + docker("logs", names[-1], check=False).stderr[-2000:])
            time.sleep(0.2)
        yield {"tag": tag, "mode": request.param}
    finally:
        for name in names:
            docker("rm", "-f", name, check=False)
        docker("network", "rm", tag, check=False)


def send(gw, site, method, path, headers=None, body=None):
    """One request through Caddy: (status, what the app got or None, what the witness got or None)."""
    tid = uuid.uuid4().hex
    headers = {"X-Test-Id": tid, **(headers or {})}
    port = PORTS[site]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=body,
                                 headers={"Host": f"localhost:{port}", **headers})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        r = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
        status, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode()
    logs = docker("logs", f"{gw['tag']}-platform", check=False).stdout.splitlines()
    witness = [json.loads(line) for line in logs if tid in line and '"/authz/witness' in line]
    try:
        app = json.loads(text)
    except ValueError:
        app = None
    return status, app, (witness[0] if witness else None)


WRITES = [
    ("main", "/api/v1/project/abc", "engine", "backend"),
    ("main", "/controls/p/mcas/submissions/s1", "controls", "controls"),
    ("main", "/qualification/p/mcas/qualify/new", "qualification", "qualification"),
    ("main", "/control-objectives/p/PID/api/projects/a1/ratings", "control_objectives", "co"),
    ("main", "/report-composer/p/mcas/layouts", "report_composer", "composer"),
    ("launcher", "/api/projects/mcas/members", "platform", "platform"),
    ("dashboard", "/api/v1/chart/", "dashboard", "dashboard"),
]


@pytest.mark.parametrize("site, path, app, upstream", WRITES)
def test_a_write_is_witnessed_with_its_app_and_unstripped_path(gateway, site, path, app, upstream):
    status, got, witness = send(gateway, site, "POST", path, body=b"{}")
    assert status == 200 and got["who"] == upstream
    if gateway["mode"] == "off":
        assert witness is None and "X-Aisc-Request-Id" not in got["headers"]
        return
    h = witness["headers"]
    assert (h.get("X-Aisc-App"), h.get("X-Aisc-Original-Uri"), h.get("X-Aisc-Gateway")) == (app, path, SECRET)
    assert h.get("X-Auth-Request-Access-Token") == "token-of-alice"      # sign-in ran first (G7)
    assert got["headers"].get("X-Aisc-Request-Id") == "rid-from-witness"


def test_a_read_is_not_witnessed(gateway):
    status, got, witness = send(gateway, "main", "GET", "/qualification/_next/static/chunk.js")
    assert status == 200 and witness is None


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_forged_headers_never_reach_an_app(gateway, method):
    forged = {"X-AISC-Request-Id": "FORGED", "X-AISC-App": "platform", "X-AISC-Gateway": "guess",
              "X-AISC-Original-Uri": "/evil", "X-Auth-Request-Preferred-Username": "mallory"}
    status, got, _ = send(gateway, "main", method, "/qualification/p/mcas/x", forged,
                          b"{}" if method == "POST" else None)
    seen = got["headers"]
    assert seen.get("X-Aisc-Request-Id") in (None, "rid-from-witness")
    for name in ("X-Aisc-App", "X-Aisc-Gateway", "X-Aisc-Original-Uri", "X-Auth-Request-Preferred-Username"):
        assert name not in seen, name


def test_the_engines_project_header_is_kept(gateway):
    _, got, _ = send(gateway, "main", "PATCH", "/api/v1/project/abc", {"X-AISC-Project": "PID"}, b"{}")
    assert got["headers"].get("X-Aisc-Project") == "PID"


def test_the_launcher_never_serves_the_witness(gateway):
    status, _, _ = send(gateway, "launcher", "GET", "/api/authz/witness",
                        {"X-Forwarded-Method": "POST", "X-Forwarded-Uri": "/control-objectives/p/OTHER/x"})
    assert status == 404


def test_with_the_platform_down_reads_work_and_writes_fail_only_with_the_witness_on(gateway):
    name = f"{gateway['tag']}-platform"
    docker("stop", name)
    try:
        assert send(gateway, "main", "GET", "/qualification/_next/static/chunk.js")[0] == 200
        expected = 502 if gateway["mode"] == "on" else 200          # off: nothing depends on the platform (R6.4)
        assert send(gateway, "main", "POST", "/qualification/p/mcas/x", body=b"{}")[0] == expected
    finally:
        docker("start", name)
        time.sleep(1)


def test_a_refused_page_load_is_sent_to_sign_in(gateway):
    """The witness answers a refused document load with a 302; forward_auth passes it through (R1.12)."""
    status, _, _ = send(gateway, "main", "POST", "/qualification/p/mcas/x",
                        {"X-Test": "witness-401", "Sec-Fetch-Dest": "document"}, b"{}")
    assert status == (302 if gateway["mode"] == "on" else 200)
    status, _, _ = send(gateway, "main", "POST", "/qualification/p/mcas/x", {"X-Test": "witness-401"}, b"{}")
    assert status == (401 if gateway["mode"] == "on" else 200)


def test_a_listed_read_that_matters_is_witnessed(gateway):
    """spec 3.1 `import protect-reads <app> <path>...` (S1: {args[1:]} works on Caddy 2.10.2)."""
    reads = re.findall(r"^\s*import protect-reads (\S+) (.+)$", CADDYFILE.read_text(), re.M)
    assert reads, "no handle imports protect-reads"
    app, paths = reads[0][0], reads[0][1].split()
    prefix = {"qualification": "", "controls": "", "control_objectives": "/control-objectives",
              "report_composer": "/report-composer"}.get(app, "")
    path = prefix + paths[0].replace("*", "x")
    site = "main"
    _, _, witness = send(gateway, site, "GET", path)
    if gateway["mode"] == "off":
        assert witness is None
    else:
        assert witness and witness["headers"].get("X-Aisc-App") == app
