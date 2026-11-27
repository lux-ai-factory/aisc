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
    # the card's reviewed components: a reviewer's correction of the drafted graph, and discarding them all
    ("apps/qualification/src/server/services/OntologyService.ts", "patchNode", "this.claimComponents("),
    ("apps/qualification/src/server/services/OntologyService.ts", "resetPatch", "this.claimComponents("),
    # a checklist submission's answers: a draft saved (or closed), and a new submission
    ("apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "saveDraft", "claimSections("),
    ("apps/controls/src/app/p/[project]/checklists/[id]/fill/actions.ts", "submitForm", "claimSections("),
    # a proof file of an answer, attached or removed: the section of that answer
    ("apps/controls/src/lib/proofFiles.ts", "attachProofFile", "claimSections("),
    ("apps/controls/src/lib/proofFiles.ts", "removeProofFile", "claimSections("),
    # the risk register: ratings and their comments, and a mapping by hand
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "rate", "self._claim_register("),
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "save_risk_mapping",
     "self._claim_register("),
    # the key ticks: set, and all cleared
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "save_keys", "self._claim_register("),
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "clear_keys", "self._claim_register("),
]
#: the helpers the save paths call, and the shared helper each one calls in turn
HELPERS = [
    ("apps/qualification/src/server/services/OntologyService.ts", "claimComponents", "claimForSave("),
    ("apps/controls/src/lib/checklistSections.ts", "claimSections", "claimForSave("),
    ("apps/control-objectives/src/aisc_control_objectives/db/repository.py", "_claim_register",
     "holds.claim_for_save("),
]

#: writes on the content of a part that claim nothing in this version: (file, function or method, why)
NOT_CLAIMED = [
    ("apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "reopenForAmendment",
     "an amendment copies a closed submission's answers into a new draft as they were: nobody types them"),
    ("apps/controls/src/app/p/[project]/submissions/[id]/actions.ts", "saveDraft",
     "a submission's label is saved here without a claim: it names the whole submission, not one of its sections"),
    ("apps/controls/src/app/p/[project]/checklists/[id]/review/actions.ts", "saveReviewedQuestions",
     "a review of the checklist removes the answers to the questions it removes, in every draft: the checklist's "
     "owner decides that, not a section's holder"),
    ("apps/control-objectives/src/aisc_control_objectives/projects.py", "use_profile",
     "a profile switch changes which objectives the assessment runs on, not the register's content"),
    ("apps/control-objectives/src/aisc_control_objectives/projects.py", "_map_risks_of",
     "the AI mapping run is an automatic writer; its holder rule (write only for the holder when it started) is "
     "not built in this version"),
    ("apps/qualification/src/app/p/[project]/api/qualifications/[id]/extracted/route.ts", "PUT",
     "the card agent's draft is an automatic writer; its holder rule is not built in this version"),
]

#: the files that write a checklist submission's answers (controls), by what they do
ANSWER_WRITERS = {
    # save paths, above
    "apps/controls/src/app/p/[project]/submissions/[id]/actions.ts":
        "saveDraft claims; reopenForAmendment copies a closed submission's answers into a new draft as they were",
    "apps/controls/src/app/p/[project]/checklists/[id]/fill/actions.ts": "submitForm claims",
    # not a save on a part in this version
    "apps/controls/src/lib/proofFiles.ts": "attachProofFile and removeProofFile claim",
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


@pytest.mark.parametrize(("path", "name", "why"), NOT_CLAIMED,
                         ids=[f"{p.split('/')[1]}:{n}" for p, n, _ in NOT_CLAIMED])
def test_each_write_left_unclaimed_still_exists(path, name, why):
    assert _body(path, name)


def test_no_file_writes_a_checklists_answers_without_being_classified():
    found = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "apps/controls/src").rglob("*.ts")
                   if ANSWER_WRITE.search("\n".join(_code_lines(p))))
    unclassified = [p for p in found if p not in ANSWER_WRITERS]
    assert unclassified == [], ("these files write a checklist's answers and are on no list here:\n"
                                + "\n".join(unclassified))
