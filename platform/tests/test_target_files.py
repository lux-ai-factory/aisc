"""A component of the AI card reached by an uploaded file: a model file or a dataset, uploaded in Manage
(PUT /projects/{slug}/targets/{key}/file?name=<file name>, the bytes as the body). The platform makes one engine component of the matching type
for the target, through the engine's own API with the caller's token, and uploads the bytes to it, so
the evaluation form lists it as it lists any model or dataset. Runs on the throwaway; the engine and
qualification are local fakes."""
from __future__ import annotations

import hashlib

import pytest

from tests.conftest import needs_database
from tests.connection_support import EngineFake
from tests.http_stub import Stub
from tests.test_targets_sync import K1, K2, K3, card, jsonld, sync, version

pytestmark = needs_database
BOB = "00000000-0000-0000-0000-000000000b0b"
ONNX = b"\x08\x07onnx model bytes" * 64


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("ENGINE_URL", stub.base)
    monkeypatch.setenv("QUALIFICATION_URL", stub.base + "/qualification")


class EngineWithFiles(EngineFake):
    """The engine fake, also taking a component's file (PUT /api/v1/components/<pid>/data)."""

    def __init__(self, stub, platform_pid):
        super().__init__(stub, platform_pid)
        self.uploads: dict[str, list[bytes]] = {}

    def _create(self, request):
        comp = super()._create(request)
        self.stub.route("PUT", f"/api/v1/components/{comp['pid']}/data", (200, lambda r, c=comp: self._upload(c, r)))
        return comp

    def _upload(self, comp, request):
        self.uploads.setdefault(comp["pid"], []).append(request.body)
        return {"file_name": "stored.bin", "file_size": len(request.body)}

    def carrying(self, target: str) -> list[dict]:
        return [c for c in self.components if (c.get("json_value") or {}).get("card_target") == target]


@pytest.fixture
def carded(client, as_user, project, stub):
    """A project whose card lists a model, training data and a rule engine, synced into targets."""
    engine = EngineWithFiles(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model"), (K2, "Training data", "training_data"),
                                   (K3, "Policy rules", "rule_engine")))
    assert sync(client, as_user, project).status_code == 200
    return engine


def upload(client, project, key, headers, data=ONNX, name="scoring.onnx"):
    return client.put(f"/projects/{project['slug']}/targets/{key}/file", params={"name": name}, content=data,
                      headers={**headers, "Content-Type": "application/octet-stream"})


def targets_of(client, project, headers):
    r = client.get(f"/projects/{project['slug']}/targets", headers=headers)
    assert r.status_code == 200, r.text
    return {t["key"]: t for t in r.json()["targets"]}


def test_a_model_file_becomes_one_engine_model_component_carrying_the_bytes(client, admin, project, carded):
    r = upload(client, project, f"component:{K1}", admin)
    assert r.status_code == 200, r.text
    made = carded.carrying(f"target:{project['pid']}/component:{K1}")
    assert len(made) == 1
    assert made[0]["component_type"] == "model"
    assert made[0]["name"] == "AI card · Component: Scoring model (model) · uploaded file"
    assert len(carded.uploads[made[0]["pid"]]) == 1 and ONNX in carded.uploads[made[0]["pid"]][0]
    assert b'filename="scoring.onnx"' in carded.uploads[made[0]["pid"]][0]


def test_a_data_component_becomes_an_engine_dataset(client, admin, project, carded):
    assert upload(client, project, f"component:{K2}", admin, data=b"a,b\n1,2\n", name="train.csv").status_code == 200
    made = carded.carrying(f"target:{project['pid']}/component:{K2}")
    assert [c["component_type"] for c in made] == ["dataset"]


def test_the_target_says_its_file_its_size_and_its_hash(client, admin, project, carded):
    upload(client, project, f"component:{K1}", admin)
    t = targets_of(client, project, admin)[f"component:{K1}"]
    assert t["file"]["name"] == "scoring.onnx"
    assert t["file"]["size"] == len(ONNX)
    assert t["file"]["sha256"] == hashlib.sha256(ONNX).hexdigest()
    assert t["file"]["uploaded_at"]
    assert t["engine_file_component"] == carded.carrying(f"target:{project['pid']}/component:{K1}")[0]["pid"]


def test_a_second_upload_replaces_the_file_on_the_same_engine_component(client, admin, project, carded):
    upload(client, project, f"component:{K1}", admin)
    newer = b"newer model" * 10
    assert upload(client, project, f"component:{K1}", admin, data=newer, name="v2.onnx").status_code == 200
    made = carded.carrying(f"target:{project['pid']}/component:{K1}")
    assert len(made) == 1 and len(carded.uploads[made[0]["pid"]]) == 2
    t = targets_of(client, project, admin)[f"component:{K1}"]
    assert t["file"]["name"] == "v2.onnx" and t["file"]["sha256"] == hashlib.sha256(newer).hexdigest()


def test_each_target_says_which_kind_of_file_it_takes(client, admin, project, carded):
    t = targets_of(client, project, admin)
    assert t[f"component:{K1}"]["file_kind"] == "model"
    assert t[f"component:{K2}"]["file_kind"] == "dataset"
    assert t[f"component:{K3}"]["file_kind"] is None
    assert t["system"]["file_kind"] is None
    assert t[f"component:{K1}"]["file"] is None


@pytest.mark.parametrize("target_key", ["system", f"component:{K3}"])
def test_a_target_that_takes_no_file_is_refused(client, admin, project, carded, target_key):
    r = upload(client, project, target_key, admin)
    assert r.status_code == 422, r.text
    assert carded.uploads == {}


def test_an_unknown_target_is_404(client, admin, project, carded):
    assert upload(client, project, "component:0b9c7a1e-0000-4000-8000-0000000000ff", admin).status_code == 404


def test_an_empty_file_is_refused(client, admin, project, carded):
    assert upload(client, project, f"component:{K1}", admin, data=b"").status_code == 422
    assert carded.components and not carded.carrying(f"target:{project['pid']}/component:{K1}")


def test_a_file_above_the_limit_is_refused_before_the_engine_is_asked(client, admin, project, carded, monkeypatch):
    monkeypatch.setenv("TARGET_FILE_MAX_MB", "1")
    r = upload(client, project, f"component:{K1}", admin, data=b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413, r.text
    assert not carded.carrying(f"target:{project['pid']}/component:{K1}")


def test_only_who_manages_connections_may_upload(client, as_user, make_project, stub):
    project = make_project(editors=(BOB,))
    carded_engine = EngineWithFiles(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model")))
    sync(client, as_user, project)
    assert upload(client, project, f"component:{K1}", as_user(BOB)).status_code == 403
    assert carded_engine.uploads == {}


def test_a_target_with_a_file_and_no_endpoint_says_so_in_its_mirrors_name(client, admin, as_user, project, carded):
    upload(client, project, f"component:{K1}", admin)
    sync(client, as_user, project)
    assert carded.named(f"target:{project['pid']}/component:{K1}")["name"] == \
        "AI card · Component: Scoring model (model) · uploaded file, no endpoint"


def test_a_file_without_a_name_is_refused(client, admin, project, carded):
    r = client.put(f"/projects/{project['slug']}/targets/component:{K1}/file", content=ONNX, headers=admin)
    assert r.status_code == 422, r.text


def test_an_engine_that_refuses_the_file_records_nothing(client, admin, project, carded, stub):
    upload(client, project, f"component:{K1}", admin)
    made = carded.carrying(f"target:{project['pid']}/component:{K1}")[0]
    stub.route("PUT", f"/api/v1/components/{made['pid']}/data", (500, {"detail": "boom"}))
    r = upload(client, project, f"component:{K1}", admin, data=b"other", name="other.onnx")
    assert r.status_code == 502, r.text
    assert targets_of(client, project, admin)[f"component:{K1}"]["file"]["name"] == "scoring.onnx"


def test_an_upload_is_recorded_in_the_ledger_with_the_files_hash(client, admin, project, carded, monkeypatch):
    import os

    import psycopg
    from psycopg.conninfo import make_conninfo

    from platform_service import projectdb

    monkeypatch.setenv("LEDGER_MODE", "record")
    upload(client, project, f"component:{K1}", admin)
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"]))) as conn:
        row = conn.execute("select item_type, item_id, details from ledger.outbox where action = 'target.file.uploaded'"
                           " order by occurred_at desc limit 1").fetchone()
    assert row is not None
    assert row[0] == "target" and row[1] == f"component:{K1}"
    assert row[2] == {"name": "scoring.onnx", "size": len(ONNX), "sha256": hashlib.sha256(ONNX).hexdigest()}


def test_a_long_upload_does_not_hold_up_the_projects_card_syncs(client, admin, project, carded, monkeypatch):
    import psycopg

    from platform_service import db, engine_components

    free_during_upload = []
    real = engine_components.upload

    def upload_and_look(pid, token, component, name, stream):
        with psycopg.connect(db.dsn(), autocommit=True) as conn:
            got = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"targets:{pid}",)).fetchone()[0]
            if got:
                conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"targets:{pid}",))
        free_during_upload.append(got)
        return real(pid, token, component, name, stream)

    monkeypatch.setattr(engine_components, "upload", upload_and_look)
    r = upload(client, project, f"component:{K1}", admin)
    assert r.status_code == 200, r.text
    assert free_during_upload == [True]
