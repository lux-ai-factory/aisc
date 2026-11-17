"""start, stop and remove: the stack brought up and waited on (a service that keeps failing named with its log
lines), stopped, or deleted with its data."""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .docker import (DOCKER_CALL_WAIT_S, LOG_TAIL_LINES, LOG_WAIT_S, Stack, captured, docker_in_time, docker_now,
                     end_helper_bypass, find_docker, finished_after, run_program, run_step)
from .keycloak import keycloak_realm_url, sync_sign_in
from .ports import (TAKEN_IN_DOCKER, free_for_docker, held_by_aisc, kept_ports_not_ports, local_lines,
                    prepare_port_probe, published_ports, settle_ports)
from .secrets import hide_secrets, make_postgres_tls, make_secrets, warn_known_account_passwords, write_runtime
from .settings import (COMPOSE, LOCAL, NO_DOCKER, OUT, ROOT, Refused, configurator, effective, install_id, lines_of,
                       project, read_local, say, served_over_https, settings_file, text_of, use_configurator, value_in,
                       warn, with_slash, write_beside)


#: True once start has handed the stack to compose `up`; a refusal after that point cannot say "nothing was started".
STACK_BEING_STARTED = False


def failing_services(ps_json: str) -> list[str]:
    """The services `compose ps -a --format json` shows unhealthy, or exited with an error, in the order listed.
    Compose prints one object per line, older versions one array: both are read; anything else names none."""
    text = ps_json.strip()
    try:
        parsed = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines()]
    except ValueError:
        return []
    return [entry["Service"] for entry in parsed
            if isinstance(entry, dict) and entry.get("Service")
            and (entry.get("Health") == "unhealthy"
                 or (entry.get("State") == "exited" and entry.get("ExitCode") not in (0, None)))]


def show_failing_logs(stack: Stack) -> None:
    """After a failed `up`, the last lines of each failing service, secrets hidden: compose names only the
    dependency that failed, the cause is in that service's own log. Says nothing when Docker does not answer."""
    listed = stack.call([*stack.compose, "ps", "-a", "--format", "json"], DOCKER_CALL_WAIT_S)
    if listed is None or listed.returncode != 0:
        return
    for service in failing_services(listed.stdout):
        shown = stack.logs(service, 20, DOCKER_CALL_WAIT_S)
        if shown is None:
            continue
        warn(f"--- {service}: its last log lines ---", *shown.splitlines())


def other_stacks(ps_output: str, own: str) -> list[tuple[str, str]]:
    """The running stacks other than own, from `project<TAB>working_dir` lines: each once, in the order seen."""
    found: list[tuple[str, str]] = []
    for line in ps_output.splitlines():
        project, _, folder = line.partition("\t")
        if project and project != own and (project, folder) not in found:
            found.append((project, folder))
    return found


def another_install_refusal(stack: str, folder: str) -> str:
    return (f"another AISC install is running from {folder} (stack {stack}). Only one runs at a time: stop it with  "
            f"docker compose -p {stack} stop  (its data is kept), then run start again.")


# --------------------------------------------------------------------------------------------------- start

BRANCH = "pilot"


def answer_of(url: str) -> int | None:
    """The HTTP status of one request, redirects not followed: a 302 to the sign-in is an answer."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(url, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def answer_over_tls(port: int, public_name: str) -> int | None:
    """The HTTP status of `GET /` on this machine's port over TLS, asked as a browser asks for the public name
    (SNI and Host), redirects not followed; None when nothing answers. An install served over https listens
    there for its public name only: plain HTTP gets a 400, another name no site. The certificate is not checked:
    the listener is this machine's own, and a development one signs its certificate itself (tls internal)."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection(("localhost", port), timeout=5) as raw, \
                context.wrap_socket(raw, server_hostname=public_name) as tls:
            tls.sendall(f"GET / HTTP/1.1\r\nHost: {public_name}\r\nConnection: close\r\n\r\n".encode())
            response = http.client.HTTPResponse(tls)
            response.begin()
            return response.status
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        return None


#: services that run once and exit (restart "no"): finished with code 0 is their good end, so they are never
#: reported as stopped; one that exited non-zero keeps its own warning at the end of start
ONE_SHOT_SERVICES = frozenset({
    "make_buckets", "postgres-setup", "immudb-key", "ledger-pool", "report-grants", "aisc-backend-migrate",
    "controls-migrate", "qualification-migrate", "control-objectives-migrate", "report-composer-migrate",
    "dashboard-migrate", "minio-data-owner", "devpi-data-owner", "rabbitmq-setup", "postgres-tls",
})


#: the pause between the two polls made after a failed `up -d`
STUCK_RECHECK_S = float(os.environ.get("START_STUCK_RECHECK_S", "2"))


#: in the wait loops, a container seen restarting on two polls is stuck only once Docker has restarted it this
#: many times (its backoff starts at 100 ms and doubles, so a few restarts are a dependency not yet up) ...
CRASH_LOOP_RESTARTS = 5
#: ... or once this many seconds have passed on Docker's clock since this start began
RESTART_GRACE_S = float(os.environ.get("START_RESTART_GRACE_S", "90"))


def crash_looping(container: str, began_at: datetime) -> bool:
    """Whether a container seen restarting on two polls has been at it long enough to be stuck: Docker has
    restarted it CRASH_LOOP_RESTARTS times (RestartCount), or RESTART_GRACE_S have passed since began_at on
    Docker's clock. A count Docker does not give in time counts as none."""
    said = docker_in_time([Stack.docker, "inspect", "--format", "{{.RestartCount}}", container], DOCKER_CALL_WAIT_S) \
        if container else None
    if said and said.returncode == 0 and said.stdout.strip().isdigit() \
            and int(said.stdout.strip()) >= CRASH_LOOP_RESTARTS:
        return True
    return (docker_now() - began_at).total_seconds() > RESTART_GRACE_S


def warn_unfinished(stack: Stack, this_start: set[str] | None, began_at: datetime) -> None:
    """At the end of start: each service that exited non-zero during it. A one-shot (make_buckets, report-grants,
    the migrations) is not waited on by everything, so `up -d` went through and the sign-in answers without it."""
    for service, status in stack.failing(this_start, began_at):
        say(f"Warning: {service} did not finish ({status}). See why with: docker compose -p {project()} logs {service}")


def stuck_services(ps_lines: str, was_restarting: set[str], this_start: set[str] | None, began_at: datetime,
                   after_failed_up: bool = False) -> tuple[list[str], set[str]]:
    """(the services to report, the services restarting now), from lines of `service TAB status TAB container`.
    Only this start's services count (this_start; None when compose would not list them): the project also holds
    containers of removed services, which `up -d` leaves as they are.
    A container that restarts once and then stays up is normal (it waited for a dependency), so a restarting
    one counts only when it was restarting on the poll before as well and, in the wait loops, has also restarted
    CRASH_LOOP_RESTARTS times or been at it for RESTART_GRACE_S since began_at (crash_looping): a service waiting
    for a dependency on a slow machine restarts a few times. After a failed `up` (after_failed_up) compose has
    already failed, so two polls are enough. A service that exited non-zero counts at
    once if it stopped after this start began (an earlier run's exit is not this start's problem) and is not
    a one-shot."""
    restarting, stuck = set(), []
    for line in ps_lines.splitlines():
        service, _, rest = line.partition("\t")
        status, _, container = rest.partition("\t")
        if this_start is not None and service not in this_start:
            continue
        if status.lower().startswith("restarting"):
            restarting.add(service)
            if service in was_restarting and (after_failed_up or crash_looping(container, began_at)):
                stuck.append(service)
        elif (re.match(r"exited \([1-9]", status.lower()) and service not in ONE_SHOT_SERVICES
              and container and finished_after(container, began_at)):
            stuck.append(service)
    return stuck, restarting


def refuse_if_stuck(was_restarting: set[str], this_start: set[str] | None, began_at: datetime,
                    after_failed_up: bool = False) -> set[str]:
    """Called on every poll of start and once at its end: names each container that keeps restarting or died,
    with its last log lines, and stops start at once instead of waiting out the whole timeout."""
    ps = captured([*COMPOSE, "ps", "-a", "--format", "{{.Service}}\t{{.Status}}\t{{.ID}}"])
    stuck, restarting = stuck_services(ps.stdout, was_restarting, this_start, began_at, after_failed_up)
    if not stuck:
        return restarting
    for service in stuck:
        logs = docker_in_time([*COMPOSE, "logs", "--tail", str(LOG_TAIL_LINES), service], LOG_WAIT_S)
        shown = hide_secrets(logs.stdout + logs.stderr) if logs else "no logs (Docker did not answer in time)"
        warn(f"{service} keeps restarting or has stopped. Its last {LOG_TAIL_LINES} log lines:", shown,
             f"See all of it with: docker compose -p {project()} logs {service}")
    raise Refused(f"{', '.join(stuck)} keeps restarting or has stopped, so the stack cannot come up. "
                  "Fix what the lines above say, then run start again.")


def not_running(lines: str) -> list[str]:
    return [line for line in lines.splitlines() if line and not re.search(r"\t(Up|running|Exited \(0\))", line)]


def start(args: list[str]) -> None:
    """Install and start AISC in one command; `start --configurator` starts the Configurator's own deployment
    (docker-compose.configurator.yml with env.configurator), refused unless it is served over https.

    1. Refuses a checkout that cannot work, before anything runs: Docker not running, Compose older than 2.17, a
       branch other than pilot (master's files are older), submodules not checked out. Warns when
       the disk is nearly full.
    2. Makes the secrets (once, then it keeps them; run again after a pull).
    3. Checks every port the stack publishes. On an install not served over https, a taken browser port (the
       engine's 80, the launcher's 8100, the dashboard's 8188, the sign-in's 8081) moves to a free fallback,
       and its address with it; the choice is kept in env.local and tried first next time. Any other taken
       port, or a taken browser port on an install served over https, stops here, with the command that shows
       which program holds it.
    4. Builds every image. A failed build is tried twice more, with fewer builds at once: a timeout on a slow
       network or a laptop short of memory usually passes the second time, and the cache keeps what was built.
       A build or start that fails because Docker's credential helper failed (`error getting credentials`, as
       when WSL's "credsStore": "desktop.exe" cannot reach Docker Desktop) runs once more without the helper,
       for the rest of this start only (run_step); the person's Docker config is not changed, and the way to mend
       it is named once.
    5. Starts the stack and waits until the sign-in page answers: `up -d` returns before the gateway's sign-in is
       ready, and a page opened then shows 502. Then tells the sign-in (Keycloak) the install's addresses, which
       its realm otherwise keeps from the first start. Then names, as a warning, every one-shot service that
       exited non-zero (make_buckets when it could not make the buckets). While it waits, a service that keeps
       restarting (seen restarting twice in a row, and restarted 5 times or for 90 seconds) or that exited
       with an error is named with its last log lines and stops the start at once; so does one that does so
       when `up -d` itself fails. No plugin is fetched: the publisher
       fetches and builds one when an admin installs it.
    6. Lists the local controls (local_controls/) every project catalogue gets; one it cannot read is a warning,
       not a failure.

    Settings for the impatient or the tests: START_WAIT_S (default 300), START_POLL_S (5), START_URL (default: the
    launcher on its published port on this machine), START_SIGN_IN_URL (Keycloak's realm page), START_SYNC_TRIES (6) and START_SYNC_WAIT_S (5) for telling the
    sign-in the addresses, START_MIN_DISK_GB (20), START_RESTART_GRACE_S (90) for how long a restarting service
    may be waited on, START_PROBE_WAIT_S (10) and START_PULL_WAIT_S (300) for asking
    Docker whether it can publish the ports."""
    if "--configurator" in args:
        use_configurator()
    try:
        start_steps()
    finally:
        end_helper_bypass()


def start_steps() -> None:
    """start's steps 1 to 6, in order (see start)."""
    global STACK_BEING_STARTED
    wait_s = float(os.environ.get("START_WAIT_S", "300"))
    poll_s = float(os.environ.get("START_POLL_S", "5"))
    min_disk_gb = int(os.environ.get("START_MIN_DISK_GB", "20"))

    # 1. The checkout and the machine
    found = find_docker()
    if found is None or captured([found, "info"]).returncode != 0:
        raise Refused(NO_DOCKER)
    Stack.use_docker(found)
    version = captured([Stack.docker, "compose", "version", "--short"]).stdout.strip().lstrip("v")
    parts = re.match(r"(\d+)\.(\d+)", version)
    if not parts or (int(parts[1]), int(parts[2])) < (2, 17):
        raise Refused(f"Docker Compose {version or 'is missing'}: AISC needs the Compose plugin 2.17 or later "
                      "(docker compose version).")
    if configurator() and (int(parts[1]), int(parts[2])) < (2, 24):
        raise Refused(f"Docker Compose {version}: the Configurator's compose file needs the Compose plugin 2.24 or "
                      "later (docker compose version).")
    branch = captured(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != BRANCH:
        raise Refused(f"this checkout is on '{branch or 'no branch'}', not {BRANCH}. Run: git checkout {BRANCH} && "
                      "git submodule update --init --recursive (or clone again: git -c core.autocrlf=false clone "
                      f"--recursive --branch {BRANCH} https://github.com/lux-ai-factory/aisc.git)")
    missing = sum(1 for line in captured(["git", "submodule", "status"]).stdout.splitlines() if line.startswith("-"))
    if missing:
        raise Refused(f"{missing} submodule(s) are not checked out. Run: git submodule update --init --recursive")
    free_gb = shutil.disk_usage(".").free // 2**30
    if free_gb < min_disk_gb:
        say(f"Warning: {free_gb} GB free here; the first build needs about {min_disk_gb} GB. It may fail with "
            "'no space left on device'.")

    # 2. The secrets
    make_secrets([], hint=False)
    warn_known_account_passwords(OUT)
    if configurator():
        make_postgres_tls()

    # Only one install runs at a time: refuse before the ports are looked at, so the other stack's are never taken
    # for ours to move. project() is this install's stack by now. No answer from Docker: carry on.
    running = docker_in_time([Stack.docker, "ps", "--filter", "label=com.docker.compose.service=platform", "--format",
                              '{{.Label "com.docker.compose.project"}}\t'
                              '{{.Label "com.docker.compose.project.working_dir"}}'], DOCKER_CALL_WAIT_S)
    if running is not None and running.returncode == 0:
        elsewhere = other_stacks(running.stdout, project())
        if elsewhere:
            raise Refused(another_install_refusal(*elsewhere[0]))

    # 3. The ports, before anything is built: a taken one would otherwise surface only after the whole build
    config = captured([*COMPOSE, "config", "--format", "json"])
    if config.returncode != 0:
        raise Refused(f"compose cannot read its files: {config.stderr.strip()[-600:]}")
    not_ports = kept_ports_not_ports()
    if not_ports:
        raise Refused("AISC cannot start: " + " ".join(not_ports))
    kept = read_local()
    prepare_port_probe()
    settings, problems, moved = settle_ports(published_ports(json.loads(config.stdout)), held_by_aisc(), kept,
                                             not served_over_https(), free_for_docker, TAKEN_IN_DOCKER.__contains__)
    if problems:
        raise Refused("AISC cannot start: " + " ".join(problems))
    # The realm import makes the sign-in's callback and sign-out rule from the launcher's address as compose
    # gives it (see sign_in_clients): one set without its slash is given with one.
    tracked_launcher = effective("LAUNCHER_EXTERNAL_URL", settings_file())
    if "LAUNCHER_EXTERNAL_URL" not in settings and tracked_launcher and not tracked_launcher.endswith("/"):
        settings["LAUNCHER_EXTERNAL_URL"] = with_slash(tracked_launcher)
    existing = lines_of(LOCAL) if Path(LOCAL).is_file() else []
    if local_lines(existing, settings) != existing:
        write_beside(LOCAL, text_of(local_lines(existing, settings)))
        write_runtime()
    for line in moved:
        say(line)
    if moved:
        say("If a port is held by something left from an earlier AISC run, restarting Docker frees it.")
    elif "API_URL_EXTERNAL" in settings:
        say(f"On this install, steps 1 and 2 open on {settings['API_URL_EXTERNAL']}.")

    # Where to wait, read now that the ports are settled: an address read before step 3 may be the one another
    # program holds. The launcher's published port on this machine, as for Keycloak's realm (keycloak_realm_url):
    # an https install's public name may not resolve from here, nor its certificate be trusted. Its listener
    # there serves TLS for that name only, so it is asked over TLS with the name (answer_over_tls).
    launcher = with_slash(effective("LAUNCHER_EXTERNAL_URL") or "http://localhost:8100/")
    # the Configurator publishes 443 only: there the gateway's own redirect to the sign-in is the answer
    launcher_port = 443 if configurator() else int(effective("HOMEPAGE_PORT_EXTERNAL") or "8100")
    public_name = urlsplit(launcher).hostname or urlsplit(effective("CADDY_DOMAIN", settings_file())).hostname or "localhost"
    over_tls = served_over_https() and not os.environ.get("START_URL")
    url = (f"https://localhost:{launcher_port}/ (as {public_name})" if over_tls
           else os.environ.get("START_URL") or f"http://localhost:{launcher_port}/")

    def launcher_answer() -> int | None:
        return answer_over_tls(launcher_port, public_name) if over_tls else answer_of(url)

    # 4. The images
    for attempt in (1, 2, 3):
        if attempt == 1:
            say("Building the images (the first time takes several minutes) ...")
            env = None
        else:
            say(f"The build failed; trying again ({attempt} of 3), fewer images at once ...")
            env = {**os.environ, "COMPOSE_BAKE": "false", "COMPOSE_PARALLEL_LIMIT": "2"}
        if run_step([*COMPOSE, "build"], env)[0] == 0:
            break
    else:
        raise Refused("the build failed three times. The first error above says why: often the network (pip, uv or "
                      "npm timed out) or the disk; what was built is kept.")

    # 5. Start, and wait for the sign-in page
    # A failed attempt, finished by hand with `docker compose up`, leaves containers in state "created";
    # they hold names and ports the next up needs, so they go first.
    left = run_program([*COMPOSE, "ps", "-a", "--status", "created", "--format", "{{.Service}}"],
                          capture_output=True, text=True)
    left_over = left.stdout.split() if left.returncode == 0 else []
    if left_over:
        say(f"Removing what an earlier attempt left unstarted: {' '.join(left_over)}")
        run_program([*COMPOSE, "rm", "-f", *left_over], capture_output=True)
    # An install from before plugins were fetched on install keeps the exited one-shot plugin-downloader;
    # no service has that name now, so compose would warn about an orphan on every start.
    old = captured([Stack.docker, "ps", "-a", "--filter", "name=^plugin-downloader$",
                    "--filter", f"label=com.docker.compose.project={project()}", "--format", "{{.ID}}"])
    old_ids = old.stdout.split() if old.returncode == 0 else []
    if old_ids:
        say("Removing the plugin-downloader container left from the old plugin download.")
        run_program([Stack.docker, "rm", "-f", *old_ids], capture_output=True)
    STACK_BEING_STARTED = True
    # the services this start has (not a removed service's) and when `up` began: a
    # container that exited with an error counts only if it is one of them and stopped after that
    stack = Stack(COMPOSE)
    listed = captured([*COMPOSE, "config", "--services"])
    this_start = set(listed.stdout.split()) if listed.returncode == 0 and listed.stdout.split() else None
    began_at = docker_now()
    say("Starting the stack ...")
    if run_step([*COMPOSE, "up", "-d"])[0] != 0:
        # `up -d` waits for the health of what others depend on (minio, postgres, keycloak ...), so a service
        # that keeps dying fails it before any wait below: name that service and its log lines first. Two polls,
        # a moment apart, so the restarting rule (restarting twice in a row) can apply here too.
        restarting = refuse_if_stuck(set(), this_start, began_at, after_failed_up=True)
        time.sleep(STUCK_RECHECK_S)
        refuse_if_stuck(restarting, this_start, began_at, after_failed_up=True)
        # Nothing restarting or dead: a service that runs but never turns healthy (MinIO refusing its stored
        # config) is named here with its own log lines.
        show_failing_logs(stack)
        raise Refused("the stack did not start: see the error above.")
    say(f"Waiting for the sign-in page at {url} (Keycloak needs about 30 seconds on a first start) ...")
    deadline = time.monotonic() + wait_s
    restarting: set[str] = set()
    while True:
        restarting = refuse_if_stuck(restarting, this_start, began_at)
        code = launcher_answer()
        if code in (200, 302, 303):
            break
        if time.monotonic() >= deadline:
            warn(f"The sign-in page did not answer within {wait_s:g}s (last answer: {code or 'none'}). "
                 "Services not running:")
            warn(*not_running(captured([*COMPOSE, "ps", "-a", "--format", "{{.Service}}\t{{.Status}}"]).stdout))
            raise Refused(f"see why with: docker compose -p {project()} logs <service>  (for example keycloak or oauth2-proxy)")
        time.sleep(poll_s)
    # The launcher redirects to the sign-in before Keycloak has imported its realm: a person who follows at once
    # gets no form. The realm's own page answers 200 only once it is there.
    realm = keycloak_realm_url()
    while (code := answer_of(realm)) != 200:
        restarting = refuse_if_stuck(restarting, this_start, began_at)
        if time.monotonic() >= deadline:
            warn(f"Keycloak's realm page {realm} did not answer 200 within {wait_s:g}s (last answer: "
                 f"{code or 'none'}), so the sign-in cannot be shown yet.")
            raise Refused(f"see why with: docker compose -p {project()} logs keycloak")
        time.sleep(poll_s)
    # The realm answers: now it can be told this install's addresses, which may have moved since it was imported
    sync_sign_in()

    refuse_if_stuck(restarting, this_start, began_at)
    warn_unfinished(stack, this_start, began_at)

    # 6. The local controls every project catalogue gets (local_controls/), read by the platform's own code
    found = captured([*COMPOSE, "exec", "-T", "platform", "python", "-m", "platform_service.catalogue"])
    if found.returncode == 0:
        controls = [line for line in found.stdout.splitlines() if line.strip()]
        say(f"{len(controls)} local controls go into every project catalogue (local_controls/):",
            *("  " + c for c in controls))
    else:
        say("Warning: the local controls could not be read; catalogues get the public entries only.",
            f"See why with: docker compose -p {project()} logs platform")

    # the sign-in that works on this install: admin / admin only while the password still is admin (a new local
    # install); generated (https) or changed (rotate-infra-password) ones are this install's own
    if value_in("AISC_ADMIN_PASSWORD", OUT).strip("'\"") == "admin":
        sign_in = ["sign in as admin / admin (user / user is an ordinary account)."]
    else:
        sign_in = ["sign in as admin with this install's own password. Show it, and the ordinary account user's, with:",
                   "  uv run scripts/aisc.py password   (AISC_ADMIN_PASSWORD and AISC_USER_PASSWORD in env.secrets)"]
    say("",
        f"AISC is up: open {launcher.rstrip('/')} and {sign_in[0]}", *sign_in[1:],
        "If you installed AISC before on this machine, use a private window (an old session cookie is refused).")


def same_folder(folder: str) -> bool:
    return bool(folder) and os.path.normcase(str(Path(folder).resolve())) == os.path.normcase(str(ROOT.resolve()))


def own_compose(verb: str) -> list[str]:
    """The compose command for `stop` or `remove`: this checkout's own stack (project()) and no other. Refuses,
    before any docker call, where nothing was installed: project() would then be the plain `aisc`, which may be
    an older install's. Refuses too when a container of the stack was made from another folder (every install
    made before ids is `aisc`, and AISC_PROJECT may be left in the shell), and when Docker cannot say."""
    if not (ROOT / OUT).exists():
        raise Refused(f"no AISC install in this folder (no {OUT}): nothing to {verb}")
    docker_command = find_docker()
    if docker_command is None:
        raise Refused(NO_DOCKER)
    done = "stopped" if verb == "stop" else "removed"
    listed = docker_in_time([docker_command, "ps", "-a", "--filter", f"label=com.docker.compose.project={project()}",
                             "--format", '{{.Label "com.docker.compose.project.working_dir"}}'], DOCKER_CALL_WAIT_S)
    if listed is None or listed.returncode != 0:
        raise Refused(f"Docker did not list the containers of stack {project()}, so nothing shows they are this "
                      f"folder's; nothing was {done}")
    folders = listed.stdout.splitlines()
    for folder in folders:
        if not same_folder(folder.strip()):
            raise Refused(f"stack {project()} belongs to {folder.strip() or 'a folder Docker does not name'}: run this "
                          f"there; nothing was {done}")
    # with no container left, only a name made from this folder's own id shows the volumes are this folder's
    own = install_id(str(ROOT / OUT))
    if verb == "remove" and not folders and (not own or project() != f"aisc-{own}"):
        why = ("every install made before ids names its stack aisc" if project() == "aisc"
               else "its name comes from AISC_PROJECT, not from this install's id")
        raise Refused(f"stack {project()} has no container left to show it is this folder's ({why}). See its volumes "
                      f"with  docker volume ls --filter label=com.docker.compose.project={project()}  and, if they are "
                      "this install's, delete them with  docker volume rm <name> ...; nothing was removed")
    return [docker_command, *COMPOSE[1:]]


def run_compose(argv: list[str]) -> None:
    done = run_program(argv)
    if done.returncode:
        raise Refused(f"docker compose failed (exit {done.returncode})", done.returncode)


def stop(_args: list[str]) -> None:
    """Stop this install's containers. Their data stays; start brings them back."""
    argv = own_compose("stop")
    run_compose([*argv, "stop"])
    say(f"Stopped the containers of {project()}. Their data is kept: run start to bring them back.")


def offer_backup() -> None:
    """Before the volumes go: ask whether to back them up first (scripts/backup-databases.sh, every part restored
    and counted), and say where. A backup that does not pass stops the removal."""
    folder = os.environ.get("AISC_BACKUP_DIR") or str(Path.home() / "aisc-backups" / project())
    try:
        answer = input(f"Back up its databases, ledger, files and secrets first, to {folder} "
                       "(scripts/backup-databases.sh)? [y/N]: ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        return
    try:
        done = run_program(["bash", str(ROOT / "scripts/backup-databases.sh"), "--dir", folder], cwd=ROOT)
    except FileNotFoundError:
        raise Refused("there is no bash here to run scripts/backup-databases.sh; nothing was removed") from None
    if done.returncode != 0:
        raise Refused(f"the backup did not pass (see above); nothing was removed. What it wrote is in {folder}")


def remove(_args: list[str]) -> None:
    """Delete this install's containers and volumes (all its data), after the person types this folder's name and
    is offered a backup. No answer, or any other, removes nothing."""
    argv = own_compose("remove")
    try:
        typed = input(f"This deletes this install's containers and all its data (stack {project()}). "
                      f"Type the folder name ({ROOT.name}) to go on: ")
    except EOFError:
        typed = ""
    if typed.strip() != ROOT.name:
        raise Refused("nothing was removed")
    offer_backup()
    run_compose([*argv, "down", "-v", "--remove-orphans"])
    say(f"Removed the containers and data of {project()}. This folder can now be deleted.")
