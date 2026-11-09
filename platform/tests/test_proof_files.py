"""Proof files of checklist answers, as the controls app reaches them.

POST /internal/projects/{pid}/proof-files takes one file (its bytes as the body, its name in `name`),
checks it and stores it in the project's bucket; GET .../proof-files/{id} sends it back. Only the controls
app may call them, with its own token (PLATFORM_CONTROLS_TOKEN), and never through the gateway. A project's
bucket is made with its database and removed with it. Runs on the throwaway database, with the in-memory
store in place of MinIO (tests/test_proof_store.py runs the same contract on a real one)."""
from __future__ import annotations

import hashlib
import uuid

import pytest

from platform_service import proof_store
from platform_service.proof_types import MAX_BYTES
from tests.conftest import needs_database
from tests.proof_fake import FakeStore

pytestmark = needs_database
CONTROLS_TOKEN = "controls-proof-files-token-for-tests"
ENGINE_TOKEN = "engine-token-for-tests"
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


@pytest.fixture
def fake(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(proof_store, "store", lambda: store)
    monkeypatch.setenv("PLATFORM_CONTROLS_TOKEN", CONTROLS_TOKEN)
    monkeypatch.setenv("PLATFORM_ENGINE_TOKEN", ENGINE_TOKEN)
    return store


def upload(client, pid, data=PDF, name="policy.pdf", token=CONTROLS_TOKEN, **headers):
    return client.post(f"/internal/projects/{pid}/proof-files", params={"name": name}, content=data,
                       headers={"X-AISC-Service-Token": token, "Content-Type": "application/octet-stream",
                                **headers})


def download(client, pid, file_id, token=CONTROLS_TOKEN, **headers):
    return client.get(f"/internal/projects/{pid}/proof-files/{file_id}",
                      headers={"X-AISC-Service-Token": token, **headers})


# the bucket follows the project


def test_making_a_project_makes_its_bucket(fake, make_project):
    made = make_project()
    assert fake.has_bucket(proof_store.bucket_name(made["pid"]))


def test_deleting_a_project_removes_its_bucket_and_files(fake, client, make_project, admin):
    made = make_project()
    assert upload(client, made["pid"]).status_code == 201
    r = client.request("DELETE", f"/projects/{made['slug']}", json={"confirm_name": made["name"]}, headers=admin)
    assert r.status_code == 204, r.text
    assert not fake.has_bucket(proof_store.bucket_name(made["pid"]))


def test_a_bucket_that_cannot_be_made_undoes_the_project(fake, client, as_user, unique, dsn):
    import psycopg

    from platform_service import projectdb

    fake.down = True
    slug = unique()
    r = client.post("/projects", json={"name": slug, "slug": slug}, headers=as_user("alice"))
    assert r.status_code == 503, r.text
    fake.down = False
    assert client.get(f"/projects/{slug}", headers=as_user("root", roles=("admin",))).status_code == 404
    with psycopg.connect(dsn) as conn:
        names = [r[0] for r in conn.execute("SELECT datname FROM pg_database").fetchall()]
    assert not [n for n in names if n.startswith("project_") and n not in _live_project_dbs(dsn, projectdb)]


def _live_project_dbs(dsn, projectdb):
    import psycopg

    with psycopg.connect(dsn) as conn:
        return {projectdb.database_name(r[0]) for r in conn.execute("SELECT pid FROM core.project").fetchall()}


def test_a_project_still_made_when_no_store_is_set_up(monkeypatch, make_project):
    monkeypatch.delenv("S3_URL", raising=False)
    assert make_project()["pid"]


# taking a file


def test_a_file_is_stored_and_described(fake, client, project):
    r = upload(client, project["pid"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "name", "mime", "size", "sha256"}
    assert body["name"] == "policy.pdf" and body["mime"] == "application/pdf" and body["size"] == len(PDF)
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert uuid.UUID(body["id"])
    stored = fake.buckets[proof_store.bucket_name(project["pid"])][body["id"]]
    assert stored[0] == PDF and stored[2]["sha256"] == body["sha256"]


def test_the_same_bytes_twice_are_two_files(fake, client, project):
    first, second = upload(client, project["pid"]).json(), upload(client, project["pid"]).json()
    assert first["id"] != second["id"] and first["sha256"] == second["sha256"]


def test_a_project_made_before_proof_files_gets_its_bucket_on_the_first_file(fake, client, project):
    fake.buckets.clear()
    assert upload(client, project["pid"]).status_code == 201
    assert fake.has_bucket(proof_store.bucket_name(project["pid"]))


@pytest.mark.parametrize("data, name", [
    (b"MZ\x90\0\x03\0\0\0" + b"\0" * 64, "invoice.pdf"),
    (b"<html><script>alert(1)</script></html>", "report.pdf"),
    (b"PK\x03\x04" + b"\0" * 40, "plan.docx"),
])
def test_a_file_of_another_type_is_refused_and_not_stored(fake, client, project, data, name):
    r = upload(client, project["pid"], data=data, name=name)
    assert r.status_code == 415, r.text
    assert "detail" in r.json()
    assert not fake.buckets.get(proof_store.bucket_name(project["pid"]))


def test_a_file_over_25_megabytes_is_refused(fake, client, project):
    r = upload(client, project["pid"], data=b"%PDF-" + b"0" * MAX_BYTES)
    assert r.status_code == 413, r.text
    assert not fake.buckets.get(proof_store.bucket_name(project["pid"]))


def test_a_file_of_exactly_25_megabytes_is_taken(fake, client, project):
    r = upload(client, project["pid"], data=b"%PDF-" + b"0" * (MAX_BYTES - 5))
    assert r.status_code == 201, r.text


def test_a_file_without_a_name_is_refused(fake, client, project):
    assert upload(client, project["pid"], name="").status_code == 422


def test_a_store_that_does_not_answer_is_503(fake, client, project):
    fake.down = True
    assert upload(client, project["pid"]).status_code == 503


# who may call


def test_only_the_controls_token_is_taken(fake, client, project):
    assert upload(client, project["pid"], token="").status_code == 401
    assert upload(client, project["pid"], token="wrong").status_code == 401
    assert upload(client, project["pid"], token=ENGINE_TOKEN).status_code == 401
    stored = upload(client, project["pid"]).json()
    assert download(client, project["pid"], stored["id"], token=ENGINE_TOKEN).status_code == 401


def test_the_routes_are_closed_without_the_controls_token(fake, client, project, monkeypatch):
    monkeypatch.delenv("PLATFORM_CONTROLS_TOKEN")
    assert upload(client, project["pid"]).status_code in (401, 503)


def test_never_through_the_gateway(fake, client, project):
    assert upload(client, project["pid"], **{"X-Forwarded-For": "10.0.0.1"}).status_code == 404
    stored = upload(client, project["pid"]).json()
    assert download(client, project["pid"], stored["id"], **{"X-Forwarded-Host": "gw"}).status_code == 404


def test_an_unknown_project_is_404(fake, client):
    assert upload(client, str(uuid.uuid4())).status_code == 404
    assert upload(client, "not-a-pid").status_code == 404


# reading a file back


def test_a_stored_file_comes_back_with_its_type(fake, client, project):
    stored = upload(client, project["pid"]).json()
    r = download(client, project["pid"], stored["id"])
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(r.content).hexdigest() == stored["sha256"]


def test_one_project_cannot_read_another_s_file(fake, client, make_project):
    mine, theirs = make_project(), make_project()
    stored = upload(client, theirs["pid"]).json()
    assert download(client, mine["pid"], stored["id"]).status_code == 404
    assert download(client, theirs["pid"], stored["id"]).status_code == 200


def test_an_unknown_file_is_404(fake, client, project):
    assert download(client, project["pid"], str(uuid.uuid4())).status_code == 404
    assert download(client, project["pid"], "../other").status_code == 404


def test_there_is_no_route_that_replaces_or_deletes_a_file(fake, client, project):
    stored = upload(client, project["pid"]).json()
    path = f"/internal/projects/{project['pid']}/proof-files/{stored['id']}"
    headers = {"X-AISC-Service-Token": CONTROLS_TOKEN}
    assert client.put(path, content=b"other", headers=headers).status_code == 405
    assert client.delete(path, headers=headers).status_code == 405
    assert download(client, project["pid"], stored["id"]).content == PDF
