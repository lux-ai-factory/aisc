"""The internal hosts a project's connections may reach, managed from the UI: per project, edited by its owners and platform admins; the deployment's
CONNECTIONS_ALLOWED_HOSTS stays as a floor nobody can remove here; the stack's own services and
cloud metadata addresses are never allowed from the UI, checked when an entry is saved and again,
on the resolved address, at every call. Changes apply at once, with no restart. Runs on the
throwaway; the system under test is a local stub on loopback, which is refused unless allowed."""
from __future__ import annotations

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import connection_allowlist, projectdb
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, Stub, engine_component, new_secret, private_address

pytestmark = needs_database
ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-000000000b0b"
EVE = "00000000-0000-0000-0000-000000000e0e"


PRIVATE = private_address()


@pytest.fixture
def stub():
    """The system under test on a private address of this machine: internal, so refused unless
    allowed, and not loopback, which the UI can never allow (loopback is the platform itself)."""
    if PRIVATE is None:
        pytest.skip("this machine has no private non-loopback address for the stub")
    s = Stub(bind=PRIVATE)
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.delenv("CONNECTIONS_ALLOWED_HOSTS", raising=False)     # no floor unless a test sets one
    monkeypatch.setenv("ENGINE_URL", stub.base)


@pytest.fixture
def names(monkeypatch):
    """What each name resolves to, as the platform sees it: nothing unless a test says so, so the
    stack's service names (postgres, keycloak, ...) resolve only where a test puts them."""
    table: dict[str, set[str]] = {}
    monkeypatch.setattr(connection_allowlist, "resolve", lambda host: set(table.get(host, set())))
    return table


@pytest.fixture
def admin(as_user):
    return as_user("root", roles=("admin",))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("allow")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()


def hosts(project):
    return f"/projects/{project['slug']}/allowed-hosts"


def connect(client, admin, project, stub, name="mcas-chat"):
    """A connection to the stub (loopback: refused unless allowed)."""
    engine_component(stub, project["pid"])
    stub.route("POST", "/chat", (200, {"answer": "Up to 5,000 EUR."}))
    body = {"label": "MCAS chat", "kind": "rest", "base_url": stub.base, "path": "/chat",
            "body_template": {"question": "{{input}}", "history": "{{history}}"}, "response_path": "answer",
            "timeout_s": 5, "secret": new_secret()}
    r = client.put(f"/projects/{project['slug']}/connections/{name}", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return name


def probe(client, admin, project, name="mcas-chat"):
    return client.post(f"/projects/{project['slug']}/connections/{name}/test", json={}, headers=admin).json()


def member(client, as_user, project, subject, role):
    r = client.post(f"/projects/{project['slug']}/members", json={"subject": subject, "role": role},
                    headers=as_user(ALICE))
    assert r.status_code == 201, r.text


# The list and who edits it

def test_a1_an_owner_adds_an_entry_and_sees_it_with_who_and_when(client, as_user, project, names):
    r = client.put(f"{hosts(project)}/host.docker.internal:8500", json={"note": "MCAS-lite"}, headers=as_user(ALICE))
    assert r.status_code == 200, r.text
    listed = client.get(hosts(project), headers=as_user(ALICE)).json()
    (entry,) = listed["entries"]
    assert entry["host"] == "host.docker.internal:8500" and entry["note"] == "MCAS-lite"
    assert entry["updated_by"] and entry["updated_at"]
    assert listed["floor"] == []


def test_a1_a_platform_admin_edits_it_too(client, admin, project, names):
    assert client.put(f"{hosts(project)}/mcas.internal", json={}, headers=admin).status_code == 200


def test_a2_an_editor_may_not_and_a_stranger_is_told_nothing(client, as_user, project, names):
    member(client, as_user, project, BOB, "editor")
    assert client.put(f"{hosts(project)}/mcas.internal", json={}, headers=as_user(BOB)).status_code == 403
    assert client.get(hosts(project), headers=as_user(BOB)).status_code == 403
    assert client.put(f"{hosts(project)}/mcas.internal", json={}, headers=as_user(EVE)).status_code == 404
    assert client.get(hosts(project), headers=as_user(EVE)).status_code == 404


@pytest.mark.parametrize("bad", ["http://mcas.internal", "mcas internal", "mcas.internal:0", "mcas.internal:70000",
                                 "mcas.internal:x", "-mcas", "a" * 254, "mcas..internal", "*.internal"])
def test_a3_an_entry_is_a_host_or_host_and_port(client, as_user, project, names, bad):
    r = client.put(f"{hosts(project)}/{bad}", json={}, headers=as_user(ALICE))
    assert r.status_code in (404, 422), (bad, r.status_code)
    assert client.get(hosts(project), headers=as_user(ALICE)).json()["entries"] == []


def test_a3_entries_are_kept_lower_case_and_an_ip_literal_works(client, as_user, project, names):
    assert client.put(f"{hosts(project)}/MCAS.Internal:8500", json={}, headers=as_user(ALICE)).status_code == 200
    assert client.put(f"{hosts(project)}/10.1.2.3", json={}, headers=as_user(ALICE)).status_code == 200
    got = {e["host"] for e in client.get(hosts(project), headers=as_user(ALICE)).json()["entries"]}
    assert got == {"mcas.internal:8500", "10.1.2.3"}


def test_a3_removing_an_entry(client, as_user, project, names):
    client.put(f"{hosts(project)}/mcas.internal", json={}, headers=as_user(ALICE))
    assert client.delete(f"{hosts(project)}/mcas.internal", headers=as_user(ALICE)).status_code == 204
    assert client.delete(f"{hosts(project)}/mcas.internal", headers=as_user(ALICE)).status_code == 404


# The deny list, when saving

@pytest.mark.parametrize("denied", ["postgres", "postgres:5432", "Keycloak:8080", "platform", "aisc-backend",
                                    "minio:9000", "169.254.169.254", "metadata.google.internal", "localhost:8000",
                                    "127.0.0.1", "127.0.0.53:53"])
def test_a4_the_stacks_own_services_and_metadata_are_never_allowed(client, as_user, project, names, denied):
    r = client.put(f"{hosts(project)}/{denied}", json={}, headers=as_user(ALICE))
    assert r.status_code == 422 and "never" in r.json()["detail"], (denied, r.text)


def test_a4_a_name_that_resolves_to_a_stack_service_is_refused(client, as_user, project, names):
    names["postgres"] = {"172.20.0.5"}
    names["sneaky.internal"] = {"172.20.0.5"}
    r = client.put(f"{hosts(project)}/sneaky.internal:5432", json={}, headers=as_user(ALICE))
    assert r.status_code == 422 and "postgres" in r.json()["detail"]
    assert client.put(f"{hosts(project)}/172.20.0.5", json={}, headers=as_user(ALICE)).status_code == 422


# The deployment's floor

def test_a5_the_env_entries_are_listed_read_only(client, as_user, project, names, monkeypatch):
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", "host.docker.internal:8500, ollama:11434")
    listed = client.get(hosts(project), headers=as_user(ALICE)).json()
    assert listed["floor"] == ["host.docker.internal:8500", "ollama:11434"]
    r = client.delete(f"{hosts(project)}/ollama:11434", headers=as_user(ALICE))
    assert r.status_code == 409 and "deployment" in r.json()["detail"]
    assert client.put(f"{hosts(project)}/ollama:11434", json={}, headers=as_user(ALICE)).status_code == 409


# Changes apply at once, everywhere the platform calls

def test_a6_the_test_button_follows_the_list_without_a_restart(client, admin, project, stub, names):
    name = connect(client, admin, project, stub)
    assert probe(client, admin, project, name)["error"] == "blocked"
    assert client.put(f"{hosts(project)}/{stub.host}", json={}, headers=admin).status_code == 200
    out = probe(client, admin, project, name)
    assert out["ok"] is True and out["answer"].startswith("Up to 5,000")
    client.delete(f"{hosts(project)}/{stub.host}", headers=admin)
    assert probe(client, admin, project, name)["error"] == "blocked"


def test_a7_the_protocol_endpoints_follow_it_too(client, admin, project, stub, names):
    name = connect(client, admin, project, stub)
    key = client.post(f"/internal/projects/{project['pid']}/connections/{name}/run-keys",
                      headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN}).json()["key"]
    ask = lambda: client.post(f"/internal/facade/{project['pid']}/{name}/aisc/ask", json={"input": "q"},
                              headers={"Authorization": f"Bearer {key}"})
    assert ask().status_code == 502 and ask().json()["error"] == "blocked"
    client.put(f"{hosts(project)}/{stub.host}", json={}, headers=admin)
    assert ask().status_code == 200 and ask().json()["output"].startswith("Up to 5,000")


def test_a8_the_resolve_route_hands_the_run_its_projects_rule(client, admin, project, stub, names, monkeypatch):
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", "ollama:11434")
    names["postgres"] = {"172.20.0.5"}
    name = connect(client, admin, project, stub)
    client.put(f"{hosts(project)}/{stub.host}", json={}, headers=admin)
    d = client.get(f"/internal/projects/{project['pid']}/connections/{name}",
                   headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN}).json()
    assert d["allowed_hosts"] == ["ollama:11434", stub.host]
    assert "172.20.0.5" in d["denied_addresses"] and "169.254.169.254" in d["denied_addresses"]


def test_a9_one_projects_list_opens_nothing_for_another(client, admin, as_user, project, stub, names, unique):
    other = client.post("/projects", json={"name": unique("other")}, headers=as_user(ALICE)).json()
    connect(client, admin, project, stub)
    connect(client, admin, other, stub)
    client.put(f"{hosts(project)}/{stub.host}", json={}, headers=admin)
    assert probe(client, admin, project)["ok"] is True
    assert probe(client, admin, other)["error"] == "blocked"


# The deny list at call time, and the floor's exemption

def test_a10_an_entry_later_pointing_at_a_stack_service_is_refused_at_the_call(client, admin, project, stub, names):
    name = connect(client, admin, project, stub)
    names["postgres"] = {"10.0.0.5"}
    assert client.put(f"{hosts(project)}/{stub.host}", json={}, headers=admin).status_code == 200
    assert probe(client, admin, project, name)["ok"] is True
    names["postgres"] = {PRIVATE}              # the stub's address is now a stack service's
    out = probe(client, admin, project, name)
    assert out["ok"] is False and out["error"] == "blocked" and "never" in out["detail"]


def test_a11_the_floor_may_still_allow_what_the_ui_never_can(client, admin, project, stub, names, monkeypatch):
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    names["postgres"] = {PRIVATE}
    name = connect(client, admin, project, stub)
    assert probe(client, admin, project, name)["ok"] is True


# Stored in the project's own database

def test_a12_entries_live_in_the_projects_database(client, as_user, project, names, dsn):
    client.put(f"{hosts(project)}/mcas.internal:8500", json={"note": "n"}, headers=as_user(ALICE))
    with psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(project["pid"]))) as conn:
        row = conn.execute("select host, note, updated_by from connection.allowed_host").fetchone()
    assert row[0] == "mcas.internal:8500" and row[1] == "n" and row[2]
