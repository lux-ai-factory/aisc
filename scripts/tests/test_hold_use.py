"""Every save path on the content of a held part calls the holder helper.

Only the holder of a part saves on it (docs/specs/who-does-what.md, section 2). Every save on the content of a
part claims it, through the helper of its language (aisc_identity.holds.claim_for_save, claimForSave in
shared/access-ts/holds.ts), inside the transaction that writes. The save paths of qualification, controls and
control-objectives are listed here with the call each makes; a save path that does not make it fails the test.
The files that write a checklist's answers are listed too, by what they do: a new one has to be classified.

Read as source text; nothing is imported or run.

Run from the repo root:

    uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        python -m pytest -q -p no:cacheprovider scripts/tests/test_hold_use.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: (file, function or method, the call it makes inside its transaction)
SAVE_PATHS = [
    # the AI card: a save and a correction both store the card here, claiming every section of its form
    ("apps/qualification/src/server/services/QualificationService.ts", "storeCard", "claimForSave("),
    # a checklist submission's answers: a draft saved (or closed), and a new submission
    ("apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "saveDraft", "claimSections("),
    ("apps/controls/src/app/p/[project]/checklists/[id]/fill/actions.ts", "submitForm", "claimSections("),
    # the risk register: ratings and their comments, and a mapping by hand
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "rate", "self._claim_register("),
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "save_risk_mapping",
     "self._claim_register("),
]
#: the helpers the save paths call, and the shared helper each one calls in turn
HELPERS = [
    ("apps/controls/src/lib/checklistSections.ts", "claimSections", "claimForSave("),
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "_claim_register",
     "holds.claim_for_save("),
]

#: the files that write a checklist submission's answers (controls), by what they do
ANSWER_WRITERS = {
    # save paths, above
    "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts":
        "saveDraft claims; reopenForAmendment copies a closed submission's answers into a new draft as they were",
    "apps/controls/src/app/p/[project]/checklists/[id]/fill/actions.ts": "submitForm claims",
    # not a save on a part in this version
    "apps/controls/src/lib/proofFiles.ts": "links a proof file to an answer; the answer's text is not changed",
    "apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts":
        "a review of the checklist removes the answers to the questions it removes, in every draft",
}

#: a write of a checklist's answers, in Prisma as controls writes it
ANSWER_WRITE = re.compile(r"\.submissionAnswer\.(?:create|createMany|update|updateMany|upsert|delete|deleteMany)\(")
COMMENT = re.compile(r"^\s*(?:#|//|\*|/\*)")
#: where a function or method starts, in the TypeScript and Python of these modules
START = re.compile(r"^(\s*)(?:export\s+)?(?:async\s+)?(?:private\s+|static\s+|public\s+)*(?:async\s+)?"
                   r"(?:function\s+|def\s+)?(\w+)\s*(?:<[^>]*>)?\(")


def _code_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(errors="ignore").splitlines() if not COMMENT.match(line)]


def _body(path: str, name: str) -> str:
    """The source of function or method `name` in `path`: from its first line to the next function or method
    at its own indentation or less."""
    lines = _code_lines(ROOT / path)
    for i, line in enumerate(lines):
        started = START.match(line)
        if not started or started.group(2) != name or not re.search(r"\b(?:function|def|async|private)\b", line):
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
    raise AssertionError(f"{path} has no function or method {name}: the list here is out of date")


@pytest.mark.parametrize(("path", "name", "call"), SAVE_PATHS + HELPERS,
                         ids=[f"{p.split('/')[1]}:{n}" for p, n, _ in SAVE_PATHS + HELPERS])
def test_each_save_path_calls_the_holder_helper(path, name, call):
    assert call in _body(path, name), f"{path}: {name} saves on a held part without calling {call.rstrip('(')}"


def test_no_file_writes_a_checklists_answers_without_being_classified():
    found = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "apps/controls/src").rglob("*.ts")
                   if ANSWER_WRITE.search("\n".join(_code_lines(p))))
    unclassified = [p for p in found if p not in ANSWER_WRITERS]
    assert unclassified == [], ("these files write a checklist's answers and are on no list here:\n"
                                + "\n".join(unclassified))
