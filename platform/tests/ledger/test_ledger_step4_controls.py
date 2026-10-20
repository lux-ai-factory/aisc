"""The controls app's events, in the shapes its actions send (apps/controls/src/app/**/actions.ts),
are accepted by the relay against the REAL registry, each citing the witnessed request of the page the
action is posted from, as controls_rw. A draft's save and its close are one server action (same_action)."""
from __future__ import annotations

import uuid

import pytest

from tests.ledger.conftest import MEMBER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_db
S, C = "cmsub0000000000000000001", "cmchk0000000000000000001"


@pytest.fixture(autouse=True)
def _enforce(mode):
    mode("enforce")


def body(request_id, action, item_type, item_id, **over):
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": item_type,
         "item_id": item_id, "details": {}}
    e.update(over)
    return e


def rejected(store, pid):
    return [e.details["reason"] for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


STATE = {"label": "Run", "status": "Draft", "answers": [{"questionId": "q1", "answer": "yes", "score": None}]}
QUESTION = {"id": "cmq1", "order": 1, "text": "Is it logged?", "article": None, "category": None}
META = {"title": "Accuracy", "sourceId": "cmsrc", "controlTopic": "Accuracy", "description": None,
        "sourceUpdatedAt": None, "countryIds": ["lu"], "regulationIds": ["eu-ai-act"]}
CASES = [
    (f"/checklists/{C}/fill", "controls.submission.created", "submission", S,
     {"details": {"checklist": C}, "content": STATE, "after": STATE}),
    (f"/submissions/{S}", "controls.submission.draft_saved", "submission", S,
     {"content": STATE, "before": STATE, "after": STATE}),
    (f"/submissions/{S}", "controls.submission.closed", "submission", S,
     {"details": {"score": 3}, "content": STATE, "before": STATE, "after": {**STATE, "status": "Closed"}}),
    (f"/submissions/{S}", "controls.submission.reopened", "submission", S,
     {"details": {"next": "cmnext", "version": 2}, "content": {"next": STATE}}),
    (f"/submissions/{S}", "controls.submission.archived", "submission", S, {}),
    (f"/submissions/{S}", "controls.submission.restored", "submission", S, {}),
    (f"/submissions/{S}", "controls.submission.discarded", "submission", S,
     {"details": {"checklist": C}, "before": STATE}),
    (f"/checklists/{C}/review", "controls.checklist.questions_revised", "checklist", C,
     {"item_version": "2", "details": {"version": 2, "questions": 3, "added": 1, "reworded": 1, "removed": 1,
                                       "moved": 0, "answers_removed": 4, "closed_answers_removed": 2},
      "content": {"before": [QUESTION], "after": [{**QUESTION, "id": "cmq2", "text": "Reworded?"}],
                  "checklist": {"before": META, "after": META},
                  "removed_answers": [{"submission": S, "status": "Closed", "version": 1, "question": "cmq1",
                                       "answer": "yes", "score": None}]}}),
    (f"/checklists/{C}/review", "controls.submission.answers_removed", "submission", S,
     {"details": {"checklist": C, "version": 2, "answers_removed": 1}, "before": STATE,
      "after": {**STATE, "answers": []}}),
    (f"/checklists/{C}/review", "controls.checklist.edited", "checklist", C,
     {"before": META, "after": {**META, "title": "Retitled"}}),
    ("/install", "control.installed", "checklist", C,
     {"details": {"package": "eu-ai-act-art-9", "questions": 12},
      "content": {"package_sha256": "a" * 64, "source": {"id": "cmsrc", "name": "AESIA", "url": None},
                  "questions": [QUESTION]}}),
]


@pytest.mark.parametrize("tail, action, item_type, item_id, over", CASES, ids=[c[1] for c in CASES])
def test_an_event_as_the_app_sends_it_is_accepted(project, memory_ledger, witnessed, tail, action, item_type,
                                                  item_id, over):
    request_id = witnessed(MEMBER, "POST", "controls", f"/controls/p/{project['pid']}{tail}", next_action="7f0d01")
    emit(project["pid"], "controls_rw", body(request_id, action, item_type, item_id, **over))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    [e] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == action]
    assert (e.source_app, e.item_id) == ("controls", item_id)


def test_a_drafts_save_and_its_close_share_one_action_id(project, memory_ledger, witnessed):
    first = witnessed(MEMBER, "POST", "controls", f"/controls/p/{project['pid']}/submissions/{S}", next_action="7f0d02")
    emit(project["pid"], "controls_rw", body(first, "controls.submission.draft_saved", "submission", S, content=STATE))
    relay_all(project["pid"])
    later = witnessed(MEMBER, "POST", "controls", f"/controls/p/{project['pid']}/submissions/{S}", next_action="7f0d02")
    emit(project["pid"], "controls_rw", body(later, "controls.submission.closed", "submission", S,
                                             details={"score": 1}, content=STATE))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []


def test_a_reviews_edit_and_its_question_revision_share_one_action_id(project, memory_ledger, witnessed):
    """saveReviewedQuestions records `edited` when the questions stay, `questions_revised` when they change."""
    page = f"/controls/p/{project['pid']}/checklists/{C}/review"
    first = witnessed(MEMBER, "POST", "controls", page, next_action="7f0d03")
    emit(project["pid"], "controls_rw", body(first, "controls.checklist.edited", "checklist", C,
                                             before=META, after=META))
    relay_all(project["pid"])
    later = witnessed(MEMBER, "POST", "controls", page, next_action="7f0d03")
    emit(project["pid"], "controls_rw", body(later, "controls.checklist.questions_revised", "checklist", C,
                                             item_version="2", content={"before": [], "after": []},
                                             details={"version": 2, "questions": 1, "answers_removed": 0,
                                                      "closed_answers_removed": 0}))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []


@pytest.mark.parametrize("first_actions", [("controls.checklist.edited",),
                                           ("controls.checklist.questions_revised",
                                            "controls.submission.answers_removed")])
def test_a_review_that_removes_answers_records_each_submission_it_changed(project, memory_ledger, witnessed,
                                                                          first_actions):
    """A review that removes questions records, per submission that lost answers, the state before and
    after (so that draft's next save chains on the state without them, not a false tamper alarm). The review's
    path names the checklist, so the submission's id is not bound to it; the action id is saveReviewedQuestions',
    whichever of its branches ran first."""
    page = f"/controls/p/{project['pid']}/checklists/{C}/review"
    first = witnessed(MEMBER, "POST", "controls", page, next_action="7f0d04")
    for action in first_actions:
        if action == "controls.checklist.edited":
            emit(project["pid"], "controls_rw", body(first, action, "checklist", C, before=META, after=META))
        else:
            item_type, item_id, fields = removal(action)
            emit(project["pid"], "controls_rw", body(first, action, item_type, item_id, **fields))
    relay_all(project["pid"])
    later = witnessed(MEMBER, "POST", "controls", page, next_action="7f0d04")
    for action in ("controls.checklist.questions_revised", "controls.submission.answers_removed",
                   "controls.submission.answers_removed"):
        item_type, item_id, fields = removal(action)
        emit(project["pid"], "controls_rw", body(later, action, item_type, item_id, **fields))
    relay_all(project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    removed = [e for e in entries(memory_ledger, log_of(project["pid"]))
               if e.action == "controls.submission.answers_removed"]
    assert len(removed) == first_actions.count("controls.submission.answers_removed") + 2


def removal(action):
    """(item_type, item_id, fields) of a review's question revision, or of one submission it changed."""
    if action == "controls.checklist.questions_revised":
        return "checklist", C, {"item_version": "2", "content": {"before": [QUESTION], "after": []},
                                "details": {"version": 2, "questions": 0, "answers_removed": 1,
                                            "closed_answers_removed": 0}}
    return "submission", f"cmsub{uuid.uuid4().hex[:19]}", {
        "details": {"checklist": C, "version": 2, "answers_removed": 1},
        "before": STATE, "after": {**STATE, "answers": []}}
