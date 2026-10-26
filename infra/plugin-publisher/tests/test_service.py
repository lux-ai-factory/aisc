import logging
import subprocess
import threading
import time
from pathlib import Path

import pytest

from conftest import GITHUB_TOKEN, SERVICE_TOKEN
from plugin_publisher import service
from plugin_publisher.git import StepFailed
from plugin_publisher.service import Publisher

SECRETS = ("GITHUB_TOKEN", "TWINE_USERNAME", "TWINE_PASSWORD", "PLUGIN_PUBLISHER_TOKEN")

REPO = "aisc-plugin-demo"
PACKAGE = "aisc-plugin-demo"


@pytest.mark.parametrize("repo", ["..%2Fx", "evil", "aisc-plugin-A"])
def test_a_repo_outside_the_allowed_names_is_refused(client, git_calls, index, repo):
    assert client.get(f"/sources/{repo}")[0] == 400
    assert client.post("/publish", {"repo": repo, "package": PACKAGE})[0] == 400
    assert git_calls() == []
    assert index.uploads == []


@pytest.mark.parametrize("repo", ["aisc-plugin-builder", "aisc-plugin-integrator",
                                  "aisc-plugin-interface", "aisc-plugin-manager"])
def test_the_plugin_tooling_repos_are_refused(client, git_calls, index, repo):
    for status, body in (client.get(f"/sources/{repo}"),
                         client.post("/publish", {"repo": repo, "package": repo})):
        assert status == 400
        assert "plugin tooling, not a plugin" in body["detail"]
    assert git_calls() == []
    assert index.uploads == []


def test_the_source_version_is_read_from_the_branch_head(client, github):
    github(REPO, {"main": (PACKAGE, "1.1.0"), "feat/unified-modules": (PACKAGE, "1.2.0")})

    status, body = client.get(f"/sources/{REPO}")

    assert status == 200
    assert body == {"repo": REPO, "branch": "feat/unified-modules",
                    "package": PACKAGE, "version": "1.2.0"}


def test_without_feat_unified_modules_the_default_branch_is_used(client, github):
    github(REPO, {"trunk": ("data-monitor", "0.4.1")}, default="trunk")

    status, body = client.get(f"/sources/{REPO}")

    assert status == 200
    assert body == {"repo": REPO, "branch": "trunk", "package": "data-monitor",
                    "version": "0.4.1"}


def test_an_unknown_repo_has_no_source(client, github):
    assert client.get("/sources/aisc-plugin-missing")[0] == 404


def test_publish_builds_checks_and_uploads_one_repo(client, github, index, build, workdir):
    github(REPO, {"main": (PACKAGE, "1.1.0"), "feat/unified-modules": (PACKAGE, "1.2.0")})

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 200
    assert body == {"package": PACKAGE, "version": "1.2.0", "published": True, "replaced": False}
    assert build.calls == 1
    assert index.uploads == [["aisc_plugin_demo-1.2.0-py3-none-any.whl"]]
    # the clone and the build lived in a temporary folder that is gone
    assert list(workdir.iterdir()) == []


def test_a_version_on_the_index_with_the_same_content_is_not_uploaded(client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.1.0")})
    index.versions[PACKAGE] = {"1.1.0"}
    index.files[(PACKAGE, "1.1.0")] = b"wheel"

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 200
    assert body == {"package": PACKAGE, "version": "1.1.0", "published": False, "replaced": False}
    assert build.calls == 1
    assert index.uploads == []


def test_a_version_on_the_index_whose_content_changed_is_replaced(client, github, index, build, caplog):
    github(REPO, {"main": (PACKAGE, "1.1.0")})
    index.versions[PACKAGE] = {"1.1.0"}
    index.files[(PACKAGE, "1.1.0")] = b"wheel"
    build.content = b"wheel v2"

    with caplog.at_level(logging.INFO):
        status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 200
    assert body == {"package": PACKAGE, "version": "1.1.0", "published": True, "replaced": True}
    assert index.uploads == [["aisc_plugin_demo-1.1.0-py3-none-any.whl"]]
    assert index.files[(PACKAGE, "1.1.0")] == b"wheel v2"
    assert f"replaced {PACKAGE} 1.1.0 on the index: its content changed" in caplog.text


def test_a_version_listed_on_the_index_whose_wheel_cannot_be_read_is_uploaded(client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.1.0")})
    index.versions[PACKAGE] = {"1.1.0"}

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 200
    assert body == {"package": PACKAGE, "version": "1.1.0", "published": True, "replaced": True}
    assert index.uploads == [["aisc_plugin_demo-1.1.0-py3-none-any.whl"]]


def test_a_build_of_another_package_is_refused_before_upload(client, github, index):
    github(REPO, {"main": ("renamed-package", "1.0.0")})

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 409
    assert "renamed-package" in body["detail"] and PACKAGE in body["detail"]
    assert index.uploads == []


def test_a_wheel_of_another_name_than_its_pyproject_is_refused_before_upload(
        client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.0.0")})
    build.built_name = "something-else"

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 409
    assert "something_else" in body["detail"] and PACKAGE in body["detail"]
    assert index.uploads == []


def test_two_publishes_of_one_repo_upload_once(client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.0.0")})
    build.delay = 0.5
    results = []

    def publish():
        results.append(client.post("/publish", {"repo": REPO, "package": PACKAGE}))

    threads = [threading.Thread(target=publish) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [status for status, _ in results] == [200, 200]
    assert sorted(body["published"] for _, body in results) == [False, True]
    assert build.calls == 2
    assert len(index.uploads) == 1


def test_every_git_call_asks_for_http_1_1_and_never_carries_the_token(
        client, github, git_calls, caplog):
    github(REPO, {"main": (PACKAGE, "1.1.0"), "feat/unified-modules": (PACKAGE, "1.2.0")})
    caplog.set_level(logging.DEBUG)

    client.get(f"/sources/{REPO}")
    client.post("/publish", {"repo": REPO, "package": PACKAGE})

    calls = git_calls()
    assert calls
    for argv in calls:
        assert argv[:2] == ["-c", "http.version=HTTP/1.1"]
        assert any(a.startswith("credential.helper=") and "${GITHUB_TOKEN}" in a for a in argv)
        assert GITHUB_TOKEN not in " ".join(argv)
    assert any("ls-remote" in argv and "--exit-code" in argv and "feat/unified-modules" in argv
               for argv in calls)
    assert GITHUB_TOKEN not in caplog.text


@pytest.mark.parametrize("token", [None, ""])
def test_without_a_github_token_git_is_given_no_credential_helper(
        client, github, git_calls, monkeypatch, token):
    if token is None:
        monkeypatch.delenv("GITHUB_TOKEN")
    else:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    github(REPO, {"main": (PACKAGE, "1.0.0")})

    assert client.get(f"/sources/{REPO}")[0] == 200

    calls = git_calls()
    assert calls
    for argv in calls:
        assert not any(a.startswith("credential.helper=") for a in argv)


@pytest.mark.parametrize("token", [None, ""])
def test_a_clone_failure_without_a_github_token_says_no_access_or_no_such_repo(
        client, github, monkeypatch, caplog, token):
    if token is None:
        monkeypatch.delenv("GITHUB_TOKEN")
    else:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    github("aisc-plugin-other", {"main": ("aisc-plugin-other", "1.0.0")})
    caplog.set_level(logging.DEBUG)

    status, body = client.get(f"/sources/{REPO}")
    assert status == 404
    assert "no access, or no such repo (GITHUB_TOKEN is not set)" in body["detail"]
    assert REPO in body["detail"]

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})
    assert status == 502
    assert "no access, or no such repo (GITHUB_TOKEN is not set)" in body["detail"]


def test_a_clone_failure_with_a_github_token_keeps_gits_own_message(client, github):
    github("aisc-plugin-other", {"main": ("aisc-plugin-other", "1.0.0")})

    status, body = client.get(f"/sources/{REPO}")

    assert status == 404
    assert "GITHUB_TOKEN is not set" not in body["detail"]
    assert GITHUB_TOKEN not in str(body)


def test_a_wrong_or_missing_service_token_is_401_and_unset_is_503(client, monkeypatch):
    for token in (None, "wrong"):
        assert client.get(f"/sources/{REPO}", token=token)[0] == 401
        assert client.post("/publish", {"repo": REPO, "package": PACKAGE}, token=token)[0] == 401
    assert client.get("/health", token=None)[0] == 200

    monkeypatch.delenv("PLUGIN_PUBLISHER_TOKEN")
    assert client.get(f"/sources/{REPO}")[0] == 503
    assert client.post("/publish", {"repo": REPO, "package": PACKAGE})[0] == 503
    assert client.get("/health", token=None)[0] == 200


def test_a_clone_failure_is_502_naming_the_repo_without_the_token(
        client, tmp_path, monkeypatch, caplog):
    # a base whose path holds the token, so git's own error message carries it
    monkeypatch.setenv("GITHUB_BASE", f"file://{tmp_path}/{GITHUB_TOKEN}")
    caplog.set_level(logging.DEBUG)

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 502
    assert REPO in body["detail"] and "clone" in body["detail"]
    assert GITHUB_TOKEN not in str(body)
    assert GITHUB_TOKEN not in caplog.text


def test_a_build_failure_is_502_naming_the_step(client, github, build, index):
    github(REPO, {"main": (PACKAGE, "1.0.0")})
    build.fail = True

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 502
    assert "build" in body["detail"] and "no backend" in body["detail"]
    assert index.uploads == []


def test_the_interface_is_published_at_start_unless_on_the_index_with_the_same_content(
        start, interface, index, build, workdir):
    def publisher():
        return Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                         wheel_on_index=index.wheel_on_index, build=build, workdir=workdir)

    first = publisher()
    first.publish_interface()
    assert index.uploads == [["aisc_plugin_interface-0.2.8-py3-none-any.whl"]]
    assert start(first).get("/health", token=None) == (200, {"interface_published": True})

    # the same content on the index: built again, nothing uploaded
    again = publisher()
    again.publish_interface()
    assert len(index.uploads) == 1 and build.calls == 2
    assert start(again).get("/health", token=None) == (200, {"interface_published": True})

    index.versions.clear()
    build.fail = True
    clock = Clock()
    failing = Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                        build=build, workdir=workdir, sleep=clock.sleep, clock=clock)
    failing.publish_interface()  # logged, never raised
    assert start(failing).get("/health", token=None) == (200, {"interface_published": False})


def test_an_interface_whose_content_changed_is_replaced_at_start(interface, index, build, workdir, caplog):
    index.versions["aisc-plugin-interface"] = {"0.2.8"}
    index.files[("aisc-plugin-interface", "0.2.8")] = b"wheel"
    build.content = b"wheel v2"

    def publisher():
        return Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                         wheel_on_index=index.wheel_on_index, build=build, workdir=workdir)

    with caplog.at_level(logging.INFO):
        publisher().publish_interface()
    assert index.uploads == [["aisc_plugin_interface-0.2.8-py3-none-any.whl"]]
    assert "plugin interface aisc-plugin-interface 0.2.8 replaced on the index: its content changed" in caplog.text

    again = publisher()
    again.publish_interface()
    assert len(index.uploads) == 1
    assert again.interface_published is True


def test_wheel_content_ignores_timestamps_and_member_order():
    import hashlib
    import io
    import zipfile

    def wheel(members, date):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for name, content in members:
                archive.writestr(zipfile.ZipInfo(name, date_time=date), content)
        return data.getvalue()

    one = wheel([("a.py", b"a"), ("pkg/b.py", b"b")], (2020, 1, 1, 0, 0, 0))
    two = wheel([("pkg/b.py", b"b"), ("a.py", b"a")], (2026, 6, 1, 12, 30, 0))
    changed = wheel([("a.py", b"a"), ("pkg/b.py", b"b2")], (2020, 1, 1, 0, 0, 0))
    assert one != two
    assert service.wheel_content(one) == service.wheel_content(two)
    assert service.wheel_content(one) != service.wheel_content(changed)
    assert service.wheel_content(b"wheel") == {"": hashlib.sha256(b"wheel").hexdigest()}


@pytest.fixture
def simple_index(tmp_path, monkeypatch):
    """A local index serving a simple page for aisc-plugin-demo that links two wheels by relative hrefs."""
    import functools
    import http.server

    root = tmp_path / "index"
    page = root / "root" / "public" / "+simple" / "aisc-plugin-demo"
    files = root / "root" / "public" / "+f"
    page.mkdir(parents=True)
    files.mkdir(parents=True)
    wheels = {"1.0.0": b"demo one", "1.1.0": b"demo one point one"}
    links = []
    for version, content in wheels.items():
        name = f"aisc_plugin_demo-{version}-py3-none-any.whl"
        (files / name).write_bytes(content)
        links.append(f'<a href="../../+f/{name}#sha256=0123abcd">{name}</a><br/>')
    (page / "index.html").write_text("<html><body>" + "".join(links) + "</body></html>")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("TWINE_REPOSITORY_URL", f"http://127.0.0.1:{server.server_address[1]}/root/public/")
    yield server, wheels
    server.shutdown()
    server.server_close()


def test_index_wheel_downloads_the_listed_wheel_of_a_version(simple_index):
    server, wheels = simple_index
    assert service.index_wheel("aisc-plugin-demo", "1.1.0") == wheels["1.1.0"]
    assert service.index_wheel("aisc-plugin-demo", "1.0.0") == wheels["1.0.0"]
    assert service.index_wheel("aisc-plugin-demo", "2.0.0") is None
    server.shutdown()
    server.server_close()
    assert service.index_wheel("aisc-plugin-demo", "1.1.0") is None


class Clock:
    """A clock that only moves when the publisher sleeps, so retries take no real time."""

    def __init__(self):
        self.now, self.slept = 0.0, []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def __call__(self):
        return self.now


def test_the_interface_publish_is_retried_until_the_index_takes_it(
        start, interface, index, build, workdir):
    """devpi may still be starting when the publisher does: the upload fails, then works."""
    clock, failures = Clock(), [StepFailed("connection refused"), StepFailed("503 starting")]

    def upload(paths):
        if failures:
            raise failures.pop(0)
        index.upload(paths)

    publisher = Publisher(upload=upload, versions_on_index=index.versions_on_index, build=build,
                          workdir=workdir, sleep=clock.sleep, clock=clock)
    client = start(publisher)
    assert client.get("/health", token=None) == (200, {"interface_published": False})

    publisher.publish_interface()

    assert clock.slept == [5, 10]
    assert index.uploads == [["aisc_plugin_interface-0.2.8-py3-none-any.whl"]]
    assert client.get("/health", token=None) == (200, {"interface_published": True})


def test_the_interface_publish_is_retried_when_the_index_cannot_be_read(
        interface, index, build, workdir):
    clock, failures = Clock(), [OSError("connection refused")] * 3

    def versions_on_index(package):
        if failures:
            raise failures.pop(0)
        return index.versions_on_index(package)

    publisher = Publisher(upload=index.upload, versions_on_index=versions_on_index, build=build,
                          workdir=workdir, sleep=clock.sleep, clock=clock)
    publisher.publish_interface()

    assert clock.slept == [5, 10, 20] and publisher.interface_published is True


def test_the_interface_publish_gives_up_after_about_ten_minutes(interface, index, build, workdir):
    clock = Clock()
    build.fail = True
    publisher = Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                          build=build, workdir=workdir, sleep=clock.sleep, clock=clock)

    publisher.publish_interface()

    assert publisher.interface_published is False
    assert clock.slept[:5] == [5, 10, 20, 40, 60] and max(clock.slept) == 60
    assert 600 - 60 <= sum(clock.slept) <= 600


def test_git_is_given_the_github_token_and_no_other_secret(client, github, git_calls, monkeypatch):
    monkeypatch.setenv("TWINE_USERNAME", "root")
    monkeypatch.setenv("TWINE_PASSWORD", "devpi-root-password")
    github(REPO, {"main": (PACKAGE, "1.0.0")})

    client.get(f"/sources/{REPO}")

    assert git_calls.secrets()
    for secrets in git_calls.secrets():
        assert secrets == ["GITHUB_TOKEN"]


@pytest.fixture
def build_calls(monkeypatch, tmp_path):
    """python_build with subprocess.run recorded instead of run, every secret in the environment."""
    monkeypatch.setenv("TWINE_USERNAME", "root")
    monkeypatch.setenv("TWINE_PASSWORD", "devpi-root-password")
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(service.subprocess, "run", run)
    folder = tmp_path / "publish-x"
    (folder / "src").mkdir(parents=True)
    (folder / "dist").mkdir()
    return calls, folder


def test_the_build_runs_with_no_secret_in_its_environment(build_calls, monkeypatch):
    calls, folder = build_calls
    monkeypatch.delenv("BUILD_AS_USER", raising=False)

    service.python_build(folder / "src", folder / "dist")

    (argv, kw), = calls
    assert argv[1:4] == ["-m", "build", "--outdir"]
    env = kw["env"]
    assert not set(SECRETS) & set(env)
    assert env["PATH"]
    # a home of its own inside the publish folder, deleted with it
    assert env["HOME"].startswith(str(folder))


def test_with_build_as_user_the_build_runs_as_that_user_in_folders_it_owns(
        build_calls, monkeypatch):
    calls, folder = build_calls
    monkeypatch.setenv("BUILD_AS_USER", "builder")
    owned = []
    monkeypatch.setattr(service.shutil, "chown", lambda path, user, group: owned.append(
        (str(path), user, group)))

    service.python_build(folder / "src", folder / "dist")

    (argv, kw), = calls
    assert argv[:5] == ["setpriv", "--reuid=builder", "--regid=builder", "--init-groups", "--"]
    assert not set(SECRETS) & set(kw["env"])
    for path in (folder, folder / "src", folder / "dist", folder / "build-home"):
        assert (str(path), "builder", "builder") in owned


def test_a_symlink_in_the_build_output_is_refused_and_nothing_uploaded(
        client, github, index, build, tmp_path):
    secret = tmp_path / "environ"
    secret.write_text("TWINE_PASSWORD=devpi-root-password")
    build.link_to = secret
    github(REPO, {"main": (PACKAGE, "1.0.0")})

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 502
    assert "aisc_plugin_demo-1.0.0.tar.gz" in body["detail"]
    assert "devpi-root-password" not in str(body)
    assert index.uploads == []


def test_the_upload_is_made_from_a_copy_outside_the_build_output(start, github, index, build,
                                                                   workdir):
    uploaded = []

    def upload(paths):
        uploaded.extend((Path(p).parent.name, Path(p).read_bytes()) for p in paths)
        index.upload(paths)

    client = start(Publisher(upload=upload, versions_on_index=index.versions_on_index,
                             build=build, workdir=workdir))
    github(REPO, {"main": (PACKAGE, "1.0.0")})

    assert client.post("/publish", {"repo": REPO, "package": PACKAGE})[0] == 200
    assert uploaded and all(folder != "dist" and data == b"wheel" for folder, data in uploaded)


def test_publishes_of_different_repos_never_overlap_build_and_upload(
        start, github, index, build, workdir):
    events = build.events

    def upload(paths):
        time.sleep(0.2)
        with build.lock:
            events.append(("upload", Path(paths[0]).name.split("-")[0].replace("_", "-")))
        index.upload(paths)

    client = start(Publisher(upload=upload, versions_on_index=index.versions_on_index,
                             build=build, workdir=workdir))
    build.delay = 0.3
    repos = ["aisc-plugin-one", "aisc-plugin-two", "aisc-plugin-three"]
    for repo in repos:
        github(repo, {"main": (repo, "1.0.0")})
    threads = [threading.Thread(target=client.post, args=("/publish", {"repo": r, "package": r}))
               for r in repos]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(events) == 6
    # each build is followed by its own upload before any other build starts
    for at in range(0, 6, 2):
        assert events[at][0] == "build" and events[at + 1] == ("upload", events[at][1])


def test_the_build_users_processes_are_stopped_before_check_and_upload(
        start, github, index, build, workdir):
    order = []
    publisher = Publisher(upload=lambda paths: order.append("upload"),
                          versions_on_index=index.versions_on_index,
                          build=lambda src, out: (order.append("build"), build(src, out)),
                          workdir=workdir, stop_builds=lambda: order.append("stop"))
    github(REPO, {"main": (PACKAGE, "1.0.0")})

    assert start(publisher).post("/publish", {"repo": REPO, "package": PACKAGE})[0] == 200
    assert order == ["build", "stop", "upload"]


@pytest.mark.parametrize("failure", [StepFailed("compiler error"),
                                     StepFailed("the build did not finish within 480 s"),
                                     RuntimeError("no backend")])
def test_the_build_users_processes_are_stopped_after_a_failed_build_too(
        start, github, index, workdir, failure):
    """A failed or timed-out build may leave processes behind: they are stopped all the same."""
    order = []

    def build(src, out):
        order.append("build")
        raise failure

    publisher = Publisher(upload=lambda paths: order.append("upload"),
                          versions_on_index=index.versions_on_index, build=build,
                          workdir=workdir, stop_builds=lambda: order.append("stop"))
    github(REPO, {"main": (PACKAGE, "1.0.0")})

    assert start(publisher).post("/publish", {"repo": REPO, "package": PACKAGE})[0] == 502
    assert order == ["build", "stop"]


def test_stopping_builds_kills_every_process_of_build_as_user(monkeypatch):
    monkeypatch.setenv("BUILD_AS_USER", "builder")
    monkeypatch.setattr(service, "_uid_of", lambda user: 999)
    alive = {101, 102}
    killed = []
    monkeypatch.setattr(service, "_live_pids_of", lambda uid: sorted(alive) if uid == 999 else [])

    def kill(pid, sig):
        killed.append((pid, sig))
        alive.discard(pid)

    monkeypatch.setattr(service.os, "kill", kill)

    service.stop_build_processes()

    assert sorted(killed) == [(101, service.signal.SIGKILL), (102, service.signal.SIGKILL)]
    assert alive == set()


def test_stopping_builds_does_nothing_without_build_as_user(monkeypatch):
    monkeypatch.delenv("BUILD_AS_USER", raising=False)
    monkeypatch.setattr(service, "_live_pids_of", lambda uid: pytest.fail("looked for processes"))

    service.stop_build_processes()


def test_build_processes_that_will_not_stop_fail_the_publish(monkeypatch):
    monkeypatch.setenv("BUILD_AS_USER", "builder")
    monkeypatch.setattr(service, "_uid_of", lambda user: 999)
    monkeypatch.setattr(service, "_live_pids_of", lambda uid: [101])
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(service, "STOP_WAIT_S", 0.2)

    with pytest.raises(service.StepFailed, match="builder"):
        service.stop_build_processes()


def test_reading_a_source_checks_out_no_working_tree(github, tmp_path):
    """A source read needs one file: the repo is cloned without blobs or checkout, and
    pyproject.toml is read from git, so a large repo is read as fast as a small one."""
    from plugin_publisher.sources import read_source
    github(REPO, {"main": (PACKAGE, "1.1.0"), "feat/unified-modules": (PACKAGE, "1.2.0")})
    dest = tmp_path / "read"

    assert read_source(REPO, dest) == ("feat/unified-modules", PACKAGE, "1.2.0")

    assert sorted(p.name for p in dest.iterdir()) == [".git"]


def test_the_source_read_clones_without_checkout_by_the_same_git_rules(client, github, git_calls):
    github(REPO, {"trunk": ("data-monitor", "0.4.1")}, default="trunk")

    assert client.get(f"/sources/{REPO}")[1]["version"] == "0.4.1"

    clones = [argv for argv in git_calls() if "clone" in argv]
    assert len(clones) == 1
    assert "--no-checkout" in clones[0] and "--filter=blob:none" in clones[0]
    assert any("show" in argv and "HEAD:pyproject.toml" in argv for argv in git_calls())


def test_a_source_without_a_pyproject_has_no_source(client, github, tmp_path):
    bare = github(REPO, {})
    assert bare.exists()
    assert client.get(f"/sources/{REPO}")[0] == 404
