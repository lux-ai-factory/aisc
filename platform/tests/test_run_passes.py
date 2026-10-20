"""A plugin run reaches only what its evaluation names. The worker, which holds the stack's connections
token, asks for a run pass naming the run's target and connection references; the plugin gets the pass,
never the token, and the internal routes open with it only for those references, until it expires or the
worker revokes it. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import pytest

from platform_service import db, target_store
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN, SECRETS_KEY, new_secret
from tests.http_stub import Stub

pytestmark = needs_database
K1 = "0b9c7a1e-0000-4000-8000-000000000001"


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


def made_with_endpoints(make_project, client, admin, stub):
    """A project whose system and component K1 each have an endpoint, plus a connection of no target."""
    made = make_project()
    target_store.upsert_component(made["pid"], f"component:{K1}", "Scoring model", "model", 1)
    for name, target in (("system-chat", "system"), ("model-api", f"component:{K1}"), ("spare", None)):
        b = {"label": name, "kind": "rest", "base_url": stub.base, "path": "/chat",
             "body_template": {"question": "{{input}}"}, "response_path": "answer", "timeout_s": 5,
             "secret": new_secret()}
        if target:
            b["target"] = target
        r = client.put(f"/projects/{made['slug']}/connections/{name}", json=b, headers=admin)
        assert r.status_code in (200, 201), r.text
    return made


@pytest.fixture
def project(make_project, client, admin, stub):
    return made_with_endpoints(make_project, client, admin, stub)


def mint(client, refs, token=CONNECTIONS_TOKEN, **headers):
    return client.post("/internal/run-passes", json={"refs": refs},
                       headers={"X-AISC-Service-Token": token, **headers})


def with_pass(client, run_pass, project, path, method="GET"):
    return client.request(method, f"/internal/projects/{project['pid']}/{path}",
                          headers={"X-AISC-Run-Pass": run_pass})


def test_the_worker_mints_a_pass_for_its_runs_references(client, project):
    r = mint(client, [f"target:{project['pid']}/system"])
    assert r.status_code == 201, r.text
    assert r.json()["pass"] and r.json()["expires_at"]


def test_minting_needs_the_token_and_is_not_behind_the_gateway(client, project):
    assert mint(client, [f"target:{project['pid']}/system"], token="wrong").status_code == 401
    assert mint(client, [f"target:{project['pid']}/system"], **{"X-Forwarded-For": "1.2.3.4"}).status_code == 404


@pytest.mark.parametrize("refs", [[], ["file:x"], ["target:not-a-pid/system"], "target:x/system"])
def test_a_pass_names_at_least_one_well_formed_reference(client, project, refs):
    assert mint(client, refs).status_code == 422


def test_a_pass_is_not_minted_for_a_project_that_does_not_exist(client, project):
    assert mint(client, ["target:00000000-0000-4000-8000-0000000000aa/system"]).status_code == 404


def test_the_pass_opens_its_own_target_and_nothing_else_in_the_project(client, project):
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    r = with_pass(client, run_pass, project, "targets/system/connection")
    assert r.status_code == 200 and r.json()["name"] == "system-chat"
    assert with_pass(client, run_pass, project, "targets/system/run-keys", "POST").status_code == 201
    # another target, a connection by name, the same target's connection by name
    for path in (f"targets/component:{K1}/connection", "connections/spare", "connections/system-chat"):
        assert with_pass(client, run_pass, project, path).status_code == 403, path
    assert with_pass(client, run_pass, project, "connections/spare/run-keys", "POST").status_code == 403


def test_a_connection_reference_opens_that_connection_by_name(client, project):
    run_pass = mint(client, [f"connection:{project['pid']}/spare"]).json()["pass"]
    assert with_pass(client, run_pass, project, "connections/spare").status_code == 200
    assert with_pass(client, run_pass, project, "connections/spare/run-keys", "POST").status_code == 201
    assert with_pass(client, run_pass, project, "targets/system/connection").status_code == 403


def test_the_pass_opens_nothing_in_another_project(client, project, make_project, admin, stub):
    other = made_with_endpoints(make_project, client, admin, stub)
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    assert with_pass(client, run_pass, other, "targets/system/connection").status_code == 403
    assert with_pass(client, run_pass, other, "connections/system-chat").status_code == 403


def test_an_unknown_or_expired_pass_is_refused(client, project):
    assert with_pass(client, "aisc-rp-nothing", project, "targets/system/connection").status_code == 401
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    with db.pool().connection() as conn:
        conn.execute("UPDATE core.run_pass SET expires_at = now() - interval '1 second'")
    assert with_pass(client, run_pass, project, "targets/system/connection").status_code == 401


def test_the_worker_revokes_the_pass_when_the_run_ends(client, project):
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    r = client.delete("/internal/run-passes", headers={"X-AISC-Run-Pass": run_pass})
    assert r.status_code == 204
    assert with_pass(client, run_pass, project, "targets/system/connection").status_code == 401
    assert client.delete("/internal/run-passes", headers={"X-AISC-Run-Pass": run_pass}).status_code == 204


def test_only_the_pass_hash_is_kept(client, project):
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM core.run_pass").fetchall()
    assert rows and run_pass not in repr(rows)


def test_a_pass_cannot_mint_another_pass(client, project):
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    r = client.post("/internal/run-passes", json={"refs": [f"target:{project['pid']}/component:{K1}"]},
                    headers={"X-AISC-Run-Pass": run_pass})
    assert r.status_code == 401


def test_no_role_but_the_platforms_own_reads_the_passes(client, project):
    with db.pool().connection() as conn:
        grantees = {r["grantee"] for r in conn.execute(
            "SELECT grantee FROM information_schema.role_table_grants"
            " WHERE table_schema = 'core' AND table_name = 'run_pass'").fetchall()}
        owner = conn.execute("SELECT tableowner FROM pg_tables WHERE schemaname = 'core'"
                             " AND tablename = 'run_pass'").fetchone()["tableowner"]
    assert grantees <= {owner}, grantees
