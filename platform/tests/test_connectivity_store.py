"""One connection model: a project's provider keys, its agents' model choices and its helper models are
connections (`connection.endpoint`, kind `provider`) and their uses (`connection.use`), in the project's own
database (project-template/0030_connectivity.sql). llm_store and helper_store keep their functions.

A connection that reaches the assessed system (it has a target) is never also used by an agent or as a test
tool, and the other way round: the database refuses it.
"""
from __future__ import annotations

import psycopg
import pytest

from tests.conftest import needs_database, project_db
from tests.llm_support import SECRETS_KEY, new_key

pytestmark = needs_database

ENDPOINT = "https://judge.example.com/v1"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)


def rows(dsn, project, sql, params=()):
    with project_db(dsn, project) as conn:
        return conn.execute(sql, params).fetchall()


def run(dsn, project, sql, params=()):
    with project_db(dsn, project) as conn:
        conn.execute(sql, params)


def providers(dsn, project):
    return rows(dsn, project, "select name, provider, base_url, secret_ciphertext is not null, target_key"
                              " from connection.endpoint where kind = 'provider' and deleted_at is null order by name")


def uses(dsn, project):
    return rows(dsn, project, "select connection, use, agent, roles, model, tool_name from connection.use"
                              " where deleted_at is null order by id")


# ---- provider keys and agent choices --------------------------------------------------------------

def test_a_provider_key_is_a_provider_connection(dsn, project):
    from platform_service import llm_store

    llm_store.save_provider(project["pid"], "openai", ciphertext=llm_store.encrypt(new_key()), subject="t")

    assert providers(dsn, project) == [("llm-openai", "openai", "", True, None)]
    assert rows(dsn, project, "select count(*) from llm.provider") == [(0,)]
    assert set(llm_store.providers(project["pid"])) == {"openai"}


def test_a_self_hosted_provider_keeps_its_base_url(dsn, project):
    from platform_service import llm_store

    llm_store.save_provider(project["pid"], "compatible", base_url="https://llm.example.org/v1", subject="t")

    assert providers(dsn, project) == [("llm-compatible", "compatible", "https://llm.example.org/v1", False, None)]
    assert llm_store.providers(project["pid"])["compatible"]["base_url"] == "https://llm.example.org/v1"


def test_an_agent_choice_is_an_agent_use_of_the_provider_connection(dsn, project):
    from platform_service import llm_store

    key = new_key()
    llm_store.save_provider(project["pid"], "openai", ciphertext=llm_store.encrypt(key), subject="t")
    llm_store.save_choice(project["pid"], "card_agent", "openai", "gpt-test", subject="t", keyless_row=False)

    assert uses(dsn, project) == [("llm-openai", "agent", "card_agent", None, "gpt-test", None)]
    choice = llm_store.resolve_choice(project["pid"], "card_agent")
    assert (choice["provider"], choice["model"], choice["base_url"]) == ("openai", "gpt-test", None)
    assert llm_store.decrypt("openai", choice["ciphertext"]) == key
    assert llm_store.choices(project["pid"]) == {"card_agent": {"provider": "openai", "model": "gpt-test"}}


def test_a_keyless_choice_makes_its_provider_connection(dsn, project):
    from platform_service import llm_store

    llm_store.save_choice(project["pid"], "risk_mapper", "ollama", "llama3", subject="t", keyless_row=True)

    assert providers(dsn, project) == [("llm-ollama", "ollama", "", False, None)]
    assert uses(dsn, project) == [("llm-ollama", "agent", "risk_mapper", None, "llama3", None)]


def test_a_provider_in_use_by_an_agent_is_not_deleted(dsn, project):
    from platform_service import llm_store

    llm_store.save_choice(project["pid"], "card_agent", "ollama", "m", subject="t", keyless_row=True)

    assert llm_store.delete_provider(project["pid"], "ollama") == ["card_agent"]
    llm_store.delete_choice(project["pid"], "card_agent")
    assert llm_store.delete_provider(project["pid"], "ollama") is True
    assert providers(dsn, project) == []


# ---- helper models -------------------------------------------------------------------------------

def test_a_helper_is_a_tool_use_of_a_compatible_connection(dsn, project):
    from platform_service import helper_store, llm_store

    key = new_key()
    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge", "grader"],
                      ciphertext=llm_store.encrypt(key), subject="t")

    assert providers(dsn, project) == [("judge", "compatible", ENDPOINT, True, None)]
    assert uses(dsn, project) == [("judge", "tool", None, ["judge", "grader"], None, "judge")]
    resolved = helper_store.resolve(project["pid"], "judge")
    assert resolved == {"label": "Judge", "endpoint_url": ENDPOINT, "roles": ["judge", "grader"], "api_key": key}


def test_a_helper_named_like_an_assessed_connection_gets_a_connection_of_its_own(dsn, project):
    from platform_service import connection_store, helper_store

    connection_store.save(project["pid"], "judge", {"label": "The system", "kind": "openai",
                                                    "base_url": "https://system.example.com/v1", "model": "m"},
                          subject="t")
    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge"], subject="t")

    assert providers(dsn, project) == [("judge-helper", "compatible", ENDPOINT, False, None)]
    assert helper_store.resolve(project["pid"], "judge")["endpoint_url"] == ENDPOINT
    assert connection_store.get(project["pid"], "judge")["kind"] == "openai"
    assert [h["name"] for h in helper_store.list_models(project["pid"])] == ["judge"]


def test_removing_a_helper_drops_its_key_and_keeps_its_name_for_old_runs(dsn, project):
    from platform_service import helper_store, llm_store

    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge"],
                      ciphertext=llm_store.encrypt(new_key()), subject="t")
    assert helper_store.remove(project["pid"], "judge") is True

    assert helper_store.resolve(project["pid"], "judge") is None
    assert helper_store.get(project["pid"], "judge", with_deleted=True)["deleted_at"] is not None
    assert rows(dsn, project, "select secret_ciphertext from connection.endpoint where name = 'judge'") == [(None,)]


def test_a_removed_helper_saved_again_comes_back(dsn, project):
    from platform_service import helper_store

    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge"], subject="t")
    helper_store.remove(project["pid"], "judge")
    helper_store.save(project["pid"], "judge", label="Judge 2", endpoint_url=ENDPOINT, roles=["attacker"], subject="t")

    assert [(h["name"], h["label"], h["roles"]) for h in helper_store.list_models(project["pid"])] == [
        ("judge", "Judge 2", ["attacker"])]
    assert len(uses(dsn, project)) == 1


# ---- the assessed lock ---------------------------------------------------------------------------

def _assessed(project):
    """A connection that reaches the project's system target."""
    from platform_service import connection_store, target_store

    target_store.ensure_system(project["pid"], "The system")
    connection_store.save(project["pid"], "system-link", {"label": "System", "kind": "openai",
                                                          "base_url": "https://system.example.com/v1", "model": "m",
                                                          "target_key": "system"}, subject="t")


def test_a_connection_that_reaches_the_assessed_system_cannot_be_used(dsn, project):
    _assessed(project)

    with pytest.raises(psycopg.errors.RaiseException, match="assessed"):
        run(dsn, project, "insert into connection.use (connection, use, roles, tool_name)"
                          " values ('system-link', 'tool', array['judge'], 'sneaky')")


def test_a_used_connection_cannot_reach_the_assessed_system(dsn, project):
    from platform_service import connection_store, helper_store, target_store

    target_store.ensure_system(project["pid"], "The system")
    connection_store.save(project["pid"], "judge-link", {"label": "Judge", "kind": "openai",
                                                         "base_url": ENDPOINT, "model": "m"}, subject="t")
    run(dsn, project, "insert into connection.use (connection, use, roles, tool_name)"
                      " values ('judge-link', 'tool', array['judge'], 'judge-link')")

    with pytest.raises(connection_store.ConnectionAssessed):
        connection_store.link_target(project["pid"], "judge-link", "system", subject="t")
    assert helper_store.resolve(project["pid"], "judge-link") is not None


def test_a_provider_connection_never_reaches_the_assessed_system(dsn, project):
    from platform_service import llm_store, target_store

    target_store.ensure_system(project["pid"], "The system")
    llm_store.save_provider(project["pid"], "openai", ciphertext=llm_store.encrypt(new_key()), subject="t")

    with pytest.raises(psycopg.errors.CheckViolation):
        run(dsn, project, "update connection.endpoint set target_key = 'system' where name = 'llm-openai'")


def test_each_agent_has_one_live_choice(dsn, project):
    from platform_service import llm_store

    llm_store.save_choice(project["pid"], "card_agent", "ollama", "m", subject="t", keyless_row=True)

    with pytest.raises(psycopg.errors.UniqueViolation):
        run(dsn, project, "insert into connection.use (connection, use, agent, model)"
                          " values ('llm-ollama', 'agent', 'card_agent', 'other')")


def test_a_tool_use_names_only_known_roles(dsn, project):
    from platform_service import helper_store

    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge"], subject="t")

    with pytest.raises(psycopg.errors.CheckViolation):
        run(dsn, project, "update connection.use set roles = array['oracle'] where tool_name = 'judge'")


# ---- the move of a project made before connectivity ----------------------------------------------

def test_the_move_brings_keys_choices_and_helpers_into_connections(dsn, project):
    from platform_service import connection_store, helper_store, llm_store

    connection_store.save(project["pid"], "clash", {"label": "The system", "kind": "openai",
                                                    "base_url": "https://system.example.com/v1", "model": "m"},
                          subject="t")
    openai_token, judge_token = llm_store.encrypt(new_key()), llm_store.encrypt(new_key())
    with project_db(dsn, project) as conn:
        conn.execute("insert into llm.provider (provider, ciphertext) values ('openai', %s)", (openai_token,))
        conn.execute("insert into llm.provider (provider, base_url) values ('ollama', 'http://ollama.lab:11434')")
        conn.execute("insert into llm.system_choice (system, provider, model) values ('card_agent', 'openai', 'g')")
        conn.execute("insert into helper.model (name, label, endpoint_url, ciphertext, roles)"
                     " values ('judge', 'Judge', %s, %s, array['judge'])", (ENDPOINT, judge_token))
        conn.execute("insert into helper.model (name, label, endpoint_url, roles, deleted_at)"
                     " values ('old', 'Old', %s, array['grader'], now())", (ENDPOINT,))
        conn.execute("insert into helper.model (name, label, endpoint_url, roles)"
                     " values ('clash', 'Clash', %s, array['attacker'])", (ENDPOINT,))
        conn.execute("select connection.move_llm_and_helpers()")

    assert rows(dsn, project, "select name, provider, base_url, secret_ciphertext, deleted_at is not null"
                              " from connection.endpoint where kind = 'provider' order by name") == [
        ("clash-helper", "compatible", ENDPOINT, None, False),
        ("judge", "compatible", ENDPOINT, judge_token, False),
        ("llm-ollama", "ollama", "http://ollama.lab:11434", None, False),
        ("llm-openai", "openai", "", openai_token, False),
        ("old", "compatible", ENDPOINT, None, True),
    ]
    assert rows(dsn, project, "select connection, use, agent, roles, model, tool_name, deleted_at is not null"
                              " from connection.use order by connection") == [
        ("clash-helper", "tool", None, ["attacker"], None, "clash", False),
        ("judge", "tool", None, ["judge"], None, "judge", False),
        ("llm-openai", "agent", "card_agent", None, "g", None, False),
        ("old", "tool", None, ["grader"], None, "old", True),
    ]
    assert helper_store.resolve(project["pid"], "clash")["endpoint_url"] == ENDPOINT
    assert llm_store.resolve_choice(project["pid"], "card_agent")["ciphertext"] == openai_token


def test_the_move_runs_twice_without_doubling_anything(dsn, project):
    with project_db(dsn, project) as conn:
        conn.execute("insert into llm.provider (provider) values ('ollama')")
        conn.execute("insert into helper.model (name, label, endpoint_url, roles)"
                     " values ('judge', 'Judge', %s, array['judge'])", (ENDPOINT,))
        conn.execute("select connection.move_llm_and_helpers()")
        conn.execute("select connection.move_llm_and_helpers()")

    assert rows(dsn, project, "select count(*) from connection.endpoint where kind = 'provider'") == [(2,)]
    assert rows(dsn, project, "select count(*) from connection.use") == [(1,)]


def test_saving_a_connection_never_takes_over_a_provider_connection(dsn, project):
    from platform_service import connection_store, helper_store

    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge"], subject="t")

    with pytest.raises(connection_store.NameTaken):
        connection_store.save(project["pid"], "judge", {"label": "Mine", "kind": "openai",
                                                        "base_url": "https://system.example.com/v1", "model": "m"},
                              subject="t")
    assert helper_store.resolve(project["pid"], "judge")["endpoint_url"] == ENDPOINT


# ---- helpers next to connections made test tools on Connectivity ------------------------------------

def _admins_openai_made_a_tool(project, key):
    from platform_service import helper_store, llm_store

    llm_store.save_provider(project["pid"], "openai", ciphertext=llm_store.encrypt(key), subject="admin")
    llm_store.save_choice(project["pid"], "card_agent", "openai", "gpt-test", subject="admin", keyless_row=False)
    assert helper_store.use_as_tool(project["pid"], "llm-openai", roles=["judge"], subject="owner") is not None


def test_removing_a_helper_that_is_a_connection_made_a_tool_keeps_the_connection_its_key_and_its_agent(dsn, project):
    from platform_service import helper_store, llm_store

    key = new_key()
    _admins_openai_made_a_tool(project, key)

    assert helper_store.remove(project["pid"], "llm-openai") is True

    assert helper_store.resolve(project["pid"], "llm-openai") is None
    assert providers(dsn, project) == [("llm-openai", "openai", "", True, None)]
    assert llm_store.decrypt("openai", llm_store.resolve_choice(project["pid"], "card_agent")["ciphertext"]) == key


def test_saving_a_helper_never_rewrites_a_connection_made_a_tool_on_connectivity(dsn, project):
    from platform_service import connection_store, helper_store, llm_store

    _admins_openai_made_a_tool(project, new_key())

    with pytest.raises(connection_store.NameTaken):
        helper_store.save(project["pid"], "llm-openai", label="Mine", endpoint_url=ENDPOINT, roles=["judge"],
                          ciphertext=llm_store.encrypt(new_key()), subject="owner")
    assert providers(dsn, project) == [("llm-openai", "openai", "", True, None)]


def test_a_helper_whose_connection_an_agent_also_runs_on_keeps_that_connection_when_removed(dsn, project):
    from platform_service import helper_store, llm_store

    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["judge"],
                      ciphertext=llm_store.encrypt(new_key()), subject="t")
    llm_store.save_agent(project["pid"], "card_agent", "judge", "m", subject="admin")

    assert helper_store.remove(project["pid"], "judge") is True

    assert providers(dsn, project) == [("judge", "compatible", ENDPOINT, True, None)]


def test_a_connection_made_a_tool_under_a_name_another_helper_holds_is_refused(dsn, project):
    from platform_service import connection_store, helper_store

    connection_store.save_provider(project["pid"], "judge", label="Judge", provider="compatible",
                                   base_url="https://other.example.com/v1", subject="admin")
    helper_store.save(project["pid"], "judge", label="Judge", endpoint_url=ENDPOINT, roles=["attacker"], subject="t")

    assert helper_store.use_as_tool(project["pid"], "judge", roles=["judge"], subject="owner") is None
    assert uses(dsn, project) == [("judge-helper", "tool", None, ["attacker"], None, "judge")]


def test_an_ollama_connection_without_an_address_is_a_tool_at_the_stacks_ollama(dsn, project, monkeypatch):
    from platform_service import connection_store, helper_store

    monkeypatch.setenv("PLATFORM_OLLAMA_BASE_URL", "http://ollama.internal:11434")
    connection_store.save_provider(project["pid"], "local", label="Local", provider="ollama", subject="admin")
    helper_store.use_as_tool(project["pid"], "local", roles=["judge"], subject="owner")

    assert helper_store.resolve(project["pid"], "local")["endpoint_url"] == "http://ollama.internal:11434/v1"
    assert [h["endpoint_url"] for h in helper_store.list_models(project["pid"], "judge")] == [
        "http://ollama.internal:11434/v1"]
    assert helper_store.listing_of(project["pid"], "local")["base_url"] == "http://ollama.internal:11434"


def test_a_deleted_connection_saved_again_under_its_name_is_no_longer_a_tool_or_an_agents_model(dsn, project):
    from platform_service import connection_store, helper_store, llm_store

    connection_store.save_provider(project["pid"], "judge-x", label="Judge", provider="compatible",
                                   base_url=ENDPOINT, subject="admin")
    helper_store.use_as_tool(project["pid"], "judge-x", roles=["judge"], subject="owner")
    llm_store.save_agent(project["pid"], "card_agent", "judge-x", "m", subject="admin")

    assert connection_store.delete(project["pid"], "judge-x") is True
    connection_store.save_provider(project["pid"], "judge-x", label="Other", provider="compatible",
                                   base_url="https://k.example.com/v1", subject="admin")

    assert helper_store.list_models(project["pid"]) == []
    assert llm_store.resolve_choice(project["pid"], "card_agent") is None
    assert uses(dsn, project) == []
