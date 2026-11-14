"""The shared Redis (Celery's result backend) asks for a password.

The worker and flower get it from scripts/secrets.sh, the backend URL in env.runtime carries it as a
reference to the value defined above it, and compose refuses to start without it. The value is read inside
the container, never written into the command.

Read-only: `docker compose config` on scratch copies, and secrets.sh on a scratch directory. No value is
printed.

    uv run --no-project --with pytest --with pyyaml python -m pytest -q -p no:cacheprovider scripts/tests/test_redis_password.py
"""

import re

import pytest

import compose_cfg
from test_dashboard_bridge_token import scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of
from test_secrets_hardening import _digest

PASSWORD = "the-redis-password"


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    return compose_cfg.config(tmp_path_factory.mktemp("redis"), "inspect", env={"REDIS_PASSWORD": PASSWORD})


def _command(svc):
    cmd = svc.get("command") or []
    return " ".join(cmd) if isinstance(cmd, list) else str(cmd)


def test_the_shared_redis_asks_for_a_password_it_reads_from_its_environment(cfg):
    svc = cfg["services"]["redis"]
    cmd = _command(svc) + " " + " ".join(svc.get("entrypoint") or [])
    assert "requirepass" in cmd, "the shared Redis starts without a password"
    assert PASSWORD not in cmd, "the password is written into the command"
    assert "--protected-mode no" not in cmd
    assert (svc.get("environment") or {}).get("REDIS_PASSWORD") == PASSWORD


@pytest.mark.parametrize("name", ["aisc-eval-worker", "aisc-eval-flower"])
def test_the_worker_side_gets_the_password(cfg, name):
    assert (cfg["services"][name].get("environment") or {}).get("REDIS_PASSWORD") == PASSWORD


def test_the_compose_file_refuses_to_start_without_it(tmp_path):
    r = compose_cfg.run(tmp_path, quiet=True, missing=("REDIS_PASSWORD",))
    assert r.returncode != 0, "compose resolves the stack with no Redis password"
    assert "REDIS_PASSWORD" in r.stderr


def test_the_backend_url_carries_the_password_defined_above_it(scratch):  # noqa: F811
    run_secrets(scratch)
    lines = (scratch / "env.runtime").read_text().splitlines()
    names = [line.split("=", 1)[0] for line in lines]
    assert "REDIS_PASSWORD" in names, "env.runtime has no REDIS_PASSWORD"
    url = names.index("REDIS_BACKEND_URL")
    password = names.index("REDIS_PASSWORD")
    assert password < url, "the password is defined after the URL that refers to it"
    assert lines[url] == "REDIS_BACKEND_URL=redis://:$REDIS_PASSWORD@$REDIS_HOST:$REDIS_PORT/0"
    assert re.fullmatch(r"[0-9a-f]{64}", secrets_of(scratch)["REDIS_PASSWORD"]), "not 64 hex"


def test_rotate_replaces_the_redis_password(scratch):  # noqa: F811
    run_secrets(scratch)
    import importlib.util

    spec = importlib.util.spec_from_file_location("aisc_install_copy", scratch / "scripts/aisc.py")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert ("REDIS_PASSWORD", "rand") in module.SECRETS
    assert "REDIS_PASSWORD" in module.FRESH_ON_ROTATE


def test_an_existing_install_gets_the_redis_password_without_rotating(scratch):  # noqa: F811
    run_secrets(scratch)
    before = secrets_of(scratch)
    text = (scratch / "env.secrets").read_text()
    (scratch / "env.secrets").write_text(
        "\n".join(line for line in text.splitlines() if not line.startswith("REDIS_PASSWORD=")) + "\n")
    run_secrets(scratch)
    after = secrets_of(scratch)
    assert after.get("REDIS_PASSWORD"), "no Redis password was added"
    changed = [k for k, v in before.items() if k != "REDIS_PASSWORD" and _digest(after.get(k)) != _digest(v)]
    assert not changed, f"adding the Redis password changed {changed}"
