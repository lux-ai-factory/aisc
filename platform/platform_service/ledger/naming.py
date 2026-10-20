"""Ledger database names. A name never carries a pid: the operator's pool makes
databases before projects exist, and immudb can't rename one, so a project's log is found by lookup
(`provision.database_for`). Every name is checked before it reaches immudb."""
from __future__ import annotations

import re
import secrets

#: The platform's own events (no project).
PLATFORM_DB = "ledgerplatform"

_NAME = re.compile(r"ledger[0-9a-f]{32}")


def pool_name() -> str:
    """A fresh database name: `ledger` + 32 random lowercase hex."""
    return "ledger" + secrets.token_hex(16)


def is_ledger_name(name) -> bool:
    """True for a pool name or the platform log, and nothing else (no system database, no injection)."""
    return isinstance(name, str) and (name == PLATFORM_DB or _NAME.fullmatch(name) is not None)
