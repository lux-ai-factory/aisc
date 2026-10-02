"""The operator's pool of ledger databases (spec 7.1; spike M1-M7).

Only the immudb superuser can create databases and grant on them (M1-M5), and the platform never
holds it. So an operator runs `scripts/ledger-pool.sh`, which calls `create_databases` with the
superuser's password and `register` to list them in `ledger.pool`; projects then take them
(`provision.assign`).
"""
from __future__ import annotations

from platform_service.ledger.naming import is_ledger_name


def create_databases(url: str, *, admin_user: str = "immudb", admin_password: str, names: list[str],
                     grantee: str, grantee_password: str, login_database: str = "defaultdb") -> list[str]:
    """Create `names` in immudb and give `grantee` read-write on each, creating the user if needed.
    PermissionError when `admin_user` may not (anyone but the superuser, M1)."""
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
        users = {u.user.decode() if isinstance(u.user, bytes) else u.user for u in client.listUsers().userlist.users}
        if grantee not in users:
            client.createUser(grantee, grantee_password, constants.PERMISSION_RW, names[0])
        for name in names:
            client.changePermission(constants.PERMISSION_GRANT, grantee, name, constants.PERMISSION_RW)
    except Exception as exc:
        _refused(exc, admin_user)
        raise
    # An existing user keeps its own password: check the platform can log in with the one it holds,
    # or the pool would be unusable (found by the phase-1 drill).
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
    holds it only for this command: the platform service never has it.
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
    args = parser.parse_args(argv)

    missing = [n for n in ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_URL", "LEDGER_IMMUDB_PASSWORD",
                           "PLATFORM_DATABASE_URL") if not os.environ.get(n)]
    if missing:
        print(f"set {', '.join(missing)} first (the superuser's password only in this command's environment)",
              file=sys.stderr)
        return 2
    url = os.environ["LEDGER_IMMUDB_URL"]
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


if __name__ == "__main__":
    raise SystemExit(main())
