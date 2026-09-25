"""python -m platform_service.isolate: the command line and the run of each subcommand.

The interface is pinned by platform/tests/test_isolate.py (its docstring); the rules by
01-specs.md section 12 and 03-coding-plan.md WP P2.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import psycopg
from psycopg import IsolationLevel
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from platform_service.projects import PID

from . import copy as C
from . import preconditions as P
from . import report as REP
from . import rowtext as R
from .catalog import (BOOKKEEPING, LIBRARY, LIBRARY_ONLY, Classification, classify, moving,
                      read_tables, source_tables, target_of)
from .ownership import Placement, load_keys, place

log = logging.getLogger("platform_service.isolate")
SUBCOMMANDS = ("plan", "provision", "copy", "verify", "verify-dump", "report")


class Usage(Exception):
    pass


def parse(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m platform_service.isolate",
                                 description="Move each project's rows into its own database.")
    ap.add_argument("subcommand", choices=SUBCOMMANDS)
    ap.add_argument("dumps", nargs="*", help="verify-dump: the dump files")
    ap.add_argument("--project", action="append", default=[], metavar="PID")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", metavar="PATH")
    a = ap.parse_intermixed_args(argv)
    if a.dumps and a.subcommand != "verify-dump":
        raise Usage(f"{a.subcommand} takes no positional arguments")
    if a.subcommand == "verify-dump" and not a.dumps:
        raise Usage("verify-dump needs the dump files")
    if a.dry_run and a.subcommand != "copy":
        raise Usage("--dry-run is for copy only")
    if bool(a.project) == bool(a.all):
        raise Usage("give --project PID (repeatable) or --all")
    for p in a.project:
        if not PID.fullmatch(p or ""):
            raise Usage("not a project id")
    a.project = sorted({p.lower() for p in a.project})
    return a


def _connect(dsn: str, *, read_only: bool = False, snapshot: bool = False) -> psycopg.Connection:
    # prepare_threshold=None: no server-side prepared statements, so psycopg never sends
    # DEALLOCATE ALL after a ROLLBACK (a statement outside the read-only transaction)
    conn = psycopg.connect(dsn, autocommit=False, prepare_threshold=None)
    if snapshot:
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
    if read_only:
        conn.read_only = True
    return conn


def _close(conn) -> None:
    """Never commit on the way out: every read ends in ROLLBACK."""
    try:
        if not conn.closed:
            conn.rollback()
    finally:
        conn.close()


class Run:
    def __init__(self, args, su_dsn: str, source_dsn: str | None = None):
        self.a = args
        self.su = su_dsn                  # superuser; its database is `platform` (the library lives there)
        self.source_dsn = source_dsn or su_dsn
        self.rep = REP.new(args.subcommand, bool(args.dry_run))
        self.refusals = self.rep["refusals"]

    # ── common part: snapshot, catalog, classification, placement ──────────
    def open_source(self) -> None:
        self.src = _connect(self.source_dsn, read_only=True, snapshot=True)
        self.src.execute("SELECT 1")
        R.apply_settings(self.src, local=True)
        self.rep["snapshot_time"] = self.src.execute(
            "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')").fetchone()[0]
        self.cache = C.SourceCache(self.src)
        self.tables = source_tables(self.src)
        self.cls: Classification = classify(self.tables)
        self.rep["classification"] = dict(sorted(self.cls.labels.items()))
        for t, detail in self.cls.unclassified.items():
            self.refusals.append(P.refusal("unclassified table", table=t, detail=detail))
        self.placeable = self.cls.root | self.cls.owned | self.cls.needed
        graph = load_keys(self.src, self.tables, self.placeable)
        self.graph = graph
        self.projects = graph.projects
        if self.a.all:
            self.selected = list(self.projects)
        else:
            self.selected = []
            for p in self.a.project:
                if p in self.projects:
                    self.selected.append(p)
                else:
                    self.refusals.append(P.refusal("unknown project", project=p, detail="not in core.project"))
        self.placement: Placement = place(graph, self.tables, self.cls)
        self.refusals.extend(self.placement.conflicts)
        self.rep["unowned"] = list(self.placement.unowned)
        self.databases = {r[0] for r in self.src.execute("SELECT datname FROM pg_database").fetchall()}
        self.source_db = self.src.execute("SELECT current_database()").fetchone()[0]
        self.forms = P.source_has_forms(self.src)
        self.templates = sorted(p.name for p in projectdb.TEMPLATE.glob("*.sql"))

    def target_dsn(self, pid: str) -> str:
        return make_conninfo(self.su, dbname=projectdb.database_name(pid))

    def project_maps(self, pid: str, ttables) -> tuple[list[C.Map], list[dict]]:
        maps, refusals = [], []
        for name in sorted(self.placeable):
            src = self.tables[name]
            tgt = ttables.get(target_of(name))
            refusals += P.column_coverage(src, tgt, target_of(name), pid)
            if tgt is not None:
                maps.append(C.Map(src, tgt, set(self.placement.copied[pid].get(name, set()))))
        return maps, refusals

    def library_maps(self, ltables) -> tuple[list[C.Map], list[dict]]:
        maps, refusals = [], []
        for name, lib in sorted(LIBRARY.items()):
            src = self.tables.get(name)
            if src is None:
                continue  # S-D3: the forms tables may be absent
            tgt = ltables.get(lib)
            refusals += P.column_coverage(src, tgt, lib, None)
            if tgt is not None:
                maps.append(C.Map(src, tgt, set(self.graph.keys[name]) if name in self.graph.keys
                                  else set(R.key_md5s(self.src, name, src.pk, src.pk))))
        return maps, refusals

    def project_entry(self, pid: str) -> dict:
        return self.rep["projects"].setdefault(pid, {
            "database": projectdb.database_name(pid), "status": None, "tables": {}, "sequences": {}})

    def fill(self, entry: dict, maps: list[C.Map], out: C.Outcome) -> None:
        entry["status"] = out.status
        entry["tables"] = {m.name: out.tables[m.name].report(m.target.name) for m in maps if m.name in out.tables}
        entry["sequences"] = {n: {"last_value": v[1], "is_called": v[2]} for n, v in sorted(out.sequences.items())}

    def library_dsn(self) -> str:
        return self.su

    # ── plan and copy ────────────────────────────────────────────────────────
    def check_targets(self, *, need_databases: bool) -> dict[str, tuple[list[C.Map], C.Outcome]]:
        """Read-only pass over every selected target: heads, templates, coverage, and what a copy
        would do (I12.6, I12.8). Nothing is committed anywhere."""
        plans = {}
        for pid in self.selected:
            entry = self.project_entry(pid)
            if projectdb.database_name(pid) not in self.databases:
                entry["status"] = "missing database"
                if need_databases:
                    self.refusals.append(P.refusal("missing database", project=pid))
                else:
                    for name in sorted(self.placeable):
                        for k in sorted(self.placement.copied[pid].get(name, ())):
                            self.rep["unowned"].append({"table": name, "key": self.tables[name].key_json(k),
                                                        "reason": "project database missing"})
                continue
            tgt = _connect(self.target_dsn(pid), read_only=True)
            try:
                ttables = C.target_tables(tgt)
                bad = P.new_heads(tgt, pid, self.forms, self.templates)
                maps, cov = self.project_maps(pid, ttables)
                bad += cov
                if bad:
                    entry["status"] = "failed"
                    self.refusals.extend(bad)
                    continue
                out = C.plan(self.cache, tgt, maps, {"project": pid})
                self.fill(entry, maps, out)
                entry["status"] = "planned"
                if out.refusals:
                    entry["status"] = "failed"
                    self.refusals.extend(out.refusals)
                plans[pid] = (maps, out)
            finally:
                _close(tgt)
        return plans

    def check_library(self) -> list[C.Map] | None:
        lib = _connect(self.library_dsn(), read_only=True)
        try:
            ltables = read_tables(lib, sorted({v.split(".")[0] for v in LIBRARY.values()}))
            maps, bad = self.library_maps(ltables)
            if bad:
                self.refusals.extend(bad)
                self.rep["library"] = {"status": "failed", "tables": {}}
                return None
            out = C.plan(self.cache, lib, maps, {})
            self.rep["library"] = {"status": "planned",
                                   "tables": {m.name: out.tables[m.name].report(m.target.name) for m in maps}}
            if out.refusals:
                self.rep["library"]["status"] = "failed"
                self.refusals.extend(out.refusals)
            return maps
        finally:
            _close(lib)

    def check_sessions(self) -> None:
        dbs = [self.source_db, self.su_database()] + [
            projectdb.database_name(p) for p in self.selected if projectdb.database_name(p) in self.databases]
        own = [self.src.info.backend_pid]
        self.refusals.extend(P.active_sessions(self.src, sorted(set(dbs)), own))

    def su_database(self) -> str:
        from psycopg.conninfo import conninfo_to_dict
        return str(conninfo_to_dict(self.su).get("dbname") or self.source_db)

    def plan_or_copy(self) -> int:
        copying = self.a.subcommand == "copy" and not self.a.dry_run
        self.open_source()
        self.refusals.extend(P.old_heads(self.src))
        plans = self.check_targets(need_databases=self.a.subcommand == "copy")
        lib_maps = self.check_library()
        self.check_sessions()
        if self.refusals or not copying:
            return 1 if self.refusals else 0
        for pid in self.selected:  # pid order; stop at the first failed project (G8, D15)
            maps, _ = plans[pid]
            entry = self.project_entry(pid)
            tgt = _connect(self.target_dsn(pid))
            try:
                out = C.write(self.cache, tgt, maps, {"project": pid})
                if out.status == "copied":
                    tgt.commit()
                else:
                    tgt.rollback()
                self.fill(entry, maps, out)
                log.info("project %s: %s", pid, out.status)
            except C.Abort as e:
                tgt.rollback()
                entry["status"] = "failed"
                self.refusals.extend(e.refusals)
                log.error("project %s: failed (%s); stopping, later projects are not attempted", pid, e)
                return 1
            except Exception as e:  # noqa: BLE001 - any failure rolls that project back
                tgt.rollback()
                entry["status"] = "failed"
                entry["error"] = REP.describe(e, self.su)
                log.error("project %s: failed (%s); stopping, later projects are not attempted",
                          pid, entry["error"])
                return 1
            finally:
                _close(tgt)
        if lib_maps is not None:
            lib = _connect(self.library_dsn())
            try:
                out = C.write(self.cache, lib, lib_maps, {})
                lib.commit() if out.status == "copied" else lib.rollback()
                self.rep["library"] = {"status": out.status, "tables": {
                    m.name: out.tables[m.name].report(m.target.name) for m in lib_maps}}
                log.info("library: %s", out.status)
            except C.Abort as e:
                lib.rollback()
                self.rep["library"]["status"] = "failed"
                self.refusals.extend(e.refusals)
                return 1
            except Exception as e:  # noqa: BLE001
                lib.rollback()
                self.rep["library"] = {"status": "failed", "error": REP.describe(e, self.su), "tables": {}}
                log.error("library: failed (%s)", self.rep["library"]["error"])
                return 1
            finally:
                _close(lib)
        return 0

    # ── verify, report ───────────────────────────────────────────────────────
    def verify(self, *, failing: bool = True) -> int:
        self.open_source()
        verified: dict[str, set] = {}
        diffs: list[dict] = []
        for pid in self.selected:
            entry = self.project_entry(pid)
            if projectdb.database_name(pid) not in self.databases:
                entry["status"] = "missing database"
                diffs.append(P.refusal("missing database", project=pid))
                continue
            tgt = _connect(self.target_dsn(pid), read_only=True)
            try:
                maps, cov = self.project_maps(pid, C.target_tables(tgt))
                if cov:
                    entry["status"] = "failed"
                    diffs.extend(cov)
                    continue
                out = C.verify(self.cache, tgt, maps, {"project": pid})
                self.fill(entry, maps, out)
                diffs.extend(out.refusals)
                for m in maps:
                    verified.setdefault(m.name, set()).update(out.tables[m.name].verified_keys)
            finally:
                _close(tgt)
        lib = _connect(self.library_dsn(), read_only=True)
        try:
            ltables = read_tables(lib, sorted({v.split(".")[0] for v in LIBRARY.values()}))
            maps, cov = self.library_maps(ltables)
            if cov:
                diffs.extend(cov)
                self.rep["library"] = {"status": "failed", "tables": {}}
            else:
                out = C.verify(self.cache, lib, maps, {})
                self.rep["library"] = {"status": out.status, "tables": {
                    m.name: out.tables[m.name].report(m.target.name) for m in maps}}
                diffs.extend(out.refusals)
                for m in maps:
                    verified.setdefault(m.name, set()).update(out.tables[m.name].verified_keys)
        finally:
            _close(lib)
        if self.a.all:
            diffs.extend(self.coverage(verified))
        if failing:
            self.refusals.extend(diffs)
        else:
            self.rep["differences"] = diffs
            for p in self.rep["projects"].values():
                if p["status"] == "failed":
                    p["status"] = "differs"
        return 1 if self.refusals else 0

    def coverage(self, verified: dict[str, set]) -> list[dict]:
        """I12.13: every source row is in a target (verified equal), unowned, or bookkeeping."""
        out = []
        unowned: dict[str, set] = {}
        for u in self.placement.unowned:
            pk = self.tables[u["table"]].pk
            unowned.setdefault(u["table"], set()).add(tuple(None if u["key"][c] is None else str(u["key"][c]) for c in pk))
        cov = {}
        for name in moving(self.tables):
            n = R.count(self.src, name)
            if name in BOOKKEEPING:
                covered = n
            else:
                t = self.tables[name]
                keys = (set(self.graph.keys[name]) if name in self.graph.keys
                        else set(R.key_md5s(self.src, name, t.pk, t.pk)) if t.pk else set())
                have = verified.get(name, set()) | unowned.get(name, set())
                covered = len(keys & have)
            cov[name] = {"source_rows": n, "covered": covered, "missing": n - covered}
            if n - covered:
                out.append(P.refusal("count mismatch", table=name,
                                     detail=f"{n - covered} source rows in no target"))
        self.rep["coverage"] = cov
        return out

    def close(self) -> None:
        src = getattr(self, "src", None)
        if src is not None:
            _close(src)


def provision(a, su: str, rep: dict) -> int:
    with psycopg.connect(su, autocommit=True) as c:
        projects = {r[0] for r in c.execute("SELECT pid::text FROM core.project").fetchall()}
        dbs = {r[0] for r in c.execute("SELECT datname FROM pg_database").fetchall()}
    pids = sorted(projects) if a.all else a.project
    code = 0
    for pid in pids:
        if pid not in projects:
            rep["refusals"].append(P.refusal("unknown project", project=pid, detail="not in core.project"))
            code = 1
            continue
        name = projectdb.database_name(pid)
        if name in dbs:  # a database made before the setup function existed (S-D4)
            with psycopg.connect(make_conninfo(su, dbname=name)) as t:
                if projectdb.install_setup_function(t, su):
                    log.info("project %s: setup function installed", pid)
        projectdb.provision_as(su, pid, owner="platform_rw", set_role="platform_rw")
        rep["projects"][pid] = {"database": name, "status": "provisioned", "tables": {}, "sequences": {}}
        log.info("project %s: provisioned", pid)
    return code


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="isolate: %(levelname)s %(message)s")
    try:
        a = parse(sys.argv[1:] if argv is None else argv)
    except Usage as e:
        print(f"isolate: {e}", file=sys.stderr)
        return 2
    except SystemExit as e:  # argparse
        return int(e.code or 2)
    su = os.environ.get("ISOLATE_SUPERUSER_URL")
    if not su:
        print("isolate: ISOLATE_SUPERUSER_URL is not set", file=sys.stderr)
        return 2
    rep = REP.new(a.subcommand, bool(a.dry_run))
    run = None
    code = 1
    try:
        if a.subcommand == "provision":
            code = provision(a, su, rep)
        elif a.subcommand == "verify-dump":
            from .verify import verify_dump
            run, code = verify_dump(a, su, Run)
            rep = run.rep if run is not None else rep
        else:
            run = Run(a, su)
            rep = run.rep
            if a.subcommand in ("plan", "copy"):
                code = run.plan_or_copy()
            elif a.subcommand == "verify":
                code = run.verify()
            else:
                code = run.verify(failing=False)
    except Exception as e:  # noqa: BLE001
        rep.setdefault("error", REP.describe(e, su))
        log.error("stopped: %s", rep["error"])
        code = 1
    finally:
        if run is not None:
            run.close()
    if rep["refusals"] and code == 0:
        code = 1
    if a.report:
        REP.write(a.report, rep)
    print(REP.summary(rep))
    return code
