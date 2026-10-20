"""The operator's pool of ledger databases.

Only the immudb superuser can create databases and grant on them, and the platform never
holds it. So an operator runs `scripts/ledger-pool.sh`, which calls `create_databases` with the
superuser's password and `register` to list them in `ledger.pool`; projects then take them
(`provision.assign`). `top-up` (the ledger-pool service) also makes the engine's own account
(engine_account.py) and, after a rotation, gives aisc_ledger and aisc_engine their new passwords.
"""
from __future__ import annotations

from platform_service.ledger.naming import is_ledger_name


def create_databases(url: str, *, admin_user: str = "immudb", admin_password: str, names: list[str],
                     grantee: str, grantee_password: str, login_database: str = "defaultdb") -> list[str]:
    """Create `names` in immudb and give `grantee` read-write on each, creating the user if needed.
    PermissionError when `admin_user` may not (anyone but the superuser)."""
    from immudb import ImmudbClient, constants
    from immudb.datatypesv2 import DatabaseSettingsV2

    for name in names:
        if not is_ledger_name(name):
            raise ValueError(f"not a ledger name: {name!r}")
    client = ImmudbClient(url)
    try:
        client.login(admin_user, admin_password, database=login_database.encode())
        for name in names:
            client.createDatabaseV2(name, DatabaseSettingsV2(), True)
        # A grant, even one the user already has, ends every open session of that user: grant only
        # what is missing, so a re-run never cuts the running platform's sessions.
        held = _permissions(client, grantee)
        if held is None:
            client.createUser(grantee, grantee_password, constants.PERMISSION_RW, names[0])
            held = {names[0]: constants.PERMISSION_RW}
        for name in names:
            if held.get(name) != constants.PERMISSION_RW:
                client.changePermission(constants.PERMISSION_GRANT, grantee, name, constants.PERMISSION_RW)
    except Exception as exc:
        _refused(exc, admin_user)
        raise
    # An existing user keeps its own password: check the platform can log in with the one it holds,
    # or the pool would be unusable.
    try:
        ImmudbClient(url).login(grantee, grantee_password, database=names[0].encode())
    except Exception as exc:
        details = getattr(exc, "details", lambda: "")() or str(exc)
        if "invalid user name or password" in details.lower():
            raise PermissionError(f"{grantee} exists in immudb with another password than LEDGER_IMMUDB_PASSWORD: "
                                  "set the one immudb has, or change it there first") from exc
        raise RuntimeError(f"{grantee} could not log in to the new database {names[0]}: {details}") from exc
    return names


def _refused(exc: Exception, admin_user: str) -> None:
    text = (getattr(exc, "details", lambda: "")() or str(exc)).lower()
    code = getattr(getattr(exc, "code", lambda: None)(), "name", "")
    if "permission" in text or code == "PERMISSION_DENIED":
        raise PermissionError(f"{admin_user} may not create ledger databases: {text}") from exc


def _permissions(client, user: str) -> dict[str, int] | None:
    """{database: permission} of `user` as the superuser lists it, or None when there is no such user."""
    for u in client.listUsers().userlist.users:
        name = u.user.decode() if isinstance(u.user, bytes) else u.user
        if name == user:
            return {p.database: p.permission for p in u.permissions}
    return None


def ensure_password(url: str, *, admin_password: str, user: str, password: str) -> bool:
    """Give `user` this password when it does not log in with it; True when it changed it.

    Changed only when the login is refused for the password: a change ends the user's open sessions,
    so a password that works is left alone. A missing user is not made (False). The check logs in to a
    database the user has a right on: defaultdb (aisc_engine), else the platform's log (aisc_ledger has no
    right on defaultdb), else the first it has. Never prints or raises a password."""
    from immudb import ImmudbClient

    from platform_service.ledger.naming import PLATFORM_DB

    admin = ImmudbClient(url)
    try:
        admin.login("immudb", admin_password, database=b"defaultdb")
        held = _permissions(admin, user)
    except Exception as exc:
        _refused(exc, "immudb")
        raise
    if held is None:
        return False
    if not held:
        raise RuntimeError(f"{user} has no right on any database, so its password cannot be checked; nothing changed")
    db = "defaultdb" if "defaultdb" in held else PLATFORM_DB if PLATFORM_DB in held else sorted(held)[0]
    try:
        ImmudbClient(url).login(user, password, database=db.encode())
        return False
    except Exception as exc:
        details = getattr(exc, "details", lambda: "")() or str(exc)
        if "invalid user name or password" not in details.lower():
            raise RuntimeError(f"{user} could not log in to {db}: {details}") from exc
    admin.changePassword(user, password, "")
    return True


def register(store, names: list[str], dsn: str | None = None) -> None:
    """List `names` as free pool databases of `store`'s server (the platform's pool unless `dsn`)."""
    import psycopg

    for name in names:
        if not is_ledger_name(name):
            raise ValueError(f"not a ledger name: {name!r}")
    if dsn is None:
        from platform_service import db

        connection = db.pool().connection()
    else:
        connection = psycopg.connect(dsn)
    with connection as conn:
        for name in names:
            conn.execute("INSERT INTO ledger.pool (db, server_id) VALUES (%s, %s) ON CONFLICT (db) DO NOTHING",
                         (name, store.server_id))


def main(argv: list[str] | None = None) -> int:
    """`python -m platform_service.ledger.pool create N`: the operator's step (scripts/ledger-pool.sh).

    Reads IMMUDB_ADMIN_PASSWORD (the superuser's) from its own environment only, never prints it, and
    holds it only for this command: the platform service never has it. `top-up` also makes the engine's
    account (engine_account) and brings aisc_ledger's and aisc_engine's passwords to the configured ones.
    """
    import argparse
    import os
    import sys

    from platform_service.ledger import settings
    from platform_service.ledger.naming import PLATFORM_DB, pool_name
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    parser = argparse.ArgumentParser(prog="python -m platform_service.ledger.pool")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="make N pool databases and list them in ledger.pool")
    create.add_argument("count", type=int, nargs="?", default=settings.LEDGER_POOL)
    top_up = sub.add_parser("top-up", help="make what is missing for N free databases, and give each project"
                                           " waiting for one its database (the ledger-pool service, at start)")
    top_up.add_argument("count", type=int, nargs="?", default=settings.LEDGER_POOL)
    top_up.add_argument("--wait", type=int, default=0, help="seconds to wait for immudb and the platform's"
                                                            " migrated database (a stack's first start)")
    args = parser.parse_args(argv)

    needed = ["IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_URL", "LEDGER_IMMUDB_PASSWORD", "PLATFORM_DATABASE_URL"]
    if args.command == "top-up":
        needed.append("ENGINE_IMMUDB_PASSWORD")     # the engine's own account, made here too
    missing = [n for n in needed if not os.environ.get(n)]
    if missing:
        print(f"set {', '.join(missing)} first (the superuser's password only in this command's environment)",
              file=sys.stderr)
        return 2
    url = os.environ["LEDGER_IMMUDB_URL"]
    if args.command == "top-up":
        return _top_up(url, args.count, args.wait)
    names = [pool_name() for _ in range(args.count)]
    try:
        create_databases(url, admin_password=os.environ["IMMUDB_ADMIN_PASSWORD"], names=names + [PLATFORM_DB],
                         grantee="aisc_ledger", grantee_password=os.environ["LEDGER_IMMUDB_PASSWORD"])
    except PermissionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    store = ImmudbLedger(url, user="aisc_ledger", password=os.environ["LEDGER_IMMUDB_PASSWORD"],
                         state_store=MemoryStateStore())
    register(store, names, dsn=os.environ["PLATFORM_DATABASE_URL"])
    print(f"made {len(names)} ledger databases on {store.server_id} and listed them in ledger.pool")
    return 0


def _immudb_ready(url: str, admin: str) -> str | None:
    """Why the top-up can't start yet, or None: immudb must answer the superuser."""
    from immudb import ImmudbClient

    try:
        ImmudbClient(url).login("immudb", admin, database=b"defaultdb")
    except Exception as exc:                                            # noqa: BLE001
        return f"immudb at {url} ({type(exc).__name__})"
    return None


def _platform_ready(dsn: str) -> str | None:
    """Why the pool can't be topped up yet, or None: the platform must have migrated ledger.pool."""
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            if not conn.execute("SELECT to_regclass('ledger.pool') IS NOT NULL").fetchone()[0]:
                return "the platform's migrations (ledger.pool)"
    except psycopg.Error as exc:
        return f"the platform database ({type(exc).__name__})"
    return None


def _top_up(url: str, level: int, wait: int = 0) -> int:
    """Bring the pool up to `level` free databases on this immudb server, then give every project that has
    none (made while the pool was empty) its database. Safe to run again: with the pool full it makes
    nothing. The superuser's password is only in this command's environment, as for `create`.

    First the engine's account and the two users' passwords (as the superuser, before it waits for the
    platform, so the engine never waits on the platform's migrations)."""
    import os
    import sys

    import psycopg

    from platform_service import ledger
    from platform_service.ledger import provision
    from platform_service.ledger.naming import PLATFORM_DB, pool_name
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    import time

    from platform_service.ledger import engine_account

    admin, user_password, engine_password, dsn = (
        os.environ["IMMUDB_ADMIN_PASSWORD"], os.environ["LEDGER_IMMUDB_PASSWORD"],
        os.environ["ENGINE_IMMUDB_PASSWORD"], os.environ["PLATFORM_DATABASE_URL"])
    deadline = time.monotonic() + wait

    def waited(check) -> str | None:
        """None once `check` passes; its last reason when `wait` seconds are spent."""
        while (reason := check()) is not None:
            if time.monotonic() >= deadline:
                return reason
            time.sleep(1)
        return None

    if (missing := waited(lambda: _immudb_ready(url, admin))) is not None:
        print(f"waited {wait} s and still not ready: {missing}", file=sys.stderr)
        return 3
    try:
        # before create_databases, whose own login check would refuse a rotated password
        ledger_changed = ensure_password(url, admin_password=admin, user="aisc_ledger", password=user_password)
        engine_done = engine_account.ensure(url, admin_password=admin, password=engine_password)
    except PermissionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"ledger user aisc_ledger: password {'changed' if ledger_changed else 'unchanged'}")
    note = " (restart aisc-backend: its open session was closed)" if "rights repaired" in engine_done else ""
    print(f"engine account {engine_account.ENGINE_USER} on {engine_account.ENGINE_DATABASE}: {engine_done}{note}")
    if (missing := waited(lambda: _platform_ready(dsn))) is not None:
        print(f"waited {wait} s and still not ready: {missing}", file=sys.stderr)
        return 3
    try:
        # the platform's own log and the ledger user first: the store's identity needs both
        create_databases(url, admin_password=admin, names=[PLATFORM_DB], grantee="aisc_ledger",
                         grantee_password=user_password)
    except PermissionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    store = ImmudbLedger(url, user="aisc_ledger", password=user_password, state_store=MemoryStateStore())
    with psycopg.connect(dsn) as conn:
        free = conn.execute("SELECT count(*) FROM ledger.pool WHERE assigned_pid IS NULL AND server_id = %s",
                            (store.server_id,)).fetchone()[0]
        waiting = [str(r[0]) for r in conn.execute(
            "SELECT p.pid FROM core.project p LEFT JOIN ledger.pool l ON l.assigned_pid = p.pid"
            " WHERE l.db IS NULL ORDER BY p.created_at")]
    names = [pool_name() for _ in range(max(0, level + len(waiting) - free))]
    if names:
        create_databases(url, admin_password=admin, names=names, grantee="aisc_ledger",
                         grantee_password=user_password)
        register(store, names, dsn=dsn)
    previous = ledger.use(store)
    try:
        given = sum(1 for pid in waiting if provision.assign(pid))
    finally:
        ledger.use(previous)
    print(f"made {len(names)} ledger databases on {store.server_id}; gave {given} waiting projects their database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
