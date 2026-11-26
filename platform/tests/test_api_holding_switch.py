"""Holding is switched on or off per project, by an owner. Off by default, so a project works as before."""
from __future__ import annotations

from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor


def switch(client, as_user, project, who, on):
    return client.put(f"/projects/{project['slug']}/work/holds", json={"on": on}, headers=as_user(who))


def holding(dsn, project):
    with project_db(dsn, project) as conn:
        row = conn.execute("select enabled from work.setting where name = 'holds'").fetchone()
    return bool(row and row[0])


def test_holding_is_off_in_a_new_project(make_project, dsn):
    assert holding(dsn, make_project()) is False


def test_an_owner_switches_holding_on_and_off(client, as_user, make_project, dsn):
    project = make_project(owner=ALICE)
    turned = switch(client, as_user, project, ALICE, True)
    assert turned.status_code == 200, turned.text
    assert turned.json() == {"on": True}
    assert holding(dsn, project) is True
    assert switch(client, as_user, project, ALICE, False).status_code == 200
    assert holding(dsn, project) is False


def test_an_editor_cannot_switch_holding(client, as_user, make_project, dsn):
    project = make_project(owner=ALICE, editors=(BOB,))
    assert switch(client, as_user, project, BOB, True).status_code == 403
    assert holding(dsn, project) is False


def test_the_switch_takes_a_yes_or_no_only(client, as_user, make_project, dsn):
    project = make_project(owner=ALICE)
    assert switch(client, as_user, project, ALICE, "yes").status_code == 422
    assert holding(dsn, project) is False


def test_a_task_says_whether_holding_is_on(client, as_user, make_project, dsn):
    project = make_project(owner=ALICE)
    with project_db(dsn, project) as conn:
        task = conn.execute("insert into work.task (kind, subject) values ('fill_checklist', 'submission-1')"
                            " returning id").fetchone()[0]
        conn.execute("insert into work.part (task, key, label) values (%s, 'governance', 'Governance')", (task,))
    switch(client, as_user, project, ALICE, True)
    got = client.get(f"/projects/{project['slug']}/work/fill_checklist/submission-1", headers=as_user(ALICE))
    assert got.status_code == 200, got.text
    assert got.json().get("holding") is True
