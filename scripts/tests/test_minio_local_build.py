"""MinIO is built in the stack from a pinned source release (MinIO stopped publishing community
images in late 2025; every quay.io/minio and minio/ tag is refused). M1 to M4: static checks of
the compose files and the Dockerfile; nothing is built here."""
import re

import yaml

from conftest import ROOT

MINIO_RELEASE = "RELEASE.2025-10-15T17-29-55Z"
MC_RELEASE = "RELEASE.2025-08-13T08-35-41Z"
IMAGE = "aisc-minio:${AISC_IMAGE_TAG:-latest}"     # the stack's convention for built images (G9)
DOCKERFILE = ROOT / "infra/minio/Dockerfile"
FILES = ["docker-compose-infra.development.yml", "docker-compose-infra.yml", "docker-compose-infra.staging.yml",
         "docker-compose.engine-standalone.yml"]


def services(name):
    return yaml.safe_load((ROOT / name).read_text())["services"]


def test_m1_no_compose_file_pulls_a_minio_image():
    for f in [p.name for p in ROOT.glob("docker-compose*.yml")]:
        for svc, spec in services(f).items():
            image = (spec or {}).get("image") or ""
            assert not re.match(r"^(quay\.io/|docker\.io/)?minio/", image), f"{f}: {svc} pulls {image}"


def test_m2_minio_and_the_bucket_job_build_the_same_local_image():
    for f in FILES:
        s = services(f)
        server = s["minio"]
        for spec in (server, s["make_buckets"]):
            assert spec["image"] == IMAGE and spec.get("pull_policy") == "never", f
            build = spec["build"]
            context = build if isinstance(build, str) else build["context"]
            assert context.rstrip("/") == "./infra/minio", f


def test_m3_the_dockerfile_builds_both_binaries_from_the_pinned_source_tags():
    text = DOCKERFILE.read_text()
    assert f"ARG MINIO_RELEASE={MINIO_RELEASE}" in text and f"ARG MC_RELEASE={MC_RELEASE}" in text
    assert "https://github.com/minio/minio" in text and "https://github.com/minio/mc" in text
    assert re.search(r"^FROM golang:1\.24[.\d]*-alpine\S* AS build", text, re.M), "a pinned Go toolchain"
    assert "/usr/bin/minio" in text and "/usr/bin/mc" in text


def test_m4_the_server_keeps_its_command_healthcheck_and_bucket_names():
    for f in FILES:
        s = services(f)
        assert "server /data" in str(s["minio"]["command"])
        assert "mc" in str(s["minio"]["healthcheck"]["test"])
        job = s["make_buckets"]
        if f == "docker-compose-infra.yml":
            continue    # its job runs ./tasks/minio_add_bucket.sh, a file missing from the repo (pre-existing)
        for bucket in ("datasets", "artifacts", "models"):
            assert f"mc mb --ignore-existing minio/{bucket}" in job["entrypoint"], (f, bucket)
