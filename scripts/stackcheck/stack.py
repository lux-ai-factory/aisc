"""The running stack as the checks reach it: psql inside its Postgres container, and Keycloak's token endpoint.

Secrets are read from the environment first, then from the repository's env.runtime, and are never printed or
put on a command line: docker gets `-e PGPASSWORD` (the name only, the value from its own environment) and psql
reads its SQL on stdin; a token request carries the password in its body.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .harness import Answer

ROOT = Path(__file__).resolve().parents[2]
#: how long one psql call may take: a probe answers in well under a second
PSQL_WAIT_S = 30
TOKEN_WAIT_S = 20
#: the variable holding each database role's generated password (scripts/aisc.py secrets, applied by postgres-setup)
PASSWORD_OF = {
    "platform_rw": "PLATFORM_RW_PASSWORD",
    "qualification_rw": "QUALIFICATION_RW_PASSWORD",
    "control_objectives_rw": "CONTROL_OBJECTIVES_RW_PASSWORD",
    "controls_rw": "CONTROLS_RW_PASSWORD",
    "engine_rw": "ENGINE_RW_PASSWORD",
    "dashboard_ro": "DASHBOARD_RO_PASSWORD",
    "report_composer_rw": "REPORT_COMPOSER_PASSWORD",
    "report_ro": "REPORT_RO_PASSWORD",
}


def value_in(name: str, path: Path) -> str:
    """NAME's last value in an env file, one pair of quotes taken off; empty when it has none."""
    value = ""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip().rstrip("\r")
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
    return value


class Stack:
    """env_file: the install's env.runtime; secrets_file: its env.secrets (AISC_INSTALL names the containers).
    container: the Postgres container (PGCONTAINER, else this install's); host: where psql connects inside it
    (PGHOST, else localhost). run: subprocess.run, replaced by a test."""

    def __init__(self, env_file: Path = ROOT / "env.runtime", secrets_file: Path = ROOT / "env.secrets",
                 container: str | None = None, host: str | None = None, keycloak_url: str | None = None,
                 run=subprocess.run):
        self.env_file = Path(env_file)
        install = value_in("AISC_INSTALL", Path(secrets_file))
        self.container = (container or os.environ.get("PGCONTAINER")
                          or (f"aisc-{install}-postgres" if install else "postgres"))
        self.host = host or os.environ.get("PGHOST") or "localhost"
        self.keycloak_url = (keycloak_url or os.environ.get("KEYCLOAK_URL")
                             or self.setting("KEYCLOAK_URL_EXTERNAL"))
        self.run = run

    def setting(self, name: str) -> str:
        """A setting or secret: the environment's value, else env.runtime's; empty when neither has one."""
        return os.environ.get(name) or value_in(name, self.env_file)

    def psql(self, role: str, db: str, sql: str, password: str | None = None, options: str = "") -> Answer:
        """sql run as role in db; ok when psql exits 0, its output (or error) in text. password: the role's,
        None for the one password_of() gives. options: PGOPTIONS for the session (such as -c settings)."""
        env = {**os.environ, "PGPASSWORD": password if password is not None else self.password_of(role),
               "PGOPTIONS": options}
        argv = ["docker", "exec", "-i", "-e", "PGPASSWORD", "-e", "PGOPTIONS", self.container,
                "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-h", self.host, "-U", role, "-d", db, "-f", "-"]
        try:
            done = self.run(argv, input=sql, env=env, capture_output=True, text=True, timeout=PSQL_WAIT_S)
        except subprocess.TimeoutExpired:
            return Answer(False, f"psql did not answer within {PSQL_WAIT_S}s")
        if done.returncode == 0:
            return Answer(True, done.stdout.strip())
        return Answer(False, (done.stderr or done.stdout).strip())

    def password_of(self, role: str) -> str:
        """The role's generated password (PASSWORD_OF), or its name: the development default before it had one."""
        variable = PASSWORD_OF.get(role)
        return (self.setting(variable) if variable else "") or role

    def token(self, user: str, password: str, client: str = "aisc-webapp") -> str:
        """An access token for an account of the realm aisc; empty when Keycloak gives none, or when this
        install's sign-in address is not known (start may have moved it off its default port)."""
        if not self.keycloak_url:
            return ""
        body = urllib.parse.urlencode({"client_id": client, "grant_type": "password", "username": user,
                                       "password": password}).encode()
        request = urllib.request.Request(f"{self.keycloak_url.rstrip('/')}/realms/aisc/protocol/openid-connect/token",
                                         data=body, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TOKEN_WAIT_S) as response:
                return json.load(response).get("access_token", "")
        except (OSError, ValueError):
            return ""
