"""PR1-PR4: minimisation (I10, D9; spec 7.5, R2.5). immudb holds a pseudonymous actor reference, never
a subject or a name. The mapping lives in Postgres, can be checked against the reference with the
ledger key, and can be erased; the entries stay, pseudonymous. Content digests are keyed, so a short
answer can't be found by trying "yes" and "no"."""
from __future__ import annotations

import hashlib

import pytest

from platform_service.ledger import actors, secrets
from platform_service.ledger.canonical import canonical
from platform_service.ledger.naming import database_name
from tests.conftest import needs_database
from tests.ledger.conftest import LEDGER_KEY, MEMBER, entries, person, relay_all
from tests.ledger.test_ledger_outbox import emit

pytestmark = needs_database


@pytest.fixture
def one_event(project, witnessed, memory_ledger, mode):
    mode("enforce")
    request_id = witnessed(MEMBER, "POST", "control_objectives",
                           f"/control-objectives/p/{project['pid']}/api/projects/a1/ratings", username="bob")
    emit(project["pid"], "control_objectives_rw",
         {"event_id": "00000000-0000-4000-8000-000000000001", "request_id": request_id, "action": "risk.rated",
          "item_type": "risk", "item_id": "r1", "content": {"answer": "yes"},
          "content_sha256": secrets.content_digest(project["pid"], {"answer": "yes"}, LEDGER_KEY)})
    relay_all(project["pid"])
    return [e for e in entries(memory_ledger, database_name(project["pid"])) if e.action == "risk.rated"][0]


def test_immudb_never_holds_the_subject_or_the_name(project, memory_ledger, one_event):
    for e in entries(memory_ledger, database_name(project["pid"])):
        raw = canonical(e.as_dict())
        assert MEMBER.encode() not in raw and b"bob" not in raw


def test_the_reference_is_a_keyed_hash_of_the_subject_per_project(project, one_event):
    assert one_event.actor_ref == secrets.actor_ref(project["pid"], MEMBER, LEDGER_KEY)
    assert one_event.actor_ref != secrets.actor_ref("5d3f5f2a-ac34-414b-ae8d-3df80dfe8df3", MEMBER, LEDGER_KEY)


def test_a_swapped_mapping_row_is_detected(project, one_event):
    actors.tamper(project["pid"], one_event.actor_ref, sub="00000000-0000-0000-0000-0000000000ff")  # test hook
    with pytest.raises(actors.MappingAlarm):
        person(project["pid"], one_event.actor_ref)


def test_erasing_a_person_keeps_their_entries_pseudonymous(project, memory_ledger, one_event):
    actors.erase(project["pid"], MEMBER)
    assert person(project["pid"], one_event.actor_ref) is None
    still = [e for e in entries(memory_ledger, database_name(project["pid"])) if e.action == "risk.rated"]
    assert [e.actor_ref for e in still] == [one_event.actor_ref]


def test_content_digests_are_keyed(project, one_event):
    plain = hashlib.sha256(canonical({"answer": "yes"})).hexdigest()
    assert one_event.content_sha256 != plain
