"""Where the launcher's links go.

The engine, Keycloak and the dashboard each have an address set by the install (API_URL_EXTERNAL,
KEYCLOAK_URL_EXTERNAL, DASHBOARD_EXTERNAL_URL). The launcher's pages used to name http://localhost,
so a second copy on other ports, or staging, sent people to the first copy's apps. Now:
- the gateway serves the install's addresses at /origins.json on the launcher's origin;
- homepage/assets/origins.js reads them and sets every link marked data-origin, and until the gateway
  answers (or when it cannot) it uses this host's defaults;
- no page names localhost.
"""
import json
import re
import shutil
import subprocess
import time

import pytest

from conftest import ROOT

ORIGINS_JS = ROOT / "homepage/assets/origins.js"
PAGES = sorted((ROOT / "homepage").glob("*.html"))


def test_no_launcher_page_names_localhost():
    named = [p.name for p in PAGES + sorted((ROOT / "homepage/assets").glob("*.js")) if "localhost" in p.read_text()]
    assert not named, f"these pages name localhost: {named}"


@pytest.mark.parametrize("page", ["index.html", "project.html", "evidence.html"])
def test_the_pages_with_app_links_read_the_origins(page):
    html = (ROOT / "homepage" / page).read_text()
    assert '<script src="/assets/origins.js"></script>' in html
    assert "data-origin=" in html or "aiscLink(" in html or "aiscOrigin(" in html


_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, answer] = process.argv.slice(2);
const links = [
  {dataset: {origin: 'engine', path: '/flower/'}, href: ''},
  {dataset: {origin: 'keycloak', path: '/realms/aisc/account'}, href: ''},
  {dataset: {origin: 'dashboard', path: '/'}, href: ''},
];
const later = {dataset: {}, href: ''};
const fetch = () => answer === 'down' ? Promise.reject(new Error('down'))
  : Promise.resolve({ok: answer !== '404', json: () => Promise.resolve(JSON.parse(answer))});
const window = {};
const ctx = {window, fetch, location: {protocol: 'http:', hostname: 'example.test', port: '9100'},
             document: {querySelectorAll: (s) => s === '[data-origin]' ? links.concat(later.dataset.origin ? [later] : []) : []}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
const before = links.map(l => l.href);
window.aiscLink(later, 'engine', '/controls/p/abc');
window.aiscOriginsReady.then(() => {
  console.log(JSON.stringify({before, after: links.map(l => l.href), later: later.href,
                              engine: window.aiscOrigin('engine')}));
});
"""


def _run(tmp_path, answer):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    assert ORIGINS_JS.is_file(), "missing feature: homepage/assets/origins.js"
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    r = subprocess.run(["node", str(harness), str(ORIGINS_JS), answer], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


DEFAULTS = ["http://example.test/flower/", "http://example.test:8081/realms/aisc/account", "http://example.test:8188/"]


def test_the_links_take_the_gateways_addresses(tmp_path):
    out = _run(tmp_path, json.dumps({"engine": "http://example.test:9090/", "keycloak": "https://auth.example.test",
                                     "dashboard": "http://example.test:9098"}))
    assert out["before"] == DEFAULTS
    assert out["after"] == ["http://example.test:9090/flower/", "https://auth.example.test/realms/aisc/account",
                            "http://example.test:9098/"]
    assert out["later"] == "http://example.test:9090/controls/p/abc"
    assert out["engine"] == "http://example.test:9090"


@pytest.mark.parametrize("answer", ["down", "404", json.dumps({"engine": "", "keycloak": "javascript:alert(1)"})])
def test_without_an_answer_the_links_are_this_hosts_defaults(tmp_path, answer):
    out = _run(tmp_path, answer)
    assert out["after"] == DEFAULTS
    assert out["later"] == "http://example.test/controls/p/abc"


def test_the_gateway_serves_the_installs_origins():
    if not shutil.which("docker"):
        pytest.skip("docker is not available")
    env = {"CADDY_DOMAIN": "http://localhost", "CADDY_PORT": "8005", "HOMEPAGE_PORT": "8006", "DASHBOARD_PORT": "8008",
           "CADDY_ENVIRONMENT": "development", "LOG_FILE": "/tmp/caddy.log", "DASHBOARD_UPSTREAM": "dashboard:8189",
           "API_URL_EXTERNAL": "http://example.test:9090", "KEYCLOAK_URL_EXTERNAL": "http://example.test:9091",
           "DASHBOARD_EXTERNAL_URL": "http://example.test:9098"}
    args = [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
    r = subprocess.run(["docker", "run", "-d", "--rm", *args, "-v", f"{ROOT / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
                        "caddy:2.10.2"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    cid = r.stdout.strip()
    try:
        body = ""
        for _ in range(30):
            got = subprocess.run(["docker", "exec", cid, "wget", "-qO-", "http://localhost:8006/origins.json"],
                                 capture_output=True, text=True, timeout=30)
            if got.returncode == 0:
                body = got.stdout
                break
            time.sleep(0.5)
        assert body, "the launcher's gateway serves no /origins.json"
        assert json.loads(body) == {"engine": "http://example.test:9090", "keycloak": "http://example.test:9091",
                                    "dashboard": "http://example.test:9098"}
    finally:
        subprocess.run(["docker", "rm", "-fv", cid], capture_output=True, timeout=60)


def test_compose_hands_the_gateway_the_addresses():
    text = (ROOT / "docker-compose-infra.development.yml").read_text()
    caddy = re.search(r"\n  caddy:\n(.*?)\n  [a-z]", text, re.S).group(1)
    for name in ("API_URL_EXTERNAL", "KEYCLOAK_URL_EXTERNAL", "DASHBOARD_EXTERNAL_URL"):
        assert re.search(rf"^\s+{name}: \$\{{{name}", caddy, re.M), name
