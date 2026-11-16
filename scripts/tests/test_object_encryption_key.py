"""MinIO encrypts every object it stores with a key the install makes once and keeps across rotations: a new key would
leave every stored object unreadable. The bucket script turns encryption on for the engine's three buckets.

Read-only: scripts/aisc.py loaded as a module, compose resolved on copies, the bucket script as text.
"""

import base64

import compose_cfg
from conftest import ROOT, aisc_py


def test_the_object_encryption_key_survives_rotate():
    m = aisc_py()
    assert "MINIO_KMS_SECRET_KEY" in {n for n, _ in m.SECRETS}, "scripts/aisc.py makes no key for MinIO's encryption"
    assert "MINIO_KMS_SECRET_KEY" in m.KEPT_ON_ROTATE
    key = m.fresh("minio_kms", "MINIO_KMS_SECRET_KEY")
    assert key.startswith("aisc-key:") and len(base64.b64decode(key.split(":", 1)[1])) == 32


def test_minio_is_given_its_key(tmp_path):
    env = compose_cfg.config(tmp_path)["services"]["minio"]["environment"]
    assert "MINIO_KMS_SECRET_KEY" in env, "MinIO stores objects unencrypted"
    assert "MINIO_KMS_SECRET_KEY" in compose_cfg.required(), "MinIO starts without its key"


def test_the_engine_buckets_encrypt_by_default():
    script = ROOT / "infra/minio/make-buckets.sh"
    assert script.is_file(), "no bucket script to turn encryption on"
    text = script.read_text()
    assert "mc encrypt set sse-s3" in text
    for bucket in ("datasets", "artifacts", "models"):
        assert f"minio/{bucket}" in text, bucket
