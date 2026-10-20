"""A throwaway immudb 1.11.1 of a test's own, for the tests that need an EMPTY server or change its users
(the engine's account, the rotation of immudb's passwords). The shared throwaway immudb of the ledger
tests (LEDGER_TEST_IMMUDB_URL) is left alone: its aisc_ledger must keep the password the other tests use.

Each box is a container `aisc-t-immu-<hex>` on a free loopback port (never 3322), with a data volume of
the same name, so `recreate()` can restart immudb with another environment on the same data, as compose
does when IMMUDB_ADMIN_PASSWORD changes. Both are removed by `close()`. Passwords are generated here and
never printed. Nothing here touches the running stack.
"""
from __future__ import annotations

import secrets
import shutil
import socket
import subprocess
import time

IMAGE = "codenotary/immudb:1.11.1"


def password() -> str:
    """A password immudb accepts (upper, lower, digit, symbol, at most 32): secrets.sh's shape."""
    return "Az9-" + secrets.token_hex(12)


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0


def _free_port() -> int:
    while True:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port != 3322:
            return port


class ImmudbBox:
    def __init__(self, admin_password: str | None = None):
        self.name = "aisc-t-immu-" + secrets.token_hex(4)
        self.volume = self.name
        self.port = _free_port()
        self.url = f"127.0.0.1:{self.port}"
        self.admin_password = admin_password or password()
        self._run(force=True)

    def _run(self, force: bool) -> None:
        cmd = ["docker", "run", "-d", "--name", self.name, "-v", f"{self.volume}:/var/lib/immudb",
               "-p", f"127.0.0.1:{self.port}:3322", "-e", "IMMUDB_ADMIN_PASSWORD"]
        if force:
            cmd += ["-e", "IMMUDB_FORCE_ADMIN_PASSWORD=true"]
        env = {"PATH": __import__("os").environ["PATH"], "IMMUDB_ADMIN_PASSWORD": self.admin_password}
        r = subprocess.run(cmd + [IMAGE], capture_output=True, text=True, env=env, timeout=120)
        assert r.returncode == 0, f"could not start {self.name}: {r.stderr[-500:]}"
        self._wait()

    def _wait(self) -> None:
        from immudb import ImmudbClient

        deadline = time.monotonic() + 60
        while True:
            try:
                ImmudbClient(self.url).login("immudb", self.admin_password)
                return
            except Exception:                                           # noqa: BLE001
                if time.monotonic() > deadline:
                    raise AssertionError(f"{self.name} did not accept its superuser within 60 s")
                time.sleep(0.5)

    def recreate(self, admin_password: str) -> None:
        """Remove the container and start a new one on the same volume with this superuser password and
        IMMUDB_FORCE_ADMIN_PASSWORD=true (compose recreating immudb after env.secrets changed)."""
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=60)
        self.admin_password = admin_password
        self._run(force=True)

    def admin(self):
        from immudb import ImmudbClient

        c = ImmudbClient(self.url)
        c.login("immudb", self.admin_password)
        return c

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=60)
        subprocess.run(["docker", "volume", "rm", "-f", self.volume], capture_output=True, timeout=60)


def logs_in(url: str, user: str, pw: str, database: str | None = None) -> bool:
    """Whether `user` logs in; with no database exactly as the engine's clerk does (defaultdb)."""
    from immudb import ImmudbClient

    try:
        c = ImmudbClient(url)
        if database is None:
            c.login(user, pw)
        else:
            c.login(user, pw, database=database.encode())
        return True
    except Exception as exc:                                            # noqa: BLE001
        details = (getattr(exc, "details", lambda: "")() or str(exc)).lower()
        if "invalid user name or password" in details or "permission" in details:
            return False
        raise


def permissions(admin_client, user: str) -> dict[str, int] | None:
    """{database: permission} of `user` as the superuser lists it, or None when there is no such user."""
    for u in admin_client.listUsers().userlist.users:
        name = u.user.decode() if isinstance(u.user, bytes) else u.user
        if name == user:
            return {p.database: p.permission for p in u.permissions}
    return None


def sql_grants(admin_client, user: str, database: str = "auditdb") -> set[str]:
    """`user`'s SQL privileges on `database` (SHOW GRANTS FOR, run by the superuser)."""
    admin_client.useDatabase(database.encode())
    return {row[-1] for row in admin_client.sqlQuery(f"SHOW GRANTS FOR {user}")}


def databases(admin_client) -> set[str]:
    return {d.decode() if isinstance(d, bytes) else d for d in admin_client.databaseList()}
