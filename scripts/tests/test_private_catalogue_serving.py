"""The catalogue's own pages for a project's catalogue, served by this stack (docs/superpowers/
local-catalogue-2026-10-03/01-specs.md L1.2; since docs/superpowers/control-install-2026-10-04/01-plan.md D1, D4
for a public project too): built from apps/catalogue/frontend with the project-catalogue switch on, under
/project-catalogue/ on the launcher's origin, where /api/ is already the platform. The old address,
/private-catalogue/, redirects there."""
import json
import os
import re
import subprocess

from conftest import ROOT
from test_compose import FILES

CADDYFILE = ROOT / "Caddyfile"


def _services():
    args, required = [], set()
    for f in FILES:
        args += ["-f", str(ROOT / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {**os.environ, **{k: "dummy" for k in required}}
    j = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.plugin_downloader"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert j.returncode == 0, j.stderr[-2000:]
    return json.loads(j.stdout)["services"]


def test_the_service_builds_the_catalogue_frontend_with_the_switch_on_under_the_prefix():
    service = _services().get("catalogue-private")
    assert service, "no catalogue-private service"
    build = service["build"]
    assert build["context"] == str(ROOT / "apps/catalogue/frontend")
    args = build.get("args") or {}
    assert args.get("VITE_ENABLE_PROJECT_CATALOGUE") == "true"
    assert args.get("CATALOGUE_BASE") == "/project-catalogue/"
    assert args.get("VITE_ENABLE_INSTALL") == "true"
    assert args.get("VITE_ENABLE_ADD_ENTRIES") != "true", "the copy is read-only"
    assert "frontend" in service.get("networks", {}), "caddy reaches it on the frontend network"
    assert not service.get("ports"), "reached through the gateway only"


def _launcher_site():
    text = CADDYFILE.read_text()
    start = text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT} {")
    return text[start:text.index("\n}\n", start)]


def test_the_launcher_serves_it_behind_sign_in_before_its_own_files():
    """Sign-in must see the whole address: with handle_path the prefix is gone before protect runs, and
    after signing in the browser is sent to /catalogue?project=..., the launcher's 404."""
    site = _launcher_site()
    m = re.search(r"handle /project-catalogue/\* \{\s*route \{(.*?)\n      \}\n    \}", site, re.S)
    assert m, "no /project-catalogue/ handle with its own route on the launcher's site"
    body = m.group(1)
    steps = [line.strip() for line in body.strip().splitlines() if line.strip() and not line.strip().startswith("#")]
    assert steps == ["import protect launcher", "uri strip_prefix /project-catalogue",
                     "reverse_proxy catalogue-private:3000"], steps
    assert "handle_path /project-catalogue/" not in site
    assert site.index("handle /project-catalogue/*") < site.index("handle /p/*"), "before the launcher's files"
    assert re.search(r"redir /project-catalogue /project-catalogue/", site), "the bare prefix goes to the pages"


def test_the_old_address_redirects_to_the_new_one_keeping_the_rest():
    """/private-catalogue/<rest> (bookmarks, an open tab) goes to /project-catalogue/<rest>, query kept;
    the browser keeps the #env= hand-over across the redirect."""
    site = _launcher_site()
    m = re.search(r"handle /private-catalogue\* \{\s*route \{(.*?)\n      \}\n    \}", site, re.S)
    assert m, "no redirect from /private-catalogue"
    steps = [line.strip() for line in m.group(1).strip().splitlines() if line.strip() and not line.strip().startswith("#")]
    assert steps == ["uri strip_prefix /private-catalogue", "redir * /project-catalogue{uri} 308"], steps
    assert "reverse_proxy" not in m.group(1) and "file_server" not in m.group(1)
    assert site.index("handle /private-catalogue*") < site.index("handle /p/*")


def test_the_platform_asks_the_same_package_index_the_engine_installs_from():
    """install-info says what the engine can install, so both must name one index."""
    services = _services()
    engine, platform = services["aisc-backend"]["environment"], services["platform"]["environment"]
    for name in ("PACKAGE_REGISTRY_URL", "PACKAGE_REGISTRY_INDEX"):
        assert platform.get(name) and platform.get(name) == engine.get(name), (name, platform.get(name), engine.get(name))
