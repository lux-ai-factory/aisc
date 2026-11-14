"""AUTH_ENABLED and LEDGER_MODE are read strictly, from one parser and one file of cases.

On words are 1, true, yes and on; off words are 0, false, no and off; the ledger modes are off, record and
enforce. Case and surrounding spaces do not matter. Anything else, empty included, is refused with an error
that names the variable, never silently read as off. Absent AUTH_ENABLED means on; absent LEDGER_MODE means
record. The cases live in switch-cases.json, which the Python copies and the TypeScript twin share.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parents[1] / "switch-cases.json").read_text())


def _switches():
    try:
        return importlib.import_module("aisc_identity.switches")
    except ModuleNotFoundError:
        pytest.fail("aisc_identity.switches does not exist: there is no strict switch parser")


def _env(name, value):
    return {} if value is None else {name: value}


@pytest.mark.parametrize("case", CASES["switch"], ids=lambda c: repr(c["value"]))
def test_a_switch_is_on_only_for_an_on_word_and_off_only_for_an_off_word(case):
    s = _switches()
    if case.get("refused"):
        with pytest.raises(s.SwitchInvalid, match="AUTH_ENABLED"):
            s.parse_switch("AUTH_ENABLED", case["value"])
    else:
        assert s.parse_switch("AUTH_ENABLED", case["value"]) is case["is"]


@pytest.mark.parametrize("case", CASES["auth_enabled"], ids=lambda c: repr(c["value"]))
def test_auth_is_on_when_absent_and_refused_when_empty(case):
    s = _switches()
    env = _env("AUTH_ENABLED", case["value"])
    if case.get("refused"):
        with pytest.raises(s.SwitchInvalid, match="AUTH_ENABLED"):
            s.auth_enabled(env)
    else:
        assert s.auth_enabled(env) is case["is"]


@pytest.mark.parametrize("case", CASES["ledger_mode"], ids=lambda c: repr(c["value"]))
def test_the_ledger_mode_is_one_of_three_and_record_when_absent(case):
    s = _switches()
    env = _env("LEDGER_MODE", case["value"])
    if case.get("refused"):
        with pytest.raises(s.SwitchInvalid, match="off, record, enforce"):
            s.ledger_mode(env)
    else:
        assert s.ledger_mode(env) == case["is"]


def test_the_word_lists_are_the_agreed_ones():
    s = _switches()
    assert s.ON_WORDS == ("1", "true", "yes", "on")
    assert s.OFF_WORDS == ("0", "false", "no", "off")
    assert s.LEDGER_MODES == ("off", "record", "enforce")


def test_the_environment_check_names_every_switch():
    assert _switches().check_environment({}) == {"AUTH_ENABLED": True, "LEDGER_MODE": "record"}


def test_a_refusal_names_the_value_cut_short_and_the_allowed_words():
    s = _switches()
    with pytest.raises(s.SwitchInvalid) as caught:
        s.check_environment({"AUTH_ENABLED": "x" * 100})
    message = str(caught.value)
    assert "AUTH_ENABLED" in message and "x" * 41 not in message
    assert "1, true, yes, on" in message or "true" in message


def test_a_bad_auth_switch_no_longer_turns_auth_off(monkeypatch):
    s = _switches()
    from aisc_identity import service

    monkeypatch.setenv("AUTH_ENABLED", "ture")
    with pytest.raises(s.SwitchInvalid):
        service.settings()


def test_the_ledger_events_switch_records_when_the_mode_is_absent(monkeypatch):
    from aisc_identity import ledger_events

    monkeypatch.delenv("LEDGER_MODE", raising=False)
    assert ledger_events.on() is True


def test_an_empty_ledger_mode_is_refused_by_the_ledger_events_switch(monkeypatch):
    s = _switches()
    from aisc_identity import ledger_events

    monkeypatch.setenv("LEDGER_MODE", "")
    with pytest.raises(s.SwitchInvalid):
        ledger_events.on()
