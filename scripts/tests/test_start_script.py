"""scripts/start.sh on a scratch copy, with stand-in `docker`, `git` and `curl` that record what they are
asked and fail on cue. Nothing is built or started.

The one command a workshop participant runs (workshop 2026-10-06): it refuses a checkout that cannot
work (wrong branch, submodules missing, no Docker, an old Compose), makes the secrets, builds with up to
two retries (fewer builds at once on a retry), starts the stack and waits until the sign-in page
answers, so "compose went through" no longer ends on a 502.
"""
import os
import shutil
import subprocess

import pytest

from conftest import ROOT

DOCKER = r"""#!/bin/sh
d=$(dirname "$0")/..
echo "$* | BAKE=${COMPOSE_BAKE:-} LIMIT=${COMPOSE_PARALLEL_LIMIT:-}" >> "$d/docker.log"
case "$1" in
  info) [ -f "$d/no-daemon" ] && exit 1; exit 0 ;;
  compose)
    case "$*" in
      *"version --short"*) cat "$d/compose-version"; exit 0 ;;
      *" build"*)
        n=$(cat "$d/build-failures" 2>/dev/null || echo 0)
        if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$d/build-failures"; echo "failed to solve" >&2; exit 1; fi
        exit 0 ;;
      *" up "*) exit 0 ;;
      *" ps "*) echo "keycloak	exited (1)"; exit 0 ;;
    esac ;;
esac
exit 0
"""

GIT = r"""#!/bin/sh
d=$(dirname "$0")/..
case "$*" in
  *"rev-parse --abbrev-ref HEAD"*) cat "$d/branch" ;;
  *"submodule status"*) cat "$d/submodules" ;;
esac
"""

CURL = r"""#!/bin/sh
d=$(dirname "$0")/..
n=$(cat "$d/not-ready" 2>/dev/null || echo 0)
if [ "$n" = never ]; then printf 502; exit 0; fi
if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$d/not-ready"; printf 502; exit 0; fi
printf 302
"""


@pytest.fixture
def scratch(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/start.sh", tmp_path / "scripts/start.sh")
    (tmp_path / "scripts/secrets.sh").write_text(f"#!/bin/sh\necho ran > {tmp_path}/secrets-ran\n: > env.runtime\n")
    (tmp_path / "scripts/secrets.sh").chmod(0o755)
    shims = tmp_path / "shims"
    shims.mkdir()
    for name, body in (("docker", DOCKER), ("git", GIT), ("curl", CURL)):
        (shims / name).write_text(body)
        (shims / name).chmod(0o755)
    (tmp_path / "branch").write_text("feat/unified-modules\n")
    (tmp_path / "submodules").write_text(" 1a2b3c apps/backend (heads/feat/unified-modules)\n")
    (tmp_path / "compose-version").write_text("5.5.1\n")
    return tmp_path


def run(d, **env_over):
    env = {**os.environ, "PATH": f"{d}/shims:{os.environ['PATH']}", "START_WAIT_S": "6", "START_POLL_S": "0",
           "START_MIN_DISK_GB": "0", **env_over}
    return subprocess.run(["bash", str(d / "scripts/start.sh")], cwd=d, env=env, capture_output=True, text=True,
                          timeout=60)


def calls(d):
    return (d / "docker.log").read_text().splitlines() if (d / "docker.log").exists() else []


def test_a_good_checkout_is_built_started_and_waited_for(scratch):
    (scratch / "not-ready").write_text("2")          # the gateway answers 502 twice, then the sign-in
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (scratch / "secrets-ran").exists()
    log = calls(scratch)
    builds = [c for c in log if " build" in c]
    ups = [c for c in log if " up " in c]
    assert len(builds) == 1 and len(ups) == 1 and log.index(builds[0]) < log.index(ups[0])
    for c in builds + ups:
        assert "-p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml" in c
        assert "-f docker-compose-infra.development.yml -f docker-compose.development.yml" in c
    assert "up -d" in ups[0]
    assert "http://localhost:8100" in r.stdout and "private window" in r.stdout


def test_a_failed_build_is_tried_twice_more_with_fewer_builds_at_once(scratch):
    (scratch / "build-failures").write_text("2")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    builds = [c for c in calls(scratch) if " build" in c]
    assert len(builds) == 3
    assert builds[0].endswith("BAKE= LIMIT=")
    assert all(b.endswith("BAKE=false LIMIT=2") for b in builds[1:])
    assert "again" in r.stdout


def test_three_failed_builds_stop_before_starting_anything(scratch):
    (scratch / "build-failures").write_text("3")
    r = run(scratch)
    assert r.returncode != 0
    assert not [c for c in calls(scratch) if " up " in c]
    assert "build failed" in (r.stdout + r.stderr).lower()


def test_a_stack_that_never_answers_says_what_is_not_running(scratch):
    (scratch / "not-ready").write_text("never")
    r = run(scratch, START_WAIT_S="1")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "keycloak" in out and "logs" in out


@pytest.mark.parametrize("setup, says", [
    (lambda d: (d / "branch").write_text("master\n"), "feat/unified-modules"),
    (lambda d: (d / "submodules").write_text("-1a2b3c apps/backend\n"), "git submodule update --init --recursive"),
    (lambda d: (d / "compose-version").write_text("2.12.0\n"), "2.17"),
    (lambda d: (d / "no-daemon").write_text(""), "Docker is not running"),
])
def test_a_checkout_that_cannot_work_is_refused_before_anything_runs(scratch, setup, says):
    setup(scratch)
    r = run(scratch)
    assert r.returncode != 0
    assert says in r.stdout + r.stderr
    assert not (scratch / "secrets-ran").exists()
    assert not [c for c in calls(scratch) if " build" in c or " up " in c]
