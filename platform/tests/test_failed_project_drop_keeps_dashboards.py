"""Removing a project drops its database first and removes its dashboards only once the drop succeeded.
If the drop fails, the project and its data stay, and so must every dashboard and chart people made on it:
re-making the starter dashboard does not bring hand-made ones back. Runs on the throwaway."""
from __future__ import annotations

import pytest

from platform_service import dashboard_bridge, projectdb
from tests.conftest import needs_database


@pytest.fixture
def bridge(monkeypatch):
    seen: list[str] = []
    monkeypatch.setenv("LEDGER_MODE", "off")
    monkeypatch.setattr(dashboard_bridge, "unregister", lambda pid: seen.append("unregister") or True)
    monkeypatch.setattr(dashboard_bridge, "register", lambda *a: seen.append("register") or True)
    return seen


def _delete(client, made, headers):
    return client.request("DELETE", f"/projects/{made['slug']}", json={"confirm_name": made["name"]}, headers=headers)


@needs_database
def test_a_failed_drop_leaves_the_dashboards_untouched(client, as_user, make_project, bridge, monkeypatch):
    made = make_project()
    real_drop = projectdb.drop

    def failing(dsn, pid):
        if str(pid) == made["pid"]:
            raise RuntimeError("the database could not be dropped")
        return real_drop(dsn, pid)

    monkeypatch.setattr(projectdb, "drop", failing)
    try:
        answer = _delete(client, made, as_user("root", roles=("admin",)))
        assert answer.status_code >= 500, answer.status_code
    except RuntimeError:
        pass                                    # the failure reached the caller as it happened
    assert "unregister" not in bridge, "the dashboards were removed before the drop that then failed"


@needs_database
def test_the_dashboards_go_after_the_database_is_dropped(client, as_user, make_project, bridge, monkeypatch):
    made = make_project()
    order: list[str] = []
    real_drop = projectdb.drop
    monkeypatch.setattr(projectdb, "drop", lambda dsn, pid: order.append("drop") or real_drop(dsn, pid))
    monkeypatch.setattr(dashboard_bridge, "unregister", lambda pid: order.append("unregister") or True)
    assert _delete(client, made, as_user("root", roles=("admin",))).status_code == 204
    assert order == ["drop", "unregister"]
