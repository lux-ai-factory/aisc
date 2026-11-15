"""The guard triggers of every project database are there, enabled, and on tables their owner role holds.

A guard trigger (init/guard-triggers.txt) keeps a history from being rewritten: card versions, run traces,
measures, the ledger outbox. The event trigger aisc_guard_triggers_stay refuses disabling or dropping one, but
the superuser can drop the event trigger first; and a table handed back to a runtime role lets that role lift
its guards. So for every `project_<hex>` database this reports, one line each:

    missing: <db> <table> <trigger>          the table exists without the trigger
    disabled: <db> <table> <trigger>         the trigger is there but does not fire (tgenabled is not 'O')
    owner: <db> <table> is owned by <role>   the table is not its schema's owner role's

A module schema (qualification, controls, control_objectives, report_composer, engine) belongs to
<schema>_owner, every other schema to platform_owner. A listed table that does not exist (a module that has not
opened the project yet) is not reported.

    python3 -m stackcheck.guard_triggers    # from scripts/, with PGHOST, PGPORT, PGUSER, PGPASSWORD set

Read-only: catalogue queries only. The connection's password is never printed.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

GUARD_LIST = Path(__file__).resolve().parents[2] / "init" / "guard-triggers.txt"
PROJECT_DB = re.compile(r"^project_[0-9a-f]{32}$")
MODULE_SCHEMAS = ("qualification", "controls", "control_objectives", "report_composer", "engine")


def listed_guards(path: Path = GUARD_LIST) -> list[tuple[str, str]]:
    """The (schema.table, trigger) lines of the guard list."""
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            table, trigger = line.split()
            out.append((table, trigger))
    return out


def owner_role(schema: str) -> str:
    return f"{schema}_owner" if schema in MODULE_SCHEMAS else "platform_owner"


def _connect(dsn_template: str, database: str):
    import psycopg

    return psycopg.connect(dsn_template.format(database=database), autocommit=True,
                           options="-c default_transaction_read_only=on")


def project_databases(dsn_template: str) -> list[str]:
    with _connect(dsn_template, "postgres") as conn:
        names = [row[0] for row in conn.execute("SELECT datname FROM pg_database ORDER BY datname")]
    return [name for name in names if PROJECT_DB.match(name)]


def database_problems(conn, db: str, guards: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    owners_seen: set[str] = set()
    for table, trigger in guards:
        schema = table.split(".", 1)[0]
        row = conn.execute("SELECT pg_get_userbyid(c.relowner) FROM pg_class c WHERE c.oid = to_regclass(%s)",
                           (table,)).fetchone()
        if row is None:
            continue
        owner = row[0]
        if owner != owner_role(schema) and table not in owners_seen:
            owners_seen.add(table)
            found.append(f"owner: {db} {table} is owned by {owner}")
        state = conn.execute("SELECT tgenabled FROM pg_trigger WHERE tgrelid = to_regclass(%s) AND tgname = %s",
                             (table, trigger)).fetchone()
        if state is None:
            found.append(f"missing: {db} {table} {trigger}")
        elif state[0] != "O":
            found.append(f"disabled: {db} {table} {trigger}")
    return found


def problems(dsn_template: str, guards: list[tuple[str, str]]) -> list[str]:
    """Every problem of every project database on the cluster `dsn_template` (with `{database}`) reaches."""
    found: list[str] = []
    for db in project_databases(dsn_template):
        with _connect(dsn_template, db) as conn:
            found += database_problems(conn, db, guards)
    return found


def main() -> int:
    from psycopg.conninfo import make_conninfo

    base = make_conninfo(host=os.environ.get("PGHOST", "127.0.0.1"), port=os.environ.get("PGPORT", "5432"),
                         user=os.environ.get("PGUSER", ""), password=os.environ.get("PGPASSWORD", ""))
    template = base.replace("{", "{{").replace("}", "}}") + " dbname={database}"
    try:
        found = problems(template, listed_guards())
    except Exception as exc:  # noqa: BLE001 - the class names what failed; the message may hold the address
        print(f"  FAIL guard triggers: could not read the cluster ({type(exc).__name__})")
        return 1
    for line in found:
        print(f"  FAIL {line}")
    print(f"  {'PASS' if not found else 'FAIL'} guard triggers: {len(found)} problems")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
