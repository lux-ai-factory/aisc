"""Who holds PLATFORM_ENGINE_TOKEN, read from the resolved compose files, and where it comes from.

The engine backend asks the platform whether a card target picked for an evaluation has a connection
(GET /internal/projects/{pid}/targets/{key}/reachable) with a token of its own, held by the two of
them only. Nothing is started: `docker compose config` reads scratch copies of the compose files, and
secrets.sh runs on a scratch copy of the checkout.
"""
import re

import pytest

import compose_cfg
from compose_cfg import FILES
from conftest import aisc_py
from test_dashboard_bridge_token import printed, runtime_of, scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of
from test_plugin_publisher_secrets import IDS, RUNS, holders


@pytest.mark.parametrize("files, profiles", RUNS, ids=IDS)
def test_only_the_platform_and_the_engine_backend_hold_the_engine_token(tmp_path, files, profiles):
    assert holders(tmp_path, files, profiles, "PLATFORM_ENGINE_TOKEN") == ["aisc-backend", "platform"]


def test_the_engine_backend_reaches_the_platform(tmp_path):
    services = compose_cfg.config(tmp_path)["services"]
    assert services["aisc-backend"]["environment"]["PLATFORM_URL"] == "http://platform:8000"


def test_compose_refuses_to_start_without_the_engine_token(tmp_path):
    assert "PLATFORM_ENGINE_TOKEN" in compose_cfg.required()
    r = compose_cfg.run(tmp_path, quiet=True, missing=("PLATFORM_ENGINE_TOKEN",))
    assert r.returncode != 0 and "PLATFORM_ENGINE_TOKEN" in r.stderr, r.stderr[-1000:]


def test_the_engine_token_is_generated_with_the_other_secrets(scratch):  # noqa: F811
    assert dict(aisc_py().SECRETS).get("PLATFORM_ENGINE_TOKEN") == "rand"
    r = run_secrets(scratch)
    token = secrets_of(scratch).get("PLATFORM_ENGINE_TOKEN", "")
    assert re.fullmatch(r"[0-9a-f]{64}", token), "PLATFORM_ENGINE_TOKEN missing or not 64 hex in env.secrets"
    assert runtime_of(scratch).get("PLATFORM_ENGINE_TOKEN") == token, "not in env.runtime"
    assert token not in printed(r), "secrets.sh printed the engine token"
