"""Staffing rules written short, for the tests that compare them.

`stage()` is one check stage with the spec's defaults, `rule()` a whole rule. A test names only the
settings it is about.
"""
from __future__ import annotations

ANY = {"kind": "any"}


def functions(*names):
    return {"kind": "functions", "functions": list(names)}


def people(*subjects):
    return {"kind": "people", "people": list(subjects)}


def stage(needed=1, group=None, kind="review", other_line=False, not_earlier_signer=False,
          any_objection_sends_back=True, due_days=None):
    return {"needed": needed, "from": group or ANY, "kind": kind, "other_line": other_line,
            "not_earlier_signer": not_earlier_signer, "any_objection_sends_back": any_objection_sends_back,
            "due_days": due_days}


def rule(*stages, sampled=None, count=1, mode="any_one", doers_from=None):
    return {"doers": {"count": count, "mode": mode, "from": doers_from or ANY},
            "stages": list(stages), "sampled": sampled}


def floor(min_stages=0, min_needed=1, require_other_line=False, require_not_earlier_signer=False,
          allowed_from=None, sampling=None):
    return {"min_stages": min_stages, "min_needed": min_needed, "require_other_line": require_other_line,
            "require_not_earlier_signer": require_not_earlier_signer, "allowed_from": allowed_from,
            "sampling": sampling}
