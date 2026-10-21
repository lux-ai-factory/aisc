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

#: a docker that records every call in `docker.log` (its arguments, then the folder it ran in). `ps` answers the
#: names in `names` until a stack was taken down; `inspect` answers the compose labels of an install in
#: `install/`; `image ls` answers by reference only when asked for one (`-q` gets an id shared with :latest).
DOCKER = r"""#!/bin/sh
d=$(cd "$(dirname "$0")/.." && pwd)
printf '%s | cwd=%s\n' "$*" "$PWD" >> "$d/docker.log"
case "$1" in
  info) exit 0 ;;
  ps) [ -f "$d/names" ] && [ ! -f "$d/taken-down" ] && cat "$d/names"; exit 0 ;;
  inspect) printf 'aisc\t%s\t%s\t%s\n' "$d/install" "$d/install/env.runtime" \
             "$d/install/docker-compose.one.yml,$d/install/docker-compose.two.yml"; exit 0 ;;
  image)
    case "$*" in
      *" -q"*) echo 3f2a1b0c9d8e ;;
      *"reference=aisc-ports-"*) echo "aisc-ports-schema-docs:latest" ;;
      *"reference=aisc-*:ports"*) printf 'aisc-backend:ports\naisc-webapp:ports\n' ;;
    esac
    exit 0 ;;
  compose)
    case "$*" in *"-p aisc "*" down"*) touch "$d/taken-down" ;; esac
    exit 0 ;;
esac
exit 0
"""

#: git and uv that fail and record that they were called: the copy is never cloned or started here
FAILING = r"""#!/bin/sh
printf '%s\n' "$*" >> "$(dirname "$0")/../$(basename "$0").log"
exit 1
"""


@pytest.fixture
def fake_docker(tmp_path):
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "docker").write_text(DOCKER)
    (shims / "docker").chmod(0o755)
    (tmp_path / "install").mkdir()
    return tmp_path


def run(d, *args, failing=()):
    for name in failing:
        (d / "shims" / name).write_text(FAILING)
        (d / "shims" / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{d}/shims:{os.environ['PATH']}", "TMPDIR": str(d)}
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
    assert "up -d --no-build" in body, "a stack taken down is not brought back"


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


def kept_copy(d, name="aisc-ports.kept"):
    """A folder as the check leaves it with --keep: in its temporary folder, with the state file it writes."""
    work = d / name
    work.mkdir()
    (work / "taken-down").write_text("")
    return work


@pytest.mark.parametrize("given", [
    lambda d: d / "aisc-ports.kept" / ".." / "..",          # matches */aisc-ports.* and is the folder above
    lambda d: d / "elsewhere" / "aisc-ports.kept",           # not in the check's temporary folder
    lambda d: d / "aisc-ports.kept" / "aisc-ports.inner",   # not directly in it
    lambda d: d / "aisc-ports.unmarked",                      # never written by the check
])
def test_clean_up_refuses_a_folder_the_check_did_not_make(fake_docker, given):
    """--clean-up removes the folder given: only one the check made, directly in its temporary folder and
    holding its state file, whatever the path looks like."""
    kept = kept_copy(fake_docker)
    (fake_docker / "elsewhere").mkdir()
    kept_copy(fake_docker / "elsewhere")
    kept_copy(kept, "aisc-ports.inner")
    (fake_docker / "aisc-ports.unmarked").mkdir()
    r = run(fake_docker, "--clean-up", str(given(fake_docker)))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not a folder this check made" in r.stderr
    assert kept.is_dir() and (fake_docker / "elsewhere/aisc-ports.kept").is_dir()
    assert (kept / "aisc-ports.inner").is_dir() and (fake_docker / "aisc-ports.unmarked").is_dir()
    assert not calls(fake_docker), calls(fake_docker)


def test_the_copy_s_images_are_removed_by_their_ports_tag_only(fake_docker):
    """An image id can be shared with the install's :latest (same commit, warm cache): removing by id, or with -f,
    would take the install's images too. Only the copy's own references go, and an image in use stays."""
    work = kept_copy(fake_docker)
    r = run(fake_docker, "--clean-up", str(work))
    assert r.returncode == 0, r.stdout + r.stderr
    removed = [c.split(" | ")[0].split()[1:] for c in calls(fake_docker) if c.startswith("rmi ")]
    assert removed, calls(fake_docker)
    names = [a for args in removed for a in args]
    assert "-f" not in names and "--force" not in names
    assert sorted(names) == ["aisc-backend:ports", "aisc-ports-schema-docs:latest", "aisc-webapp:ports"]
    assert not work.exists()


def test_a_stack_taken_down_comes_back_exactly_as_it_ran(fake_docker):
    """Taken down and brought back from its own folder with its own compose files and env file, as its containers'
    labels say: no rebuild from the folder's current files, no port moved, no branch check (aisc.py start would
    do all three), and its volumes kept."""
    (fake_docker / "names").write_text("caddy\n")
    r = run(fake_docker, "--take-down-running", failing=("git", "uv"))
    assert r.returncode == 1, r.stdout + r.stderr          # the copy cannot be cloned here: the check fails
    install = fake_docker / "install"
    stack = (f"compose -p aisc --env-file {install}/env.runtime -f {install}/docker-compose.one.yml "
             f"-f {install}/docker-compose.two.yml")
    log = calls(fake_docker)
    down = [c for c in log if c.startswith(stack + " down")]
    up = [c for c in log if c.startswith(stack + " up")]
    assert down == [f"{stack} down | cwd={install}"], log
    assert up == [f"{stack} up -d --no-build | cwd={install}"], log
    assert log.index(down[0]) < log.index(up[0])
    assert not [c for c in log if c.startswith("compose -p aisc ") and c not in down + up], log
    assert not (fake_docker / "uv.log").exists(), "aisc.py was run"
    assert "aisc.py" not in r.stdout + r.stderr


@pytest.mark.parametrize("log, spoke", [
    ("#12 writing image sha256:9c05432ab1e5432f0 done\n#14 0.5432s\nAISC is up: open http://localhost:8110\n", False),
    ("Port 80 is taken on this computer, so AISC uses http://localhost:8080 instead\nAISC is up\n", False),
    ("Port 5432 is taken. Stop the program that holds it (see which with: ss -ltnp 'sport = :5432').\n", True),
    ("Port 5432 is taken on this computer, so AISC uses http://localhost:5433 instead\n", True),
    ("Ports 80, 5432 are all taken. Free one of them\n", True),
])
def test_only_start_s_own_port_messages_count_as_speaking_of_a_port(tmp_path, log, spoke):
    """A build log is full of digests and timings; 5432 inside one says nothing about the port."""
    (tmp_path / "start.log").write_text(log)
    body = _function(SCRIPT.read_text(), "start_spoke_of_port")
    r = subprocess.run(["bash", "-c", f"start_spoke_of_port() {{\n{body}}}\nstart_spoke_of_port 5432 \"$1\"", "_",
                        str(tmp_path / "start.log")], capture_output=True, text=True, timeout=30)
    assert (r.returncode == 0) == spoke, r.stdout + r.stderr


def _workflow(name):
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    return data.get("on", data.get(True)), data["jobs"]


def test_the_check_runs_in_its_own_workflow_by_hand_and_weekly():
    """A full build is too long for every push; and a workflow-wide schedule in ci.yml would run every module's
    jobs weekly as well."""
    triggers, _ = _workflow("ci.yml")
    assert "schedule" not in triggers and "workflow_dispatch" not in triggers
    triggers, jobs = _workflow("port-fallback.yml")
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    runs = [step.get("run", "") for job in jobs.values() for step in job["steps"]]
    assert any("scripts/verify-port-fallback.sh" in run for run in runs)


def test_keep_says_the_copy_is_kept_as_the_last_scenario_left_it():
    """The copy kept is the one the last scenario left, on moved ports (the engine moved twice): the help and the
    message at the end say so, give every address, and the exact command that removes it."""
    r = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30)
    keep = next(line for line in r.stdout.splitlines() if "--keep" in line)
    assert "last scenario" in keep and "moved" in keep, keep
    body = _function(SCRIPT.read_text(), "on_exit")
    assert "last scenario" in body
    for setting in ("API_URL_EXTERNAL", "LAUNCHER_EXTERNAL_URL", "DASHBOARD_EXTERNAL_URL", "KEYCLOAK_URL_EXTERNAL"):
        assert setting in body, setting
    assert "verify-port-fallback.sh --clean-up $WORK" in body
