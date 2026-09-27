"""The report test bed in the ISOLATED layout (isolation 2026-09-25, 01-specs.md I1.1, I1.3, I1.5..I1.7).

Test infrastructure only. It builds the state that `python -m platform_service.isolate copy` plus the
stage-7 drop leave behind, so the report composer's and the renderer's tests can run against one
database per project before the real tool exists:

    from report_bed_isolated import build_isolated
    bed = build_isolated("iso-rep-renderer")          # modules=True: qualification, CO, engine seeded
    bed.dsn("report_ro", report_bed.project_db(IDS["A"]))
    bed.stop()

What it does, in order:
 1. `report_bed.build(label, modules=...)`: the old (shared) layout with its fixed seed.
 2. A project database for every project of core.project that should have one (the seed says gamma
    has none, `no_database` defaults to gamma; legacy beds pass `no_database=frozenset()` so gamma
    gets one too; with modules=False the composer bed gets databases for alpha, beta and echo).
 3. Per project P, in P's database: the moving schemas (qualification, control_objectives, engine,
    report_composer when present) and core.system are restored from a pg_dump of `platform`, then
    every row that is not P's is removed (core.project cascade, then an FK-driven prune of engine,
    whose Django keys have no ON DELETE), `project_id` is dropped from the five tables of I1.7,
    core.system becomes project.system (I1.5, FKs follow it, I1.6), and schema core goes.
 4. Owners and grants: schemas owned by platform_rw, tables by their module role; the reader list of
    I2.6 for report_ro and dashboard_ro. When the platform's template files 0006..0010 exist they
    are applied by step 2 and this step only adds what the modules' migrations would add; when they
    do not, the bed stands in for them and records it in `bed.applied["templates 0006..0010"] = False`.
 5. In `platform`: the moving schemas and core.system are dropped (stage 7, I1.3); schema
    report_library is made (owner report_composer_rw) when init/platform-db.sql did not make it.

Never the host's 5432 (the bed's own port). Never prints a password or a row.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_bed  # noqa: E402

IDS = report_bed.IDS
project_db = report_bed.project_db

MOVING = ("qualification", "control_objectives", "engine", "report_composer")
MODULE_ROLE = {"qualification": "qualification_rw", "control_objectives": "control_objectives_rw",
               "engine": "engine_rw", "report_composer": "report_composer_rw"}
#: the platform project's column in each root table (I1.7); engine keeps its column (I7.9)
DROPPED_PROJECT_ID = ("qualification.qualification", "control_objectives.project",
                      "report_composer.layout", "report_composer.template", "report_composer.generated_report")
NEW_TEMPLATES = ("0006_project_system.sql", "0007_qualification.sql", "0008_control_objectives.sql",
                 "0009_engine.sql", "0010_report_composer.sql")
#: I2.6, the one reader list for report_ro and dashboard_ro
READERS = {
    "project": ["system"],
    "qualification": ["qualification", "qualification_answer", "qualification_risk", "knowledge_graph",
                      "card_component", "question_set", "question_set_version", "question_set_version_item",
                      "question", "questionnaire", "questionnaire_version", "questionnaire_version_item"],
    "control_objectives": ["project", "graph", "risk", "mapped_objective", "mapping_run"],
    "engine": ["project", "ai_system", "ai_component", "evaluation", "evaluation_plugin", "evaluation_input",
               "plugin", "observation", "measurement", "metric", "direct", "derived", "metric_category",
               "metric_category_metrics", "artifact"],
}
#: projects of the seed with no project database (report_bed's seed comment: gamma has none)
NO_DATABASE = {IDS["C"]}


def missing_templates() -> list[str]:
    return [n for n in NEW_TEMPLATES if not (report_bed.PROJECT_TEMPLATE / n).exists()]


def _connect(bed, db):
    import psycopg

    return psycopg.connect(bed.su_dsn(db), autocommit=True)


def _docker(bed, *args, check=True, input_=None):
    r = subprocess.run(["docker", "exec", "-i", "-e", f"PGPASSWORD={bed.t.password}", bed.t.name, *args],
                       capture_output=True, text=input_ is not None, input=input_)
    if check and r.returncode != 0:
        err = r.stderr if isinstance(r.stderr, str) else r.stderr.decode(errors="replace")
        raise RuntimeError(f"bed: {args[0]} failed: {err[-2000:]}")
    return r


def _dump(bed, path, *selectors):
    _docker(bed, "pg_dump", "-h", "127.0.0.1", "-U", "aisc-postgres-user",
            "-Fc", "--no-owner", "--no-privileges", *selectors, "-f", path, "platform")


def _restore(bed, db, path):
    """pg_restore without the CREATE SCHEMA entries (the schemas may exist already, made by a template)."""
    listing = _docker(bed, "pg_restore", "-l", path).stdout.decode()
    keep = "\n".join(line for line in listing.splitlines() if " SCHEMA " not in line or line.startswith(";"))
    lst = path + ".list"
    _docker(bed, "sh", "-c", f"cat > {lst}", input_=keep)
    _docker(bed, "pg_restore", "-h", "127.0.0.1", "-U", "aisc-postgres-user", "--no-owner", "--no-privileges",
            "--exit-on-error", "-L", lst, "-d", db, path)


def _roles(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT rolname FROM pg_roles").fetchall()}


def _prune_engine(conn, pid) -> None:
    """Rows of other projects out of engine: its FKs (Django) have no ON DELETE, so delete orphans to a fixpoint."""
    if conn.execute("SELECT to_regclass('engine.project')").fetchone()[0] is None:
        return
    conn.execute("SET session_replication_role = replica")
    conn.execute("DELETE FROM engine.project WHERE project_id IS DISTINCT FROM %s", (pid,))
    fks = conn.execute(
        "SELECT c.conrelid::regclass::text, c.confrelid::regclass::text,"
        " array_agg(a.attname ORDER BY k.n), array_agg(fa.attname ORDER BY k.n)"
        " FROM pg_constraint c CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(ck, fk, n)"
        " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.ck"
        " JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = k.fk"
        " WHERE c.contype = 'f' AND c.connamespace = 'engine'::regnamespace"
        " GROUP BY c.oid, c.conrelid, c.confrelid").fetchall()
    while True:
        removed = 0
        for child, parent, cols, pcols in fks:
            notnull = " AND ".join(f"ch.{c} IS NOT NULL" for c in cols)
            match = " AND ".join(f"p.{pc} = ch.{c}" for c, pc in zip(cols, pcols))
            removed += conn.execute(f"DELETE FROM {child} ch WHERE {notnull}"
                                    f" AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE {match})").rowcount
        if removed == 0:
            break
    conn.execute("SET session_replication_role = origin")


def _isolate_one(bed, pid, schemas, templates_applied) -> None:
    db = project_db(pid)
    with _connect(bed, db) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS core")
        for (fn,) in _core_functions(bed):
            conn.execute(fn)
        for s in schemas:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
    _restore(bed, db, "/tmp/iso-core.dump")
    if schemas:
        _restore(bed, db, "/tmp/iso-modules.dump")
    with _connect(bed, db) as conn:
        roles = _roles(conn)
        with conn.transaction():
            conn.execute("DELETE FROM core.project WHERE pid <> %s", (pid,))
        _prune_engine(conn, pid)
        with conn.transaction():
            for t in DROPPED_PROJECT_ID:
                if conn.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is not None:
                    conn.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS project_id CASCADE")
            if conn.execute("SELECT to_regclass('project.system')").fetchone()[0] is None:
                conn.execute("CREATE SCHEMA IF NOT EXISTS project")
                conn.execute("ALTER TABLE core.system SET SCHEMA project")
                conn.execute("ALTER TABLE project.system DROP COLUMN project_id CASCADE")
                conn.execute("ALTER TABLE project.system ADD CONSTRAINT system_number_key UNIQUE (number)")
            else:  # the template made project.system: fill it and point the keys at it (I1.6)
                cols = [r[0] for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'project'"
                    " AND table_name = 'system' AND column_name IN (SELECT column_name FROM"
                    " information_schema.columns WHERE table_schema = 'core' AND table_name = 'system')"
                    " ORDER BY ordinal_position").fetchall()]
                conn.execute(f"INSERT INTO project.system ({', '.join(cols)}) SELECT {', '.join(cols)}"
                             " FROM core.system")
                for tbl, name, definition in conn.execute(
                        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint"
                        " WHERE contype = 'f' AND confrelid = 'core.system'::regclass").fetchall():
                    conn.execute(f'ALTER TABLE {tbl} DROP CONSTRAINT "{name}"')
                    conn.execute(f'ALTER TABLE {tbl} ADD CONSTRAINT "{name}" '
                                 + definition.replace("core.system(", "project.system("))
                conn.execute("DROP TABLE core.system")
            conn.execute(
                "CREATE OR REPLACE FUNCTION project.system_only_latest_changes() RETURNS trigger"
                " LANGUAGE plpgsql AS $f$ BEGIN"
                " IF NEW.number <> OLD.number THEN RAISE EXCEPTION 'a version keeps its number'; END IF;"
                " IF OLD.number < (SELECT max(number) FROM project.system) THEN"
                " RAISE EXCEPTION 'only the latest version may change'; END IF; RETURN NEW; END $f$")
            conn.execute("DROP TRIGGER IF EXISTS system_only_latest_changes ON project.system")
            conn.execute("CREATE TRIGGER system_only_latest_changes BEFORE UPDATE ON project.system"
                         " FOR EACH ROW EXECUTE FUNCTION project.system_only_latest_changes()")
            if conn.execute("SELECT to_regprocedure('qualification.card_is_latest(uuid)')").fetchone()[0]:
                conn.execute(
                    "CREATE OR REPLACE FUNCTION qualification.card_is_latest(version_pid uuid) RETURNS boolean"
                    " LANGUAGE sql STABLE AS $f$ SELECT EXISTS (SELECT 1 FROM project.system s"
                    " WHERE s.pid = version_pid AND s.number = (SELECT max(o.number) FROM project.system o)) $f$")
            conn.execute("DROP SCHEMA core CASCADE")
            # owners (D10): schemas platform_rw, tables the module role, project.system platform_rw
            conn.execute("ALTER SCHEMA project OWNER TO platform_rw")
            conn.execute("ALTER TABLE project.system OWNER TO platform_rw")
            for s in MOVING:
                role = MODULE_ROLE[s]
                if role not in roles:
                    continue
                if s == "report_composer" and not templates_applied:
                    conn.execute("CREATE SCHEMA IF NOT EXISTS report_composer")
                if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (s,)).fetchone() is None:
                    continue
                conn.execute(f"ALTER SCHEMA {s} OWNER TO platform_rw")
                for (t,) in conn.execute("SELECT c.oid::regclass::text FROM pg_class c WHERE c.relkind IN ('r', 'p')"
                                         " AND c.relnamespace = %s::regnamespace", (s,)).fetchall():
                    conn.execute(f"ALTER TABLE {t} OWNER TO {role}")
                for (f,) in conn.execute("SELECT p.oid::regprocedure::text FROM pg_proc p"
                                         " WHERE p.pronamespace = %s::regnamespace", (s,)).fetchall():
                    conn.execute(f"ALTER FUNCTION {f} OWNER TO {role}")
                if not templates_applied:  # what 0007..0010 would grant
                    conn.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {role}')
                    conn.execute(f"GRANT USAGE, CREATE ON SCHEMA {s} TO {role}")
                    conn.execute(f'ALTER ROLE {role} IN DATABASE "{db}" SET search_path = {s}')
                    conn.execute(f"GRANT USAGE ON SCHEMA project TO {role}")
                    conn.execute(f"GRANT SELECT, REFERENCES ON project.system TO {role}")
            for reader in ("report_ro", "dashboard_ro"):
                if reader not in roles:
                    continue
                if not templates_applied:
                    conn.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {reader}')
                for s, tables in READERS.items():
                    if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (s,)).fetchone() is None:
                        continue
                    conn.execute(f"GRANT USAGE ON SCHEMA {s} TO {reader}")
                    for t in tables:
                        if conn.execute("SELECT to_regclass(%s)", (f"{s}.{t}",)).fetchone()[0] is not None:
                            conn.execute(f"GRANT SELECT ON {s}.{t} TO {reader}")
                if conn.execute("SELECT to_regclass('engine.plugin_config')").fetchone()[0] is not None:
                    conn.execute(f"GRANT SELECT (id, plugin_id) ON engine.plugin_config TO {reader}")


_CORE_FUNCTIONS: list | None = None


def _core_functions(bed):
    """core's functions (the trigger function of core.system), so the core dump restores."""
    global _CORE_FUNCTIONS
    if _CORE_FUNCTIONS is None:
        with _connect(bed, "platform") as conn:
            _CORE_FUNCTIONS = conn.execute(
                "SELECT pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.pronamespace = 'core'::regnamespace"
            ).fetchall()
    return _CORE_FUNCTIONS


def build_isolated(label: str = "iso-rep", *, modules: bool = True, no_database=frozenset(NO_DATABASE)):
    """`no_database`: the pids of the seed that get no project database (default: gamma, as the seed says).
    Legacy beds pass `frozenset()` so that gamma, too, has a database holding its own version C_V1."""
    global _CORE_FUNCTIONS
    no_database = frozenset(no_database)
    _CORE_FUNCTIONS = None
    bed = report_bed.build(label, seed=True, modules=modules)
    try:
        missing = missing_templates()
        bed.applied["templates 0006..0010"] = not missing
        bed.missing_templates = missing
        with _connect(bed, "platform") as conn:
            pids = [str(r[0]) for r in conn.execute("SELECT pid FROM core.project ORDER BY pid").fetchall()]
            schemas = [s for s in MOVING if conn.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname = %s", (s,)).fetchone()]
            existing = {r[0] for r in conn.execute("SELECT datname FROM pg_database").fetchall()}
        for pid in pids:
            if pid not in no_database and project_db(pid) not in existing:
                report_bed._project_database(bed.t, pid)
        _dump(bed, "/tmp/iso-core.dump", "-t", "core.system", "-t", "core.project")
        with_tables = [s for s in schemas if _has_tables(bed, s)]
        if with_tables:
            _dump(bed, "/tmp/iso-modules.dump", *[x for s in with_tables for x in ("-n", s)])
        for pid in pids:
            if pid not in no_database:
                _isolate_one(bed, pid, with_tables, templates_applied=not missing)
        with _connect(bed, "platform") as conn, conn.transaction():
            for s in schemas:
                conn.execute(f"DROP SCHEMA {s} CASCADE")
            conn.execute("DROP TABLE IF EXISTS core.system CASCADE")
            conn.execute("DROP FUNCTION IF EXISTS core.system_only_latest_changes()")
            bed.applied["report_library by init"] = conn.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname = 'report_library'").fetchone() is not None
            if not bed.applied["report_library by init"] and "report_composer_rw" in _roles(conn):
                conn.execute("CREATE SCHEMA report_library AUTHORIZATION report_composer_rw")
        bed.isolated = True
        return bed
    except Exception:
        bed.stop()
        raise


def _has_tables(bed, schema) -> bool:
    with _connect(bed, "platform") as conn:
        return conn.execute("SELECT 1 FROM pg_class WHERE relnamespace = %s::regnamespace AND relkind = 'r'"
                            " LIMIT 1", (schema,)).fetchone() is not None


if __name__ == "__main__":  # a smoke run: build, print counts, remove
    b = build_isolated("iso-rep-smoke")
    try:
        print("applied:", b.applied)
        for key in ("A", "B", "E"):
            db = project_db(IDS[key])
            print(key, "versions", b.scalar(db, "SELECT count(*) FROM project.system"),
                  "evaluations", b.scalar(db, "SELECT count(*) FROM engine.evaluation"),
                  "cards", b.scalar(db, "SELECT count(*) FROM qualification.qualification"))
        print("platform schemas:", b.scalar("platform", "SELECT string_agg(nspname, ',' ORDER BY nspname) FROM"
                                                        " pg_namespace WHERE nspname !~ '^pg_' AND nspname <>"
                                                        " 'information_schema'"))
    finally:
        b.stop()
