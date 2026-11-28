"""A sign-off is given on fixed content: the content hash of a task's subject, computed in the project's
database by one function per held kind (work.content_hash), and the card state it was made on
(work.card_state). The hash moves when the content a person saves moves, and only then.

The card (describe_system, subject "card") is the latest stored card: the card of the latest version, at its
latest revision. A checklist submission (fill_checklist) is its answers. The risk register (rate_risks, the
card version as subject) is its ratings, comments, mappings and key ticks.
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg
import pytest

from tests import work_content as wc
from tests.conftest import needs_database, project_db

V1, V2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
APPS = Path(__file__).resolve().parents[2] / "apps"


@pytest.fixture
def content(project):
    if not wc.SUPERUSER:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    wc.make_tables(project)
    return project


def hash_of(dsn, project, kind, subject):
    with project_db(dsn, project) as conn:
        return conn.execute("select work.content_hash(%s, %s)", (kind, subject)).fetchone()[0]


@needs_database
def test_the_card_hash_moves_with_an_answer_of_the_latest_card_and_only_then(dsn, content):
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1)
    first = hash_of(dsn, content, "describe_system", "card")
    assert re.fullmatch(r"[0-9a-f]{64}", first), first
    assert hash_of(dsn, content, "describe_system", "card") == first
    wc.sql(content, "UPDATE qualification.qualification SET saved_by = 'who stored it is not content'")
    assert hash_of(dsn, content, "describe_system", "card") == first
    wc.sql(content, "UPDATE qualification.qualification_answer SET answer = 'Lending'")
    assert hash_of(dsn, content, "describe_system", "card") != first


@needs_database
@pytest.mark.parametrize("column,value", [
    ('"systemName"', "'Other name'"), ('"systemVersion"', "'2.0'"), ("company", "'Other Corp'"),
    ("description", "'Another description'"), ('"targetUseCase"', "'Lending'"), ('"targetUsers"', "'Banks'"),
    ('"intendedDeployers"', "'Branches'"), ("system_type", "'Recommender'"), ("purpose", "'Scoring'"),
    ("provider_term", "'Provider'"), ("deployer_term", "'Deployer'"), ('"targetSystemTags"', "'{vision}'"),
    ('"sectorTags"', "'{finance}'"), ('"marketFormTags"', "'{saas}'"), ('"localityTags"', "'{eu}'"),
])
def test_the_card_hash_moves_with_every_identification_field_the_card_page_shows(dsn, content, column, value):
    # an agreement stops counting when any field of the card changes, the Identification and use section too
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1)
    before = hash_of(dsn, content, "describe_system", "card")
    wc.sql(content, f"UPDATE qualification.qualification SET {column} = {value}")
    assert hash_of(dsn, content, "describe_system", "card") != before


@needs_database
def test_the_card_hash_is_the_latest_version_at_its_latest_revision(dsn, content):
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1, answers=(("annex-1", "q1", "Hiring"),))
    on_v1 = hash_of(dsn, content, "describe_system", "card")
    wc.card_version(content, V2, 2)
    wc.card(content, "c2", V2, answers=(("annex-1", "q1", "Lending"),))
    on_v2 = hash_of(dsn, content, "describe_system", "card")
    assert on_v2 != on_v1
    wc.card(content, "c2r2", V2, revision=2, answers=(("annex-1", "q1", "Hiring"),))
    assert hash_of(dsn, content, "describe_system", "card") == on_v1   # the same content as version 1's card


@needs_database
def test_the_card_hash_moves_with_a_correction_of_the_components(dsn, content):
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1)
    before = hash_of(dsn, content, "describe_system", "card")
    wc.sql(content, """UPDATE qualification.qualification SET "ontologyPatch" = '{"n1": {"label": "Model"}}'""")
    assert hash_of(dsn, content, "describe_system", "card") != before


@needs_database
def test_the_card_hash_moves_with_the_components_block_and_the_risk_block(dsn, content):
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1)
    before = hash_of(dsn, content, "describe_system", "card")
    wc.sql(content, "INSERT INTO qualification.qualification_component (qualification_id, position, key, name, kind)"
                    " VALUES ('c1', 0, gen_random_uuid(), 'Scorer', 'model')")
    with_component = hash_of(dsn, content, "describe_system", "card")
    assert with_component != before
    wc.sql(content, 'INSERT INTO qualification.qualification_risk ("qualificationId", position, risk, source,'
                    " consequence, affected) VALUES ('c1', 0, 'Bias', 'data', 'harm', 'applicants')")
    assert hash_of(dsn, content, "describe_system", "card") != with_component


@needs_database
def test_a_checklist_hash_is_its_answers(dsn, content):
    wc.sql(content, 'INSERT INTO controls.submission_answer ("submissionId", "questionId", answer, score) VALUES'
                    " ('s1', 'q1', 'yes', 4), ('s2', 'q1', 'no', 1)")
    first = hash_of(dsn, content, "fill_checklist", "s1")
    wc.sql(content, "UPDATE controls.submission_answer SET answered_at = now()")
    wc.sql(content, "UPDATE controls.submission_answer SET answer = 'maybe' WHERE \"submissionId\" = 's2'")
    assert hash_of(dsn, content, "fill_checklist", "s1") == first
    wc.sql(content, "UPDATE controls.submission_answer SET score = 5 WHERE \"submissionId\" = 's1'")
    after_score = hash_of(dsn, content, "fill_checklist", "s1")
    assert after_score != first
    wc.sql(content, "UPDATE controls.submission_answer SET answer = 'yes, always' WHERE \"submissionId\" = 's1'")
    assert hash_of(dsn, content, "fill_checklist", "s1") != after_score


@needs_database
def test_a_risk_register_hash_is_its_ratings_comments_mappings_and_key_ticks(dsn, content):
    wc.card_version(content, V1, 1)
    wc.card_version(content, V2, 2)
    wc.sql(content, "INSERT INTO control_objectives.project (id, system_id) VALUES ('a1', %s), ('a2', %s)", (V1, V2))
    wc.sql(content, "INSERT INTO control_objectives.risk (project_id, risk_id, rating_impact, rating_likelihood)"
                    " VALUES ('a1', 'R1', 3, 4), ('a2', 'R1', 1, 1)")
    seen = {hash_of(dsn, content, "rate_risks", V1)}
    wc.sql(content, "UPDATE control_objectives.risk SET rating_impact = 5 WHERE project_id = 'a2'")
    assert hash_of(dsn, content, "rate_risks", V1) in seen                      # another version's register
    for change in ("UPDATE control_objectives.risk SET rating_likelihood = 2 WHERE project_id = 'a1'",
                   "UPDATE control_objectives.risk SET severity_comment = 'checked' WHERE project_id = 'a1'",
                   "INSERT INTO control_objectives.mapped_objective (risk_row_id, objective_id)"
                   " SELECT id, 'O7' FROM control_objectives.risk WHERE project_id = 'a1'",
                   "INSERT INTO control_objectives.objective_key VALUES ('a1', 'O7', true)",
                   "UPDATE control_objectives.objective_key SET key = false"):
        wc.sql(content, change)
        now = hash_of(dsn, content, "rate_risks", V1)
        assert now not in seen, change
        seen.add(now)


@needs_database
def test_a_kind_without_a_hash_function_is_an_error(dsn, content):
    with pytest.raises(psycopg.Error):
        hash_of(dsn, content, "launch_run", "run-1")


@needs_database
def test_the_card_state_is_the_latest_version_and_its_revision(dsn, content):
    with project_db(dsn, content) as conn:
        assert conn.execute("select work.card_state()").fetchone()[0] is None
    wc.card_version(content, V1, 1)
    wc.card_version(content, V2, 2)
    wc.card(content, "c2", V2)
    wc.card(content, "c2r2", V2, revision=2)
    with project_db(dsn, content) as conn:
        assert conn.execute("select work.card_state()").fetchone()[0] == {"version": V2, "number": 2, "revision": 2}


def _granted_by_the_apps() -> set[str]:
    found = set()
    for path in [*APPS.glob("qualification/prisma/migrations/*/migration.sql"),
                 *APPS.glob("controls/prisma/migrations/*/migration.sql"),
                 *APPS.glob("control-objectives/alembic/versions/*.py")]:
        text = " ".join(path.read_text().split())
        found.update(re.findall(r"GRANT SELECT \([^)]*\) ON [\w.]+ TO platform_rw;", text))
    return found


def test_the_stand_in_grants_platform_rw_what_the_apps_migrations_grant():
    assert set(wc.GRANTS) <= _granted_by_the_apps(), set(wc.GRANTS) - _granted_by_the_apps()


@needs_database
def test_the_card_change_says_who_stored_the_latest_card_state_and_when(dsn, content):
    with project_db(dsn, content) as conn:
        assert conn.execute("select work.card_change()").fetchone()[0] is None
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1)
    wc.sql(content, "UPDATE qualification.qualification SET saved_by = 'Maria Rossi',"
                    " created_at = '2026-01-20T11:02:00Z' WHERE id = 'c1'")
    with project_db(dsn, content) as conn:
        assert conn.execute("select work.card_change()").fetchone()[0] == {
            "version": V1, "number": 1, "revision": 1, "by": "Maria Rossi", "at": "2026-01-20T11:02:00+00:00"}
    wc.card(content, "c1r2", V1, revision=2)
    wc.sql(content, "UPDATE qualification.qualification SET saved_by = 'Maria Rossi', amended_by = 'Luca Bianchi',"
                    " created_at = '2026-01-20T12:15:00Z' WHERE id = 'c1r2'")
    with project_db(dsn, content) as conn:
        changed = conn.execute("select work.card_change()").fetchone()[0]
    assert (changed["revision"], changed["by"], changed["at"]) == (2, "Luca Bianchi", "2026-01-20T12:15:00+00:00")


@needs_database
def test_every_module_reads_the_card_change(dsn, content):
    wc.card_version(content, V1, 1)
    wc.card(content, "c1", V1)
    for role in ("qualification_rw", "controls_rw", "control_objectives_rw", "platform_rw"):
        with project_db(dsn, content, role=role) as conn:
            assert conn.execute("select work.card_change()").fetchone()[0]["revision"] == 1, role
