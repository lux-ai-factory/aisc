"""Which page action creates each kind of task held in this version, and which one submits it.

The first save on a part nobody holds creates the task and the part (work.claim_for_save, called through the
helper of the app's language). The step's own completing action submits the task where the step has one;
where it has none, a "Submit for check" button on its page does. Both submit through the platform's
POST /projects/{p}/work/{kind}/{subject}/submit. A kind not listed here is not held in this version.

Each row names the function that does it and the call it makes, so a test (tests/test_work_mapping.py) reads
that function and finds the call and the kind there.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Where:
    """A function of an app, by file (from the repository's root) and name, and the call it makes."""
    path: str
    function: str
    call: str


@dataclass(frozen=True)
class Row:
    subject: str
    parts: str
    creates: Where
    submits: Where


QUALIFICATION = "apps/qualification/src"
CONTROLS = "apps/controls/src"
CONTROL_OBJECTIVES = "apps/control-objectives/src/aisc_control_objectives"

ROWS: dict[str, Row] = {
    # the project's AI card, across its versions: every save makes a new version
    "describe_system": Row(
        subject="card",
        parts="the sections of the card's form",
        creates=Where(f"{QUALIFICATION}/server/services/QualificationService.ts", "storeCard", "claimForSave("),
        submits=Where(f"{QUALIFICATION}/app/p/[project]/qualify/[id]/submit-actions.ts", "submitCardForCheck",
                      "submitWork("),
    ),
    # one checklist submission; closing it is the step's own completing action
    "fill_checklist": Row(
        subject="the submission's id",
        parts="the sections (question categories) of the checklist",
        creates=Where(f"{CONTROLS}/lib/checklistSections.ts", "claimSections", "claimForSave("),
        submits=Where(f"{CONTROLS}/app/p/[project]/submissions/[id]/actions.ts", "saveDraft", "submitTask("),
    ),
    # the risk register of one card version: ratings, comments, mappings and key ticks
    "rate_risks": Row(
        subject="the card version's pid",
        parts="one part, the register",
        creates=Where(f"{CONTROL_OBJECTIVES}/db/repository.py", "_claim_register", "holds.claim_for_save("),
        submits=Where(f"{CONTROL_OBJECTIVES}/api/app.py", "submit_register_form", "submit_task("),
    ),
}
