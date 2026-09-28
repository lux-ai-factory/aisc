"""The dashboard bridge token (adapt Task 6d, D2, 2026-09-28).

The platform tells the dashboard's bridge (`POST/DELETE /api/v1/aisc_project/<pid>`) about every project,
with DASHBOARD_BRIDGE_TOKEN; the bridge refuses every call when the token is empty. The end-to-end run of
Task 6b found it empty in both services: scripts/secrets.sh never wrote it and compose fell back to "".

So: secrets.sh generates it like its other random secrets, an existing env.secrets gets every missing
secret appended without a byte of what is there changing, it never prints a secret, and compose refuses
to start platform or dashboard without it.

Nothing is started and nothing in the repo is written: secrets.sh runs on a scratch copy and
`docker compose config` reads scratch copies of the compose files.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_dashboard_bridge_token.py
"""

import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_llm_keys import run_secrets, secrets_of
from test_service_tokens import FILES, config

NAME = "DASHBOARD_BRIDGE_TOKEN"
REQUIRED = "${DASHBOARD_BRIDGE_TOKEN:?set DASHBOARD_BRIDGE_TOKEN (scripts/secrets.sh)}"
ENDS = ["dashboard", "platform"]


@pytest.fixture
def scratch(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "keycloak").mkdir()
    shutil.copy(ROOT / "scripts/secrets.sh", tmp_path / "scripts/secrets.sh")
    shutil.copy(ROOT / "keycloak/aisc-realm.json", tmp_path / "keycloak/aisc-realm.json")
    shutil.copy(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    return tmp_path


def runtime_of(d):
    return dict(line.split("=", 1) for line in (d / "env.runtime").read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#"))


def printed(r):
    return r.stdout + r.stderr


# ── secrets.sh ───────────────────────────────────────────────────────────────


def test_a_new_install_gets_the_bridge_token_in_env_secrets_and_env_runtime(scratch):
    r = run_secrets(scratch)
    token = secrets_of(scratch).get(NAME, "")
    assert re.fullmatch(r"[0-9a-f]{64}", token), f"{NAME} missing or not 64 hex in env.secrets"
    assert runtime_of(scratch).get(NAME) == token, f"{NAME} is not in env.runtime"
    assert token not in printed(r), "secrets.sh printed the bridge token"


def test_an_existing_env_secrets_without_it_gets_it_added_and_keeps_every_byte(scratch):
    run_secrets(scratch)
    lines = (scratch / "env.secrets").read_text().splitlines(keepends=True)
    before = "".join(l for l in lines if not l.startswith(NAME + "="))
    (scratch / "env.secrets").write_text(before)
    r = run_secrets(scratch)
    after = (scratch / "env.secrets").read_text()
    assert after.startswith(before), "a value that was there changed"
    added = secrets_of(scratch)
    assert re.fullmatch(r"[0-9a-f]{64}", added.get(NAME, "")), f"{NAME} was not added"
    assert after[len(before):] == f"{NAME}={added[NAME]}\n", "anything but the missing token was added"
    assert runtime_of(scratch).get(NAME) == added[NAME]
    assert added[NAME] not in printed(r)
    run_secrets(scratch)
    assert (scratch / "env.secrets").read_text() == after, "a third run changed env.secrets"


def test_any_secret_missing_from_an_existing_env_secrets_is_added(scratch):
    """Not only the bridge token: every secret a fresh install gets, whatever this install lacks."""
    run_secrets(scratch)
    fresh = set(secrets_of(scratch))
    kept = "# made before\nGATEWAY_CLIENT_SECRET=old-client\n"
    (scratch / "env.secrets").write_text(kept)
    r = run_secrets(scratch)
    after = (scratch / "env.secrets").read_text()
    assert after.startswith(kept)
    values = secrets_of(scratch)
    assert set(values) == fresh, sorted(fresh ^ set(values))
    assert values["GATEWAY_CLIENT_SECRET"] == "old-client"
    assert len(values["GATEWAY_COOKIE_SECRET"]) == 43
    out = printed(r)
    for k, v in values.items():
        assert v not in out, f"secrets.sh printed {k}"


def test_rotate_replaces_the_bridge_token(scratch):
    run_secrets(scratch)
    before = secrets_of(scratch)[NAME]
    r = subprocess.run(["bash", str(scratch / "scripts/secrets.sh"), "--rotate"], cwd=scratch,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    after = secrets_of(scratch)[NAME]
    assert re.fullmatch(r"[0-9a-f]{64}", after) and after != before
    assert after not in printed(r)


# ── compose ──────────────────────────────────────────────────────────────────


def test_compose_requires_the_token_for_platform_and_dashboard():
    text = (ROOT / "docker-compose.development.yml").read_text()
    assert f"{NAME}: {REQUIRED}" in text
    assert text.count(REQUIRED) == 2, "platform and dashboard, each once"
    for f in FILES + ["docker-compose.plugin_downloader.yml"]:
        assert not re.search(r"\$\{DASHBOARD_BRIDGE_TOKEN:?-", (ROOT / f).read_text()), f"{f} has a fallback"


def test_the_token_reaches_exactly_platform_and_dashboard(tmp_path):
    services, required = config(tmp_path, {NAME: "value-of-the-bridge-token"})
    assert NAME in required
    holders = sorted(s for s, svc in services.items()
                     if "value-of-the-bridge-token" in (svc.get("environment") or {}).values())
    assert holders == ENDS
    for s in ENDS:
        assert services[s]["environment"][NAME] == "value-of-the-bridge-token"


def test_compose_refuses_to_start_without_it(tmp_path):
    args, required = [], set()
    for f in FILES:
        shutil.copy(ROOT / f, tmp_path / f)
        args += ["-f", str(tmp_path / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {k: v for k, v in os.environ.items() if k != NAME}
    env.update({k: "dummy" for k in required - {NAME}})
    r = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *args, "config", "-q"],
                       env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert "set DASHBOARD_BRIDGE_TOKEN (scripts/secrets.sh)" in r.stderr, r.stderr[-1000:]


@pytest.mark.parametrize("name", ["env.development", "env.staging"])
def test_env_files_say_where_the_token_comes_from(name):
    text = (ROOT / name).read_text()
    assert any(NAME in line and "env.secrets" in line for line in text.splitlines() if line.startswith("#"))
    assert not re.search(rf"^{NAME}=", text, re.M), f"{name} must not set {NAME}"
