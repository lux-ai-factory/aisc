"""MinIO encrypts what it stores by default: every bucket the platform makes is set to server-side
encryption (SSE-S3), so an object written there is encrypted at rest. Checked on a recording client and,
when scripts/test-platform.sh started one, on a throwaway MinIO."""
from __future__ import annotations

import os
import uuid

import pytest

from platform_service import proof_store


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def bucket_exists(self, bucket):
        self.calls.append(("bucket_exists", (bucket,)))
        return False

    def make_bucket(self, bucket, *args, **kwargs):
        self.calls.append(("make_bucket", (bucket,)))

    def set_bucket_encryption(self, bucket, config):
        self.calls.append(("set_bucket_encryption", (bucket, config)))


def test_a_new_bucket_is_set_to_encrypt_what_it_stores():
    store = object.__new__(proof_store.MinioStore)
    store._client = RecordingClient()
    store.make_bucket("proof-" + "0" * 32)
    encryption = [args for name, args in store._client.calls if name == "set_bucket_encryption"]
    assert encryption, "a bucket is made without server-side encryption"
    from minio.sseconfig import SSEConfig
    (bucket, config), = encryption
    assert bucket == "proof-" + "0" * 32 and isinstance(config, SSEConfig)
    assert config.rule.sse_algorithm == "AES256"


def test_a_stored_object_is_encrypted_at_rest():
    url = os.environ.get("PROOF_TEST_S3_URL", "")
    if not url:
        pytest.skip("no throwaway MinIO (PROOF_TEST_S3_URL)")
    store = proof_store.MinioStore(url, os.environ["PROOF_TEST_S3_USER"], os.environ["PROOF_TEST_S3_PASSWORD"])
    bucket = proof_store.bucket_name(uuid.uuid4())
    try:
        store.make_bucket(bucket)
        store.put(bucket, "f", b"x", "text/plain", {})
        stat = store._client.stat_object(bucket, "f")
        assert stat.metadata.get("x-amz-server-side-encryption") == "AES256", \
            "the object is stored without encryption"
    finally:
        store.remove_bucket(bucket)
