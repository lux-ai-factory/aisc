#!/usr/bin/env bash
# Can every plugin this stack downloaded be installed, from the private catalogue, by a person?
#
#   ./scripts/verify-plugins.sh
#
#   P0 the index holds the shared plugin interface (shared/plugin-interface) at its version: a plugin's
#      run installs its dependencies from PyPI and this index, and takes it from here
#   P1 every plugin repo plugin-downloader cloned into def_plugins/ is on the stack's package index
#      (devpi), under its pyproject name and version; a missing one names `docker logs plugin-publisher`
#   P2 what plugin-downloader skipped (a private repo without GITHUB_TOKEN: WARN) or could not clone (FAIL)
#   P3 a throwaway project, made through the launcher as the development admin (VERIFY_ADMIN_USER /
#      VERIFY_ADMIN_PASSWORD, default admin / admin, read from the environment and never printed):
#      every package on the index installs into its engine project
#   P4 the same project with a private catalogue: every package on the index is offered by a blue entry
#      whose install check says installable, and every blue test is installable (no blue entry that
#      can't be installed, no pink one that can). The public catalogue not answering is a WARN
#
# The throwaway project is taken away at the end, also after a failure. Output lines are
# "  PASS|FAIL|WARN Pn <text>"; exit status 1 on any FAIL.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE/.." && exec uv run --no-project --quiet python - "$@" <<'PY'
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlencode

failed = False


def say(kind, check, text):
    global failed
    failed |= kind == "FAIL"
    print(f"  {kind} {check} {text}", flush=True)


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def index():
    """{normalised name: (name, [versions])} of what devpi holds, read inside the devpi container."""
    def get(path):
        r = subprocess.run(["docker", "exec", "devpi", "curl", "-s", "-H", "Accept: application/json",
                            f"http://localhost:3141/{path}"], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)["result"]
    index_name = os.environ.get("PACKAGE_REGISTRY_INDEX", "root/public").strip("/")
    out = {}
    for name in get(index_name)["projects"]:
        out[norm(name)] = (name, sorted(get(f"{index_name}/{name}").keys()))
    return out


def pyproject_name_version(path):
    text = path.read_text()
    name = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
    version = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return (name.group(1) if name else None), (version.group(1) if version else None)


def p0(held):
    name, version = pyproject_name_version(Path("shared/plugin-interface/pyproject.toml"))
    found = held.get(norm(name or ""))
    if found and version in found[1]:
        say("PASS", "P0", f"the index holds the shared {name} {version}, which plugin runs install")
    else:
        say("FAIL", "P0", f"the index lacks the shared {name} {version}: runs would take PyPI's, which has no"
                          " connector (docker logs plugin-publisher)")
    held.pop(norm(name or ""), None)          # the interface is no plugin: P3 and P4 skip it


def p1_p2(held):
    for repo in sorted(Path("def_plugins").glob("*/pyproject.toml")):
        name, version = pyproject_name_version(repo)
        found = held.get(norm(name or ""))
        if found and version in found[1]:
            say("PASS", "P1", f"{repo.parent.name}: {name} {version} is on the index")
        else:
            say("FAIL", "P1", f"{repo.parent.name}: {name} {version} is not on the index"
                              " (docker logs plugin-publisher says why it did not build)")
    log = subprocess.run(["docker", "logs", "plugin-downloader"], capture_output=True, text=True).stdout
    for repo in sorted(set(re.findall(r"^skipped (\S+?):", log, re.M))):
        say("WARN", "P2", f"{repo} was skipped: a private repo, and env.secrets has no GITHUB_TOKEN")
    for repo in sorted(set(re.findall(r"^could not (?:clone|update) (\S+)", log, re.M))):
        say("FAIL", "P2", f"{repo} could not be downloaded (docker logs plugin-downloader)")


def _browser_like_cookies():
    """Python's cookie policy differs from a browser's on localhost (Secure cookies over http, and
    "localhost.local" matching), which breaks the sign-in; this one treats localhost as a browser does."""
    import http.cookiejar

    local = ("localhost", "127.0.0.1")

    class Policy(http.cookiejar.DefaultCookiePolicy):
        @staticmethod
        def _local(request):
            return urlsplit(request.get_full_url()).hostname in local

        def return_ok_secure(self, cookie, request):
            return self._local(request) or super().return_ok_secure(cookie, request)

        def return_ok_domain(self, cookie, request):
            return (self._local(request) and cookie.domain.lstrip(".") in ("localhost", "localhost.local")) \
                or super().return_ok_domain(cookie, request)

        def domain_return_ok(self, domain, request):
            return (self._local(request) and domain.lstrip(".") in ("localhost", "localhost.local")) \
                or super().domain_return_ok(domain, request)

    return Policy()


class Session:
    """A person signed in through the gateway, with its cookies on every call: the gateway takes its own
    session, not a bearer token."""

    def __init__(self):
        import http.cookiejar

        self.launcher = os.environ.get("VERIFY_BASE_URL", "http://localhost:8100").rstrip("/")
        self.apps = os.environ.get("VERIFY_APPS_URL", "http://localhost").rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(
            http.cookiejar.CookieJar(policy=_browser_like_cookies())))

    def sign_in(self, user, password):
        with self.opener.open(self.launcher + "/", timeout=30) as res:
            page = res.read().decode(errors="replace")
        m = re.search(r'action="([^"]+)"', page)
        if not m:
            return False
        form = urlencode({"username": user, "password": password}).encode()
        with self.opener.open(m.group(1).replace("&amp;", "&"), data=form, timeout=30) as res:
            return urlsplit(res.geturl()).netloc == urlsplit(self.launcher).netloc

    def call(self, method, path, body=None, project=None, timeout=60):
        """(status, body): /api/projects... on the launcher, everything else on the apps' address."""
        base = self.launcher if path.startswith("/api/projects") else self.apps
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if method not in ("GET", "HEAD"):
            headers["Origin"] = base
        if project:
            headers["X-AISC-Project"] = project
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as res:
                if urlsplit(res.geturl()).netloc != urlsplit(base).netloc:
                    return 401, None                                   # sent to the sign-in
                text = res.read().decode(errors="replace")
                return res.status, (json.loads(text) if text[:1] in ("[", "{") else text)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode(errors="replace")
            try:
                return exc.code, json.loads(text)
            except ValueError:
                return exc.code, text[:300]


def detail(body):
    return body.get("detail") if isinstance(body, dict) else body


def p3_p4(held):
    session = Session()
    try:
        signed = session.sign_in(os.environ.get("VERIFY_ADMIN_USER", "admin"),
                                 os.environ.get("VERIFY_ADMIN_PASSWORD", "admin"))
    except (urllib.error.URLError, OSError) as exc:
        signed = False
        say("FAIL", "P3", f"the launcher did not answer: {exc}")
    if not signed:
        say("FAIL", "P3", "not run: the gateway did not sign in VERIFY_ADMIN_USER (default: the development admin)")
        return
    name = f"verify-plugins-{secrets.token_hex(3)}"
    status, project = session.call("POST", "/api/projects", {"name": name})
    if status not in (200, 201):
        say("FAIL", "P3", f"a throwaway project could not be made ({status}: {detail(project)})")
        return
    try:
        pid, slug = project["pid"], project["slug"]
        status, engine = session.call("POST", f"/api/v1/projects/for-platform/{pid}", {}, project=pid)
        if status != 200:
            say("FAIL", "P3", f"the engine did not make the project's engine project ({status}: {detail(engine)})")
            return
        for key in sorted(held):
            package, versions = held[key]
            version = versions[-1]
            status, made = session.call("POST", "/api/v1/plugins",
                                        {"package_name": package, "version": version, "project_uuid": engine["pid"]},
                                        project=pid, timeout=1500)
            if status == 200 and made:
                say("PASS", "P3", f"{package} {version} installs ({', '.join(p['name'] for p in made)})")
            else:
                say("FAIL", "P3", f"{package} {version} does not install ({status}: {str(detail(made))[:300]})")
        p4(session, slug, held)
    finally:
        status, _ = session.call("DELETE", f"/api/projects/{project['slug']}", {"confirm_name": name})
        if status not in (204, 404):
            say("WARN", "P3", f"the throwaway project {project['slug']} could not be taken away ({status})")


def p4(session, slug, held):
    status, chosen = session.call("POST", f"/api/projects/{slug}/catalogue", {"mode": "private"}, timeout=120)
    if status == 503:
        say("WARN", "P4", f"not run: the public catalogue did not answer, so no private copy ({detail(chosen)})")
        return
    if status != 200:
        say("FAIL", "P4", f"choosing a private catalogue answered {status}: {detail(chosen)}")
        return
    status, tools = session.call("GET", f"/api/projects/{slug}/catalogue/api/tool/?detailed=true")
    if status != 200:
        say("FAIL", "P4", f"the private catalogue's entries answered {status}")
        return
    offered = set()
    for t in tools:
        if "test" not in [g.get("slug") for g in t.get("tags") or []]:
            continue
        status, info = session.call("GET", f"/api/projects/{slug}/catalogue/api/tool/{t['slug']}/install-info")
        installable = status == 200 and info.get("installable")
        blue = t.get("completion_status") == "full"
        if installable:
            offered.add(norm(info["package_name"]))
        if blue and not installable:
            say("FAIL", "P4", f"{t['slug']} is blue but can't be installed ({detail(info) if status != 200 else info.get('reason')})")
        elif installable and not blue:
            say("FAIL", "P4", f"{t['slug']} can be installed but is pink")
    for key in sorted(held):
        if key in offered:
            say("PASS", "P4", f"{held[key][0]} is offered by a blue, installable entry")
        else:
            say("FAIL", "P4", f"{held[key][0]} is on the index but no entry of the private catalogue offers it")


held = index()
if not held:
    say("FAIL", "P1", "the package index holds nothing (docker logs plugin-publisher)")
p0(held)
p1_p2(held)
p3_p4(held)
sys.exit(1 if failed else 0)
PY
