"""Step 8 of the pipeline chain: the two dashboard datasets of 03 WP11 (11a).

S12.1: a test result read through `engine_results_<hex>` carries the version that was the
latest when its evaluation started (v1), and a control answer read through
`controls_answers_<hex>` carries the version under which it was answered (v2).

Two modes.
- Inside scripts/test-pipeline-chain.sh ($CHAIN_JSON names the container and the ids the
  earlier steps wrote): only the queries run, on what the modules wrote.
- Standalone (`uv run --no-project --with pytest python -m pytest scripts/pipeline_chain`): a
  throwaway postgres:14-alpine is made, every migration at the working tree is applied, one
  project is seeded with v1 and v2, an evaluation stamped v1 and an answer stamped v2, and
  a second project whose rows must never appear (S11.4). The container is removed afterwards.

The queries run as dashboard_ro, as Superset's "AISC Results" and "AISC Controls <slug>"
connections do.

Column note: 03 11a writes `p.platform_project_id`; the engine's column (reference dump of
e34fca3) is `engine.project.project_id`, so the query uses that.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from throwaway import ROOT, SHARED_PYTHONPATH, SU, Throwaway, platform_migration

ENGINE_RESULTS_SQL = """
SELECT m.pid, m.score, m.unit, m.time, m.dimensions, met.name AS metric,
       e.pid AS evaluation_pid, e.created_at AS evaluated_at,
       s.pid AS system_version_pid, s.number AS system_version
  FROM engine.measurement m
  JOIN engine.observation o ON o.id = m.observation_id
  JOIN engine.evaluation e ON e.id = o.evaluation_id
  JOIN engine.project p ON p.id = e.project_id
  JOIN engine.metric met ON met.id = m.metric_id
  LEFT JOIN core.system s ON s.pid = e.system_id
 WHERE p.project_id = '{pid}'
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
    def __init__(self, t: Throwaway, project: str, project_db: str, other: str | None, owned: bool):
        self.t, self.project, self.project_db, self.other, self.owned = t, project, project_db, other, owned
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


def _standalone() -> Ctx:
    t = Throwaway.start("dashq")
    p, q = str(uuid.uuid4()), str(uuid.uuid4())
    v1, v2, w1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    db = "project_" + p.replace("-", "")
    ctx = Ctx(t, p, db, q, True)
    t.psql("postgres", (ROOT / "init/platform-db.sql").read_text())
    t.psql("platform", (ROOT / "init/project-databases.sql").read_text())
    for f in sorted((ROOT / "platform/migrations").glob("*.sql")):
        platform_migration(t, f)
    env = dict(os.environ, DB_ENGINE="django.db.backends.postgresql", DB_NAME="platform",
               DB_USER="engine_rw", DB_PASSWORD="engine_rw", DB_HOST="127.0.0.1",
               DB_PORT=str(t.port), DB_SCHEMA="engine", PYTHONPATH=SHARED_PYTHONPATH)
    subprocess.run([str(ROOT / "apps/backend/.venv/bin/python"), "manage.py", "migrate", "--noinput"],
                   cwd=ROOT / "apps/backend", env=env, check=True, capture_output=True)

    # platform: two projects; P has v1 and v2, Q has its own v1
    if not _has_column(t, "platform", "core", "system", "number"):
        ctx.problems.append("core.system.number (WP2, platform/migrations/0003_card_versions_in_core_system.sql)")
        return ctx
    t.psql("platform", f"""
        INSERT INTO core.project (pid, name, slug) VALUES ('{p}', 'P', 'p-{p[:8]}'), ('{q}', 'Q', 'q-{q[:8]}');
        INSERT INTO core.system (pid, project_id, name, number) VALUES
          ('{v1}', '{p}', 'S', 1), ('{v2}', '{p}', 'S', 2), ('{w1}', '{q}', 'T', 1);""", role="platform_rw")

    # engine: an evaluation of P stamped v1 with one measurement; one of Q stamped w1
    r = t.psql("platform", f"""
        SET search_path = engine;
        INSERT INTO project (pid, name, description, status, created_at, project_id) VALUES
          (gen_random_uuid(), 'P', '', 'active', now(), '{p}'), (gen_random_uuid(), 'Q', '', 'active', now(), '{q}');
        INSERT INTO metric (pid, name, description, type_spec, created_at) VALUES (gen_random_uuid(), 'accuracy', '', 'direct', now());
        INSERT INTO evaluation (pid, status, project_id, system_id, created_at)
          SELECT gen_random_uuid(), 'completed', id, CASE project_id WHEN '{p}' THEN '{v1}'::uuid ELSE '{w1}'::uuid END, now() FROM project;
        INSERT INTO observation (pid, name, description, observer, tool, evaluation_id, created_at)
          SELECT gen_random_uuid(), 'o', '', 'x', 'x', id, now() FROM evaluation;
        INSERT INTO measurement (pid, name, description, unit, time, score, uncertainty, metric_id, observation_id, created_at)
          SELECT gen_random_uuid(), 'm', '', '%', now(), 0.9, 0, (SELECT id FROM metric LIMIT 1), id, now() FROM observation;
        """, role="engine_rw", check=False)
    if r.returncode != 0:
        ctx.problems.append("an evaluation stamped with a core.system pid (WP1 0023 restores the FK to core.system): "
                            + r.stderr.strip().splitlines()[-1])

    # the project's database, as the platform provisions it, with the controls migrations
    t.psql("postgres", f'CREATE DATABASE "{db}"', role="platform_rw")
    for f in sorted((ROOT / "platform/project-template").glob("*.sql")):
        t.psql(db, f.read_text(), role="platform_rw")
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
        # a failed setup must not leave its container behind (S12.3)
        subprocess.run("docker ps -aq --filter name=aisc-t-dashq- | xargs -r docker rm -f",
                       shell=True, capture_output=True)
        raise
    try:
        yield c
    finally:
        c.t.stop()


def test_s12_1_engine_results_carry_the_version_of_the_evaluation(ctx):
    """S12.1 (and S11.1, engine half): the test result reads system_version = 1."""
    ctx.require()
    rows = ctx.t.rows("platform", ENGINE_RESULTS_SQL.format(pid=ctx.project), role="dashboard_ro")
    assert rows, "engine_results returned no rows for the project"
    assert {r["system_version"] for r in rows} == {1}


def test_s12_1_controls_answers_carry_the_version_they_were_answered_under(ctx):
    """S12.1 (and S11.1, controls half): the answer reads system_version_number = 2."""
    ctx.require()
    rows = ctx.t.rows(ctx.project_db, CONTROLS_ANSWERS_SQL, role="dashboard_ro")
    assert rows, "controls_answers returned no rows"
    assert {r["system_version_number"] for r in rows} == {2}


def test_s11_4_engine_results_never_return_another_projects_rows(ctx):
    """S11.4: the dataset of P returns no evaluation of another project."""
    ctx.require()
    if ctx.other is None:
        pytest.skip("chain mode seeds one project only")
    mine = ctx.t.rows("platform", ENGINE_RESULTS_SQL.format(pid=ctx.project), role="dashboard_ro")
    theirs = ctx.t.rows("platform", ENGINE_RESULTS_SQL.format(pid=ctx.other), role="dashboard_ro")
    assert mine and theirs
    assert not {r["evaluation_pid"] for r in mine} & {r["evaluation_pid"] for r in theirs}
