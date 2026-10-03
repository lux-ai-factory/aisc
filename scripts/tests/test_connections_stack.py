"""Manage, Connections in the stack: the resolve token is generated once by secrets.sh, and compose
gives the platform and the eval worker exactly what the connections need. Nothing is started; compose
files are resolved with `docker compose config`."""
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


# secrets.sh

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


# compose

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


def test_r5_the_platform_names_its_internal_url_for_the_protocol_endpoints_and_the_run_key_ttl():
    services, _ = config()
    env = services["platform"]["environment"]
    assert env["PLATFORM_INTERNAL_URL"] == "http://platform:8000"
    assert int(env["CONNECTIONS_RUN_KEY_TTL_S"]) == 43200


def test_r4_the_eval_worker_gets_the_platform_url_the_token_and_the_allowlist():
    services, _ = config()
    env = services["aisc-eval-worker"]["environment"]
    assert env["PLATFORM_URL"] == "http://platform:8000"
    assert env["PLATFORM_CONNECTIONS_TOKEN"] == "dummy"
    # the platform hands a run its project's rule in the resolve response, so the worker has no
    # allowlist of its own that could drift or allow more
    assert "CONNECTIONS_ALLOWED_HOSTS" not in env
    assert "CONNECTIONS_ALLOWED_HOSTS" in services["platform"]["environment"]


def test_r4_the_platform_the_backend_and_the_worker_share_a_network():
    services, _ = config()
    nets = {s: set(services[s].get("networks", {})) for s in ("platform", "aisc-backend", "aisc-eval-worker")}
    assert nets["platform"] & nets["aisc-backend"] and nets["platform"] & nets["aisc-eval-worker"], nets


def test_r6_every_name_a_stack_service_answers_to_is_on_the_deny_list():
    """The UI may never allow the stack's own services: every service, container and alias name of
    the compose files is in connection_allowlist.STACK_SERVICES."""
    import ast
    import yaml

    src = (ROOT / "platform/platform_service/connection_allowlist.py").read_text()
    node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "STACK_SERVICES" for t in n.targets))
    listed = set(ast.literal_eval(node.value.args[0]))
    names = set()
    for f in ROOT.glob("docker-compose*.yml"):
        for name, spec in ((yaml.safe_load(f.read_text()) or {}).get("services") or {}).items():
            names.add(name)
            if (spec or {}).get("container_name"):
                names.add(spec["container_name"])
            nets = (spec or {}).get("networks")
            if isinstance(nets, dict):
                for v in nets.values():
                    names |= set((v or {}).get("aliases") or [])
    missing = sorted(n for n in names if "${" not in n and n not in listed)
    assert not missing, f"stack names the UI could allow: {missing}"
