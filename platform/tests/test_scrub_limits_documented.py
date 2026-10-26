"""The scrub's limits are written down where a reader meets them: next to the rule (connection_facade's
scrub functions) and in the root CHANGELOG's entry for it. Forms the scrub does not take: hex, unpadded
base64, double encodings, case changes, and a secret split across output items or calls. The target must not
echo credentials; the answer scrub is a safety net, not a guarantee. No database."""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from platform_service import connection_facade

ROOT = Path(__file__).resolve().parents[2]

#: each limit, as a pattern any honest wording of it matches (lower case)
LIMITS = {
    "hex": r"\bhex",
    "unpadded base64": r"unpadded",
    "double encodings": r"double",
    "case changes": r"\bcase\b",
    "a secret split across output items or calls": r"split",
    "the target must not echo credentials": r"must not echo",
    "a safety net, not a guarantee": r"safety net",
}


def missing_limits(text: str) -> list[str]:
    text = " ".join(text.lower().split())
    return [limit for limit, pattern in LIMITS.items() if not re.search(pattern, text)]


def the_rules_comments() -> str:
    """The docstrings of the scrub functions and the comments just above them."""
    parts = []
    for fn in (connection_facade.scrub, connection_facade.secret_forms, connection_facade.scrub_answer):
        parts += [inspect.getdoc(fn) or "", inspect.getcomments(fn) or ""]
    return "\n".join(parts)


def unreleased_entries() -> list[str]:
    """The bullets of the CHANGELOG's newest section, each with its continuation lines."""
    text = (ROOT / "CHANGELOG.md").read_text()
    sections = re.split(r"^## ", text, flags=re.M)
    newest = sections[1]
    return [entry for entry in re.split(r"^- ", newest, flags=re.M)[1:]]


def test_the_scrubs_comment_names_every_documented_limit():
    missing = missing_limits(the_rules_comments())
    assert not missing, f"the scrub's comment does not name: {missing}"


def test_the_changelogs_scrub_entry_names_every_documented_limit():
    entries = [e for e in unreleased_entries() if "scrub" in e.lower()]
    assert entries, "no CHANGELOG entry about the scrub in the newest section"
    best = min(entries, key=lambda e: len(missing_limits(e)))
    missing = missing_limits(best)
    assert not missing, f"no scrub entry of the CHANGELOG's newest section names: {missing}"
