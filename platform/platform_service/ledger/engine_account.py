"""The engine's own immudb account: aisc_engine, on auditdb.

The engine's audit clerk (apps/backend) logs in WITHOUT naming a database, so the account needs a
right on defaultdb (read) besides read-write on auditdb, granted in that order: a grant on one database wipes
the user's SQL privileges on every other. Its SQL privileges on auditdb are narrowed to SELECT, CREATE,
INSERT. Made by ledger-pool (`pool top-up`) as the superuser, before the engine starts (compose).
A grant or a password change ends the user's open sessions (the clerk logs in again on its next call):
so nothing is changed when the account is already right.

    python -m platform_service.ledger.engine_account check   # read only, as aisc_engine (verify-immudb.sh)
"""
from __future__ import annotations

ENGINE_USER = "aisc_engine"
ENGINE_DATABASE = "auditdb"
ENGINE_SQL_PRIVILEGES = frozenset({"SELECT", "CREATE", "INSERT"})

_REVOKED = ("UPDATE", "DELETE", "DROP", "ALTER")          # the four of immudb's seven the clerk never uses
_ABSENT = "aisc_check_absent"                             # a table that never exists: check's probes touch nothing


def _details(exc) -> str:
    return getattr(exc, "details", lambda: "")() or str(exc)


def _sql_grants(admin) -> set[str]:
    admin.useDatabase(ENGINE_DATABASE.encode())
    return {row[-1] for row in admin.sqlQuery(f"SHOW GRANTS FOR {ENGINE_USER}")}


def ensure(url: str, *, admin_password: str, password: str) -> str:
    """Make or repair the account; returns what it did: "made", "rights repaired", "password changed",
    "rights repaired, password changed" or "unchanged". Never deletes, revokes a database right or drops."""
    from immudb import ImmudbClient, constants
    from immudb.datatypesv2 import DatabaseSettingsV2

    from platform_service.ledger.pool import _permissions, _refused, ensure_password

    R, RW = constants.PERMISSION_R, constants.PERMISSION_RW
    admin = ImmudbClient(url)
    try:
        admin.login("immudb", admin_password, database=b"defaultdb")
        done = []
        listed = {d.decode() if isinstance(d, bytes) else d for d in admin.databaseList()}
        if ENGINE_DATABASE not in listed:
            admin.createDatabaseV2(ENGINE_DATABASE, DatabaseSettingsV2(), True)
            done.append("made")
        held = _permissions(admin, ENGINE_USER)
        user_made = held is None
        if user_made:
            admin.createUser(ENGINE_USER, password, R, "defaultdb")
            held = {"defaultdb": R}
            done.append("made")
        # A third database granted by hand is check's to report, not this to revoke: compare only these two.
        if held.get("defaultdb") != R or held.get(ENGINE_DATABASE) != RW or _sql_grants(admin) != ENGINE_SQL_PRIVILEGES:
            admin.changePermission(constants.PERMISSION_GRANT, ENGINE_USER, "defaultdb", R)
            admin.changePermission(constants.PERMISSION_GRANT, ENGINE_USER, ENGINE_DATABASE, RW)   # last: a grant wipes the others
            admin.useDatabase(ENGINE_DATABASE.encode())
            admin.sqlExec(f"REVOKE {', '.join(_REVOKED)} ON DATABASE {ENGINE_DATABASE} TO USER {ENGINE_USER};")
            if "made" not in done:
                done.append("rights repaired")
    except Exception as exc:
        _refused(exc, "immudb")
        raise
    # a user made just now has this password; one that existed may not (even when auditdb was just made)
    if not user_made and ensure_password(url, admin_password=admin_password, user=ENGINE_USER, password=password):
        done.append("password changed")
    # as the clerk logs in: no database, then auditdb
    try:
        c = ImmudbClient(url)
        c.login(ENGINE_USER, password)
        c.useDatabase(ENGINE_DATABASE.encode())
    except Exception as exc:
        raise RuntimeError(f"{ENGINE_USER} cannot reach {ENGINE_DATABASE} after it was set up: {_details(exc)}") from exc
    return "made" if "made" in done else ", ".join(done) or "unchanged"


def ensure_engine_account(url: str, *, admin_password: str, password: str) -> bool:
    """True when it changed something."""
    return ensure(url, admin_password=admin_password, password=password) != "unchanged"


def check_engine_account(url: str, *, password: str) -> list[str]:
    """What is wrong with the account, probed as aisc_engine itself (it may not run SHOW GRANTS); [] when
    it is as designed. Changes nothing: every probe names a table or database that is refused before it is
    looked up."""
    from immudb import ImmudbClient
    from immudb.datatypesv2 import DatabaseSettingsV2

    from platform_service.ledger.naming import PLATFORM_DB

    c = ImmudbClient(url)
    try:
        c.login(ENGINE_USER, password)                                  # as the clerk: no database
    except Exception as exc:
        if "invalid user name or password" in _details(exc).lower():
            return [f"{ENGINE_USER} does not log in with ENGINE_IMMUDB_PASSWORD (wrong password, or no such user)"]
        return [f"{ENGINE_USER} could not log in: {_details(exc)}"]
    problems = []
    listed = {d.decode() if isinstance(d, bytes) else d for d in c.databaseList()}
    if ENGINE_DATABASE not in listed:
        problems.append(f"{ENGINE_USER} has no right on {ENGINE_DATABASE}")
    if extra := sorted(listed - {"defaultdb", ENGINE_DATABASE}):
        problems.append(f"{ENGINE_USER} reaches other databases: {', '.join(extra)}")
    if ENGINE_DATABASE in listed:
        c.useDatabase(ENGINE_DATABASE.encode())
        for verb, stmt in (("DELETE", f"DELETE FROM {_ABSENT} WHERE id < 0"), ("DROP", f"DROP TABLE {_ABSENT}")):
            try:
                c.sqlExec(stmt)
                problems.append(f"{ENGINE_USER} may {verb} in {ENGINE_DATABASE}")
            except Exception as exc:
                if f"requires [{verb}]" not in _details(exc):
                    problems.append(f"{ENGINE_USER} may {verb} in {ENGINE_DATABASE} (immudb: {_details(exc)})")
    try:
        c.createDatabaseV2(ENGINE_DATABASE, DatabaseSettingsV2(), True)  # exists: a no-op even if it were allowed
        problems.append(f"{ENGINE_USER} may create databases")
    except Exception as exc:
        if "permission" not in _details(exc).lower():
            problems.append(f"{ENGINE_USER}: createDatabase answered {_details(exc)}")
    try:
        ImmudbClient(url).login(ENGINE_USER, password, database=PLATFORM_DB.encode())
        problems.append(f"{ENGINE_USER} logs in to the platform's ledger database {PLATFORM_DB}")
    except Exception:
        pass                                                            # refused (no right) or no such database
    return problems


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(prog="python -m platform_service.ledger.engine_account")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="as aisc_engine: it logs in as the clerk does, reaches defaultdb and auditdb "
                                 "only, and may not DELETE, DROP or create databases (read only)")
    parser.parse_args(argv)
    missing = [n for n in ("LEDGER_IMMUDB_URL", "ENGINE_IMMUDB_PASSWORD") if not os.environ.get(n)]
    if missing:
        print(f"set {', '.join(missing)} first", file=sys.stderr)
        return 2
    problems = check_engine_account(os.environ["LEDGER_IMMUDB_URL"], password=os.environ["ENGINE_IMMUDB_PASSWORD"])
    for p in problems:
        print(f"problem: {p}")
    if not problems:
        print(f"engine account {ENGINE_USER}: logs in as the clerk does, reaches defaultdb and {ENGINE_DATABASE} "
              "only, may not DELETE, DROP or create databases")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
