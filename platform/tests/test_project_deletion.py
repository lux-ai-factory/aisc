"""Deleting a project: only an admin, and only by typing its name.

It drops the project's database, which is everything every module holds for
it, so the rule is strict and the tests check the database is really gone.
"""
import psycopg

from platform_service import projectdb
from tests.conftest import needs_database


def _db_exists(dsn, pid):
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "select 1 from pg_database where datname = %s", (projectdb.database_name(pid),)
        ).fetchone() is not None


def _delete(client, slug, name, headers):
    return client.request("DELETE", f"/projects/{slug}", json={"confirm_name": name}, headers=headers)


@needs_database
def test_an_admin_who_types_the_name_deletes_the_project_and_its_database(client, as_user, unique, dsn):
    slug = unique()
    created = client.post("/projects", json={"name": f"Name {slug}", "slug": slug}, headers=as_user("alice")).json()
    assert _db_exists(dsn, created["pid"])
    admin = as_user("root", roles=("admin",))
    assert _delete(client, slug, f"Name {slug}", admin).status_code == 204
    assert client.get(f"/projects/{slug}", headers=admin).status_code == 404
    assert not _db_exists(dsn, created["pid"])


@needs_database
def test_a_name_that_is_nearly_right_deletes_nothing(client, as_user, unique, dsn):
    slug = unique()
    created = client.post("/projects", json={"name": f"Name {slug}", "slug": slug}, headers=as_user("alice")).json()
    admin = as_user("root", roles=("admin",))
    for wrong in (f"name {slug}", f"Name {slug} ", slug, ""):
        assert _delete(client, slug, wrong, admin).status_code == 422
    assert _db_exists(dsn, created["pid"])


@needs_database
def test_an_owner_who_is_not_an_admin_cannot_delete(client, as_user, unique, dsn):
    slug = unique()
    created = client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice")).json()
    assert _delete(client, slug, slug, as_user("alice")).status_code == 403
    assert _db_exists(dsn, created["pid"])


@needs_database
def test_a_stranger_is_told_nothing(client, as_user, unique):
    slug = unique()
    client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice"))
    assert _delete(client, slug, slug, as_user("mallory")).status_code == 404


@needs_database
def test_an_unknown_project_is_404_even_for_an_admin(client, as_user):
    assert _delete(client, "pytest-no-such-project", "x", as_user("root", roles=("admin",))).status_code == 404
