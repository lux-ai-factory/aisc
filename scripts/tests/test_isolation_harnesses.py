"""Test harnesses, consistency checks and labels after isolation (01-specs.md I7.12, I11.3, I16.6, I18.7,
I19.2, I19.3).

Throwaway postgres:14-alpine only (scripts/tests/isolation_bed.py and scripts/lib/throwaway-pg.sh).

    uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_isolation_harnesses.py
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from contextlib import contextmanager

import pytest

import isolation_bed as ib
from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from db_consistency import checks  # noqa: E402
from db_consistency.cluster import Cluster  # noqa: E402

TPG = ROOT / "scripts/lib/throwaway-pg.sh"
GUARD = ROOT / "scripts/guard-frozen.sh"
CHAIN = ROOT / "scripts/test-pipeline-chain.sh"
DASHQ = ROOT / "scripts/pipeline_chain/test_dashboard_queries.py"
SERVER = ROOT / "inspector/schema-docs/server.py"
CHECKS = ROOT / "scripts/db_consistency/checks.py"
DB_A = ib.project_db(ib.A)


# ── I11.3 schema-docs labels ─────────────────────────────────────────────────


def _server():
    spec = importlib.util.spec_from_file_location("schema_docs_labels", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_i11_3_project_schemas_name_every_module():
    labels = _server().PROJECT_SCHEMAS
    for schema in ("project", "qualification", "control_objectives", "engine", "report_composer",
                   "controls", "llm", "provision"):
        assert schema in labels, f"I11.3: PROJECT_SCHEMAS lacks {schema}"


def test_i11_3_platform_schemas_are_the_shared_ones_only():
    labels = _server().PLATFORM_SCHEMAS
    # (forms are per project since the user's decision of 2026-09-25: no form library in platform)
    assert set(labels) == {"core", "catalogue", "report_library"}, f"I11.3: {sorted(labels)}"
    assert labels["core"][0] == "Projects and their members", f"I11.3: core label {labels['core'][0]!r}"


def test_i11_2_the_database_rule_is_unchanged():
    """I11.2: the regex stays ^(platform|project_[0-9a-f]{32})$."""
    assert _server().DATABASE.pattern == r"^(platform|project_[0-9a-f]{32})$"


# ── I19.2 harnesses ──────────────────────────────────────────────────────────


def test_i19_2_throwaway_pg_has_tpg_project_db():
    assert re.search(r"^tpg_project_db\s*\(\)", TPG.read_text(), re.M), "I19.2: throwaway-pg.sh lacks tpg_project_db"


def test_i19_2_tpg_project_db_makes_a_project_database_with_the_template():
    """I19.2: `tpg_project_db <pid>` creates project_<hex> and applies every template file, tracked."""
    assert re.search(r"^tpg_project_db\s*\(\)", TPG.read_text(), re.M), "I19.2: throwaway-pg.sh lacks tpg_project_db"
    pid = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
    script = f"""
set -e
. "{TPG}"
tpg_start iso-top-tpg
tpg_init_platform "{ROOT}"
tpg_project_db {pid}
tpg_su project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b -tA -c "SELECT string_agg(name, ',' ORDER BY name) FROM provision.template_migration"
"""
    r = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    templates = sorted(p.name for p in (ROOT / "platform/project-template").glob("*.sql"))
    assert r.stdout.strip().splitlines()[-1] == ",".join(templates)


def test_i19_2_n6_throwaway_rows_parse_a_single_row():
    """I19.2 (N6): Throwaway.rows parses psql tuples-only output; a query of one row returns one dict."""
    sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
    from throwaway import Throwaway
    t = Throwaway.start("iso-top-n6")
    try:
        assert t.rows("platform", "SELECT 1 AS x") == [{"x": 1}]
    finally:
        t.stop()


@pytest.mark.parametrize("path", [GUARD, CHAIN])
def test_i19_2_harnesses_target_project_databases(path):
    """I19.2: guard-frozen.sh and test-pipeline-chain.sh build module schemas in project databases."""
    text = path.read_text()
    assert "tpg_project_db" in text, f"I19.2: {path.name} does not make project databases with tpg_project_db"


def test_i7_12_guard_g1_compares_engine_definitions_in_a_project_database():
    """I7.12: G1 dumps the engine schema of a project database migrated by migrate_projects, not
    platform.engine."""
    text = GUARD.read_text()
    assert "migrate_projects" in text, "I7.12: guard-frozen.sh does not migrate the engine per project"
    assert not re.search(r"tpg_dump platform --schema-only --schema=engine > \"\$OUT/engine\.candidate\.sql\"", text), \
        "I7.12: G1 still dumps platform.engine as the candidate"


def test_i19_3_dashboard_queries_run_the_engine_dataset_on_a_project_database():
    """I19.3: the engine dataset SQL joins project.system, has no pid filter, and runs on the project
    database as dashboard_ro."""
    text = DASHQ.read_text()
    sql = text.split("ENGINE_RESULTS_SQL", 1)[1].split('"""', 2)[1]
    assert "project.system" in sql and "core.system" not in sql, "I19.3: engine dataset still joins core.system"
    assert "{pid}" not in sql, "I19.3: engine dataset still filters by pid"
    assert not re.search(r'rows\("platform", ENGINE_RESULTS_SQL', text), "I19.3: engine dataset still runs on platform"


# ── I16.6 db_consistency per project database ────────────────────────────────


def test_i16_6_checks_no_longer_read_core_system():
    code = "\n".join(l for l in CHECKS.read_text().splitlines() if not l.lstrip().startswith("#"))
    assert "core.system" not in code, "I16.6: db_consistency still reads core.system"


def test_i16_6_checks_cover_card_component_against_the_engine():
    code = CHECKS.read_text()
    assert "card_component" in code and "engine.ai_component" in code, \
        "I16.6: no check that card_component.component_pid exists in engine.ai_component"


@pytest.fixture(scope="module")
def bed():
    b = ib.build("consist")
    yield b
    b.stop()


@pytest.fixture(scope="module")
def cluster(bed):
    return Cluster(conninfo=bed.su_dsn("postgres"))


ALL = ("templates", "project_system", "qualification", "control_objectives", "engine", "report_composer", "controls")


@contextmanager
def planted(bed, db, sql, undo):
    r = bed.psql(db, sql)
    assert r.returncode == 0, r.stderr
    try:
        yield
    finally:
        bed.psql(db, undo)


def _findings(found, *needles):
    return [f for f in found if f.level == "FAIL" and all(n in f.message for n in needles)]


def test_i16_6_a_clean_isolated_bed_passes_every_data_check(bed, cluster):
    bed.require(*ALL)
    for check in checks.DATA_CHECKS:
        found = [f for f in check.run(cluster) if f.level == "FAIL"]
        assert found == [], f"I16.6 {check.id}: {[f.message for f in found]}"


@pytest.mark.parametrize("module,tracker,undo_col", [
    ("qualification", "qualification._prisma_migrations", "migration_name"),
    ("control_objectives", "control_objectives.alembic_version", "version_num"),
    ("engine", "engine.django_migrations", "name"),
    ("report_composer", "report_composer.schema_migration", "name"),
])
def test_i16_6_c7_every_module_tracker_is_checked(bed, cluster, module, tracker, undo_col):
    """I16.6 C7: a project database behind on any module's migrations is a FAIL naming that tracker."""
    bed.require(*ALL)
    backup = f"iso_backup_{module}"
    with planted(bed, DB_A, f"CREATE TABLE public.{backup} AS SELECT * FROM {tracker}; DELETE FROM {tracker}",
                 f"INSERT INTO {tracker} SELECT * FROM public.{backup}; DROP TABLE public.{backup}"):
        hits = _findings(checks.c7_migrations(cluster), DB_A, tracker.split(".")[1])
    assert hits, f"I16.6 C7: an emptied {tracker} was not reported"


def test_i16_6_c4_an_evaluation_stamp_that_does_not_resolve_in_the_same_database(bed, cluster):
    """I16.6 C4: engine.evaluation.system_id must be a project.system of the same database."""
    bed.require(*ALL)
    ghost = "deadbeef-0000-4000-8000-00000000beef"
    sql = f"""SET session_replication_role = replica;
      INSERT INTO engine.project (pid, name, description, status, created_at, project_id)
        VALUES ('{ghost}', 'ghost', '', 'active', now(), '{ib.A}');
      INSERT INTO engine.evaluation (pid, status, project_id, system_id, created_at)
        SELECT '{ghost}', 'completed', id, '{ghost}', now() FROM engine.project WHERE pid = '{ghost}';"""
    undo = f"""SET session_replication_role = replica; DELETE FROM engine.evaluation WHERE pid = '{ghost}';
      DELETE FROM engine.project WHERE pid = '{ghost}';"""
    with planted(bed, DB_A, sql, undo):
        hits = _findings(checks.c4_references(cluster), DB_A, ghost)
    assert hits, "I16.6 C4: an evaluation stamped with a version absent from project.system was not reported"


def test_i16_6_c8_lints_the_project_schemas(bed, cluster):
    """I16.6 C8: the lint covers qualification, control_objectives, report_composer and project in project
    databases (engine frozen, excluded)."""
    bed.require(*ALL)
    with planted(bed, DB_A, "CREATE TABLE qualification.\"BadName\" (\"camelCol\" int)",
                 "DROP TABLE qualification.\"BadName\""):
        found = checks.c8_naming(cluster)
    assert [f for f in found if DB_A in f.message and "camelCol" in f.message], "I16.6 C8: project schema not linted"


SYS = "5a5a5a5a-0000-4000-8000-00000000005a"
PLANT_SYSTEM = (f"INSERT INTO project.system (pid, number, name, version, provider) "
                f"VALUES ('{SYS}', 77, 'Alpha', '1', 'Acme');")
UNPLANT_SYSTEM = f"DELETE FROM project.system WHERE pid = '{SYS}';"


def _any(found, *needles):
    return [f for f in found if all(n in f.message for n in needles)]


def test_i16_6_c3_a_card_named_unlike_its_version_in_the_same_database(bed, cluster):
    """I16.6 C3: qualification.qualification joins project.system of the same database (no core.system);
    a card whose systemName differs from its version's name is a FAIL naming the database and the card."""
    bed.require(*ALL)
    sql = f"""SET session_replication_role = replica; {PLANT_SYSTEM}
      INSERT INTO qualification.qualification (id, "systemName", "systemVersion", company, description,
             "targetUseCase", "targetUsers", updated_at, system_id)
      VALUES ('iso-c3-card', 'Beta', '1', 'Acme', '', '', '', now(), '{SYS}');"""
    undo = f"""SET session_replication_role = replica; DELETE FROM qualification.qualification WHERE id = 'iso-c3-card';
      {UNPLANT_SYSTEM}"""
    with planted(bed, DB_A, sql, undo):
        hits = _findings(checks.c3_system_identity(cluster), DB_A, "iso-c3-card")
    assert hits, "I16.6 C3: a card named unlike its project.system version was not reported in its database"


def test_i16_6_c4_a_controls_answer_naming_a_version_absent_from_its_database(bed, cluster):
    """I16.6 C4 (paired stamps): controls.submission_answer.system_version_pid must be a project.system row of
    the same database (no core.system lookup)."""
    bed.require(*ALL)
    ghost = "6b6b6b6b-0000-4000-8000-00000000006b"
    sql = f"""SET session_replication_role = replica;
      INSERT INTO controls.submission_answer (id, "submissionId", "questionId", system_version_pid)
      VALUES ('iso-c4-answer', 'nosub', 'noq', '{ghost}');"""
    undo = "SET session_replication_role = replica; DELETE FROM controls.submission_answer WHERE id = 'iso-c4-answer';"
    with planted(bed, DB_A, sql, undo):
        hits = _findings(checks.c4_references(cluster), DB_A, "iso-c4-answer")
    assert hits, "I16.6 C4: an answer stamped with a version absent from project.system was not reported"


def test_i16_6_card_component_must_name_an_engine_component_of_the_same_database(bed, cluster):
    """I16.6: qualification.card_component.component_pid exists in engine.ai_component of the same database."""
    bed.require(*ALL)
    ghost = "7c7c7c7c-0000-4000-8000-00000000007c"
    sql = f"""SET session_replication_role = replica;
      INSERT INTO qualification.card_component (id, qualification_id, component_pid, airo_property, name, component_type)
      VALUES ('iso-cc', 'nocard', '{ghost}', 'hasModel', 'm', 'model');"""
    undo = "SET session_replication_role = replica; DELETE FROM qualification.card_component WHERE id = 'iso-cc';"
    found = []
    with planted(bed, DB_A, sql, undo):
        for check in checks.DATA_CHECKS:
            found += check.run(cluster)
    assert _any(found, DB_A, ghost), "I16.6: a card_component naming no engine.ai_component was not reported"


def test_i16_6_c6_a_stale_graph_is_reported_in_its_project_database(bed, cluster):
    """I16.6 C6: the graph digest check runs per project database (control_objectives.graph against
    qualification.knowledge_graph of the same database) and names the database."""
    bed.require(*ALL)
    sql = f"""SET session_replication_role = replica; {PLANT_SYSTEM}
      INSERT INTO qualification.qualification (id, "systemName", "systemVersion", company, description,
             "targetUseCase", "targetUsers", updated_at, system_id)
      VALUES ('iso-c6-card', 'Alpha', '1', 'Acme', '', '', '', now(), '{SYS}');
      INSERT INTO qualification.knowledge_graph (id, "qualificationId", digest, turtle, jsonld, nodes, triples)
      VALUES ('iso-c6-kg', 'iso-c6-card', 'd', '', '{{"now": 2}}', 1, 1);
      INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, system_id)
      VALUES ('isoc6assessment', 'Alpha 1', 'x', now(), now(), '{SYS}');
      INSERT INTO control_objectives.graph (project_id, jsonld, digest, risks, uploaded_at)
      VALUES ('isoc6assessment', '{{"then": 1}}', 'x', 0, now());"""
    undo = f"""SET session_replication_role = replica;
      DELETE FROM control_objectives.graph WHERE project_id = 'isoc6assessment';
      DELETE FROM control_objectives.project WHERE id = 'isoc6assessment';
      DELETE FROM qualification.knowledge_graph WHERE id = 'iso-c6-kg';
      DELETE FROM qualification.qualification WHERE id = 'iso-c6-card'; {UNPLANT_SYSTEM}"""
    with planted(bed, DB_A, sql, undo):
        hits = _any(checks.c6_stale_graph(cluster), DB_A, "isoc6assessment")
    assert hits, "I16.6 C6: a stale graph in a project database was not reported naming that database"


# ── I18.7 no new script prints a secret ──────────────────────────────────────


def test_i18_7_isolation_scripts_print_no_secret():
    paths = sorted((ROOT / "scripts/isolation").glob("*.sh")) + [ROOT / "scripts/verify-project-databases.sh"]
    missing = [p.name for p in paths if not p.exists()]
    assert not missing and len(paths) >= 3, f"I18.7: scripts to scan are missing: {missing or 'scripts/isolation/*.sh'}"
    for p in paths:
        for line in p.read_text().splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert not re.search(r"set -[a-z]*x", line), f"I18.7: {p.name} traces commands"
            if re.search(r"\b(echo|printf)\b", line):
                assert not re.search(r"\$\{?(\w*PASSWORD|\w*TOKEN|\w*SECRET|\w*_KEY)\b", line), \
                    f"I18.7: {p.name} prints a secret: {line.strip()[:80]}"
