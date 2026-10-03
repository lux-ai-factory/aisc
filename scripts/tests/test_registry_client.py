"""The engine's package registry client can be built from what compose gives it.

The engine backend's settings (apps/backend/config/settings.py) turn an empty
PACKAGE_REGISTRY_USER / PASSWORD into None, and plugin-manager's DevpiClient refuses a user
without a password: with `PACKAGE_REGISTRY_USER=root` and an empty password the backend does not
boot (routers/plugin.py builds the Loader at import). The eval worker (aisc_eval/utils/env.py)
passes the raw strings.

Read-only: compose files are resolved with `docker compose config` from scratch copies; the
client is built in a subprocess (httpx, pydantic, packaging via uv) and never contacts the index.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

DEV_FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
STANDALONE = "docker-compose.engine-standalone.yml"


def _resolve(tmp_path, files, env_file):
    args, required = [], set()
    for f in files:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("PACKAGE_REGISTRY_")},
           **{k: "dummy" for k in required}}
    cmd = ["docker", "compose", "-p", "aisc-t-registry", "--project-directory", str(ROOT)]
    if env_file:
        cmd += ["--env-file", str(ROOT / env_file)]
    r = subprocess.run(cmd + args + ["config", "--format", "json"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)["services"]


def _registry(svc):
    env = svc.get("environment") or {}
    return {k: env.get(k) for k in ("PLUGIN_PATH", "PACKAGE_REGISTRY_URL", "PACKAGE_REGISTRY_INDEX",
                                    "PACKAGE_REGISTRY_USER", "PACKAGE_REGISTRY_PASSWORD")}


def _build_clients(cases):
    """Build DevpiClient for each case as the backend (settings.py's empty_str_to_none, read from
    the file itself) and the eval worker (raw strings) do; return {name: error or None}."""
    settings = (ROOT / "apps/backend/config/settings.py").read_text()
    rule = re.search(r"^empty_str_to_none\s*=\s*(lambda .+)$", settings, re.M).group(1)
    script = f"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("devpi_client", {str(ROOT / 'shared/plugin-manager/src/aisc_plugin_manager/devpi_client.py')!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
empty_str_to_none = {rule}
out = {{}}
for name, kind, e in json.load(sys.stdin):
    user, password = e.get("PACKAGE_REGISTRY_USER"), e.get("PACKAGE_REGISTRY_PASSWORD")
    if kind == "backend":
        user, password = empty_str_to_none(user), empty_str_to_none(password)
    else:
        user, password = user if user is not None else "", password if password is not None else ""
    try:
        m.DevpiClient(e.get("PACKAGE_REGISTRY_URL") or "", e.get("PACKAGE_REGISTRY_INDEX") or "", user, password)
        out[name] = None
    except Exception as exc:
        out[name] = f"{{type(exc).__name__}}: {{exc}}"
print(json.dumps(out))
"""
    r = subprocess.run(["uv", "run", "--no-project", "--with", "httpx", "--with", "pydantic",
                        "--with", "packaging", "python", "-c", script],
                       input=json.dumps(cases), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("env_file", ["env.plugin_downloader", "env.development"])
def test_the_engine_builds_its_registry_client_from_the_configurator_env(tmp_path, env_file):
    services = _resolve(tmp_path, DEV_FILES, env_file)
    cases = [[f"{env_file} {name}", kind, _registry(services[name])]
             for name, kind in (("aisc-backend", "backend"), ("aisc-backend-migrate", "backend"),
                                ("aisc-eval-worker", "eval"))
             if _registry(services[name])["PACKAGE_REGISTRY_URL"]]
    assert cases, "no engine service gets a registry"
    errors = {k: v for k, v in _build_clients(cases).items() if v}
    assert errors == {}, errors


def test_the_standalone_engine_builds_its_registry_client(tmp_path):
    services = _resolve(tmp_path, [STANDALONE], None)
    cases = [["standalone aisc-backend", "backend", _registry(services["aisc-backend"])],
             ["standalone aisc-eval-worker", "eval", _registry(services["aisc-eval-worker"])]]
    errors = {k: v for k, v in _build_clients(cases).items() if v}
    assert errors == {}, errors
