"""Who may see which database diagrams (2026-09-25).

Caddy asks GET /authz/schema with forward_auth before /inspect/schema/*, and passes
the path it was asked for in X-Forwarded-Uri. The diagrams show structure, never
rows, so they are open to project members: a member sees the landing page, the
shared platform's diagrams and their own project's; a project they are not in is
refused. Only an admin may force a new SchemaSpy run (?refresh=1), which is slow.
pgAdmin, which shows the data itself, stays behind /authz/admin.
"""
import pytest

from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-0000000000b0"
ADMIN = "00000000-0000-0000-0000-000000000adm"


@pytest.fixture
def project(client, as_user, unique):
    """A project Alice made, so Alice owns it and Bob is not in it."""
    response = client.post("/projects", json={"name": unique("schema")}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


def database_of(project) -> str:
    return "project_" + project["pid"].replace("-", "")


def ask(client, headers, uri):
    return client.get("/authz/schema", headers={**headers, "X-Forwarded-Uri": uri})


def test_a_stranger_is_asked_to_sign_in(client, project):
    assert client.get("/authz/schema", headers={"X-Forwarded-Uri": "/"}).status_code == 401


@pytest.mark.parametrize("uri", ["/", "", "/?project=x", "/platform/", "/platform/core/index.html",
                                 "/platform/core/tables/project.html"])
def test_any_signed_in_user_sees_the_landing_page_and_the_shared_platform(client, as_user, uri):
    assert ask(client, as_user(BOB), uri).status_code == 204


def test_a_member_sees_their_own_projects_diagrams(client, as_user, project):
    db = database_of(project)
    for uri in (f"/{db}", f"/{db}/", f"/{db}/controls/index.html", f"/{db}/llm/relationships.html"):
        assert ask(client, as_user(ALICE), uri).status_code == 204, uri


def test_someone_outside_the_project_is_refused_its_diagrams(client, as_user, project):
    db = database_of(project)
    for uri in (f"/{db}/", f"/{db}/controls/index.html"):
        assert ask(client, as_user(BOB), uri).status_code == 403, uri


def test_an_admin_sees_every_projects_diagrams(client, as_user, project):
    assert ask(client, as_user(ADMIN, ("admin",)), f"/{database_of(project)}/").status_code == 204


def test_a_database_that_is_no_project_is_refused(client, as_user):
    for uri in ("/project_" + "0" * 32 + "/", "/keycloak/", "/superset/", "/postgres/", "/../platform/"):
        assert ask(client, as_user(ADMIN, ("admin",)), uri).status_code == 403, uri


def test_the_prefix_caddy_may_leave_on_is_understood(client, as_user, project):
    db = database_of(project)
    assert ask(client, as_user(ALICE), f"/inspect/schema/{db}/").status_code == 204
    assert ask(client, as_user(BOB), f"/inspect/schema/{db}/").status_code == 403


def test_only_an_admin_may_force_a_new_run(client, as_user, project):
    db = database_of(project)
    assert ask(client, as_user(ALICE), f"/{db}/?refresh=1").status_code == 403
    assert ask(client, as_user(BOB), "/platform/?refresh=1").status_code == 403
    assert ask(client, as_user(ADMIN, ("admin",)), f"/{db}/?refresh=1").status_code == 204


def test_without_the_forwarded_uri_nothing_but_the_landing_page_is_assumed(client, as_user, project):
    assert client.get("/authz/schema", headers=as_user(BOB)).status_code == 204
