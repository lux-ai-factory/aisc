"""Staffing rules: how many people do a task, and the check stages after it.

A rule is plain data, chosen by a project for one task kind and one tier. Nothing here touches a
database: the functions take the rule, the floor and what they compare, and answer. The number of
people is a setting, so one person with no check, four eyes and a committee are the same shape.
"""
from __future__ import annotations

import copy
import hashlib
import hmac

from platform_service.work.kinds import TIERS

MAX_STAGES = 4
MAX_PEOPLE = 20
MAX_DUE_DAYS = 60
MAX_ONE_IN = 100
CONDITIONS = ("test_failed", "risk_above_3", "risk_above_4", "doer_asked")
DOER_MODES = ("any_one", "all")
STAGE_KINDS = ("review", "approval")
AUDIT = "audit"
AUDIT_LINE = 3

_RULE_KEYS = ("doers", "stages", "sampled")
_DOER_KEYS = ("count", "mode", "from")
_STAGE_KEYS = ("needed", "from", "kind", "other_line", "not_earlier_signer", "any_objection_sends_back",
               "due_days")
_INDEPENDENCE = ("other_line", "not_earlier_signer", "any_objection_sends_back")

#: the order a list of reasons is given in
LOOSENING_REASONS = ("fewer_stages", "fewer_needed", "wider_group", "weaker_independence", "approval_to_review",
                     "more_sampling")
FLOOR_CODES = ("too_few_stages", "too_few_needed", "other_line_required", "not_earlier_signer_required",
               "group_not_allowed", "sampling_not_allowed")


class InvalidRule(ValueError):
    """A rule that cannot be carried out, with where (`pointer`, as in /stages/0/needed) and why."""

    def __init__(self, pointer: str, message: str):
        super().__init__(f"{pointer}: {message}")
        self.pointer = pointer
        self.message = message


def _default_stage() -> dict:
    return {"needed": 1, "from": {"kind": "any"}, "kind": "review", "other_line": False,
            "not_earlier_signer": False, "any_objection_sends_back": True, "due_days": None}


def _unknown(given: dict, allowed: tuple, at: str) -> None:
    for key in given:
        if key not in allowed:
            raise InvalidRule(f"{at}/{key}", "is not a setting of a staffing rule")


def _whole(value, low: int, high: int, at: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRule(at, f"must be a whole number from {low} to {high}")
    if value < low:
        raise InvalidRule(at, f"must be at least {low}")
    if value > high:
        raise InvalidRule(at, f"must be at most {high}")
    return value


def _flag(value, at: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRule(at, "must be true or false")
    return value


def _group(given, at: str, functions: dict | None) -> dict:
    if not isinstance(given, dict):
        raise InvalidRule(at, "must say who: any member, functions or people")
    kind = given.get("kind")
    if kind == "any":
        _unknown(given, ("kind",), at)
        return {"kind": "any"}
    if kind == "functions":
        _unknown(given, ("kind", "functions"), at)
        names = given.get("functions")
        if not isinstance(names, list) or not names:
            raise InvalidRule(f"{at}/functions", "must name at least 1 function")
        for i, name in enumerate(names):
            if name == AUDIT or (functions is not None and functions.get(name) == AUDIT_LINE):
                raise InvalidRule(f"{at}/functions/{i}", "audit is never a doer or a checker")
            if functions is not None and name not in functions:
                raise InvalidRule(f"{at}/functions/{i}", f"the project has no function {name!r}")
        return {"kind": "functions", "functions": list(names)}
    if kind == "people":
        _unknown(given, ("kind", "people"), at)
        people = given.get("people")
        if not isinstance(people, list) or not people or not all(isinstance(p, str) and p for p in people):
            raise InvalidRule(f"{at}/people", "must name at least 1 person")
        return {"kind": "people", "people": list(people)}
    raise InvalidRule(f"{at}/kind", "must be any, functions or people")


def _stage(given, i: int, functions: dict | None) -> dict:
    at = f"/stages/{i}"
    if not isinstance(given, dict):
        raise InvalidRule(at, "must be a check stage")
    _unknown(given, _STAGE_KEYS, at)
    stage = {**_default_stage(), **given}
    stage["from"] = _group(stage["from"], f"{at}/from", functions)
    stage["needed"] = _whole(stage["needed"], 1, MAX_PEOPLE, f"{at}/needed")
    if stage["from"]["kind"] == "people" and stage["needed"] > len(stage["from"]["people"]):
        raise InvalidRule(f"{at}/needed", "cannot be more than the people the stage names")
    if stage["kind"] not in STAGE_KINDS:
        raise InvalidRule(f"{at}/kind", "must be review or approval")
    for key in _INDEPENDENCE:
        stage[key] = _flag(stage[key], f"{at}/{key}")
    if stage["due_days"] is not None:
        stage["due_days"] = _whole(stage["due_days"], 1, MAX_DUE_DAYS, f"{at}/due_days")
    return stage


def _sampled(given, has_stage: bool):
    if given is None:
        return None
    if not has_stage:
        raise InvalidRule("/sampled", "a rule with no check stage has nothing to sample")
    if not isinstance(given, dict) or len(given) != 1:
        raise InvalidRule("/sampled", "must be one_in or when")
    if "one_in" in given:
        return {"one_in": _whole(given["one_in"], 2, MAX_ONE_IN, "/sampled/one_in")}
    if "when" in given:
        when = given["when"]
        if not isinstance(when, list) or not when:
            raise InvalidRule("/sampled/when", "must name at least 1 condition")
        for i, condition in enumerate(when):
            if condition not in CONDITIONS:
                raise InvalidRule(f"/sampled/when/{i}", f"is not one of {', '.join(CONDITIONS)}")
        if set(when) == {"doer_asked"}:
            raise InvalidRule("/sampled/when", "the doer asking cannot be the only reason for a check")
        return {"when": list(when)}
    raise InvalidRule("/sampled", "must be one_in or when")


def validate(rule: dict, functions: dict | None = None) -> dict:
    """The rule with every default filled in, or InvalidRule. `functions` maps the project's function names to
    their lines; without it, names are not checked against a project (audit is still refused). The rule given
    is not changed."""
    if not isinstance(rule, dict):
        raise InvalidRule("", "must be an object")
    rule = copy.deepcopy(rule)
    _unknown(rule, _RULE_KEYS, "")
    doers = rule.get("doers") or {}
    if not isinstance(doers, dict):
        raise InvalidRule("/doers", "must be an object")
    _unknown(doers, _DOER_KEYS, "/doers")
    count = _whole(doers.get("count", 1), 1, MAX_PEOPLE, "/doers/count")
    mode = doers.get("mode", "any_one")
    if mode not in DOER_MODES:
        raise InvalidRule("/doers/mode", "must be any_one or all")
    doers_from = _group(doers.get("from", {"kind": "any"}), "/doers/from", functions)
    stages = rule.get("stages") or []
    if not isinstance(stages, list):
        raise InvalidRule("/stages", "must be a list")
    if len(stages) > MAX_STAGES:
        raise InvalidRule("/stages", f"a rule has at most {MAX_STAGES} check stages")
    stages = [_stage(s, i, functions) for i, s in enumerate(stages)]
    sampled = _sampled(rule.get("sampled"), bool(stages))
    return {"doers": {"count": count, "mode": mode, "from": doers_from}, "stages": stages, "sampled": sampled}


def _normal(rule: dict) -> dict:
    return validate(rule)


# -- what lowers control ---------------------------------------------------------------------------------

_GROUP_RANK = {"people": 0, "functions": 1, "any": 2}


def _wider(before: dict, after: dict) -> bool:
    b, a = _GROUP_RANK[before["kind"]], _GROUP_RANK[after["kind"]]
    if a != b:
        return a > b
    if before["kind"] == "functions":
        return bool(set(after["functions"]) - set(before["functions"]))
    if before["kind"] == "people":
        return bool(set(after["people"]) - set(before["people"]))
    return False


def _more_sampling(before, after) -> bool:
    if after is None:
        return False
    if before is None:
        return True
    if "one_in" in before and "one_in" in after:
        return after["one_in"] > before["one_in"]
    if "when" in before and "when" in after:
        return bool(set(before["when"]) - set(after["when"]))
    return "one_in" in before and "when" in after


def is_loosening(before: dict, after: dict) -> list[str]:
    """The reasons the change from `before` to `after` lowers control, each once, in LOOSENING_REASONS order;
    empty when it is not looser in any setting. Doers and due days never count."""
    before, after = _normal(before), _normal(after)
    found = set()
    if len(after["stages"]) < len(before["stages"]):
        found.add("fewer_stages")
    for b, a in zip(before["stages"], after["stages"]):
        if a["needed"] < b["needed"]:
            found.add("fewer_needed")
        if _wider(b["from"], a["from"]):
            found.add("wider_group")
        if any(b[key] and not a[key] for key in _INDEPENDENCE):
            found.add("weaker_independence")
        if b["kind"] == "approval" and a["kind"] == "review":
            found.add("approval_to_review")
    if _more_sampling(before["sampled"], after["sampled"]):
        found.add("more_sampling")
    return [r for r in LOOSENING_REASONS if r in found]


def tier_change(before: str, after: str) -> list[str]:
    """["lower_tier"] when the tier goes down, else empty."""
    return ["lower_tier"] if TIERS.index(after) < TIERS.index(before) else []


# -- the floor -------------------------------------------------------------------------------------------

def _sampling_allows(sampling, sampled) -> bool:
    """Whether the floor's sampling setting admits the rule's sampling as if it were a stage."""
    return (isinstance(sampling, dict) and sampled is not None and "one_in" in sampled
            and sampled["one_in"] <= sampling["max_one_in"])


def _sampling_refused(sampling, sampled) -> bool:
    if sampled is None or sampling is None:
        return False
    if sampling == "never":
        return True
    return "when" in sampled or sampled["one_in"] > sampling["max_one_in"]


def meets_floor(rule: dict, floor: dict | None) -> list[str]:
    """What the rule lacks against the floor, in FLOOR_CODES order; empty when it meets it. No floor: free."""
    if floor is None:
        return []
    rule = _normal(rule)
    stages, sampled, sampling = rule["stages"], rule["sampled"], floor.get("sampling")
    counted = len(stages) if sampled is None or _sampling_allows(sampling, sampled) else 0
    found = []
    if counted < floor.get("min_stages", 0):
        found.append("too_few_stages")
    if any(s["needed"] < floor.get("min_needed", 1) for s in stages):
        found.append("too_few_needed")
    if floor.get("require_other_line") and any(not s["other_line"] for s in stages):
        found.append("other_line_required")
    if floor.get("require_not_earlier_signer") and any(not s["not_earlier_signer"] for s in stages[1:]):
        found.append("not_earlier_signer_required")
    allowed = floor.get("allowed_from")
    if allowed is not None and any(s["from"]["kind"] != "functions" or not set(s["from"]["functions"]) <= set(allowed)
                                   for s in stages):
        found.append("group_not_allowed")
    if _sampling_refused(sampling, sampled):
        found.append("sampling_not_allowed")
    return found


def _sampling_strictness(sampling) -> tuple:
    """Higher is stricter: never, then a limit (a smaller one_in is stricter), then no word at all."""
    if sampling == "never":
        return (2, 0)
    if isinstance(sampling, dict):
        return (1, -sampling["max_one_in"])
    return (0, 0)


def combine_floors(for_tier: dict | None, for_every_tier: dict | None) -> dict | None:
    """The floor in force: the stricter of the two, setting by setting. Either may be missing."""
    if for_tier is None or for_every_tier is None:
        return copy.deepcopy(for_tier if for_tier is not None else for_every_tier)
    a, b = for_tier, for_every_tier
    allowed_a, allowed_b = a.get("allowed_from"), b.get("allowed_from")
    if allowed_a is None or allowed_b is None:
        allowed = list(allowed_a if allowed_a is not None else allowed_b) if (allowed_a or allowed_b) is not None else None
    else:
        allowed = [f for f in allowed_a if f in allowed_b]
    sampling = max((a.get("sampling"), b.get("sampling")), key=_sampling_strictness)
    return {"min_stages": max(a.get("min_stages", 0), b.get("min_stages", 0)),
            "min_needed": max(a.get("min_needed", 1), b.get("min_needed", 1)),
            "require_other_line": bool(a.get("require_other_line") or b.get("require_other_line")),
            "require_not_earlier_signer": bool(a.get("require_not_earlier_signer")
                                               or b.get("require_not_earlier_signer")),
            "allowed_from": allowed,
            "sampling": copy.deepcopy(sampling)}


def is_lower_floor(before: dict | None, after: dict | None) -> bool:
    """Whether the new floor asks for less than the old one in any setting. Removing a floor is lower; setting
    the first one is not."""
    if before is None:
        return False
    if after is None:
        return True
    if after.get("min_stages", 0) < before.get("min_stages", 0):
        return True
    if after.get("min_needed", 1) < before.get("min_needed", 1):
        return True
    for key in ("require_other_line", "require_not_earlier_signer"):
        if before.get(key) and not after.get(key):
            return True
    allowed_b, allowed_a = before.get("allowed_from"), after.get("allowed_from")
    if allowed_b is not None and (allowed_a is None or set(allowed_a) - set(allowed_b)):
        return True
    return _sampling_strictness(after.get("sampling")) < _sampling_strictness(before.get("sampling"))


# -- sampling ---------------------------------------------------------------------------------------------

def draw_sample(key: bytes, subject_id: str, one_in: int) -> bool:
    """Whether a submitted task about `subject_id` is checked under "one in `one_in`". Keyed with the project's
    ledger key, so the draw cannot be worked out from a page, and taken from the subject alone, so handing the
    same thing in again gives the same answer. An auditor with the key can recompute it."""
    digest = hmac.new(key, subject_id.encode(), hashlib.sha256).digest()
    return int.from_bytes(digest, "big") % one_in == 0
