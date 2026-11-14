"""The platform reads LEDGER_MODE and AUTH_ENABLED strictly, refuses to start on a bad value, and records the
ledger's mode at every start.

A misspelt mode used to turn the ledger off without a word. Now only `off`, `record` and `enforce` are
accepted, and `ledger.mode` is written to the outbox at start whatever the mode, so a period with the ledger
off shows in the platform log once it is on again.

    bash scripts/test-platform.sh -q tests/ledger/test_ledger_mode_at_start.py
"""
from __future__ import annotations

import importlib

import psycopg
import pytest

from platform_service.ledger import outbox, registry, witness
from tests.conftest import DSN
from tests.ledger.conftest import need


def _switch_invalid():
    try:
        return importlib.import_module("aisc_identity.switches").SwitchInvalid
    except ModuleNotFoundError:
        pytest.fail("aisc_identity.switches is missing: there is no strict switch parser")


def _app_module():
    return importlib.import_module("platform_service.app")


def test_witness_mode_refuses_a_misspelt_mode(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "recrod")
    invalid = _switch_invalid()
    with pytest.raises(invalid):
        witness.mode()


def test_witness_mode_reads_an_absent_mode_as_record(monkeypatch):
    monkeypatch.delenv("LEDGER_MODE", raising=False)
    assert witness.mode() == "record"


def test_the_start_refuses_a_bad_auth_switch(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "")
    app_module = _app_module()
    assert hasattr(app_module, "check_switches_at_start"), "the platform checks no switch at start"
    with pytest.raises(_switch_invalid(), match="AUTH_ENABLED"):
        app_module.check_switches_at_start()


def test_the_switch_check_runs_before_the_ledger_worker_starts():
    app_module = _app_module()
    names = [getattr(hook, "__name__", "") for hook in app_module.app.router.on_startup]
    assert "check_switches_at_start" in names and "record_ledger_mode_at_start" in names, names
    assert names.index("check_switches_at_start") < names.index("record_ledger_mode_at_start") \
        < names.index("start"), names


def test_the_mode_is_recorded_at_start_even_when_off(monkeypatch):
    need(DSN, "no platform database reachable (PLATFORM_TEST_DATABASE_URL)")
    monkeypatch.setenv("LEDGER_MODE", "off")
    assert hasattr(outbox, "record_mode"), "the outbox cannot record the ledger's mode"
    with psycopg.connect(DSN, autocommit=True) as conn:
        event_id = outbox.record_mode(conn, witness.mode())
        row = conn.execute("SELECT action, project_pid, details->>'mode', emitter FROM core.outbox"
                           " WHERE event_id = %s", (event_id,)).fetchone()
        conn.execute("DELETE FROM core.outbox WHERE event_id = %s", (event_id,))
    assert row == ("ledger.mode", None, "off", "platform")


def test_the_registry_knows_the_mode_event():
    action = registry.REGISTRY.get("ledger.mode")
    assert action is not None, "the registry has no ledger.mode action"
    assert action.origin == "platform" and action.details_keys == ("mode",)


def test_the_relay_delivers_the_mode_to_the_platform_log_as_a_system_event(memory_ledger, mode):
    from platform_service.ledger.naming import PLATFORM_DB
    from tests.ledger.conftest import entries, relay_all

    mode("record")
    with psycopg.connect(DSN, autocommit=True) as conn:
        event_id = outbox.record_mode(conn, "record")
    relay_all()
    delivered = [e for e in entries(memory_ledger, PLATFORM_DB) if e.item_id == event_id or e.event_id == event_id]
    assert [(e.action, e.actor_kind, e.details, e.outcome) for e in delivered] == \
        [("ledger.mode", "system", {"mode": "record"}, "ok")], delivered
