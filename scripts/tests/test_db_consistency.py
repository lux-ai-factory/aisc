"""The database consistency check (scripts/verify-db-consistency.sh, scripts/db_consistency).

Run from the repo root:

    uv run --no-project --with pytest --with psycopg[binary] python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_db_consistency.py

Every database here is a throwaway postgres:15-alpine container, never the host's 5432. Since the
isolation (2026-09-25, 01-specs.md I16.6; rewritten by WP V1 under S-D13, the approved design moves every
module into the project's own database) the bed is scripts/tests/isolation_bed.py: three projects whose
databases are made by the platform's own provision and migrated by every module's own migrate command, so
each migration tracker exists for C7. It adds a fake `keycloak` and a minimal `superset` database. The seed
is clean, every check passes it. Each test then plants exactly one problem, asserts the check reports it,
and takes it out again.

What changed from the shared layout, case by case: C3, C4 and C6 read each project database against its own
project.system; "belongs to another project" is now "a pid of B's project.system planted in A's table does not
resolve here" (foreign keys make a real cross-project stamp impossible); C5 reads the composer's `*_by`
columns in the project databases; C7 checks every module's tracker; C8 lints the project schemas.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
import isolation_bed as ib  # noqa: E402
from throwaway import Throwaway  # noqa: E402

from db_consistency import checks, heads  # noqa: E402
from db_consistency.cluster import Cluster  # noqa: E402

A, B = ib.A, ib.B
E = "e0000000-0000-4000-8000-00000000000e"
A_V1 = "a1000000-0000-4000-8000-000000000001"
A_V2 = "a2000000-0000-4000-8000-000000000002"
B_V1 = "b1000000-0000-4000-8000-000000000001"
E_V1 = "e1000000-0000-4000-8000-000000000001"
DB_A, DB_B, DB_E = ib.project_db(A), ib.project_db(B), ib.project_db(E)

# Keycloak subjects of the seed (user_entity.id in realm aisc)
OLGA = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
ERIN = "33333333-3333-4333-8333-333333333333"
MASTER_ADMIN = "99999999-9999-4999-8999-999999999999"
UNKNOWN = "deadbeef-0000-4000-8000-00000000dead"

JSONLD = '{"@graph": [{"@id": "urn:aisc:system:alpha", "@type": "https://w3id.org/airo#AISystem"}]}'
LAYOUT = "10000000-0000-4000-8000-00000000000a"
REPORT = "20000000-0000-4000-8000-00000000000b"
ENGINE_PROJECT = "a0e00000-0000-4000-8000-000000000001"

SEED_PLATFORM = f"""
INSERT INTO core.project_member (project_id, subject, email, role) VALUES
  ('{A}', '{OLGA}', 'olga@localhost', 'owner'),
  ('{B}', '{BOB}', 'bob@localhost', 'editor'),
  ('{E}', '{ERIN}', 'erin@localhost', 'owner');
"""

SEED_A = f"""
SET session_replication_role = replica;
INSERT INTO project.system (pid, number, name, version, provider) VALUES
  ('{A_V1}', 1, 'Alpha scorer', '0.9', 'Acme AI'),
  ('{A_V2}', 2, 'Alpha scorer', '1.0', 'Acme AI');
INSERT INTO qualification.qualification
  (id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", updated_at, system_id)
  VALUES ('q-a1', 'Alpha scorer', '0.9', 'Acme AI', 'd', 'u', 'u', now(), '{A_V1}'),
         ('q-a2', 'Alpha scorer', '1.0', 'Acme AI', 'd', 'u', 'u', now(), '{A_V2}');
INSERT INTO qualification.knowledge_graph (id, "qualificationId", digest, turtle, jsonld, nodes, triples) VALUES
  ('kg-a2', 'q-a2', 'not-a-sha256-of-anything', '# turtle', '{JSONLD}', 1, 1);
INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, system_id) VALUES
  ('coa2', 'Alpha scorer 1.0', 'd', now(), now(), '{A_V2}');
INSERT INTO control_objectives.graph (project_id, jsonld, digest, risks, uploaded_at) VALUES
  ('coa2', '{JSONLD}', encode(sha256(convert_to('{JSONLD}', 'UTF8')), 'hex'), 0, now());
INSERT INTO engine.aisc_backend_project (id, pid, name, description, status, created_at, project_id) VALUES
  (1, '{ENGINE_PROJECT}', 'Alpha project', '', 'active', now(), '{A}');
INSERT INTO engine.aisc_backend_evaluation (id, pid, status, project_id, system_id, created_at) VALUES
  (1, 'a2e00000-0000-4000-8000-000000000021', 'done', 1, '{A_V2}', now()),
  (2, 'a0e00000-0000-4000-8000-000000000041', 'done', 1, NULL, now());
INSERT INTO report_composer.layout (id, system_id, name, created_by, updated_by) VALUES
  ('{LAYOUT}', '{A_V2}', 'Standard', '{OLGA}', '{OLGA}');
INSERT INTO report_composer.generated_report (id, layout_id, layout_revision, system_id, snapshot, status, created_by)
  VALUES ('{REPORT}', '{LAYOUT}', 1, '{A_V2}', '{{}}', 'done', '{OLGA}');
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, system_version_pid, system_version_number)
  VALUES ('a-1', 's', 'q-a-1', 'yes', '{A_V2}', 2), ('a-2', 's', 'q-a-2', 'yes', '{A_V1}', 1);
"""

SEED_B = f"""
SET session_replication_role = replica;
INSERT INTO project.system (pid, number, name, version, provider) VALUES ('{B_V1}', 1, 'Beta bot', NULL, NULL);
INSERT INTO qualification.qualification
  (id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", updated_at, system_id)
  VALUES ('q-b1', 'Beta bot', '', '', 'd', 'u', 'u', now(), '{B_V1}');
INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, system_id) VALUES
  ('cob1', 'Beta bot', 'd', now(), now(), '{B_V1}');
INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, system_version_pid, system_version_number)
  VALUES ('b-1', 's', 'q-b-1', 'yes', '{B_V1}', 1);
"""

SEED_E = f"""
SET session_replication_role = replica;
INSERT INTO project.system (pid, number, name, version, provider) VALUES ('{E_V1}', 1, 'Echo assistant', '1', 'Echo Labs');
INSERT INTO qualification.qualification
  (id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", updated_at, system_id)
  VALUES ('q-e1', 'Echo assistant', '1', 'Echo Labs', 'd', 'u', 'u', now(), '{E_V1}');
"""

SUPERSET = """
CREATE TABLE aisc_comment (id integer PRIMARY KEY, dashboard_id text, author_sub text, author_name text, body text,
                           created_at timestamp DEFAULT now());
CREATE TABLE aisc_review_request (id integer PRIMARY KEY, dashboard_id text, requested_by_sub text,
                                  requested_by_name text, message text, assignee_type text, assignee_user_sub text);
"""

SEED_SUPERSET = f"""
INSERT INTO aisc_comment (id, dashboard_id, author_sub, author_name, body) VALUES
  (1, 'd1', '{OLGA}', 'Olga', 'looks right');
INSERT INTO aisc_review_request
  (id, dashboard_id, requested_by_sub, requested_by_name, message, assignee_type, assignee_user_sub) VALUES
  (1, 'd1', '{OLGA}', 'Olga', 'please check', 'user', '{BOB}');
"""

KEYCLOAK = f"""
CREATE TABLE realm (id varchar(36) PRIMARY KEY, name varchar(255) UNIQUE);
CREATE TABLE user_entity (id varchar(36) PRIMARY KEY, realm_id varchar(255) NOT NULL,
                          username varchar(255), email varchar(255));
INSERT INTO realm VALUES ('r-master', 'master'), ('r-aisc', 'aisc');
INSERT INTO user_entity (id, realm_id, username) VALUES
  ('{OLGA}', 'r-aisc', 'olga'), ('{BOB}', 'r-aisc', 'bob'), ('{ERIN}', 'r-aisc', 'erin'),
  ('{MASTER_ADMIN}', 'r-master', 'admin');
"""

PRISMA = heads.controls()


def sql(b, db: str, text: str, role: str | None = None) -> None:
    r = b.psql(db, text, role=role, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"seed failed on {db}: {r.stderr[-2000:]}")


@pytest.fixture(scope="session")
def bed():
    b = ib.build("consist-old", projects=(A, B, E))
    try:
        b.require("templates", "project_system", "qualification", "control_objectives", "engine",
                  "report_composer", "controls")
        sql(b, "platform", SEED_PLATFORM)
        for db, seed in ((DB_A, SEED_A), (DB_B, SEED_B), (DB_E, SEED_E)):
            sql(b, db, seed)
        sql(b, "postgres", "CREATE DATABASE superset")
        sql(b, "superset", SUPERSET + SEED_SUPERSET)
        sql(b, "postgres", "CREATE DATABASE keycloak")
        sql(b, "keycloak", KEYCLOAK)
        yield b
    finally:
        b.stop()


@pytest.fixture(scope="session")
def cluster(bed):
    return Cluster(f"host=127.0.0.1 port={bed.port} user=aisc-postgres-user password={bed.t.password}")


@contextmanager
def planted(bed, db: str, plant: str, remove: str):
    """One problem, planted as the superuser (foreign keys off) and taken out afterwards."""
    sql(bed, db, "SET session_replication_role = replica;\n" + plant)
    try:
        yield
    finally:
        sql(bed, db, "SET session_replication_role = replica;\n" + remove)


def messages(findings, level=None):
    return [f.message for f in findings if level is None or f.level == level]


def only(findings, level, *needles):
    """Exactly one finding at `level`, and its message carries every needle."""
    hits = [f for f in findings if f.level == level and all(n in f.message for n in needles)]
    assert len(hits) == 1, f"wanted one {level} with {needles}, got: {[(f.level, f.message) for f in findings]}"
    return hits[0]


# ── the connection ────────────────────────────────────────────────────────────

def test_every_connection_is_read_only(cluster):
    with cluster.connect("platform") as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        with pytest.raises(Exception, match="read-only"):
            conn.execute("CREATE TABLE core.sneaky (x int)")


def test_the_clean_bed_passes_every_data_check(cluster):
    for check in checks.DATA_CHECKS:
        found = check.run(cluster)
        assert found == [], f"{check.id}: {[(f.level, f.message) for f in found]}"


# ── C1 orphan databases ──────────────────────────────────────────────────────

ORPHAN_HEX = "0123456789abcdef0123456789abcdef"


def test_c1_a_project_database_without_a_project(bed, cluster):
    with planted(bed, "postgres", f'CREATE DATABASE "project_{ORPHAN_HEX}"',
                 f'DROP DATABASE "project_{ORPHAN_HEX}"'):
        f = only(checks.c1_orphan_databases(cluster), "FAIL", f"project_{ORPHAN_HEX}")
        assert f.check == "C1"


def test_c1_a_project_without_its_database(bed, cluster):
    lost = "f0000000-0000-4000-8000-00000000000f"
    with planted(bed, "platform",
                 f"INSERT INTO core.project (pid, name, slug) VALUES ('{lost}', 'Lost', 'lost')",
                 f"DELETE FROM core.project WHERE pid = '{lost}'"):
        only(checks.c1_orphan_databases(cluster), "FAIL", lost, "lost")


# ── the script ───────────────────────────────────────────────────────────────

SCRIPT = ROOT / "scripts/verify-db-consistency.sh"


def run_script(bed):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST="127.0.0.1", PGPORT=str(bed.port), PGUSER="aisc-postgres-user",
               PGPASSWORD=bed.t.password, NO_COLOR="1")
    return subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)


def test_the_script_passes_a_clean_bed_and_fails_a_broken_one(bed):
    clean = run_script(bed)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "  PASS every project database belongs to a project" in clean.stdout
    assert "failed: 0" in clean.stdout
    assert bed.t.password not in clean.stdout + clean.stderr
    with planted(bed, "postgres", f'CREATE DATABASE "project_{ORPHAN_HEX}"',
                 f'DROP DATABASE "project_{ORPHAN_HEX}"'):
        broken = run_script(bed)
    assert broken.returncode != 0
    assert f"  FAIL C1 project_{ORPHAN_HEX} has no core.project row" in broken.stdout
    assert "failed: 0" not in broken.stdout


# ── C2 unknown databases and schemas ─────────────────────────────────────────

@pytest.mark.parametrize("name", ["aisc", "controls", "qualification", "control_objectives"])
def test_c2_a_leftover_standalone_database(bed, cluster, name):
    with planted(bed, "postgres", f'CREATE DATABASE "{name}"', f'DROP DATABASE "{name}"'):
        only(checks.c2_unknown_databases_and_schemas(cluster), "FAIL", f"database {name}", "leftover")


def test_c2_an_unknown_database(bed, cluster):
    with planted(bed, "postgres", 'CREATE DATABASE "scratch"', 'DROP DATABASE "scratch"'):
        f = only(checks.c2_unknown_databases_and_schemas(cluster), "FAIL", "database scratch")
        assert "leftover" not in f.message


def test_c2_an_unknown_schema_in_platform(bed, cluster):
    with planted(bed, "platform", "CREATE SCHEMA junk", "DROP SCHEMA junk"):
        only(checks.c2_unknown_databases_and_schemas(cluster), "FAIL", "schema junk", "platform")


@pytest.mark.parametrize("schema", ["engine", "qualification", "control_objectives", "report_composer"])
def test_c2_a_retired_module_schema_in_platform_is_a_warning(bed, cluster, schema):
    """I16.6 C2: a module schema left in platform after the cutover is retired, pending the stage-7 drop."""
    with planted(bed, "platform", f"CREATE SCHEMA {schema}", f"DROP SCHEMA {schema}"):
        found = checks.c2_unknown_databases_and_schemas(cluster)
    only(found, "WARN", f"schema {schema}", "retired", "stage-7")
    assert messages(found, "FAIL") == []


def test_c2_a_core_table_beyond_the_three_is_a_warning(bed, cluster):
    with planted(bed, "platform", "CREATE TABLE core.system (pid uuid)", "DROP TABLE core.system"):
        only(checks.c2_unknown_databases_and_schemas(cluster), "WARN", "core.system", "stage-7")


def test_c2_the_catalogue_is_never_flagged(bed, cluster):
    # the catalogue schema is in the bed already; a catalogue database of its own is not ours to judge
    with planted(bed, "postgres", 'CREATE DATABASE "catalogue_dev"', 'DROP DATABASE "catalogue_dev"'):
        assert checks.c2_unknown_databases_and_schemas(cluster) == []


# ── C3 system identity drift ─────────────────────────────────────────────────

@pytest.mark.parametrize("column, version_value, drifted", [
    ('"systemName"', "Alpha scorer", "Alpha scorer PRO"),
    ('"systemVersion"', "1.0", "1.0.1"),
    ("company", "Acme AI", "Acme Inc"),
])
def test_c3_the_card_says_something_else_than_its_version(bed, cluster, column, version_value, drifted):
    with planted(bed, DB_A,
                 f"UPDATE qualification.qualification SET {column} = '{drifted}' WHERE id = 'q-a2'",
                 f"UPDATE qualification.qualification SET {column} = '{version_value}' WHERE id = 'q-a2'"):
        only(checks.c3_system_identity(cluster), "FAIL", DB_A, A_V2, "qualification", drifted, version_value)


def test_c3_the_assessment_is_named_after_another_version(bed, cluster):
    with planted(bed, DB_A,
                 "UPDATE control_objectives.project SET name = 'Alpha scorer 0.9' WHERE id = 'coa2'",
                 "UPDATE control_objectives.project SET name = 'Alpha scorer 1.0' WHERE id = 'coa2'"):
        only(checks.c3_system_identity(cluster), "FAIL", DB_A, A_V2, "control_objectives", "Alpha scorer 0.9",
             "Alpha scorer 1.0")


def test_c3_a_version_less_system_is_named_without_one(bed, cluster):
    with planted(bed, DB_B,
                 "UPDATE control_objectives.project SET name = 'Beta bot ' WHERE id = 'cob1'",
                 "UPDATE control_objectives.project SET name = 'Beta bot' WHERE id = 'cob1'"):
        only(checks.c3_system_identity(cluster), "FAIL", DB_B, B_V1, "control_objectives")


# ── C4 references resolve ────────────────────────────────────────────────────

NOWHERE = "00000000-0000-4000-8000-00000000beef"
EP = "b0e00000-0000-4000-8000-0000000000e2"
C4_CASES = {
    "engine project with no platform project": (
        f"INSERT INTO engine.aisc_backend_project (id, pid, name, description, status, created_at, project_id)"
        f" VALUES (2, '{EP}', 'Standalone', '', 'active', now(), NULL)",
        "DELETE FROM engine.aisc_backend_project WHERE id = 2",
        "WARN", (DB_A, "engine.aisc_backend_project", EP, "no platform project")),
    "engine project of another project": (
        f"INSERT INTO engine.aisc_backend_project (id, pid, name, description, status, created_at, project_id)"
        f" VALUES (2, '{EP}', 'Ghost', '', 'active', now(), '{B}')",
        "DELETE FROM engine.aisc_backend_project WHERE id = 2",
        "FAIL", (DB_A, "engine.aisc_backend_project", EP, B)),
    "evaluation of a system that does not exist": (
        f"UPDATE engine.aisc_backend_evaluation SET system_id = '{NOWHERE}' WHERE id = 1",
        f"UPDATE engine.aisc_backend_evaluation SET system_id = '{A_V2}' WHERE id = 1",
        "FAIL", (DB_A, "engine.aisc_backend_evaluation", NOWHERE)),
    "evaluation stamped with a version of B": (
        f"UPDATE engine.aisc_backend_evaluation SET system_id = '{B_V1}' WHERE id = 1",
        f"UPDATE engine.aisc_backend_evaluation SET system_id = '{A_V2}' WHERE id = 1",
        "FAIL", (DB_A, "engine.aisc_backend_evaluation", B_V1, "not a project.system of this database")),
    "card of a system that does not exist": (
        f"UPDATE qualification.qualification SET system_id = '{NOWHERE}' WHERE id = 'q-a1'",
        f"UPDATE qualification.qualification SET system_id = '{A_V1}' WHERE id = 'q-a1'",
        "FAIL", (DB_A, "qualification.qualification", "q-a1", NOWHERE)),
    "card of a version of B": (
        f"UPDATE qualification.qualification SET system_id = '{B_V1}' WHERE id = 'q-a1'",
        f"UPDATE qualification.qualification SET system_id = '{A_V1}' WHERE id = 'q-a1'",
        "FAIL", (DB_A, "qualification.qualification", "q-a1", B_V1, "not a project.system of this database")),
    "assessment of a system that does not exist": (
        f"UPDATE control_objectives.project SET system_id = '{NOWHERE}' WHERE id = 'coa2'",
        f"UPDATE control_objectives.project SET system_id = '{A_V2}' WHERE id = 'coa2'",
        "FAIL", (DB_A, "control_objectives.project", "coa2", NOWHERE)),
    "assessment of a version of B": (
        f"UPDATE control_objectives.project SET system_id = '{B_V1}' WHERE id = 'coa2'",
        f"UPDATE control_objectives.project SET system_id = '{A_V2}' WHERE id = 'coa2'",
        "FAIL", (DB_A, "control_objectives.project", "coa2", B_V1)),
    "layout of a version of B": (
        f"UPDATE report_composer.layout SET system_id = '{B_V1}' WHERE id = '{LAYOUT}'",
        f"UPDATE report_composer.layout SET system_id = '{A_V2}' WHERE id = '{LAYOUT}'",
        "FAIL", (DB_A, "report_composer.layout", LAYOUT, B_V1)),
    "report of another version than its layout": (
        f"UPDATE report_composer.generated_report SET system_id = '{A_V1}' WHERE id = '{REPORT}'",
        f"UPDATE report_composer.generated_report SET system_id = '{A_V2}' WHERE id = '{REPORT}'",
        "FAIL", (DB_A, "report_composer.generated_report", REPORT, "layout")),
    "report of a layout that does not exist": (
        f"UPDATE report_composer.generated_report SET layout_id = '{NOWHERE}' WHERE id = '{REPORT}'",
        f"UPDATE report_composer.generated_report SET layout_id = '{LAYOUT}' WHERE id = '{REPORT}'",
        "FAIL", (DB_A, "report_composer.generated_report", REPORT, NOWHERE)),
    "report of a system that does not exist": (
        f"UPDATE report_composer.generated_report SET system_id = '{NOWHERE}' WHERE id = '{REPORT}'",
        f"UPDATE report_composer.generated_report SET system_id = '{A_V2}' WHERE id = '{REPORT}'",
        "FAIL", (DB_A, "report_composer.generated_report", REPORT, NOWHERE)),
    "answer stamped with a version of B": (
        f"UPDATE controls.submission_answer SET system_version_pid = '{B_V1}' WHERE id = 'a-2'",
        f"UPDATE controls.submission_answer SET system_version_pid = '{A_V1}' WHERE id = 'a-2'",
        "FAIL", (DB_A, "a-2", B_V1, "not a project.system of this database")),
    "answer stamped with a version that does not exist": (
        f"UPDATE controls.submission_answer SET system_version_pid = '{NOWHERE}' WHERE id = 'a-2'",
        f"UPDATE controls.submission_answer SET system_version_pid = '{A_V1}' WHERE id = 'a-2'",
        "FAIL", (DB_A, "a-2", NOWHERE)),
    "answer carrying another number than its version": (
        "UPDATE controls.submission_answer SET system_version_number = 2 WHERE id = 'a-2'",
        "UPDATE controls.submission_answer SET system_version_number = 1 WHERE id = 'a-2'",
        "FAIL", (DB_A, "a-2", "system_version_number", A_V1)),
    "card component that is no engine component": (
        f"INSERT INTO qualification.card_component (id, qualification_id, component_pid, airo_property, name,"
        f" component_type) VALUES ('cc-ghost', 'q-a2', '{NOWHERE}', 'hasModel', 'm', 'model')",
        "DELETE FROM qualification.card_component WHERE id = 'cc-ghost'",
        "FAIL", (DB_A, "card_component", "cc-ghost", NOWHERE)),
}


@pytest.mark.parametrize("case", list(C4_CASES))
def test_c4_a_reference_that_does_not_resolve(bed, cluster, case):
    plant, remove, level, needles = C4_CASES[case]
    with planted(bed, DB_A, plant, remove):
        f = only(checks.c4_references(cluster), level, *needles)
    found = checks.c4_references(cluster)
    assert found == [], found
    assert f.check == "C4"


# ── C5 users resolve ─────────────────────────────────────────────────────────

C5_CASES = {
    "member": ("platform",
               f"INSERT INTO core.project_member (project_id, subject, role) VALUES ('{E}', '{UNKNOWN}', 'viewer')",
               f"DELETE FROM core.project_member WHERE subject = '{UNKNOWN}'",
               "core.project_member.subject"),
    "a user of another realm": (
               "platform",
               f"INSERT INTO core.project_member (project_id, subject, role) VALUES ('{E}', '{MASTER_ADMIN}', 'viewer')",
               f"DELETE FROM core.project_member WHERE subject = '{MASTER_ADMIN}'",
               "core.project_member.subject"),
    "layout editor": (DB_A,
               f"UPDATE report_composer.layout SET updated_by = '{UNKNOWN}'",
               f"UPDATE report_composer.layout SET updated_by = '{OLGA}'",
               f"{DB_A} report_composer.layout.updated_by"),
    "report author": (DB_A,
               f"UPDATE report_composer.generated_report SET created_by = '{UNKNOWN}'",
               f"UPDATE report_composer.generated_report SET created_by = '{OLGA}'",
               f"{DB_A} report_composer.generated_report.created_by"),
    "comment author": ("superset",
               f"UPDATE aisc_comment SET author_sub = '{UNKNOWN}'",
               f"UPDATE aisc_comment SET author_sub = '{OLGA}'",
               "aisc_comment.author_sub"),
    "review assignee": ("superset",
               f"UPDATE aisc_review_request SET assignee_user_sub = '{UNKNOWN}'",
               f"UPDATE aisc_review_request SET assignee_user_sub = '{BOB}'",
               "aisc_review_request.assignee_user_sub"),
}


@pytest.mark.parametrize("case", list(C5_CASES))
def test_c5_a_subject_keycloak_does_not_know(bed, cluster, case):
    db, plant, remove, where = C5_CASES[case]
    sub = MASTER_ADMIN if "realm" in case else UNKNOWN
    with planted(bed, db, plant, remove):
        f = only(checks.c5_users(cluster), "WARN", sub, where, "realm aisc")
    assert f.check == "C5"
    assert checks.c5_users(cluster) == []


def test_c5_skips_when_keycloak_cannot_be_read(bed, cluster):
    from dataclasses import replace
    found = checks.c5_users(replace(cluster, keycloak_db="no_keycloak_here"))
    assert [f.level for f in found] == ["WARN"]
    assert "skipped" in found[0].message and "no_keycloak_here" in found[0].message


# ── C6 stale step-2 graph ────────────────────────────────────────────────────

def test_c6_the_card_was_rebuilt_after_the_assessment(bed, cluster):
    with planted(bed, DB_A,
                 "UPDATE qualification.knowledge_graph SET jsonld = jsonld || ' ' WHERE id = 'kg-a2'",
                 f"UPDATE qualification.knowledge_graph SET jsonld = '{JSONLD}' WHERE id = 'kg-a2'"):
        f = only(checks.c6_stale_graph(cluster), "WARN", DB_A, "coa2", A_V2, "by content")
    assert f.check == "C6"


def test_c6_the_card_has_no_stored_graph_to_compare(bed, cluster):
    with planted(bed, DB_A,
                 "UPDATE qualification.knowledge_graph SET \"qualificationId\" = 'q-none' WHERE id = 'kg-a2'",
                 "UPDATE qualification.knowledge_graph SET \"qualificationId\" = 'q-a2' WHERE id = 'kg-a2'"):
        only(checks.c6_stale_graph(cluster), "WARN", DB_A, "coa2", "no stored knowledge graph")


# ── C7 databases behind on migrations ────────────────────────────────────────

TEMPLATES = heads.templates()


def test_c7_a_template_file_not_applied(bed, cluster):
    last = TEMPLATES[-1]
    with planted(bed, DB_B, f"DELETE FROM provision.template_migration WHERE name = '{last}'",
                 f"INSERT INTO provision.template_migration (name) VALUES ('{last}')"):
        f = only(checks.c7_migrations(cluster), "FAIL", DB_B, "provision.template_migration", last)
    assert f.check == "C7"


def test_c7_a_controls_migration_not_applied(bed, cluster):
    last = PRISMA[-1]
    with planted(bed, DB_B, f"UPDATE controls._prisma_migrations SET migration_name = 'x' WHERE migration_name = '{last}'",
                 f"UPDATE controls._prisma_migrations SET migration_name = '{last}' WHERE migration_name = 'x'"):
        only(checks.c7_migrations(cluster), "FAIL", DB_B, "controls._prisma_migrations", last)


def test_c7_a_rolled_back_controls_migration_is_not_applied(bed, cluster):
    first = PRISMA[0]
    with planted(bed, DB_B, f"UPDATE controls._prisma_migrations SET rolled_back_at = now() WHERE migration_name = '{first}'",
                 f"UPDATE controls._prisma_migrations SET rolled_back_at = NULL WHERE migration_name = '{first}'"):
        only(checks.c7_migrations(cluster), "FAIL", DB_B, "controls._prisma_migrations", first)


@pytest.mark.parametrize("tracker,column,wanted", [
    ("qualification._prisma_migrations", "migration_name", heads.qualification),
    ("engine.django_migrations", "name", heads.engine),
    ("report_composer.schema_migration", "name", heads.report_composer),
])
def test_c7_a_module_migration_not_applied(bed, cluster, tracker, column, wanted):
    last = wanted()[-1]
    with planted(bed, DB_B, f"UPDATE {tracker} SET {column} = 'x' WHERE {column} = '{last}'",
                 f"UPDATE {tracker} SET {column} = '{last}' WHERE {column} = 'x'"):
        only(checks.c7_migrations(cluster), "FAIL", DB_B, tracker, last)


def test_c7_control_objectives_not_at_its_head(bed, cluster):
    head = heads.control_objectives()[0]
    with planted(bed, DB_B, "UPDATE control_objectives.alembic_version SET version_num = 'older'",
                 f"UPDATE control_objectives.alembic_version SET version_num = '{head}'"):
        found = checks.c7_migrations(cluster)
    only(found, "FAIL", DB_B, "control_objectives.alembic_version", "lacks", head)
    only(found, "FAIL", DB_B, "control_objectives.alembic_version", "older", "not at the head")


def test_c7_the_report_library_behind(bed, cluster):
    with planted(bed, "platform", "UPDATE report_library.schema_migration SET name = 'x'",
                 "UPDATE report_library.schema_migration SET name = '0001_presets.sql'"):
        only(checks.c7_migrations(cluster), "FAIL", "platform", "report_library.schema_migration", "0001_presets.sql")


def test_c7_a_project_database_never_provisioned(bed, cluster):
    db = f"project_{ORPHAN_HEX}"
    with planted(bed, "postgres", f'CREATE DATABASE "{db}"', f'DROP DATABASE "{db}"'):
        found = checks.c7_migrations(cluster)
        for tracker in heads.trackers():
            only(found, "FAIL", db, tracker.table, "missing")


# ── C8 naming and types lint ─────────────────────────────────────────────────

LINT_PROJECT_DB = f"project_{ORPHAN_HEX}"
LINT_PLATFORM = """
CREATE SCHEMA core; CREATE SCHEMA report_library; CREATE SCHEMA catalogue;
CREATE TABLE core.project (pid uuid, created_at timestamptz);
CREATE TABLE core.schema_migration (name text, "appliedAt" timestamp);
CREATE TABLE report_library.preset (id uuid, created_by text);
CREATE TABLE catalogue.tool ("toolName" text, created_at timestamp);
CREATE TABLE public.whatever ("camelCase" text);
"""
LINT_PROJECT = """
CREATE SCHEMA project; CREATE SCHEMA qualification; CREATE SCHEMA control_objectives;
CREATE SCHEMA report_composer; CREATE SCHEMA controls; CREATE SCHEMA engine; CREATE SCHEMA provision;
CREATE SCHEMA llm;
CREATE TABLE project.system (pid uuid, number integer, created_at timestamptz);
CREATE TABLE qualification.card (id text, answered_at timestamp(3) with time zone);
CREATE TABLE qualification._prisma_migrations (id text, started_at timestamp);
CREATE TABLE control_objectives.project (id text, created_at timestamptz);
CREATE TABLE control_objectives.alembic_version ("versionNum" text);
CREATE TABLE report_composer.layout (id uuid, created_by text);
CREATE TABLE controls.submission (id text, "order" integer, closed_at timestamptz);
CREATE TABLE controls._prisma_migrations (id text, "startedAt" timestamp);
CREATE TABLE engine.frozen ("camelCase" text, created_at timestamp);
CREATE TABLE provision.template_migration (name text, applied_at timestamp);
"""
LINT_SUPERSET = """
CREATE TABLE aisc_comment (id integer, author_sub text, created_at timestamptz);
CREATE TABLE ab_user (id integer, "changedOn" timestamp);
"""


@pytest.fixture(scope="module")
def lint():
    """A cluster of its own: C8 on schemas that are clean, on a second throwaway."""
    t = Throwaway.start("dbcheck-lint")
    try:
        for db in ("superset", LINT_PROJECT_DB):
            t.psql("postgres", f'CREATE DATABASE "{db}"')
        t.psql("platform", LINT_PLATFORM)
        t.psql("superset", LINT_SUPERSET)
        t.psql(LINT_PROJECT_DB, LINT_PROJECT)
        yield t, Cluster(f"host=127.0.0.1 port={t.port} user=aisc-postgres-user password={t.password}")
    finally:
        t.stop()


def test_c8_clean_schemas_and_what_is_excluded_report_nothing(lint):
    _, cl = lint
    assert checks.c8_naming(cl) == []


C8_CASES = {
    "camelCase in a project's qualification": (
        LINT_PROJECT_DB, 'ALTER TABLE qualification.card ADD COLUMN "systemName" text',
        'ALTER TABLE qualification.card DROP COLUMN "systemName"',
        (LINT_PROJECT_DB, "qualification.card", "systemName", "snake_case")),
    "no time zone in a project's report_composer": (
        LINT_PROJECT_DB, "ALTER TABLE report_composer.layout ADD COLUMN made timestamp",
        "ALTER TABLE report_composer.layout DROP COLUMN made",
        (LINT_PROJECT_DB, "report_composer.layout", "made", "timestamp without time zone")),
    "camelCase in a project's controls": (
        LINT_PROJECT_DB, 'ALTER TABLE controls.submission ADD COLUMN "questionId" text',
        'ALTER TABLE controls.submission DROP COLUMN "questionId"',
        (LINT_PROJECT_DB, "controls.submission", "questionId", "snake_case")),
    "camelCase in a project's project.system": (
        LINT_PROJECT_DB, 'ALTER TABLE project.system ADD COLUMN "createdBy" text',
        'ALTER TABLE project.system DROP COLUMN "createdBy"',
        (LINT_PROJECT_DB, "project.system", "createdBy", "snake_case")),
    "no time zone in the platform's report library": (
        "platform", "ALTER TABLE report_library.preset ADD COLUMN made timestamp",
        "ALTER TABLE report_library.preset DROP COLUMN made",
        ("platform", "report_library.preset", "made", "timestamp without time zone")),
    "no time zone in superset's aisc tables": (
        "superset", "ALTER TABLE aisc_comment ALTER created_at TYPE timestamp",
        "ALTER TABLE aisc_comment ALTER created_at TYPE timestamptz",
        ("superset", "aisc_comment", "created_at", "timestamp without time zone")),
}


@pytest.mark.parametrize("case", list(C8_CASES))
def test_c8_a_column_off_the_convention(lint, case):
    t, cl = lint
    db, plant, remove, needles = C8_CASES[case]
    t.psql(db, plant)
    try:
        f = only(checks.c8_naming(cl), "WARN", *needles)
    finally:
        t.psql(db, remove)
    assert f.check == "C8"


def test_c8_a_catalogue_named_column_is_not_ours(lint):
    t, cl = lint
    t.psql(LINT_PROJECT_DB, 'ALTER TABLE qualification.card ADD COLUMN "catalogueId" text')
    try:
        assert checks.c8_naming(cl) == []
    finally:
        t.psql(LINT_PROJECT_DB, 'ALTER TABLE qualification.card DROP COLUMN "catalogueId"')


def test_c8_on_the_real_schemas(cluster):
    found = checks.c8_naming(cluster)
    text = "\n".join(messages(found))
    assert all(f.level == "WARN" for f in found)
    assert '"systemName"' not in text and "systemName" in text   # qualification's camelCase
    assert f"{DB_A} qualification.qualification" in text
    assert "controls.submission_answer" in text and "submissionId" in text
    assert "aisc_comment" in text and "timestamp without time zone" in text
    assert "engine." not in text and "catalogue" not in text and "_prisma_migrations" not in text
