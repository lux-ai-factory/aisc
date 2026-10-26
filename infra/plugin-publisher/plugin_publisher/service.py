"""The publisher's HTTP API, reached only by the platform on the backend network:

- GET /health: {"interface_published": bool}, without a token;
- GET /sources/{repo}: the branch, package and version at the head of that repo;
- POST /publish {"repo", "package"}: fetch, build and check that one plugin, and upload it unless the index
  already holds that version with the same content.

Every route but /health needs X-AISC-Service-Token equal to PLUGIN_PUBLISHER_TOKEN."""

import hashlib
import hmac
import io
import json
import logging
import os
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from plugin_publisher.git import StepFailed, scrub, tail
from plugin_publisher.sources import (
    NotAllowed, SourceError, artefact_name, check_allowed, clone, dist, read_project, read_source,
)

logger = logging.getLogger("plugin_publisher")

PORT = 8000
BUILD_TIMEOUT_S = 480
UPLOAD_TIMEOUT_S = 120
INDEX_TIMEOUT_S = 10
STOP_WAIT_S = 5.0
# The interface publish at start waits for devpi, which on a slow machine is healthy minutes after
# the publisher starts: tried again after 5 s, then twice as long each time up to a minute, for
# about ten minutes in all.
INTERFACE_FIRST_WAIT_S = 5
INTERFACE_LONGEST_WAIT_S = 60
INTERFACE_GIVE_UP_AFTER_S = 600
_ARTEFACT = r"\.(?:tar\.gz|whl|zip)"


class Refused(Exception):
    """An answer other than 200, with the status to give."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# What a build may see of the environment: a repo's build backend, setup.py and build requirements
# are code from outside, so no secret is passed, only what pip needs to fetch the build requirements.
BUILD_ENV_PASSED = ("PATH", "LANG", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST",
                    "PIP_CERT", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy",
                    "https_proxy", "no_proxy")


def _own_tree(root: Path, user: str) -> None:
    shutil.chown(root, user, user)
    for path in root.rglob("*"):
        if not path.is_symlink():
            shutil.chown(path, user, user)


def python_build(source: Path, outdir: Path) -> None:
    """The build the one-shot publisher ran: python -m build (sdist and wheel) into outdir, with no
    secret in its environment. With BUILD_AS_USER set (the image sets it) the build runs as that
    unprivileged user, who can neither read the service's environment in /proc/1 nor change its
    code; the publish folder (clone, home, output) is handed to that user first."""
    folder = Path(outdir).parent
    home = folder / "build-home"
    home.mkdir(exist_ok=True)
    env = {k: os.environ[k] for k in BUILD_ENV_PASSED if k in os.environ}
    env["HOME"] = str(home)
    argv = [sys.executable, "-m", "build", "--outdir", str(outdir), str(source)]
    user = os.environ.get("BUILD_AS_USER")
    if user:
        _own_tree(folder, user)
        argv = ["setpriv", f"--reuid={user}", f"--regid={user}", "--init-groups", "--", *argv]
    try:
        r = subprocess.run(argv, env=env, capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise StepFailed(f"the build did not finish within {BUILD_TIMEOUT_S} s") from None
    if r.returncode != 0:
        raise StepFailed(r.stdout + r.stderr)


def _uid_of(user: str) -> int:
    return pwd.getpwnam(user).pw_uid


def _live_pids_of(uid: int) -> list[int]:
    """The processes whose real uid is uid, zombies left out (they can no longer act)."""
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text()
        except OSError:
            continue  # it ended meanwhile
        fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        if int(fields.get("Uid", "-1").split()[0]) == uid and not fields.get(
                "State", "").strip().startswith("Z"):
            pids.append(int(entry.name))
    return pids


def stop_build_processes() -> None:
    """Kills every process of BUILD_AS_USER and waits until none is left, so nothing a build
    started can still change its output (or another publish's) once it is checked and uploaded.
    Without BUILD_AS_USER builds run as the service's own user and there is nothing to stop."""
    user = os.environ.get("BUILD_AS_USER")
    if not user:
        return
    uid = _uid_of(user)
    deadline = time.monotonic() + STOP_WAIT_S
    while pids := _live_pids_of(uid):
        if time.monotonic() > deadline:
            raise StepFailed(f"processes of {user} still running after the build: {pids}")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.05)


def twine_upload(paths: list[Path]) -> None:
    """Uploads to TWINE_REPOSITORY_URL as TWINE_USERNAME / TWINE_PASSWORD, read from the
    environment by twine itself."""
    try:
        r = subprocess.run([sys.executable, "-m", "twine", "upload", "--non-interactive",
                            *map(str, paths)], capture_output=True, text=True,
                           timeout=UPLOAD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise StepFailed(f"the upload did not finish within {UPLOAD_TIMEOUT_S} s") from None
    if r.returncode != 0:
        raise StepFailed(r.stdout + r.stderr)


def _simple_page_url(package: str) -> str:
    upload_url = os.environ.get("TWINE_REPOSITORY_URL", "http://devpi:3141/root/public/")
    return f"{upload_url.rstrip('/')}/+simple/{dist(package)}/"


def _version_of(filename: str, wanted: str) -> str | None:
    """The version part of an artefact's file name when it is of the distribution `wanted`."""
    parts = re.sub(rf"{_ARTEFACT}$", "", filename).split("-")
    # wheels are name-version-python-abi-platform, sdists name-version
    for at in range(len(parts) - 1, 0, -1):
        if dist("-".join(parts[:at])) == wanted:
            return parts[at]
    return None


def _read_simple_page(package: str) -> str | None:
    try:
        with urllib.request.urlopen(_simple_page_url(package), timeout=INDEX_TIMEOUT_S) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("package index not readable for %s: %s", package, exc)
        return None


def index_versions(package: str) -> list[str]:
    """The versions the index's simple page lists for that distribution; none when it can't be
    reached (then the build runs and the upload says what is wrong)."""
    page = _read_simple_page(package)
    if page is None:
        return []
    wanted = dist(package)
    found = {_version_of(filename, wanted)
             for filename in re.findall(rf">\s*([^<>\s]+?{_ARTEFACT})\s*<", page)}
    return sorted(found - {None})


def index_wheel(package: str, version: str) -> bytes | None:
    """The bytes of the first wheel the index's simple page lists for that distribution and version;
    None when none is listed or the page or the file cannot be read."""
    page = _read_simple_page(package)
    if page is None:
        return None
    wanted = dist(package)
    for href, text in re.findall(r"<a\s[^>]*?href=[\"']([^\"']+)[\"'][^>]*>\s*([^<>]*?)\s*</a>", page, re.I):
        filename = text or urllib.parse.urlsplit(href).path.rsplit("/", 1)[-1]
        if not filename.endswith(".whl") or _version_of(filename, wanted) != version:
            continue
        url = urllib.parse.urldefrag(urllib.parse.urljoin(_simple_page_url(package), href)).url
        try:
            with urllib.request.urlopen(url, timeout=INDEX_TIMEOUT_S) as r:
                return r.read()
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("wheel %s not readable from the index: %s", filename, exc)
            return None
    logger.warning("no wheel of %s %s listed on the index", package, version)
    return None


def wheel_content(data: bytes) -> dict[str, str]:
    """What a wheel holds, to compare two builds of one version: {member: sha256 of its bytes} for every
    file member of a zip archive (timestamps and member order do not count); {"": sha256 of the bytes}
    for bytes that are no zip archive."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {info.filename: hashlib.sha256(archive.read(info)).hexdigest()
                    for info in archive.infolist() if not info.is_dir()}
    except zipfile.BadZipFile:
        return {"": hashlib.sha256(data).hexdigest()}


class Publisher:
    """Publishes one repo at a time per repo: a lock per repo, a build on every publish, and an upload
    only when the index lacks that version or holds it with another content (builds are not byte for
    byte reproducible, so wheels are compared member by member), so two installs of one plugin upload
    it once and a change released without a version bump still reaches the index."""

    def __init__(self, upload=twine_upload, versions_on_index=index_versions,
                 wheel_on_index=index_wheel, build=python_build, workdir=None,
                 stop_builds=stop_build_processes, sleep=time.sleep, clock=time.monotonic):
        self.upload, self.versions_on_index, self.build = upload, versions_on_index, build
        self.wheel_on_index = wheel_on_index
        self.stop_builds = stop_builds
        self.sleep, self.clock = sleep, clock
        # One build at a time across all repos: every build runs as the same user, so a build
        # running beside another publish's check and upload could swap that publish's files.
        self._build_lock = threading.Lock()
        self.workdir = workdir
        self.interface_published = False
        self._locks = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[key]

    def _on_index(self, package: str, version: str) -> bool:
        return version in self.versions_on_index(package)

    def source(self, repo: str) -> dict:
        check_allowed(repo)
        with tempfile.TemporaryDirectory(dir=self.workdir, prefix="source-") as tmp:
            branch, package, version = read_source(repo, Path(tmp) / "src")
        return {"repo": repo, "branch": branch, "package": package, "version": version}

    def publish(self, repo: str, package: str) -> dict:
        check_allowed(repo)
        # a fresh folder per publish, deleted afterwards: nothing of one build leaks into the next
        with tempfile.TemporaryDirectory(dir=self.workdir, prefix="publish-") as tmp:
            src = Path(tmp) / "src"
            clone(repo, src)
            name, version = read_project(src, repo)
            if dist(name) != dist(package):
                raise Refused(409, f"{repo} builds the package {name}, not {package}; "
                                   "nothing was published")
            with self._lock(repo):
                published, replaced = self._build_and_publish(src, Path(tmp) / "dist", package, version, repo)
        if replaced:
            logger.info("replaced %s %s on the index: its content changed", package, version)
        return {"package": package, "version": version, "published": published, "replaced": replaced}

    def _build_and_publish(self, src: Path, out: Path, package: str, version: str,
                           label: str) -> tuple[bool, bool]:
        """Builds, checks, then uploads unless the index holds this version with the same wheel content:
        (published, replaced), replaced meaning the version was on the index already."""
        out.mkdir()
        with self._build_lock:
            # the build user's processes are stopped whether the build worked, failed or timed out;
            # a failed build's own error is the one reported
            try:
                try:
                    self.build(src, out)
                except BaseException:
                    self._stop_builds_quietly()
                    raise
                self.stop_builds()
            except StepFailed as exc:
                raise SourceError("build", label, exc.output) from None
            except Exception as exc:
                raise SourceError("build", label, str(exc)) from None
            # checked and uploaded from a copy in a folder only the service can write
            with tempfile.TemporaryDirectory(dir=self.workdir, prefix="accepted-") as accepted:
                built = self._take_output(out, Path(accepted), label)
                other = [p.name for p in built if dist(artefact_name(p.name)) != dist(package)]
                if other:
                    raise Refused(409, f"{label} built {', '.join(other)}, not the package "
                                       f"{package}; nothing was published")
                wheels = [p for p in built if p.name.endswith(".whl")]
                if not wheels:
                    raise SourceError("build", label, "the build produced no wheel")
                on_index = self._on_index(package, version)
                if on_index and wheel_content(wheels[0].read_bytes()) == wheel_content(
                        self.wheel_on_index(package, version) or b""):
                    return False, False
                try:
                    self.upload(built)
                except StepFailed as exc:
                    raise SourceError("upload", label, exc.output) from None
                except Exception as exc:
                    raise SourceError("upload", label, str(exc)) from None
                logger.info("published %s", ", ".join(p.name for p in built))
                return True, on_index

    def _stop_builds_quietly(self) -> None:
        try:
            self.stop_builds()
        except Exception as exc:
            logger.error("after a failed build: %s", scrub(str(exc)))

    @staticmethod
    def _take_output(out: Path, into: Path, label: str) -> list[Path]:
        """Copies the build's files into a folder of the service's own. Only regular files: a link
        would make the upload, which runs as the service, send the content of whatever it points
        to (/proc/1/environ, for one)."""
        taken = []
        for entry in sorted(out.iterdir()):
            if not stat.S_ISREG(os.lstat(entry).st_mode):
                raise SourceError("build", label,
                                  f"the build left {entry.name}, which is not a regular file")
            shutil.copyfile(entry, into / entry.name, follow_symlinks=False)
            taken.append(into / entry.name)
        if not taken:
            raise SourceError("build", label, "the build produced no file")
        return taken

    def publish_interface(self) -> None:
        """Every run resolves the plugin interface from the index, so it is published at start
        unless that version is already there with the same content. A failure (devpi still starting, most often) is
        logged and tried again with a growing wait, for about INTERFACE_GIVE_UP_AFTER_S; /health
        says interface_published false until it succeeds. Run in the background, it never holds
        up the HTTP server."""
        started, wait = self.clock(), INTERFACE_FIRST_WAIT_S
        while not self._publish_interface_once():
            if self.clock() - started + wait > INTERFACE_GIVE_UP_AFTER_S:
                logger.error("gave up publishing the plugin interface after %d s",
                             self.clock() - started)
                return
            logger.info("publishing the plugin interface again in %d s", wait)
            self.sleep(wait)
            wait = min(wait * 2, INTERFACE_LONGEST_WAIT_S)

    def _publish_interface_once(self) -> bool:
        path = Path(os.environ.get("INTERFACE_PATH") or "/interface")
        try:
            package, version = read_project(path, "the plugin interface")
            with self._lock(f"interface:{package}"):
                with tempfile.TemporaryDirectory(dir=self.workdir, prefix="interface-") as tmp:
                    _, replaced = self._build_and_publish(path, Path(tmp) / "dist", package, version,
                                                          "the plugin interface")
            if replaced:
                logger.info("plugin interface %s %s replaced on the index: its content changed",
                            package, version)
            self.interface_published = True
            logger.info("plugin interface %s %s is on the index", package, version)
            return True
        except (SourceError, Refused) as exc:
            logger.error("%s: %s", exc, tail(getattr(exc, "output", "")))
        except Exception as exc:
            logger.error("could not publish the plugin interface: %s", scrub(str(exc)))
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "plugin-publisher"

    def log_message(self, format, *args):
        logger.info("%s %s", self.address_string(), scrub(format % args))

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        expected = os.environ.get("PLUGIN_PUBLISHER_TOKEN")
        if not expected:
            self._send(503, {"detail": "PLUGIN_PUBLISHER_TOKEN is not set"})
            return False
        given = self.headers.get("X-AISC-Service-Token") or ""
        if not hmac.compare_digest(given.encode(), expected.encode()):
            self._send(401, {"detail": "a valid X-AISC-Service-Token is required"})
            return False
        return True

    def _answer(self, work) -> None:
        publisher = self.server.publisher
        try:
            self._send(200, work(publisher))
        except NotAllowed as exc:
            self._send(400, {"detail": str(exc)})
        except Refused as exc:
            logger.warning(exc.detail)
            self._send(exc.status, {"detail": exc.detail})
        except SourceError as exc:
            detail = f"{exc}: {tail(exc.output)}"
            logger.warning(detail)
            # an unreadable source is "no source" to /sources, a failed step a bad gateway
            status = 404 if self.command == "GET" else 502
            self._send(status, {"detail": detail, "step": exc.step})

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health":
            self._send(200, {"interface_published": self.server.publisher.interface_published})
        elif path.startswith("/sources/"):
            if self._authorised():
                repo = urllib.parse.unquote(path[len("/sources/"):])
                self._answer(lambda p: p.source(repo))
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path != "/publish":
            self._send(404, {"detail": "not found"})
            return
        if not self._authorised():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"detail": "the body must be JSON"})
            return
        repo, package = (body.get("repo"), body.get("package")) if isinstance(body, dict) else (None, None)
        if not isinstance(package, str) or not package:
            self._send(400, {"detail": "package is required"})
            return
        self._answer(lambda p: p.publish(repo, package))


def make_server(publisher: Publisher, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.publisher = publisher
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    publisher = Publisher()
    # in the background, so /health answers while the interface builds
    threading.Thread(target=publisher.publish_interface, daemon=True).start()
    server = make_server(publisher, "0.0.0.0", PORT)
    logger.info("plugin publisher listening on %s", PORT)
    server.serve_forever()
