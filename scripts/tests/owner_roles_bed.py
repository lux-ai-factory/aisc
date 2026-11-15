"""A throwaway bed set up the way postgres-setup sets up a stack that has owner roles.

The same steps as isolation_bed.build, with the role files postgres-setup runs on every start added in
its order: init/platform-role.sql and init/owner-roles.sql in `platform`, then
init/project-database-setup.sql in `template1` (so every project database made afterwards has it) and,
after provisioning, in each project database. A file that is missing or fails is a bed problem, not an
error, so each test that needs it fails on what it checks.

    bed = build("owners")                       # platform, two projects, every module migrated
    bed = build("owners", owner_roles=False)    # the same without the owner roles (an old setup)

Passwords stay in memory: never printed, never in an assertion message.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import isolation_bed as ib
from throwaway import Throwaway, platform_migration

ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "init"

#: module schema -> its owner role, for every schema a module migrates.
OWNERS = {schema: f"{schema}_owner" for schema in ib.MODULES}
#: the platform's own schemas in a project database, all owned by platform_owner.
PLATFORM_SCHEMAS = ("project", "evidence", "trace", "ledger", "provision", "connection", "helper", "llm", "target")
#: the guard list postgres-setup loads (one `schema.table trigger` per line).
GUARD_LIST = INIT / "guard-triggers.txt"


def guards() -> list[tuple[str, str]]:
    if not GUARD_LIST.exists():
        return []
    out = []
    for line in GUARD_LIST.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            table, trigger = line.split()
            out.append((table, trigger))
    return out


def build(label: str, *, owner_roles: bool = True, modules: bool = True,
          projects: tuple[str, ...] = (ib.A, ib.B)) -> ib.IsoBed:
    t = Throwaway.start(f"iso-top-{label}")
    bed = ib.IsoBed(t)
    try:
        ib._su_file(bed, "postgres", INIT / "platform-db.sql", "init")
        files = ["project-databases", "platform-role", "inspector-role", "report-roles"]
        if owner_roles:
            files.append("owner-roles")
        for f in files:
            ib._su_file(bed, "platform", INIT / f"{f}.sql", f"init-{f}")
        if owner_roles:
            ib._su_file(bed, "template1", INIT / "project-database-setup.sql", "init-project-database-setup")
        for m in sorted((ROOT / "platform/migrations").glob("*.sql")):
            try:
                platform_migration(t, m)
            except subprocess.CalledProcessError as e:
                bed.problems["platform-migrations"] = f"{m.name}: " + ib._redact(bed, (e.stderr or "").strip()[-300:])
                break
        if projects:
            ib.provision(bed, list(projects))
            if owner_roles:
                for pid in projects:
                    ib._su_file(bed, ib.project_db(pid), INIT / "project-database-setup.sql",
                                "init-project-database-setup")
        if modules and projects:
            ib.migrate_modules(bed)
        return bed
    except BaseException:
        t.stop()
        raise


def as_role(bed: ib.IsoBed, db: str, role: str, sql: str) -> tuple[str, str]:
    """(stdout, stderr) of `sql` run as `role`, tuples only, unaligned."""
    r = subprocess.run(
        ["docker", "exec", "-i", "-e", f"PGPASSWORD={role}", bed.t.name, "psql", "-X", "-q", "-t", "-A",
         "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", role, "-d", db, "-f", "-"],
        input=sql, text=True, capture_output=True)
    return r.stdout.strip(), r.stderr.strip()


def as_su(bed: ib.IsoBed, db: str, sql: str) -> tuple[str, str]:
    """(stdout, stderr) of `sql` run as the superuser, tuples only; never raises."""
    r = subprocess.run(
        ["docker", "exec", "-i", "-e", f"PGPASSWORD={bed.t.password}", bed.t.name, "psql", "-X", "-q", "-t",
         "-A", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", ib.SU, "-d", db, "-f", "-"],
        input=sql, text=True, capture_output=True)
    return r.stdout.strip(), ib._redact(bed, r.stderr.strip())
