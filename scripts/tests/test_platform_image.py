"""The platform, report composer, MinIO and schema diagrams images run as users of their own, and the platform image
installs from its lock and carries the shared code itself instead of reading it from a mount.

MinIO's volume may have been made by root in an older install, so a one-shot hands /data to MinIO's user before
MinIO starts. Read-only: the Dockerfiles are read and `docker compose config` resolves copies of the compose files;
nothing is built, pulled or started.
"""

import compose_cfg
import test_image_policy as policy
from conftest import ROOT

#: the user each root-repository image ends as
OWN_USERS = {"platform/Dockerfile": "platform", "apps/report-composer/Dockerfile": "composer",
             "infra/minio/Dockerfile": "minio",
             # schema-docs already ends as its base image's java user
             "inspector/schema-docs/Dockerfile": "java"}


def test_the_platform_image_installs_from_its_lock():
    text = (ROOT / "platform/Dockerfile").read_text()
    words = [w for w, _ in policy.instructions(ROOT / "platform/Dockerfile")]
    assert "pip install --no-cache-dir ." not in text, "the platform image resolves its dependencies at build"
    assert "uv sync --frozen --no-dev" in text or "uv export --frozen --no-dev" in text, \
        "the platform image does not install from platform/uv.lock"
    assert "COPY --from=shared" in text, "the platform image does not take the shared code from its build context"
    assert words[-1] in ("CMD", "ENTRYPOINT")


def test_the_platform_takes_shared_code_from_the_image_not_a_mount(tmp_path):
    svc = compose_cfg.config(tmp_path)["services"]["platform"]
    assert "shared" in (svc["build"].get("additional_contexts") or {}), \
        "the platform build has no `shared` additional context"
    mounts = [v["source"] for v in svc.get("volumes", []) if "/shared/" in v.get("source", "") + "/"]
    assert mounts == [], f"the platform still reads shared code from mounts: {mounts}"
    assert "PYTHONPATH" not in (svc.get("environment") or {}), "the platform still points PYTHONPATH at the mounts"


def test_each_root_repository_image_ends_as_its_own_user():
    users = {}
    for file in OWN_USERS:
        user, _ = policy.runs_as(policy.stages(ROOT / file), None)
        users[file] = user
    assert users == OWN_USERS


def test_minio_data_is_handed_to_its_user_before_minio_starts(tmp_path):
    s = compose_cfg.config(tmp_path)["services"]
    assert "minio-data-owner" in s, "no one-shot hands MinIO's volume to MinIO's user"
    assert s["minio"].get("user") == "10030"
    assert s["minio"]["depends_on"]["minio-data-owner"]["condition"] == "service_completed_successfully"
    assert s["minio-data-owner"].get("network_mode") == "none"
    assert "10030" in " ".join(s["minio-data-owner"]["command"])
