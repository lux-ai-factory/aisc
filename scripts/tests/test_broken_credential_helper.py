"""A Docker credential helper that fails, on real Docker: aisc.py start runs the failed step once more without it.

Docker Desktop's WSL integration writes "credsStore": "desktop.exe" into ~/.docker/config.json inside WSL, and
Docker asks that helper even for public images; when it fails, every pull fails with `error getting credentials`.
Here the same failure is made on Linux: a docker-credential-broken on PATH that exits 1 with nothing to say, named
by a temporary DOCKER_CONFIG. The person's own ~/.docker is never read or written. alpine:latest is pulled; it is
removed afterwards only when it was not here before.
"""
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import aisc_py

#: a registry login (user:password in base64) on a registry this test never pulls from
LOGIN = base64.b64encode(b"someone:not-a-real-password").decode()
LOGINS = {"registry.example.invalid": {"auth": LOGIN}}
IMAGE = "alpine:latest"


def docker(*argv, env=None):
    return subprocess.run(["docker", *argv], capture_output=True, text=True, env=env, timeout=300)


@pytest.fixture
def broken_helper(tmp_path):
    """(the environment a person with a broken helper runs in, their Docker config folder)"""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    if docker("info").returncode != 0:
        pytest.skip("Docker is not running")
    helpers = tmp_path / "bin"
    helpers.mkdir()
    (helpers / "docker-credential-broken").write_text("#!/bin/sh\nexit 1\n")
    (helpers / "docker-credential-broken").chmod(0o755)
    config = tmp_path / "docker-config"
    config.mkdir()
    (config / "config.json").write_text(json.dumps({"credsStore": "broken", "auths": LOGINS}, indent=1))
    env = {**os.environ, "PATH": f"{helpers}{os.pathsep}{os.environ['PATH']}", "DOCKER_CONFIG": str(config)}
    no_helper = tmp_path / "no-helper"
    no_helper.mkdir()
    (no_helper / "config.json").write_text("{}")
    had_image = docker("image", "inspect", IMAGE).returncode == 0
    if docker("pull", IMAGE, env={**env, "DOCKER_CONFIG": str(no_helper)}).returncode != 0:
        pytest.skip(f"{IMAGE} cannot be pulled here (no network or no registry)")
    broken = docker("pull", IMAGE, env=env)
    assert broken.returncode != 0 and "error getting credentials" in broken.stderr, broken.stderr
    yield env, config
    if not had_image:
        docker("image", "rm", IMAGE)


@pytest.fixture
def retry_seen(monkeypatch):
    """aisc.py, with what each run of a step saw recorded: its DOCKER_CONFIG, that folder's config.json, and
    whether `docker compose` answered with it."""
    m = aisc_py()
    real = m.run_and_watch
    seen = []

    def watched(argv, env=None):
        folder = (env or os.environ).get("DOCKER_CONFIG", "")
        config = Path(folder, "config.json")
        compose = docker("compose", "version", env=env)
        seen.append({"folder": folder, "config": json.loads(config.read_text()) if config.is_file() else None,
                     "compose": compose.returncode == 0})
        return real(argv, env)

    monkeypatch.setattr(m, "run_and_watch", watched)
    yield m, seen
    m.end_helper_bypass()      # as start does when it ends


def test_the_pull_is_retried_without_the_helper_and_succeeds(broken_helper, retry_seen, capsys):
    env, config = broken_helper
    m, seen = retry_seen
    code, bypassed = m.run_step(["docker", "pull", IMAGE], env)
    assert code == 0 and bypassed
    assert [run["folder"] == str(config) for run in seen] == [True, False]
    out = capsys.readouterr()
    assert "Docker's credential helper (broken) failed; pulled without it for this run. To fix it for good: " in out.out
    assert LOGIN not in out.out + out.err


def test_the_users_config_is_not_edited(broken_helper, retry_seen):
    env, config = broken_helper
    m, _ = retry_seen
    before = {path.name: path.read_bytes() for path in config.iterdir()}
    m.run_step(["docker", "pull", IMAGE], env)
    assert {path.name: path.read_bytes() for path in config.iterdir()} == before


def test_registry_logins_are_kept_in_the_retry(broken_helper, retry_seen):
    env, _ = broken_helper
    m, seen = retry_seen
    m.run_step(["docker", "pull", IMAGE], env)
    retry = seen[1]
    assert retry["config"] == {"auths": LOGINS}
    assert retry["compose"], "docker compose is not found with the temporary config"


def test_the_temporary_config_is_deleted(broken_helper, retry_seen):
    """It serves every later step of the same start, and goes when the start ends (end_helper_bypass)."""
    env, _ = broken_helper
    m, seen = retry_seen
    m.run_step(["docker", "pull", IMAGE], env)
    m.run_step(["docker", "pull", IMAGE], env)
    assert seen[2]["folder"] == seen[1]["folder"] and os.path.isdir(seen[1]["folder"])
    m.end_helper_bypass()
    assert not os.path.exists(seen[1]["folder"])


def test_the_temporary_config_is_deleted_when_the_retry_fails_too(broken_helper, retry_seen, capsys):
    env, _ = broken_helper
    m, seen = retry_seen
    code, bypassed = m.run_step(["docker", "pull", "aisc-no-such-registry.invalid/nothing:here"], env)
    assert code != 0 and bypassed
    m.end_helper_bypass()
    assert len(seen) == 2 and not os.path.exists(seen[1]["folder"])
    out = capsys.readouterr()
    assert "pulled without it" not in out.out
    assert "credential helper (broken) failed" in out.err


@pytest.mark.parametrize("kind, says", [
    ("wsl", 'remove "credsStore"'),
    ("wsl", '"desktop.exe" with Docker Desktop running'),
    ("macos", "keychain"),
    ("linux", "docker-credential-broken"),
    ("windows", "Docker Desktop"),
])
def test_the_fix_named_suits_the_machine(kind, says):
    assert says in aisc_py().credential_helper_fix(kind, "broken", Path("/home/someone/.docker/config.json"))


@pytest.mark.parametrize("helper", ["desktop.exe", "desktop"])
def test_a_wsl_helper_that_is_already_docker_desktop_is_not_told_to_use_it(helper):
    line = aisc_py().credential_helper_fix("wsl", helper, Path("/home/someone/.docker/config.json"))
    assert "start Docker Desktop and turn on WSL integration for this distribution" in line
    assert 'remove credsStore from /home/someone/.docker/config.json' in line
    assert 'set it to "desktop.exe"' not in line
