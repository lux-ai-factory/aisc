"""Pure parsing of what aisc-plugin-langbite writes. Never raises.

0.1.1: one measure per group, named "{Concern} | {Model} | {Language} | {Input Type} |
{Reflection Type}". 0.2.5 and later: every group is a "Bias Evaluation Results" measure whose dimensions hold
those five values, and its description ends in "| Errors: e | Refused: r"; "Refusals" (per group) and
"Failed cases" (per failed answer) come beside it."""
from __future__ import annotations

import re
from collections.abc import Mapping

RUN_SUCCESS = "LangBiTe Run Success"
OVERALL = "Overall Pass Rate"
ALL_TOLERANCES = "All Tolerances Passed"
SUMMARY_NAMES = (RUN_SUCCESS, OVERALL, ALL_TOLERANCES)
#: 0.2.5 and later
GROUP_RESULT = "Bias Evaluation Results"
GROUP_DIMENSIONS = ("concern", "model", "language", "input_type", "reflection_type")
#: 0.2.5 and later, per group and per failed answer: the results dashboard lists them, the report does not
DASHBOARD_ONLY = ("Refusals", "Failed cases")

_GROUP_DESCRIPTION = re.compile(
    r"^\s*Tolerance Evaluation:\s*(?P<check>[^|]*?)\s*\|\s*Tolerance:\s*(?P<tol>[^|]*?)\s*\|\s*"
    r"Passed:\s*(?P<p>\d+)\s*/\s*(?P<n>\d+)\s*\|\s*Failed:\s*(?P<f>\d+)\s*/\s*(?P<n2>\d+)\s*"
    r"(?:\|\s*Errors:\s*\d+\s*\|\s*Refused:\s*\d+\s*)?$")
_CHECKS_PASSED = re.compile(r"(\d+)\s*/\s*(\d+)\s+tolerance checks passed")


def group_parts(name, dimensions=None) -> list[str] | None:
    """The five parts of a group: from a 0.2.5+ measure's dimensions, or a 0.1.1 name (exactly four " | ");
    else None."""
    if name == GROUP_RESULT:
        if not isinstance(dimensions, Mapping) or not dimensions.get("concern"):
            return None
        return [str(dimensions.get(k) or "") for k in GROUP_DIMENSIONS]
    if not isinstance(name, str) or name.count(" | ") != 4:
        return None
    parts = [p.strip() for p in name.split(" | ")]
    return parts if len(parts) == 5 else None


def group_description(description) -> dict:
    """{check, tolerance, passed, failed, total}; None fields when the text does not parse."""
    empty = {"check": None, "tolerance": None, "passed": None, "failed": None, "total": None}
    if not isinstance(description, str):
        return empty
    match = _GROUP_DESCRIPTION.match(description)
    if not match:
        return empty
    tolerance = None
    try:
        tolerance = float(match.group("tol")) if match.group("tol").strip() else None
    except ValueError:
        tolerance = None
    return {"check": match.group("check") or None, "tolerance": tolerance, "passed": int(match.group("p")),
            "failed": int(match.group("f")), "total": int(match.group("n"))}


def checks_passed(description) -> tuple[int, int] | None:
    """(a, b) from "{a}/{b} tolerance checks passed", else None."""
    if not isinstance(description, str):
        return None
    match = _CHECKS_PASSED.search(description)
    return (int(match.group(1)), int(match.group(2))) if match else None
