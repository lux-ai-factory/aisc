"""The isolation test bed (isolation 2026-09-25, 01-specs.md section 20): one throwaway Postgres with
the platform database and project databases made the way the isolated stack makes them.

Test infrastructure only. It builds databases with the product's own files and commands and records
what could not be built as `problems`, so a test that needs a missing piece FAILS with the requirement
ID instead of erroring in a fixture:

    bed = build("grants")               # aisc-t-iso-top-grants-<hex>, a free port, never 5432
    bed.require("qualification", "engine")   # pytest.fail("missing feature: ...") when absent
    bed.stop()

Steps, in the stack's order:
 1. init/platform-db.sql, init/project-databases.sql, init/inspector-role.sql, init/report-roles.sql
    (superuser; a file that fails is a problem, not an error)
 2. platform migrations as platform_rw (scripts/pipeline_chain/throwaway.platform_migration)
 3. two projects A and B in core.project (platform_rw), their databases made by the platform's own
    `projectdb.provision` (so every template file 0001.. is applied, 0006..0010 included once they exist)
 4. each module's migrate command against every project database (I3.6, I5.5, I7.6, I8.4, controls):
    qualification `node scripts/migrate-projects.mjs`, control-objectives
    `python -m aisc_control_objectives.migrate_projects`, engine `manage.py migrate_projects`, composer
    `python -m report_composer.migrate`, controls `node scripts/migrate-projects.mjs`.

Passwords stay in memory: never printed, never in an assertion message.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
from throwaway import SU, Throwaway, platform_migration  # noqa: E402

INSTALL = Path.home() / "aisc-install"

A = "a0000000-0000-4000-8000-00000000000a"
B = "b0000000-0000-4000-8000-00000000000b"

#: I2.1: the template files every project database has after isolation.
TEMPLATES = ["0001_controls.sql", "0002_dashboard.sql", "0003_report.sql", "0004_inspector.sql",
             "0005_llm.sql", "0006_project_system.sql", "0007_qualification.sql",
             "0008_control_objectives.sql", "0009_engine.sql", "0010_report_composer.sql",
             "0011_qualification_temporary.sql", "0012_connection.sql",
             "0013_connection_allowlist.sql", "0014_target.sql"]

#: I1.1: module schema -> its role.
MODULES = {
    "qualification": "qualification_rw",
    "control_objectives": "control_objectives_rw",
    "engine": "engine_rw",
    "report_composer": "report_composer_rw",
    "controls": "controls_rw",
}

#: I2.6, exhaustive: SELECT for report_ro and dashboard_ro inside a project database.
READERS = ("report_ro", "dashboard_ro")
READER_TABLES = {
    "project": ["system"],
    # what each assessment is about (targets plan v2): no secret, the readers show it with results
    "target": ["target"],
    "controls": ["checklist", "checklist_question", "source", "submission", "submission_answer"],
    "qualification": ["qualification", "qualification_answer", "qualification_risk", "knowledge_graph",
                      "card_component", "form", "form_version", "form_question", "form_version_question"],
    "control_objectives": ["project", "graph", "risk", "mapped_objective", "mapping_run"],
    "engine": ["aisc_backend_project", "aisc_backend_aisystem", "aisc_backend_aicomponent", "aisc_backend_evaluation",
               "aisc_backend_evaluationplugin", "aisc_backend_evaluationinput", "aisc_backend_plugin", "aisc_backend_observation",
               "aisc_backend_measurement", "aisc_backend_metric", "aisc_backend_direct", "aisc_backend_derived",
               "aisc_backend_metriccategory", "aisc_backend_metriccategory_metrics", "aisc_backend_artifact"],
    "report_composer": [],
    "llm": [],
    "connection": [],
    "provision": [],
}
#: I2.6: only these columns of engine.aisc_backend_pluginconfig.
PLUGIN_CONFIG_COLUMNS = ["id", "plugin_id"]
#: I2.6: never readable by either reader.
SECRETS = ["engine.aisc_backend_projectconfig", "engine.aisc_backend_pluginconfigprojectconfig", "llm.provider",
           "llm.system_choice", "connection.endpoint", "connection.run_key"]

#: The migration trackers of every module (I16.3, I16.6 C7).
TRACKERS = {
    "qualification": "qualification._prisma_migrations",
    "control_objectives": "control_objectives.alembic_version",
    "engine": "engine.django_migrations",
    "report_composer": "report_composer.schema_migration",
    "controls": "controls._prisma_migrations",
}


def project_db(pid: str) -> str:
    return "project_" + pid.replace("-", "")


def _python(module_dir: str) -> str:
    """The module's virtualenv python: this worktree's when it has one, else the install's (used
    read-only; the code imported is this worktree's, through cwd/PYTHONPATH)."""
    for base in (ROOT, INSTALL):
        p = base / module_dir / ".venv/bin/python"
        if p.exists():
            return str(p)
    return ""


@dataclass
class IsoBed:
    t: Throwaway
    projects: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)

    @property
    def port(self) -> int:
        return self.t.port

    def dsn(self, role: str, db: str) -> str:
        return f"postgresql://{role}:{role}@127.0.0.1:{self.t.port}/{db}"

    def su_dsn(self, db: str) -> str:
        return f"postgresql://{SU}:{self.t.password}@127.0.0.1:{self.t.port}/{db}"

    def template(self, role: str, suffix: str = "") -> str:
        return f"postgresql://{role}:{role}@127.0.0.1:{self.t.port}/{{database}}{suffix}"

    def psql(self, db: str, sql: str, role: str | None = None, check: bool = False):
        return self.t.psql(db, sql, role=role, check=check)

    def rows(self, db: str, sql: str, role: str | None = None) -> list[dict]:
        return self.t.rows(db, sql, role=role)

    def scalar(self, db: str, sql: str) -> str:
        return self.t.scalar(db, sql)

    def require(self, *keys: str) -> None:
        missing = [f"{k}: {self.problems[k]}" for k in keys if k in self.problems]
        if missing:
            pytest.fail("missing feature: " + "; ".join(missing))

    def exists(self, db: str, relation: str) -> bool:
        return self.scalar(db, f"SELECT to_regclass('{relation}') IS NOT NULL") == "t"

    def stop(self) -> None:
        self.t.stop()


def _redact(bed: IsoBed, text: str) -> str:
    return text.replace(bed.t.password, "***")


def _su_file(bed: IsoBed, db: str, path: Path, key: str) -> None:
    if not path.exists():
        bed.problems[key] = f"{path.relative_to(ROOT)} missing"
        return
    r = bed.psql(db, path.read_text())
    if r.returncode != 0:
        bed.problems[key] = f"{path.name} failed: " + _redact(bed, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "?")


def _run(bed: IsoBed, key: str, cmd: list[str], cwd: Path, env: dict[str, str], why: str) -> None:
    try:
        r = subprocess.run(cmd, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as e:
        bed.problems[key] = f"{why}: {e}"
        return
    out = _redact(bed, (r.stdout + r.stderr)[-1500:])
    bed.logs[key] = out
    if r.returncode != 0:
        last = [l for l in out.strip().splitlines() if l.strip()][-1:] or ["?"]
        bed.problems[key] = f"{why} (exit {r.returncode}): {last[0][:300]}"


def provision(bed: IsoBed, pids: list[str]) -> None:
    """Rows in core.project, then the platform's own projectdb.provision for each (I2.4)."""
    for pid in pids:
        r = bed.psql("platform", f"INSERT INTO core.project (pid, name, slug) VALUES "
                                 f"('{pid}', 'Iso {pid[:1]}', 'iso-{pid[:8]}') ON CONFLICT DO NOTHING",
                     role="platform_rw")
        if r.returncode != 0:
            bed.problems["projects"] = _redact(bed, r.stderr.strip())
            return
    code = ("import sys; from platform_service import projectdb\n"
            "for p in sys.argv[2:]: projectdb.provision(sys.argv[1], p)\n")
    _run(bed, "provision", ["uv", "run", "--quiet", "--extra", "dev", "python", "-c", code,
                            bed.dsn("platform_rw", "platform"), *pids],
         ROOT / "platform", {"PLATFORM_DATABASE_URL": bed.dsn("platform_rw", "platform"),
                             "PLATFORM_TEST_DATABASE_URL": bed.dsn("platform_rw", "platform")},
         "projectdb.provision")
    bed.projects += [p for p in pids if p not in bed.projects]
    templates = {p.name for p in (ROOT / "platform/project-template").glob("*.sql")}
    lacking = [t for t in TEMPLATES if t not in templates]
    if lacking:
        bed.problems["templates"] = "I2.1 template files missing: " + ", ".join(lacking)


def migrate_modules(bed: IsoBed) -> None:
    """Each module's own command for every project database (the -migrate one-shots of the stack)."""
    port = bed.port
    # controls: exists today (plan 1)
    _run(bed, "controls", ["node", "scripts/migrate-projects.mjs"], ROOT / "apps/controls",
         {"PROJECT_DATABASE_URL": bed.template("controls_rw", "?schema=controls")},
         "controls migrate-projects.mjs")
    # qualification (I3.6): every project database (no form library: forms are per project)
    q = ROOT / "apps/qualification/scripts/migrate-projects.mjs"
    if not q.exists():
        bed.problems["qualification"] = "I3.6 apps/qualification/scripts/migrate-projects.mjs missing"
    else:
        _run(bed, "qualification", ["node", str(q)], ROOT / "apps/qualification",
             {"PROJECT_DATABASE_URL": bed.template("qualification_rw", "?schema=qualification&connection_limit=2")},
             "I3.6 qualification migrate-projects.mjs")
    # control objectives (I5.5)
    py = _python("apps/control-objectives")
    if not py:
        bed.problems["control_objectives"] = "no python environment for apps/control-objectives"
    else:
        _run(bed, "control_objectives", [py, "-m", "aisc_control_objectives.migrate_projects"],
             ROOT / "apps/control-objectives",
             {"PYTHONPATH": str(ROOT / "apps/control-objectives/src"),
              "DATABASE_URL": f"postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:{port}/platform",
              "PROJECT_DATABASE_URL": "postgresql+psycopg://control_objectives_rw:control_objectives_rw@127.0.0.1:"
                                      f"{port}/{{database}}"},
             "I5.5 python -m aisc_control_objectives.migrate_projects")
    # engine (I7.6)
    py = _python("apps/backend")
    if not py:
        bed.problems["engine"] = "no python environment for apps/backend"
    else:
        _run(bed, "engine", [py, "manage.py", "migrate_projects"], ROOT / "apps/backend",
             # migrate_projects (aisc_backend/deployment.py) only migrates a database per
             # project in configurator mode, which is what this bed's engine runs as.
             {"AISC_DEPLOYMENT": "configurator",
              "DB_ENGINE": "django.db.backends.postgresql", "DB_NAME": "platform", "DB_USER": "engine_rw",
              "DB_PASSWORD": "engine_rw", "DB_HOST": "127.0.0.1", "DB_PORT": str(port), "DB_SCHEMA": "engine",
              "PYTHONPATH": f"{ROOT}/shared/plugin-interface/src:{ROOT}/shared/plugin-manager/src"},
             "I7.6 manage.py migrate_projects")
    # report composer (I8.4)
    py = _python("apps/report-composer")
    if not py:
        bed.problems["report_composer"] = "no python environment for apps/report-composer"
    else:
        _run(bed, "report_composer", [py, "-m", "report_composer.migrate"], ROOT / "apps/report-composer",
             {"PYTHONPATH": str(ROOT / "apps/report-composer"),
              "REPORT_COMPOSER_DATABASE_URL": bed.dsn("report_composer_rw", "platform"),
              "REPORT_COMPOSER_PROJECT_DATABASE_URL": bed.template("report_composer_rw")},
             "I8.4 python -m report_composer.migrate (library + every project database)")
    # what the commands must have produced, per project database
    for pid in bed.projects:
        db = project_db(pid)
        for module, tracker in TRACKERS.items():
            if module in bed.problems:
                continue
            if not bed.exists(db, tracker):
                bed.problems[module] = f"{db}: {tracker} missing after the migrate command"
        if not bed.exists(db, "project.system"):
            bed.problems.setdefault("project_system", f"I1.5/I2.1 {db}: project.system missing")


def build(label: str, *, projects: tuple[str, ...] = (A, B), modules: bool = True) -> IsoBed:
    t = Throwaway.start(f"iso-top-{label}")
    bed = IsoBed(t)
    try:
        _su_file(bed, "postgres", ROOT / "init/platform-db.sql", "init")
        for f in ("project-databases", "inspector-role", "report-roles"):
            _su_file(bed, "platform", ROOT / f"init/{f}.sql", f"init-{f}")
        for m in sorted((ROOT / "platform/migrations").glob("*.sql")):
            try:
                platform_migration(t, m)
            except subprocess.CalledProcessError as e:
                bed.problems["platform-migrations"] = f"{m.name}: " + _redact(bed, (e.stderr or "").strip()[-300:])
                break
        if projects:
            provision(bed, list(projects))
        if modules and projects:
            migrate_modules(bed)
        return bed
    except BaseException:
        t.stop()
        raise
