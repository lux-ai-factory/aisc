"""Which page action creates and submits each kind of task held in this version: one row per kind.

docs/specs/who-does-what.md, section 1: "Which event or page action creates and completes each kind is one table,
platform_service/work/mapping.py, with a test per row." The first save on a part creates the task and the part
(work.claim_for_save); the step's own completing action, or a "Submit for check" button where the step has none,
submits it through the platform's POST /projects/{p}/work/{kind}/{subject}/submit. Each row names the function that
does each, and the call it makes; the test reads that function's source and finds the call and the kind there.

Read as source text; nothing of the apps is imported or run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from platform_service.work import mapping
from platform_service.work.kinds import KINDS

ROOT = Path(__file__).resolve().parents[2]

COMMENT = re.compile(r"^\s*(?:#|//|\*|/\*)")
START = re.compile(r"^(\s*)(?:export\s+)?(?:async\s+)?(?:private\s+|static\s+|public\s+)*(?:async\s+)?"
                   r"(?:function\s+|def\s+)?(\w+)\s*(?:<[^>]*>)?\(")
DEFINES = re.compile(r"\b(?:function|def|async|private)\b")


def _body(path: str, name: str) -> str:
    """The source of function or method `name` in `path`, comments left out: from its first line to the next
    function or method at its own indentation or less."""
    assert (ROOT / path).is_file(), f"{path} is not there"
    lines = [line for line in (ROOT / path).read_text(errors="ignore").splitlines() if not COMMENT.match(line)]
    for i, line in enumerate(lines):
        started = START.match(line)
        if not started or started.group(2) != name or not DEFINES.search(line):
            continue
        indent = len(started.group(1))
        body = [line]
        for following in lines[i + 1:]:
            again = START.match(following)
            if (again and len(again.group(1)) <= indent and following.strip()
                    and re.search(r"\b(?:function|def|async|private|export)\b", following)):
                break
            body.append(following)
        return "\n".join(body)
    raise AssertionError(f"{path} has no function or method {name}")


def _names_kind(body: str, kind: str) -> bool:
    return f'"{kind}"' in body or f"'{kind}'" in body


@pytest.mark.parametrize("kind", ["describe_system", "fill_checklist", "rate_risks"])
def test_each_held_kind_has_a_row(kind):
    assert kind in mapping.ROWS


def test_every_row_is_a_kind_of_task():
    assert set(mapping.ROWS) <= set(KINDS)


@pytest.mark.parametrize("kind", ["describe_system", "fill_checklist", "rate_risks"])
def test_the_first_save_creates_the_task_and_its_parts_where_the_row_says(kind):
    row = mapping.ROWS[kind]
    body = _body(row.creates.path, row.creates.function)
    assert row.creates.call in body, f"{row.creates.function} does not call {row.creates.call}"
    assert _names_kind(body, kind), f"{row.creates.function} does not claim a {kind} task"


@pytest.mark.parametrize("kind", ["describe_system", "fill_checklist", "rate_risks"])
def test_the_action_the_row_names_submits_the_task(kind):
    row = mapping.ROWS[kind]
    body = _body(row.submits.path, row.submits.function)
    assert row.submits.call in body, f"{row.submits.function} does not call {row.submits.call}"
    assert _names_kind(body, kind), f"{row.submits.function} does not submit a {kind} task"
