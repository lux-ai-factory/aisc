"""The database access contract, as each role sees it: the read-only part of scripts/verify-db-access.sh.

Every module reads the list of projects and their members and cannot change them; the dashboard's reader writes
nothing in platform; nobody creates objects in public; only the platform service may create databases. Each
denial runs after a control that proves the role signs in and the object is there, inside a transaction that
is rolled back, so a grant that wrongly lets it through still changes nothing. The checks that make a project
and a project database stay in the bash script until this group has been proven on a live stack.
"""

from __future__ import annotations

from .harness import Answer, Check, Result, allow, deny
from .stack import Stack

DB = "platform"
MODULES = ("qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw", "report_composer_rw")
#: the readers default to read-only sessions (init/report-roles.sql): the probe turns that off for its session,
#: so only a refusal for a privilege shows they cannot write
WRITABLE_SESSION = "-c default_transaction_read_only=off"


def checks(stack: Stack) -> list[Check]:
    def read(role: str, sql: str):
        return lambda: stack.psql(role, DB, sql)

    def rolled_back(role: str, sql: str):
        return lambda: stack.psql(role, DB, f"begin;\n{sql};\nrollback;", options=WRITABLE_SESSION)

    def there(role: str, relation: str):
        """The control of a denial on a relation: the role signs in and sees that it exists."""
        def control() -> Answer:
            got = stack.psql(role, DB, f"select to_regclass('{relation}') is not null")
            return Answer(got.ok and got.text == "t", got.text if not got.ok else f"{relation} does not exist")
        return control

    def creates_databases(role: str, expected: str):
        """Whether the role may create databases, read from the catalogue (CREATE DATABASE cannot be rolled back)."""
        def run() -> Result:
            got = stack.psql(role, DB, "select rolcreatedb or rolsuper from pg_roles where rolname = current_user")
            if not got.ok:
                return Result(False, f"could not read its own role: {got.text}")
            if got.text != expected:
                return Result(False, f"rolcreatedb or rolsuper is {got.text}, not {expected}")
            return Result(True)
        return run

    found: list[Check] = []
    for role in MODULES:
        found += [
            Check(f"{role}: reads core.project", lambda r=role: allow(read(r, "select count(*) from core.project"))),
            Check(f"{role}: reads core.project_member",
                  lambda r=role: allow(read(r, "select count(*) from core.project_member"))),
            Check(f"{role}: cannot write core.project",
                  lambda r=role: deny(rolled_back(r, f"insert into core.project (name, slug) values ('x', 'x-{r}')"),
                                      control=there(r, "core.project"))),
            Check(f"{role}: cannot remove members",
                  lambda r=role: deny(rolled_back(r, "delete from core.project_member"),
                                      control=there(r, "core.project_member"))),
        ]
    found += [
        Check("dashboard_ro: cannot write core",
              lambda: deny(rolled_back("dashboard_ro", "insert into core.project (name, slug) values ('x', 'y')"),
                           control=there("dashboard_ro", "core.project"))),
        Check("dashboard_ro: cannot create tables in platform",
              lambda: deny(rolled_back("dashboard_ro", "create table core.sneaky (x int)"),
                           control=there("dashboard_ro", "core.project"))),
    ]
    for role in ("qualification_rw", "engine_rw", "dashboard_ro", "platform_rw"):
        found.append(Check(f"{role}: cannot create in public",
                           lambda r=role: deny(rolled_back(r, "create table public.sneaky (x int)"),
                                               control=there(r, "core.project"))))
    found += [
        Check("platform_rw: can create a database", creates_databases("platform_rw", "t")),
        Check("controls_rw: a module cannot create a database", creates_databases("controls_rw", "f")),
        Check("engine_rw: nor can the engine", creates_databases("engine_rw", "f")),
    ]
    return found
