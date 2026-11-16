"""The engine and the platform reach MinIO with accounts of their own, each limited to its buckets; only MinIO and the
one-shot that makes the buckets hold MinIO's root account. The one-shot sets the service passwords on every start,
so an install made before the accounts existed gets them on its next start.

Read-only: `docker compose config` on copies of the compose files, the bucket script and its policies as text,
scripts/aisc.py loaded as a module. One test runs the script in a throwaway MinIO (fixtures/minio-accounts.sh) and
is skipped when the aisc-minio image is not built; the stack's MinIO is never used.
"""

import json
import subprocess

import pytest

import compose_cfg
from conftest import ROOT, aisc_py

SCRIPT = ROOT / "infra/minio/make-buckets.sh"
POLICIES = ROOT / "infra/minio/policies"
ENGINE_BUCKETS = {"datasets", "artifacts", "models"}


def _resources(policy: dict) -> set[str]:
    out = set()
    for statement in policy["Statement"]:
        res = statement["Resource"]
        out |= set([res] if isinstance(res, str) else res)
    return out


def _actions(policy: dict) -> set[str]:
    out = set()
    for statement in policy["Statement"]:
        act = statement["Action"]
        out |= set([act] if isinstance(act, str) else act)
    return out


def test_the_buckets_and_accounts_are_made_by_a_script_in_the_image():
    assert SCRIPT.is_file(), "no infra/minio/make-buckets.sh: the buckets are made inline with the root account only"
    text = SCRIPT.read_text()
    assert "set -eu" in text
    for svc in ("engine", "platform"):
        assert f"aisc-{svc}" in text and f"S3_{svc.upper()}_PASSWORD" in text, svc
    assert "mc admin user add" in text and "mc admin policy attach" in text


def test_the_engine_account_reaches_only_its_three_buckets():
    assert (POLICIES / "engine.json").is_file(), "no MinIO policy for the engine's account"
    policy = json.loads((POLICIES / "engine.json").read_text())
    buckets = {r.removeprefix("arn:aws:s3:::").split("/")[0] for r in _resources(policy)}
    assert buckets == ENGINE_BUCKETS
    assert not any(a.startswith("admin:") or a in ("s3:*", "s3:CreateBucket", "s3:DeleteBucket")
                   for a in _actions(policy))


def test_the_platform_account_owns_only_the_proof_buckets_and_may_delete_engine_files():
    assert (POLICIES / "platform.json").is_file(), "no MinIO policy for the platform's account"
    policy = json.loads((POLICIES / "platform.json").read_text())
    resources = _resources(policy)
    assert "arn:aws:s3:::proof-*" in resources
    assert not any(a.startswith("admin:") for a in _actions(policy))
    for statement in policy["Statement"]:
        res = statement["Resource"]
        res = [res] if isinstance(res, str) else res
        if any(r.removeprefix("arn:aws:s3:::").split("/")[0] in ENGINE_BUCKETS for r in res):
            act = statement["Action"]
            assert set([act] if isinstance(act, str) else act) <= {"s3:ListBucket", "s3:DeleteObject"}, statement


def test_no_service_holds_minio_root(tmp_path):
    s = compose_cfg.config(tmp_path)["services"]
    root_user = s["minio"]["environment"]["MINIO_ROOT_USER"]
    holders = {n for n, v in s.items() if (v.get("environment") or {}).get("S3_USER") == root_user
               or "MINIO_ROOT_PASSWORD" in (v.get("environment") or {})}
    assert holders == {"minio", "make_buckets"}
    assert s["aisc-backend"]["environment"]["S3_USER"] == "aisc-engine"
    assert s["platform"]["environment"]["S3_USER"] == "aisc-platform"


def test_an_older_install_gets_the_new_service_passwords_on_start():
    m = aisc_py()
    wanted = {"S3_ENGINE_PASSWORD", "S3_PLATFORM_PASSWORD"}
    assert wanted - {n for n, _ in m.SECRETS} == set(), "scripts/aisc.py makes no MinIO service passwords"
    assert wanted - set(m.FRESH_ON_ROTATE) == set()


def test_each_account_reaches_only_its_buckets_in_a_real_minio():
    r = subprocess.run(["bash", str(ROOT / "scripts/tests/fixtures/minio-accounts.sh")], capture_output=True,
                       text=True, timeout=300)
    if r.returncode == 3:
        pytest.skip("aisc-minio image not built")
    assert r.returncode == 0, r.stderr[-2000:]
    probe = json.loads(r.stdout)
    assert probe["engine"] == {"put_artifacts": True, "read_datasets": True, "make_bucket": False,
                               "read_proof": False, "admin": False}
    assert probe["platform"] == {"make_proof_bucket": True, "list_artifacts": True, "read_artifact": False,
                                 "put_artifacts": False, "admin": False}
