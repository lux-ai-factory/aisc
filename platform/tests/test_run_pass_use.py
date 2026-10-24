"""The platform records which connection served a run. The worker mints the run's pass naming the
evaluation plugin it runs; every resolve and every run-key issuance under that pass is kept: the
connection, its kind and its fingerprint at that moment, never its key or the run key. Results read it
back to say what the run reached. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import uuid

import pytest

from platform_service import connection_store, db, run_passes
from platform_service.routes.connections import descriptor_of
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN
from tests.test_run_passes import _env, made_with_endpoints, stub, with_pass  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


def mint(client, refs, evaluation_plugin=None):
    body = {"refs": refs}
    if evaluation_plugin is not None:
        body["evaluation_plugin"] = evaluation_plugin
    return client.post("/internal/run-passes", json=body, headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})


def fingerprint_of(project, name):
    from aisc_plugin_interface.connections import Descriptor
    row = connection_store.descriptor(project["pid"], name)
    return Descriptor.from_dict(descriptor_of(row, project["pid"])).fingerprint()


def test_a_resolve_under_the_pass_records_the_connection_and_its_fingerprint(client, project):
    plugin = str(uuid.uuid4())
    run_pass = mint(client, [f"target:{project['pid']}/system"], plugin).json()["pass"]
    assert with_pass(client, run_pass, project, "targets/system/connection").status_code == 200
    uses = run_passes.uses_of(plugin)
    assert [(u["connection"], u["protocol"], u["fingerprint"]) for u in uses] == \
        [("system-chat", "rest", fingerprint_of(project, "system-chat"))]
    assert uses[0]["used_at"] is not None


def test_a_run_key_issued_under_the_pass_is_recorded_too_in_time_order(client, project):
    plugin = str(uuid.uuid4())
    run_pass = mint(client, [f"target:{project['pid']}/system", f"connection:{project['pid']}/spare"],
                    plugin).json()["pass"]
    assert with_pass(client, run_pass, project, "targets/system/run-keys", "POST").status_code == 201
    assert with_pass(client, run_pass, project, "connections/spare").status_code == 200
    assert with_pass(client, run_pass, project, "connections/spare/run-keys", "POST").status_code == 201
    uses = run_passes.uses_of(plugin)
    assert [u["connection"] for u in uses] == ["system-chat", "spare", "spare"]
    assert [u["used_at"] for u in uses] == sorted(u["used_at"] for u in uses)
    assert uses[0]["fingerprint"] == fingerprint_of(project, "system-chat")


def test_the_use_keeps_the_kind_and_fingerprint_of_that_moment(client, project, admin, stub):  # noqa: F811
    plugin = str(uuid.uuid4())
    run_pass = mint(client, [f"connection:{project['pid']}/spare"], plugin).json()["pass"]
    with_pass(client, run_pass, project, "connections/spare")
    before = fingerprint_of(project, "spare")
    r = client.put(f"/projects/{project['slug']}/connections/spare", headers=admin, json={
        "label": "spare", "kind": "openai", "base_url": stub.base, "model": "m", "timeout_s": 5})
    assert r.status_code in (200, 201), r.text
    assert fingerprint_of(project, "spare") != before
    assert [(u["protocol"], u["fingerprint"]) for u in run_passes.uses_of(plugin)] == [("rest", before)]


def test_nothing_is_recorded_without_a_pass_or_for_a_pass_of_no_evaluation_plugin(client, project):
    assert mint(client, [f"target:{project['pid']}/system"]).status_code == 201   # an older worker
    with db.pool().connection() as conn:
        before = conn.execute("SELECT count(*) AS n FROM core.run_pass_use").fetchone()["n"]
    run_pass = mint(client, [f"target:{project['pid']}/system"]).json()["pass"]
    assert with_pass(client, run_pass, project, "targets/system/connection").status_code == 200
    r = client.get(f"/internal/projects/{project['pid']}/connections/spare",
                   headers={"X-AISC-Service-Token": CONNECTIONS_TOKEN})
    assert r.status_code == 200
    with db.pool().connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM core.run_pass_use").fetchone()["n"] == before


def test_a_refused_call_records_nothing(client, project):
    plugin = str(uuid.uuid4())
    run_pass = mint(client, [f"target:{project['pid']}/system"], plugin).json()["pass"]
    assert with_pass(client, run_pass, project, "connections/spare").status_code == 403
    assert run_passes.uses_of(plugin) == []


def test_the_evaluation_plugin_must_be_a_uuid(client, project):
    assert mint(client, [f"target:{project['pid']}/system"], "not-a-uuid").status_code == 422


def test_neither_the_key_nor_the_run_key_is_stored(client, project):
    plugin = str(uuid.uuid4())
    run_pass = mint(client, [f"target:{project['pid']}/system"], plugin).json()["pass"]
    secret = with_pass(client, run_pass, project, "targets/system/connection").json()["secret"]
    run_key = with_pass(client, run_pass, project, "targets/system/run-keys", "POST").json()["key"]
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT * FROM core.run_pass_use WHERE evaluation_plugin = %s", (plugin,)).fetchall()
    assert len(rows) == 2
    assert secret not in repr(rows) and run_key not in repr(rows) and run_pass not in repr(rows)


def test_the_uses_outlive_the_pass(client, project):
    plugin = str(uuid.uuid4())
    run_pass = mint(client, [f"target:{project['pid']}/system"], plugin).json()["pass"]
    with_pass(client, run_pass, project, "targets/system/connection")
    client.delete("/internal/run-passes", headers={"X-AISC-Run-Pass": run_pass})
    assert [u["connection"] for u in run_passes.uses_of(plugin)] == ["system-chat"]


def test_no_role_but_the_platforms_own_reads_the_uses(client, project):
    with db.pool().connection() as conn:
        grantees = {r["grantee"] for r in conn.execute(
            "SELECT grantee FROM information_schema.role_table_grants"
            " WHERE table_schema = 'core' AND table_name = 'run_pass_use'").fetchall()}
        owner = conn.execute("SELECT tableowner FROM pg_tables WHERE schemaname = 'core'"
                             " AND tablename = 'run_pass_use'").fetchone()["tableowner"]
    assert grantees <= {owner}, grantees
