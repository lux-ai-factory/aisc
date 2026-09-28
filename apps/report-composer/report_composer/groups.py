"""The module groups of the layout editor's palette (report modules spec 2026-09-28, section 3)."""
from __future__ import annotations

GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("AI card", ("ai_card", "risk_classification")),
    ("Control objectives", ("control_objectives", "control_answers", "summary_coverage")),
    ("Tests run", ("test_runs",)),
    ("Results", ("test_results", "dashboard_chart", "chart")),
    ("Summary", ("key_figures", "changes_since")),
    ("Document", ("cover", "chapter", "free_text", "appendix")),
]


def palette(types: list[dict]) -> list[dict]:
    """The block types in their groups, in the order above; a type of no group (a plugin's) goes last,
    under Other."""
    by_id = {t["type_id"]: t for t in types}
    out, placed = [], set()
    for label, ids in GROUPS:
        members = [by_id[i] for i in ids if i in by_id]
        placed.update(ids)
        if members:
            out.append({"label": label, "types": members})
    rest = [t for t in types if t["type_id"] not in placed]
    if rest:
        out.append({"label": "Other", "types": rest})
    return out
