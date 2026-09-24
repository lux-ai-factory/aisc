"""Sign-in and rights on every route (report run 2026-09-23: R4.4.1 to R4.4.6, R4.3.1, R7.3.1)."""
import pytest

from conftest import IDS, error_code, need, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

PROJECT_ROUTES = [
    ("get", "/api/p/alpha/systems"), ("get", "/api/p/alpha/layouts"),
    ("get", f"/api/p/alpha/choices?block_type=test_results&system_id={IDS['A_V2']}"),
    ("post", "/api/p/alpha/layouts"), ("get", "/p/alpha/"),
]


# R4.4.1, R4.3.1
@pytest.mark.parametrize("method,path", PROJECT_ROUTES + [("get", "/api/block-types"), ("get", "/api/templates")])
def test_r4_4_1_no_sign_in_is_401(client, method, path):
    r = getattr(client, method)(path, headers={"Origin": "http://localhost"})
    assert r.status_code == 401
    if path.startswith("/api"):
        assert error_code(r) == "not_signed_in"


# R4.4.3
@pytest.mark.parametrize("method,path", PROJECT_ROUTES)
def test_r4_4_3_a_stranger_gets_404(client, auth, method, path):
    r = getattr(client, method)(path, headers=auth("bob"), json={"name": "x"} if method == "post" else None)
    assert r.status_code == 404


def test_r4_4_3_an_unknown_project_is_the_same_404(client, auth):
    a = client.get("/api/p/alpha/layouts", headers=auth("bob"))
    b = client.get("/api/p/no-such-project/layouts", headers=auth("bob"))
    assert (a.status_code, a.json()) == (b.status_code, b.json())


# R4.4.4
def test_r4_4_4_a_viewer_is_forbidden_to_edit(client, auth):
    r = client.post("/api/p/alpha/layouts", json={"name": "v"}, headers=auth("victor"))
    assert r.status_code == 403 and error_code(r) == "forbidden"
    lay = new_layout(client, auth)
    for method, path in (("put", f"/api/p/alpha/layouts/{lay['id']}"), ("delete", f"/api/p/alpha/layouts/{lay['id']}"),
                         ("post", f"/api/p/alpha/layouts/{lay['id']}/reports")):
        r = getattr(client, method)(path, headers=auth("victor"), **({"json": {}} if method != "delete" else {}))
        assert r.status_code == 403, (method, path)


def test_r4_4_4_the_membership_lookup_failing_is_503(client, auth, monkeypatch):
    import importlib

    need("report_composer.access", "role_in_project")
    access = importlib.import_module("report_composer.access")

    def broken(*a, **k):
        import psycopg

        raise psycopg.OperationalError("down")

    monkeypatch.setattr(access, "role_in_project", broken)
    assert client.get("/api/p/alpha/layouts", headers=auth("alice")).status_code == 503


# R4.4.2
def test_r4_4_2_the_role_is_read_on_every_request(client, auth, bed):
    assert client.post("/api/p/alpha/layouts", json={"name": "a"}, headers=auth("victor")).status_code == 403
    bed.psql("platform", f"UPDATE core.project_member SET role = 'editor' WHERE project_id = '{IDS['A']}' AND subject = 'victor'")
    try:
        assert client.post("/api/p/alpha/layouts", json={"name": "b"}, headers=auth("victor")).status_code == 201
    finally:
        bed.psql("platform", f"UPDATE core.project_member SET role = 'viewer' WHERE project_id = '{IDS['A']}' AND subject = 'victor'")


# R4.4.5
def test_r4_4_5_an_admin_reads_every_project_and_edits_none(client, auth):
    admin = auth("root-admin", roles=("admin",))
    assert client.get("/api/p/beta/layouts", headers=admin).status_code == 200
    assert client.post("/api/p/beta/layouts", json={"name": "x"}, headers=admin).status_code == 403


# R4.4.6
@pytest.mark.parametrize("origin", [None, "http://evil.example"])
def test_r4_4_6_writes_need_the_same_origin(client, auth, origin):
    r = client.post("/api/p/alpha/layouts", json={"name": "o"}, headers=auth("alice", origin=origin))
    assert r.status_code == 403


def test_r4_4_6_reads_need_no_origin(client, auth):
    assert client.get("/api/p/alpha/layouts", headers=auth("alice", origin=None)).status_code == 200
