"""This install's settings: where its files are, the env files it reads and writes, its Compose project and
command, and the few answers every other module needs (how to refuse, how to speak)."""
from __future__ import annotations

import os
import secrets as random_source
import sys
import tempfile
from pathlib import Path


#: the checkout (this file is scripts/aisc/settings.py)
ROOT = Path(__file__).resolve().parents[2]
OUT = "env.secrets"
COMBINED = "env.runtime"   # what compose is pointed at: the settings plus the secrets
TRACKED = "env.plugin_downloader"
LOCAL = "env.local"         # this install's own settings, chosen by start (git-ignored)
SIGNING_KEY, SIGNING_PUB = "immudb-signing.key", "immudb-signing.pub"


#: the setting that names one install: made with its env.secrets, kept by --rotate
INSTALL = "AISC_INSTALL"
NO_DOCKER = ("Docker is not running (or this user may not use it). Start Docker Desktop or the docker "
             "service, then run this again.")


def optional_compose_files() -> list[str]:
    """443 only for an install served over https, so a taken 443 never stops one on plain http; the
    infrastructure's ports on the loopback only when asked (AISC_ADMIN_PORTS=on), for tools on the host."""
    files = ["docker-compose.https.yml"] if served_over_https() else []
    if admin_ports_asked():
        files.append("docker-compose.admin-ports.yml")
    return files


def admin_ports_asked() -> bool:
    """AISC_ADMIN_PORTS=on in the shell, or else in env.local (its last line for it, as compose reads it). The
    checkout's own env.local, not the current folder's: COMPOSE asks this on import, before main moves there."""
    asked = os.environ.get("AISC_ADMIN_PORTS")
    local = ROOT / LOCAL
    if asked is None and local.is_file():
        lines = [line for line in lines_of(str(local)) if line.startswith("AISC_ADMIN_PORTS=")]
        asked = lines[-1].split("=", 1)[1].strip().strip('"\'') if lines else None
    return asked == "on"


def lan_asked() -> bool:
    """AISC_LAN=on in the shell, or else in env.local (its last line for it), as admin_ports_asked reads it."""
    asked = os.environ.get("AISC_LAN")
    local = ROOT / LOCAL
    if asked is None and local.is_file():
        lines = [line for line in lines_of(str(local)) if line.startswith("AISC_LAN=")]
        asked = lines[-1].split("=", 1)[1].strip().strip('"\'') if lines else None
    return asked == "on"


def caddy_bind_address() -> str:
    """The host address Caddy publishes the browser ports on: every interface for an install served over https
    or one that asked for the local network (AISC_LAN=on), else this machine only."""
    return "0.0.0.0" if served_over_https() or lan_asked() else "127.0.0.1"


def served_over_https() -> bool:
    # the checkout's own file, not the current folder's: COMPOSE asks this on import, before main moves there
    tracked = ROOT / TRACKED
    domain = os.environ.get("CADDY_DOMAIN") or (value_in("CADDY_DOMAIN", str(tracked)) if tracked.is_file() else "")
    return domain.strip('"').startswith("https://")


class Refused(Exception):
    """Stops a command with a message on stderr and an exit code; nothing half-written is left."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def say(*lines: str) -> None:
    for line in lines:
        print(line, flush=True)


def warn(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr, flush=True)


def lines_of(path: str) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines()


def value_in(name: str, path: str) -> str:
    """The value of NAME in a file: empty when the line is missing or has no value."""
    for line in lines_of(path):
        if line.startswith(name + "="):
            return line[len(name) + 1:]
    return ""


def install_id(path: str = OUT) -> str:
    """This install's id: empty when the file or its line is missing (an install from before ids, which keeps the
    shared names)."""
    return value_in(INSTALL, path) if Path(path).is_file() else ""


def new_install_id() -> str:
    return random_source.token_hex(3)


def stack_name(install: str) -> str:
    """The Compose project: AISC_PROJECT if set (a second copy beside an install's data), else aisc-<id>, else
    aisc for an install without an id."""
    return os.environ.get("AISC_PROJECT") or (f"aisc-{install}" if install else "aisc")


def container_prefix(install: str) -> str:
    return f"aisc-{install}-" if install else ""


#: the Compose project of this checkout's own env.secrets: COMPOSE asks this on import, before main moves there
PROJECT = stack_name(install_id(str(ROOT / OUT)))


#: the stack's compose command; start puts the docker it found first
COMPOSE = ["docker", "compose", "-p", PROJECT, "--env-file", COMBINED,
           "-f", "docker-compose-infra.development.yml", "-f", "docker-compose.development.yml",
           *[arg for name in optional_compose_files() for arg in ("-f", name)]]


def use_stack(name: str) -> None:
    """Run the stack under this Compose project from here on."""
    global PROJECT
    PROJECT = COMPOSE[3] = name


def project() -> str:
    """The Compose project the stack runs under now (use_stack moves it once env.secrets names the install)."""
    return PROJECT


def up_hint() -> str:
    return (f"  docker compose -p {PROJECT} --env-file env.runtime \\\n"
            "    -f docker-compose-infra.development.yml -f docker-compose.development.yml"
            + "".join(f" -f {name}" for name in optional_compose_files()) + " up -d")


def private(path: str) -> None:
    """Readable by its owner only. Windows has no such mode: there the file stays in the user's own folder."""
    if os.name != "nt":
        os.chmod(path, 0o600)


def write_beside(path: str, text: str) -> None:
    """Write a file whole or not at all: into a temporary file beside it, then moved into place, so a run that
    fails leaves the old file as it was."""
    fd, tmp = tempfile.mkstemp(prefix=path + ".", dir=".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        private(tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def with_value(lines: list[str], name: str, value: str) -> list[str]:
    """The lines with NAME's first line set to the value."""
    out, done = [], False
    for line in lines:
        if not done and line.startswith(name + "="):
            out.append(f"{name}={value}")
            done = True
        else:
            out.append(line)
    return out


def text_of(lines: list[str]) -> str:
    return "".join(line + "\n" for line in lines)


def local_setting(line: str) -> tuple[str, str] | None:
    """One line of env.local as (NAME, value), one pair of quotes around the value taken off: a person editing the
    file may quote it, as in the other env files. None for a comment or a line without a name."""
    name, found, value = line.partition("=")
    if not found or name.lstrip().startswith("#"):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return name.strip(), value


def read_local() -> dict[str, str]:
    """The settings in env.local, NAME to value (local_setting); the last line for a name wins, as in compose."""
    lines = lines_of(LOCAL) if Path(LOCAL).is_file() else []
    return dict(setting for setting in map(local_setting, lines) if setting)


def effective(name: str, path: str = COMBINED) -> str:
    """The value compose uses for a setting: its last line in env.runtime (env.local comes last there), one pair
    of quotes taken off; empty when env.runtime has none. path: another env file to read it from instead."""
    value = ""
    if Path(path).is_file():
        for line in lines_of(path):
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
    return value


def with_slash(address: str) -> str:
    return address if address.endswith("/") else address + "/"
