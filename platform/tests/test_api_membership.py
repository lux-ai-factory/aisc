"""A project belongs to the people in it.

Before this, every signed-in account could list, read and change every project
on the platform. These tests are the line: what a member sees, what a stranger
sees, and what each role may change.
"""
import pytest

from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-0000000000b0"
ADMIN = "00000000-0000-0000-0000-000000000adm"


@pytest.fixture
def project(client, as_user, unique):
    """A project Alice made, so Alice owns it."""
    name = unique("proj")
    response = client.post("/projects", json={"name": name}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


def test_making_a_project_makes_you_its_owner(client, as_user, project):
    response = client.get(f"/authz/projects/{project['slug']}", headers=as_user(ALICE))
    assert response.status_code == 200
    assert response.json()["role"] == "owner"


def test_a_stranger_does_not_see_it_in_the_list(client, as_user, project):
    slugs = [p["slug"] for p in client.get("/projects", headers=as_user(BOB)).json()]
    assert project["slug"] not in slugs


def test_the_owner_sees_it_in_the_list(client, as_user, project):
    slugs = [p["slug"] for p in client.get("/projects", headers=as_user(ALICE)).json()]
    assert project["slug"] in slugs


def test_a_stranger_gets_404_not_403(client, as_user, project):
    """403 would confirm the project exists, and its slug is its name. A
    stranger learns nothing, which is the same answer they would get for a
    project that does not exist."""
    assert client.get(f"/projects/{project['slug']}", headers=as_user(BOB)).status_code == 404


def test_no_token_is_401(client, project):
    assert client.get("/projects").status_code == 401
    assert client.get(f"/projects/{project['slug']}").status_code == 401


def test_an_admin_sees_every_project(client, as_user, project):
    """Somebody has to be able to find an orphaned project, and the realm
    already says who that is."""
    slugs = [p["slug"] for p in client.get("/projects", headers=as_user(ADMIN, ("admin",))).json()]
    assert project["slug"] in slugs
    assert client.get(f"/projects/{project['slug']}", headers=as_user(ADMIN, ("admin",))).status_code == 200


def test_an_owner_can_let_somebody_in(client, as_user, project):
    added = client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": BOB, "email": "bob@localhost", "role": "viewer"},
        headers=as_user(ALICE),
    )
    assert added.status_code == 201, added.text
    assert client.get(f"/projects/{project['slug']}", headers=as_user(BOB)).status_code == 200
    assert client.get(f"/authz/projects/{project['slug']}", headers=as_user(BOB)).json()["role"] == "viewer"


def test_a_viewer_cannot_let_anybody_else_in(client, as_user, project):
    client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": BOB, "role": "viewer"},
        headers=as_user(ALICE),
    )
    refused = client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": "someone-else", "role": "viewer"},
        headers=as_user(BOB),
    )
    assert refused.status_code == 403


def test_a_viewer_may_not_name_a_system_and_an_editor_may(client, as_user, project):
    """Naming the system under assessment is changing the work."""
    client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": BOB, "role": "viewer"},
        headers=as_user(ALICE),
    )
    refused = client.post(
        f"/projects/{project['slug']}/systems", json={"name": "MCAS"}, headers=as_user(BOB)
    )
    assert refused.status_code == 403

    client.put(
        f"/projects/{project['slug']}/members/{BOB}",
        json={"role": "editor"},
        headers=as_user(ALICE),
    )
    allowed = client.post(
        f"/projects/{project['slug']}/systems", json={"name": "MCAS"}, headers=as_user(BOB)
    )
    assert allowed.status_code == 201, allowed.text


def test_a_viewer_can_read_the_systems(client, as_user, project):
    client.post(
        f"/projects/{project['slug']}/systems", json={"name": "MCAS"}, headers=as_user(ALICE)
    )
    client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": BOB, "role": "viewer"},
        headers=as_user(ALICE),
    )
    response = client.get(f"/projects/{project['slug']}/systems", headers=as_user(BOB))
    assert response.status_code == 200
    assert [s["name"] for s in response.json()] == ["MCAS"]


def test_a_stranger_cannot_read_the_systems(client, as_user, project):
    assert client.get(f"/projects/{project['slug']}/systems", headers=as_user(BOB)).status_code == 404


def test_a_stranger_cannot_read_a_system_by_its_own_id(client, as_user, project):
    """The system's id is a back door into the project if nobody checks."""
    system = client.post(
        f"/projects/{project['slug']}/systems", json={"name": "MCAS"}, headers=as_user(ALICE)
    ).json()
    assert client.get(f"/systems/{system['pid']}", headers=as_user(BOB)).status_code == 404
    assert client.get(f"/systems/{system['pid']}", headers=as_user(ALICE)).status_code == 200


def test_the_last_owner_cannot_be_removed(client, as_user, project):
    """A project with nobody in it is a project nobody can fix."""
    refused = client.delete(f"/projects/{project['slug']}/members/{ALICE}", headers=as_user(ALICE))
    assert refused.status_code == 409


def test_an_owner_can_be_removed_once_there_is_another(client, as_user, project):
    client.post(
        f"/projects/{project['slug']}/members",
        json={"subject": BOB, "role": "owner"},
        headers=as_user(ALICE),
    )
    assert client.delete(f"/projects/{project['slug']}/members/{ALICE}", headers=as_user(BOB)).status_code == 204
    assert client.get(f"/projects/{project['slug']}", headers=as_user(ALICE)).status_code == 404


def test_the_members_are_readable_by_the_people_in_the_project(client, as_user, project):
    response = client.get(f"/projects/{project['slug']}/members", headers=as_user(ALICE))
    assert response.status_code == 200
    assert [m["subject"] for m in response.json()] == [ALICE]
    assert client.get(f"/projects/{project['slug']}/members", headers=as_user(BOB)).status_code == 404


def test_authz_says_no_role_for_a_stranger_rather_than_refusing(client, as_user, project):
    """This one endpoint answers for strangers too: it is what the other
    modules ask before deciding what to show, and "nothing" is an answer."""
    response = client.get(f"/authz/projects/{project['slug']}", headers=as_user(BOB))
    assert response.status_code == 200
    assert response.json() == {"role": None, "admin": False, "may_write": False}


def test_authz_tells_an_admin_it_is_an_admin(client, as_user, project):
    response = client.get(f"/authz/projects/{project['slug']}", headers=as_user(ADMIN, ("admin",)))
    assert response.json() == {"role": "owner", "admin": True, "may_write": True}


def test_health_needs_no_token(client):
    assert client.get("/health").status_code == 200
