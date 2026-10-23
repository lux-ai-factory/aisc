"""Who holds which ledger credential, read from the compose files.

Plugins run inside the engine worker with a copy of its whole environment
(apps/eval/aisc_eval/celery_tasks.py, `os.environ.copy()`), so no process that runs plugin code may
hold a ledger credential. The worker's results reach the ledger through the engine backend."""
import pytest
import yaml

from conftest import ROOT

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
#: credential -> the only services that may hold it. The engine's token may only go to a process that
#: never imports plugin code: aisc-backend loads plugin packages in-process, so its events wait in the
#: outbox and aisc-backend-ledger, which has no plugin folder and serves no route, sends them.
HOLDERS = {
    "PLATFORM_LEDGER_ENGINE_TOKEN": {"platform", "aisc-backend-ledger"},
    "PLATFORM_LEDGER_DASHBOARD_TOKEN": {"platform", "dashboard"},
    "PLATFORM_LEDGER_AGENTS_TOKEN": {"platform", "qualification-agents"},
    "PLATFORM_LEDGER_KEYS": {"platform"},
    "LEDGER_IMMUDB_PASSWORD": {"platform", "ledger-pool"},          # ledger-pool grants that user each new database
    "AISC_WITNESS_GATEWAY_SECRET": {"caddy", "platform"},
    # The engine's own immudb user; ledger-pool makes it, aisc-backend holds it as the value of
    # IMMUDB_PASSWORD (it imports plugin code: an accepted trade-off)
    "ENGINE_IMMUDB_PASSWORD": {"aisc-backend", "ledger-pool"},
}
#: Credentials a process that runs plugin code may hold anyway, and through which service only.
PLUGIN_HOLDER_ACCEPTED = {"ENGINE_IMMUDB_PASSWORD": {"aisc-backend"}}
#: Processes that run or import plugin code: the eval worker runs it, the engine backend imports
#: plugin packages to read their configuration (shared/plugin-manager loader), and the publisher runs a
#: plugin repo's build code (its build backend, setup.py) when it builds it.
RUNS_PLUGINS = {"aisc-eval-worker", "plugin-publisher", "aisc-eval-flower", "aisc-backend"}


def services() -> dict:
    """service -> the credentials it holds: its environment's keys, and every `${NAME...}` its values
    reference (aisc-backend holds ENGINE_IMMUDB_PASSWORD as the value of IMMUDB_PASSWORD)."""
    import re

    out = {}
    for name in FILES:
        for svc, body in (yaml.safe_load((ROOT / name).read_text()).get("services") or {}).items():
            env = body.get("environment") or {}
            keys = set(env) if isinstance(env, dict) else {e.split("=", 1)[0] for e in env}
            values = env.values() if isinstance(env, dict) else [e.split("=", 1)[-1] for e in env]
            keys |= {m for v in values for m in re.findall(r"\$\{([A-Z0-9_]+)", str(v or ""))}
            out.setdefault(svc, set()).update(keys)
    return out


def test_plugin_code_holds_the_engine_password_only_through_aisc_backend():
    for credential, allowed in PLUGIN_HOLDER_ACCEPTED.items():
        holding = {svc for svc in RUNS_PLUGINS & set(services()) if credential in services()[svc]}
        assert holding <= allowed, f"{credential} reaches plugin code through {sorted(holding - allowed)}"
        assert holding == allowed, f"{credential} is not where the engine reads it: {sorted(holding)}"


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
