"""Step 8 of the pipeline chain: the dashboard's two datasets carry the right card version.

A test result read through `engine_results_<hex>` carries the version that was the
latest when its evaluation started (v1), and a control answer read through
`controls_answers_<hex>` carries the version under which it was answered (v2).

Both datasets run on the project's own database, as dashboard_ro does through the project's
"AISC Controls <slug>" connection: the engine dataset reads engine.aisc_backend_measurement and
project.system of that database and filters by nothing, since the database is the project. The
engine query below is the dashboard's own SQL (aisc_ext.projects.engine_results_sql).

Two modes.
- Inside scripts/test-pipeline-chain.sh ($CHAIN_JSON names the container and the ids the
  earlier steps wrote): only the queries run, on what the modules wrote.
- Standalone (`uv run --no-project --with pytest python -m pytest scripts/pipeline_chain`): a
  throwaway postgres:15-alpine is made with the platform's init files and migrations, two
  projects P and Q get their databases (platform_rw with the project template, as
  tpg_project_db), `manage.py migrate_projects` makes the engine's tables in both, P is seeded
  with v1 and v2 in its project.system, an evaluation stamped v1 and an answer stamped v2, and Q
  with its own version and evaluation, whose rows must never appear in P's. The container
  is removed afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from throwaway import ROOT, SHARED_PYTHONPATH, SU, Throwaway, platform_migration

DASHBOARD = ROOT / "apps/results-dashboard"

ENGINE_RESULTS_SQL = """SELECT m.pid, m.score, m.unit, m.time, m.dimensions, met.name AS metric,
       e.pid AS evaluation_pid, e.created_at AS evaluated_at,
       s.pid AS system_version_pid, s.number AS system_version,
       t.key AS target_key, t.kind AS target_kind, t.component_kind AS target_component_kind,
       CASE WHEN ti.id IS NULL THEN 'unassigned'
            WHEN t.key IS NULL THEN tc.name::text
            ELSE t.label END AS target_label,
       CASE WHEN ti.id IS NULL THEN 'unassigned'
            WHEN t.key IS NULL THEN 'not a target'
            WHEN t.kind = 'component'
                 AND t.last_card_number < (SELECT max(number) FROM project.system) THEN 'stale'
            ELSE 'current' END AS target_status,
       COALESCE(p.display_name, p.name, 'unknown') AS tool
  FROM engine.aisc_backend_measurement m
  JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
  JOIN engine.aisc_backend_evaluation e ON e.id = o.evaluation_id
  JOIN engine.aisc_backend_metric met ON met.id = m.metric_id
  LEFT JOIN project.system s ON s.pid = e.system_id
  LEFT JOIN (engine.aisc_backend_evaluationplugin ep
             JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id
             JOIN engine.aisc_backend_plugin p ON p.id = pc.plugin_id)
         ON ep.evaluation_id = e.id
        AND o.tool = p.package_name || '::' || p.name || ' (v' || p.version || ')'
  LEFT JOIN engine.aisc_backend_evaluationinput ti ON ti.evaluation_plugin_id = ep.id AND ti.name = 'target'
  LEFT JOIN engine.aisc_backend_aicomponent tc ON tc.id = ti.component_id
  LEFT JOIN target.target t ON t.engine_component = tc.pid
"""

CONTROLS_ANSWERS_SQL = """
SELECT c.title, q.text, a.answer, a.score, a.system_version_number, a.answered_at,
       s.label, s.version AS submission_version
  FROM controls.submission_answer a
  JOIN controls.submission s ON s.id = a."submissionId"
  JOIN controls.checklist_question q ON q.id = a."questionId"
  JOIN controls.checklist c ON c.id = q."checklistId"
"""


class Ctx:
    def __init__(self, t: Throwaway, project: str, project_db: str, other_db: str | None, owned: bool):
        self.t, self.project, self.project_db, self.other_db, self.owned = t, project, project_db, other_db, owned
        self.problems: list[str] = []

    def require(self) -> None:
        if self.problems:
            pytest.fail("missing feature: " + "; ".join(self.problems))


def _chain_ctx() -> Ctx | None:
    path = os.environ.get("CHAIN_JSON")
    if not path or not Path(path).exists():
        return None
    d = json.loads(Path(path).read_text())
    if not d.get("project_pid"):
        return None
    pw = os.environ["CHAIN_SU_DSN"].split(":")[2].split("@")[0]
    t = Throwaway(d["container"], d["port"], pw)
    return Ctx(t, d["project_pid"], d.get("project_db") or "project_" + d["project_pid"].replace("-", ""), None, False)


def _has_column(t: Throwaway, db: str, schema: str, table: str, column: str) -> bool:
    return t.scalar(db, f"SELECT 1 FROM information_schema.columns WHERE table_schema='{schema}'"
                        f" AND table_name='{table}' AND column_name='{column}'") == "1"


def _project_database(t: Throwaway, pid: str) -> str:
    """As the platform provisions one: made by platform_rw, every template file applied as it, tracked."""
    db = "project_" + pid.replace("-", "")
    t.psql("platform", f'CREATE DATABASE "{db}"', role="platform_rw")
    t.psql(db, "CREATE SCHEMA IF NOT EXISTS provision; CREATE TABLE IF NOT EXISTS provision.template_migration"
               " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());", role="platform_rw")
    for f in sorted((ROOT / "platform/project-template").glob("*.sql")):
        t.psql(db, f.read_text() + f"\n;\nINSERT INTO provision.template_migration (name) VALUES ('{f.name}');",
               role="platform_rw")
    return db


ENGINE_SEED = """
SET search_path = engine;
INSERT INTO aisc_backend_project (pid, name, description, status, created_at, project_id)
  VALUES (gen_random_uuid(), 'P', '', 'active', now(), '{project}');
INSERT INTO aisc_backend_metric (pid, name, description, type_spec, created_at) VALUES (gen_random_uuid(), 'accuracy', '', 'direct', now());
INSERT INTO aisc_backend_evaluation (pid, status, project_id, system_id, created_at)
  SELECT gen_random_uuid(), 'completed', id, '{version}'::uuid, now() FROM aisc_backend_project;
INSERT INTO aisc_backend_observation (pid, name, description, observer, tool, evaluation_id, created_at)
  SELECT gen_random_uuid(), 'o', '', 'x', 'x', id, now() FROM aisc_backend_evaluation;
INSERT INTO aisc_backend_measurement (pid, name, description, unit, time, score, uncertainty, metric_id, observation_id, created_at)
  SELECT gen_random_uuid(), 'm', '', '%', now(), 0.9, 0, (SELECT id FROM aisc_backend_metric LIMIT 1), id, now() FROM aisc_backend_observation;
"""


def _standalone() -> Ctx:
    t = Throwaway.start("dashq")
    p, q = str(uuid.uuid4()), str(uuid.uuid4())
    v1, v2, w1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    t.psql("postgres", (ROOT / "init/platform-db.sql").read_text())
    t.psql("platform", (ROOT / "init/project-databases.sql").read_text())
    for f in sorted((ROOT / "platform/migrations").glob("*.sql")):
        platform_migration(t, f)
    t.psql("platform", f"INSERT INTO core.project (pid, name, slug) VALUES ('{p}', 'P', 'p-{p[:8]}'),"
                       f" ('{q}', 'Q', 'q-{q[:8]}')", role="platform_rw")
    db, other = _project_database(t, p), _project_database(t, q)
    ctx = Ctx(t, p, db, other, True)
    if t.scalar(db, "SELECT to_regclass('project.system') IS NOT NULL") != "t":
        ctx.problems.append("project.system (template 0006_project_system.sql)")
        return ctx
    # the card versions, written as the platform writes them
    t.psql(db, f"INSERT INTO project.system (pid, number, name) VALUES ('{v1}', 1, 'S'), ('{v2}', 2, 'S')",
           role="platform_rw")
    t.psql(other, f"INSERT INTO project.system (pid, number, name) VALUES ('{w1}', 1, 'T')", role="platform_rw")

    # the engine's tables in both databases, as its one-shot makes them. migrate_projects
    # (aisc_backend/deployment.py) only migrates a database per project in configurator mode.
    env = dict(os.environ, AISC_DEPLOYMENT="configurator",
               DB_ENGINE="django.db.backends.postgresql", DB_NAME="platform",
               DB_USER="engine_rw", DB_PASSWORD="engine_rw", DB_HOST="127.0.0.1",
               DB_PORT=str(t.port), DB_SCHEMA="engine", PYTHONPATH=SHARED_PYTHONPATH)
    subprocess.run([str(ROOT / "apps/backend/.venv/bin/python"), "manage.py", "migrate_projects"],
                   cwd=ROOT / "apps/backend", env=env, check=True, capture_output=True)
    for database, project, version in ((db, p, v1), (other, q, w1)):
        r = t.psql(database, ENGINE_SEED.format(project=project, version=version), role="engine_rw", check=False)
        if r.returncode != 0:
            ctx.problems.append(f"an evaluation stamped with a project.system pid in {database}: "
                                + r.stderr.strip().splitlines()[-1])
            return ctx

    # P's controls, with the controls migrations
    menv = dict(os.environ, DATABASE_URL=t.dsn("controls_rw", db) + "?schema=controls")
    subprocess.run([str(ROOT / "apps/controls/node_modules/.bin/prisma"), "migrate", "deploy"],
                   cwd=ROOT / "apps/controls", env=menv, check=True, capture_output=True)
    if not _has_column(t, db, "controls", "submission_answer", "system_version_number"):
        ctx.problems.append("controls.submission_answer.system_version_number (WP10 controls migration)")
        return ctx
    t.psql(db, f"""
        SET search_path = controls;
        INSERT INTO source (id, slug, name, updated_at) VALUES ('src', 'src', 'Source', now());
        INSERT INTO checklist (id, "catalogueId", title, "sourceId", "controlTopic", updated_at)
          VALUES ('cl', 'slug-1', 'Checklist', 'src', 'topic', now());
        INSERT INTO checklist_question (id, "checklistId", "order", text) VALUES ('q1', 'cl', 1, 'Question');
        INSERT INTO submission (id, "checklistId", label, updated_at) VALUES ('s1', 'cl', 'first', now());
        INSERT INTO submission_answer (id, "submissionId", "questionId", answer, score,
                                       system_version_pid, system_version_number, answered_at)
          VALUES ('a1', 's1', 'q1', 'yes', 3, '{v2}', 2, now());""", role="controls_rw")
    return ctx


@pytest.fixture(scope="module")
def ctx():
    c = _chain_ctx()
    if c is not None:
        yield c
        return
    try:
        c = _standalone()
    except BaseException:
        # a failed setup must not leave its container behind
        subprocess.run("docker ps -aq --filter name=aisc-t-dashq- | xargs -r docker rm -f",
                       shell=True, capture_output=True)
        raise
    try:
        yield c
    finally:
        c.t.stop()


def test_i19_3_the_engine_dataset_is_the_dashboards_own_sql():
    """The query here is the one the dashboard registers (aisc_ext.projects.engine_results_sql),
    whitespace aside."""
    sys.path.insert(0, str(DASHBOARD))
    from aisc_ext import projects

    assert " ".join(ENGINE_RESULTS_SQL.split()) == " ".join(projects.engine_results_sql().split())


def test_s12_1_engine_results_carry_the_version_of_the_evaluation(ctx):
    """The test result reads system_version = 1, in the project's database."""
    ctx.require()
    rows = ctx.t.rows(ctx.project_db, ENGINE_RESULTS_SQL, role="dashboard_ro")
    assert rows, "engine_results returned no rows for the project"
    assert {r["system_version"] for r in rows} == {1}


def test_s12_1_controls_answers_carry_the_version_they_were_answered_under(ctx):
    """The controls answer reads system_version_number = 2."""
    ctx.require()
    rows = ctx.t.rows(ctx.project_db, CONTROLS_ANSWERS_SQL, role="dashboard_ro")
    assert rows, "controls_answers returned no rows"
    assert {r["system_version_number"] for r in rows} == {2}


def test_s11_4_engine_results_never_return_another_projects_rows(ctx):
    """P's database returns no evaluation of Q's; each project's dataset reads its own database."""
    ctx.require()
    if ctx.other_db is None:
        pytest.skip("chain mode seeds one project only")
    mine = ctx.t.rows(ctx.project_db, ENGINE_RESULTS_SQL, role="dashboard_ro")
    theirs = ctx.t.rows(ctx.other_db, ENGINE_RESULTS_SQL, role="dashboard_ro")
    assert mine and theirs
    assert not {r["evaluation_pid"] for r in mine} & {r["evaluation_pid"] for r in theirs}
