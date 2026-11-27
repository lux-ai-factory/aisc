"""Submitting, signing, sending back and finishing a task, and changing how many people check a kind of task,
are on the project's record, each with the person who did it; a send back keeps its reason as content."""
from __future__ import annotations

import pytest

from tests import work_content as wc
from tests.conftest import DSN, project_db
from tests.ledger.conftest import MEMBER, OWNER, entries, log_of, needs_db, person, relay_all

pytestmark = needs_db

TASK = "/projects/{slug}/work/fill_checklist/s1"


@pytest.fixture
def call(through_gateway, mode):
    mode("enforce")
    return through_gateway


@pytest.fixture
def worked(project, call):
    """MEMBER saved a checklist submission's Governance section, with holding on."""
    wc.make_tables(project)
    wc.sql(project, 'INSERT INTO controls.submission_answer ("submissionId", "questionId", answer, score)'
                    " VALUES ('s1', 'q1', 'yes', 4)")
    assert call(OWNER, "PUT", f"/projects/{project['slug']}/work/holds", json={"on": True}).status_code == 200
    with project_db(DSN, project, role="controls_rw") as conn:
        conn.execute("select work.claim_for_save('fill_checklist', 's1', 'governance', 'Governance', %s, 'Member')",
                     (MEMBER,))
    return project


def events(store, pid, prefixes=("task.", "staffing.")):
    relay_all(pid)
    return [e for e in entries(store, log_of(pid)) if e.action.startswith(prefixes)]


def test_changing_the_checkers_of_a_kind_and_applying_a_preset_are_recorded(project, call, memory_ledger):
    slug = project["slug"]
    assert call(OWNER, "PUT", f"/projects/{slug}/work/rules/fill_checklist", json={"checkers": 2}).status_code == 200
    assert call(OWNER, "POST", f"/projects/{slug}/work/preset", json={"preset": "four_eyes"}).status_code == 200
    got = [(e.action, person(project["pid"], e.actor_ref)[0], e.details) for e in events(memory_ledger, project["pid"])]
    assert got == [("staffing.rule_changed", OWNER, {"kind": "fill_checklist", "checkers": 2}),
                   ("staffing.preset_applied", OWNER, {"preset": "four_eyes"})]


def test_a_submit_with_no_checker_is_recorded_as_submitted_and_done(worked, call, memory_ledger):
    submitted = call(MEMBER, "POST", TASK.format(slug=worked["slug"]) + "/submit")
    assert submitted.status_code == 200, submitted.text
    got = [(e.action, person(worked["pid"], e.actor_ref)[0], e.item_id, e.details)
           for e in events(memory_ledger, worked["pid"])]
    assert got == [("task.submitted", MEMBER, "fill_checklist/s1",
                    {"kind": "fill_checklist", "round": 1, "checkers_needed": 0}),
                   ("task.done", MEMBER, "fill_checklist/s1", {"kind": "fill_checklist", "round": 1})]


def test_an_agreement_that_finishes_the_check_is_recorded_as_signed_and_done(worked, call, memory_ledger):
    slug = worked["slug"]
    call(OWNER, "PUT", f"/projects/{slug}/work/rules/fill_checklist", json={"checkers": 1})
    content_hash = call(MEMBER, "POST", TASK.format(slug=slug) + "/submit").json()["content_hash"]
    signed = call(OWNER, "POST", TASK.format(slug=slug) + "/sign",
                  json={"answer": "agree", "content_hash": content_hash})
    assert signed.status_code == 200, signed.text
    got = [(e.action, person(worked["pid"], e.actor_ref)[0]) for e in events(memory_ledger, worked["pid"], ("task.",))]
    assert got == [("task.submitted", MEMBER), ("task.signed", OWNER), ("task.done", OWNER)]


def test_a_send_back_is_recorded_with_its_reason_as_content(worked, call, memory_ledger):
    from platform_service.ledger import secrets

    slug = worked["slug"]
    call(OWNER, "PUT", f"/projects/{slug}/work/rules/fill_checklist", json={"checkers": 1})
    content_hash = call(MEMBER, "POST", TASK.format(slug=slug) + "/submit").json()["content_hash"]
    sent = call(OWNER, "POST", TASK.format(slug=slug) + "/sign",
                json={"answer": "send_back", "reason": "Question 1 needs evidence", "content_hash": content_hash})
    assert sent.status_code == 200, sent.text
    [sent_back] = [e for e in events(memory_ledger, worked["pid"]) if e.action == "task.sent_back"]
    assert person(worked["pid"], sent_back.actor_ref)[0] == OWNER
    assert sent_back.content_sha256 == secrets.content_digest(worked["pid"], {"reason": "Question 1 needs evidence"})
    assert "reason" not in sent_back.details
