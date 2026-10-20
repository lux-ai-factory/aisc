"""What a check reports."""

from __future__ import annotations

from dataclasses import dataclass

FAIL = "FAIL"
WARN = "WARN"


@dataclass(frozen=True)
class Finding:
    level: str  # FAIL or WARN
    check: str  # C1 .. C8
    message: str


def fail(check: str, message: str) -> Finding:
    return Finding(FAIL, check, message)


def warn(check: str, message: str) -> Finding:
    return Finding(WARN, check, message)
