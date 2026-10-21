"""scripts/start.sh on a scratch copy, with stand-in `docker` and `git` that record what they are asked and
fail on cue, and a stand-in sign-in page on a local port. Nothing is built or started.

The one command a person installing the stack runs: it refuses a checkout that cannot
work (wrong branch, submodules missing, no Docker, an old Compose), makes the secrets, builds with up to
two retries (fewer builds at once on a retry), starts the stack and waits until the sign-in page
answers, so "compose went through" no longer ends on a 502.
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import threading

import pytest

from conftest import ROOT, copy_install_scripts

DOCKER = r"""#!/bin/sh
d=$(dirname "$0")/..
echo "$* | BAKE=${COMPOSE_BAKE:-} LIMIT=${COMPOSE_PARALLEL_LIMIT:-}" >> "$d/docker.log"
case "$1" in
  info) [ -f "$d/no-daemon" ] && exit 1; exit 0 ;;
  compose)
    case "$*" in
      *"version --short"*) cat "$d/compose-version"; exit 0 ;;
      *" config --format json"*) if [ -f "$d/config-answer" ]; then cat "$d/config-answer"; else echo '{"services": {}}'; fi
        exit 0 ;;
      *" build"*)
        n=$(cat "$d/build-failures" 2>/dev/null || echo 0)
        if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$d/build-failures"; echo "failed to solve" >&2; exit 1; fi
        exit 0 ;;
      *" up "*) exit 0 ;;
      *" ps "*) if [ -f "$d/ps-answer" ]; then cat "$d/ps-answer"; else echo "keycloak	exited (1)"; fi; exit 0 ;;
      *" exec "*) [ -f "$d/local-controls" ] || exit 1; cat "$d/local-controls"; exit 0 ;;
    esac ;;
  volume) [ -f "$d/has-data" ] && exit 0; exit 1 ;;
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

def sign_in_page(d):
    """The gateway as the start sees it: 502 while `not-ready` counts down (or for ever: `never`), then the
    sign-in's redirect."""
    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            ready = d / "not-ready"
            n = ready.read_text().strip() if ready.exists() else "0"
            if n != "never" and int(n) > 0:
                ready.write_text(str(int(n) - 1))
            self.send_response(502 if n == "never" or int(n) > 0 else 302)
            self.send_header("Location", "/sign-in")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def scratch(tmp_path):
    copy_install_scripts(tmp_path)
    shutil.copy(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    shims = tmp_path / "shims"
    shims.mkdir()
    for name, body in (("docker", DOCKER), ("git", GIT)):
        (shims / name).write_text(body)
        (shims / name).chmod(0o755)
    (tmp_path / "branch").write_text("feat/unified-modules\n")
    (tmp_path / "submodules").write_text(" 1a2b3c apps/backend (heads/feat/unified-modules)\n")
    (tmp_path / "compose-version").write_text("5.5.1\n")
    server = sign_in_page(tmp_path)
    (tmp_path / "url").write_text(f"http://127.0.0.1:{server.server_address[1]}/")
    yield tmp_path
    server.shutdown()


def run(d, **env_over):
    env = {**os.environ, "PATH": f"{d}/shims:{os.environ['PATH']}", "START_WAIT_S": "6", "START_POLL_S": "0",
           "START_MIN_DISK_GB": "0", "START_URL": (d / "url").read_text(), **env_over}
    return subprocess.run(["bash", str(d / "scripts/start.sh")], cwd=d, env=env, capture_output=True, text=True,
                          timeout=60)


def calls(d):
    return (d / "docker.log").read_text().splitlines() if (d / "docker.log").exists() else []


def test_a_good_checkout_is_built_started_and_waited_for(scratch):
    (scratch / "not-ready").write_text("2")          # the gateway answers 502 twice, then the sign-in
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (scratch / "env.secrets").exists() and (scratch / "env.runtime").exists()
    log = calls(scratch)
    builds = [c for c in log if " build" in c]
    ups = [c for c in log if " up " in c]
    assert len(builds) == 1 and len(ups) == 1 and log.index(builds[0]) < log.index(ups[0])
    for c in builds + ups:
        assert "-p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml" in c
        assert "-f docker-compose-infra.development.yml -f docker-compose.development.yml" in c
    assert "up -d" in ups[0]
    assert (scratch / "url").read_text().rstrip("/") in r.stdout and "private window" in r.stdout


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
    assert not (scratch / "env.secrets").exists()
    assert not [c for c in calls(scratch) if " build" in c or " up " in c]


def test_it_says_which_local_controls_every_catalogue_gets(scratch):
    (scratch / "local-controls").write_text("altai-x\nfraia-y\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    asked = [c for c in calls(scratch) if " exec " in c]
    assert len(asked) == 1 and "exec -T platform python -m platform_service.catalogue" in asked[0]
    assert "2 local controls" in r.stdout and "altai-x" in r.stdout and "fraia-y" in r.stdout


def test_local_controls_it_cannot_read_do_not_stop_the_start(scratch):
    r = run(scratch)                                  # the exec fails: no local-controls file
    assert r.returncode == 0, r.stdout + r.stderr
    assert "local controls could not be read" in r.stdout and "AISC is up" in r.stdout


def test_a_one_shot_that_failed_is_named_after_the_sign_in_answers(scratch):
    """Plugin-publisher exits 1 naming the plugins it could not build, but nothing waits on it, so
    `up -d` returns 0 and the script said "AISC is up" with the plugin missing from the index."""
    (scratch / "ps-answer").write_text("plugin-publisher\tExited (1) 5 seconds ago\n"
                                       "report-grants\tExited (0) 9 seconds ago\n"
                                       "platform\tUp 2 minutes (healthy)\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    warnings = [line for line in r.stdout.splitlines() if "Warning" in line]
    assert any("plugin-publisher" in w for w in warnings), r.stdout
    assert not any("report-grants" in w or "platform" in w for w in warnings), r.stdout
    assert "docker compose -p aisc logs plugin-publisher" in r.stdout


def test_no_failed_one_shot_no_warning(scratch):
    (scratch / "ps-answer").write_text("report-grants\tExited (0) 9 seconds ago\nplatform\tUp 2 minutes\n")
    r = run(scratch)
    assert r.returncode == 0 and "did not finish" not in r.stdout


def test_a_taken_port_stops_start_before_anything_is_built(scratch):
    """A person learns of a taken port in seconds, not after the whole build."""
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        (scratch / "config-answer").write_text(json.dumps({"services": {"postgres": {"ports": [
            {"host_ip": "127.0.0.1", "published": str(port), "target": 5432}]}}}))
        r = run(scratch)
    assert r.returncode == 1
    assert f"Port {port} is taken" in r.stderr
    assert not [c for c in calls(scratch) if " build" in c]


def test_start_keeps_the_engine_settings_it_chose(scratch):
    """env.local holds the engine's port and address, and compose reads them through env.runtime."""
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    local = (scratch / "env.local").read_text().splitlines()
    assert [l.split("=", 1)[0] for l in local] == ["ENGINE_PORT", "ENGINE_HTTPS_PORT", "API_URL_EXTERNAL"]
    assert (scratch / "env.runtime").read_text().splitlines()[-3:] == local
