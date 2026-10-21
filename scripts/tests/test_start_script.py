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
  ps) [ -f "$d/held-ports" ] && cat "$d/held-ports"; exit 0 ;;
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
           "START_MIN_DISK_GB": "0", "START_URL": (d / "url").read_text(),
           "START_SIGN_IN_URL": (d / "url").read_text() + "realms/aisc", **env_over}
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
