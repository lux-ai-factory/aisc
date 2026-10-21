# /// script
# requires-python = ">=3.10"
# dependencies = ["cryptography>=42"]
# ///
"""Install and run AISC on Linux, macOS and Windows alike: the commands a person installing it runs.

    uv run scripts/aisc.py start                              # check, make the secrets, build, start, wait
    uv run scripts/aisc.py secrets                            # make the secrets if they are missing
    uv run scripts/aisc.py secrets --rotate                   # make new ones, replacing what is there
    uv run scripts/aisc.py secrets --add-ledger-key           # add the next version of the ledger's master key
    uv run scripts/aisc.py secrets --rotate-one NAME          # a new IMMUDB_ADMIN_PASSWORD, LEDGER_IMMUDB_PASSWORD
                                                              # or ENGINE_IMMUDB_PASSWORD
    uv run scripts/aisc.py password                           # the admin and user accounts' passwords
    uv run scripts/aisc.py rotate-infra-password NAME [--ask] # a new value for an infrastructure password

scripts/start.sh, scripts/secrets.sh and scripts/rotate-infra-password.sh run the same commands. Only Python
and Docker are needed on the host: no bash, openssl, curl or awk, so a Windows terminal will do. uv fetches
Python and the one library this needs (cryptography, for the immudb signing key).

The secrets
-----------
A secret committed to the repo is a secret every clone shares. The worst of them would be the gateway's cookie
secret: whoever holds it can mint a session cookie for any user, offline, and that cookie is the session every
module trusts. So none of them has a default. The compose files refuse to start without these; `secrets` writes
them once into env.secrets, which is git-ignored. The realm import takes the one it holds from Keycloak's
environment (${GATEWAY_CLIENT_SECRET}).

PLATFORM_SECRETS_KEY is the exception to --rotate: it encrypts the LLM API keys stored in every project's
database, so a fresh one would make all of them unreadable. --rotate keeps it. To rotate it: prepend a new Fernet
key to it (comma list, newest first), restart the platform, run
  python -m platform_service.llm_store rotate
in the platform container, then drop the old key from the list.

The ledger's two secrets survive --rotate too:
- PLATFORM_LEDGER_KEYS is versioned ("v1:<hex>,v2:<hex>") and every version is kept for ever, because the
  digests in immudb were made with them. Rotating means adding the next version (--add-ledger-key) and
  restarting the platform; new digests use it, old ones still check.
- LEDGER_IMMUDB_PASSWORD (the platform's immudb user, aisc_ledger) and ENGINE_IMMUDB_PASSWORD (the engine's,
  aisc_engine) live in immudb too once the users exist; change them with --rotate-one, which ledger-pool then
  applies in immudb at the next start.

The infrastructure's own passwords (the Postgres superuser, MinIO's root, RabbitMQ, Keycloak's bootstrap admin,
the realm's admin and user accounts) are made here too. Their images apply them only when their volume is first
made, so:
- --rotate keeps them (a new value would no longer open the existing volume);
- an install made before they were generated runs on the values env.plugin_downloader used to hold. When
  env.secrets lacks one, this writes the value that install runs on (from its env.runtime, or else the old
  tracked value), never a new one. Such an install is on well-known passwords until rotate-infra-password
  changes each, in its service and then in env.secrets; a new install gets random ones.

The realm's two accounts are admin / admin and user / user on a local install: its sign-in is reached from this
machine only (Keycloak is published on 127.0.0.1). An install served to others (CADDY_DOMAIN https://, from the
environment or env.plugin_downloader) gets generated passwords for them.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import secrets as random_source
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
OUT = "env.secrets"
COMBINED = "env.runtime"   # what compose is pointed at: the settings plus the secrets
TRACKED = "env.plugin_downloader"
LOCAL = "env.local"         # this install's own settings, chosen by start (git-ignored)
#: the engine's ports: the one it prefers, then the ones a new install moves to when that one is taken
ENGINE_PORTS: dict[str, tuple[int, tuple[int, ...]]] = {"ENGINE_PORT": (80, (8080, 8090, 8000, 8880, 8888)),
                                                       "ENGINE_HTTPS_PORT": (443, (8443, 8453, 9443))}
SIGNING_KEY, SIGNING_PUB = "immudb-signing.key", "immudb-signing.pub"
#: the Compose project: aisc, unless AISC_PROJECT names another (a second copy beside an install's data)
PROJECT = os.environ.get("AISC_PROJECT", "aisc")
COMPOSE = ["docker", "compose", "-p", PROJECT, "--env-file", COMBINED, "-f", "docker-compose.plugin_downloader.yml",
           "-f", "docker-compose-infra.development.yml", "-f", "docker-compose.development.yml"]
#: the docker command start found on PATH (see find_docker); every docker call runs this one
DOCKER = "docker"
UP_HINT = (f"  docker compose -p {PROJECT} --env-file env.runtime -f docker-compose.plugin_downloader.yml \\\n"
           "    -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d")


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


# ---------------------------------------------------------------------------------------------- the secrets

# Every secret, in the order a new env.secrets lists them, with the kind of value it takes. A secret added here
# reaches existing installs too: a plain run appends whatever an env.secrets lacks, never replacing a value that
# is there.
SECRETS = [
    # the infrastructure (VOLUME_BOUND below): Postgres superuser, MinIO root, RabbitMQ, Keycloak's admin
    ("POSTGRES_PASSWORD", "rand"),
    ("S3_PASSWORD", "rand"),
    ("RABBITMQ_PASSWORD", "rand"),
    ("KEYCLOAK_ADMIN_PASSWORD", "rand"),
    # the realm's two development accounts, admin and user: the realm import puts these into it, and its
    # database keeps them after, so they are volume-bound too. admin / admin and user / user on a local install,
    # generated on one served to others over https (account below)
    ("AISC_ADMIN_PASSWORD", "account"),
    ("AISC_USER_PASSWORD", "account"),
    ("GATEWAY_COOKIE_SECRET", "cookie"),
    ("GATEWAY_CLIENT_SECRET", "rand"),
    ("DJANGO_SECRET_KEY", "rand"),
    ("INTERNAL_API_KEY", "rand"),
    ("SUPERSET_SECRET_KEY", "rand"),
    # signs the dashboard's guest tokens (embedding is on): never Superset's published default
    ("SUPERSET_GUEST_TOKEN_SECRET", "rand"),
    # the platform's calls to the dashboard's bridge (/api/v1/aisc_project); with none, it refuses them all
    ("DASHBOARD_BRIDGE_TOKEN", "rand"),
    ("REPORT_SERVICE_TOKEN", "rand"),
    # Keycloak's and Superset's own database roles (init/keycloak-role.sql, init/superset-role.sql)
    ("KEYCLOAK_DB_PASSWORD", "rand"),
    ("SUPERSET_DB_PASSWORD", "rand"),
    ("REPORT_RO_PASSWORD", "rand"),
    ("REPORT_COMPOSER_PASSWORD", "rand"),
    ("INSPECTOR_PASSWORD", "rand"),
    # One token per agentic system, so each agent resolves only its own choice and key.
    ("PLATFORM_CARD_AGENT_TOKEN", "rand"),
    ("PLATFORM_RISK_MAPPER_TOKEN", "rand"),
    # the plugin-side client of Manage -> Connections resolves a connection with it (platform, eval worker)
    ("PLATFORM_CONNECTIONS_TOKEN", "rand"),
    # One token per caller edge of the service-only APIs: each is held by its caller and its callee only, so no
    # service can call another with a token it was not given.
    ("QUALIFICATION_AGENTS_TO_WEB_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_AGENTS_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN", "rand"),
    ("QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_PREFILL_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_PDF_TOKEN", "rand"),
    ("CONTROLS_WEB_TO_PDF_TOKEN", "rand"),
    ("PLATFORM_SECRETS_KEY", "fernet"),
    # immudb's superuser: compose starts immudb with IMMUDB_FORCE_ADMIN_PASSWORD, so a new value is applied at
    # its next start
    ("IMMUDB_ADMIN_PASSWORD", "immudbpw"),
    # the ledger: the platform's immudb user, and its versioned master keys (both kept by --rotate)
    ("LEDGER_IMMUDB_PASSWORD", "immudbpw"),
    # the engine's own immudb user, aisc_engine, on auditdb only (read on defaultdb): ledger-pool makes it with
    # this password, so like the ledger user's it is kept by --rotate (--rotate-one changes it)
    ("ENGINE_IMMUDB_PASSWORD", "immudbpw"),
    ("PLATFORM_LEDGER_KEYS", "ledgerkey"),
    # platform_rw, the platform service's database role: postgres-setup applies it on every start
    ("PLATFORM_RW_PASSWORD", "rand"),
    # qualification_rw, the qualification app's database role: postgres-setup applies it on every start
    ("QUALIFICATION_RW_PASSWORD", "rand"),
    # control_objectives_rw, the control objectives service's database role: postgres-setup applies it
    ("CONTROL_OBJECTIVES_RW_PASSWORD", "rand"),
    ("CONTROLS_RW_PASSWORD", "rand"),
    ("CATALOGUE_RW_PASSWORD", "rand"),
    ("DEVPI_ROOT_PASSWORD", "rand"),
    ("ENGINE_RW_PASSWORD", "rand"),
    # keys the engine's run tickets; the backend only (the eval worker runs plugin code)
    ("RUN_TICKET_KEY", "rand"),
    # dashboard_ro, the results dashboard's read role: postgres-setup applies it
    ("DASHBOARD_RO_PASSWORD", "rand"),
    # the dashboard's own Redis (Superset's cache, dashboard-redis): its password, held by the dashboard only
    ("DASHBOARD_REDIS_PASSWORD", "rand"),
    # the ledger witness: Caddy sends it, the platform checks it
    ("AISC_WITNESS_GATEWAY_SECRET", "rand"),
    # one token per caller that posts ledger events, held by it and the platform only
    ("PLATFORM_LEDGER_ENGINE_TOKEN", "rand"),
    ("PLATFORM_LEDGER_DASHBOARD_TOKEN", "rand"),
    ("PLATFORM_LEDGER_AGENTS_TOKEN", "rand"),
]
# The infrastructure passwords: their volumes hold them (see the top of this file).
VOLUME_BOUND = ("POSTGRES_PASSWORD", "S3_PASSWORD", "RABBITMQ_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
                "AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD")
# What --rotate keeps: replacing any of these would make stored data unreadable or unverifiable.
# DEVPI_ROOT_PASSWORD: devpi's volume holds root's password and devpi refuses to start on another one.
# SUPERSET_SECRET_KEY: it encrypts the database connections Superset stores; to change it, set
# PREVIOUS_SECRET_KEY to the old one and run `superset re-encrypt-secrets` in the dashboard container.
KEPT_ON_ROTATE = ("PLATFORM_SECRETS_KEY", "LEDGER_IMMUDB_PASSWORD", "ENGINE_IMMUDB_PASSWORD", "PLATFORM_LEDGER_KEYS",
                  "DEVPI_ROOT_PASSWORD", "SUPERSET_SECRET_KEY", *VOLUME_BOUND)
# The immudb passwords the stack brings to a new value itself (--rotate-one).
ROTATE_ONE = ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD", "ENGINE_IMMUDB_PASSWORD")
LEDGER_KEYS = re.compile(r"v[1-9][0-9]*:[0-9a-f]{64}(,v[1-9][0-9]*:[0-9a-f]{64})*")


def rand() -> str:
    return random_source.token_hex(32)


def cookie() -> str:
    # oauth2-proxy decodes this as base64url and wants exactly 32 bytes out. With padding it does not decode,
    # and it then measures the string itself and refuses to start: "cookie_secret must be 16, 24, or 32 bytes".
    return base64.urlsafe_b64encode(random_source.token_bytes(32)).decode().rstrip("=")


def fernet() -> str:
    # Fernet wants urlsafe base64 of 32 bytes WITH its `=` padding: 44 characters.
    return base64.urlsafe_b64encode(random_source.token_bytes(32)).decode()


def immudbpw() -> str:
    # immudb refuses a password without an upper and a lower case letter, a digit and a symbol, or over 32
    # characters: 24 random hex (96 bits) behind a fixed prefix that has one of each.
    return "Az9-" + random_source.token_hex(12)


def served_over_https() -> bool:
    domain = os.environ.get("CADDY_DOMAIN") or (value_in("CADDY_DOMAIN", TRACKED) if Path(TRACKED).is_file() else "")
    return domain.strip('"').startswith("https://")


def account(name: str) -> str:
    if served_over_https():
        return rand()
    return {"AISC_ADMIN_PASSWORD": "admin", "AISC_USER_PASSWORD": "user"}.get(name) or rand()


def fresh(kind: str, name: str) -> str:
    """A new value of this kind; the ledger's master key list starts at version 1."""
    return {"cookie": cookie, "fernet": fernet, "immudbpw": immudbpw, "ledgerkey": lambda: "v1:" + rand(),
            "account": lambda: account(name)}.get(kind, rand)()


def lines_of(path: str) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines()


def value_in(name: str, path: str) -> str:
    """The value of NAME in a file: empty when the line is missing or has no value."""
    for line in lines_of(path):
        if line.startswith(name + "="):
            return line[len(name) + 1:]
    return ""


def kept_value(name: str) -> str:
    return value_in(name, OUT) if Path(OUT).is_file() else ""


def was_tracked(name: str) -> str:
    """The value env.plugin_downloader held for an infrastructure password before they were generated."""
    return {"KEYCLOAK_ADMIN_PASSWORD": "admin", "AISC_ADMIN_PASSWORD": "admin", "AISC_USER_PASSWORD": "user"}.get(
        name, "dev-password")


def running_value(name: str) -> str:
    """An install whose env.secrets predates the infrastructure passwords: the value its volumes were made with.
    Its env.runtime says what it runs on; without one, the value env.plugin_downloader held."""
    value = value_in(name, COMBINED) if Path(COMBINED).is_file() else ""
    return value or was_tracked(name)


def missing_value(name: str, kind: str, existed: bool) -> str:
    """The value a secret takes when env.secrets lacks it: a new one, but for an existing install's
    infrastructure password, the one it runs on."""
    return running_value(name) if existed and name in VOLUME_BOUND else fresh(kind, name)


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


def add_ledger_key() -> None:
    """The next version of the ledger's master key, appended; nothing else changes."""
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    current = value_in("PLATFORM_LEDGER_KEYS", OUT)
    if not current:
        raise Refused(f"PLATFORM_LEDGER_KEYS is missing from {OUT}: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    if not LEDGER_KEYS.fullmatch(current):
        raise Refused(f"PLATFORM_LEDGER_KEYS in {OUT} is not v<N>:<64 hex>[,...]: fix it by hand; nothing changed")
    following = max(int(k.split(":", 1)[0][1:]) for k in current.split(",")) + 1
    write_beside(OUT, text_of(with_value(lines_of(OUT), "PLATFORM_LEDGER_KEYS", f"{current},v{following}:{rand()}")))
    say(f"added ledger key version v{following} to {OUT} (restart the platform to sign new digests with it)")


def rotate_one(name: str) -> None:
    """A new value for one of immudb's passwords; every other line of env.secrets stays as it is. A restart
    finishes it: immudb applies its superuser's at start (IMMUDB_FORCE_ADMIN_PASSWORD), and ledger-pool, as the
    superuser, gives aisc_ledger and aisc_engine their new ones."""
    if name not in ROTATE_ONE:
        raise Refused(f"--rotate-one takes one of: {' '.join(ROTATE_ONE)} (the immudb passwords the stack brings to "
                      "a new value itself)", 2)
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    if not any(line.startswith(name + "=") for line in lines_of(OUT)):
        raise Refused(f"{name} is missing from {OUT}: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    write_beside(OUT, text_of(with_value(lines_of(OUT), name, immudbpw())))
    hint = ("  docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml \\\n"
            "    -f docker-compose-infra.development.yml -f docker-compose.development.yml")
    say(f"rotated {name} in {OUT}. To apply it, recreate immudb, ledger-pool, platform and aisc-backend:",
        hint + " up -d immudb ledger-pool platform aisc-backend",
        "  ledger-pool must exit 0 (docker compose -p aisc ps -a ledger-pool), then, whichever name was rotated:",
        hint + " restart aisc-backend",
        "  (immudb's restart ended the engine's audit session, and the engine does not log in again by itself)")


def new_file(rotate: bool, existed: bool) -> list[str]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"# Generated by scripts/aisc.py secrets on {stamp}. Not in git.",
             "# Rotating these signs everyone out. Keycloak keeps the old GATEWAY_CLIENT_SECRET: set the new one",
             "# on its aisc-gateway client (admin console, Clients, Credentials), or delete the aisc realm to "
             "re-import it."]
    for name, kind in SECRETS:
        if name in KEPT_ON_ROTATE and kept_value(name):
            lines.append(f"{name}={kept_value(name)}")
        else:
            lines.append(f"{name}={missing_value(name, kind, existed)}")
    return lines


def with_missing_added(existed: bool) -> list[str]:
    say(f"{OUT} exists; keeping its values and adding any that are missing (--rotate to replace)")
    lines = lines_of(OUT)
    for name, kind in SECRETS:
        if not any(line.startswith(name + "=") for line in lines):
            lines.append(f"{name}={missing_value(name, kind, existed)}")
            if name in VOLUME_BOUND:
                say(f"added {name} to {OUT}: the value this install already runs on (its volume holds it)")
            else:
                say(f"added {name} to {OUT}")
    return lines


def make_signing_key() -> None:
    """immudb signs its states with this key; the platform checks them with the public half. Made once and never
    replaced, --rotate included: a new key would make every saved state unverifiable. Private to this user; the
    stack's immudb-key job hands immudb its own copy."""
    key, pub = Path(SIGNING_KEY), Path(SIGNING_PUB)
    if not key.is_file() or key.stat().st_size == 0:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        made = ec.generate_private_key(ec.SECP256R1())
        pub.write_bytes(made.public_key().public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo))
        new = Path(SIGNING_KEY + ".new")
        new.write_bytes(made.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
        private(str(new))
        os.replace(new, key)
        say(f"made {SIGNING_KEY} and {SIGNING_PUB}")
    if os.name != "nt":
        os.chmod(key, 0o600)
        os.chmod(pub, 0o644)


def write_runtime() -> None:
    """compose takes one --env-file, so the settings and the secrets are combined into one. Also git-ignored,
    also made again from its two sources. The infrastructure passwords come from env.secrets only (a value still
    in the tracked file is dropped), and first: compose expands a setting built from one (CELERY_BROKER_URL holds
    $RABBITMQ_PASSWORD) with the values defined above it in the file."""
    def infra(line: str) -> bool:
        name = line.split("=", 1)[0]
        return " " not in name and name in VOLUME_BOUND

    secret_lines, tracked = lines_of(OUT), lines_of(TRACKED)
    # this install's own settings (the ports start chose) come last, so compose takes them over the tracked ones
    local = lines_of(LOCAL) if Path(LOCAL).is_file() else []
    combined = ([l for l in secret_lines if infra(l)] + [l for l in tracked if not infra(l)]
                + [l for l in secret_lines if not infra(l)] + local)
    write_beside(COMBINED, text_of(combined))
    say(f"wrote {COMBINED} ({TRACKED} + {OUT}{' + ' + LOCAL if local else ''})")


def port_is_free(port: int, host: str) -> bool:
    """Whether Docker could publish this port on this address. Binding it is the real test; Windows refuses
    one in its reserved ranges with an access error, which means taken. Where Linux refuses the bind outright
    (a port below 1024 without root), whether something answers on it decides, on loopback and on each address
    of the machine."""
    with socket.socket() as s:
        # As Docker binds on Linux: past connections still closing (TIME_WAIT) do not hold the port. Only there:
        # on Windows this option would let the test bind over a program that is listening, and on macOS (BSD
        # sockets) a bind on 0.0.0.0 would succeed beside a program listening on 127.0.0.1 only.
        if sys.platform.startswith("linux"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except PermissionError:
            if os.name == "nt":
                return False   # Windows' reserved ranges (Hyper-V, WSL): Docker cannot publish there either
        except OSError:
            return False
    # A program listening on the machine's network address only is not on 127.0.0.1, so each of its IPv4
    # addresses is tried too.
    addresses = ["127.0.0.1"]
    try:
        addresses += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    for address in dict.fromkeys(addresses):
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex((address, port)) == 0:
                return False
    return True


def read_local() -> dict[str, str]:
    """The settings in env.local as NAME=value lines, one pair of quotes around a value taken off: a person
    editing the file may quote it, as in the other env files. Comments and lines without a name are not settings."""
    kept = {}
    for line in lines_of(LOCAL) if Path(LOCAL).is_file() else []:
        name, found, value = line.partition("=")
        if found and not name.lstrip().startswith("#"):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            kept[name.strip()] = value
    return kept


def local_lines(existing: list[str], settings: dict[str, str]) -> list[str]:
    """env.local's lines with the settings start manages set: each in the place it already has, the new ones
    after the rest. Every other line (a note, a setting a person added) stays as it is, and in its place."""
    managed = {*ENGINE_PORTS, "API_URL_EXTERNAL"}
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


def engine_settings(port: int, https_port: int) -> dict[str, str]:
    """What the engine's ports change: compose publishes them. Only a moved engine gets an address here: on
    port 80 the install's own API_URL_EXTERNAL stands (an https or other-host install sets it itself)."""
    settings = {"ENGINE_PORT": str(port), "ENGINE_HTTPS_PORT": str(https_port)}
    if port != 80:
        settings["API_URL_EXTERNAL"] = f"http://localhost:{port}"
    return settings


def published_ports(config: dict) -> list[tuple[str, int, int]]:
    """(address, published port, container port) of every port a `docker compose config --format json` publishes."""
    return [(p.get("host_ip") or "0.0.0.0", int(p["published"]), int(p["target"]))
            for service in config.get("services", {}).values() for p in service.get("ports") or []
            if p.get("published")]


def find_docker() -> str | None:
    """The docker command on this process's own PATH, or None. Windows looks a program up through the parent
    process's search path, not the PATH given to a child, so running `docker` and seeing it work proves nothing
    about this PATH."""
    return shutil.which("docker", path=os.environ.get("PATH"))


def held_by_aisc() -> set[int]:
    """The host ports this install's own running containers publish: theirs, so not taken."""
    ports = captured([DOCKER, "ps", "--filter", f"label=com.docker.compose.project={PROJECT}",
                      "--format", "{{.Ports}}"]).stdout
    return {int(p) for p in re.findall(r":(\d+)->", ports)}


def has_data() -> bool:
    """Whether this install has run before: its database volume exists, and with it a sign-in set up for the
    engine's address."""
    return captured([DOCKER, "volume", "inspect", f"{PROJECT}_postgres_data"]).returncode == 0


def who_holds(port: int) -> str:
    """The command that shows which program holds a port, on this system."""
    return f"netstat -ano | findstr :{port}" if os.name == "nt" else f"sudo lsof -i :{port}"


def settle_ports(published: list[tuple[str, int, int]], held: set[int], kept: dict[str, str], may_move: bool,
                 is_free: Callable[[int, str], bool]) -> tuple[dict[str, str], list[str]]:
    """The engine's settings for env.local, and one problem per port that stops the start.

    The engine's ports are Caddy's (container port 8005): the ones this install kept, else 80 and 443. When one
    is taken, an install with no data yet (may_move) moves to the first free fallback, also off a port it kept
    from a start that never got as far as the sign-in; one that has run before must not, since its sign-in
    knows only its address. Every other published port is checked
    as it is. A port this install's own containers hold is not taken."""
    def free(port: int, host: str = "0.0.0.0") -> bool:
        return port in held or is_free(port, host)

    problems, chosen = [], {}
    for name, (preferred, fallbacks) in ENGINE_PORTS.items():
        port = int(kept[name]) if name in kept else preferred
        if free(port):
            chosen[name] = port
        elif not may_move:
            problems.append(f"Port {port} is taken, and this install's sign-in is set up for it. Stop the program "
                            f"that holds it (see which with: {who_holds(port)}).")
        else:
            moved = choose_port(preferred, fallbacks, free)
            if moved is None:
                tried = ", ".join(str(p) for p in (preferred, *fallbacks))
                problems.append(f"Ports {tried} are all taken. Free one of them (see which program holds one "
                                f"with: {who_holds(preferred)}).")
            else:
                chosen[name] = moved
    for host, port, target in published:
        if target != 8005 and not free(port, host):
            problems.append(f"Port {port} is taken. Stop the program that holds it (see which with: "
                            f"{who_holds(port)}).")
    settings = engine_settings(chosen["ENGINE_PORT"], chosen["ENGINE_HTTPS_PORT"]) if len(chosen) == 2 else {}
    return settings, problems


def make_secrets(args: list[str]) -> None:
    # Every file written here holds secrets or is made from them: private from the moment it exists.
    os.umask(0o077)
    existed = Path(OUT).is_file()
    mode = args[0] if args else ""
    if mode == "--add-ledger-key":
        add_ledger_key()
    elif mode == "--rotate-one":
        rotate_one(args[1] if len(args) > 1 else "")
    rotate = mode == "--rotate"

    if rotate or not existed:
        lines = new_file(rotate, existed)
        made = f"{len(SECRETS)} secrets, {'rotated' if rotate else 'new'}"
    else:
        lines = with_missing_added(existed)
        made = "kept, missing ones added"
    # An empty value is a missing one (an earlier run left NAME=): made again in its place.
    for name, kind in SECRETS:
        first = next((line for line in lines if line.startswith(name + "=")), None)
        if first == name + "=":
            lines = with_value(lines, name, fresh(kind, name))
            say(f"generated the empty {name} again")
    write_beside(OUT, text_of(lines))
    say(f"wrote {OUT} ({made})")

    # The one with a shape requirement, checked here rather than discovered by a gateway that will not start.
    length = len(value_in("GATEWAY_COOKIE_SECRET", OUT))
    if length != 43:
        raise Refused(f"GATEWAY_COOKIE_SECRET is {length} characters; oauth2-proxy needs 32 bytes base64url (43)")
    make_signing_key()
    write_runtime()
    say("", "run the stack with:", UP_HINT)


def show_passwords(_args: list[str]) -> None:
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (or start) first")
    say(f"admin  {value_in('AISC_ADMIN_PASSWORD', OUT)}", f"user   {value_in('AISC_USER_PASSWORD', OUT)}")


# ------------------------------------------------------------------------------- an infrastructure password

ROTATABLE = ("POSTGRES_PASSWORD", "RABBITMQ_PASSWORD", "S3_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
             "AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD")
# kcadm signs in to the master realm as Keycloak's admin, then sets one account's password. Its arguments stay
# inside the container; its session file is removed again.
KCADM = """
    kc=/opt/keycloak/bin/kcadm.sh; cfg=/tmp/kcadm-rotate.json
    "$kc" config credentials --config "$cfg" --server http://localhost:8080 --realm master \\
      --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$ADMIN_VALUE" >/dev/null \\
      && "$kc" set-password --config "$cfg" -r "$REALM" --username "${ACCOUNT:-$KC_BOOTSTRAP_ADMIN_USERNAME}" --new-password "$NEW_VALUE"
    s=$?; rm -f "$cfg"; exit $s"""
# psql reads the value from its environment (\\getenv): it is on no command line, not even the container's
PSQL = "\\getenv pw NEW_VALUE\n\\getenv role POSTGRES_USER\nALTER ROLE :\"role\" PASSWORD :'pw';\n"
UNSAFE = re.compile(r"""[\s'"$#\\]""")


def chosen_value(name: str) -> str:
    """A password the person chooses: typed twice and never shown at a terminal, one line from a pipe."""
    if sys.stdin.isatty():
        value = getpass.getpass(f"new {name}: ")
        if getpass.getpass("again: ") != value:
            raise Refused("the two did not match; nothing changed", 2)
    else:
        value = sys.stdin.readline().rstrip("\r\n")
    if len(value) < 12 or UNSAFE.search(value):
        raise Refused("refused: at least 12 characters, and no space, quote, $, # or backslash; nothing changed", 2)
    return value


def rotate_infra_password(args: list[str]) -> None:
    """A new value for a password the infrastructure keeps in its own volume. These are applied by their service
    only when its volume is first made, so a new value is set in the service itself first, on the running stack,
    and written to env.secrets and env.runtime only once the service took it: a refusal leaves both files as they
    were. The value goes to the container by name (docker exec -e NAME), never on a command line, and is never
    printed. A chosen password has at least 12 characters and none of: space, quotes, $, # or backslash, which the
    env file compose reads would take apart. MinIO takes its new root password when it is recreated."""
    name = args[0] if args else ""
    mode = args[1] if len(args) > 1 else ""
    if name not in ROTATABLE or mode not in ("", "--ask"):
        raise Refused(f"usage: scripts/aisc.py rotate-infra-password NAME [--ask], NAME one of: {' '.join(ROTATABLE)}", 2)
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    old = value_in(name, OUT)
    if not old:
        raise Refused(f"{name} is missing from {OUT}: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    new = chosen_value(name) if mode == "--ask" else rand()
    env = {**os.environ, "OLD_VALUE": old, "NEW_VALUE": new}

    def docker(*argv: str, admin: str | None = None, realm: str = "", account: str = "", stdin: str | None = None):
        run_env = env if admin is None else {**env, "ADMIN_VALUE": admin, "REALM": realm, "ACCOUNT": account}
        r = subprocess.run([find_docker() or DOCKER, *argv], env=run_env, input=stdin if stdin is not None else "", text=True,
                           stdout=subprocess.DEVNULL)
        if r.returncode != 0:
            raise Refused(f"the service did not take the new {name}; nothing changed", r.returncode)

    def keycloak_set(admin: str, realm: str, account: str = "") -> None:
        docker("exec", "-e", "ADMIN_VALUE", "-e", "NEW_VALUE", "-e", "REALM", "-e", "ACCOUNT", "keycloak",
               "bash", "-c", KCADM, admin=admin, realm=realm, account=account)

    if name == "POSTGRES_PASSWORD":
        docker("exec", "-i", "-e", "NEW_VALUE", "postgres", "sh", "-c",
               'exec psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d postgres', stdin=PSQL)
    elif name == "RABBITMQ_PASSWORD":
        docker("exec", "-e", "NEW_VALUE", "rabbitmq", "sh", "-c",
               'rabbitmqctl --quiet change_password "$RABBITMQ_DEFAULT_USER" "$NEW_VALUE"')
    elif name == "KEYCLOAK_ADMIN_PASSWORD":
        keycloak_set(old, "master")
    elif name in ("AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD"):
        keycloak_set(value_in("KEYCLOAK_ADMIN_PASSWORD", OUT), "aisc", "admin" if name == "AISC_ADMIN_PASSWORD" else "user")

    os.umask(0o077)
    write_beside(OUT, text_of(with_value(lines_of(OUT), name, new)))
    # env.runtime, which compose reads, is made from env.secrets again
    with open(os.devnull, "w") as quiet:
        stdout, sys.stdout = sys.stdout, quiet
        try:
            make_secrets([])
        finally:
            sys.stdout = stdout
    say(f"{name} has a new value in the service, {OUT} and env.runtime. Recreate what reads it:", UP_HINT)


# --------------------------------------------------------------------------------------------------- start

BRANCH = "feat/unified-modules"


def captured(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", "")


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


def keycloak_realm_url() -> str:
    """The realm's own page on Keycloak's published port on this machine (the last KEYCLOAK_PORT_EXTERNAL line
    of env.runtime, else 8081), or START_SIGN_IN_URL. Not its public address: an https or other-host install's
    name may not resolve from here (hairpin NAT, a self-signed certificate) though the install is healthy."""
    given = os.environ.get("START_SIGN_IN_URL")
    if given:
        return given
    port = "8081"
    if Path(COMBINED).is_file():
        for line in lines_of(COMBINED):
            if line.startswith("KEYCLOAK_PORT_EXTERNAL="):
                port = line.split("=", 1)[1].strip().strip("'\"") or port
    return f"http://localhost:{port}/realms/aisc"


def not_running(lines: str) -> list[str]:
    return [l for l in lines.splitlines() if l and not re.search(r"\t(Up|running|Exited \(0\))", l)]


def start(_args: list[str]) -> None:
    """Install and start AISC in one command.

    1. Refuses a checkout that cannot work, before anything runs: Docker not running, Compose older than 2.17, a
       branch other than feat/unified-modules (master's files are older), submodules not checked out. Warns when
       the disk is nearly full.
    2. Makes the secrets (once, then it keeps them; run again after a pull).
    3. Checks every port the stack publishes. On a new install served over plain http, a taken 80 or 443 moves
       the engine to a free fallback (8080 ..., 8443 ...); the choice is kept in env.local and never changes on
       its own. Any other taken port, or a taken one on an install that has run before, stops here, with the
       command that shows which program holds it.
    4. Builds every image. A failed build is tried twice more, with fewer builds at once: a timeout on a slow
       network or a laptop short of memory usually passes the second time, and the cache keeps what was built.
    5. Starts the stack and waits until the sign-in page answers: `up -d` returns before the gateway's sign-in is
       ready, and a page opened then shows 502. Then names, as a warning, every one-shot service that exited
       non-zero (plugin-publisher when a plugin did not build).
    6. Lists the local controls (local_controls/) every project catalogue gets; one it cannot read is a warning,
       not a failure.

    Settings for the impatient or the tests: START_WAIT_S (default 300), START_POLL_S (5), START_URL,
    START_SIGN_IN_URL (Keycloak's realm page), START_MIN_DISK_GB (20)."""
    wait_s = float(os.environ.get("START_WAIT_S", "300"))
    poll_s = float(os.environ.get("START_POLL_S", "5"))
    url = os.environ.get("START_URL", "http://localhost:8100/")
    min_disk_gb = int(os.environ.get("START_MIN_DISK_GB", "20"))

    # 1. The checkout and the machine
    global DOCKER
    found = find_docker()
    if found is None or captured([found, "info"]).returncode != 0:
        raise Refused("Docker is not running (or this user may not use it). Start Docker Desktop or the docker "
                      "service, then run this again.")
    DOCKER = COMPOSE[0] = found
    version = captured([DOCKER, "compose", "version", "--short"]).stdout.strip().lstrip("v")
    parts = re.match(r"(\d+)\.(\d+)", version)
    if not parts or (int(parts[1]), int(parts[2])) < (2, 17):
        raise Refused(f"Docker Compose {version or 'is missing'}: AISC needs the Compose plugin 2.17 or later "
                      "(docker compose version).")
    branch = captured(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != BRANCH:
        raise Refused(f"this checkout is on '{branch or 'no branch'}', not {BRANCH}. Run: git checkout {BRANCH} && "
                      "git submodule update --init --recursive (or clone again: git -c core.autocrlf=false clone "
                      f"--recursive --branch {BRANCH} https://github.com/lux-ai-factory/aisc.git)")
    missing = sum(1 for l in captured(["git", "submodule", "status"]).stdout.splitlines() if l.startswith("-"))
    if missing:
        raise Refused(f"{missing} submodule(s) are not checked out. Run: git submodule update --init --recursive")
    free_gb = shutil.disk_usage(".").free // 2**30
    if free_gb < min_disk_gb:
        say(f"Warning: {free_gb} GB free here; the first build needs about {min_disk_gb} GB. It may fail with "
            "'no space left on device'.")

    # 2. The secrets
    make_secrets([])

    # 3. The ports, before anything is built: a taken one would otherwise surface only after the whole build
    config = captured([*COMPOSE, "config", "--format", "json"])
    if config.returncode != 0:
        raise Refused(f"compose cannot read its files: {config.stderr.strip()[-600:]}")
    kept = read_local()
    settings, problems = settle_ports(published_ports(json.loads(config.stdout)), held_by_aisc(), kept,
                                      not served_over_https() and not has_data(), port_is_free)
    if problems:
        raise Refused("AISC cannot start: " + " ".join(problems))
    existing = lines_of(LOCAL) if Path(LOCAL).is_file() else []
    if local_lines(existing, settings) != existing:
        write_beside(LOCAL, text_of(local_lines(existing, settings)))
        write_runtime()
    if settings["ENGINE_PORT"] != "80":
        why = "Port 80 is taken on this computer, so" if "ENGINE_PORT" not in kept else "On this install,"
        say(f"{why} steps 1 and 2 open on {settings['API_URL_EXTERNAL']}.")

    # 4. The images
    for attempt in (1, 2, 3):
        if attempt == 1:
            say("Building the images (the first time takes several minutes) ...")
            env = None
        else:
            say(f"The build failed; trying again ({attempt} of 3), fewer images at once ...")
            env = {**os.environ, "COMPOSE_BAKE": "false", "COMPOSE_PARALLEL_LIMIT": "2"}
        if subprocess.run([*COMPOSE, "build"], env=env).returncode == 0:
            break
    else:
        raise Refused("the build failed three times. The first error above says why: often the network (pip, uv or "
                      "npm timed out) or the disk. Fix it and run this again; what was built is kept.")

    # 5. Start, and wait for the sign-in page
    say("Starting the stack ...")
    if subprocess.run([*COMPOSE, "up", "-d"]).returncode != 0:
        raise Refused("the stack did not start: see the error above.")
    say(f"Waiting for the sign-in page at {url} (Keycloak needs about 30 seconds on a first start) ...")
    deadline = time.monotonic() + wait_s
    while True:
        code = answer_of(url)
        if code in (200, 302, 303):
            break
        if time.monotonic() >= deadline:
            warn(f"The sign-in page did not answer within {wait_s:g}s (last answer: {code or 'none'}). "
                 "Services not running:")
            warn(*not_running(captured([*COMPOSE, "ps", "-a", "--format", "{{.Service}}\t{{.Status}}"]).stdout))
            raise Refused(f"see why with: docker compose -p {PROJECT} logs <service>  (for example keycloak or oauth2-proxy)")
        time.sleep(poll_s)
    # The launcher redirects to the sign-in before Keycloak has imported its realm: a person who follows at once
    # gets no form. The realm's own page answers 200 only once it is there.
    realm = keycloak_realm_url()
    while (code := answer_of(realm)) != 200:
        if time.monotonic() >= deadline:
            warn(f"Keycloak's realm page {realm} did not answer 200 within {wait_s:g}s (last answer: "
                 f"{code or 'none'}), so the sign-in cannot be shown yet.")
            raise Refused(f"see why with: docker compose -p {PROJECT} logs keycloak")
        time.sleep(poll_s)

    # A one-shot service (plugin-publisher, report-grants, the migrations) that exited non-zero: nothing waits on
    # some of them, so `up -d` went through and the sign-in answers without them.
    for line in captured([*COMPOSE, "ps", "-a", "--format", "{{.Service}}\t{{.Status}}"]).stdout.splitlines():
        service, _, status = line.partition("\t")
        if re.match(r"Exited \([1-9]", status):
            say(f"Warning: {service} did not finish ({status}). See why with: docker compose -p {PROJECT} logs {service}")

    # 6. The local controls every project catalogue gets (local_controls/), read by the platform's own code
    found = captured([*COMPOSE, "exec", "-T", "platform", "python", "-m", "platform_service.catalogue"])
    if found.returncode == 0:
        controls = [l for l in found.stdout.splitlines() if l.strip()]
        say(f"{len(controls)} local controls go into every project catalogue (local_controls/):",
            *("  " + c for c in controls))
    else:
        say("Warning: the local controls could not be read; catalogues get the public entries only.",
            f"See why with: docker compose -p {PROJECT} logs platform")

    # the sign-in that works on this install: admin / admin only while the password still is admin (a new local
    # install); generated (https) or changed (rotate-infra-password) ones are this install's own
    if value_in("AISC_ADMIN_PASSWORD", OUT).strip("'\"") == "admin":
        sign_in = ["sign in as admin / admin (user / user is an ordinary account)."]
    else:
        sign_in = ["sign in as admin with this install's own password. Show it, and the ordinary account user's, with:",
                   "  uv run scripts/aisc.py password   (AISC_ADMIN_PASSWORD and AISC_USER_PASSWORD in env.secrets)"]
    say("",
        f"AISC is up: open {url.rstrip('/')} and {sign_in[0]}", *sign_in[1:],
        "If you installed AISC before on this machine, use a private window (an old session cookie is refused).")


COMMANDS = {"start": start, "secrets": make_secrets, "password": show_passwords,
            "rotate-infra-password": rotate_infra_password}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        warn(f"usage: uv run scripts/aisc.py {{{'|'.join(COMMANDS)}}} [options]  (see the top of scripts/aisc.py)")
        return 2
    os.chdir(ROOT)
    try:
        COMMANDS[argv[0]](argv[1:])
    except Refused as refused:
        warn(f"aisc.py {argv[0]}: {refused}" if argv[0] == "start" else str(refused))
        return refused.code
    except OSError as failed:
        warn(f"aisc.py {argv[0]}: {failed.strerror or failed} ({failed.filename or 'a file here'}); the files "
             "already there are as they were")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
