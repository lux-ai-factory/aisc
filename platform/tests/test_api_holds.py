"""Taking, releasing, handing over and taking over a part, through the platform's API.

Any editor or owner takes a part nobody holds; the holder releases it or offers it to someone, who accepts or
declines; an owner takes a part over, or gives it to someone else, with a reason.
"""
from __future__ import annotations

import pytest

from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor
CAROL = "00000000-0000-0000-0000-0000000000c0"    # editor
VERA = "00000000-0000-0000-0000-0000000000f0"     # viewer


@pytest.fixture
def team(make_project, dsn):
    project = make_project(owner=ALICE, editors=(BOB, CAROL), viewers=(VERA,))
    with project_db(dsn, project) as conn:
        task = conn.execute("insert into work.task (kind, subject) values ('fill_checklist', 'submission-1')"
                            " returning id").fetchone()[0]
        conn.execute("insert into work.part (task, key, label) values (%s, 'governance', 'Governance')", (task,))
    return project


def part_url(project, action):
    return f"/projects/{project['slug']}/work/fill_checklist/submission-1/parts/governance/{action}"


def holder(client, as_user, project):
    got = client.get(f"/projects/{project['slug']}/work/fill_checklist/submission-1", headers=as_user(ALICE))
    assert got.status_code == 200, got.text
    return {p["key"]: p["holder_subject"] for p in got.json()["parts"]}["governance"]


def test_an_editor_takes_a_part_nobody_holds(client, as_user, team):
    taken = client.post(part_url(team, "take"), headers=as_user(BOB))
    assert taken.status_code == 200, taken.text
    assert holder(client, as_user, team) == BOB


def test_a_viewer_cannot_take_a_part(client, as_user, team):
    assert client.post(part_url(team, "take"), headers=as_user(VERA)).status_code == 403
    assert holder(client, as_user, team) is None


def test_taking_a_part_someone_holds_is_refused_and_says_who_holds_it(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    refused = client.post(part_url(team, "take"), headers=as_user(CAROL))
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "not_holder"
    assert holder(client, as_user, team) == BOB


def test_the_holder_releases_a_part(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    assert client.post(part_url(team, "release"), headers=as_user(BOB)).status_code == 200
    assert holder(client, as_user, team) is None


def test_someone_else_cannot_release_a_part(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    assert client.post(part_url(team, "release"), headers=as_user(CAROL)).status_code == 409
    assert holder(client, as_user, team) == BOB


def test_a_part_offered_and_accepted_changes_holder(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    offered = client.post(part_url(team, "offer"), json={"to": CAROL}, headers=as_user(BOB))
    assert offered.status_code == 200, offered.text
    assert holder(client, as_user, team) == BOB
    assert client.post(part_url(team, "accept"), headers=as_user(CAROL)).status_code == 200
    assert holder(client, as_user, team) == CAROL


def test_a_part_cannot_be_offered_to_a_viewer(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    assert client.post(part_url(team, "offer"), json={"to": VERA}, headers=as_user(BOB)).status_code == 422


def test_an_owner_takes_a_part_over_with_a_reason(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    over = client.post(part_url(team, "take-over"), json={"to": CAROL, "reason": "Bob is away until Monday"},
                       headers=as_user(ALICE))
    assert over.status_code == 200, over.text
    assert holder(client, as_user, team) == CAROL


def test_a_take_over_needs_a_reason(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    refused = client.post(part_url(team, "take-over"), json={"to": CAROL, "reason": " "}, headers=as_user(ALICE))
    assert refused.status_code == 422, refused.text
    assert holder(client, as_user, team) == BOB


def test_an_editor_cannot_take_a_part_over(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    refused = client.post(part_url(team, "take-over"), json={"to": CAROL, "reason": "faster"},
                          headers=as_user(CAROL))
    assert refused.status_code == 403
    assert holder(client, as_user, team) == BOB


def test_a_task_lists_its_parts_and_who_holds_them(client, as_user, team):
    client.post(part_url(team, "take"), headers=as_user(BOB))
    got = client.get(f"/projects/{team['slug']}/work/fill_checklist/submission-1", headers=as_user(VERA)).json()
    assert got["state"] == "open"
    assert [(p["key"], p["label"], p["holder_subject"]) for p in got["parts"]] == [("governance", "Governance", BOB)]
