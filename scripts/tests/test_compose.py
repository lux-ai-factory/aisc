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


# ── LLM keys (pipeline 2026-09-24-llm-keys, 01-specs.md S6.1, S6.2, S6.7) ─────
# A secret given as `${NAME:?...}` is in the fixture's `required` set and so resolves to "dummy":
# that value proves the `:?` form (D9) without reading env.secrets.


def _extra_hosts(svc):
    hosts = svc.get("extra_hosts") or []
    if isinstance(hosts, dict):
        return {f"{k}:{v}" for k, v in hosts.items()}
    return {h.replace("=", ":", 1) for h in hosts}


def test_s6_1_platform_gets_the_two_secrets_and_the_ollama_default(compose):
    q, cfg = compose
    env = cfg["services"]["platform"].get("environment") or {}
    assert env.get("PLATFORM_SECRETS_KEY") == "dummy", "PLATFORM_SECRETS_KEY is not a required `:?` variable"
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy", "PLATFORM_INTERNAL_TOKEN is not a required `:?` variable"
    assert env.get("PLATFORM_OLLAMA_BASE_URL") == "http://host.docker.internal:11434"
    assert "host.docker.internal:host-gateway" in _extra_hosts(cfg["services"]["platform"])


def test_s6_2_the_card_agent_reaches_the_platform_with_the_token(compose):
    q, cfg = compose
    svc = cfg["services"]["qualification-agents"]
    env = svc.get("environment") or {}
    assert env.get("PLATFORM_URL") == "http://platform:8000"
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy"
    assert "host.docker.internal:host-gateway" in _extra_hosts(svc)
    assert "backend" in (svc.get("networks") or {})


def test_s6_2_the_risk_mapper_gets_the_token(compose):
    q, cfg = compose
    svc = cfg["services"]["control-objectives"]
    env = svc.get("environment") or {}
    assert env.get("PLATFORM_INTERNAL_TOKEN") == "dummy"
    assert env.get("PLATFORM_URL")
    assert "backend" in (svc.get("networks") or {})
    assert "backend" in (cfg["services"]["platform"].get("networks") or {})


def test_s6_7_the_compose_files_stay_valid_with_the_new_variables(compose):
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]
    names = {n for s in ("platform", "qualification-agents", "control-objectives")
             for n in (cfg["services"][s].get("environment") or {})}
    assert {"PLATFORM_SECRETS_KEY", "PLATFORM_INTERNAL_TOKEN", "PLATFORM_OLLAMA_BASE_URL", "PLATFORM_URL"} <= names
    assert not (cfg["services"]["platform"].get("ports")), "the platform must publish no port (S5.5)"
