"""The database consistency check (scripts/verify-db-consistency.sh, scripts/db_consistency).

Run from the repo root:

    uv run --no-project --with pytest --with psycopg[binary] python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_db_consistency.py

Every database here is a throwaway postgres:14-alpine container (scripts/lib/report_bed.py),
never the host's 5432. The bed is built once, with a clean seed that every check passes. Each
test then plants exactly one problem, asserts the check reports it, and takes it out again.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
import report_bed  # noqa: E402
from throwaway import Throwaway  # noqa: E402

from db_consistency import checks  # noqa: E402
from db_consistency.cluster import Cluster  # noqa: E402

IDS = report_bed.IDS
A, A_V1, A_V2 = IDS["A"], IDS["A_V1"], IDS["A_V2"]
B, B_V1 = IDS["B"], IDS["B_V1"]
E, E_V1 = IDS["E"], IDS["E_V1"]
DB_A = report_bed.project_db(A)
DB_B = report_bed.project_db(B)

# Keycloak subjects of the seed (user_entity.id in realm aisc)
OLGA = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
ERIN = "33333333-3333-4333-8333-333333333333"
MASTER_ADMIN = "99999999-9999-4999-8999-999999999999"
UNKNOWN = "deadbeef-0000-4000-8000-00000000dead"

JSONLD = '{"@graph": [{"@id": "urn:aisc:system:alpha", "@type": "https://w3id.org/airo#AISystem"}]}'
LAYOUT = "10000000-0000-4000-8000-00000000000a"
REPORT = "20000000-0000-4000-8000-00000000000b"

SEED_PLATFORM = f"""
SET session_replication_role = replica;
INSERT INTO core.project (pid, name, slug) VALUES
  ('{A}', 'Alpha project', 'alpha'), ('{B}', 'Beta project', 'beta'), ('{E}', 'Echo project', 'echo');
INSERT INTO core.system (pid, project_id, number, name, version, provider) VALUES
  ('{A_V1}', '{A}', 1, 'Alpha scorer', '0.9', 'Acme AI'),
  ('{A_V2}', '{A}', 2, 'Alpha scorer', '1.0', 'Acme AI'),
  ('{B_V1}', '{B}', 1, 'Beta bot', NULL, NULL),
  ('{E_V1}', '{E}', 1, 'Echo assistant', '1', 'Echo Labs');
INSERT INTO core.project_member (project_id, subject, email, role) VALUES
  ('{A}', '{OLGA}', 'olga@localhost', 'owner'),
  ('{B}', '{BOB}', 'bob@localhost', 'editor'),
  ('{E}', '{ERIN}', 'erin@localhost', 'owner');

INSERT INTO qualification.qualification
  (id, "systemName", "systemVersion", company, description, "targetUseCase", "targetUsers", updated_at,
   project_id, system_id) VALUES
  ('q-a1', 'Alpha scorer', '0.9', 'Acme AI', 'd', 'u', 'u', now(), '{A}', '{A_V1}'),
  ('q-a2', 'Alpha scorer', '1.0', 'Acme AI', 'd', 'u', 'u', now(), '{A}', '{A_V2}'),
  ('q-b1', 'Beta bot', '', '', 'd', 'u', 'u', now(), '{B}', '{B_V1}'),
  ('q-e1', 'Echo assistant', '1', 'Echo Labs', 'd', 'u', 'u', now(), '{E}', '{E_V1}');
INSERT INTO qualification.knowledge_graph (id, "qualificationId", digest, turtle, jsonld, nodes, triples) VALUES
  ('kg-a2', 'q-a2', 'not-a-sha256-of-anything', '# turtle', '{JSONLD}', 1, 1);

INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, project_id, system_id) VALUES
  ('coa2', 'Alpha scorer 1.0', 'd', now(), now(), '{A}', '{A_V2}'),
  ('cob1', 'Beta bot', 'd', now(), now(), '{B}', '{B_V1}');
INSERT INTO control_objectives.graph (project_id, jsonld, digest, risks, uploaded_at) VALUES
  ('coa2', '{JSONLD}', encode(sha256(convert_to('{JSONLD}', 'UTF8')), 'hex'), 0, now());

INSERT INTO engine.project (id, pid, name, description, status, created_at, project_id) VALUES
  (1, 'a0e00000-0000-4000-8000-000000000001', 'Alpha project', '', 'active', now(), '{A}');
INSERT INTO engine.evaluation (id, pid, status, project_id, system_id, created_at) VALUES
  (1, 'a2e00000-0000-4000-8000-000000000021', 'done', 1, '{A_V2}', now()),
  (2, 'a0e00000-0000-4000-8000-000000000041', 'done', 1, NULL, now());

INSERT INTO report_composer.layout (id, project_id, system_id, name, created_by, updated_by) VALUES
  ('{LAYOUT}', '{A}', '{A_V2}', 'Standard', '{OLGA}', '{OLGA}');
INSERT INTO report_composer.generated_report
  (id, layout_id, layout_revision, project_id, system_id, snapshot, status, created_by) VALUES
  ('{REPORT}', '{LAYOUT}', 1, '{A}', '{A_V2}', '{{}}', 'done', '{OLGA}');
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

PRISMA = sorted(p.name for p in (ROOT / "apps/controls/prisma/migrations").iterdir() if p.is_dir())


def seed_project_db(pid: str, answers: list[tuple[str, str]]) -> str:
    rows = ",\n  ".join(
        f"('m-{i}', 'x', now(), '{name}', now(), 1)" for i, name in enumerate(PRISMA))
    sql = ("SET session_replication_role = replica;\n"
           "INSERT INTO controls._prisma_migrations"
           " (id, checksum, finished_at, migration_name, started_at, applied_steps_count) VALUES\n  "
           + rows + ";\n")
    if answers:
        sql += ("INSERT INTO controls.submission_answer (id, \"submissionId\", \"questionId\", answer,"
                " system_version_pid) VALUES\n  "
                + ",\n  ".join(f"('{aid}', 's', 'q-{aid}', 'yes', '{sv}')" for aid, sv in answers) + ";\n")
    return sql


def sql(b, db: str, text: str, role: str | None = None) -> None:
    r = b.psql(db, text, role=role, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"seed failed on {db}: {r.stderr[-2000:]}")


@pytest.fixture(scope="session")
def bed():
    report_bed.check_dsn_env()
    b = report_bed.build("dbcheck", seed=False)
    try:
        for f in sorted((ROOT / "apps/report-composer/migrations").glob("*.sql")):
            sql(b, "platform", "SET search_path = report_composer, core;\n"
                   "CREATE TABLE IF NOT EXISTS report_composer.schema_migration (name text PRIMARY KEY,"
                   " applied_at timestamptz NOT NULL DEFAULT now());\n" + f.read_text()
                   + f"\n;\nINSERT INTO report_composer.schema_migration (name) VALUES ('{f.name}');",
                   role="report_composer_rw")
        sql(b, "platform", SEED_PLATFORM)
        sql(b, "superset", SEED_SUPERSET)
        sql(b, "postgres", "CREATE DATABASE keycloak")
        sql(b, "keycloak", KEYCLOAK)
        sql(b, DB_A, seed_project_db(A, [("a-1", A_V2), ("a-2", A_V1)]))
        sql(b, DB_B, seed_project_db(B, [("b-1", B_V1)]))
        sql(b, report_bed.project_db(E), seed_project_db(E, []))
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


def test_c2_the_catalogue_is_never_flagged(bed, cluster):
    # the catalogue schema is in the bed already; a catalogue database of its own is not ours to judge
    with planted(bed, "postgres", 'CREATE DATABASE "catalogue_dev"', 'DROP DATABASE "catalogue_dev"'):
        assert checks.c2_unknown_databases_and_schemas(cluster) == []


# ── C3 system identity drift ─────────────────────────────────────────────────

@pytest.mark.parametrize("column, core_value, drifted", [
    ('"systemName"', "Alpha scorer", "Alpha scorer PRO"),
    ('"systemVersion"', "1.0", "1.0.1"),
    ("company", "Acme AI", "Acme Inc"),
])
def test_c3_the_card_says_something_else_than_core(bed, cluster, column, core_value, drifted):
    with planted(bed, "platform",
                 f"UPDATE qualification.qualification SET {column} = '{drifted}' WHERE id = 'q-a2'",
                 f"UPDATE qualification.qualification SET {column} = '{core_value}' WHERE id = 'q-a2'"):
        only(checks.c3_system_identity(cluster), "FAIL", A_V2, "qualification", drifted, core_value)


def test_c3_the_assessment_is_named_after_another_version(bed, cluster):
    with planted(bed, "platform",
                 "UPDATE control_objectives.project SET name = 'Alpha scorer 0.9' WHERE id = 'coa2'",
                 "UPDATE control_objectives.project SET name = 'Alpha scorer 1.0' WHERE id = 'coa2'"):
        only(checks.c3_system_identity(cluster), "FAIL", A_V2, "control_objectives", "Alpha scorer 0.9",
             "Alpha scorer 1.0")


def test_c3_a_version_less_system_is_named_without_one(bed, cluster):
    with planted(bed, "platform",
                 "UPDATE control_objectives.project SET name = 'Beta bot ' WHERE id = 'cob1'",
                 "UPDATE control_objectives.project SET name = 'Beta bot' WHERE id = 'cob1'"):
        only(checks.c3_system_identity(cluster), "FAIL", B_V1, "control_objectives")
