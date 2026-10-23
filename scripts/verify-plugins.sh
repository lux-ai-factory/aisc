#!/usr/bin/env bash
# Is the plugin path working: is the publisher up, the shared interface on the index, and can what was
# installed so far be installed again, from the private catalogue, by a person?
#
#   ./scripts/verify-plugins.sh                    what is there now
#   ./scripts/verify-plugins.sh --install langbite   also installs the catalogue entry "langbite" as the
#                                                    admin, which fetches its repo from GitHub and builds it
#                                                    (about a minute; needs GitHub reachable from the stack)
#
#   publisher  plugin-publisher answers /health and has published the shared plugin interface
#   interface  the index holds the shared plugin interface (shared/plugin-interface) at its version: a
#              plugin's run installs its dependencies from PyPI and this index, and takes it from here
#   install    the check's own project ("verify plugins", made by the first run and reused), through the
#              launcher as the development admin (VERIFY_ADMIN_USER / VERIFY_ADMIN_PASSWORD, by default
#              `admin` and its password from env.secrets, never printed): every plugin package on the index
#              (a test is on it only after someone installed it) installs into its engine project. With
#              --install <slug>, that entry is installed first, through the private catalogue
#   catalogue  the same project with a private catalogue: every package on the index is offered by a blue
#              entry whose install check says installable, and every blue test is installable (no blue entry
#              that can't be installed, no pink one that can). The public catalogue not answering is a WARN
#
# Output lines are "  PASS|FAIL|WARN <check> <text>"; exit status 1 on any FAIL.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/dev-accounts.sh"
. "$HERE/lib/install-addresses.sh"
cd "$HERE/.." && exec uv run --no-project --quiet --with packaging python - "$@" <<'PY'
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlencode

from packaging.version import InvalidVersion, Version

failed = False
#: the project the check installs into: made by the first run, reused by every later one (a project keeps its
#: ledger database for good, deleted or not, so one per run would use up the ledger pool)
PROJECT_NAME = "verify plugins"


def say(kind, check, text):
    global failed
    failed |= kind == "FAIL"
    print(f"  {kind} {check} {text}", flush=True)


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def newest_last(versions):
    """Oldest first, by version (0.2.9 before 0.2.10); a version that is not PEP 440 goes first."""
    def key(v):
        try:
            return (1, Version(v))
        except InvalidVersion:
            return (0, Version("0"))
    return sorted(versions, key=key)


def index():
    """{normalised name: (name, [versions])} of what devpi holds, read inside the devpi container."""
    def get(path):
        r = subprocess.run(["docker", "exec", "devpi", "curl", "-s", "-H", "Accept: application/json",
                            f"http://localhost:3141/{path}"], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout)["result"]
    index_name = os.environ.get("PACKAGE_REGISTRY_INDEX", "root/public").strip("/")
    out = {}
    for name in get(index_name)["projects"]:
        out[norm(name)] = (name, newest_last(get(f"{index_name}/{name}").keys()))
    return out


def index_now(package):
    """{normalised name: (name, versions)} of one package, read from the index again after an install."""
    return {key: value for key, value in index().items() if key == norm(package)}


def pyproject_name_version(path):
    text = path.read_text()
    name = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
    version = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return (name.group(1) if name else None), (version.group(1) if version else None)


def interface_on_index(held):
    name, version = pyproject_name_version(Path("shared/plugin-interface/pyproject.toml"))
    found = held.get(norm(name or ""))
    if found and version in found[1]:
        say("PASS", "interface", f"the index holds the shared {name} {version}, which plugin runs install")
    else:
        say("FAIL", "interface", f"the index lacks the shared {name} {version}: runs would take PyPI's, which has no"
                          " connector (docker logs plugin-publisher)")
    held.pop(norm(name or ""), None)          # the interface is no plugin: the install and catalogue checks skip it


def publisher_health():
    """plugin-publisher answers /health (asked inside its container: it publishes no port) and has put the
    shared interface on the index."""
    r = subprocess.run(["docker", "exec", "plugin-publisher", "python", "-c",
                        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health',"
                        " timeout=4).read().decode())"], capture_output=True, text=True, timeout=60)
    try:
        health = json.loads(r.stdout)
    except ValueError:
        health = None
    if r.returncode != 0 or not isinstance(health, dict):
        say("FAIL", "publisher", "plugin-publisher does not answer /health (docker logs plugin-publisher)")
    elif health.get("interface_published"):
        say("PASS", "publisher", "plugin-publisher is up and has published the shared plugin interface")
    else:
        say("FAIL", "publisher", "plugin-publisher is up but has not published the shared plugin interface"
                                 " (docker logs plugin-publisher)")


def install_slug(argv):
    """The catalogue entry named by `--install <slug>`, or None."""
    if "--install" in argv:
        rest = argv[argv.index("--install") + 1:]
        if rest and not rest[0].startswith("-"):
            return rest[0]
        say("FAIL", "install", "--install takes the slug of a catalogue entry, for example --install langbite")
        sys.exit(2)
    return None


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

        self.launcher = os.environ["VERIFY_BASE_URL"].rstrip("/")
        self.apps = os.environ["VERIFY_APPS_URL"].rstrip("/")
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


def installs_and_catalogue(held, slug_to_install=None):
    session = Session()
    try:
        signed = session.sign_in(os.environ["VERIFY_ADMIN_USER"], os.environ["VERIFY_ADMIN_PASSWORD"])
    except (urllib.error.URLError, OSError) as exc:
        signed = False
        say("FAIL", "install", f"the launcher did not answer: {exc}")
    if not signed:
        say("FAIL", "install", "not run: the gateway did not sign in VERIFY_ADMIN_USER (default: the development admin)")
        return
    status, projects = session.call("GET", "/api/projects")
    project = next((p for p in projects if p.get("name") == PROJECT_NAME), None) if status == 200 else None
    if project is None:
        status, project = session.call("POST", "/api/projects", {"name": PROJECT_NAME})
        if status not in (200, 201):
            say("FAIL", "install", f"the check's project could not be made ({status}: {detail(project)})")
            return
    pid, slug = project["pid"], project["slug"]
    status, engine = session.call("POST", f"/api/v1/projects/for-platform/{pid}", {}, project=pid)
    if status != 200:
        say("FAIL", "install", f"the engine did not make the project's engine project ({status}: {detail(engine)})")
        return
    if not held and not slug_to_install:
        say("WARN", "install", "no test is on the index yet (a test is fetched when it is first installed);"
                               " ./scripts/verify-plugins.sh --install <slug> fetches one")
    for key in sorted(held):
        package, versions = held[key]
        version = versions[-1]
        status, made = session.call("POST", "/api/v1/plugins",
                                    {"package_name": package, "version": version, "project_uuid": engine["pid"]},
                                    project=pid, timeout=1500)
        if status == 200 and made:
            say("PASS", "install", f"{package} {version} installs ({', '.join(p['name'] for p in made)})")
        else:
            say("FAIL", "install", f"{package} {version} does not install ({status}: {str(detail(made))[:300]})")
    private_catalogue(session, slug, held, slug_to_install)


def fetch_and_install(session, slug, entry):
    """Install one test of the private catalogue as the admin: the platform has the publisher fetch and build
    its repo, then installs it. Returns the package name, or None."""
    status, done = session.call("POST", f"/api/projects/{slug}/catalogue/api/tool/{entry}/install", {}, timeout=1500)
    if status == 200 and isinstance(done, dict):
        say("PASS", "install", f"{entry}: fetched, built and installed as {done['package_name']} {done['version']}")
        return done["package_name"]
    say("FAIL", "install", f"{entry} was not installed ({status}: {str(detail(done))[:300]})")
    return None


def private_catalogue(session, slug, held, slug_to_install=None):
    status, chosen = session.call("POST", f"/api/projects/{slug}/catalogue", {"mode": "private"}, timeout=120)
    if status == 503:
        say("WARN", "catalogue", f"not run: the public catalogue did not answer, so no private copy ({detail(chosen)})")
        return
    # the project is reused and a catalogue choice is final: the platform answers 409 with this detail (and no
    # other) when it was chosen on an earlier run
    already = status == 409 and detail(chosen) == "this project chose its catalogue already"
    if status != 200 and not already:
        say("FAIL", "catalogue", f"choosing a private catalogue answered {status}: {detail(chosen)}")
        return
    if slug_to_install:
        package = fetch_and_install(session, slug, slug_to_install)
        if package:
            held.update(index_now(package))
    status, tools = session.call("GET", f"/api/projects/{slug}/catalogue/api/tool/?detailed=true")
    if status != 200:
        say("FAIL", "catalogue", f"the private catalogue's entries answered {status}")
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
            say("FAIL", "catalogue", f"{t['slug']} is blue but can't be installed ({detail(info) if status != 200 else info.get('reason')})")
        elif installable and not blue:
            say("FAIL", "catalogue", f"{t['slug']} can be installed but is pink")
    for key in sorted(held):
        if key in offered:
            say("PASS", "catalogue", f"{held[key][0]} is offered by a blue, installable entry")
        else:
            say("FAIL", "catalogue", f"{held[key][0]} is on the index but no entry of the private catalogue offers it")


publisher_health()
slug_to_install = install_slug(sys.argv[1:])
held = index()
if not held:
    say("FAIL", "index", "the package index holds nothing (docker logs plugin-publisher)")
interface_on_index(held)
installs_and_catalogue(held, slug_to_install)
sys.exit(1 if failed else 0)
PY
