"""scripts/verify-port-fallback.sh: a whole copy of AISC started with its default browser ports taken, then signed
into on the ports it moved to. It builds and starts a stack, so here it is only read and run against a stand-in
`docker` that records what it is asked: it must refuse to run beside an install (the compose files fix the
container names), always clean up after itself, and never remove another install's data."""
import os
import re
import subprocess

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-port-fallback.sh"

#: a docker that answers `ps` with the names in `names` and records every call in `docker.log`
DOCKER = r"""#!/bin/sh
d=$(dirname "$0")/..
printf '%s\n' "$*" >> "$d/docker.log"
case "$1" in
  info) exit 0 ;;
  ps) [ -f "$d/names" ] && cat "$d/names"; exit 0 ;;
  inspect) printf 'aisc\t%s\n' "$d/elsewhere"; exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def fake_docker(tmp_path):
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "docker").write_text(DOCKER)
    (shims / "docker").chmod(0o755)
    return tmp_path


def run(d, *args):
    env = {**os.environ, "PATH": f"{d}/shims:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=d, env=env, capture_output=True, text=True, timeout=60)


def calls(d):
    log = d / "docker.log"
    return log.read_text().splitlines() if log.exists() else []


def test_the_check_refuses_beside_a_running_install(fake_docker):
    (fake_docker / "names").write_text("caddy\nsome-other-container\n")
    r = run(fake_docker)
    assert r.returncode == 2, r.stdout + r.stderr
    said = r.stdout + r.stderr
    assert "caddy" in said and "--take-down-running" in said
    assert "some-other-container" not in said
    # nothing was taken down, started or removed
    assert all(c.split()[0] in ("ps", "inspect", "info") for c in calls(fake_docker)), calls(fake_docker)


def test_the_check_runs_beside_containers_that_are_not_aiscs(fake_docker):
    """Only AISC's own container names stop it: a dry run beside an unrelated container lists its steps."""
    (fake_docker / "names").write_text("some-other-container\n")
    r = run(fake_docker, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "aisc-ports" in r.stdout and "AISC_IMAGE_TAG=ports" in r.stdout


def test_a_dry_run_changes_nothing(fake_docker):
    (fake_docker / "names").write_text("caddy\n")
    r = run(fake_docker, "--dry-run", "--take-down-running")
    assert r.returncode == 0, r.stdout + r.stderr
    for step in ("new install, every default taken", "install with data, its port taken later",
                 "leftover of a failed attempt", "ports nobody uses"):
        assert step in r.stdout
    assert "take down" in r.stdout and "caddy" in r.stdout
    assert all(c.split()[0] in ("ps", "inspect", "info") for c in calls(fake_docker)), calls(fake_docker)


def test_the_help_names_every_option():
    r = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    for option in ("--take-down-running", "--keep", "--dry-run", "--clean-up"):
        assert option in r.stdout


def test_an_unknown_option_is_refused():
    r = subprocess.run(["bash", str(SCRIPT), "--no-such-option"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2


def _function(text, name):
    m = re.search(rf"^{name}\(\) \{{[^\n]*\n(.*?)^\}}", text, re.S | re.M)
    assert m, f"no function {name}"
    return m.group(1)


def test_the_check_always_cleans_up():
    text = SCRIPT.read_text()
    trap = re.search(r"^\s*trap '?(\w+)'? EXIT", text, re.M)
    assert trap, "no trap on EXIT"
    body = _function(text, trap.group(1))
    # the trap may hand the work to one function the --clean-up option runs as well
    called = re.findall(r"^\s*(\w+)\b", body, re.M)
    for name in called:
        if re.search(rf"^{name}\(\) \{{", text, re.M):
            body += _function(text, name)
    assert "standin" in body and "rm -f" in body, "the stand-ins are not removed"
    assert re.search(r"aisc-ports.*down -v|copy_compose down -v", body), "the copy is not taken down with its volumes"
    assert ":ports" in body and "rmi" in body, "the copy's images are not removed"
    assert "rm -rf" in body, "the clone is not removed"
    assert "aisc.py start" in body, "a stack taken down is not brought back"


def test_the_check_never_touches_another_install_s_data():
    text = SCRIPT.read_text()
    compose = _function(text, "copy_compose")
    assert "-p aisc-ports" in compose and len(re.findall(r"-p ", compose)) == 1
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    removing = [line for line in lines if re.search(r"down\b.*\s-v\b|volume rm|volume prune", line)]
    assert removing, "the copy's data is never removed"
    for line in removing:
        assert "aisc-ports" in line or line.lstrip().startswith("copy_compose"), line
    # the running stack is taken down without its volumes
    for line in lines:
        if re.search(r"\bdown\b", line) and "aisc-ports" not in line and "copy_compose" not in line:
            assert not re.search(r"\s-v\b|--volumes", line), line


def test_verify_sh_runs_the_check_with_its_options():
    r = subprocess.run(["bash", str(ROOT / "scripts/verify.sh"), "--port-fallback", "--help"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "--take-down-running" in r.stdout
