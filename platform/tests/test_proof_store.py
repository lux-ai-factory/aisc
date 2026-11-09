"""The proof-file store: one bucket per project, objects written once and never replaced.

The same contract runs on the in-memory fake the route tests use and on a real MinIO. The MinIO one is a
throwaway container scripts/test-platform.sh starts (PROOF_TEST_S3_URL); never the stack's own."""
import os
import uuid

import pytest

from platform_service import proof_store
from tests.proof_fake import FakeStore

S3_URL = os.environ.get("PROOF_TEST_S3_URL", "")


def _minio():
    if not S3_URL:
        pytest.skip("no throwaway MinIO (PROOF_TEST_S3_URL): scripts/test-platform.sh starts one when the"
                    " aisc-minio image is built")
    return proof_store.MinioStore(S3_URL, os.environ["PROOF_TEST_S3_USER"], os.environ["PROOF_TEST_S3_PASSWORD"])


@pytest.fixture(params=["fake", "minio"])
def store(request):
    return FakeStore() if request.param == "fake" else _minio()


@pytest.fixture
def bucket(store):
    name = proof_store.bucket_name(uuid.uuid4())
    store.make_bucket(name)
    yield name
    store.remove_bucket(name)


def _read(opened) -> bytes:
    try:
        return b"".join(opened.chunks)
    finally:
        opened.close()


def test_the_bucket_is_named_after_the_project():
    pid = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
    assert proof_store.bucket_name(pid) == "proof-0f1e2d3c4b5a69788796a5b4c3d2e1f0"
    assert proof_store.bucket_name(pid.upper()) == proof_store.bucket_name(pid)


def test_only_a_project_id_names_a_bucket():
    with pytest.raises(ValueError):
        proof_store.bucket_name("../other")


def test_making_a_bucket_twice_is_harmless(store, bucket):
    store.make_bucket(bucket)
    assert store.has_bucket(bucket)


def test_an_object_comes_back_as_it_was_stored(store, bucket):
    store.put(bucket, "f1", b"%PDF-1.7 body", "application/pdf", {"name": "a%20b.pdf", "sha256": "ab" * 32})
    opened = store.open(bucket, "f1")
    assert opened.mime == "application/pdf" and opened.size == 13
    assert opened.meta["name"] == "a%20b.pdf" and opened.meta["sha256"] == "ab" * 32
    assert _read(opened) == b"%PDF-1.7 body"


def test_an_object_is_never_replaced(store, bucket):
    store.put(bucket, "f1", b"first", "text/plain", {})
    with pytest.raises(FileExistsError):
        store.put(bucket, "f1", b"second", "text/plain", {})
    assert _read(store.open(bucket, "f1")) == b"first"


def test_a_missing_object_or_bucket_is_none(store, bucket):
    assert store.open(bucket, "nothing") is None
    assert store.open(proof_store.bucket_name(uuid.uuid4()), "f1") is None


def test_removing_a_bucket_removes_its_objects(store):
    name = proof_store.bucket_name(uuid.uuid4())
    store.make_bucket(name)
    store.put(name, "f1", b"one", "text/plain", {})
    store.put(name, "f2", b"two", "text/plain", {})
    store.remove_bucket(name)
    assert not store.has_bucket(name)
    store.remove_bucket(name)                                         # gone already: harmless


def test_an_unreachable_minio_is_storage_unavailable():
    unreachable = proof_store.MinioStore("http://127.0.0.1:9", "user", "password")
    with pytest.raises(proof_store.StorageUnavailable):
        unreachable.make_bucket(proof_store.bucket_name(uuid.uuid4()))


def test_the_store_is_configured_from_the_stack_s3_settings(monkeypatch):
    monkeypatch.setenv("S3_URL", "http://minio:9000")
    monkeypatch.setenv("S3_USER", "user")
    monkeypatch.setenv("S3_PASSWORD", "password")
    assert isinstance(proof_store.store(), proof_store.MinioStore)
    monkeypatch.delenv("S3_URL")
    assert proof_store.store() is None
