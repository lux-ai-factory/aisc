"""The ports the stack publishes: whether each is free on this machine and for Docker, and where a taken browser
port moves to."""
from __future__ import annotations

import errno
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .docker import DOCKER_CALL_WAIT_S, Stack, captured, docker_in_time
from .settings import LOCAL, lines_of, local_setting, project, say


@dataclass(frozen=True)
class BrowserPort:
    """A port the browser reaches the install on: the setting compose publishes it through, the service and
    container port behind it, the host port it prefers, the ones it moves to when that one is taken, the
    setting that holds its address, and the host address Docker publishes it on."""
    variable: str
    service: str
    target: int
    preferred: int
    fallbacks: tuple[int, ...]
    address: str | None
    host: str


#: every port the browser reaches; no fallback is listed twice or is another one's preferred port
BROWSER_PORTS: tuple[BrowserPort, ...] = (
    BrowserPort("ENGINE_PORT", "caddy", 8005, 80, (8080, 8090, 8000, 8880, 8888), "API_URL_EXTERNAL", "0.0.0.0"),
    BrowserPort("HOMEPAGE_PORT_EXTERNAL", "caddy", 8006, 8100, (8110, 8120, 8130), "LAUNCHER_EXTERNAL_URL", "0.0.0.0"),
    BrowserPort("DASHBOARD_PORT_EXTERNAL", "caddy", 8008, 8188, (8198, 8288, 8388), "DASHBOARD_EXTERNAL_URL",
                "0.0.0.0"),
    BrowserPort("KEYCLOAK_PORT_EXTERNAL", "keycloak", 8080, 8081, (8091, 8181, 8281), "KEYCLOAK_URL_EXTERNAL",
                "127.0.0.1"),
)


#: Windows judges a refused or shared bind differently (see can_bind)
ON_WINDOWS = os.name == "nt"


#: the IPv6 address bound beside each IPv4 one: Docker publishes an all-interfaces port on [::] too, and a
#: browser on this machine asks localhost, ::1 first, so a program there holds the port as well
IPV6_BESIDE = {"0.0.0.0": "::", "127.0.0.1": "::1"}


def can_bind(family: socket.AddressFamily, host: str, port: int) -> bool | None:
    """Whether this port can be bound on this address: True, False when something holds it, None when binding
    cannot tell (Linux refuses a port below 1024 without root). An address family this machine lacks (no IPv6)
    holds nothing: True."""
    try:
        s = socket.socket(family)
    except OSError:
        return True
    with s:
        # As Docker binds on Linux: past connections still closing (TIME_WAIT) do not hold the port. Only there:
        # on Windows this option would let the test bind over a program that is listening, and on macOS (BSD
        # sockets) a bind on 0.0.0.0 would succeed beside a program listening on 127.0.0.1 only.
        if sys.platform.startswith("linux"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # On Windows a wildcard bind succeeds beside a program listening on one address of the same port (the
        # [::1] case) unless the probe asks for the port to itself
        if ON_WINDOWS and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if family == socket.AF_INET6:
            # IPv6 only, so a program on the IPv4 side is not counted twice (and macOS binds [::] dual-stack)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            s.bind((host, port))
            return True
        except PermissionError:
            # Windows' reserved ranges (Hyper-V, WSL): Docker cannot publish there either
            return False if ON_WINDOWS else None
        except OSError as failed:
            # an IPv6 address this machine does not have (IPv6 switched off) holds nothing
            return family == socket.AF_INET6 and failed.errno in (errno.EADDRNOTAVAIL,
                                                                   getattr(errno, "WSAEADDRNOTAVAIL", None))


def port_is_free(port: int, host: str) -> bool:
    """Whether Docker could publish this port on this address. Binding it is the real test, on IPv4 and on the
    IPv6 address beside it (IPV6_BESIDE); Windows refuses one in its reserved ranges with an access error,
    which means taken. Where Linux refuses the bind outright (a port below 1024 without root), whether
    something answers decides, on loopback (both families) and on each address of the machine."""
    bound = [can_bind(socket.AF_INET, host, port)]
    if host in IPV6_BESIDE:
        bound.append(can_bind(socket.AF_INET6, IPV6_BESIDE[host], port))
    if False in bound:
        return False
    if None not in bound:
        return True
    # A program listening on the machine's network address only is not on 127.0.0.1, so each of its IPv4
    # addresses is tried too.
    addresses = [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]
    try:
        addresses += [(socket.AF_INET, info[4][0])
                      for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    for family, address in dict.fromkeys(addresses):
        try:
            s = socket.socket(family)
        except OSError:
            continue
        with s:
            s.settimeout(1)
            if s.connect_ex((address, port)) == 0:
                return False
    return True


def kept_ports_not_ports() -> list[str]:
    """One problem per browser port in env.local whose value is not a port. The guide tells people to edit the
    file, and compose would take a comment after the value as part of it."""
    variables = {port.variable for port in BROWSER_PORTS}
    problems = []
    for number, line in enumerate(lines_of(LOCAL) if Path(LOCAL).is_file() else [], 1):
        setting = local_setting(line)
        is_port = setting and re.fullmatch(r"[0-9]{1,5}", setting[1]) and 1 <= int(setting[1]) <= 65535
        if setting and setting[0] in variables and not is_port:
            problems.append(f"{LOCAL} line {number} ({line}) is not a port: {setting[0]} takes a whole number from "
                            "1 to 65535, with nothing after it on the line.")
    return problems


def local_lines(existing: list[str], settings: dict[str, str]) -> list[str]:
    """env.local's lines with the settings start manages set: each in the place it already has, the new ones
    after the rest. Every other line (a note, a setting a person added) stays as it is, and in its place."""
    managed = {name for port in BROWSER_PORTS for name in (port.variable, port.address) if name}
    out, done = [], set()
    for line in existing:
        name = line.partition("=")[0].strip()
        if "=" not in line or name not in managed:
            out.append(line)
        elif name in settings and name not in done:
            out.append(f"{name}={settings[name]}")
            done.add(name)
    return out + [f"{name}={value}" for name, value in settings.items() if name not in done]


def choose_port(preferred: int, fallbacks: tuple[int, ...], is_free: Callable[[int], bool]) -> int | None:
    """The preferred port if it is free, else the first free fallback; None when every one is taken."""
    return next((p for p in (preferred, *fallbacks) if is_free(p)), None)


def address_of(port: BrowserPort, number: int) -> str:
    """The address a browser on this machine reaches a port on. Browsers send the Origin of
    http://localhost:80 as http://localhost, so 80 is left out; the launcher's ends with a slash, as
    LAUNCHER_EXTERNAL_URL always has."""
    address = "http://localhost" + ("" if number == 80 else f":{number}")
    return address + "/" if port.address == "LAUNCHER_EXTERNAL_URL" else address


def published_ports(config: dict) -> list[tuple[str, str, int, int]]:
    """(service, address, published port, container port) of every port a `docker compose config --format json`
    publishes."""
    return [(name, p.get("host_ip") or "0.0.0.0", int(p["published"]), int(p["target"]))
            for name, service in config.get("services", {}).items() for p in service.get("ports") or []
            if p.get("published")]


def held_by_aisc() -> set[int]:
    """The host ports this install's own running containers publish: theirs, so not taken."""
    ports = captured([Stack.docker, "ps", "--filter", f"label=com.docker.compose.project={project()}",
                      "--format", "{{.Ports}}"]).stdout
    return {int(p) for p in re.findall(r":(\d+)->", ports)}


#: the image the probe runs: the stack's own Caddy, which publishes these ports, so `up` would pull it anyway
PROBE_IMAGE = "caddy:2.10.2@sha256:c3d7ee5d2b11f9dc54f947f68a734c84e9c9666c92c88a7f30b9cba5da182adb"
#: the name every probe container starts with, so one left behind (a probe cut short) is found and removed
PROBE_PREFIX = "aisc-port-probe-"
#: how long one probe may take: a container that only binds and exits needs well under a second
PROBE_WAIT_S = float(os.environ.get("START_PROBE_WAIT_S", "10"))
#: how long fetching the probe's image may take: tens of megabytes, on a slow link or through a proxy
PULL_WAIT_S = float(os.environ.get("START_PULL_WAIT_S", "300"))


#: how Docker words a refusal of a port it cannot publish: Docker Desktop's forwarder (Windows, macOS), the
#: Linux daemon (a leftover forwarder, a program listening), Windows' reserved ranges and its own bind error
PORT_TAKEN = re.compile(r"ports are not available|port is already allocated|address already in use|"
                        r"bind: an attempt was made to access a socket in a way forbidden|"
                        r"only one usage of each socket address", re.IGNORECASE)

#: whether Docker left a call of the port check unanswered this start: no further probe is tried, each
#: would wait its full time on the same busy daemon
DOCKER_UNANSWERED = False
#: whether this start already said Docker could not check the ports: once is enough
PROBE_FAILED_SAID = False
#: the ports Docker refused although the host saw them free: taken inside Docker, out of sight of the host's tools
TAKEN_IN_DOCKER: set[int] = set()


def docker_says_port_taken(message: str) -> bool:
    """Whether a failed `docker run -p` failed because the port is taken, not for any other reason."""
    return bool(PORT_TAKEN.search(message))


def prepare_port_probe() -> None:
    """Remove probe containers an earlier start left behind, and make sure the probe's image is here. A leftover
    would hold its port and be taken for another program; the image is fetched once, said beforehand since it
    can take minutes, so no probe waits on it. Nothing here may stop or freeze the start: a call Docker does
    not answer in time leaves the host's own check to decide for the rest of the start."""
    global DOCKER_UNANSWERED
    names = docker_in_time([Stack.docker, "ps", "-a", "--filter", f"name={PROBE_PREFIX}", "--format", "{{.Names}}"],
                           DOCKER_CALL_WAIT_S)
    leftovers = [name for name in names.stdout.split() if name.startswith(PROBE_PREFIX)] if names else []
    image = None
    if names and (not leftovers or docker_in_time([Stack.docker, "rm", "-f", *leftovers], DOCKER_CALL_WAIT_S)):
        image = docker_in_time([Stack.docker, "image", "inspect", PROBE_IMAGE], DOCKER_CALL_WAIT_S)
    if image and image.returncode != 0:
        say("Fetching the image the port check uses (once) ...")
        image = docker_in_time([Stack.docker, "pull", "--quiet", PROBE_IMAGE], PULL_WAIT_S)
    if image is None:
        DOCKER_UNANSWERED = True


def docker_can_publish(port: int, host: str) -> bool | None:
    """Whether Docker itself can publish this port on this address: a container that only binds and exits.
    Docker Desktop publishes through its own VM, shared with WSL, where a program holding the port is out of
    sight of a bind on the host; so is a forwarder an earlier container left behind. False when Docker refuses
    the port as taken; None when the probe fails for any other reason (no image offline, a Docker error, no
    answer in time), and the host's own check decides."""
    global DOCKER_UNANSWERED
    if DOCKER_UNANSWERED:
        return None
    name = f"{PROBE_PREFIX}{port}"
    done = docker_in_time([Stack.docker, "run", "--rm", "--name", name, "--pull", "never", "-p", f"{host}:{port}:80",
                           "--entrypoint", "true", PROBE_IMAGE], PROBE_WAIT_S)
    if done is None:
        DOCKER_UNANSWERED = True
        docker_in_time([Stack.docker, "rm", "-f", name], DOCKER_CALL_WAIT_S)
        return None
    if done.returncode == 0:
        return True
    return False if docker_says_port_taken(done.stderr + done.stdout) else None


def free_for_docker(port: int, host: str) -> bool:
    """Whether start may publish this port: free on the host (port_is_free) and Docker can publish it
    (docker_can_publish). A refusal from Docker alone is remembered (TAKEN_IN_DOCKER), so the advice names
    Docker, not the host's tools; a probe that cannot tell leaves the host's answer, and says so once."""
    global PROBE_FAILED_SAID
    if not port_is_free(port, host):
        return False
    answer = docker_can_publish(port, host)
    if answer is None and not PROBE_FAILED_SAID:
        PROBE_FAILED_SAID = True
        say("Docker could not check the ports itself; going by this computer's own check.")
    if answer is False:
        TAKEN_IN_DOCKER.add(port)
    return answer is not False


def docker_side_hint(windows: bool | None = None) -> str:
    """What frees a port Docker cannot use although nothing on the host holds it. On Windows it is held inside
    Docker Desktop's VM or a WSL distribution, which share their network."""
    if os.name == "nt" if windows is None else windows:
        return ("The port is taken inside Docker Desktop or WSL: running wsl --shutdown and restarting Docker "
                "Desktop frees ports left by earlier runs.")
    return ("Something inside Docker holds it, such as a forwarder an earlier container left: restarting Docker "
            "frees it.")


def who_holds(port: int) -> str:
    """The command that shows which program holds a port, on this system."""
    return f"netstat -ano | findstr :{port}" if os.name == "nt" else f"sudo lsof -i :{port}"


def settle_ports(published: list[tuple[str, str, int, int]], held: set[int], kept: dict[str, str], may_move: bool,
                 is_free: Callable[[int, str], bool], taken_in_docker: Callable[[int], bool] = lambda port: False
                 ) -> tuple[dict[str, str], list[str], list[str]]:
    """The browser ports' settings for env.local, one problem per port that stops the start, and one line per
    port that moved this start.

    Each browser port is tried on the port this install kept, else its preferred one. When that is taken, an
    install not served over https (may_move) moves to the first free one of its preferred port and fallbacks:
    start tells the sign-in the install's addresses, so data is no reason to stay. One served over https must
    not, since its public names lead to the ports it has. A port picked for one role is never offered to the
    next. On plain http a port that is not at its preferred one gets its address written too; at its preferred
    one, or on an install served over https, the install's own address stands (it sets it itself). Every other
    published port is checked as it is. A port this install's own containers hold is not taken. A port only
    Docker refused (taken_in_docker) is explained as Docker's: the host's tools would show nothing holding it."""
    picked: set[int] = set()

    def what_frees(port: int) -> str:
        if taken_in_docker(port):
            return f"Docker cannot use it, although nothing on this computer holds it. {docker_side_hint()}"
        return f"Stop the program that holds it (see which with: {who_holds(port)})."

    def free(port: int, host: str = "0.0.0.0") -> bool:
        return port not in picked and (port in held or is_free(port, host))

    settings: dict[str, str] = {}
    problems, moved = [], []
    for role in BROWSER_PORTS:
        first = int(kept[role.variable]) if role.variable in kept else role.preferred
        if free(first, role.host):
            chosen = first
        elif not may_move:
            chosen = None
            problems.append(f"Port {first} is taken, and an install served over https does not move to another "
                            f"port. {what_frees(first)}")
        else:
            chosen = choose_port(role.preferred, role.fallbacks, lambda p, host=role.host: free(p, host))
            if chosen is None:
                tried = ", ".join(str(p) for p in (role.preferred, *role.fallbacks))
                in_docker = any(map(taken_in_docker, (role.preferred, *role.fallbacks)))
                inside = " " + docker_side_hint() if in_docker else ""
                problems.append(f"Ports {tried} are all taken. Free one of them (see which program holds one "
                                f"with: {who_holds(role.preferred)}).{inside}")
            else:
                where = "(Docker cannot use it)" if taken_in_docker(first) else "on this computer"
                moved.append(f"Port {first} is taken {where}, so AISC uses {address_of(role, chosen)} "
                             f"instead ({role.variable}={chosen}, kept in {LOCAL}).")
        if chosen is not None:
            picked.add(chosen)
            settings[role.variable] = str(chosen)
            # an https install names itself, and env.local comes last in env.runtime: a localhost address
            # written there would override its public names, so a port it kept stays published but unnamed
            if chosen != role.preferred and role.address and may_move:
                settings[role.address] = address_of(role, chosen)
    for service, host, port, target in published:
        # a browser port is published through its variable, on one of its own candidates; the engine's
        # https port (443) is Caddy's 8005 too, but no browser port moves there, so it is checked as it is
        role = next((r for r in BROWSER_PORTS if (r.service, r.target) == (service, target)), None)
        if role and port in {role.preferred, *role.fallbacks, int(kept.get(role.variable, role.preferred))}:
            continue
        if not free(port, host):
            problems.append(f"Port {port} is taken. {what_frees(port)}")
    return settings, problems, moved
