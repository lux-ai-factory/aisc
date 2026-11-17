"""Manage > Connectivity, through the platform's API: an admin adds a provider connection (a model provider's key,
or a self-hosted model server); an admin runs a Configurator agent on it; an owner makes a connection a test tool;
and the page reads everything in one call that never holds a secret. The internal routes the agents, the engine
and the worker call answer from the same connections.
"""
from __future__ import annotations

import ipaddress

import pytest

from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN
from tests.llm_support import INTERNAL_TOKEN, RISK_TOKEN, SECRETS_KEY, new_key

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"   # owns the project, not an admin
BOB = "00000000-0000-0000-0000-000000000b0b"     # a viewer
ENGINE_TOKEN = "engine-connectivity-token-for-tests"
SERVICE = "X-AISC-Service-Token"
SELF_HOSTED = "https://llm.example.com/v1"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from aisc_plugin_interface import connections as client

    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CARD_AGENT_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("PLATFORM_RISK_MAPPER_TOKEN", RISK_TOKEN)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)
    monkeypatch.delenv("CONNECTIONS_ALLOWED_HOSTS", raising=False)
    real = client._addresses
    monkeypatch.setattr(client.transport, "_addresses", lambda host, port: [ipaddress.ip_address("93.184.216.34")]
                        if host.endswith("example.com") else real(host, port))


@pytest.fixture
def project(make_project):
    return make_project(owner=ALICE, viewers=(BOB,))


def put_provider(client, project, headers, name="work-openai", **body):
    sent = {"label": "OpenAI (work)", "kind": "provider", "provider": "openai", **body}
    return client.put(f"/projects/{project['slug']}/connections/{name}", json=sent, headers=headers)


# ---- provider connections ------------------------------------------------------------------------

def without_rule(answer: dict) -> dict:
    """A resolve answer without the project's network rule, which it always carries."""
    rule = ("allowed_hosts", "denied_addresses", "floor_hosts")
    assert set(rule) <= set(answer), sorted(answer)
    return {k: v for k, v in answer.items() if k not in rule}


def test_an_admin_adds_a_provider_connection_and_never_gets_its_key_back(client, admin, project):
    key = new_key()
    r = put_provider(client, project, admin, secret=key)

    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["kind"], got["provider"], got["has_secret"], got["target"]) == ("provider", "openai", True, None)
    assert key not in r.text


def test_a_provider_connection_names_a_provider_the_platform_knows(client, admin, project):
    r = put_provider(client, project, admin, provider="telepathy")

    assert r.status_code == 422
    assert "provider" in r.json()["detail"]


def test_a_self_hosted_provider_connection_needs_its_address(client, admin, project):
    assert put_provider(client, project, admin, provider="compatible").status_code == 422
    r = put_provider(client, project, admin, provider="compatible", base_url=SELF_HOSTED)
    assert r.status_code == 200, r.text
    assert r.json()["base_url"] == SELF_HOSTED


def test_a_provider_connection_never_reaches_the_assessed_system(client, admin, project):
    r = put_provider(client, project, admin, target="system")

    assert r.status_code == 422
    assert "assessed system" in r.json()["detail"]


def test_only_an_admin_adds_a_connection(client, as_user, project):
    assert put_provider(client, project, as_user(ALICE), secret=new_key()).status_code == 403


# ---- Configurator agents -------------------------------------------------------------------------

def test_an_admin_runs_an_agent_on_a_provider_connection(client, admin, project):
    key = new_key()
    put_provider(client, project, admin, secret=key)

    r = client.put(f"/projects/{project['slug']}/agents/card_agent", headers=admin,
                   json={"connection": "work-openai", "model": "gpt-test"})

    assert r.status_code == 200, r.text
    resolved = client.get(f"/internal/projects/{project['pid']}/llm/card_agent", headers={SERVICE: INTERNAL_TOKEN})
    assert without_rule(resolved.json()) == {"configured": True, "provider": "openai", "model": "gpt-test",
                                             "base_url": None, "api_key": key,
                                             "chat_base_url": "https://api.openai.com/v1"}


def test_an_agent_runs_only_on_a_provider_connection(client, admin, project):
    from platform_service import connection_store

    connection_store.save(project["pid"], "chat", {"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED,
                                                   "model": "m"}, subject="t")

    r = client.put(f"/projects/{project['slug']}/agents/card_agent", headers=admin,
                   json={"connection": "chat", "model": "m"})

    assert r.status_code == 422
    assert "provider connection" in r.json()["detail"]


def test_an_owner_does_not_choose_an_agents_model(client, admin, as_user, project):
    put_provider(client, project, admin, secret=new_key())

    r = client.put(f"/projects/{project['slug']}/agents/card_agent", headers=as_user(ALICE),
                   json={"connection": "work-openai", "model": "gpt-test"})

    assert r.status_code == 403


def test_removing_an_agents_choice_sends_it_back_to_the_stack_default(client, admin, project):
    put_provider(client, project, admin, secret=new_key())
    client.put(f"/projects/{project['slug']}/agents/risk_mapper", headers=admin,
               json={"connection": "work-openai", "model": "gpt-test"})

    assert client.delete(f"/projects/{project['slug']}/agents/risk_mapper", headers=admin).status_code == 204
    resolved = client.get(f"/internal/projects/{project['pid']}/llm/risk_mapper", headers={SERVICE: RISK_TOKEN})
    assert resolved.json() == {"configured": False}


# ---- test tools ----------------------------------------------------------------------------------

def test_an_owner_makes_a_provider_connection_a_test_tool(client, admin, as_user, project):
    key = new_key()
    put_provider(client, project, admin, secret=key)

    r = client.put(f"/projects/{project['slug']}/connections/work-openai/tool", headers=as_user(ALICE),
                   json={"roles": ["judge", "grader"]})

    assert r.status_code == 200, r.text
    listed = client.get(f"/internal/projects/{project['pid']}/helpers?role=judge", headers={SERVICE: ENGINE_TOKEN})
    assert [(h["name"], h["ref"]) for h in listed.json()["helpers"]] == [
        ("work-openai", f"helper:{project['pid']}/work-openai")]
    resolved = client.get(f"/internal/projects/{project['pid']}/helpers/work-openai/resolve",
                          headers={SERVICE: CONNECTIONS_TOKEN})
    assert without_rule(resolved.json()) == {"label": "OpenAI (work)", "endpoint_url": "https://api.openai.com/v1",
                                             "roles": ["judge", "grader"], "api_key": key}


def test_a_connection_that_reaches_the_assessed_system_is_never_a_test_tool(client, admin, project):
    from platform_service import connection_store, target_store

    target_store.ensure_system(project["pid"], "The system")
    connection_store.save(project["pid"], "the-system", {"label": "System", "kind": "openai", "base_url": SELF_HOSTED,
                                                         "model": "m", "target_key": "system"}, subject="t")

    r = client.put(f"/projects/{project['slug']}/connections/the-system/tool", headers=admin,
                   json={"roles": ["judge"]})

    assert r.status_code == 409
    assert "assessed system" in r.json()["detail"]


def test_a_tool_names_only_known_roles(client, admin, project):
    put_provider(client, project, admin, secret=new_key())

    r = client.put(f"/projects/{project['slug']}/connections/work-openai/tool", headers=admin,
                   json={"roles": ["oracle"]})

    assert r.status_code == 422


def test_a_viewer_does_not_make_a_test_tool(client, admin, as_user, project):
    put_provider(client, project, admin, secret=new_key())

    r = client.put(f"/projects/{project['slug']}/connections/work-openai/tool", headers=as_user(BOB),
                   json={"roles": ["judge"]})

    assert r.status_code == 403


def test_an_owner_stops_using_a_connection_as_a_test_tool(client, admin, as_user, project):
    put_provider(client, project, admin, secret=new_key())
    client.put(f"/projects/{project['slug']}/connections/work-openai/tool", headers=admin, json={"roles": ["judge"]})

    r = client.delete(f"/projects/{project['slug']}/connections/work-openai/tool", headers=as_user(ALICE))

    assert r.status_code == 204
    resolved = client.get(f"/internal/projects/{project['pid']}/helpers/work-openai/resolve",
                          headers={SERVICE: CONNECTIONS_TOKEN})
    assert resolved.status_code == 404


# ---- the page's one read -------------------------------------------------------------------------

def test_the_connectivity_page_reads_everything_in_one_call_without_a_secret(client, admin, as_user, project):
    key = new_key()
    put_provider(client, project, admin, secret=key)
    client.put(f"/projects/{project['slug']}/agents/card_agent", headers=admin,
               json={"connection": "work-openai", "model": "gpt-test"})
    client.put(f"/projects/{project['slug']}/connections/work-openai/tool", headers=admin, json={"roles": ["judge"]})

    r = client.get(f"/projects/{project['slug']}/connectivity", headers=as_user(ALICE))

    assert r.status_code == 200, r.text
    assert key not in r.text
    got = r.json()
    assert set(got) >= {"components", "agents", "tools", "connections", "can_manage"}
    [conn] = [c for c in got["connections"] if c["name"] == "work-openai"]
    assert conn["used_for"] == [{"use": "agent", "agent": "card_agent", "model": "gpt-test"},
                                {"use": "tool", "roles": ["judge"]}]
    assert {a["id"]: a["choice"] for a in got["agents"]}["card_agent"] == {"connection": "work-openai",
                                                                         "model": "gpt-test"}
    assert {t["role"]: [c["name"] for c in t["connections"]] for t in got["tools"]}["judge"] == ["work-openai"]
    assert got["can_manage"] is False


def test_a_viewer_does_not_see_the_connectivity_page(client, as_user, project):
    assert client.get(f"/projects/{project['slug']}/connectivity", headers=as_user(BOB)).status_code == 403


# ---- an agent's model, picked from what its connection's provider offers ---------------------------------

def test_an_admin_lists_the_models_a_provider_connection_offers_with_its_own_address_and_key(client, admin, project,
                                                                                            monkeypatch):
    from platform_service import llm_catalogue
    asked = {}

    def listing(provider, api_key=None, base_url=None, rule=None):
        asked.update(provider=provider, api_key=api_key, base_url=base_url)
        return {"models": ["text-embedding-3", "gpt-4o-mini"], "error": None}

    monkeypatch.setattr(llm_catalogue, "list_models", listing)
    key = new_key()
    put_provider(client, project, admin, name="llm-judge", provider="compatible", base_url="https://api.openai.com/v1",
                 secret=key)
    r = client.get(f"/projects/{project['slug']}/connections/llm-judge/models", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"models": ["gpt-4o-mini", "text-embedding-3"], "error": None}
    assert asked == {"provider": "compatible", "api_key": key, "base_url": "https://api.openai.com/v1"}
    assert key not in r.text


def test_a_connections_models_are_never_asked_at_an_address_the_projects_rule_now_refuses(client, admin, project,
                                                                                         monkeypatch):
    """A provider connection saved at an internal address the project allowed then; the entry is gone since: its key
    is not sent there, and the rule's reason is the error."""
    import httpx

    from aisc_plugin_interface import connections as guard
    from platform_service import connection_store, llm_store

    real = guard.transport._addresses
    monkeypatch.setattr(guard.transport, "_addresses", lambda host, port: [ipaddress.ip_address("10.20.30.40")]
                        if host == "inside.example.com" else real(host, port))

    def no_call(*args, **kwargs):
        raise AssertionError("the listing called an address the project's network rule refuses")

    monkeypatch.setattr(httpx, "Client", no_call)
    key = new_key()
    connection_store.save_provider(project["pid"], "inside-llm", label="Inside", provider="compatible",
                                   base_url="https://inside.example.com/v1", ciphertext=llm_store.encrypt(key),
                                   subject="t")
    r = client.get(f"/projects/{project['slug']}/connections/inside-llm/models", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["models"] == []
    assert "internal address" in r.json()["error"]
    assert key not in r.text


def test_only_an_admin_lists_a_connections_models(client, admin, as_user, project):
    put_provider(client, project, admin, secret=new_key())
    assert client.get(f"/projects/{project['slug']}/connections/work-openai/models",
                      headers=as_user(ALICE)).status_code == 403


def test_a_connection_that_is_no_provider_has_no_models_to_list(client, admin, project):
    from platform_service import connection_store
    connection_store.save(project["pid"], "chat", {"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED,
                                                   "model": "m"}, subject="t")
    assert client.get(f"/projects/{project['slug']}/connections/chat/models", headers=admin).status_code == 404


# ---- who may make which connection a test tool, and who sees a connection's settings ------------------

def _chat_connection(project):
    from platform_service import connection_store

    connection_store.save(project["pid"], "chat", {"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED,
                                                   "model": "m"}, ciphertext=None, subject="t")


def test_an_owner_makes_only_a_provider_connection_a_test_tool(client, admin, as_user, project):
    _chat_connection(project)

    r = client.put(f"/projects/{project['slug']}/connections/chat/tool", headers=as_user(ALICE),
                   json={"roles": ["judge"]})

    assert r.status_code == 403
    resolved = client.get(f"/internal/projects/{project['pid']}/helpers/chat/resolve",
                          headers={SERVICE: CONNECTIONS_TOKEN})
    assert resolved.status_code == 404


def test_an_admin_makes_any_connection_without_a_target_a_test_tool(client, admin, project):
    _chat_connection(project)

    r = client.put(f"/projects/{project['slug']}/connections/chat/tool", headers=admin, json={"roles": ["judge"]})

    assert r.status_code == 200, r.text


def test_an_owner_sees_each_connections_name_label_kind_and_uses_only(client, admin, as_user, project):
    put_provider(client, project, admin, provider="compatible", base_url=SELF_HOSTED, secret=new_key())
    client.put(f"/projects/{project['slug']}/connections/work-openai/tool", headers=admin, json={"roles": ["judge"]})

    owner = client.get(f"/projects/{project['slug']}/connectivity", headers=as_user(ALICE)).json()
    [seen] = [c for c in owner["connections"] if c["name"] == "work-openai"]
    assert seen == {"name": "work-openai", "label": "OpenAI (work)", "kind": "provider",
                    "used_for": [{"use": "tool", "roles": ["judge"]}]}
    assert SELF_HOSTED not in str(owner["connections"])

    full = client.get(f"/projects/{project['slug']}/connectivity", headers=admin).json()
    [seen] = [c for c in full["connections"] if c["name"] == "work-openai"]
    assert seen["base_url"] == SELF_HOSTED and seen["used_for"] == [{"use": "tool", "roles": ["judge"]}]


# ---- a refused save is a conflict with its reason, never a server error --------------------------------

def test_linking_a_test_tool_to_the_assessed_system_is_a_conflict(client, admin, project):
    from platform_service import target_store

    target_store.ensure_system(project["pid"], "The system")
    _chat_connection(project)
    assert client.put(f"/projects/{project['slug']}/connections/chat/tool", headers=admin,
                      json={"roles": ["judge"]}).status_code == 200

    r = client.post(f"/projects/{project['slug']}/connections/chat/target", headers=admin, json={"key": "system"})
    assert r.status_code == 409 and "assessed system" in r.json()["detail"]

    r = client.put(f"/projects/{project['slug']}/connections/chat", headers=admin,
                   json={"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED, "model": "m", "target": "system"})
    assert r.status_code == 409 and "assessed system" in r.json()["detail"]


def test_a_connection_of_another_kind_over_a_provider_connection_is_a_conflict(client, admin, project):
    assert put_provider(client, project, admin).status_code == 200

    r = client.put(f"/projects/{project['slug']}/connections/work-openai", headers=admin,
                   json={"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED, "model": "m"})

    assert r.status_code == 409 and "another kind" in r.json()["detail"]


def test_a_provider_key_whose_connection_name_another_connection_holds_is_a_conflict(client, admin, project):
    from platform_service import connection_store

    connection_store.save(project["pid"], "llm-openai", {"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED,
                                                         "model": "m"}, subject="t")

    r = client.put(f"/projects/{project['slug']}/llm/providers/openai", headers=admin, json={"api_key": new_key()})
    assert r.status_code == 409 and "llm-openai" in r.json()["detail"]

    connection_store.save(project["pid"], "llm-ollama", {"label": "Chat", "kind": "openai", "base_url": SELF_HOSTED,
                                                         "model": "m"}, subject="t")
    r = client.put(f"/projects/{project['slug']}/llm/systems/risk_mapper", headers=admin,
                   json={"provider": "ollama", "model": "llama3"})
    assert r.status_code == 409 and "llm-ollama" in r.json()["detail"]
