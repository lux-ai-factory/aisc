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
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading

import pytest

from conftest import RUN_KCADM_IN_EXEC, ROOT, add_fake_kcadm, copy_install_scripts

DOCKER = r"""#!/bin/sh
d=$(dirname "$0")/..
# one line per call, whatever the arguments hold (a script passed to bash -c has newlines)
printf '%s' "$* | BAKE=${COMPOSE_BAKE:-} LIMIT=${COMPOSE_PARALLEL_LIMIT:-}" | tr '\n' ' ' >> "$d/docker.log"
echo >> "$d/docker.log"
[ "$1" = exec ] && [ -f "$d/exec-fails" ] && { echo "Error response from daemon" >&2; exit 1; }
# A build or up, as Docker runs it with a credential helper: `<step>-credentials-fail` makes the helper named in
# the config fail (a config without one passes; `credentials-always-fail`: that one too). Each such call, and
# the Docker config it ran with, goes to steps.log; a config other than the user's is copied to seen-config.json.
helper_step() {
  printf '%s | CFG=%s\n' "$1" "${DOCKER_CONFIG:-}" >> "$d/steps.log"
  if [ -n "${DOCKER_CONFIG:-}" ] && [ "$DOCKER_CONFIG" != "$(cd "$d" && pwd)/user-docker" ]; then
    cp "$DOCKER_CONFIG/config.json" "$d/seen-config.json"
    [ -e "$DOCKER_CONFIG/cli-plugins/docker-compose" ] && touch "$d/seen-compose-plugin"
  fi
  [ -f "$d/$1-says" ] && { cat "$d/$1-says" >&2; exit 1; }
  if [ -f "$d/$1-credentials-fail" ]; then
    if [ -f "$d/credentials-always-fail" ] || grep -q credsStore "${DOCKER_CONFIG:-$d/none}/config.json" 2>/dev/null; then
      echo 'error getting credentials - err: exit status 1, out: ``' >&2; exit 1
    fi
  fi
}
""" + RUN_KCADM_IN_EXEC + r"""
case "$1" in
  info) [ -f "$d/no-daemon" ] && exit 1
        case "$*" in *SystemTime*) [ -f "$d/docker-time" ] && cat "$d/docker-time" ;; esac
        exit 0 ;;
  compose)
    case "$*" in
      *"version --short"*) cat "$d/compose-version"; exit 0 ;;
      *" config --format json"*) if [ -f "$d/config-answer" ]; then cat "$d/config-answer"; else echo '{"services": {}}'; fi
        exit 0 ;;
      *" build"*)
        helper_step build
        n=$(cat "$d/build-failures" 2>/dev/null || echo 0)
        if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$d/build-failures"; echo "failed to solve" >&2; exit 1; fi
        exit 0 ;;
      *" ps -a --status created"*) [ -f "$d/created-fails" ] && exit 1
        [ -f "$d/created-answer" ] && cat "$d/created-answer"; exit 0 ;;
      *" rm "*) exit 0 ;;
      *" up "*) helper_step up; [ -f "$d/up-fails" ] && exit 1; exit 0 ;;
      *" ps -q keycloak"*) if [ -f "$d/keycloak-id" ]; then cat "$d/keycloak-id"; else echo kc-of-this-project; fi
        exit 0 ;;
      *" config --services"*) [ -f "$d/services-answer" ] && cat "$d/services-answer"; exit 0 ;;
      *" logs "*) [ -f "$d/logs-hangs" ] && exec sleep 5
        # honours --tail N as Docker does
        for last; do :; done; n=all; case "$*" in *"--tail "*) n=$(echo "$*" | sed 's/.*--tail \([0-9]*\).*/\1/') ;; esac
        [ -f "$d/logs-$last" ] && { if [ "$n" = all ]; then cat "$d/logs-$last"; else tail -n "$n" "$d/logs-$last"; fi; }
        exit 0 ;;
      *" ps "*)
        # ps-answer-1, ps-answer-2 ... are the answers of the first, second ... call; later calls get ps-answer
        n=$(( $(cat "$d/ps-calls" 2>/dev/null || echo 0) + 1 )); echo $n > "$d/ps-calls"
        [ -f "$d/ps-answer-$n" ] && { cat "$d/ps-answer-$n"; exit 0; }
        if [ -f "$d/ps-answer" ]; then cat "$d/ps-answer"; else echo "keycloak	Up 2 minutes"; fi; exit 0 ;;
      *" exec "*) [ -f "$d/local-controls" ] || exit 1; cat "$d/local-controls"; exit 0 ;;
    esac ;;
  inspect) for last; do :; done
           # `restarts-<container>` holds that container's RestartCount; `inspect-<container>` its FinishedAt
           case "$*" in *RestartCount*) [ -f "$d/restarts-$last" ] && cat "$d/restarts-$last"; exit 0 ;; esac
           [ -f "$d/inspect-$last" ] && cat "$d/inspect-$last"; exit 0 ;;
  volume) [ -f "$d/has-data" ] && exit 0; exit 1 ;;
  ps) case "$*" in *"name=^plugin-downloader$"*) [ -f "$d/old-downloader" ] && cat "$d/old-downloader"; exit 0 ;; esac
      [ -f "$d/held-ports" ] && cat "$d/held-ports"; exit 0 ;;
  image) [ -f "$d/no-probe-image" ] && exit 1; exit 0 ;;
  pull) [ -f "$d/pull-hangs" ] && exec sleep 5; exit 0 ;;
  run)
    # a port probe: `probe-fails` fails every one with its message; `probe-refuses` holds one -p spec
    # (0.0.0.0:80:) refused with the message in `probe-says`, as Docker refuses a port it cannot publish;
    # `probe-hangs`: a daemon too busy to answer
    [ -f "$d/probe-hangs" ] && exec sleep 5
    [ -f "$d/probe-fails" ] && { cat "$d/probe-fails" >&2; exit 125; }
    if [ -f "$d/probe-refuses" ]; then
      case "$*" in *"-p $(cat "$d/probe-refuses")"*) cat "$d/probe-says" >&2; exit 125 ;; esac
    fi
    exit 0 ;;
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

def sign_in_page(d, port=0):
    """The gateway as the start sees it: 502 while `not-ready` counts down (or for ever: `never`), then the
    sign-in's redirect. The realm's own page (/realms/...) answers 503 while `realm-not-ready` counts down (or
    for ever: `never`), then 200; every request's path is appended to `requests`, in the order it came."""
    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            with open(d / "requests", "a") as seen:
                seen.write(self.path + "\n")
            if self.path.startswith("/realms/"):
                realm = d / "realm-not-ready"
                left = realm.read_text().strip() if realm.exists() else "0"
                if left != "never" and int(left) > 0:
                    realm.write_text(str(int(left) - 1))
                self.send_response(503 if left == "never" or int(left) > 0 else 200)
                self.end_headers()
                return
            ready = d / "not-ready"
            n = ready.read_text().strip() if ready.exists() else "0"
            if n != "never" and int(n) > 0:
                ready.write_text(str(int(n) - 1))
            self.send_response(502 if n == "never" or int(n) > 0 else 302)
            self.send_header("Location", "/sign-in")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Page)
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
    add_fake_kcadm(shims)
    (tmp_path / "branch").write_text("feat/unified-modules\n")
    (tmp_path / "submodules").write_text(" 1a2b3c apps/backend (heads/feat/unified-modules)\n")
    (tmp_path / "compose-version").write_text("5.5.1\n")
    server = sign_in_page(tmp_path)
    (tmp_path / "url").write_text(f"http://127.0.0.1:{server.server_address[1]}/")
    yield tmp_path
    server.shutdown()


def run(d, **env_over):
    env = {**os.environ, "PATH": f"{d}/shims:{os.environ['PATH']}", "START_WAIT_S": "6", "START_POLL_S": "0",
           "START_MIN_DISK_GB": "0", "START_URL": (d / "url").read_text(),
           "START_SIGN_IN_URL": (d / "url").read_text() + "realms/aisc", **env_over}
    return subprocess.run(["bash", str(d / "scripts/start.sh")], cwd=d, env=env, capture_output=True, text=True,
                          timeout=60)


def calls(d):
    return (d / "docker.log").read_text().splitlines() if (d / "docker.log").exists() else []


def test_a_good_checkout_is_built_started_and_waited_for(scratch):
    (scratch / "not-ready").write_text("2")          # the gateway answers 502 twice, then the sign-in
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)   # whatever holds them on the test machine
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (scratch / "env.secrets").exists() and (scratch / "env.runtime").exists()
    log = calls(scratch)
    builds = [c for c in log if " build" in c]
    ups = [c for c in log if " up " in c]
    assert len(builds) == 1 and len(ups) == 1 and log.index(builds[0]) < log.index(ups[0])
    for c in builds + ups:
        assert "-p aisc --env-file env.runtime -f docker-compose-infra.development.yml " \
               "-f docker-compose.development.yml" in c
        assert "plugin_downloader" not in c
    assert "up -d" in ups[0]
    assert "AISC is up: open http://localhost:8100 " in r.stdout and "private window" in r.stdout


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
    (scratch / "ps-answer").write_text("keycloak\tCreated\n")      # neither restarting nor failed: just not running
    r = run(scratch, START_WAIT_S="1")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "keycloak" in out and "logs" in out


def test_aisc_is_not_up_until_the_realm_has_been_imported(scratch):
    """The launcher redirects to the sign-in before Keycloak has imported its realm; a person who follows at
    once gets no form. So the realm's own page must answer 200 first."""
    (scratch / "realm-not-ready").write_text("2")     # the realm answers 503 twice, then 200
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    realm = [p for p in (scratch / "requests").read_text().splitlines() if p.startswith("/realms/")]
    assert realm == ["/realms/aisc"] * 3
    assert "AISC is up" in r.stdout


def test_a_realm_that_never_answers_gives_a_warning_naming_keycloak_and_no_aisc_is_up(scratch):
    (scratch / "realm-not-ready").write_text("never")
    r = run(scratch, START_WAIT_S="1")
    assert r.returncode != 0
    assert "Keycloak" in r.stderr and "AISC is up" not in r.stdout


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
    """make_buckets exits 1 when it cannot make the buckets, but nothing waits on it, so `up -d`
    returns 0 and the script said "AISC is up" with nothing to store results in."""
    (scratch / "ps-answer").write_text("make_buckets\tExited (1) 5 seconds ago\n"
                                       "report-grants\tExited (0) 9 seconds ago\n"
                                       "platform\tUp 2 minutes (healthy)\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    warnings = [line for line in r.stdout.splitlines() if "Warning" in line]
    assert any("make_buckets" in w for w in warnings), r.stdout
    assert not any("report-grants" in w or "platform" in w for w in warnings), r.stdout
    assert "docker compose -p aisc logs make_buckets" in r.stdout


def test_no_failed_one_shot_no_warning(scratch):
    (scratch / "ps-answer").write_text("report-grants\tExited (0) 9 seconds ago\nplatform\tUp 2 minutes\n")
    r = run(scratch)
    assert r.returncode == 0 and "did not finish" not in r.stdout


def test_a_restarting_container_is_named_with_its_last_log_lines_and_start_stops_early(scratch):
    (scratch / "not-ready").write_text("never")
    (scratch / "ps-answer").write_text("minio\tRestarting (1) 4 seconds ago\tc-min\nplatform\tUp 2 minutes\n")
    (scratch / "restarts-c-min").write_text("5\n")
    (scratch / "logs-minio").write_text("".join(f"minio line {i}\n" for i in range(1, 31)))
    r = run(scratch, START_WAIT_S="60")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "minio" in out and "minio line 30" in out and "minio line 11" in out
    assert "minio line 10\n" not in out
    assert "docker compose -p aisc logs minio" in out
    assert any(" logs " in c and "--tail 20" in c and c.split("|")[0].split()[-1] == "minio" for c in calls(scratch))
    assert "AISC is up" not in out


def test_secrets_in_those_log_lines_are_hidden(scratch):
    (scratch / "env.secrets").write_text("S3_PASSWORD=plainvalue-4711\n")
    (scratch / "not-ready").write_text("never")
    (scratch / "ps-answer").write_text("minio\tRestarting (1) 4 seconds ago\tc-min\n")
    (scratch / "restarts-c-min").write_text("5\n")
    (scratch / "logs-minio").write_text("starting minio\nMINIO_ROOT_PASSWORD=abc123\n"
                                        "auth token: xyz789\nthe Secret is s3cr3t\nSOME_key=k1\n"
                                        "login failed for plainvalue-4711 at 10:00\nfatal: bad config\n")
    r = run(scratch, START_WAIT_S="60")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "starting minio" in out and "fatal: bad config" in out
    for hidden in ("abc123", "xyz789", "s3cr3t", "k1", "plainvalue-4711"):
        assert hidden not in out, hidden


def test_one_shots_that_finished_are_not_reported(scratch):
    (scratch / "ps-answer").write_text("make_buckets\tExited (0) 5 seconds ago\n"
                                       "ledger-pool\tExited (0) 9 seconds ago\n"
                                       "report-grants\tExited (1) 9 seconds ago\nplatform\tUp 2 minutes\n")
    (scratch / "logs-report-grants").write_text("grants failed\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "make_buckets" not in r.stdout and "ledger-pool" not in r.stdout
    assert "grants failed" not in r.stdout          # a failed one-shot keeps its warning, not the crash report


def test_a_container_that_restarts_once_and_recovers_does_not_stop_start(scratch):
    (scratch / "not-ready").write_text("2")
    (scratch / "ps-answer-1").write_text("minio\tRestarting (1) 4 seconds ago\n")
    (scratch / "ps-answer").write_text("minio\tUp 3 seconds\nplatform\tUp 2 minutes\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "AISC is up" in r.stdout


def test_a_container_restarting_on_two_polls_with_few_restarts_does_not_stop_start(scratch):
    """A service that crash-loops for a few seconds while a dependency comes up is normal on a slow machine."""
    (scratch / "not-ready").write_text("3")
    (scratch / "ps-answer").write_text("minio\tRestarting (1) 4 seconds ago\tc-min\nplatform\tUp 2 minutes\n")
    (scratch / "restarts-c-min").write_text("2\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "AISC is up" in r.stdout


def test_a_container_restarting_on_two_polls_with_five_restarts_stops_start(scratch):
    (scratch / "not-ready").write_text("3")
    (scratch / "ps-answer").write_text("minio\tRestarting (1) 4 seconds ago\tc-min\nplatform\tUp 2 minutes\n")
    (scratch / "restarts-c-min").write_text("5\n")
    (scratch / "logs-minio").write_text("minio: unknown flag\n")
    r = run(scratch)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "minio keeps restarting" in r.stdout + r.stderr and "AISC is up" not in r.stdout


@pytest.mark.parametrize("seconds_since_began, stops", [(89, False), (91, True)])
def test_a_container_restarting_for_over_ninety_seconds_stops_start_whatever_its_count(
        monkeypatch, seconds_since_began, stops):
    from datetime import datetime, timedelta, timezone
    aisc = aisc_module(monkeypatch)
    began = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(aisc, "docker_now", lambda: began + timedelta(seconds=seconds_since_began))
    monkeypatch.setattr(aisc, "docker_in_time", lambda argv, wait: subprocess.CompletedProcess(argv, 0, "2\n", ""))
    stuck, restarting = aisc.stuck_services("minio\tRestarting (1) 4 seconds ago\tc-min\n", {"minio"}, None, began)
    assert (stuck == ["minio"]) is stops and restarting == {"minio"}


def test_the_ninety_seconds_can_be_set_for_tests(monkeypatch):
    monkeypatch.setenv("START_RESTART_GRACE_S", "7")
    assert aisc_module(monkeypatch).RESTART_GRACE_S == 7


LONG_AGO, FAR_FUTURE = "2000-01-01T00:00:00.123456789Z", "2999-01-01T00:00:00.123456789Z"


def api_exited(scratch, finished_at, services="api\nplatform\n"):
    """`api` exited with an error at finished_at; the services this start has are `services`."""
    (scratch / "not-ready").write_text("never")
    (scratch / "services-answer").write_text(services)
    (scratch / "ps-answer").write_text("api\tExited (1) 3 seconds ago\tc-api\nplatform\tUp 2 minutes\tc-pl\n")
    (scratch / "inspect-c-api").write_text(finished_at + "\n")
    (scratch / "logs-api").write_text("api crashed: bad config\n")


def test_a_service_that_exits_with_an_error_during_this_start_is_named_and_stops_start(scratch):
    api_exited(scratch, FAR_FUTURE)
    r = run(scratch, START_WAIT_S="60")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "api crashed: bad config" in out and "docker compose -p aisc logs api" in out


@pytest.mark.parametrize("docker_time_zone", ["Z", "+02:00"])
def test_a_docker_clock_ahead_of_the_host_is_the_one_a_stop_is_judged_by(scratch, docker_time_zone):
    """WSL2 and Docker Desktop VM clocks drift by minutes: the reference time comes from Docker's own clock."""
    from datetime import datetime, timedelta, timezone

    def stamp(minutes, zone="Z"):
        """The instant `minutes` from now, written in the given zone as Docker writes it."""
        at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        if zone != "Z":
            at = at.astimezone(timezone(timedelta(hours=int(zone[:3]))))
        return at.strftime("%Y-%m-%dT%H:%M:%S.123456789") + zone

    (scratch / "docker-time").write_text(stamp(10, docker_time_zone) + "\n")           # Docker's clock runs 10 minutes ahead
    api_exited(scratch, stamp(5))                                       # after the host's time, before Docker's
    (scratch / "not-ready").write_text("1")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    api_exited(scratch, stamp(15))                                      # after Docker's time: this start's doing
    r = run(scratch, START_WAIT_S="60")
    assert r.returncode == 1 and "api crashed" in r.stdout + r.stderr


def test_an_exited_container_from_an_earlier_run_does_not_stop_start(scratch):
    api_exited(scratch, LONG_AGO)
    (scratch / "not-ready").write_text("1")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "api crashed" not in r.stdout + r.stderr


def test_a_container_of_a_service_not_in_this_start_does_not_stop_start(scratch):
    api_exited(scratch, FAR_FUTURE, services="platform\n")         # api: an inspect-profile or orphan container
    (scratch / "not-ready").write_text("1")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr


def aisc_module(monkeypatch):
    """scripts/aisc.py imported for a direct call of one function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("aisc_under_test", ROOT / "scripts" / "aisc.py")
    aisc = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "aisc_under_test", aisc)      # its dataclasses look the module up
    spec.loader.exec_module(aisc)
    return aisc


@pytest.mark.parametrize("text, utc", [
    ("2026-10-23T18:24:33.785320213+02:00", "2026-10-23T16:24:33.785320"),    # as `docker info` prints it here
    ("2026-10-23T18:24:33.785320213-05:00", "2026-10-23T23:24:33.785320"),
    ("2026-10-23T16:24:33.785320213Z", "2026-10-23T16:24:33.785320"),
    ("2026-10-23T16:24:33Z", "2026-10-23T16:24:33"),
])
def test_docker_times_in_any_offset_are_read_as_the_right_utc_instant(monkeypatch, text, utc):
    from datetime import datetime, timezone
    parsed = aisc_module(monkeypatch).parse_docker_time(text)
    assert parsed == datetime.fromisoformat(utc).replace(tzinfo=timezone.utc)


def test_docker_s_time_of_a_container_that_never_ran_is_long_before_any_start(monkeypatch):
    from datetime import datetime, timezone
    parsed = aisc_module(monkeypatch).parse_docker_time("0001-01-01T00:00:00Z")
    assert parsed is not None and parsed < datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert aisc_module(monkeypatch).parse_docker_time("not a time") is None


def test_a_missing_env_secrets_still_shows_the_report(tmp_path, monkeypatch):
    """The report must never crash on the file it hides values from: without it only the secret-word lines go."""
    aisc = aisc_module(monkeypatch)
    monkeypatch.chdir(tmp_path)                       # no env.secrets here
    assert aisc.hide_secrets("starting\nDB_PASSWORD=abc123\nfatal: bad config") == \
        "starting\n[a line naming a secret is hidden]\nfatal: bad config"
    (tmp_path / "env.secrets").mkdir()                # unreadable as a file
    assert "fatal: bad config" in aisc.hide_secrets("fatal: bad config")


def test_logs_that_docker_does_not_give_in_time_are_said_so_and_start_still_stops(scratch):
    (scratch / "not-ready").write_text("never")
    (scratch / "ps-answer").write_text("minio\tRestarting (1) 4 seconds ago\tc-min\n")
    (scratch / "restarts-c-min").write_text("5\n")
    (scratch / "logs-hangs").write_text("")
    r = run(scratch, START_WAIT_S="60", START_LOG_WAIT_S="1")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "no logs (Docker did not answer in time)" in out and "docker compose -p aisc logs minio" in out


def test_a_log_line_with_bytes_that_are_not_text_still_gives_the_report(scratch):
    (scratch / "not-ready").write_text("never")
    (scratch / "ps-answer").write_text("minio\tRestarting (1) 4 seconds ago\tc-min\n")
    (scratch / "restarts-c-min").write_text("5\n")
    (scratch / "logs-minio").write_bytes(b"starting minio\nbad bytes \xff\xfe here\nfatal: bad config\n")
    r = run(scratch, START_WAIT_S="60")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "Traceback" not in out and "UnicodeDecodeError" not in out
    assert "fatal: bad config" in out and "minio keeps restarting" in out


def test_a_service_that_keeps_restarting_is_named_even_when_up_itself_fails(scratch):
    """Others wait on minio's health, so compose's `up -d` fails with "container minio is unhealthy" and never
    reaches the waits: the report has to come before the refusal."""
    (scratch / "up-fails").write_text("")
    (scratch / "ps-answer").write_text("minio\tRestarting (3) 4 seconds ago\tc-min\nplatform\tCreated\tc-pl\n")
    (scratch / "logs-minio").write_text("minio: unknown flag\n")
    r = run(scratch, START_STUCK_RECHECK_S="0")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "minio keeps restarting" in out and "minio: unknown flag" in out
    assert "docker compose -p aisc logs minio" in out


def test_a_service_that_exited_with_an_error_is_named_even_when_up_itself_fails(scratch):
    (scratch / "up-fails").write_text("")
    (scratch / "ps-answer").write_text("minio\tExited (3) 4 seconds ago\tc-min\n")
    (scratch / "inspect-c-min").write_text(FAR_FUTURE + "\n")
    (scratch / "logs-minio").write_text("minio: unknown flag\n")
    r = run(scratch, START_STUCK_RECHECK_S="0")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "minio: unknown flag" in out and "docker compose -p aisc logs minio" in out


def test_an_up_that_fails_with_nothing_stuck_keeps_the_old_message(scratch):
    (scratch / "up-fails").write_text("")
    (scratch / "ps-answer").write_text("minio\tUp 2 seconds\tc-min\n")
    r = run(scratch, START_STUCK_RECHECK_S="0")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "the stack did not start: see the error above." in out
    assert "keeps restarting" not in out


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


#: what `docker ps` shows when this install's own Caddy and Keycloak hold the four browser ports
OWN_BROWSER_PORTS = ("0.0.0.0:80->8005/tcp, 0.0.0.0:8100->8006/tcp, 0.0.0.0:8188->8008/tcp\n"
                     "127.0.0.1:8081->8080/tcp\n")


def test_start_keeps_the_browser_ports_it_chose(scratch):
    """env.local holds the four browser ports, and compose reads them through env.runtime."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)   # whatever holds them on the test machine
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    local = (scratch / "env.local").read_text().splitlines()
    assert local == ["ENGINE_PORT=80", "HOMEPAGE_PORT_EXTERNAL=8100", "DASHBOARD_PORT_EXTERNAL=8188",
                     "KEYCLOAK_PORT_EXTERNAL=8081"]
    assert (scratch / "env.runtime").read_text().splitlines()[-len(local):] == local


def test_start_keeps_an_https_install_s_own_engine_address(scratch):
    """An install served over https names its engine itself; start must not replace it with localhost."""
    settings = (scratch / "env.plugin_downloader").read_text()
    settings = settings.replace('API_URL_EXTERNAL="http://localhost"', 'API_URL_EXTERNAL="https://aisc.example.org"')
    settings = settings.replace('CADDY_DOMAIN="http://localhost"', 'CADDY_DOMAIN="https://aisc.example.org"')
    (scratch / "env.plugin_downloader").write_text(settings)
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    engine = [line for line in (scratch / "env.runtime").read_text().splitlines() if line.startswith("API_URL_EXTERNAL=")]
    assert engine[-1] == 'API_URL_EXTERNAL="https://aisc.example.org"'


def test_an_https_install_with_a_port_kept_from_plain_http_keeps_its_own_address(scratch):
    """Its engine stays on the port it kept, but its public https address is the one compose uses, and start
    sends nobody to localhost."""
    settings = (scratch / "env.plugin_downloader").read_text()
    settings = settings.replace('API_URL_EXTERNAL="http://localhost"', 'API_URL_EXTERNAL="https://aisc.example.org"')
    settings = settings.replace('CADDY_DOMAIN="http://localhost"', 'CADDY_DOMAIN="https://aisc.example.org"')
    (scratch / "env.plugin_downloader").write_text(settings)
    (scratch / "env.local").write_text("ENGINE_PORT=8090\n")
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->", "0.0.0.0:8090->"))
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    runtime = (scratch / "env.runtime").read_text().splitlines()
    engine = [line for line in runtime if line.startswith("API_URL_EXTERNAL=")]
    assert engine[-1] == 'API_URL_EXTERNAL="https://aisc.example.org"'
    assert "ENGINE_PORT=8090" in (scratch / "env.local").read_text().splitlines()
    assert "open on http://localhost" not in r.stdout


def test_a_new_install_is_told_to_sign_in_as_admin_admin(scratch):
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sign in as admin / admin" in r.stdout


def test_an_install_with_its_own_passwords_is_not_told_admin_admin(scratch):
    """Passwords generated (https) or changed (rotate-infra-password): admin / admin would be refused."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    assert run(scratch).returncode == 0
    secrets = (scratch / "env.secrets").read_text()
    secrets = secrets.replace("AISC_ADMIN_PASSWORD=admin\n", "AISC_ADMIN_PASSWORD=Zq8-changed-by-its-admin\n")
    (scratch / "env.secrets").write_text(secrets)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "admin / admin" not in r.stdout
    assert "uv run scripts/aisc.py password" in r.stdout


def test_a_quoted_port_kept_in_env_local_is_honoured(scratch):
    """A person editing env.local may quote a value, as the other env files do."""
    (scratch / "env.local").write_text('ENGINE_PORT="8090"\nHOMEPAGE_PORT_EXTERNAL="8100"\n')
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    local = (scratch / "env.local").read_text().splitlines()
    assert "ENGINE_PORT=8090" in local and "HOMEPAGE_PORT_EXTERNAL=8100" in local


def test_what_a_person_added_to_env_local_survives_a_start(scratch):
    (scratch / "env.local").write_text("# my note\nENGINE_PORT=8090\nMY_SETTING=x\nENGINE_HTTPS_PORT=8453\n")
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (scratch / "env.local").read_text().splitlines() == [
        "# my note", "ENGINE_PORT=8090", "MY_SETTING=x", "ENGINE_HTTPS_PORT=8453",
        "API_URL_EXTERNAL=http://localhost:8090", "HOMEPAGE_PORT_EXTERNAL=8100", "DASHBOARD_PORT_EXTERNAL=8188",
        "KEYCLOAK_PORT_EXTERNAL=8081"]


def test_a_moved_port_is_announced_with_what_frees_a_leftover(scratch):
    """The launcher's kept port is now held by another program: it moves (here back to 8100, which this
    install's own stand-in holds), and start says so once, with what frees a port an earlier run left held."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    with socket.socket() as held:
        held.bind(("0.0.0.0", 0))
        held.listen()
        port = held.getsockname()[1]
        (scratch / "env.local").write_text(f"HOMEPAGE_PORT_EXTERNAL={port}\n"
                                           f"LAUNCHER_EXTERNAL_URL=http://localhost:{port}/\n")
        r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"Port {port} is taken" in r.stdout and "http://localhost:8100/" in r.stdout
    assert r.stdout.count("restarting Docker frees it") == 1
    local = (scratch / "env.local").read_text().splitlines()
    assert "HOMEPAGE_PORT_EXTERNAL=8100" in local and not [line for line in local if "LAUNCHER" in line]


def test_start_tells_the_sign_in_its_addresses_after_the_stack_is_up(scratch):
    """A port that moved after the realm was first imported would otherwise sign nobody in: Keycloak keeps the
    addresses it imported. So every start sends it the ones compose uses now (env.runtime, last line wins)."""
    (scratch / "env.local").write_text("ENGINE_PORT=8090\nAPI_URL_EXTERNAL=http://localhost:8090\n")
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->", "0.0.0.0:8090->"))
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls(scratch)
    up = next(i for i, c in enumerate(log) if " up " in c)
    told = [i for i, c in enumerate(log) if c.startswith("exec ") and " kc-of-this-project " in c]
    assert told and min(told) > up
    sent = (scratch / "exec-input").read_text()
    assert "http://localhost:8090/oauth2/callback" in sent and "http://localhost:8090/*" in sent
    assert "update clients/id-of-aisc-gateway" in "\n".join(log)
    admin = [line for line in (scratch / "env.secrets").read_text().splitlines()
             if line.startswith("KEYCLOAK_ADMIN_PASSWORD=")][0].split("=", 1)[1]
    assert admin not in (scratch / "docker.log").read_text()
    assert "AISC is up" in r.stdout


def test_start_stops_when_the_sign_in_cannot_be_told(scratch):
    (scratch / "exec-fails").write_text("")
    r = run(scratch, START_SYNC_TRIES="2", START_SYNC_WAIT_S="0")
    assert r.returncode == 1
    assert "could not be told" in r.stderr
    assert "AISC is up" not in r.stdout
    assert len([c for c in calls(scratch) if c.startswith("exec ") and " kc-of-this-project " in c]) == 2


def test_start_tells_this_project_s_keycloak_and_no_other(scratch):
    """A second copy beside an install (AISC_PROJECT and an override that renames its containers) must never
    tell the first one's Keycloak its addresses: the container is the one compose runs for this project."""
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    execs = [c for c in calls(scratch) if c.startswith("exec ")]
    assert execs and all(" kc-of-this-project bash " in c for c in execs)
    assert not [c for c in execs if " keycloak bash " in c]


def test_start_stops_when_this_project_runs_no_keycloak(scratch):
    (scratch / "keycloak-id").write_text("")
    r = run(scratch, START_SYNC_TRIES="2", START_SYNC_WAIT_S="0")
    assert r.returncode == 1
    assert "could not be told" in r.stderr and "AISC is up" not in r.stdout
    assert not [c for c in calls(scratch) if c.startswith("exec ")]


def test_no_secret_reaches_a_command_line_when_start_tells_the_sign_in(scratch):
    """Neither docker's command line on the host nor kcadm's inside the container (which the host's `ps`
    shows too): Keycloak's admin password reaches kcadm through KC_CLI_PASSWORD."""
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    secrets = [line.split("=", 1)[1] for line in (scratch / "env.secrets").read_text().splitlines()
               if "=" in line and not line.startswith("#")]
    for log in ("docker.log", "kcadm.log"):
        text = (scratch / log).read_text()
        assert not [v for v in secrets if len(v) >= 8 and v in text], log
    admin = [v for v in (scratch / "env.secrets").read_text().splitlines() if v.startswith("KEYCLOAK_ADMIN_PASSWORD=")]
    assert set((scratch / "kcadm-login").read_text().splitlines()) == {admin[0].split("=", 1)[1]}


def test_start_clears_containers_a_failed_attempt_left_created(scratch):
    """A refused start followed by a hand-run `docker compose up` leaves containers in state created, which
    then block the next start; start removes them before it brings the stack up."""
    (scratch / "created-answer").write_text("aisc-webapp\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls(scratch)
    removal = [c for c in log if c.startswith("compose ") and " rm -f " in c and "kcadm" not in c]
    ups = [c for c in log if " up " in c]
    assert len(removal) == 1 and " rm -f aisc-webapp" in removal[0], log
    assert log.index(removal[0]) < log.index(ups[0])


def test_start_removes_the_exited_plugin_downloader_an_old_install_left(scratch):
    """Plugins are fetched on install now, so the old one-shot container has no service: it would make
    compose warn about an orphan on every start. Only that container, only of this project."""
    (scratch / "old-downloader").write_text("abc123\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls(scratch)
    asked = [c for c in log if c.startswith("ps ") and "plugin-downloader" in c]
    assert len(asked) == 1 and "label=com.docker.compose.project=aisc" in asked[0], log
    removed = [c for c in log if c.startswith("rm ")]
    assert len(removed) == 1 and removed[0].startswith("rm -f abc123"), log
    assert log.index(removed[0]) < log.index([c for c in log if " up " in c][0])
    assert r.stdout.count("plugin download") == 1, r.stdout


def test_start_removes_nothing_when_no_plugin_downloader_is_left(scratch):
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not [c for c in calls(scratch) if c.startswith("rm ")]
    assert "plugin download" not in r.stdout


COMPOSE_OF_THE_STACK = ("compose -p aisc --env-file env.runtime "
                        "-f docker-compose-infra.development.yml -f docker-compose.development.yml")


def test_start_asks_compose_for_this_project_s_created_containers_only(scratch):
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    asked = [c for c in calls(scratch) if "--status created" in c]
    assert asked == [COMPOSE_OF_THE_STACK + " ps -a --status created --format {{.Service}} | BAKE= LIMIT="]
    assert not [c for c in calls(scratch) if c.startswith("compose ") and " rm " in c]
    assert "Removing what an earlier attempt left" not in r.stdout


def test_start_goes_on_when_compose_cannot_list_the_created_containers(scratch):
    (scratch / "created-fails").write_text("")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not [c for c in calls(scratch) if c.startswith("compose ") and " rm " in c]
    assert [c for c in calls(scratch) if " up -d" in c] and "AISC is up" in r.stdout


def test_a_refused_start_says_not_to_run_compose_directly(scratch):
    (scratch / "branch").write_text("master\n")
    r = run(scratch)
    assert r.returncode != 0
    assert "Nothing was started. Fix this and run start again, not docker compose directly." in r.stdout + r.stderr


HINT = "Nothing was started. Fix this and run start again, not docker compose directly."


def test_a_refusal_before_the_stack_starts_ends_with_the_hint_once(scratch):
    (scratch / "branch").write_text("master\n")
    r = run(scratch)
    assert (r.stdout + r.stderr).count(HINT) == 1


def test_the_build_refusal_tells_to_run_again_once(scratch):
    (scratch / "build-failures").write_text("3")
    r = run(scratch)
    said = r.stderr.lower()
    assert "build failed" in said and said.count("run ") == 1 and said.count("again") == 1, said


def test_the_sign_in_refusal_does_not_claim_nothing_was_started(scratch):
    (scratch / "exec-fails").write_text("")
    r = run(scratch, START_SYNC_TRIES="2", START_SYNC_WAIT_S="0")
    assert "could not be told" in r.stderr and "Nothing was started" not in r.stderr


def test_a_refusal_after_up_does_not_claim_nothing_was_started(scratch):
    (scratch / "up-fails").write_text("")
    r = run(scratch)
    assert r.returncode != 0
    assert "did not start" in r.stderr and "Nothing was started" not in r.stderr


def https_install(d, launcher='https://aisc.example.org:8100/'):
    """The scratch copy served over https at aisc.example.org, its launcher at the address given."""
    settings = (d / "env.plugin_downloader").read_text()
    settings = settings.replace('API_URL_EXTERNAL="http://localhost"', 'API_URL_EXTERNAL="https://aisc.example.org"')
    settings = settings.replace('CADDY_DOMAIN="http://localhost"', 'CADDY_DOMAIN="https://aisc.example.org"')
    settings = settings.replace("LAUNCHER_EXTERNAL_URL=http://localhost:8100/", f"LAUNCHER_EXTERNAL_URL={launcher}")
    (d / "env.plugin_downloader").write_text(settings)
    (d / "held-ports").write_text(OWN_BROWSER_PORTS)


def test_a_launcher_address_without_its_slash_is_used_with_one(scratch):
    """The realm import makes its sign-out rule and callback from LAUNCHER_EXTERNAL_URL as it is: compose must
    be given it with its slash, and so must the sign-in start tells."""
    https_install(scratch, launcher="https://aisc.example.org")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    launcher = [line for line in (scratch / "env.runtime").read_text().splitlines()
                if line.startswith("LAUNCHER_EXTERNAL_URL=")]
    assert launcher[-1] == "LAUNCHER_EXTERNAL_URL=https://aisc.example.org/"
    sent = (scratch / "exec-input").read_text()
    assert "https://aisc.example.org/oauth2/callback" in sent and "https://aisc.example.org/*##" in sent
    assert "aisc.example.orgoauth2" not in sent and "aisc.example.org*" not in sent


def test_an_https_install_s_sign_in_gets_no_development_server(scratch):
    https_install(scratch)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "5173" not in (scratch / "exec-input").read_text()


def test_a_plain_http_install_s_sign_in_keeps_the_development_server(scratch):
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    sent = (scratch / "exec-input").read_text()
    assert "http://localhost:5173/*" in sent and '"http://localhost:5173"' in sent


def page_on(d, port):
    """The stand-in sign-in page on 127.0.0.1:port, or a skip when this machine holds that port."""
    try:
        return sign_in_page(d, port)
    except OSError:
        pytest.skip(f"port {port} is held on this machine")


def test_a_moved_launcher_is_waited_on_and_announced_at_its_new_address(scratch):
    """8100 is held by another program, so the launcher moves to 8110: start waits on 8110, on this machine,
    and names it at the end, not the address the other program holds."""
    blocker = socket.socket()
    try:
        blocker.bind(("0.0.0.0", 8100))
        blocker.listen()
    except OSError:
        pass                                    # something on this machine holds it already: taken either way
    page = page_on(scratch, 8110)
    try:
        (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace(":8100->", ":8110->"))
        r = run(scratch, START_URL="", START_SIGN_IN_URL="http://127.0.0.1:8110/realms/aisc")
    finally:
        page.shutdown()
        page.server_close()
        blocker.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HOMEPAGE_PORT_EXTERNAL=8110" in (scratch / "env.local").read_text().splitlines()
    assert [p for p in (scratch / "requests").read_text().splitlines() if not p.startswith("/realms/")] == ["/"]
    assert "Waiting for the sign-in page at http://localhost:8110/" in r.stdout
    up = [line for line in r.stdout.splitlines() if line.startswith("AISC is up")]
    assert up and "open http://localhost:8110 " in up[-1], r.stdout


def test_a_refused_start_does_not_advise_running_compose(scratch):
    """start makes the secrets on its way; the secrets command's own advice (run the stack with docker
    compose ... up -d) is the very thing a refused start must not lead to."""
    (scratch / "build-failures").write_text("3")
    r = run(scratch)
    assert r.returncode != 0
    assert "run the stack with" not in r.stdout + r.stderr


@pytest.mark.parametrize("line", ["ENGINE_PORT=8090 # mine", "HOMEPAGE_PORT_EXTERNAL=70000",
                                  "KEYCLOAK_PORT_EXTERNAL=", "DASHBOARD_PORT_EXTERNAL=0", 'ENGINE_PORT="eighty"'])
def test_a_kept_port_that_is_not_a_port_is_refused_naming_its_line(scratch, line):
    """env.local is the file a person edits to choose a port; a value that is not one ends start with a message
    naming the line, not a traceback, and before anything is built."""
    (scratch / "env.local").write_text(f"# my ports\n{line}\n")
    r = run(scratch)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert f"env.local line 2 ({line})" in r.stderr and "a whole number from 1 to 65535" in r.stderr
    assert not [c for c in calls(scratch) if " build" in c]


def moved_install(d):
    """An install with data whose launcher and dashboard moved earlier (env.local keeps them), held by its own
    containers."""
    (d / "env.local").write_text("HOMEPAGE_PORT_EXTERNAL=8110\nLAUNCHER_EXTERNAL_URL=http://localhost:8110/\n"
                                 "DASHBOARD_PORT_EXTERNAL=8198\nDASHBOARD_EXTERNAL_URL=http://localhost:8198\n")
    (d / "held-ports").write_text(OWN_BROWSER_PORTS.replace(":8100->", ":8110->").replace(":8188->", ":8198->"))


def updates(d):
    """What each client update sent, by the client id it named, in the order kcadm was asked."""
    named = re.findall(r"^KCADM update clients/(\S+) ", (d / "kcadm.log").read_text(), re.M)
    sent = [json.loads(line) for line in (d / "exec-input").read_text().splitlines() if line.strip()]
    return list(zip(named, sent))


def test_each_client_is_sent_its_own_moved_addresses(scratch):
    moved_install(scratch)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    sent = dict(updates(scratch))
    assert set(sent) == {"id-of-aisc-gateway", "id-of-aisc-webapp"}
    gateway, webapp = sent["id-of-aisc-gateway"], sent["id-of-aisc-webapp"]
    assert gateway["redirectUris"] == ["http://localhost/oauth2/callback", "http://localhost:8110/oauth2/callback",
                                       "http://localhost:8198/oauth2/callback"]
    assert gateway["attributes"]["post.logout.redirect.uris"] == "http://localhost:8110/*##http://localhost/*"
    assert webapp["baseUrl"] == "http://localhost" and "8110" not in json.dumps(webapp)


def test_a_second_client_that_cannot_be_updated_stops_start(scratch):
    moved_install(scratch)
    (scratch / "update-fails").write_text("clients/id-of-aisc-webapp")
    r = run(scratch, START_SYNC_TRIES="2", START_SYNC_WAIT_S="0")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not be told" in r.stderr and "update refused" in r.stderr
    assert "AISC is up" not in r.stdout
    assert [client for client, _ in updates(scratch)] == ["id-of-aisc-gateway", "id-of-aisc-webapp"] * 2


def test_an_https_install_tells_the_sign_in_its_https_addresses_only(scratch):
    https_install(scratch)
    with open(scratch / "env.plugin_downloader", "a") as settings:
        settings.write("DASHBOARD_EXTERNAL_URL=https://aisc.example.org:8188\n")
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    sent = dict(updates(scratch))
    assert sent["id-of-aisc-gateway"]["redirectUris"] == [
        "https://aisc.example.org/oauth2/callback", "https://aisc.example.org:8100/oauth2/callback",
        "https://aisc.example.org:8188/oauth2/callback"]
    assert sent["id-of-aisc-webapp"]["baseUrl"] == "https://aisc.example.org"
    assert "localhost" not in (scratch / "exec-input").read_text()


def tls_launcher(d, public_name):
    """The launcher's Caddy listener on an install served over https, on a port of its own: TLS for the public
    name only. A request over TLS whose SNI and Host are that name gets the sign-in's 302; any other TLS request
    a 421; a plain-HTTP one a 400, as Caddy answers it. Each request is noted in `tls-requests`. The certificate
    is a throwaway self-signed one, made with openssl."""
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj",
                    f"/CN={public_name}", "-keyout", str(d / "tls.key"), "-out", str(d / "tls.crt")],
                   check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(d / "tls.crt", d / "tls.key")
    seen = {}
    context.sni_callback = lambda _sock, name, _ctx: seen.__setitem__("sni", name)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def answer(conn):
        with conn:
            conn.settimeout(5)
            if conn.recv(1, socket.MSG_PEEK) != b"\x16":           # not a TLS handshake
                conn.recv(65536)
                (d / "tls-requests").open("a").write("plain http\n")
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n"
                             b"Client sent an HTTP request to an HTTPS server.\n")
                return
            seen.clear()
            with context.wrap_socket(conn, server_side=True) as tls:
                request = tls.recv(65536).decode("latin-1")
                host = next((line.split(":", 1)[1].strip() for line in request.split("\r\n")
                             if line.lower().startswith("host:")), "")
                (d / "tls-requests").open("a").write(f"tls sni={seen.get('sni')} host={host}\n")
                ok = seen.get("sni") == public_name and host == public_name
                tls.sendall(b"HTTP/1.1 302 Found\r\nLocation: /sign-in\r\nContent-Length: 0\r\n\r\n" if ok
                            else b"HTTP/1.1 421 Misdirected Request\r\nContent-Length: 0\r\n\r\n")

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            try:
                answer(conn)
            except (OSError, ssl.SSLError):
                pass

    threading.Thread(target=serve, daemon=True).start()
    return listener


def test_an_https_install_is_waited_on_over_tls_for_its_public_name(scratch):
    """The launcher's listener on an https install serves TLS for the public name only: a plain-HTTP request
    gets a 400, and start would wait until it gives up. It asks over TLS, with that name, on this machine."""
    https_install(scratch)
    listener = tls_launcher(scratch, "aisc.example.org")
    port = listener.getsockname()[1]
    try:
        (scratch / "env.local").write_text(f"HOMEPAGE_PORT_EXTERNAL={port}\n")
        (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace(":8100->", f":{port}->"))
        r = run(scratch, START_URL="", START_WAIT_S="4")
    finally:
        listener.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tls sni=aisc.example.org host=aisc.example.org" in (scratch / "tls-requests").read_text()
    up = [line for line in r.stdout.splitlines() if line.startswith("AISC is up")]
    assert up and "open https://aisc.example.org:8100 " in up[-1], r.stdout


def host_sees_free(d, *ports):
    """The host's own check (port_is_free) finds these ports free, whatever holds them on the test machine: a
    bind succeeds and nothing answers. Docker's VM is where they are taken, as on Docker Desktop."""
    (d / "pyshim").mkdir()
    (d / "pyshim/sitecustomize.py").write_text(f"""import errno, socket
FREE = {set(ports)!r}
bind, connect_ex = socket.socket.bind, socket.socket.connect_ex
socket.socket.bind = lambda self, address: None if address[1] in FREE else bind(self, address)
socket.socket.connect_ex = (lambda self, address: errno.ECONNREFUSED if address[1] in FREE
                            else connect_ex(self, address))
""")
    return {"PYTHONPATH": str(d / "pyshim")}


WINDOWS_REFUSAL = ("Error response from daemon: ports are not available: exposing port TCP 0.0.0.0:80 -> "
                   "127.0.0.1:0: /forwards/expose returned unexpected status: 500")
LEFTOVER_FORWARDER = ("docker: Error response from daemon: driver failed programming external connectivity on "
                      "endpoint aisc-port-probe-80: Bind for 0.0.0.0:80 failed: port is already allocated.")


@pytest.mark.parametrize("refusal", [WINDOWS_REFUSAL, LEFTOVER_FORWARDER])
def test_a_port_docker_cannot_publish_moves_before_anything_is_built(scratch, refusal):
    """On Docker Desktop a port can be held inside Docker's own VM (a web server in WSL, a leftover forwarder)
    where a bind on the host does not see it: the host check passes, and `up` fails after the whole build.
    Docker itself is asked first, so the engine moves to 8080 before anything is built."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->8005/tcp, ", ""))
    (scratch / "probe-refuses").write_text("0.0.0.0:80:")
    (scratch / "probe-says").write_text(refusal)
    r = run(scratch, **host_sees_free(scratch, 80, 8080))
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls(scratch)
    probes = [c for c in log if c.startswith("run ") and " -p 0.0.0.0:80:" in c]
    builds = [c for c in log if " build" in c]
    assert probes and builds and log.index(probes[0]) < log.index(builds[0])
    out = r.stdout.splitlines()
    moved = [line for line in out if line.startswith("Port 80 is taken")]
    assert moved and "http://localhost:8080" in moved[0]
    assert out.index(moved[0]) < next(i for i, line in enumerate(out) if line.startswith("Building the images"))
    assert "ENGINE_PORT=8080" in (scratch / "env.local").read_text().splitlines()
    assert [c for c in log if " up " in c] and "AISC is up" in r.stdout


def test_a_probe_docker_cannot_run_leaves_the_host_check_to_decide(scratch):
    """No image offline, or a Docker error that says nothing of the port: the host's answer stands, the start
    goes on, and nothing moves."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->8005/tcp, ", ""))
    (scratch / "probe-fails").write_text("Unable to find image 'caddy:2.10.2' locally\ndocker: Error response "
                                         "from daemon: pull access denied for caddy, repository does not exist")
    r = run(scratch, **host_sees_free(scratch, 80, 8080))
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c for c in calls(scratch) if c.startswith("run ") and " -p 0.0.0.0:80:" in c]
    assert "is taken" not in r.stdout + r.stderr
    assert "ENGINE_PORT=80" in (scratch / "env.local").read_text().splitlines()
    assert "AISC is up" in r.stdout


def test_ports_this_install_holds_are_not_probed(scratch):
    """Its own running containers hold them: a probe would be refused, and they are not taken. Any other
    published port is asked of Docker."""
    with socket.socket() as spare:
        spare.bind(("127.0.0.1", 0))
        other = spare.getsockname()[1]
    (scratch / "config-answer").write_text(json.dumps({"services": {"postgres": {"ports": [
        {"host_ip": "127.0.0.1", "published": str(other), "target": 5432}]}}}))
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS)
    r = run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    probes = [c for c in calls(scratch) if c.startswith("run ") and " -p " in c]
    for held in (80, 8100, 8188, 8081):
        assert not [c for c in probes if f":{held}:" in c], probes
    assert [c for c in probes if f"-p 127.0.0.1:{other}:" in c], probes


def test_a_pull_of_the_probe_image_that_hangs_leaves_the_host_check_to_decide(scratch):
    """A first start behind a slow link: the probe's image is fetched once, said before it starts, and a fetch
    that does not finish in time is given up; the start goes on with the host's own check."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->8005/tcp, ", ""))
    (scratch / "no-probe-image").write_text("")
    (scratch / "pull-hangs").write_text("")
    r = run(scratch, START_PULL_WAIT_S="1", **host_sees_free(scratch, 80, 8080))
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout.splitlines()
    fetching = next(i for i, line in enumerate(out) if line.startswith("Fetching the image the port check uses"))
    assert fetching < out.index("Docker could not check the ports itself; going by this computer's own check.")
    assert not [c for c in calls(scratch) if c.startswith("run ") and " -p " in c]
    assert "ENGINE_PORT=80" in (scratch / "env.local").read_text().splitlines()


def test_after_a_probe_that_hangs_no_other_port_is_probed(scratch):
    """A busy Docker Desktop would make each probe wait its full time: after the first that does not answer,
    the host's own check decides for the rest of the start."""
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->8005/tcp, ", "")
                                        .replace("0.0.0.0:8100->8006/tcp, ", ""))
    (scratch / "probe-hangs").write_text("")
    r = run(scratch, START_PROBE_WAIT_S="1", **host_sees_free(scratch, 80, 8100))
    assert r.returncode == 0, r.stdout + r.stderr
    assert len([c for c in calls(scratch) if c.startswith("run ") and " -p " in c]) == 1
    assert r.stdout.count("Docker could not check the ports itself") == 1


def test_a_port_docker_refuses_on_an_https_install_names_docker_not_the_host(scratch):
    """Nothing on the host holds it, so the host's tools (netstat, lsof) would show nothing: the refusal says
    Docker cannot use the port, and what frees one Docker holds."""
    https_install(scratch)
    (scratch / "held-ports").write_text(OWN_BROWSER_PORTS.replace("0.0.0.0:80->8005/tcp, ", ""))
    (scratch / "probe-refuses").write_text("0.0.0.0:80:")
    (scratch / "probe-says").write_text(WINDOWS_REFUSAL)
    r = run(scratch, **host_sees_free(scratch, 80))
    assert r.returncode == 1
    assert "Port 80 is taken" in r.stderr and "Docker cannot use it" in r.stderr
    assert "restarting Docker" in r.stderr
    assert "lsof" not in r.stderr and "netstat" not in r.stderr


# ---------------------------------------------------------------------------------- a broken credential helper

#: what a registry login looks like in config.json: user:password in base64, never to be shown
LOGIN = "dXNlcjpzZWNyZXQtcGFzc3dvcmQ="


def users_docker_config(d):
    """The person's Docker config, as Docker Desktop's WSL integration writes it: a credential helper that fails,
    a registry login, the Compose plugin among its own cli-plugins."""
    config = d / "user-docker"
    (config / "cli-plugins").mkdir(parents=True)
    (config / "cli-plugins/docker-compose").write_text("")
    (config / "config.json").write_text(json.dumps({
        "credsStore": "desktop.exe", "credHelpers": {"gcr.io": "gcloud"},
        "auths": {"registry.example.org": {"auth": LOGIN}}, "currentContext": "default"}, indent=1))
    return config


def steps(d, step):
    """(the Docker config each `step` call ran with), in order."""
    log = (d / "steps.log").read_text().splitlines() if (d / "steps.log").exists() else []
    return [line.split(" | CFG=")[1] for line in log if line.startswith(step + " ")]


@pytest.mark.parametrize("step", ["build", "up"])
def test_a_step_that_fails_on_the_credential_helper_is_run_once_more_without_it(scratch, step):
    user = users_docker_config(scratch)
    before = (user / "config.json").read_bytes()
    (scratch / f"{step}-credentials-fail").write_text("")
    r = run(scratch, DOCKER_CONFIG=str(user))
    assert r.returncode == 0, r.stdout + r.stderr
    ran_with = steps(scratch, step)
    assert len(ran_with) == 2 and ran_with[0] == str(user)
    retried_with = ran_with[1]
    assert retried_with and retried_with != str(user)
    seen = json.loads((scratch / "seen-config.json").read_text())
    assert "credsStore" not in seen and "credHelpers" not in seen
    assert seen["auths"] == {"registry.example.org": {"auth": LOGIN}} and seen["currentContext"] == "default"
    assert (scratch / "seen-compose-plugin").exists()
    assert (user / "config.json").read_bytes() == before
    assert not os.path.exists(retried_with)
    assert ("Docker's credential helper (desktop.exe) failed; pulled without it for this run. To fix it for good: "
            in r.stdout)
    assert LOGIN not in r.stdout + r.stderr


@pytest.mark.parametrize("step", ["build", "up"])
def test_an_unrelated_pull_failure_is_not_retried(scratch, step):
    user = users_docker_config(scratch)
    (scratch / f"{step}-says").write_text("Error response from daemon: pull access denied for aisc/nothing\n")
    r = run(scratch, DOCKER_CONFIG=str(user))
    assert r.returncode != 0
    assert set(steps(scratch, step)) == {str(user)}
    assert "credential helper" not in r.stdout + r.stderr
    assert "pull access denied" in r.stderr


@pytest.mark.parametrize("step", ["build", "up"])
def test_only_one_retry(scratch, step):
    """The person's config is tried once: after the helper failed, every later run of the step (the build's own
    retries, with fewer builds at once) goes without it, in the same temporary config."""
    user = users_docker_config(scratch)
    (scratch / f"{step}-credentials-fail").write_text("")
    (scratch / "credentials-always-fail").write_text("")
    r = run(scratch, DOCKER_CONFIG=str(user))
    assert r.returncode != 0
    ran_with = steps(scratch, step)
    assert ran_with[0] == str(user) and str(user) not in ran_with[1:]
    assert len(ran_with) == (4 if step == "build" else 2)
    assert len(set(ran_with[1:])) == 1
    assert "pulled without it" not in r.stdout
    assert (r.stdout + r.stderr).count("credential helper (desktop.exe) failed") == 1
    assert not os.path.exists(ran_with[1])


def test_after_the_helper_failed_the_builds_retries_keep_going_without_it(scratch):
    """A slow network on top of a broken helper: the retry without the helper times out, and the build's next
    attempt still goes without the helper, in the same temporary config, rather than fail on it at once."""
    user = users_docker_config(scratch)
    (scratch / "build-credentials-fail").write_text("")
    (scratch / "build-failures").write_text("1")     # the first run without the helper fails on the network
    r = run(scratch, DOCKER_CONFIG=str(user))
    assert r.returncode == 0, r.stdout + r.stderr
    builds = steps(scratch, "build")
    assert len(builds) == 3 and builds[0] == str(user)
    assert builds[1] == builds[2] != str(user)
    assert steps(scratch, "up") == [builds[1]]
    assert r.stdout.count("Docker's credential helper (desktop.exe) failed; pulled without it for this run.") == 1
    assert not os.path.exists(builds[1])


def test_a_bypassed_build_is_followed_by_an_up_without_the_helper_and_one_line(scratch):
    user = users_docker_config(scratch)
    (scratch / "build-credentials-fail").write_text("")
    (scratch / "up-credentials-fail").write_text("")
    r = run(scratch, DOCKER_CONFIG=str(user))
    assert r.returncode == 0, r.stdout + r.stderr
    builds = steps(scratch, "build")
    assert len(builds) == 2 and steps(scratch, "up") == [builds[1]]
    assert (r.stdout + r.stderr).count("Docker's credential helper (desktop.exe) failed") == 1
    assert not os.path.exists(builds[1])


def test_the_temporary_config_is_gone_when_start_fails_after_the_bypass(scratch):
    user = users_docker_config(scratch)
    (scratch / "build-credentials-fail").write_text("")
    (scratch / "up-fails").write_text("")
    r = run(scratch, DOCKER_CONFIG=str(user))
    assert r.returncode != 0 and "did not start" in r.stderr
    folder = steps(scratch, "build")[1]
    assert steps(scratch, "up") == [folder]
    assert not os.path.exists(folder)
