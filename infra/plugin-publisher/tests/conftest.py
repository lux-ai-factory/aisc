"""Fixtures for the publisher's tests: bare git repos standing in for GitHub, a fake package index
and a fake build (so no test reaches the network), and the service on a free local port."""

import json
import os
import shutil
import stat
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from plugin_publisher.service import Publisher, make_server

SERVICE_TOKEN = "service-token-for-tests"
GITHUB_TOKEN = "ghp_secret_token_for_tests"
REAL_GIT = shutil.which("git")


def _git(*args, cwd):
    subprocess.run(
        [REAL_GIT, "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def github(tmp_path, monkeypatch):
    """A folder of bare repos that GITHUB_BASE points at, and a way to add one: make(repo,
    {branch: (package, version)}, default=branch)."""
    base = tmp_path / "github"
    base.mkdir()
    monkeypatch.setenv("GITHUB_BASE", f"file://{base}")

    def make(repo, branches, default="main"):
        work = tmp_path / "work" / repo
        work.mkdir(parents=True)
        _git("init", "-q", "-b", default, cwd=work)
        _git("commit", "-q", "--allow-empty", "-m", "start", cwd=work)
        for branch, (package, version) in branches.items():
            _git("checkout", "-q", "-B", branch, default, cwd=work)
            (work / "pyproject.toml").write_text(
                f'[project]\nname = "{package}"\nversion = "{version}"\n'
            )
            _git("add", "pyproject.toml", cwd=work)
            _git("commit", "-q", "-m", f"{package} {version}", cwd=work)
        bare = base / f"{repo}.git"
        _git("clone", "-q", "--bare", str(work), str(bare), cwd=tmp_path)
        _git("symbolic-ref", "HEAD", f"refs/heads/{default}", cwd=bare)
        return bare

    return make


class FakeIndex:
    """The index as the publisher sees it: versions per package, the wheel it holds for each version
    (`files`, {(dist, version): bytes}), and every upload recorded."""

    def __init__(self):
        self.versions = {}
        self.files = {}
        self.uploads = []
        self.lock = threading.Lock()

    def wheel_on_index(self, package, version):
        with self.lock:
            return self.files.get((_dist(package), version))

    def versions_on_index(self, package):
        with self.lock:
            return sorted(self.versions.get(_dist(package), set()))

    def upload(self, paths):
        names = [Path(p).name for p in paths]
        with self.lock:
            self.uploads.append(names)
            for name in names:
                if name.endswith(".whl"):
                    dist, version = name.split("-")[:2]
                    self.versions.setdefault(_dist(dist), set()).add(version)
            for path in paths:
                if Path(path).name.endswith(".whl"):
                    dist, version = Path(path).name.split("-")[:2]
                    self.files[(_dist(dist), version)] = Path(path).read_bytes()


def _dist(name):
    import re
    return re.sub(r"[-_.]+", "-", name).lower()


class FakeBuild:
    """Writes the wheel a real build would name from pyproject.toml (underscores, as wheels do).
    built_name overrides the name, to stand in for a repo whose build makes another package; content
    is what the wheel holds."""

    def __init__(self):
        self.calls = 0
        self.content = b"wheel"
        self.delay = 0.0
        self.built_name = None
        self.fail = False
        self.link_to = None
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, source, outdir):
        with self.lock:
            self.calls += 1
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("build failed: no backend")
        project = tomllib.loads((Path(source) / "pyproject.toml").read_text())["project"]
        name = (self.built_name or project["name"]).replace("-", "_")
        with self.lock:
            self.events.append(("build", project["name"]))
        (Path(outdir) / f"{name}-{project['version']}-py3-none-any.whl").write_bytes(self.content)
        if self.link_to:
            # a hostile build: an sdist that is a link to a file it could not read itself
            (Path(outdir) / f"{name}-{project['version']}.tar.gz").symlink_to(self.link_to)


@pytest.fixture
def index():
    return FakeIndex()


@pytest.fixture
def build():
    return FakeBuild()


@pytest.fixture
def workdir(tmp_path):
    folder = tmp_path / "builds"
    folder.mkdir()
    return folder


@pytest.fixture
def interface(tmp_path, monkeypatch):
    folder = tmp_path / "interface"
    folder.mkdir()
    (folder / "pyproject.toml").write_text(
        '[project]\nname = "aisc-plugin-interface"\nversion = "0.2.8"\n'
    )
    monkeypatch.setenv("INTERFACE_PATH", str(folder))
    return folder


@pytest.fixture(autouse=True)
def tokens(monkeypatch):
    monkeypatch.setenv("PLUGIN_PUBLISHER_TOKEN", SERVICE_TOKEN)
    monkeypatch.setenv("GITHUB_TOKEN", GITHUB_TOKEN)


@pytest.fixture
def git_calls(tmp_path, monkeypatch):
    """A git on PATH that records each call's argv and which secret variables it was given, then
    runs the real one."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    log = tmp_path / "git-calls.log"
    stub = stub_dir / "git"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "secrets = [v for v in ('GITHUB_TOKEN', 'TWINE_USERNAME', 'TWINE_PASSWORD',"
        " 'PLUGIN_PUBLISHER_TOKEN') if v in os.environ]\n"
        f"open({str(log)!r}, 'a').write(json.dumps([sys.argv[1:], secrets]) + '\\n')\n"
        f"os.execv({REAL_GIT!r}, [{REAL_GIT!r}] + sys.argv[1:])\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")

    def lines():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def read():
        return [argv for argv, _ in lines()]

    # the secret variables each call could see in its environment
    read.secrets = lambda: [secrets for _, secrets in lines()]
    return read


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method, path, body=None, token=SERVICE_TOKEN):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("X-AISC-Service-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body, **kw):
        return self.call("POST", path, body, **kw)


@pytest.fixture
def start(index, build, workdir):
    """Starts the service over a publisher made with the fake index and build; returns a client."""
    servers = []

    def run(publisher=None):
        publisher = publisher or Publisher(
            upload=index.upload, versions_on_index=index.versions_on_index,
            wheel_on_index=index.wheel_on_index, build=build, workdir=workdir,
        )
        server = make_server(publisher, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        client = Client(server.server_address[1])
        client.publisher = publisher
        return client

    yield run
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client(start):
    return start()
