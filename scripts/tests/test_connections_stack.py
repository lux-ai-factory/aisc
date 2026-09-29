"""Manage → Connections in the stack (connections plan 2026-09-29, R3 and R4): the resolve token is
generated once by secrets.sh, and compose gives the platform and the eval worker exactly what the
connections need. Nothing is started; compose files are resolved with `docker compose config`."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]


def config():
    args, required = [], set()
    for f in FILES:
        args += ["-f", str(ROOT / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {**{k: v for k, v in os.environ.items() if not k.startswith(("PLATFORM_", "CONNECTIONS_", "ENGINE_URL"))},
           **{k: "dummy" for k in required}}
    r = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)["services"], required


# ── R3 secrets.sh ───────────────────────────────────────────────────────────

@pytest.fixture
def scratch(tmp_path):
    for d in ("scripts", "keycloak"):
        (tmp_path / d).mkdir()
    shutil.copy(ROOT / "scripts/secrets.sh", tmp_path / "scripts/secrets.sh")
    shutil.copy(ROOT / "keycloak/aisc-realm.json", tmp_path / "keycloak/aisc-realm.json")
    shutil.copy(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    return tmp_path


def secrets_of(d):
    return dict(l.split("=", 1) for l in (d / "env.secrets").read_text().splitlines() if l and not l.startswith("#"))


def run(d):
    r = subprocess.run(["bash", str(d / "scripts/secrets.sh")], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    return r


def test_r3_secrets_sh_writes_the_connections_token_once_and_keeps_it(scratch):
    run(scratch)
    first = secrets_of(scratch)
    assert re.fullmatch(r"[0-9a-f]{64}", first["PLATFORM_CONNECTIONS_TOKEN"])
    others = {v for k, v in first.items() if k.endswith("_TOKEN") and k != "PLATFORM_CONNECTIONS_TOKEN"}
    assert first["PLATFORM_CONNECTIONS_TOKEN"] not in others
    out = run(scratch)
    assert secrets_of(scratch)["PLATFORM_CONNECTIONS_TOKEN"] == first["PLATFORM_CONNECTIONS_TOKEN"]
    assert first["PLATFORM_CONNECTIONS_TOKEN"] not in out.stdout + out.stderr


@pytest.mark.parametrize("name", ["env.development", "env.staging"])
def test_r3_env_files_say_where_the_connections_token_comes_from(name):
    text = (ROOT / name).read_text()
    assert any("PLATFORM_CONNECTIONS_TOKEN" in l and "env.secrets" in l for l in text.splitlines() if l.startswith("#"))
    assert not re.search(r"^PLATFORM_CONNECTIONS_TOKEN=", text, re.M)


# ── R4 compose ──────────────────────────────────────────────────────────────

def test_r4_the_token_is_required_so_compose_refuses_to_start_without_it():
    _, required = config()
    assert "PLATFORM_CONNECTIONS_TOKEN" in required


def test_r4_the_platform_gets_the_token_the_engine_url_the_allowlist_and_the_client():
    services, _ = config()
    p = services["platform"]
    env = p["environment"]
    assert env["PLATFORM_CONNECTIONS_TOKEN"] == "dummy"
    assert env["ENGINE_URL"] == "http://aisc-backend:8000"
    assert "CONNECTIONS_ALLOWED_HOSTS" in env
    mounts = {v["target"]: v for v in p["volumes"]}
    src = mounts.get("/app/shared/plugin-interface/src")
    assert src and src["source"] == str(ROOT / "shared/plugin-interface/src") and src.get("read_only"), mounts.keys()
    assert "/app/shared/plugin-interface/src" in env["PYTHONPATH"].split(":")
    assert "/app/shared/identity" in env["PYTHONPATH"].split(":")


def test_r4_the_eval_worker_gets_the_platform_url_the_token_and_the_allowlist():
    services, _ = config()
    env = services["aisc-eval-worker"]["environment"]
    assert env["PLATFORM_URL"] == "http://platform:8000"
    assert env["PLATFORM_CONNECTIONS_TOKEN"] == "dummy"
    assert "CONNECTIONS_ALLOWED_HOSTS" in env
    assert services["platform"]["environment"]["CONNECTIONS_ALLOWED_HOSTS"] == env["CONNECTIONS_ALLOWED_HOSTS"]


def test_r4_the_platform_the_backend_and_the_worker_share_a_network():
    services, _ = config()
    nets = {s: set(services[s].get("networks", {})) for s in ("platform", "aisc-backend", "aisc-eval-worker")}
    assert nets["platform"] & nets["aisc-backend"] and nets["platform"] & nets["aisc-eval-worker"], nets
