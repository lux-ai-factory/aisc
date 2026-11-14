"""AUTH_ENABLED and LEDGER_MODE, read strictly.

A switch is on only for an on word and off only for an off word; a ledger mode is one of three words. Case and
surrounding spaces do not matter. Anything else, an empty value included, is refused with an error naming the
variable, so a typo stops the service instead of quietly turning authentication or the ledger off.

Absent AUTH_ENABLED means on; absent LEDGER_MODE means record.

Standard library only: the qualification agents and the results dashboard keep byte-identical copies of this
file, and scripts/tests/test_switch_copies.py checks that they do.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

ON_WORDS = ("1", "true", "yes", "on")
OFF_WORDS = ("0", "false", "no", "off")
LEDGER_MODES = ("off", "record", "enforce")

_SHOWN_VALUE_LENGTH = 40


class SwitchInvalid(ValueError):
    """A switch holds a value that is none of its allowed words."""


def _refuse(name: str, value: str, allowed: tuple[str, ...]) -> SwitchInvalid:
    shown = repr(value)[:_SHOWN_VALUE_LENGTH]
    return SwitchInvalid(f"{name}={shown} is not allowed: use one of {', '.join(allowed)}")


def parse_switch(name: str, value: str) -> bool:
    word = value.strip().lower()
    if word in ON_WORDS:
        return True
    if word in OFF_WORDS:
        return False
    raise _refuse(name, value, ON_WORDS + OFF_WORDS)


def auth_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    value = env.get("AUTH_ENABLED")
    if value is None:
        return True
    return parse_switch("AUTH_ENABLED", value)


def ledger_mode(environ: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if environ is None else environ
    value = env.get("LEDGER_MODE")
    if value is None:
        return "record"
    word = value.strip().lower()
    if word in LEDGER_MODES:
        return word
    raise _refuse("LEDGER_MODE", value, LEDGER_MODES)


def check_environment(environ: Optional[Mapping[str, str]] = None) -> dict[str, object]:
    """Both switches as they will be read, or SwitchInvalid naming the first bad one."""
    env = os.environ if environ is None else environ
    return {"AUTH_ENABLED": auth_enabled(env), "LEDGER_MODE": ledger_mode(env)}
