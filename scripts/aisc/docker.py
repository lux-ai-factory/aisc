"""Every call of a program the install script makes, Docker's above all: in time or not, watched as it runs,
past a credential helper that fails, and the Stack that reads the containers of this install."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .secrets import hide_secrets
from .settings import COMPOSE, say, warn


def find_docker() -> str | None:
    """The docker command on this process's own PATH, or None. Windows looks a program up through the parent
    process's search path, not the PATH given to a child, so running `docker` and seeing it work proves nothing
    about this PATH."""
    return shutil.which("docker", path=os.environ.get("PATH"))


#: how long listing or removing a container may take: a daemon slower than this is too busy to probe
DOCKER_CALL_WAIT_S = 20


def docker_in_time(argv: list[str], wait_s: float) -> subprocess.CompletedProcess | None:
    """One docker call given wait_s seconds; None when it did not finish in time (it is stopped then)."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=wait_s)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", "")
    except subprocess.TimeoutExpired:
        return None


def run_program(argv: list[str], **options) -> subprocess.CompletedProcess:
    """One program run to its end, as subprocess.run runs it with these options: every program the install script
    starts is started in this module."""
    return subprocess.run(argv, **options)


def captured(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", "")


# ------------------------------------------------------------------------ a Docker credential helper that fails

#: what Docker says when the credential helper its config names fails; it asks the helper even for public images
CREDENTIAL_HELPER_FAILED = "error getting credentials"
#: the config.json keys that name credential helpers; everything else (registry logins in auths too) is kept
HELPER_KEYS = ("credsStore", "credHelpers")


def run_and_watch(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    """Runs a Docker step with its output shown as it comes; returns its exit code and what it wrote on stderr."""
    try:
        with subprocess.Popen(argv, env=env, stderr=subprocess.PIPE) as step:
            said = []
            for line in step.stderr:
                text = line.decode(errors="replace")
                said.append(text)
                sys.stderr.write(text)
                sys.stderr.flush()
            return step.wait(), "".join(said)
    except FileNotFoundError:
        return 127, ""


def docker_config_folder(env: dict[str, str] | None = None) -> Path:
    """The folder Docker reads its config.json from: DOCKER_CONFIG, else ~/.docker."""
    return Path((env or os.environ).get("DOCKER_CONFIG") or Path.home() / ".docker")


def helpers_named(config: dict) -> str:
    """The credential helper a Docker config names for every registry (credsStore), else the per-registry ones
    (credHelpers); empty for none."""
    if config.get("credsStore"):
        return str(config["credsStore"])
    return ", ".join(sorted(set(map(str, (config.get("credHelpers") or {}).values()))))


def machine_kind() -> str:
    """windows, macos, wsl or linux: where the fix for a broken credential helper differs."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if os.environ.get("WSL_DISTRO_NAME") or "microsoft" in os.uname().release.lower():
        return "wsl"
    return "linux"


def credential_helper_fix(kind: str, helper: str, config_file: Path) -> str:
    """One line: how to mend the credential helper for good on this kind of machine."""
    if kind == "wsl" and any(name in ("desktop", "desktop.exe") for name in helper.split(", ")):
        return ("start Docker Desktop and turn on WSL integration for this distribution, or remove credsStore "
                f"from {config_file}.")
    if kind == "wsl":
        return (f'in {config_file} inside WSL, remove "credsStore", or set it to "desktop.exe" with Docker Desktop '
                "running.")
    if kind == "macos":
        return "unlock the login keychain (open Keychain Access, or run: security unlock-keychain), then start again."
    if kind == "windows":
        return f'restart Docker Desktop and sign in to it again; if it still fails, remove "credsStore" from {config_file}.'
    return (f"make docker-credential-{helper.split(', ')[0]} work (it must be on PATH and answer), or remove "
            f'"credsStore" and "credHelpers" from {config_file}.')


def config_without_helpers(source: Path, folder: Path, config: dict) -> None:
    """Fills folder as a Docker config folder like source, but whose config.json names no credential helper.
    Everything else in source (cli-plugins, so `docker compose` is still found; contexts; buildx) is linked."""
    kept = {key: value for key, value in config.items() if key not in HELPER_KEYS}
    written = os.open(folder / "config.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(written, "w") as file:
        json.dump(kept, file, indent=1)
    for entry in source.iterdir() if source.is_dir() else ():
        if entry.name == "config.json":
            continue
        try:
            (folder / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        except OSError:      # Windows without the right to make links: a copy does as well for one run
            if entry.is_dir():
                shutil.copytree(entry, folder / entry.name, symlinks=True)
            else:
                shutil.copy2(entry, folder / entry.name)


@dataclass
class HelperBypass:
    """This start's way round a credential helper that failed: the temporary Docker config naming no helper,
    which every later step of the start runs with, and what to tell the person about it."""
    folder: Path
    helper: str
    fix: str
    told: bool = False


#: set once the credential helper has failed in this start; end_helper_bypass removes its folder
HELPER_BYPASS: HelperBypass | None = None


def bypass_helper(env: dict[str, str] | None) -> HelperBypass | None:
    """A temporary Docker config like the person's but naming no credential helper; None when theirs names none
    (or cannot be read), so there is nothing to go round."""
    source = docker_config_folder(env)
    try:
        config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    helper = helpers_named(config) if isinstance(config, dict) else ""
    if not helper:
        return None
    folder = Path(tempfile.mkdtemp(prefix="aisc-docker-config-"))     # readable by this user only
    try:
        config_without_helpers(source, folder, config)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return HelperBypass(folder, helper, credential_helper_fix(machine_kind(), helper, source / "config.json"))


def run_step(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, bool]:
    """Runs a Docker step (a build, a pull, an up). When it fails because the configured credential helper failed
    (`error getting credentials`), runs it once more with a temporary DOCKER_CONFIG naming no helper: registry
    logins in auths still hold. From then on every step of this start runs with that config, so the build's own
    retries and the up are not lost to the helper again; end_helper_bypass removes it when the start ends. The
    person's config is only read. Returns the exit code and whether the step ran without the helper. Any other
    failure is returned as it is."""
    global HELPER_BYPASS
    if HELPER_BYPASS is None:
        code, said = run_and_watch(argv, env)
        if code == 0 or CREDENTIAL_HELPER_FAILED not in said:
            return code, False
        HELPER_BYPASS = bypass_helper(env)
        if HELPER_BYPASS is None:
            return code, False
    code, _ = run_and_watch(argv, {**(env or os.environ), "DOCKER_CONFIG": str(HELPER_BYPASS.folder)})
    if code == 0 and not HELPER_BYPASS.told:
        HELPER_BYPASS.told = True
        say(f"Docker's credential helper ({HELPER_BYPASS.helper}) failed; pulled without it for this run. "
            f"To fix it for good: {HELPER_BYPASS.fix}")
    return code, True


def end_helper_bypass() -> None:
    """Removes this start's temporary Docker config, if the helper failed. When no step went through without the
    helper either, says so here: the helper may still be what is wrong."""
    global HELPER_BYPASS
    if HELPER_BYPASS is None:
        return
    bypass, HELPER_BYPASS = HELPER_BYPASS, None
    shutil.rmtree(bypass.folder, ignore_errors=True)
    if not bypass.told:
        warn(f"Docker's credential helper ({bypass.helper}) failed, and the steps failed again without it: see the "
             f"error above. To fix the helper: {bypass.fix}")


LOG_TAIL_LINES = 20


#: how long fetching those lines may take: a wedged daemon must not hang start while it reports
LOG_WAIT_S = float(os.environ.get("START_LOG_WAIT_S", "20"))


def finished_after(container: str, began_at: datetime) -> bool:
    """Whether this container stopped after began_at (Stack.finished_after), asked of the docker start found."""
    return Stack([Stack.docker, *COMPOSE[1:]]).finished_after(container, began_at)


def parse_docker_time(text: str) -> datetime | None:
    """Docker's RFC 3339 time (nanoseconds; `Z` or an offset like +02:00, as `docker info` prints it) as an aware
    UTC datetime with microseconds; None if it is not one. 0001-01-01T00:00:00Z, a container that never ran,
    parses to a year long before any start."""
    match = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)$", text.strip())
    if not match:
        return None
    zone = "+00:00" if match.group(3) == "Z" else match.group(3)
    try:
        return datetime.fromisoformat(f"{match.group(1)}.{(match.group(2) or '0')[:6].ljust(6, '0')}{zone}"
                                      ).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def docker_now() -> datetime:
    """The time on Docker's own clock, the one a container's FinishedAt is on: a VM's clock (WSL2, Docker Desktop)
    can drift by minutes from the host's. The host's clock only when Docker does not say."""
    said = docker_in_time([Stack.docker, "info", "--format", "{{.SystemTime}}"], DOCKER_CALL_WAIT_S)
    return (said and said.returncode == 0 and parse_docker_time(said.stdout)) or datetime.now(timezone.utc)


class Stack:
    """This install's Compose project, as start reads it: which of its containers failed, and their log lines.
    Every docker call goes through call(), the one place a test answers in-process instead of Docker, and every
    log line shown goes through hide_secrets first.

    compose: the stack's compose command (COMPOSE), its first word the docker start found."""

    #: the docker command on this process's PATH (as find_docker finds it), found once when the module loads;
    #: start finds it again, checks it answers and keeps it here (use_docker). Windows runs a bare `docker` from
    #: the parent's search path, not this PATH.
    docker: str = shutil.which("docker", path=os.environ.get("PATH")) or "docker"

    def __init__(self, compose: list[str]):
        self.compose = list(compose)

    @classmethod
    def use_docker(cls, found: str) -> None:
        """The docker command start found and checked: every later docker call of this run, and the stack's
        compose command (COMPOSE), start with it."""
        cls.docker = COMPOSE[0] = found

    def call(self, argv: list[str], wait_s: float) -> subprocess.CompletedProcess | None:
        """One docker call given wait_s seconds; None when it did not finish in time."""
        return docker_in_time(argv, wait_s)

    def logs(self, service: str, tail: int = LOG_TAIL_LINES, wait_s: float = LOG_WAIT_S) -> str | None:
        """The service's last log lines, each secret hidden (hide_secrets); None when Docker did not answer."""
        said = self.call([*self.compose, "logs", "--no-color", "--tail", str(tail), service], wait_s)
        return None if said is None else hide_secrets(said.stdout + said.stderr)

    def finished_after(self, container: str, began_at: datetime) -> bool:
        """Whether this container stopped after began_at, by Docker's own FinishedAt (RFC 3339 with nanoseconds,
        in UTC). False when Docker does not say or it never ran: such a container is not this start's doing."""
        said = self.call([self.compose[0], "inspect", "--format", "{{.State.FinishedAt}}", container],
                         DOCKER_CALL_WAIT_S)
        if not said or said.returncode != 0:
            return False
        finished = parse_docker_time(said.stdout)
        return finished is not None and finished > began_at

    def failing(self, this_start: set[str] | None, began_at: datetime) -> list[tuple[str, str]]:
        """(service, status) of each container that exited non-zero during this start, in the order compose lists
        them. Only this start's services count (this_start; None when compose would not list them), and only a
        container that stopped after began_at: the project also holds containers of earlier runs (an inspect
        profile) and of removed services, whose exits are not this start's."""
        listed = self.call([*self.compose, "ps", "-a", "--format", "{{.Service}}\t{{.Status}}\t{{.ID}}"],
                           DOCKER_CALL_WAIT_S)
        if listed is None or listed.returncode != 0:
            return []
        found = []
        for line in listed.stdout.splitlines():
            service, _, rest = line.partition("\t")
            status, _, container = rest.partition("\t")
            if (re.match(r"Exited \([1-9]", status) and (this_start is None or service in this_start)
                    and container and self.finished_after(container, began_at)):
                found.append((service, status))
        return found
