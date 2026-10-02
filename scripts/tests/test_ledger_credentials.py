"""T17, T18: who holds which ledger credential, read from the compose files (spec 6.5; R1.9). Plugins run
inside the engine worker with a copy of its whole environment (apps/eval/aisc_eval/celery_tasks.py,
`os.environ.copy()`), so no process that runs plugin code may hold a ledger credential. The worker's
results reach the ledger through the engine backend."""
import pytest
import yaml

from conftest import ROOT

FILES = ["docker-compose.plugin_downloader.yml", "docker-compose-infra.development.yml", "docker-compose.development.yml"]
#: credential -> the only services that may hold it
HOLDERS = {
    "PLATFORM_LEDGER_ENGINE_TOKEN": {"aisc-backend", "platform"},
    "PLATFORM_LEDGER_DASHBOARD_TOKEN": {"dashboard", "platform"},
    "PLATFORM_LEDGER_AGENTS_TOKEN": {"qualification-agents", "platform"},
    "PLATFORM_LEDGER_KEYS": {"platform"},
    "AISC_WITNESS_GATEWAY_SECRET": {"caddy", "platform"},
}
RUNS_PLUGINS = {"aisc-eval-worker", "plugin-downloader", "plugin-publisher", "aisc-eval-flower"}


def services() -> dict:
    out = {}
    for name in FILES:
        for svc, body in (yaml.safe_load((ROOT / name).read_text()).get("services") or {}).items():
            env = body.get("environment") or {}
            keys = set(env) if isinstance(env, dict) else {e.split("=", 1)[0] for e in env}
            out.setdefault(svc, set()).update(keys)
    return out


@pytest.mark.parametrize("credential", sorted(HOLDERS))
def test_each_credential_is_held_exactly_by_its_holders(credential):
    holding = {svc for svc, keys in services().items() if credential in keys}
    assert holding == HOLDERS[credential], f"{credential}: held by {sorted(holding)}"


def test_nothing_that_runs_plugin_code_holds_a_ledger_credential():
    for svc in RUNS_PLUGINS & set(services()):
        leaked = {k for k in services()[svc] if k.startswith(("PLATFORM_LEDGER_", "AISC_WITNESS_"))}
        assert not leaked, f"{svc} runs plugin code and holds {sorted(leaked)}"


def test_caddy_selects_the_witness_snippet_by_environment():
    assert "LEDGER_GATEWAY" in services()["caddy"]
