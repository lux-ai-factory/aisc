"""The Evidence map: step 4's links as a matrix of objectives and checks, with a note per link, a review by
someone other than the person who made the links, and each objective's coverage on the version shown.

What a link may be and how links are saved is in test_evidence.py; this file reuses its project, whose latest
card version (V2) selects O1 (REQ1) and O24 (REQ6), with LangBiTe (REQ1, REQ6) and checklist ck1 (REQ6).
"""
from __future__ import annotations

import pytest

from platform_service import catalogue as project_catalogue
from platform_service import evidence
from tests.conftest import needs_database
from tests.test_evidence import (ALICE, BOB, GOV, LB, V1, V2, VERA, _reader, _runs, _submission,  # noqa: F401
                                 catalogue, evidence_project, get, put, sql, tools)

pytestmark = needs_database
LB24 = {"objective_id": "O24", "kind": "test", "key": "aisc-plugin-langbite"}


def review(client, as_user, project, who=BOB, version=None):
    return client.post(f"/projects/{project['slug']}/evidence/review", json={"version": version},
                       headers=as_user(who))


def objective(body, oid):
    return next(o for o in body["objectives"] if o["id"] == oid)


# ── the tables ──────────────────────────────────────────────────────────────

def test_a_link_has_a_note_and_a_version_has_a_review_the_readers_read(evidence_project, dsn):
    pid = evidence_project["pid"]
    cols = sql(dsn, pid, "SELECT column_name FROM information_schema.columns"
                         " WHERE table_schema = 'evidence' AND table_name = 'review' ORDER BY ordinal_position")
    assert [c[0] for c in cols] == ["system_id", "reviewed_by", "reviewed_by_name", "reviewed_at"]
    assert sql(dsn, pid, "SELECT data_type FROM information_schema.columns WHERE table_schema = 'evidence'"
                         " AND table_name = 'link' AND column_name = 'note'") == [("text",)]
    rows = sql(dsn, pid, "SELECT r, has_table_privilege(r, 'evidence.review', 'SELECT'),"
                         " has_table_privilege(r, 'evidence.review', 'INSERT')"
                         " FROM unnest(array['report_ro', 'dashboard_ro', 'report_composer_rw']) r"
                         " WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)")
    assert rows and all(sel and not ins for _, sel, ins in rows)


# ── notes ───────────────────────────────────────────────────────────────────

def test_a_note_says_why_a_link_is_evidence(client, as_user, evidence_project):
    r = put(client, as_user, evidence_project, [{**LB, "note": "pass: no bias above 0.1"}])
    assert r.status_code == 200, r.text
    assert [(link["key"], link["note"]) for link in r.json()["links"]] == [("aisc-plugin-langbite",
                                                                            "pass: no bias above 0.1")]


def test_a_note_changes_and_the_link_keeps_who_made_it(client, as_user, evidence_project):
    put(client, as_user, evidence_project, [LB])
    r = put(client, as_user, evidence_project, [{**LB, "note": "a new reason"}], BOB)
    assert r.status_code == 200, r.text
    (link,) = r.json()["links"]
    assert (link["note"], link["created_by"]) == ("a new reason", ALICE)


def test_a_link_saved_without_a_note_has_none(client, as_user, evidence_project):
    assert put(client, as_user, evidence_project, [LB]).json()["links"][0]["note"] is None


def test_a_note_is_at_most_1000_characters(client, as_user, evidence_project):
    assert put(client, as_user, evidence_project, [{**LB, "note": "x" * 1001}]).status_code == 422
    assert put(client, as_user, evidence_project, [{**LB, "note": "x" * 1000}]).status_code == 200


# ── review ──────────────────────────────────────────────────────────────────

def test_someone_who_made_no_link_marks_the_map_reviewed(client, as_user, evidence_project):
    put(client, as_user, evidence_project, [LB])
    r = review(client, as_user, evidence_project)
    assert r.status_code == 200, r.text
    got = r.json()["review"]
    assert (got["reviewed_by"], got["reviewed_by_name"]) == (BOB, BOB) and got["reviewed_at"]
    assert get(client, as_user, evidence_project).json()["review"]["reviewed_by"] == BOB


def test_the_person_who_made_a_link_may_not_review_the_map(client, as_user, evidence_project):
    put(client, as_user, evidence_project, [LB])
    r = review(client, as_user, evidence_project, ALICE)
    assert r.status_code == 422 and "someone who made none of its links" in r.text, r.text
    assert get(client, as_user, evidence_project).json()["review"] is None


def test_a_viewer_may_not_review(client, as_user, evidence_project):
    put(client, as_user, evidence_project, [LB])
    assert review(client, as_user, evidence_project, VERA).status_code == 403


def test_an_empty_map_is_not_reviewed(client, as_user, evidence_project):
    r = review(client, as_user, evidence_project)
    assert r.status_code == 422 and "no links" in r.text, r.text


def test_an_older_version_is_not_reviewed(client, as_user, evidence_project):
    assert review(client, as_user, evidence_project, version=V1).status_code == 409


def test_the_review_is_recorded_in_the_activity_log(client, as_user, evidence_project, monkeypatch):
    from tests.ledger.test_ledger_outbox import SUPERUSER_DSN, as_superuser

    if not SUPERUSER_DSN:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    monkeypatch.setenv("LEDGER_MODE", "record")
    put(client, as_user, evidence_project, [LB])
    review(client, as_user, evidence_project)
    rows = as_superuser(evidence_project["pid"], "SELECT item_id, card_version::text FROM ledger.outbox"
                                                 " WHERE action = 'evidence.map.reviewed'")
    assert [tuple(r) for r in rows] == [(V2, V2)]


def test_the_page_says_whether_the_caller_may_review(client, as_user, evidence_project):
    assert get(client, as_user, evidence_project, BOB).json()["can_review"] is False      # nothing linked
    put(client, as_user, evidence_project, [LB])
    assert get(client, as_user, evidence_project, BOB).json()["can_review"] is True
    assert get(client, as_user, evidence_project, ALICE).json()["can_review"] is False    # made a link
    assert get(client, as_user, evidence_project, VERA).json()["can_review"] is False


@pytest.mark.parametrize("change", [
    [LB, GOV],                                        # a link added
    [],                                               # every link removed
    [{**LB, "note": "why"}],                          # a note
])
def test_a_change_to_the_map_clears_its_review(client, as_user, evidence_project, change):
    put(client, as_user, evidence_project, [LB])
    review(client, as_user, evidence_project)
    put(client, as_user, evidence_project, change)
    assert get(client, as_user, evidence_project).json()["review"] is None


def test_a_save_that_changes_nothing_keeps_the_review(client, as_user, evidence_project):
    put(client, as_user, evidence_project, [LB])
    review(client, as_user, evidence_project)
    put(client, as_user, evidence_project, [LB])
    assert get(client, as_user, evidence_project).json()["review"]["reviewed_by"] == BOB


# ── coverage ────────────────────────────────────────────────────────────────

def test_an_objective_nothing_covers_is_a_gap(client, as_user, evidence_project):
    body = put(client, as_user, evidence_project, [LB]).json()
    assert (objective(body, "O1")["linked"], objective(body, "O24")["linked"]) == (True, False)
    assert objective(body, "O24")["evidence"] == "not covered"
    assert body["coverage"] == {"objectives": 2, "linked": 1, "gaps": 1}


def test_a_linked_objective_has_no_evidence_until_its_checks_give_some(client, as_user, evidence_project):
    body = put(client, as_user, evidence_project, [LB]).json()
    assert objective(body, "O1")["evidence"] == "no evidence"


def test_a_finished_run_of_this_version_is_evidence(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    _runs(dsn, evidence_project["pid"], "aisc-plugin-langbite", V1, "Done")       # another version's run
    assert objective(get(client, as_user, evidence_project).json(), "O1")["evidence"] == "no evidence"
    _runs(dsn, evidence_project["pid"], "aisc-plugin-langbite", V2, "Done")
    assert objective(get(client, as_user, evidence_project).json(), "O1")["evidence"] == "evidence"


def test_a_failed_run_asks_for_attention(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    _runs(dsn, evidence_project["pid"], "aisc-plugin-langbite", V2, "Done", "Failed")
    assert objective(get(client, as_user, evidence_project).json(), "O1")["evidence"] == "attention"


@pytest.mark.parametrize("scores,status", [((4, 3), "evidence"), ((2, 3), "attention")])
def test_a_checklists_answers_are_evidence_and_a_mean_below_3_asks_for_attention(
        client, as_user, evidence_project, dsn, scores, status):
    put(client, as_user, evidence_project, [GOV])
    _submission(dsn, evidence_project["pid"], "s1", "ck1", 1, "draft", [(s, "") for s in scores])
    assert objective(get(client, as_user, evidence_project).json(), "O24")["evidence"] == status


def test_a_stale_link_covers_nothing(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    sql(dsn, evidence_project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = false"
                                      " WHERE package_name = 'aisc-plugin-langbite'")
    o1 = objective(get(client, as_user, evidence_project).json(), "O1")
    assert (o1["linked"], o1["evidence"]) == (False, "not covered")


# ── what each row says about its objective ──────────────────────────────────

def test_each_objective_names_its_risks_their_ratings_and_whether_it_is_a_priority(
        client, as_user, evidence_project, dsn):
    pid = evidence_project["pid"]
    sql(dsn, pid, "UPDATE control_objectives.objective_selection SET priority_ids = '{O24}' WHERE project_id = 'a2'")
    sql(dsn, pid, "INSERT INTO control_objectives.risk (id, project_id, risk_id, position, text, short_label,"
                  " rating_impact, rating_likelihood) VALUES (1, 'a2', 'R1', 0, 'Biased answers', 'Bias', 4, 3),"
                  " (2, 'a2', 'R2', 1, 'Nobody checks', '', NULL, 2), (3, 'a1', 'R1', 0, 'old', 'old', 1, 1)")
    sql(dsn, pid, "INSERT INTO control_objectives.mapped_objective (risk_row_id, objective_id) VALUES"
                  " (1, 'O1'), (1, 'O24'), (2, 'O24'), (3, 'O1')")
    body = get(client, as_user, evidence_project).json()
    assert [o["id"] for o in body["objectives"]] == ["O24", "O1"]                  # priority first
    assert (objective(body, "O24")["priority"], objective(body, "O1")["priority"]) == (True, False)
    assert objective(body, "O1")["risks"] == [{"id": "R1", "label": "Bias", "impact": 4, "likelihood": 3}]
    assert objective(body, "O24")["risks"] == [
        {"id": "R1", "label": "Bias", "impact": 4, "likelihood": 3},
        {"id": "R2", "label": "Nobody checks", "impact": None, "likelihood": 2}]


def test_each_objective_says_whether_it_expects_a_test_a_control_or_both(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project).json()
    assert (objective(body, "O1")["expects"], objective(body, "O24")["expects"]) == ("Control + Test", "Control")


# ── dimensions from the project's own catalogue ─────────────────────────────

def test_dimensions_come_from_the_projects_own_catalogue(client, as_user, evidence_project, monkeypatch):
    """A private catalogue gives a local test the dimensions its admin set: the map reads them, not the
    public catalogue's."""
    asked = []

    def own(pid, token, detailed, internal=False):
        asked.append((str(pid), bool(token), detailed))
        return [{"slug": "langbite", "package_name": "aisc-plugin-langbite",
                 "tags": [{"slug": "societal-environmental-wellbeing", "section": "dimension"}]},
                {"slug": "gov", "package_name": None,
                 "tags": [{"slug": "human-agency-oversight", "section": "dimension"}]}]

    monkeypatch.setattr(project_catalogue, "tools", own)
    body = get(client, as_user, evidence_project).json()
    assert asked == [(str(evidence_project["pid"]), True, True)]
    assert next(t for t in body["tests"] if t["key"] == "aisc-plugin-langbite")["dimensions"] == ["REQ6"]
    assert put(client, as_user, evidence_project, [LB]).status_code == 422           # O1 is REQ1
    assert put(client, as_user, evidence_project, [{**GOV, "objective_id": "O1"}]).status_code == 200


def test_a_project_without_a_catalogue_yet_reads_the_public_one(client, as_user, evidence_project, monkeypatch):
    def not_chosen(*args, **kwargs):
        raise project_catalogue.NotChosen("no catalogue yet")

    monkeypatch.setattr(project_catalogue, "tools", not_chosen)
    body = get(client, as_user, evidence_project).json()
    assert next(t for t in body["tests"] if t["key"] == "aisc-plugin-langbite")["dimensions"] == ["REQ1", "REQ6"]


def test_a_catalogue_that_does_not_answer_refuses_no_link_for_its_dimensions(
        client, as_user, evidence_project, monkeypatch):
    def down(*args, **kwargs):
        raise project_catalogue.PublicUnavailable("down")

    monkeypatch.setattr(project_catalogue, "tools", down)
    assert put(client, as_user, evidence_project, [{**GOV, "objective_id": "O1"}]).status_code == 200
