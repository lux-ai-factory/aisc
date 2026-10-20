"""Superset's cache is a Redis of its own.

Superset's RedisCache unpickles what it reads (cachelib's RedisSerializer: a value starting with `!`
goes through pickle.loads). On the shared, password-less `redis` the eval worker reaches, a plugin
could write a pickle there and run code in the dashboard, which holds every project's read password
and immudb's superuser. So the dashboard's cache is `dashboard-redis`: a password from
scripts/secrets.sh, on a network only the dashboard's own services join, nothing published.

Read-only: `docker compose config` on scratch copies, and secrets.sh on a scratch directory.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_dashboard_redis.py
"""

import re

import pytest

import compose_cfg
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of

DASHBOARD_SIDE = {"dashboard", "dashboard-migrate", "dashboard-redis"}


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    # every profile, so a service that only a profile starts is checked too
    return compose_cfg.config(tmp_path_factory.mktemp("dashboard-redis"), "inspect", "add-controls",
                              env={"DASHBOARD_REDIS_PASSWORD": "the-dashboard-redis-password"})


def _nets(svc):
    return set(svc.get("networks") or {})


@pytest.mark.parametrize("name", ["dashboard", "dashboard-migrate"])
def test_the_dashboard_caches_in_its_own_redis_with_a_password(cfg, name):
    env = cfg["services"][name]["environment"]
    assert env.get("DASHBOARD_REDIS_HOST") == "dashboard-redis"
    assert env.get("DASHBOARD_REDIS_PORT") == "6379"
    assert env.get("DASHBOARD_REDIS_PASSWORD") == "the-dashboard-redis-password"
    # the shared one is not named any more, under the old variable either
    assert env.get("REDIS_HOST") in (None, "dashboard-redis")


def test_the_dashboard_redis_asks_for_the_password_and_publishes_nothing(cfg):
    svc = cfg["services"]["dashboard-redis"]
    cmd = " ".join(svc.get("command") or []) if isinstance(svc.get("command"), list) else str(svc.get("command"))
    assert "requirepass" in cmd
    # the value is read from the environment inside the container, never written into the command
    assert "the-dashboard-redis-password" not in cmd
    assert svc["environment"]["DASHBOARD_REDIS_PASSWORD"] == "the-dashboard-redis-password"
    assert not svc.get("ports")


def test_no_service_running_plugin_code_shares_a_network_with_the_dashboard_redis(cfg):
    redis_nets = _nets(cfg["services"]["dashboard-redis"])
    assert redis_nets
    on_it = {n for n, s in cfg["services"].items() if _nets(s) & redis_nets}
    assert on_it == DASHBOARD_SIDE
    assert not _nets(cfg["services"]["aisc-eval-worker"]) & redis_nets


def test_the_compose_file_refuses_to_start_without_the_password(tmp_path):
    r = compose_cfg.run(tmp_path, quiet=True, missing=("DASHBOARD_REDIS_PASSWORD",))
    assert r.returncode != 0
    assert "DASHBOARD_REDIS_PASSWORD" in r.stderr


def test_secrets_sh_generates_the_dashboard_redis_password(scratch):  # noqa: F811
    run_secrets(scratch)
    shaped = bool(re.fullmatch(r"[0-9a-f]{64}", secrets_of(scratch).get("DASHBOARD_REDIS_PASSWORD", "")))
    assert shaped, "DASHBOARD_REDIS_PASSWORD missing from env.secrets or not 64 hex"
