"""The rule sets a project can start from: a number of checkers per kind of task.

Two only: one person throughout, and four eyes. Sector-shaped sets are examples a project imports,
never presets, because a preset's name would be read as a claim of conformity.
"""
from __future__ import annotations

from platform_service.work.kinds import KINDS

NAMES = ("light", "four_eyes")

#: kinds four eyes leaves to one person: a launch is checked by reviewing its results, and composing a report
#: by releasing it
_ONE_PERSON_IN_FOUR_EYES = frozenset({"launch_run", "compose_report"})


def checkers(preset: str) -> dict[str, int]:
    """The number of checkers a preset gives each kind of task. An unknown preset is a KeyError."""
    if preset not in NAMES:
        raise KeyError(preset)
    if preset == "light":
        return {kind: 0 for kind in KINDS}
    return {kind: 0 if kind in _ONE_PERSON_IN_FOUR_EYES else 1 for kind in KINDS}
