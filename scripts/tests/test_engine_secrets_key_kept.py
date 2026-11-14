"""The engine's at-rest key, ENGINE_SECRETS_KEY, is a generated secret of its own, kept by `secrets --rotate`
and given to the backend and the eval worker only.

Read-only: scripts/aisc.py loaded as a module, `docker compose config` on scratch copies, and secrets.sh on a
scratch directory. No value is printed.
"""

import pytest

import compose_cfg
from conftest import aisc_py
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of
from test_secrets_hardening import _digest, _run

KEY = "the-engine-secrets-key"


def test_the_engine_key_is_a_fernet_secret_kept_by_rotate():
    aisc = aisc_py()
    assert ("ENGINE_SECRETS_KEY", "fernet") in aisc.SECRETS
    assert "ENGINE_SECRETS_KEY" in aisc.KEPT_ON_ROTATE


def test_rotate_keeps_the_engine_key(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    assert "ENGINE_SECRETS_KEY" in list(before), "secrets.sh writes no ENGINE_SECRETS_KEY"
    r = _run(scratch, "--rotate")
    assert r.returncode == 0, r.stderr[-2000:]
    assert _digest(secrets_of(scratch)["ENGINE_SECRETS_KEY"]) == _digest(before["ENGINE_SECRETS_KEY"])


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    return compose_cfg.config(tmp_path_factory.mktemp("engine-key"), env={"ENGINE_SECRETS_KEY": KEY})


@pytest.mark.parametrize("name", ["aisc-backend", "aisc-eval-worker"])
def test_the_backend_and_the_worker_get_the_engine_key(cfg, name):
    assert (cfg["services"][name].get("environment") or {}).get("ENGINE_SECRETS_KEY") == KEY


def test_the_compose_file_refuses_to_start_without_the_engine_key(tmp_path):
    r = compose_cfg.run(tmp_path, quiet=True, missing=("ENGINE_SECRETS_KEY",))
    assert r.returncode != 0 and "ENGINE_SECRETS_KEY" in r.stderr, "compose resolves without ENGINE_SECRETS_KEY"
