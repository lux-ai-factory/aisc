"""A take-over is kept in the project's database with its reason (docs/specs/who-does-what.md, sections 2 and 7).

The owner's reason was only in the ledger event. Now the take-over is a row of work.take_over, written in the same
transaction as the take-over and never changed: the person who lost the part sees "Alice took over Governance from
you: reason" in My tasks until they put it away or the task's round moves on, and the report's "Who did what" block
lists it.
"""
from __future__ import annotations

import psycopg
import pytest

from tests import work_content as wc
from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor
CAROL = "00000000-0000-0000-0000-0000000000c0"    # editor
TASK = "/projects/{slug}/work/fill_checklist/s1"


@pytest.fixture
def team(make_project, client, as_user):
    if not wc.SUPERUSER:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    project = make_project(owner=ALICE, editors=(BOB, CAROL))
    wc.make_tables(project)
    wc.sql(project, 'INSERT INTO controls.submission_answer ("submissionId", "questionId", answer, score)'
                    " VALUES ('s1', 'q1', 'yes', 4)")
    assert client.put(f"/projects/{project['slug']}/work/holds", json={"on": True},
                      headers=as_user(ALICE)).status_code == 200
    return project


def save(dsn, project, who, part="governance", label="Governance"):
    with project_db(dsn, project, role="controls_rw") as conn:
        conn.execute("select work.claim_for_save(%s, %s, %s, %s, %s, %s)",
                     ("fill_checklist", "s1", part, label, who, who))


def take_over(client, as_user, project, to=None, reason="Bob is away until Monday", who=ALICE):
    body = {"reason": reason, **({"to": to} if to else {})}
    answer = client.post(TASK.format(slug=project["slug"]) + "/parts/governance/take-over", json=body,
                         headers=as_user(who))
    assert answer.status_code == 200, answer.text
    return answer.json()


def kept(dsn, project):
    with project_db(dsn, project) as conn:
        return conn.execute("select round, part, from_subject, to_subject, by_subject, reason from work.take_over"
                            " order by id").fetchall()


def taken_from_me(client, as_user, who, project):
    got = client.get("/work/mine", headers=as_user(who))
    assert got.status_code == 200, got.text
    return [row for row in got.json()["taken_from_me"] if row["project"] == project["slug"]]


def test_a_take_over_is_kept_with_its_reason(client, as_user, team, dsn):
    save(dsn, team, BOB)
    take_over(client, as_user, team, to=CAROL)
    assert kept(dsn, team) == [(1, "governance", BOB, CAROL, ALICE, "Bob is away until Monday")]


def test_a_kept_take_over_is_never_changed_or_removed(client, as_user, team, dsn):
    save(dsn, team, BOB)
    take_over(client, as_user, team)
    # the platform's role may only add one; even the superuser cannot change or remove it
    with project_db(dsn, team) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update work.take_over set reason = 'other'")
    for statement in ("update work.take_over set reason = 'other'", "delete from work.take_over"):
        with pytest.raises(psycopg.Error, match="never changed or removed"):
            wc.sql(team, statement)


def test_the_person_who_lost_the_part_is_told_in_my_tasks_with_the_reason(client, as_user, team, dsn):
    save(dsn, team, BOB)
    take_over(client, as_user, team)
    rows = taken_from_me(client, as_user, BOB, team)
    assert [(r["label"], r["by_name"], r["to_name"], r["reason"]) for r in rows] == [
        ("Governance", ALICE, ALICE, "Bob is away until Monday")]
    assert taken_from_me(client, as_user, ALICE, team) == [] and taken_from_me(client, as_user, CAROL, team) == []


def test_the_line_goes_once_the_former_holder_puts_it_away(client, as_user, team, dsn):
    save(dsn, team, BOB)
    take_over(client, as_user, team)
    line = taken_from_me(client, as_user, BOB, team)[0]
    url = f"/projects/{team['slug']}/work/take-overs/{line['id']}/dismiss"
    assert client.post(url, headers=as_user(CAROL)).status_code == 403, "only the person it was taken from"
    assert client.post(url, headers=as_user(BOB)).status_code == 200
    assert taken_from_me(client, as_user, BOB, team) == []
    assert len(kept(dsn, team)) == 1, "the take-over itself stays"


def test_the_line_goes_when_the_tasks_round_moves_on(client, as_user, team, dsn):
    save(dsn, team, BOB)
    take_over(client, as_user, team)
    save(dsn, team, ALICE)
    assert client.post(TASK.format(slug=team["slug"]) + "/submit", headers=as_user(ALICE)).status_code == 200
    assert taken_from_me(client, as_user, BOB, team) != [], "same round, done: still told"
    save(dsn, team, CAROL, "data", "Data")       # the next round
    assert taken_from_me(client, as_user, BOB, team) == []


def test_a_part_nobody_held_given_to_someone_tells_nobody(client, as_user, team, dsn):
    save(dsn, team, BOB)
    assert client.post(TASK.format(slug=team["slug"]) + "/parts/governance/release",
                       headers=as_user(BOB)).status_code == 200
    take_over(client, as_user, team, to=CAROL, reason="Carol knows the data")
    assert kept(dsn, team) == [(1, "governance", None, CAROL, ALICE, "Carol knows the data")]
    assert taken_from_me(client, as_user, BOB, team) == []


def test_the_report_reader_reads_the_take_overs_and_nothing_written(client, as_user, team, dsn):
    # report_ro reads work.take_over as it reads the sign-offs (template 0047, 0048)
    with project_db(dsn, team) as conn:
        assert conn.execute("select has_table_privilege('report_ro', 'work.take_over', 'select'),"
                            " has_table_privilege('report_ro', 'work.take_over', 'insert'),"
                            " has_table_privilege('report_ro', 'work.take_over_dismissed', 'select')"
                            ).fetchone() == (True, False, False)
