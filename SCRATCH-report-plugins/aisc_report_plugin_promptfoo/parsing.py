"""Pure parsing of what aisc-plugin-promptfoo 0.1.0 writes. Never raises."""
from __future__ import annotations

import re

RATES = ("pass_rate", "fail_rate", "refusal_rate")
KNOWN = RATES + ("mean_latency_ms", "total_cost", "n_tests")

_DIRECTION = re.compile(r"\b(higher|lower) is better\b")


def direction(unit) -> str | None:
    """"higher" or "lower" when the unit says "(higher is better)" or "(lower is better)", else None."""
    if not isinstance(unit, str):
        return None
    match = _DIRECTION.search(unit)
    return match.group(1) if match else None
