"""This install's settings: where its files are, the env files it reads and writes, its Compose project and
command, and the few answers every other module needs (how to refuse, how to speak)."""
from __future__ import annotations

import os
import re
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


#: the Configurator's own deployment (start --configurator): its settings, made from env.configurator.example, and
#: its compose file, laid over the https one
CONFIGURATOR_SETTINGS = "env.configurator"
CONFIGURATOR_FILE = "docker-compose.configurator.yml"
#: the settings env.runtime is made from: env.plugin_downloader, or env.configurator once use_configurator ran
SETTINGS = TRACKED


def settings_file() -> str:
    """The settings file this start makes env.runtime from (use_configurator changes it)."""
    return SETTINGS


def configurator() -> bool:
    """Whether this start runs the Configurator's own deployment (start --configurator)."""
    return SETTINGS == CONFIGURATOR_SETTINGS


def optional_compose_files() -> list[str]:
    """443 only for an install served over https, so a taken 443 never stops one on plain http; the
    infrastructure's ports on the loopback only when asked (AISC_ADMIN_PORTS=on), for tools on the host; the
    Configurator's own file last, for start --configurator."""
    files = ["docker-compose.https.yml"] if served_over_https() else []
    if admin_ports_asked():
        files.append("docker-compose.admin-ports.yml")
    if configurator():
        files.append(CONFIGURATOR_FILE)
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
    tracked = ROOT / SETTINGS
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


def use_configurator() -> None:
    """start --configurator: the settings from env.configurator, and the https and Configurator compose files over
    the development ones. Refused, before anything else runs, unless the install is served over https and
    env.configurator exists: the Configurator's session cookie, sign-in and gateway are https only."""
    global SETTINGS
    own = ROOT / CONFIGURATOR_SETTINGS
    domain = (os.environ.get("CADDY_DOMAIN") or (value_in("CADDY_DOMAIN", str(own)) if own.is_file() else "")).strip("\"'")
    if not domain.startswith("https://"):
        raise Refused(f"the Configurator is served over https only, and CADDY_DOMAIN is {domain or 'not set'}. Set "
                      f"CADDY_DOMAIN=https://<its address> in {CONFIGURATOR_SETTINGS} (copied from "
                      f"{CONFIGURATOR_SETTINGS}.example)")
    if not own.is_file():
        raise Refused(f"no {CONFIGURATOR_SETTINGS}: copy {CONFIGURATOR_SETTINGS}.example to {CONFIGURATOR_SETTINGS} and "
                      "set the values it marks (https:// address, AISC_IMAGE_TAG)")
    SETTINGS = CONFIGURATOR_SETTINGS
    for name in optional_compose_files():
        if name not in COMPOSE:
            COMPOSE.extend(["-f", name])


#: the Configurator's parts: the setting that names each one's host, and the address made from it (env.configurator)
CONFIGURATOR_PARTS = {"ENGINE_HOST": "API_URL_EXTERNAL", "LAUNCHER_HOST": "LAUNCHER_EXTERNAL_URL",
                      "DASHBOARD_HOST": "DASHBOARD_EXTERNAL_URL", "SIGN_IN_HOST": "KEYCLOAK_URL_EXTERNAL"}
HOST_NAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*")


def configurator_setting(name: str) -> str:
    """A setting as compose gives it to the Configurator: the shell's value, else env.configurator's."""
    return os.environ.get(name) or effective(name, str(ROOT / CONFIGURATOR_SETTINGS))


def check_host_names() -> None:
    """start --configurator, before Docker is asked: Caddy serves each part at its own host name on 443, so each
    host name setting must be a name, the four different, and each part's address https://<its name>. Refused
    with the setting to fix."""
    hosts = {name: configurator_setting(name).strip() for name in CONFIGURATOR_PARTS}
    for name, host in hosts.items():
        if not host:
            raise Refused(f"{name} is not set in {CONFIGURATOR_SETTINGS}: the Configurator serves each part at its "
                          f"own host name. Set it (see {CONFIGURATOR_SETTINGS}.example)")
        if not HOST_NAME.fullmatch(host):
            raise Refused(f"{name} is {host}: a host name only, such as app.example.org (no https://, port or path)")
    if len(set(hosts.values())) < len(hosts):
        raise Refused(f"{', '.join(hosts)} must be four different host names: Caddy tells the parts apart by name")
    for name, address_name in CONFIGURATOR_PARTS.items():
        address = configurator_setting(address_name).strip()
        wanted = f"https://{hosts[name]}"
        if address not in (wanted, wanted + "/"):
            raise Refused(f"{address_name} is {address or 'not set'}: the Configurator serves this part at "
                          f"https://<{name}> only ({wanted}). Set {address_name}=https://${{{name}}} in "
                          f"{CONFIGURATOR_SETTINGS}")


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
    of quotes taken off; empty when env.runtime has none. path: another env file to read it from instead. A
    ${OTHER} in it is filled in as compose fills it: from OTHER's line above it in the file, else the shell's."""
    seen: dict[str, str] = {}
    if Path(path).is_file():
        for line in lines_of(path):
            other, sign, value = line.partition("=")
            if not sign or other.startswith("#") or " " in other:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            seen[other] = re.sub(r"\$\{([A-Za-z0-9_]+)\}",
                                 lambda m: seen.get(m[1], os.environ.get(m[1], "")), value)
    return seen.get(name, "")


def with_slash(address: str) -> str:
    return address if address.endswith("/") else address + "/"
