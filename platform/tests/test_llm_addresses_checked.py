"""A project's model address is checked against its network rule before any request: the model listing does
not ask an address the rule refuses, and an agent resolving its model gets the rule with it. Runs on the
throwaway."""
from __future__ import annotations

import pytest

from platform_service import llm_catalogue
from tests.conftest import needs_database
from tests.test_api_llm import _secrets, put_provider, put_system, resolve  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.fixture
def project(make_project):
    return make_project()


def test_a_base_url_the_rule_refuses_is_not_asked(monkeypatch):
    sent = []
    monkeypatch.setattr(llm_catalogue.httpx.Client, "send", lambda *a, **k: sent.append(a))
    try:
        got = llm_catalogue.list_models("compatible", base_url="http://169.254.169.254/v1",
                                        rule={"allowed_hosts": [], "denied_addresses": ["169.254.169.254"],
                                              "floor_hosts": []})
    except TypeError as exc:
        pytest.fail(f"the model listing takes no rule: {exc}")
    assert got["models"] == [] and "never" in (got["error"] or ""), got
    assert sent == []


def test_an_agent_resolving_its_model_gets_the_projects_rule(client, admin, project):
    assert put_provider(client, project, "compatible", admin, base_url="https://models.example/v1").status_code == 200
    assert put_system(client, project, "card_agent", admin, "compatible", "m").status_code == 200
    r = resolve(client, project["pid"])
    assert r.status_code == 200, r.text
    assert {"allowed_hosts", "denied_addresses", "floor_hosts"} <= set(r.json()), sorted(r.json())
