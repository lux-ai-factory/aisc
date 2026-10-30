"""Sign-in and rights on every route."""
import pytest

from conftest import IDS, error_code, new_layout, some_template

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

PROJECT_ROUTES = [
    ("get", "/api/p/alpha/systems"), ("get", "/api/p/alpha/layouts"),
    ("get", f"/api/p/alpha/choices?block_type=test_results&system_id={IDS['A_V2']}"),
    ("post", "/api/p/alpha/layouts"), ("get", "/p/alpha/"),
]


@pytest.mark.parametrize("method,path", PROJECT_ROUTES + [("get", "/api/p/alpha/templates")])
def test_no_sign_in_is_401(client, method, path):
    r = getattr(client, method)(path, headers={"Origin": "http://localhost"})
    assert r.status_code == 401
    if path.startswith("/api"):
        assert error_code(r) == "not_signed_in"


@pytest.mark.parametrize("method,path", PROJECT_ROUTES)
def test_a_stranger_gets_404(client, auth, method, path):
    # json= only for post (TestClient.get takes no json argument)
    extra = {"json": {"name": "x"}} if method == "post" else {}
    r = getattr(client, method)(path, headers=auth("bob"), **extra)
    assert r.status_code == 404


def test_an_unknown_project_is_the_same_404(client, auth):
    a = client.get("/api/p/alpha/layouts", headers=auth("bob"))
    b = client.get("/api/p/no-such-project/layouts", headers=auth("bob"))
    assert (a.status_code, a.json()) == (b.status_code, b.json())


def test_a_viewer_is_forbidden_to_edit(client, auth):
    r = client.post("/api/p/alpha/layouts", json={"name": "v"}, headers=auth("victor"))
    assert r.status_code == 403 and error_code(r) == "forbidden"
    lay = new_layout(client, auth)
    for method, path in (("put", f"/api/p/alpha/layouts/{lay['id']}"), ("delete", f"/api/p/alpha/layouts/{lay['id']}"),
                         ("post", f"/api/p/alpha/layouts/{lay['id']}/reports")):
        r = getattr(client, method)(path, headers=auth("victor"), **({"json": {}} if method != "delete" else {}))
        assert r.status_code == 403, (method, path)


def test_the_membership_lookup_failing_is_503(client, auth, monkeypatch):
    import psycopg

    def broken(*a, **k):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr("report_composer.db.connect", broken)
    assert client.get("/api/p/alpha/layouts", headers=auth("alice")).status_code == 503


def test_the_role_is_read_on_every_request(client, auth, bed):
    assert client.post("/api/p/alpha/layouts", json={"name": "a"}, headers=auth("victor")).status_code == 403
    bed.psql("platform", f"UPDATE core.project_member SET role = 'editor' WHERE project_id = '{IDS['A']}' AND subject = 'victor'")
    try:
        body = {"name": "b", "template_id": some_template(client, auth)}
        assert client.post("/api/p/alpha/layouts", json=body, headers=auth("victor")).status_code == 201
    finally:
        bed.psql("platform", f"UPDATE core.project_member SET role = 'viewer' WHERE project_id = '{IDS['A']}' AND subject = 'victor'")


def test_an_admin_is_owner_of_every_project(client, auth):
    admin = auth("root-admin", roles=("admin",))
    assert client.get("/api/p/beta/layouts", headers=admin).status_code == 200
    look = {"name": "Admin look", "font": "inter", "font_size_pt": 10,
            "primary_color": "#000fdf", "accent_color": "#ff007e"}
    template = client.post("/api/p/beta/templates", json=look, headers=admin)
    assert template.status_code == 201, template.text
    layout = {"name": "Admin layout", "template_id": template.json()["id"]}
    assert client.post("/api/p/beta/layouts", json=layout, headers=admin).status_code == 201


@pytest.mark.parametrize("origin", [None, "http://evil.example"])
def test_writes_need_the_same_origin(client, auth, origin):
    r = client.post("/api/p/alpha/layouts", json={"name": "o"}, headers=auth("alice", origin=origin))
    assert r.status_code == 403


def test_reads_need_no_origin(client, auth):
    assert client.get("/api/p/alpha/layouts", headers=auth("alice", origin=None)).status_code == 200
