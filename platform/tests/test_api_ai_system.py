"""The one AI system of a project, through the API and in the database.

What the rules in test_ai_system.py decide, the database has to hold: one
system per project, a frozen version that cannot be changed even by a query
that forgets to check, and a draft that stays the latest.
"""
import psycopg
import pytest

from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-0000000000b0"


@pytest.fixture
def project(client, as_user, unique):
    response = client.post("/projects", json={"name": unique("sys")}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def viewer(client, as_user, project):
    response = client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": BOB, "role": "viewer"},
        headers=as_user(ALICE),
    )
    assert response.status_code in (200, 201), response.text
    return BOB


def system_of(client, as_user, project, who=ALICE):
    return client.get(f"/projects/{project['slug']}/ai-system", headers=as_user(who))


def test_a_new_project_has_its_one_ai_system_as_a_draft_version_1(client, as_user, project):
    response = system_of(client, as_user, project)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [v["number"] for v in body["versions"]] == [1]
    assert body["current"]["number"] == 1
    assert body["current"]["frozen_at"] is None
    assert body["current"]["name"] == project["name"]


def test_editing_the_draft_changes_it_and_makes_no_new_version(client, as_user, project):
    response = client.patch(f"/projects/{project['slug']}/ai-system",
                            json={"provider": "LIST"}, headers=as_user(ALICE))
    assert response.status_code == 200, response.text
    assert response.json()["forked_from"] is None
    body = system_of(client, as_user, project).json()
    assert [v["number"] for v in body["versions"]] == [1]
    assert body["current"]["provider"] == "LIST"


def test_once_frozen_an_edit_makes_version_2_and_leaves_version_1_alone(client, as_user, project):
    v1 = system_of(client, as_user, project).json()["current"]
    frozen = client.post(f"/ai-system-versions/{v1['pid']}/freeze",
                         json={"reason": "evaluation"}, headers=as_user(ALICE))
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["frozen_at"] is not None

    edited = client.patch(f"/projects/{project['slug']}/ai-system",
                          json={"description": "second thoughts"}, headers=as_user(ALICE))
    assert edited.status_code == 200, edited.text
    assert edited.json()["forked_from"] == v1["pid"]

    body = system_of(client, as_user, project).json()
    assert [v["number"] for v in body["versions"]] == [2, 1]
    assert body["current"]["number"] == 2
    assert body["current"]["description"] == "second thoughts"
    old = client.get(f"/ai-system-versions/{v1['pid']}", headers=as_user(ALICE)).json()
    assert old["description"] == v1["description"]
    assert old["frozen_at"] is not None


def test_freezing_twice_keeps_the_first_moment(client, as_user, project):
    v1 = system_of(client, as_user, project).json()["current"]
    first = client.post(f"/ai-system-versions/{v1['pid']}/freeze",
                        json={"reason": "evaluation"}, headers=as_user(ALICE)).json()
    again = client.post(f"/ai-system-versions/{v1['pid']}/freeze",
                        json={"reason": "ai card"}, headers=as_user(ALICE)).json()
    assert again["frozen_at"] == first["frozen_at"]
    assert again["frozen_reason"] == "evaluation"


def test_asking_for_a_draft_gives_the_draft_or_makes_the_next_version(client, as_user, project):
    """What the engine calls before it changes a component."""
    v1 = system_of(client, as_user, project).json()["current"]
    same = client.post(f"/projects/{project['slug']}/ai-system/draft", headers=as_user(ALICE))
    assert same.status_code == 200, same.text
    assert same.json()["version"]["pid"] == v1["pid"]
    assert same.json()["forked_from"] is None

    client.post(f"/ai-system-versions/{v1['pid']}/freeze", json={"reason": "evaluation"},
                headers=as_user(ALICE))
    fork = client.post(f"/projects/{project['slug']}/ai-system/draft", headers=as_user(ALICE)).json()
    assert fork["version"]["number"] == 2
    assert fork["forked_from"] == v1["pid"]
    assert fork["version"]["name"] == v1["name"]


def test_a_viewer_reads_the_system_and_may_not_change_or_freeze_it(client, as_user, project, viewer):
    assert system_of(client, as_user, project, who=viewer).status_code == 200
    v1 = system_of(client, as_user, project).json()["current"]
    assert client.patch(f"/projects/{project['slug']}/ai-system", json={"provider": "x"},
                        headers=as_user(viewer)).status_code == 403
    assert client.post(f"/ai-system-versions/{v1['pid']}/freeze", json={"reason": "x"},
                       headers=as_user(viewer)).status_code == 403


def test_a_stranger_learns_nothing(client, as_user, project):
    assert system_of(client, as_user, project, who=BOB).status_code == 404
    v1 = system_of(client, as_user, project).json()["current"]
    assert client.get(f"/ai-system-versions/{v1['pid']}", headers=as_user(BOB)).status_code == 404


def test_a_project_cannot_have_a_second_ai_system(dsn, client, as_user, project):
    with psycopg.connect(dsn) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("insert into core.ai_system (project_id) values (%s)", (project["pid"],))


def test_the_database_refuses_to_change_a_frozen_version(dsn, client, as_user, project):
    v1 = system_of(client, as_user, project).json()["current"]
    client.post(f"/ai-system-versions/{v1['pid']}/freeze", json={"reason": "evaluation"},
                headers=as_user(ALICE))
    with psycopg.connect(dsn) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("update core.ai_system_version set description = 'sneaky' where pid = %s",
                     (v1["pid"],))


def test_there_is_never_more_than_one_draft(dsn, client, as_user, project):
    body = system_of(client, as_user, project).json()
    with psycopg.connect(dsn) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "insert into core.ai_system_version (ai_system_id, number, name)"
            " values (%s, 2, 'a second draft')",
            (body["pid"],),
        )
