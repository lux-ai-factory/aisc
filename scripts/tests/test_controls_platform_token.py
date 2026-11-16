"""Who holds PLATFORM_CONTROLS_TOKEN and the MinIO credentials the proof files need, read from the resolved
compose files, and where the token comes from.

The controls app sends the files that prove a checklist answer to the platform
(POST /internal/projects/{pid}/proof-files) and reads them back from it, with a token of its own held by the
two of them only. The platform stores them in MinIO, with the stack's S3 settings; the controls app never
holds those. Nothing is started: `docker compose config` reads scratch copies of the compose files, and
secrets.sh runs on a scratch copy of the checkout.
"""
import re

import pytest

import compose_cfg
from conftest import aisc_py
from test_dashboard_bridge_token import printed, runtime_of, scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of
from test_plugin_publisher_secrets import IDS, RUNS, holders


@pytest.mark.parametrize("files, profiles", RUNS, ids=IDS)
def test_only_the_platform_and_the_controls_app_hold_the_controls_token(tmp_path, files, profiles):
    assert holders(tmp_path, files, profiles, "PLATFORM_CONTROLS_TOKEN") == ["controls-web", "platform"]


@pytest.mark.parametrize("files, profiles", RUNS, ids=IDS)
def test_the_platform_holds_the_minio_credentials_and_the_controls_app_does_not(tmp_path, files, profiles):
    # the platform's own MinIO account; make_buckets sets its password
    held = holders(tmp_path, files, profiles, "S3_PLATFORM_PASSWORD")
    assert "platform" in held and "controls-web" not in held


def test_the_platform_reaches_minio_with_the_stack_s3_address_and_its_own_account(tmp_path):
    env = compose_cfg.config(tmp_path, env={"S3_URL": "http://minio:9000", "S3_USER": "minio-user"})[
        "services"]["platform"]["environment"]
    assert env["S3_URL"] == "http://minio:9000" and env["S3_USER"] == "aisc-platform"


def test_the_controls_app_reaches_the_platform(tmp_path):
    services = compose_cfg.config(tmp_path)["services"]
    assert services["controls-web"]["environment"]["PLATFORM_URL"] == "http://platform:8000"


def test_compose_refuses_to_start_without_the_controls_token(tmp_path):
    assert "PLATFORM_CONTROLS_TOKEN" in compose_cfg.required()
    r = compose_cfg.run(tmp_path, quiet=True, missing=("PLATFORM_CONTROLS_TOKEN",))
    assert r.returncode != 0 and "PLATFORM_CONTROLS_TOKEN" in r.stderr, r.stderr[-1000:]


def test_the_controls_token_is_generated_with_the_other_secrets(scratch):  # noqa: F811
    assert dict(aisc_py().SECRETS).get("PLATFORM_CONTROLS_TOKEN") == "rand"
    assert "PLATFORM_CONTROLS_TOKEN" in aisc_py().FRESH_ON_ROTATE
    run_secrets(scratch)
    token = secrets_of(scratch).get("PLATFORM_CONTROLS_TOKEN", "")
    assert re.fullmatch(r"[0-9a-f]{64}", token), "PLATFORM_CONTROLS_TOKEN missing or not 64 hex in env.secrets"
    assert runtime_of(scratch).get("PLATFORM_CONTROLS_TOKEN") == token, "not in env.runtime"
