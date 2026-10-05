"""A fresh install records into the ledger from its first project, with no step beyond the README's.

The ledger is on by default (LEDGER_MODE=record, the gateway's witness on), and the ledger-pool one-shot
tops the pool of per-project immudb databases up at every start, giving any project that waits its
database. Only immudb and that one-shot hold immudb's superuser password; the platform never does."""
import re

import pytest
import yaml

from conftest import ROOT

COMPOSE = ROOT / "docker-compose.development.yml"
INFRA = ROOT / "docker-compose-infra.development.yml"


def _services(path):
    return yaml.safe_load(path.read_text())["services"]


def test_every_app_records_by_default():
    defaults = set(re.findall(r"LEDGER_MODE: \$\{LEDGER_MODE:-(\w+)\}", COMPOSE.read_text()))
    assert defaults == {"record"}, defaults


def test_the_gateway_witnesses_by_default():
    assert "LEDGER_GATEWAY: ${LEDGER_GATEWAY:-on}" in INFRA.read_text()
    assert "LEDGER_GATEWAY:-off" not in INFRA.read_text()


def test_the_pool_is_topped_up_at_every_start():
    pool = _services(COMPOSE)["ledger-pool"]
    command = " ".join(pool["command"]) if isinstance(pool["command"], list) else pool["command"]
    assert "platform_service.ledger.pool" in command and "top-up" in command and "--wait" in command
    assert pool["image"].startswith("aisc-platform:")
    assert pool.get("restart", "no") == "no"
    assert set(pool["depends_on"]) >= {"platform", "immudb"}
    env = pool["environment"]
    for name in ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD", "LEDGER_IMMUDB_URL", "PLATFORM_DATABASE_URL"):
        assert name in env, name


def test_the_platform_never_holds_immudbs_superuser_password():
    """Of the ledger's parts only the ledger-pool one-shot holds it (immudb itself has it too). The
    engine (aisc-backend and its migrate one-shot) holds it for its own audit ledgers, from before the
    ledger, in code that is kept as its authors wrote it."""
    holders = {name for f in (COMPOSE, INFRA) for name, s in _services(f).items()
               if "IMMUDB_ADMIN_PASSWORD" in (s.get("environment") or {})}
    assert holders == {"immudb", "ledger-pool", "aisc-backend", "aisc-backend-migrate"}, holders
    assert "platform" not in holders
