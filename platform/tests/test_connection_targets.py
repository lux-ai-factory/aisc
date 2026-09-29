"""Endpoints belong to targets (targets plan v2, TG6 to TG9): a connection is the endpoint of one
target (the system or a card component), exactly one per target; a plugin run reaches the
endpoint of its evaluation's target through the platform. Connections are no longer engine
components of their own (O1): the target's mirror is what an evaluation picks. Runs on the
throwaway; the system under test is a local stub."""
from __future__ import annotations

import pytest

from platform_service import target_store
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, EngineFake, Stub, new_secret

pytestmark = needs_database
ALICE = "00000000-0000-0000-0000-00000000a11c"
K1 = "0b9c7a1e-0000-4000-8000-000000000001"
K2 = "0b9c7a1e-0000-4000-8000-000000000002"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("PLATFORM_SECRETS_KEY", SECRETS_KEY)
    monkeypatch.setenv("PLATFORM_CONNECTIONS_TOKEN", CONNECTIONS_TOKEN)
    monkeypatch.setenv("CONNECTIONS_ALLOWED_HOSTS", stub.host)
    monkeypatch.setenv("ENGINE_URL", stub.base)


@pytest.fixture
def admin(as_user):
    return as_user("root", roles=("admin",))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("ct")}, headers=as_user(ALICE)).json()
    target_store.upsert_component(made["pid"], f"component:{K1}", "Scoring model", "model", 1)
    target_store.upsert_component(made["pid"], f"component:{K2}", "Training data", "training_data", 1)
    return made


def body(stub, **over):
    b = {"label": "MCAS chat", "kind": "rest", "base_url": stub.base, "path": "/chat",
         "body_template": {"question": "{{input}}", "history": "{{history}}"}, "response_path": "answer",
         "timeout_s": 5, "secret": new_secret()}
    b.update(over)
    return b


def put(client, project, name, admin, b):
    return client.put(f"/projects/{project['slug']}/connections/{name}", json=b, headers=admin)


def internal(client, project, path, method="GET", token=CONNECTIONS_TOKEN):
    return client.request(method, f"/internal/projects/{project['pid']}/targets/{path}",
                          headers={"X-AISC-Service-Token": token})


# ── TG6 one endpoint per target ─────────────────────────────────────────────

def test_tg6_a_connection_is_the_endpoint_of_the_target_it_names(client, admin, project, stub):
    r = put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert r.status_code == 200, r.text
    assert r.json()["target"] == {"key": "system", "kind": "system", "label": project["name"]}


def test_tg6_a_second_endpoint_for_the_same_target_is_refused_naming_the_first(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = put(client, project, "mcas-api", admin, body(stub, target="system"))
    assert r.status_code == 409 and "mcas-chat" in r.json()["detail"]
    assert put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}")).status_code == 200


def test_tg6_an_unknown_target_is_refused(client, admin, project, stub):
    r = put(client, project, "mcas-chat", admin, body(stub, target="component:0b9c7a1e-0000-4000-8000-00000000dead"))
    assert r.status_code == 422 and "target" in r.json()["detail"]


def test_tg6_the_target_is_fixed_once_set(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = put(client, project, "mcas-chat", admin, body(stub, target=f"component:{K1}"))
    assert r.status_code == 422 and "new connection" in r.json()["detail"]
    assert put(client, project, "mcas-chat", admin, body(stub, label="MCAS assistant")).status_code == 200


def test_tg6_a_connection_without_a_target_can_be_given_one_later(client, admin, project, stub):
    assert put(client, project, "mcas-chat", admin, body(stub)).json()["target"] is None
    assert put(client, project, "mcas-chat", admin, body(stub, target="system")).json()["target"]["key"] == "system"


def test_tg6_deleting_a_connection_frees_its_target(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert client.delete(f"/projects/{project['slug']}/connections/mcas-chat", headers=admin).status_code == 204
    assert put(client, project, "mcas-api", admin, body(stub, target="system")).status_code == 200


def test_tg6_the_targets_list_names_each_targets_endpoint(client, admin, as_user, project, stub):
    put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}", label="Scorer API"))
    t = {x["key"]: x for x in client.get(f"/projects/{project['slug']}/targets", headers=as_user(ALICE)).json()["targets"]}
    assert t[f"component:{K1}"]["endpoint"] == {"name": "mcas-scorer", "label": "Scorer API", "kind": "rest"}
    assert t["system"]["endpoint"] is None


# ── TG7 and TG8 a run reaches its target's endpoint ─────────────────────────

def test_tg7_the_internal_route_gives_the_endpoint_of_a_target(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = internal(client, project, "system/connection")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "mcas-chat" and d["secret"] and d["target"]["key"] == "system"
    assert d["allowed_hosts"] == [stub.host]


def test_tg7_a_target_without_an_endpoint_says_so(client, admin, project, stub):
    r = internal(client, project, f"component:{K2}/connection")
    assert r.status_code == 404 and "Training data has no endpoint" in r.json()["detail"]


def test_tg7_the_route_needs_the_token_and_is_not_behind_the_gateway(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert internal(client, project, "system/connection", token="wrong").status_code == 401
    r = client.get(f"/internal/projects/{project['pid']}/targets/system/connection",
                   headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN, "X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 404
    assert internal(client, project, "not-a-key/connection").status_code == 404


def test_tg8_run_keys_are_issued_by_target(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = internal(client, project, "system/run-keys", method="POST")
    assert r.status_code == 201, r.text
    assert r.json()["endpoints"]["openai"]["model"] == "mcas-chat"
    assert internal(client, project, f"component:{K2}/run-keys", method="POST").status_code == 404


# ── TG9 connections are no engine components of their own (O1) ──────────────

def test_tg9_a_new_connection_makes_no_engine_component(client, admin, project, stub):
    engine = EngineFake(stub, project["pid"])
    r = put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert r.status_code == 200 and not [c for c in engine.components if "connection:" in str(c["json_value"])]


def test_tg9_an_older_connections_engine_component_is_renamed_legacy_and_kept(client, admin, project, stub, dsn):
    from tests.test_connections import one
    engine = EngineFake(stub, project["pid"])
    put(client, project, "mcas-chat", admin, body(stub))
    old = engine._create({"json": {"name": "MCAS chat", "component_type": "resource",
                                   "json_value": {"value": f"connection:{project['pid']}/mcas-chat"}}})
    one(dsn, project, "update connection.endpoint set engine_component = %s where name = 'mcas-chat' returning name",
        (old["pid"],))
    assert put(client, project, "mcas-chat", admin, body(stub, target="system")).status_code == 200
    assert old["name"] == "Legacy connection: MCAS chat, pick its target instead"
    assert engine.components == [old]


def test_tg8_the_run_key_names_the_connection_and_the_target_for_the_runs_record(client, admin, project, stub):
    put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}"))
    d = internal(client, project, f"component:{K1}/run-keys", method="POST").json()
    assert d["connection"] == "mcas-scorer"
    assert d["target"]["key"] == f"component:{K1}" and d["target"]["label"] == "Scoring model"


def test_tg7_the_descriptor_carries_its_target_so_the_fingerprint_follows_it(client, admin, project, stub, dsn):
    from aisc_plugin_interface import connections as c
    from tests.test_connections import one
    put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}"))
    d = internal(client, project, f"component:{K1}/connection").json()
    assert c.Descriptor.from_dict(d).target["key"] == f"component:{K1}"
    fingerprint = one(dsn, project, "select 1")  # noqa: F841 (keeps the bed warm)
    issued = internal(client, project, f"component:{K1}/run-keys", method="POST").json()
    stored = one(dsn, project, "select fingerprint from connection.run_key order by issued_at desc limit 1")[0]
    assert stored == c.Descriptor.from_dict(d).fingerprint() and issued["key"]
