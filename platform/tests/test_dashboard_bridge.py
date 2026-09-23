"""The platform side of the dashboard (WP11 of pipeline-2026-09-23).

A project's database lets the dashboard in (template 0002_dashboard.sql), and
making or deleting a project tells the dashboard bridge, which makes or removes
that project's datasets, connection, role and dashboard (S11.5). The bridge is
a stub HTTP server here; a bridge that is down never stops the platform.
"""
import http.server
import threading
import time

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
TOKEN = "pytest-bridge-token"


class _Bridge:
    def __init__(self, delay=0.0):
        self.calls, self.delay = [], delay
        bridge = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                bridge.calls.append((self.command, self.path, self.headers.get("X-AISC-Bridge-Token"), body))
                if bridge.delay:
                    time.sleep(bridge.delay)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            do_POST = do_DELETE = do_PUT = _record

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def bridge(monkeypatch):
    stub = _Bridge()
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.url)
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    yield stub
    stub.close()


def _closed_port_url():
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def _make(client, as_user, unique):
    response = client.post("/projects", json={"name": unique("dash")}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


def _delete(client, as_user, project):
    return client.request("DELETE", f"/projects/{project['slug']}", json={"confirm_name": project["name"]},
                          headers=as_user("root", roles=("admin",)))


# ── template 0002_dashboard.sql ─────────────────────────────────────────────


def test_wp11_the_dashboard_may_connect_to_a_project_database_and_use_its_controls_schema(
        client, as_user, unique, dsn, bridge):
    created = _make(client, as_user, unique)
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(make_conninfo(dsn, user="dashboard_ro", password="dashboard_ro", dbname=name)) as conn:
        assert conn.execute("select has_schema_privilege('controls', 'USAGE')").fetchone()[0]
    with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
        applied = {r[0] for r in conn.execute("select name from provision.template_migration").fetchall()}
    assert "0002_dashboard.sql" in applied


def test_wp11_the_dashboard_still_writes_nothing_in_a_project_database(client, as_user, unique, dsn, bridge):
    created = _make(client, as_user, unique)
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(make_conninfo(dsn, user="dashboard_ro", password="dashboard_ro", dbname=name)) as conn:
        assert not conn.execute("select has_schema_privilege('controls', 'CREATE')").fetchone()[0]


# ── the bridge calls (S11.5, platform side) ────────────────────────────────


def test_s11_5_making_a_project_registers_it_with_the_dashboard_bridge(client, as_user, unique, bridge):
    created = _make(client, as_user, unique)
    posts = [c for c in bridge.calls if c[0] == "POST"]
    assert [c[1] for c in posts] == [f"/api/v1/aisc_project/{created['pid']}"]
    assert posts[0][2] == TOKEN


def test_s11_5_deleting_a_project_unregisters_it_before_its_database_is_dropped(
        client, as_user, unique, bridge, monkeypatch):
    created = _make(client, as_user, unique)
    order = []
    real_drop = projectdb.drop

    def recording_drop(*args, **kwargs):
        order.append(("drop", len([c for c in bridge.calls if c[0] == "DELETE"])))
        return real_drop(*args, **kwargs)

    monkeypatch.setattr(projectdb, "drop", recording_drop)
    assert _delete(client, as_user, created).status_code == 204
    deletes = [c for c in bridge.calls if c[0] == "DELETE"]
    assert [c[1] for c in deletes] == [f"/api/v1/aisc_project/{created['pid']}"]
    assert deletes[0][2] == TOKEN
    assert order == [("drop", 1)], "the bridge is told before the database is dropped"


def test_s11_5_a_bridge_that_is_down_does_not_stop_making_or_deleting_a_project(
        client, as_user, unique, monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", _closed_port_url())
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    created = _make(client, as_user, unique)
    assert _delete(client, as_user, created).status_code == 204


def test_s11_5_a_bridge_that_hangs_is_given_up_on_after_about_5_seconds(client, as_user, unique, monkeypatch):
    stub = _Bridge(delay=20)
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.url)
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    try:
        started = time.monotonic()
        _make(client, as_user, unique)
        elapsed = time.monotonic() - started
    finally:
        stub.close()
    assert stub.calls, "the bridge was called"
    assert elapsed < 12, f"project creation waited {elapsed:.1f}s on the bridge"


def test_s11_5_a_failed_registration_is_retried_by_provision_all(client, as_user, unique, monkeypatch):
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", _closed_port_url())
    monkeypatch.setenv("DASHBOARD_BRIDGE_TOKEN", TOKEN)
    created = _make(client, as_user, unique)
    stub = _Bridge()
    monkeypatch.setenv("DASHBOARD_BRIDGE_URL", stub.url)
    try:
        db.reset()
        db.pool()  # the next pool() after a start runs provision_all
        paths = [c[1] for c in stub.calls if c[0] == "POST"]
    finally:
        stub.close()
        db.reset()
    assert f"/api/v1/aisc_project/{created['pid']}" in paths
