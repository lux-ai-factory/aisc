"""Who holds a part of a task is on the project's record: each take, release, hand-over and take-over is an event
with the person who made it, and a take-over keeps its reason."""
from __future__ import annotations

import pytest

from tests.conftest import DSN, project_db
from tests.ledger.conftest import OWNER, MEMBER, entries, log_of, needs_db, person, relay_all

pytestmark = needs_db

PART = "/projects/{slug}/work/fill_checklist/submission-1/parts/governance/{action}"


@pytest.fixture
def call(through_gateway, mode):
    mode("enforce")
    return through_gateway


@pytest.fixture
def task(project):
    with project_db(DSN, project) as conn:
        tid = conn.execute("insert into work.task (kind, subject) values ('fill_checklist', 'submission-1')"
                           " returning id").fetchone()[0]
        conn.execute("insert into work.part (task, key, label) values (%s, 'governance', 'Governance')", (tid,))
    return project


def hold_events(store, pid):
    return [e for e in entries(store, log_of(pid)) if e.action.startswith("hold.")]


def test_taking_and_releasing_a_part_are_recorded_with_who_did_it(task, call, memory_ledger):
    slug = task["slug"]
    assert call(OWNER, "POST", PART.format(slug=slug, action="take")).status_code == 200
    assert call(OWNER, "POST", PART.format(slug=slug, action="release")).status_code == 200
    relay_all(task["pid"])
    got = [(e.action, person(task["pid"], e.actor_ref)[0], e.item_id) for e in hold_events(memory_ledger, task["pid"])]
    assert got == [("hold.taken", OWNER, "fill_checklist/submission-1/governance"),
                   ("hold.released", OWNER, "fill_checklist/submission-1/governance")]


def test_a_take_over_is_recorded_with_its_reason(task, call, memory_ledger):
    slug = task["slug"]
    call(OWNER, "POST", PART.format(slug=slug, action="take"))
    over = call(OWNER, "POST", PART.format(slug=slug, action="take-over"),
                json={"reason": "Bob is away until Monday"})
    assert over.status_code == 200, over.text
    relay_all(task["pid"])
    taken_over = [e for e in hold_events(memory_ledger, task["pid"]) if e.action == "hold.taken_over"]
    assert len(taken_over) == 1
    from platform_service.ledger import secrets

    assert taken_over[0].content_sha256 == secrets.content_digest(task["pid"], {"reason": "Bob is away until Monday"})
    assert "reason" not in taken_over[0].details
