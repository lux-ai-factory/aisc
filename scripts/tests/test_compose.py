"""Compose file rules (03 WP6a, WP2). Read-only: the compose files are copied to a scratch
directory and resolved with `docker compose config`; nothing is started, stopped or built."""

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]


@pytest.fixture(scope="module")
def compose(tmp_path_factory):
    d = tmp_path_factory.mktemp("compose")
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, d / f)
        args += ["-f", str(d / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    # secrets the files demand are given dummy values; env.secrets is never read
    env = {**os.environ, **{k: "dummy" for k in required}}
    base = ["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
            "--env-file", str(ROOT / "env.development"), *args]
    q = subprocess.run(base + ["config", "-q"], env=env, capture_output=True, text=True)
    j = subprocess.run(base + ["config", "--format", "json"], env=env, capture_output=True, text=True)
    return q, (json.loads(j.stdout) if j.returncode == 0 else None)


def test_s6a_compose_config_is_valid(compose):
    """WP6a: `docker compose -f <copy> config -q` passes."""
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]


def test_s6a_qualification_agents_service(compose):
    """WP6a: service qualification-agents builds services/agents, on network backend, with
    LLM_SERVICE_URL=http://qualification-llm:4000."""
    q, cfg = compose
    svc = cfg["services"].get("qualification-agents")
    assert svc, "no service qualification-agents"
    ctx = svc["build"]["context"] if isinstance(svc.get("build"), dict) else svc.get("build", "")
    assert str(ctx).rstrip("/").endswith("apps/qualification/services/agents")
    assert "backend" in (svc.get("networks") or {})
    assert (svc.get("environment") or {}).get("LLM_SERVICE_URL") == "http://qualification-llm:4000"


def test_s6a_qualification_web_reaches_the_agents(compose):
    """WP6a: qualification-web gets AGENT_SERVICE_URL on the port service.py is served on."""
    q, cfg = compose
    dockerfile = (ROOT / "apps/qualification/services/agents/Dockerfile").read_text()
    port = re.search(r'"--port", "(\d+)"', dockerfile).group(1)
    value = (cfg["services"]["qualification-web"].get("environment") or {}).get("AGENT_SERVICE_URL")
    assert value == f"http://qualification-agents:{port}"


def test_wp2_aisc_backend_has_no_platform_url(compose):
    """WP2 code: PLATFORM_URL (from c0f460e) is gone from aisc-backend."""
    q, cfg = compose
    names = set(cfg["services"]["aisc-backend"].get("environment") or {})
    assert "PLATFORM_URL" not in names
