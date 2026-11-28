"""One name per person, everywhere the work pages show one: the display name the identity provider gives (the
token's `name`), else the user name, else the email (docs/specs/who-does-what.md, section 7).

A holder, a doer, a sign-off and a submit are named from the caller's token; the Give-to list names the members of
the project, whose display name the platform keeps from the last time each of them used it (a member who never
signed in is named by their email, else their subject).
"""
from __future__ import annotations

import pytest

from tests import work_content as wc
from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database

BOB = "00000000-0000-0000-0000-0000000000b0"      # editor
CAROL = "00000000-0000-0000-0000-0000000000c0"    # editor, never signed in
TASK = "/projects/{slug}/work/fill_checklist/s1"


@pytest.fixture
def team(make_project, client, as_user):
    if not wc.SUPERUSER:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    project = make_project(owner=ALICE, editors=(BOB, CAROL))
    wc.make_tables(project)
    assert client.put(f"/projects/{project['slug']}/work/holds", json={"on": True},
                      headers=as_user(ALICE)).status_code == 200
    return project


def test_a_part_taken_is_held_under_the_display_name(client, as_user, team, dsn):
    url = TASK.format(slug=team["slug"])
    with project_db(dsn, team, role="controls_rw") as conn:
        conn.execute("select work.claim_for_save('fill_checklist', 's1', 'governance', 'Governance', %s, %s)",
                     (BOB, BOB))
        conn.execute("select work.claim_for_save('fill_checklist', 's1', 'data', 'Data', %s, %s)", (BOB, BOB))
    assert client.post(url + "/parts/data/release", headers=as_user(BOB)).status_code == 200
    taken = client.post(url + "/parts/data/take", headers=as_user(ALICE, name="Alice Martin"))
    assert taken.status_code == 200, taken.text
    assert taken.json()["holder"] == "Alice Martin"


def test_the_user_name_names_a_person_without_a_display_name(client, as_user, team, dsn):
    from aisc_identity import display_name
    from aisc_identity.caller import Caller

    assert display_name(Caller(subject="s", email="anna@aisc.local", username="anna", roles=())) == "anna"
    assert display_name(Caller(subject="s", email="anna@aisc.local", username=None, roles=())) == "anna@aisc.local"
    assert display_name(Caller(subject="s", email=None, username=None, roles=(), name="Anna Rossi")) == "Anna Rossi"
    assert display_name(Caller(subject="s", email=None, username=None, roles=())) == "s"


def test_give_to_names_each_member_by_their_display_name(client, as_user, team, dsn):
    client.get(f"/projects/{team['slug']}/work", headers=as_user(BOB, name="Bob Rossi"))
    to = client.get(f"/projects/{team['slug']}/work", headers=as_user(ALICE, name="Alice Martin")).json()["give_to"]
    names = {m["subject"]: m["name"] for m in to}
    assert names[ALICE] == "Alice Martin" and names[BOB] == "Bob Rossi"
    assert names[CAROL] == CAROL, "never signed in, added with no email: their subject"


def test_a_part_given_to_someone_is_held_under_their_display_name(client, as_user, team, dsn):
    client.get(f"/projects/{team['slug']}/work", headers=as_user(BOB, name="Bob Rossi"))
    url = TASK.format(slug=team["slug"])
    with project_db(dsn, team, role="controls_rw") as conn:
        conn.execute("select work.claim_for_save('fill_checklist', 's1', 'governance', 'Governance', %s, %s)",
                     (CAROL, CAROL))
    given = client.post(url + "/parts/governance/take-over", json={"to": BOB, "reason": "Carol is away"},
                        headers=as_user(ALICE))
    assert given.status_code == 200, given.text
    with project_db(dsn, team) as conn:
        assert conn.execute("select holder_name from work.hold").fetchone()[0] == "Bob Rossi"
