"""The rule sets a project can start from.

Two only: one person throughout, and four eyes. Sector-shaped sets are examples a project imports,
never presets, because a preset's name would be read as a claim of conformity.
"""
from __future__ import annotations

from platform_service.work.kinds import KINDS, TIERS

NAMES = ("light", "four_eyes")

#: kinds four eyes leaves to one person: a launch is checked by reviewing its results, and composing a report
#: by releasing it
_ONE_PERSON_IN_FOUR_EYES = frozenset({"launch_run", "compose_report"})


def _alone() -> dict:
    return {"doers": {"count": 1, "mode": "any_one", "from": {"kind": "any"}}, "stages": [], "sampled": None}


def _checked_once() -> dict:
    rule = _alone()
    rule["stages"] = [{"needed": 1, "from": {"kind": "any"}, "kind": "review", "other_line": False,
                       "not_earlier_signer": False, "any_objection_sends_back": True, "due_days": None}]
    return rule


def rule(preset: str, kind: str, tier: str) -> dict:
    """The rule a preset gives for a kind and tier. An unknown preset, kind or tier is a KeyError."""
    if preset not in NAMES:
        raise KeyError(preset)
    if kind not in KINDS:
        raise KeyError(kind)
    if tier not in TIERS:
        raise KeyError(tier)
    if preset == "light" or kind in _ONE_PERSON_IN_FOUR_EYES:
        return _alone()
    return _checked_once()
