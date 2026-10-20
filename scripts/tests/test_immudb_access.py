"""One access model for immudb.

Only immudb and the ledger-pool one-shot hold immudb's superuser password. The engine (aisc-backend)
reaches its audit log as its own user, aisc_engine, on auditdb, made by ledger-pool, and starts only
after ledger-pool succeeded. The dashboard has no immudb setting at all.

The compose files are read with PyYAML (merge keys resolved) where the question is which value a
service is GIVEN (a `${NAME...}` reference), and through `docker compose config` (compose_cfg) where the
question is whether the stack resolves. verify-immudb.sh runs on a scratch copy with a fake `docker` on
PATH. Nothing is started, stopped or built; env.secrets is never read.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys

import pytest
import yaml

import compose_cfg
from conftest import ROOT

COMPOSE_FILES = sorted(p.name for p in ROOT.glob("docker-compose*.yml"))
ENGINE_ACCOUNT = ROOT / "platform/platform_service/ledger/engine_account.py"


def _env(body) -> dict:
    env = body.get("environment") or {}
    if isinstance(env, list):
        env = dict(e.split("=", 1) if "=" in e else (e, None) for e in env)
    return {k: ("" if v is None else str(v)) for k, v in env.items()}


def services() -> dict[str, dict]:
    """service -> its environment, over every compose file of the repo root, merges resolved."""
    out: dict[str, dict] = {}
    for name in COMPOSE_FILES:
        for svc, body in (yaml.safe_load((ROOT / name).read_text()).get("services") or {}).items():
            out.setdefault(svc, {}).update(_env(body))
    return out


def dev_service(name: str) -> dict:
    return yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"][name]


def mentions(env: dict, secret: str) -> bool:
    """The service holds `secret`: as a key, or as a `${secret...}` reference in any value."""
    return secret in env or any(re.search(r"\$\{" + secret + r"\b", v) for v in env.values())


def _constant(name: str) -> str:
    assert ENGINE_ACCOUNT.exists(), "platform/platform_service/ledger/engine_account.py does not exist yet"
    for node in ast.parse(ENGINE_ACCOUNT.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a constant of engine_account.py")



def test_only_immudb_and_ledger_pool_hold_the_superuser_password():
    holders = {svc for svc, env in services().items() if mentions(env, "IMMUDB_ADMIN_PASSWORD")}
    assert holders == {"immudb", "ledger-pool"}, sorted(holders)



def test_the_engine_password_goes_to_the_engine_and_ledger_pool_only():
    holders = {svc for svc, env in services().items() if mentions(env, "ENGINE_IMMUDB_PASSWORD")}
    assert holders == {"aisc-backend", "ledger-pool"}, sorted(holders)
    for svc in holders:
        refs = [v for v in services()[svc].values() if "${ENGINE_IMMUDB_PASSWORD" in v]
        assert refs and all(v == "${ENGINE_IMMUDB_PASSWORD:?run scripts/secrets.sh first}" for v in refs), (svc, len(refs))



def test_the_engine_reaches_immudb_as_its_own_user():
    env = services()["aisc-backend"]
    assert env.get("IMMUDB_URL") == "immudb:3322"
    assert env.get("IMMUDB_USER") == _constant("ENGINE_USER")
    assert env.get("IMMUDB_DATABASE") == _constant("ENGINE_DATABASE")
    assert env.get("IMMUDB_PASSWORD") == "${ENGINE_IMMUDB_PASSWORD:?run scripts/secrets.sh first}"
    assert "IMMUDB_ADMIN_PASSWORD" not in env



@pytest.mark.parametrize("svc", ["aisc-backend-migrate", "dashboard", "dashboard-migrate", "aisc-eval-worker",
                                 "aisc-eval-flower", "platform"])
def test_these_services_have_no_immudb_setting(svc):
    env = services()[svc]
    named = sorted(k for k in env if k.startswith("IMMUDB_"))
    referenced = sorted(k for k, v in env.items() if "${IMMUDB_" in v)
    assert not named and not referenced, (named, referenced)
    if svc.startswith("dashboard"):
        assert "AISC_AUDIT_ENABLED" not in env



def test_ledger_pool_has_everything_it_needs():
    env = services()["ledger-pool"]
    for name in ("ENGINE_IMMUDB_PASSWORD", "IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_URL", "LEDGER_IMMUDB_PASSWORD",
                 "PLATFORM_DATABASE_URL"):
        assert name in env, name


# The engine fails closed


def test_the_engine_starts_only_after_ledger_pool_succeeded(tmp_path):
    cfg = compose_cfg.config(tmp_path)
    dep = cfg["services"]["aisc-backend"].get("depends_on", {}).get("ledger-pool")
    assert dep and dep.get("condition") == "service_completed_successfully", dep


def test_compose_refuses_to_resolve_without_the_engine_password(tmp_path):
    r = compose_cfg.run(tmp_path, quiet=True, missing=("ENGINE_IMMUDB_PASSWORD",))
    assert r.returncode != 0, "the stack resolves without ENGINE_IMMUDB_PASSWORD"
    assert "ENGINE_IMMUDB_PASSWORD" in r.stderr, r.stderr[-1000:]


# scripts/verify-immudb.sh, with a fake docker

CANNED = {"admin": "Canned-admin-pw-1!", "ledger": "Canned-ledger-pw-2!", "engine": "Canned-engine-pw-3!",
          "superset": "canned-superset-secret-4"}

#: container -> (compose service, environment, exit code)
TARGET = {
    "immudb": ("immudb", {"IMMUDB_ADMIN_PASSWORD": CANNED["admin"], "IMMUDB_FORCE_ADMIN_PASSWORD": "true"}, 0),
    "aisc-ledger-pool-1": ("ledger-pool", {"IMMUDB_ADMIN_PASSWORD": CANNED["admin"],
                                           "LEDGER_IMMUDB_PASSWORD": CANNED["ledger"],
                                           "ENGINE_IMMUDB_PASSWORD": CANNED["engine"],
                                           "LEDGER_IMMUDB_URL": "immudb:3322"}, 0),
    "platform": ("platform", {"LEDGER_IMMUDB_URL": "immudb:3322", "LEDGER_IMMUDB_PASSWORD": CANNED["ledger"]}, 0),
    "aisc-backend": ("aisc-backend", {"IMMUDB_URL": "immudb:3322", "IMMUDB_USER": "aisc_engine",
                                      "IMMUDB_PASSWORD": CANNED["engine"], "IMMUDB_DATABASE": "auditdb"}, 0),
    "aisc-backend-migrate": ("aisc-backend-migrate", {"DJANGO_SETTINGS_MODULE": "config.settings"}, 0),
    "dashboard": ("dashboard", {"SUPERSET_SECRET_KEY": CANNED["superset"]}, 0),
    "dashboard-migrate": ("dashboard-migrate", {"SUPERSET_SECRET_KEY": CANNED["superset"]}, 0),
}

FAKE_DOCKER = r'''#!/usr/bin/env python3
"""A fake docker for verify-immudb.sh: answers ps, inspect and `compose ... run ... engine_account check`
from a scenario file; never reaches a daemon."""
import json, os, sys
scenario = json.load(open(os.environ["FAKE_DOCKER_SCENARIO"]))
containers, check_exit = scenario["containers"], scenario["check_exit"]
args = sys.argv[1:]
fmt = ""
for i, a in enumerate(args):
    if a in ("--format", "-f") and i + 1 < len(args):
        fmt = args[i + 1]
    elif a.startswith("--format="):
        fmt = a.split("=", 1)[1]
def info(name):
    svc, env, code = containers[name]
    return {"Name": "/" + name, "Config": {"Env": [f"{k}={v}" for k, v in env.items()],
            "Labels": {"com.docker.compose.project": "aisc", "com.docker.compose.service": svc}},
            "State": {"ExitCode": code, "Status": "exited" if svc in ("ledger-pool", "aisc-backend-migrate",
                      "dashboard-migrate") else "running", "Running": svc not in ("ledger-pool",)}}
if args and args[0] == "ps":
    for name, (svc, _, _) in containers.items():
        if "Label" in fmt and "service" in fmt:            # names with their compose service
            print(f"{name}\t{svc}")
        else:
            print(name)
    sys.exit(0)
if args and args[0] == "inspect":
    names = [a for a in args if a in containers]
    if not names:
        sys.exit(1)
    for name in names:
        d = info(name)
        if "ExitCode" in fmt:
            print(d["State"]["ExitCode"])
        elif "Status" in fmt:
            print(d["State"]["Status"])
        elif "Env" in fmt:
            print("\n".join(d["Config"]["Env"]))
        elif "compose.service" in fmt:
            print(d["Config"]["Labels"]["com.docker.compose.service"])
        elif "compose.project" in fmt:
            print("aisc")
        else:
            print(json.dumps([d]))
    sys.exit(0)
if args and args[0] == "compose":
    if "engine_account" in " ".join(args) and "check" in args:
        if check_exit:
            print("problem: aisc_engine may DELETE in auditdb")
        else:
            print("engine account aisc_engine: as designed")
        sys.exit(check_exit)
    sys.exit(0)
sys.exit(1)
'''

SCRIPT = ROOT / "scripts/verify-immudb.sh"


def run_verify(tmp_path, containers=None, check_exit=0):
    assert SCRIPT.exists(), "scripts/verify-immudb.sh does not exist yet"
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tree / "scripts/verify-immudb.sh")
    if (ROOT / "scripts/lib").is_dir():
        shutil.copytree(ROOT / "scripts/lib", tree / "scripts/lib", ignore=shutil.ignore_patterns("__pycache__"))
    secrets = "".join(f"{k}={v}\n" for k, v in (("IMMUDB_ADMIN_PASSWORD", CANNED["admin"]),
                                                ("LEDGER_IMMUDB_PASSWORD", CANNED["ledger"]),
                                                ("ENGINE_IMMUDB_PASSWORD", CANNED["engine"])))
    (tree / "env.secrets").write_text(secrets)
    (tree / "env.runtime").write_text(secrets)
    for f in COMPOSE_FILES:
        shutil.copy(ROOT / f, tree / f)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"containers": containers or TARGET, "check_exit": check_exit}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    (bin_dir / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DOCKER_SCENARIO": str(scenario)}
    for k in ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD", "ENGINE_IMMUDB_PASSWORD"):
        env.pop(k, None)
    r = subprocess.run(["bash", str(tree / "scripts/verify-immudb.sh")], cwd=tree, env=env, capture_output=True,
                       text=True, timeout=120)
    out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    for secret in CANNED.values():
        assert secret not in out, "verify-immudb.sh printed a secret value"
    return r.returncode, out


def _with(name, **env_changes):
    containers = json.loads(json.dumps(TARGET))
    svc, env, code = containers[name]
    for k, v in env_changes.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    containers[name] = [svc, env, code]
    return containers


def test_verify_immudb_passes_on_the_target_layout(tmp_path):
    code, out = run_verify(tmp_path)
    assert code == 0, out[-3000:]


@pytest.mark.parametrize("case, containers, named", [
    ("dashboard holds IMMUDB_PASSWORD", _with("dashboard", IMMUDB_PASSWORD=CANNED["admin"]), "dashboard"),
    ("engine holds the superuser's", _with("aisc-backend", IMMUDB_ADMIN_PASSWORD=CANNED["admin"]), "aisc-backend"),
    ("engine logs in as the superuser", _with("aisc-backend", IMMUDB_USER="immudb"), "aisc-backend"),
])
def test_verify_immudb_fails_naming_the_container(tmp_path, case, containers, named):
    code, out = run_verify(tmp_path, containers)
    assert code != 0, f"{case}: passed\n{out[-2000:]}"
    assert named in out, f"{case}: {named} not named\n{out[-2000:]}"


def test_verify_immudb_fails_when_ledger_pool_failed(tmp_path):
    containers = json.loads(json.dumps(TARGET))
    containers["aisc-ledger-pool-1"][2] = 1
    code, out = run_verify(tmp_path, containers)
    assert code != 0 and "ledger-pool" in out, out[-2000:]


def test_verify_immudb_fails_when_the_account_check_fails(tmp_path):
    code, out = run_verify(tmp_path, check_exit=1)
    assert code != 0, out[-2000:]


# docs/guide.md (only text exists)


def test_the_guide_names_the_engines_own_audit_log_and_the_holders():
    guide = (ROOT / "docs/guide.md").read_text()
    flat = " ".join(guide.split())
    assert "aisc_engine" in flat and "auditdb" in flat
    assert re.search(r"engine[^.]*audit log[^.]*(outside|separate from|not in) the (platform )?ledger", flat, re.I), \
        "the guide does not say the engine's audit log is outside the platform ledger"
    assert re.search(r"ENGINE_IMMUDB_PASSWORD[^.]*--rotate|--rotate[^.]*ENGINE_IMMUDB_PASSWORD", flat), \
        "the guide does not say --rotate keeps ENGINE_IMMUDB_PASSWORD"
    assert re.search(r"only `?immudb`? and `?ledger-pool`?[^.]*superuser", flat, re.I), \
        "the guide does not say only immudb and ledger-pool hold the superuser password"
