"""R1-R3: the relay (I2, I3, I9, T1-T4, T6, T8, T9). An outbox row becomes a ledger entry only if
the request it cites was witnessed for the same project, through the same app, on a path its action
allows, recently enough; the actor is the witness's, never the app's."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import pytest

from platform_service.ledger import relay
from platform_service.ledger.canonical import canonical, sha256_hex
from platform_service.ledger.naming import database_name
from tests.conftest import needs_database
from tests.ledger.conftest import MEMBER, SUPERUSER_DSN, entries
from tests.ledger.test_ledger_outbox import as_role

pytestmark = [needs_database, pytest.mark.skipif(not SUPERUSER_DSN, reason="PLATFORM_TEST_SUPERUSER_URL is not set")]


def submission_path(pid):
    return f"/controls/p/{pid}/submissions/s1"


def add(pid, role, request_id, *, action="controls.submission.closed", item_id="s1", details=None,
        content=None, content_sha256=None, event_id=None):
    event_id = event_id or str(uuid.uuid4())
    as_role(pid, role,
            "INSERT INTO ledger.outbox (event_id, request_id, action, item_type, item_id, details, content,"
            " content_sha256) VALUES (%s, %s, %s, 'submission', %s, %s, %s, %s)",
            (event_id, request_id, action, item_id, json.dumps(details or {}),
             json.dumps(content) if content is not None else None, content_sha256))
    return event_id


def trusted(store, pid, action="controls.submission.closed"):
    return [e for e in entries(store, database_name(pid)) if e.action == action]


def rejected(store, pid):
    return [e for e in entries(store, database_name(pid)) if e.action == "ledger.rejected"]


@pytest.fixture
def closing(project, witnessed, memory_ledger, mode):
    """A witnessed request that closes a submission in the controls app."""
    mode("enforce")
    return witnessed(MEMBER, "POST", submission_path(project["pid"]), username="bob")


def test_a_row_citing_its_request_becomes_an_entry_with_the_witnesss_actor(project, memory_ledger, closing):
    content = {"answers": [{"q": 1, "a": "yes"}]}
    add(project["pid"], "controls_rw", closing, content=content, content_sha256=sha256_hex(content))
    stats = relay.relay_once(project["pid"])
    assert stats.delivered == 1 and stats.rejected == 0
    [e] = trusted(memory_ledger, project["pid"])
    assert (e.actor_kind, e.actor_sub, e.actor_name, e.source_app) == ("user", MEMBER, "bob", "controls")
    assert e.request_id == closing and e.content_sha256 == sha256_hex(content)


def test_an_app_naming_who_acted_is_rejected(project, memory_ledger, closing):
    add(project["pid"], "controls_rw", closing, details={"actor_sub": "00000000-0000-0000-0000-00000000dead"})
    relay.relay_once(project["pid"])
    assert trusted(memory_ledger, project["pid"]) == []
    [r] = rejected(memory_ledger, project["pid"])
    assert r.details["reason"] == "actor_supplied"


@pytest.mark.parametrize("case, reason", [
    ("no_request", "missing_request"),
    ("unknown_request", "unknown_request"),
    ("other_app", "app_mismatch"),
    ("path_not_allowed", "path_not_allowed"),
    ("unknown_action", "unknown_action"),
    ("bad_hash", "content_hash"),
])
def test_a_row_that_does_not_fit_its_request_is_rejected(project, witnessed, memory_ledger, closing, case, reason):
    pid = project["pid"]
    role, request_id, kwargs = "controls_rw", closing, {}
    if case == "no_request":
        request_id = None
    elif case == "unknown_request":
        request_id = str(uuid.uuid4())
    elif case == "other_app":
        role = "qualification_rw"                                   # a controls request cited by qualification
    elif case == "path_not_allowed":
        request_id = witnessed(MEMBER, "POST", f"/controls/p/{pid}/sources/new")
    elif case == "unknown_action":
        kwargs["action"] = "controls.submission.vanished"
    elif case == "bad_hash":
        kwargs.update(content={"answers": []}, content_sha256="0" * 64)
    add(pid, role, request_id, **kwargs)
    relay.relay_once(pid)
    assert trusted(memory_ledger, pid) == []
    [r] = rejected(memory_ledger, pid)
    assert r.details["reason"] == reason


def test_an_old_request_is_rejected(project, memory_ledger, closing):
    from datetime import datetime, timezone

    add(project["pid"], "controls_rw", closing)
    relay.relay_once(project["pid"], now=datetime.now(timezone.utc) + timedelta(minutes=6))
    [r] = rejected(memory_ledger, project["pid"])
    assert r.details["reason"] == "stale_request"


def test_a_request_may_not_cause_more_events_than_its_action_allows(project, memory_ledger, closing):
    add(project["pid"], "controls_rw", closing)
    add(project["pid"], "controls_rw", closing)                     # closing twice on one request
    relay.relay_once(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["per_request"]


def test_a_request_witnessed_in_another_project_is_rejected(client, as_user, unique, project, witnessed,
                                                             memory_ledger, mode):
    mode("enforce")
    other = client.post("/projects", json={"name": unique("other")}, headers=as_user(MEMBER)).json()
    request_id = witnessed(MEMBER, "POST", submission_path(other["pid"]))
    add(project["pid"], "controls_rw", request_id)
    relay.relay_once(project["pid"])
    [r] = rejected(memory_ledger, project["pid"])
    assert r.details["reason"] == "project_mismatch"


def test_running_the_relay_again_adds_nothing(project, memory_ledger, closing):
    add(project["pid"], "controls_rw", closing)
    relay.relay_once(project["pid"])
    relay.relay_once(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


def test_a_crash_between_writing_and_marking_loses_and_duplicates_nothing(project, memory_ledger, closing,
                                                                          monkeypatch):
    add(project["pid"], "controls_rw", closing)
    real = relay._mark_delivered
    calls = {"n": 0}

    def crash_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the relay died here")
        return real(*args, **kwargs)

    monkeypatch.setattr(relay, "_mark_delivered", crash_once)
    with pytest.raises(RuntimeError):
        relay.relay_once(project["pid"])
    relay.relay_once(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


def test_the_hash_check_uses_canonical_json(project, memory_ledger, closing):
    content = {"b": 1, "a": [1, 2]}
    add(project["pid"], "controls_rw", closing, content=content,
        content_sha256=hashlib.sha256(canonical({"a": [1, 2], "b": 1})).hexdigest())
    relay.relay_once(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1
