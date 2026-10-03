"""R9-R16: the relay's answers to the phase 3 review (16-phase3-review.md). A bad row is a rejection,
never a stall; one project never stops another; the action binding learns from accepted events only;
run events inherit their start's verified; newer-registry rows are held for HOLD_UNKNOWN only; the
crash and lock guards are pinned."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from platform_service.ledger import outbox, registry, relay
from tests.conftest import DSN
from tests.ledger.conftest import MEMBER, OWNER, entries, log_of, needs_db, relay_all
from tests.ledger.test_ledger_outbox import as_superuser, emit
from tests.ledger.test_ledger_relay import (_actions, close_uri, closing, ev, rejected, shift_witness,  # noqa: F401
                                            trusted)

pytestmark = needs_db


def reasons(store, pid):
    return [r.details["reason"] for r in rejected(store, pid)]


# B1: a bad row is a rejection; one project never stops another ---------------------------------------

@pytest.mark.parametrize("field", ["content", "before", "details"])
def test_a_value_canonical_json_refuses_is_rejected_and_the_log_goes_on(project, memory_ledger, closing, witnessed,
                                                                        field):
    """An integer beyond 2**53 is valid jsonb (a nanosecond timestamp is one)."""
    big = {"n": 12345678901234567890}
    bad = ev(closing, **({"details": big} if field == "details" else {field: big}))
    emit(project["pid"], "controls_rw", bad)
    later = witnessed(MEMBER, "POST", "controls", close_uri(project, "s2"))
    emit(project["pid"], "controls_rw", ev(later, item_id="s2"))
    relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) in (["unencodable"], ["details_key:n"])
    assert [e.item_id for e in trusted(memory_ledger, project["pid"])] == ["s2"]


def test_one_projects_failure_never_stops_another_or_the_platform_log(project, make_project, memory_ledger,
                                                                      witnessed, monkeypatch):
    from platform_service.ledger.naming import PLATFORM_DB

    other = make_project(MEMBER)
    request_id = witnessed(MEMBER, "POST", "controls", close_uri(other))
    emit(other["pid"], "controls_rw", ev(request_id))
    real = relay._relay_log

    def broken(pid, stats):
        if pid == project["pid"]:
            raise RuntimeError("a bug in one project's relay")
        return real(pid, stats)
    monkeypatch.setattr(relay, "_relay_log", broken)
    with psycopg.connect(DSN) as conn:
        conn.execute("INSERT INTO core.outbox (event_id, emitter, action, item_type, item_id)"
                     " VALUES (%s, 'platform', 'project.created', 'project', 'x')", (str(uuid.uuid4()),))
    stats = relay.relay_once()
    assert len(trusted(memory_ledger, other["pid"])) == 1
    assert any(e.action in ("project.created", "ledger.rejected") for e in entries(memory_ledger, PLATFORM_DB))
    assert stats.pending >= 1


def test_a_witness_entry_rebuilt_after_a_registry_upgrade_is_not_a_poison(project, memory_ledger, closing,
                                                                           monkeypatch):
    """A crash after the witness append and before `delivered_seq`, then a deploy raising VERSION: the
    rebuilt entry differs from the stored one. The stored one is the record (review B1)."""
    relay_all(project["pid"])
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE ledger.witness SET delivered_seq = NULL WHERE request_id = %s", (closing,))
        conn.execute("DELETE FROM ledger.event_index WHERE event_id = %s", (f"witness:{closing}",))
    monkeypatch.setattr(registry, "VERSION", registry.VERSION + 1)
    relay_all(project["pid"])
    mine = [e for e in entries(memory_ledger, log_of(project["pid"])) if e.event_id == f"witness:{closing}"]
    assert len(mine) == 1
    with psycopg.connect(DSN) as conn:
        assert conn.execute("SELECT delivered_seq FROM ledger.witness WHERE request_id = %s",
                            (closing,)).fetchone()[0] == mine[0].seq


# M2: the binding learns from accepted events only ------------------------------------------------------

def test_a_rejected_event_teaches_the_action_id_nothing(project, memory_ledger, witnessed, settings):
    page = f"/controls/p/{project['slug']}/submissions/s1"
    first = witnessed(MEMBER, "POST", "controls", page, next_action="77aa")
    emit(project["pid"], "controls_rw", ev(first, action="controls.submission.draft_saved"))
    relay_all(project["pid"])
    shift_witness(first, -(settings.WINDOW + timedelta(minutes=1)))   # the next event is stale
    emit(project["pid"], "controls_rw", ev(first, action="controls.submission.renamed"))
    relay_all(project["pid"])
    someone = witnessed(OWNER, "POST", "controls", page, next_action="77aa")       # another member
    emit(project["pid"], "controls_rw", ev(someone, action="controls.submission.renamed"))
    relay_all(project["pid"])
    assert trusted(memory_ledger, project["pid"], "controls.submission.renamed") == []
    assert reasons(memory_ledger, project["pid"]) == ["stale_request", "action_id"]


# M3, m4: runs ---------------------------------------------------------------------------------------

def _start_run(project, request_id):
    run_id = str(uuid.uuid4())
    emit(project["pid"], "control_objectives_rw", {"event_id": str(uuid.uuid4()), "request_id": request_id,
                                                    "run_id": run_id, "action": "ai.mapping.requested",
                                                    "item_type": "assessment", "item_id": "a1", "details": {}})
    return run_id


def _run_event(project, request_id, run_id, **over):
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "run_id": run_id, "action": "ai.mapping.failed",
         "item_type": "assessment", "item_id": "a1", "details": {"error": "timeout"}}
    e.update(over)
    emit(project["pid"], "control_objectives_rw", e)


def _map_uri(project):
    return f"/control-objectives/p/{project['pid']}/api/projects/a1/map"


def test_a_run_of_an_unverified_request_is_unverified(project, memory_ledger, call_witness, mode):
    mode("record")
    r = call_witness("not-a-token", "POST", "control_objectives", _map_uri(project))
    request_id = r.headers["X-AISC-Request-Id"]
    run_id = _start_run(project, request_id)
    relay_all(project["pid"])
    _run_event(project, request_id, run_id)
    relay_all(project["pid"])
    [failed] = trusted(memory_ledger, project["pid"], "ai.mapping.failed")
    assert failed.verified is False


def test_a_run_event_before_its_start_is_rejected(project, memory_ledger, witnessed, settings):
    request_id = witnessed(MEMBER, "POST", "control_objectives", _map_uri(project))
    run_id = _start_run(project, request_id)
    relay_all(project["pid"])
    _run_event(project, request_id, run_id)
    as_superuser(project["pid"], "UPDATE ledger.outbox SET occurred_at = occurred_at - %s WHERE action = %s",
                 (timedelta(minutes=10), "ai.mapping.failed"))
    relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) == ["run"]


def test_a_non_start_event_cannot_shadow_the_runs_start(project, memory_ledger, witnessed):
    """The start is the first accepted event of the run whose action starts runs."""
    request_id = witnessed(MEMBER, "POST", "control_objectives", _map_uri(project))
    run_id = str(uuid.uuid4())
    shadow = registry.Action(name="controls.shadow.saved", step=2, emitters=("control_objectives",),
                             item_type="assessment", caused_by=(("control_objectives", "POST", r"^/control-objectives/.*/map$"),),
                             details_keys=(), per_request=None)
    with registry.override({"controls.shadow.saved": shadow}):
        emit(project["pid"], "control_objectives_rw", {"event_id": str(uuid.uuid4()), "request_id": request_id,
                                                        "run_id": run_id, "action": "controls.shadow.saved",
                                                        "item_type": "assessment", "item_id": "a1", "details": {}})
        relay_all(project["pid"])
        emit(project["pid"], "control_objectives_rw", {"event_id": str(uuid.uuid4()), "request_id": request_id,
                                                        "run_id": run_id, "action": "ai.mapping.requested",
                                                        "item_type": "assessment", "item_id": "a1", "details": {}})
        relay_all(project["pid"])
        _run_event(project, request_id, run_id)
        relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"], "ai.mapping.failed")) == 1


# M4: newer-registry rows are held for HOLD_UNKNOWN only -----------------------------------------------

def test_a_held_row_is_rejected_after_hold_unknown(project, memory_ledger, closing, settings):
    emit(project["pid"], "controls_rw", ev(closing, action="controls.submission.archived",
                                           registry_version=registry.VERSION + 1))
    as_superuser(project["pid"], "UPDATE ledger.outbox SET occurred_at = occurred_at - %s",
                 (settings.HOLD_UNKNOWN + timedelta(hours=1),))
    relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) == ["unknown_action"]


def test_a_version_far_ahead_is_not_held(project, memory_ledger, closing):
    """An emitter's own number can't hold a row for ever: one version ahead at most."""
    emit(project["pid"], "controls_rw", ev(closing, action="controls.submission.archived",
                                           registry_version=registry.VERSION + 50))
    stats = relay_all(project["pid"])
    assert stats.held == 0 and reasons(memory_ledger, project["pid"]) == ["unknown_action"]


# M7, m1, m5: the crash and lock guards -----------------------------------------------------------------

def test_a_crash_between_indexing_and_marking_neither_rejects_nor_duplicates(project, memory_ledger, closing,
                                                                             monkeypatch):
    calls = {"n": 0}

    def crash_once(*_a):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("died after the index, before the mark (test)")
    monkeypatch.setattr(relay, "_after_index", crash_once)
    e = ev(closing)
    emit(project["pid"], "controls_rw", e)
    with pytest.raises(RuntimeError):
        relay_all(project["pid"])
    monkeypatch.setattr(relay, "_after_index", lambda *_a: None)
    relay_all(project["pid"])
    [accepted] = trusted(memory_ledger, project["pid"])
    assert rejected(memory_ledger, project["pid"]) == []
    assert as_superuser(project["pid"], "SELECT seq, reason FROM ledger.delivered WHERE event_id = %s",
                        (e["event_id"],)) == [(accepted.seq, None)]


def test_a_log_another_relay_holds_is_skipped_not_waited_on(project, memory_ledger, closing):
    """m1: a try-lock. A busy log is left for the next pass; nothing blocks on it."""
    emit(project["pid"], "controls_rw", ev(closing))
    log = log_of(project["pid"])
    with psycopg.connect(DSN) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext(%s))", ("ledger-relay:" + log,))
        stats = relay_all(project["pid"])
        assert trusted(memory_ledger, project["pid"]) == [] and stats.pending >= 1
        holder.execute("SELECT pg_advisory_unlock(hashtext(%s))", ("ledger-relay:" + log,))
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


def test_an_event_the_store_already_holds_is_indexed_not_judged_again(project, memory_ledger, closing, monkeypatch):
    """m5: after a crash between the append and the index, a key rotation would change the digest and the
    verdict; the store's own copy is the record."""
    from tests.ledger.conftest import LEDGER_KEYS

    e = ev(closing, content={"a": 1})
    emit(project["pid"], "controls_rw", e)
    real_append = memory_ledger.append

    def die_after_the_event(db, entry):
        seq = real_append(db, entry)
        if entry["event_id"] == e["event_id"]:
            raise RuntimeError("died after the append, before the index (test)")
        return seq
    monkeypatch.setattr(memory_ledger, "append", die_after_the_event)
    with pytest.raises(RuntimeError):
        relay_all(project["pid"])
    monkeypatch.setattr(memory_ledger, "append", real_append)
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", LEDGER_KEYS + ",v2:" + "b2" * 32)
    relay_all(project["pid"])
    [accepted] = trusted(memory_ledger, project["pid"])
    assert rejected(memory_ledger, project["pid"]) == [] and accepted.content_sha256.startswith("hmac:v1:")


# m6: before and after are scanned for secrets too ----------------------------------------------------

@pytest.mark.parametrize("field", ["before", "after"])
def test_a_secret_in_a_state_is_rejected(project, memory_ledger, closing, field):
    emit(project["pid"], "controls_rw", ev(closing, **{field: {"token": "Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig"}}))
    relay_all(project["pid"])
    assert reasons(memory_ledger, project["pid"]) == [f"secret_in:{field}"]


# m3: a key rotation is not a chain break ----------------------------------------------------------------

def test_a_key_rotation_between_two_events_is_not_a_chain_break(project, memory_ledger, witnessed, monkeypatch):
    from platform_service.ledger import verify
    from platform_service.ledger.registry import Action
    from tests.ledger.conftest import LEDGER_KEYS, OWNER
    from tests.ledger.test_ledger_relay import CLOSE

    many = Action(name=CLOSE.name, step=4, emitters=CLOSE.emitters, item_type="submission",
                  caused_by=CLOSE.caused_by, routes=(), actor_kinds=("user",), details_keys=(), per_request=None)
    with registry.override({CLOSE.name: many}):
        first = witnessed(MEMBER, "POST", "controls", close_uri(project))
        emit(project["pid"], "controls_rw", ev(first, before={"state": "open"}, after={"state": "closed"}))
        relay_all(project["pid"])
        monkeypatch.setenv("PLATFORM_LEDGER_KEYS", LEDGER_KEYS + ",v2:" + "b2" * 32)
        second = witnessed(OWNER, "POST", "controls", close_uri(project))
        emit(project["pid"], "controls_rw", ev(second, before={"state": "closed"}, after={"state": "reopened"}))
        relay_all(project["pid"])
        third = witnessed(OWNER, "POST", "controls", close_uri(project))
        emit(project["pid"], "controls_rw", ev(third, before={"state": "draft"}, after={"state": "closed"}))
        relay_all(project["pid"])
    assert verify.verify(project["pid"]).chain_breaks == 1          # only the real one (third), not the rotation


# M1 (second half): the relay reads in batches, in time order ---------------------------------------------

def test_a_backlog_is_relayed_in_batches_in_time_order(project, memory_ledger, witnessed, settings, monkeypatch):
    monkeypatch.setattr(settings, "RELAY_BATCH", 3)
    ids = []
    for n in range(5):
        request_id = witnessed(MEMBER, "POST", "controls", close_uri(project, f"s{n}"))
        emit(project["pid"], "controls_rw", ev(request_id, item_id=f"s{n}"))
        ids.append(request_id)
    first = relay_all(project["pid"])
    assert 0 < first.delivered <= 2 * 3                              # one batch per source at most
    for _ in range(6):
        relay_all(project["pid"])
    assert [e.item_id for e in trusted(memory_ledger, project["pid"])] == [f"s{n}" for n in range(5)]
    assert rejected(memory_ledger, project["pid"]) == []             # each event after its own witness
