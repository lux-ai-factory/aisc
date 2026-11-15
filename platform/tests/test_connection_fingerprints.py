"""The engine asks the platform, when a run starts, which endpoint each connection or target of the run would
reach: the same fingerprint a run key and a recorded use carry, never the key or the full endpoint. The route
is for the engine's container only, with its own token, and refused through the gateway."""
from __future__ import annotations

import pytest

from platform_service import connection_store
from platform_service.routes.connections import descriptor_of
from tests.conftest import needs_database
from tests.connection_support import CONNECTIONS_TOKEN
from tests.test_run_passes import _env, made_with_endpoints, stub  # noqa: F401  (fixtures)

pytestmark = needs_database

ENGINE_TOKEN = "engine-fingerprints-token-for-tests"
HEADER = "X-AISC-Service-Token"


@pytest.fixture(autouse=True)
def _engine_token(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


def fingerprint_of(project, name):
    from aisc_plugin_interface.connections import Descriptor
    row = connection_store.descriptor(project["pid"], name)
    return Descriptor.from_dict(descriptor_of(row, project["pid"])).fingerprint()


def asking(client, pid, refs, token=ENGINE_TOKEN, **headers):
    sent = {HEADER: token, **headers} if token else headers
    return client.post(f"/internal/projects/{pid}/connections/fingerprints", json={"refs": refs}, headers=sent)


def test_fingerprints_route_refuses_without_engine_token(client, project):
    assert asking(client, project["pid"], ["connection:system-chat"], token=None).status_code in (401, 503)
    assert asking(client, project["pid"], ["connection:system-chat"], token=CONNECTIONS_TOKEN).status_code == 401


def test_fingerprint_matches_the_recorded_use(client, project):
    r = asking(client, project["pid"], ["connection:system-chat", "target:system"])
    assert r.status_code == 200, r.text
    assert r.json() == {"connections": [
        {"ref": "connection:system-chat", "connection": "system-chat", "kind": "rest",
         "endpoint_sha256": fingerprint_of(project, "system-chat")},
        {"ref": "target:system", "connection": "system-chat", "kind": "rest",
         "endpoint_sha256": fingerprint_of(project, "system-chat")}]}


def test_the_answer_holds_no_key_and_no_endpoint(client, project, stub):  # noqa: F811
    r = asking(client, project["pid"], ["connection:system-chat"])
    assert r.status_code == 200, r.text
    assert stub.base not in r.text and "sk-test-" not in r.text


def test_an_unknown_reference_is_404_and_a_deleted_connection_410(client, project, admin):
    assert asking(client, project["pid"], ["connection:system-chat"]).status_code == 200
    assert asking(client, project["pid"], ["connection:no-such"]).status_code == 404
    gone = client.delete(f"/projects/{project['slug']}/connections/spare", headers=admin)
    assert gone.status_code in (200, 204), gone.text
    assert asking(client, project["pid"], ["connection:spare"]).status_code == 410


def test_more_than_thirty_two_references_are_refused(client, project):
    assert asking(client, project["pid"], ["connection:system-chat"] * 32).status_code == 200
    assert asking(client, project["pid"], ["connection:system-chat"] * 33).status_code == 422


def test_through_the_gateway_it_is_not_here(client, project):
    assert asking(client, project["pid"], ["connection:system-chat"]).status_code == 200
    r = asking(client, project["pid"], ["connection:system-chat"], **{"X-Forwarded-Host": "localhost:8100"})
    assert r.status_code == 404
