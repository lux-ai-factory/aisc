"""rotate-infra-password: a new value for a password the infrastructure keeps in its own volume, set in the
service first and only then written to env.secrets and env.runtime."""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .docker import find_docker, run_program
from .keycloak import kcadm, keycloak_container, stack_container
from .secrets import make_secrets, rand
from .settings import (NO_DOCKER, OUT, Refused, effective, lines_of, project, say, text_of, up_hint, value_in,
                       with_value, write_beside)


# ------------------------------------------------------------------------------- an infrastructure password

ROTATABLE = ("POSTGRES_PASSWORD", "RABBITMQ_PASSWORD", "S3_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
             "AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD")


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
    were. The value goes to the container by name (docker exec -e NAME) or on stdin, never on the host's command
    line, and is never printed; Keycloak's kcadm gets it on stdin, so it is on no command line in its container
    either. A chosen password has at least 12 characters and none of: space, quotes, $, # or backslash, which the
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
    # found once, on this process's PATH, before anything is asked or changed
    docker_command = find_docker()
    if docker_command is None:
        raise Refused(NO_DOCKER)
    new = chosen_value(name) if mode == "--ask" else rand()
    env = {**os.environ, "OLD_VALUE": old, "NEW_VALUE": new}

    def docker(*argv: str, stdin: str | None = None):
        r = run_program([docker_command, *argv], env=env, input=stdin if stdin is not None else "",
                           text=True, stdout=subprocess.DEVNULL)
        if r.returncode != 0:
            raise Refused(f"the service did not take the new {name}; nothing changed", r.returncode)

    def keycloak_set(admin: str, realm: str, account: str) -> None:
        """The account's id first, then its new password through reset-password, as JSON on kcadm's stdin."""
        container = keycloak_container(docker_command)
        if not container:
            raise Refused(f"Keycloak is not running in this install (docker compose -p {project()} ps keycloak); "
                          "nothing changed")
        found = kcadm(docker_command, container, admin, "get", "users", "-r", realm, "-q", f"username={account}")
        try:
            # the lookup matches names that contain the one asked for: only the account itself counts
            ids = [u["id"] for u in json.loads(found.stdout) if u.get("username") == account]
        except (ValueError, TypeError, KeyError, AttributeError):
            ids = []
        if found.returncode != 0 or len(ids) != 1:
            raise Refused(f"the service did not take the new {name}; nothing changed", found.returncode or 1)
        done = kcadm(docker_command, container, admin, "update", f"users/{ids[0]}/reset-password", "-r", realm,
                     "-f", "-", stdin=json.dumps({"type": "password", "value": new, "temporary": False}))
        if done.returncode != 0:
            raise Refused(f"the service did not take the new {name}; nothing changed", done.returncode)

    def running(service: str) -> str:
        """This stack's own container of the service; never the bare name, which may be another install's."""
        container = stack_container(docker_command, service)
        if not container:
            raise Refused(f"{service} is not running in this install (docker compose -p {project()} ps {service}); "
                          "nothing changed")
        return container

    if name == "POSTGRES_PASSWORD":
        docker("exec", "-i", "-e", "NEW_VALUE", running("postgres"), "sh", "-c",
               'exec psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d postgres', stdin=PSQL)
    elif name == "RABBITMQ_PASSWORD":
        docker("exec", "-e", "NEW_VALUE", running("rabbitmq"), "sh", "-c",
               'rabbitmqctl --quiet change_password "$RABBITMQ_DEFAULT_USER" "$NEW_VALUE"')
    elif name == "KEYCLOAK_ADMIN_PASSWORD":
        # the console admin's name, as compose gives it to Keycloak (KC_BOOTSTRAP_ADMIN_USERNAME)
        keycloak_set(old, "master", effective("KEYCLOAK_ADMIN") or "admin")
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
    say(f"{name} has a new value in the service, {OUT} and env.runtime. Recreate what reads it:", up_hint())
