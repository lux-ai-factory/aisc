"""Deleting a dashboard, a chart or a dataset in Superset itself is a dashboard event the ledger knows: the
dashboard's extension sends it, and the registry takes it as caused by Superset's own delete routes, so a
removal is not left only in Superset's logs table."""
from __future__ import annotations

import re

import pytest

DELETIONS = [
    ("dashboard.dashboard.deleted", "dashboard", "/api/v1/dashboard/4"),
    ("dashboard.chart.deleted", "chart", "/api/v1/chart/135"),
    ("dashboard.chart.deleted", "chart", "/api/v1/chart/?q=!(135,136,137)"),
    ("dashboard.dataset.deleted", "dataset", "/api/v1/dataset/10"),
]


@pytest.mark.parametrize("action, item_type, path", DELETIONS, ids=[f"{a}:{p}" for a, _, p in DELETIONS])
def test_a_superset_deletion_is_an_action_the_dashboard_may_send(action, item_type, path):
    from platform_service.ledger.registry import REGISTRY

    assert action in REGISTRY, f"the ledger registry has no {action}"
    declared = REGISTRY[action]
    assert "dashboard" in declared.emitters and declared.item_type == item_type
    route = path.split("?")[0]
    assert any(app == "dashboard" and method == "DELETE" and re.search(pattern, route)
               for app, method, pattern in declared.caused_by), f"{action} is not caused by DELETE {route}"


SENT = [
    ("/api/v1/dashboard/4?dashboard={slug}", "dashboard.dashboard.deleted", "dashboard", "4",
     {"details": {"dashboard": "{slug}"}, "before": {"title": "LangBiTe (Mijke)"}}),
    ("/api/v1/chart/?q=!(135,136)&dashboard={slug}", "dashboard.chart.deleted", "chart", "135",
     {"details": {"dashboard": "{slug}"}, "before": {"title": "Pass rate per concern"}}),
    ("/api/v1/dataset/10?dashboard={slug}", "dashboard.dataset.deleted", "dataset", "10",
     {"details": {}, "before": {"name": "engine_results_x"}}),
]


@pytest.mark.parametrize("uri, action, item_type, item_id, over", SENT, ids=[s[1] for s in SENT])
def test_a_deletion_as_the_extension_sends_it_is_accepted_when_its_request_names_the_dashboard(
        client, project, memory_ledger, witnessed, mode, monkeypatch, uri, action, item_type, item_id, over):
    import uuid

    from tests.ledger.conftest import MEMBER, entries, log_of, relay_all
    from tests.ledger.test_ledger_step5_dashboard import TOKEN, _filled, rejected, slug_of

    mode("enforce")
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", TOKEN)
    slug = slug_of(project)
    request_id = witnessed(MEMBER, "DELETE", "dashboard", uri.format(slug=slug))
    event = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
             "item_id": item_id, **_filled(over, slug)}
    r = client.post(f"/internal/projects/{project['pid']}/ledger/events", json=event,
                    headers={"X-AISC-Service-Token": TOKEN})
    assert r.status_code == 202, r.text
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert [x.item_id for x in entries(memory_ledger, log_of(project["pid"])) if x.action == action] == [item_id]
