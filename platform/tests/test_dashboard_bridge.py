"""The platform side of the dashboard.

A project's database lets the dashboard in (template 0002_dashboard.sql), and
making or deleting a project tells the dashboard bridge, which makes or removes
that project's datasets, connection, role and dashboard. The bridge is
a stub HTTP server here; a bridge that is down never stops the platform.
"""
import time

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from tests.conftest import needs_database
from tests.http_stub import Stub, closed_port_url

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
TOKEN = "pytest-bridge-token"


@pytest.fixture
def bridge(monkeypatch):
    stub = Stub(default=(200, {}))
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.url)
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    yield stub
    stub.close()


def _delete(client, as_user, project):
    return client.request("DELETE", f"/projects/{project['slug']}", json={"confirm_name": project["name"]},
                          headers=as_user("root", roles=("admin",)))


# Template 0002_dashboard.sql
def test_the_dashboard_may_connect_to_a_project_database_and_use_its_controls_schema(
        client, as_user, make_project, dsn, bridge):
    created = make_project(prefix="dash")
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(make_conninfo(dsn, user="dashboard_ro", password="dashboard_ro", dbname=name)) as conn:
        assert conn.execute("select has_schema_privilege('controls', 'USAGE')").fetchone()[0]
    with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
        applied = {r[0] for r in conn.execute("select name from provision.template_migration").fetchall()}
    assert "0002_dashboard.sql" in applied


def test_the_dashboard_still_writes_nothing_in_a_project_database(client, as_user, make_project, dsn, bridge):
    created = make_project(prefix="dash")
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(make_conninfo(dsn, user="dashboard_ro", password="dashboard_ro", dbname=name)) as conn:
        assert not conn.execute("select has_schema_privilege('controls', 'CREATE')").fetchone()[0]


# The bridge calls, platform side
def test_making_a_project_registers_it_with_the_dashboard_bridge(client, as_user, make_project, bridge):
    created = make_project(prefix="dash")
    posts = bridge.requests("POST")
    assert [c.path for c in posts] == [f"/api/v1/aisc_project/{created['pid']}"]
    assert posts[0].header("X-AISC-Bridge-Token") == TOKEN


def test_deleting_a_project_unregisters_it_before_its_database_is_dropped(
        client, as_user, make_project, bridge, monkeypatch):
    created = make_project(prefix="dash")
    order = []
    real_drop = projectdb.drop

    def recording_drop(*args, **kwargs):
        order.append(("drop", len(bridge.requests("DELETE"))))
        return real_drop(*args, **kwargs)

    monkeypatch.setattr(projectdb, "drop", recording_drop)
    assert _delete(client, as_user, created).status_code == 204
    deletes = bridge.requests("DELETE")
    assert [c.path for c in deletes] == [f"/api/v1/aisc_project/{created['pid']}"]
    assert deletes[0].header("X-AISC-Bridge-Token") == TOKEN
    assert order == [("drop", 1)], "the bridge is told before the database is dropped"


def test_a_bridge_that_is_down_does_not_stop_making_or_deleting_a_project(
        client, as_user, make_project, monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", closed_port_url())
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    created = make_project(prefix="dash")
    assert _delete(client, as_user, created).status_code == 204


def test_a_bridge_that_hangs_is_given_up_on_after_about_5_seconds(client, as_user, make_project, monkeypatch):
    stub = Stub(default=(200, {}), delay=20)
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.url)
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    try:
        started = time.monotonic()
        make_project(prefix="dash")
        elapsed = time.monotonic() - started
    finally:
        stub.close()
    assert stub.seen, "the bridge was called"
    assert elapsed < 12, f"project creation waited {elapsed:.1f}s on the bridge"


def test_a_failed_registration_is_retried_by_provision_all(client, as_user, make_project, monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", closed_port_url())
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    created = make_project(prefix="dash")
    stub = Stub(default=(200, {}))
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.url)
    try:
        db.reset()
        db.pool()  # the next pool() after a start runs provision_all
        paths = [c.path for c in stub.requests("POST")]
    finally:
        stub.close()
        db.reset()
    assert f"/api/v1/aisc_project/{created['pid']}" in paths
