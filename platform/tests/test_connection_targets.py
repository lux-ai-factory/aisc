"""Endpoints belong to targets: a connection is the endpoint of one
target (the system or a card component), exactly one per target; a plugin run reaches the
endpoint of its evaluation's target through the platform. Connections are not engine
components of their own: the target's mirror is what an evaluation picks. Runs on the
throwaway; the system under test is a local stub."""
from __future__ import annotations

import pytest

from platform_service import target_store
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, EngineFake, new_secret
from tests.http_stub import Stub

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
def project(make_project):
    made = make_project()
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


# One endpoint per target

def test_a_connection_is_the_endpoint_of_the_target_it_names(client, admin, project, stub):
    r = put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert r.status_code == 200, r.text
    assert r.json()["target"] == {"key": "system", "kind": "system", "label": project["name"]}


def test_a_second_endpoint_for_the_same_target_is_refused_naming_the_first(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = put(client, project, "mcas-api", admin, body(stub, target="system"))
    assert r.status_code == 409 and "mcas-chat" in r.json()["detail"]
    assert "already has a connection" in r.json()["detail"]
    assert put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}")).status_code == 200


def test_reviving_a_deleted_endpoint_whose_target_was_taken_names_the_target_and_the_holder(
        client, admin, project, stub):
    """The revive keeps the old target_key, the one-per-target index refuses it, and the 409 said
    "target: None already has an endpoint" (body.target, absent), naming neither the target nor the holder."""
    assert put(client, project, "mcas-chat", admin, body(stub, target="system")).status_code == 200
    assert client.delete(f"/projects/{project['slug']}/connections/mcas-chat", headers=admin).status_code == 204
    assert put(client, project, "mcas-api", admin, body(stub, target="system")).status_code == 200
    r = put(client, project, "mcas-chat", admin, body(stub))
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "None" not in detail and "system" in detail and "mcas-api" in detail, detail
    assert "already has a connection" in detail and "endpoint" not in detail, detail


def test_an_unknown_target_is_refused(client, admin, project, stub):
    r = put(client, project, "mcas-chat", admin, body(stub, target="component:0b9c7a1e-0000-4000-8000-00000000dead"))
    assert r.status_code == 422 and "is not the system or a component of this project" in r.json()["detail"]


def test_the_target_is_fixed_once_set(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = put(client, project, "mcas-chat", admin, body(stub, target=f"component:{K1}"))
    assert r.status_code == 422 and "create a new connection" in r.json()["detail"] and "endpoint" not in r.json()["detail"]
    assert put(client, project, "mcas-chat", admin, body(stub, label="MCAS assistant")).status_code == 200


def test_the_store_itself_keeps_a_target_once_set(client, admin, project, stub):
    """Checked in the write, not only before it: a save that names another target writes nothing."""
    from platform_service import connection_store

    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    with pytest.raises(connection_store.TargetSetOnce):
        connection_store.save(project["pid"], "mcas-chat", {"label": "moved", "kind": "rest", "base_url": stub.base,
                                                            "target_key": f"component:{K1}"},
                              subject="t")
    row = connection_store.get(project["pid"], "mcas-chat")
    assert (row["target_key"], row["label"]) == ("system", "MCAS chat")


def test_a_save_that_read_no_target_before_another_set_one_is_refused(client, admin, project, stub, monkeypatch):
    """Two admins save one connection with different targets: both read "no target yet"; the second
    write must not move it."""
    from platform_service import connection_store

    real_get = connection_store.get
    put(client, project, "mcas-chat", admin, body(stub))
    stale = real_get(project["pid"], "mcas-chat", with_deleted=True)        # what the second admin read
    assert stale["target_key"] is None
    put(client, project, "mcas-chat", admin, body(stub, target="system"))  # the first admin's save
    monkeypatch.setattr(connection_store, "get", lambda *a, **k: stale)
    r = put(client, project, "mcas-chat", admin, body(stub, target=f"component:{K1}"))
    assert r.status_code == 422 and "create a new connection" in r.json()["detail"] and "endpoint" not in r.json()["detail"]
    monkeypatch.setattr(connection_store, "get", real_get)
    assert connection_store.get(project["pid"], "mcas-chat")["target_key"] == "system"


def test_a_connection_without_a_target_can_be_given_one_later(client, admin, project, stub):
    assert put(client, project, "mcas-chat", admin, body(stub)).json()["target"] is None
    assert put(client, project, "mcas-chat", admin, body(stub, target="system")).json()["target"]["key"] == "system"


def test_deleting_a_connection_frees_its_target(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert client.delete(f"/projects/{project['slug']}/connections/mcas-chat", headers=admin).status_code == 204
    assert put(client, project, "mcas-api", admin, body(stub, target="system")).status_code == 200


def test_the_targets_list_names_each_targets_endpoint(client, admin, as_user, project, stub):
    put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}", label="Scorer API"))
    t = {x["key"]: x for x in client.get(f"/projects/{project['slug']}/targets", headers=as_user(ALICE)).json()["targets"]}
    assert t[f"component:{K1}"]["endpoint"] == {"name": "mcas-scorer", "label": "Scorer API", "kind": "rest"}
    assert t["system"]["endpoint"] is None


# A run reaches its target's endpoint

def test_the_internal_route_gives_the_endpoint_of_a_target(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = internal(client, project, "system/connection")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "mcas-chat" and "secret" not in d and d["has_secret"] is True and d["target"]["key"] == "system"
    assert d["allowed_hosts"] == [stub.host]


def test_a_target_without_an_endpoint_says_so(client, admin, project, stub):
    r = internal(client, project, f"component:{K2}/connection")
    assert r.status_code == 404 and "Training data has no endpoint" in r.json()["detail"]
    # the one 404 that lets a plugin skip an optional target says so (plugin-interface is_no_endpoint)
    assert r.json()["reason"] == "no_endpoint"


def test_the_route_needs_the_token_and_is_not_behind_the_gateway(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert internal(client, project, "system/connection", token="wrong").status_code == 401
    r = client.get(f"/internal/projects/{project['pid']}/targets/system/connection",
                   headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN, "X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 404
    assert internal(client, project, "not-a-key/connection").status_code == 404


def test_run_keys_are_issued_by_target(client, admin, project, stub):
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    r = internal(client, project, "system/run-keys", method="POST")
    assert r.status_code == 201, r.text
    assert r.json()["endpoints"]["openai"]["model"] == "mcas-chat"
    assert internal(client, project, f"component:{K2}/run-keys", method="POST").status_code == 404


def test_the_by_name_routes_are_guarded_by_the_one_internal_gate(client, admin, project, stub, monkeypatch):
    """The guard (gateway headers, token, constant-time compare, known project) was copied into the
    two by-name routes; a change to _internal_gate didn't reach them."""
    from fastapi.responses import JSONResponse

    from platform_service.routes import connections

    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    monkeypatch.setattr(connections, "_internal_gate", lambda pid, request, *_: JSONResponse({"detail": "gate"}, 418))
    headers = {"X-AISC-Service-Token": CONNECTIONS_TOKEN}
    base = f"/internal/projects/{project['pid']}/connections/mcas-chat"
    assert client.get(base, headers=headers).status_code == 418
    assert client.post(f"{base}/run-keys", headers=headers).status_code == 418


@pytest.mark.parametrize("path, method, status", [("system/connection", "GET", 200),
                                                  ("system/run-keys", "POST", 201)])
def test_a_target_route_runs_the_guard_once(client, admin, project, stub, monkeypatch, path, method, status):
    from platform_service import db

    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    looked_up = []
    real = db.get_project

    def counting(identifier):
        looked_up.append(identifier)
        return real(identifier)
    monkeypatch.setattr(db, "get_project", counting)
    r = internal(client, project, path, method=method)
    assert r.status_code == status, r.text
    assert looked_up == [project["pid"]]


# Connections are no engine components of their own

def test_a_new_connection_makes_no_engine_component(client, admin, project, stub):
    engine = EngineFake(stub, project["pid"])
    r = put(client, project, "mcas-chat", admin, body(stub, target="system"))
    assert r.status_code == 200 and not [c for c in engine.components if "connection:" in str(c["json_value"])]


def test_an_older_connections_engine_component_is_renamed_legacy_and_kept(client, admin, project, stub, dsn):
    from tests.conftest import one
    engine = EngineFake(stub, project["pid"])
    put(client, project, "mcas-chat", admin, body(stub))
    old = engine._create({"json": {"name": "MCAS chat", "component_type": "resource",
                                   "json_value": {"value": f"connection:{project['pid']}/mcas-chat"}}})
    one(dsn, project, "update connection.endpoint set engine_component = %s where name = 'mcas-chat' returning name",
        (old["pid"],))
    assert put(client, project, "mcas-chat", admin, body(stub, target="system")).status_code == 200
    assert old["name"] == "Legacy connection: MCAS chat, pick its target instead"
    # the connection makes no engine component of its own (its target's mirror is what evaluations pick)
    assert [c for c in engine.components if c["json_value"]["value"].startswith("connection:")] == [old]


def test_the_run_key_names_the_connection_and_the_target_for_the_runs_record(client, admin, project, stub):
    put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}"))
    d = internal(client, project, f"component:{K1}/run-keys", method="POST").json()
    assert d["connection"] == "mcas-scorer"
    assert d["target"]["key"] == f"component:{K1}" and d["target"]["label"] == "Scoring model"


def test_the_descriptor_carries_its_target_so_the_fingerprint_follows_it(client, admin, project, stub, dsn):
    from aisc_plugin_interface import connections as c
    from tests.conftest import one
    put(client, project, "mcas-scorer", admin, body(stub, target=f"component:{K1}"))
    d = internal(client, project, f"component:{K1}/connection").json()
    assert c.Descriptor.from_dict(d).target["key"] == f"component:{K1}"
    fingerprint = one(dsn, project, "select 1")  # noqa: F841 (keeps the bed warm)
    issued = internal(client, project, f"component:{K1}/run-keys", method="POST").json()
    stored = one(dsn, project, "select fingerprint from connection.run_key order by issued_at desc limit 1")[0]
    assert stored == c.Descriptor.from_dict(d).fingerprint() and issued["key"]


# What the evaluation form's target dropdown says

def _mirror(engine, project, key):
    return engine.named(f"target:{project['pid']}/{key}")["name"]


def test_binding_and_removing_an_endpoint_renames_the_target_at_once(client, admin, as_user, project, stub):
    from platform_service import targets
    engine = EngineFake(stub, project["pid"])
    # the system is offered in the engine once the project has an AI card version
    assert client.post(f"/projects/{project['slug']}/system-versions", json={"name": "MCAS", "version": "1.0.0"},
                       headers=as_user(ALICE)).status_code == 201
    targets.ensure_mirrors(project["pid"], "t")
    assert put(client, project, "mcas-chat", admin, body(stub, target="system")).status_code == 200
    assert _mirror(engine, project, "system") == f"AI card · System: {project['name']} · reached through REST API"
    assert _mirror(engine, project, f"component:{K1}").endswith("· not connected")
    assert client.delete(f"/projects/{project['slug']}/connections/mcas-chat", headers=admin).status_code == 204
    assert _mirror(engine, project, "system") == f"AI card · System: {project['name']} · not connected"


def test_the_run_key_says_what_the_platforms_endpoint_carries(client, admin, project, stub):
    """A plugin that needs more than text and a history (tool calls, logprobs) is refused against it."""
    put(client, project, "mcas-chat", admin, body(stub, target="system"))
    d = internal(client, project, "system/run-keys", method="POST").json()
    assert d["capabilities"] == ["text", "history"]
