"""R1-R8: the relay (I2, I3, I6, I9, I11, T1-T4, T6, T8, T9, T24; spec 4.2-4.5). An event becomes a
trusted entry only if the request it cites was witnessed for the same project, through an app and route
its action may be caused by, for the same item and action id, within the window measured on the
databases' clocks; the actor is the witness's, never the app's.

These tests declare their own actions (registry.override), so they pin the relay's rules, not the
contents of the real registry."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import timedelta

import psycopg
import pytest

from platform_service.ledger import registry, verify
from platform_service.ledger import secrets
from platform_service.ledger.registry import Action
from tests.conftest import DSN
from tests.ledger.conftest import log_of, needs_db, MEMBER, OWNER, SUPERUSER_DSN, entries, need, person, relay_all
from tests.ledger.test_ledger_outbox import EMIT, as_superuser, connect, emit

pytestmark = needs_db

CLOSE = Action(name="controls.submission.closed", step=4, emitters=("controls",), item_type="submission",
               caused_by=(("controls", "POST", r"^/controls/p/[^/]+/submissions/(?P<item>[^/]+)/close$"),),
               routes=(), actor_kinds=("user",), details_keys=(), per_request=1)
SAVE = Action(name="controls.submission.draft_saved", step=4, emitters=("controls",), item_type="submission",
              caused_by=(("controls", "ACTION", r"^/controls/p/[^/]+/submissions/[^/]+$"),),
              routes=(), actor_kinds=("user",), details_keys=(), per_request=1)
RENAME = Action(name="controls.submission.renamed", step=4, emitters=("controls",), item_type="submission",
                caused_by=(("controls", "ACTION", r"^/controls/p/[^/]+/submissions/[^/]+$"),),
                routes=(), actor_kinds=("user",), details_keys=(), per_request=1)
QCREATED = Action(name="qualification.created", step=1, emitters=("qualification",), item_type="qualification",
                  caused_by=(("qualification", "ACTION", r"^/qualification/p/[^/]+/qualify/new$"),),
                  routes=(), actor_kinds=("user",), details_keys=(), per_request=1)
CARD = Action(name="card_version.created", step=1, emitters=("platform",), item_type="card_version",
              caused_by=(("qualification", "ACTION", r"^/qualification/p/[^/]+/qualify/new$"),),
              routes=(), actor_kinds=("user",), details_keys=(), per_request=1)


@pytest.fixture(autouse=True)
def _actions(mode):
    need(SUPERUSER_DSN, "PLATFORM_TEST_SUPERUSER_URL is not set")
    mode("enforce")
    # override MERGES over the real registry: the fixtures' own events (member.added, ...) stay known
    with registry.override({a.name: a for a in (CLOSE, SAVE, RENAME, QCREATED, CARD)}):
        yield


def close_uri(p, item="s1"):
    return f"/controls/p/{p['slug']}/submissions/{item}/close"


def ev(request_id, *, action="controls.submission.closed", item_id="s1", **over):
    e = {"event_id": str(uuid.uuid4()), "request_id": request_id, "action": action, "item_type": "submission",
         "item_id": item_id, "details": {}}
    e.update(over)
    return e


def as_platform(statement, params=()):
    with psycopg.connect(DSN) as conn:
        conn.execute(statement, params)


def shift_witness(request_id, delta: timedelta):
    """Test hook: move a witness record in time, as a clock or a backlog would."""
    as_platform("UPDATE ledger.witness SET at = at + %s WHERE request_id = %s", (delta, request_id))


def trusted(store, pid, action="controls.submission.closed"):
    return [e for e in entries(store, log_of(pid)) if e.action == action]


def rejected(store, pid):
    return [e for e in entries(store, log_of(pid)) if e.action == "ledger.rejected"]


@pytest.fixture
def closing(project, witnessed):
    return witnessed(MEMBER, "POST", "controls", close_uri(project), username="bob")


# R1: the actor comes from the witness ----------------------------------------------------------------

def test_an_event_citing_its_request_gets_the_witnesss_actor(project, memory_ledger, closing):
    content = {"answers": [{"q": 1, "a": "yes"}]}
    emit(project["pid"], "controls_rw", ev(closing, content=content))
    relay_all(project["pid"])
    mine = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.request_id == closing]
    assert sorted(x.action for x in mine) == ["controls.submission.closed", "request.witnessed"]  # only its own (M2)
    [e] = trusted(memory_ledger, project["pid"])
    assert (e.actor_kind, e.source_app, e.request_id, e.verified) == ("user", "controls", closing, True)
    assert e.content_sha256 == secrets.content_digest(project["pid"], content)      # the platform's (N4)
    assert person(project["pid"], e.actor_ref) == (MEMBER, "bob")
    [w] = [x for x in entries(memory_ledger, log_of(project["pid"])) if x.action == "request.witnessed"
           and x.request_id == closing]                              # the fixture's member-add is witnessed too
    assert w.request_id == closing and w.actor_ref == e.actor_ref


def test_an_app_naming_who_acted_is_rejected(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing, details={"actor_sub": OWNER}))
    relay_all(project["pid"])
    assert trusted(memory_ledger, project["pid"]) == []
    [r] = rejected(memory_ledger, project["pid"])
    assert r.details["reason"] == "actor_supplied"


def test_a_rejection_is_the_relays_never_the_cited_persons(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing, details={"actor_sub": OWNER}))
    relay_all(project["pid"])
    [r] = rejected(memory_ledger, project["pid"])
    assert (r.actor_kind, r.program, r.actor_ref, r.request_id) == ("system", "relay", None, closing)


# R2: the binding checks, in order -----------------------------------------------------------------

@pytest.mark.parametrize("case, reason", [
    ("no_request", "missing_request"),
    ("unknown_request", "unknown_request"),
    ("other_project", "project_mismatch"),
    ("other_emitter", "emitter"),
    ("route_not_allowed", "cause"),
    ("other_item", "item"),
    ("unknown_action", "unknown_action"),
    ("app_digest", "platform_field:content_sha256"),
])
def test_an_event_that_does_not_fit_its_request_is_rejected(make_project, project, witnessed, memory_ledger, closing,
                                                            case, reason):
    pid, role, request_id, over = project["pid"], "controls_rw", closing, {}
    if case == "no_request":
        request_id = None
    elif case == "unknown_request":
        request_id = str(uuid.uuid4())
    elif case == "other_project":
        other = make_project(MEMBER)
        request_id = witnessed(MEMBER, "POST", "controls", close_uri(other))
    elif case == "other_emitter":
        role = "qualification_rw"                                   # a controls action from qualification
    elif case == "route_not_allowed":
        request_id = witnessed(MEMBER, "POST", "controls", f"/controls/p/{project['slug']}/sources/new")
    elif case == "other_item":
        over["item_id"] = "s2"                                      # the request closed s1
    elif case == "unknown_action":
        over["action"] = "controls.submission.vanished"
    elif case == "app_digest":
        over.update(content={"answers": []}, content_sha256="0" * 64)        # only the platform digests (N4)
    emit(pid, role, ev(request_id, **over))
    relay_all(pid)
    assert trusted(memory_ledger, pid) == []
    assert [r.details["reason"] for r in rejected(memory_ledger, pid)] == [reason]


def test_a_request_may_not_cause_more_events_than_its_action_allows(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing))
    emit(project["pid"], "controls_rw", ev(closing))
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["per_request"]


# R3: the window uses the databases' clocks, never the relay's (R2.2) -----------------------------

def test_an_event_long_after_its_request_is_stale(project, memory_ledger, closing, settings):
    shift_witness(closing, -(settings.WINDOW + timedelta(minutes=1)))
    emit(project["pid"], "controls_rw", ev(closing))
    relay_all(project["pid"])
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["stale_request"]


def test_an_event_before_its_request_is_refused(project, memory_ledger, closing, settings):
    shift_witness(closing, settings.CLOCK_SKEW + timedelta(seconds=30))
    emit(project["pid"], "controls_rw", ev(closing))
    relay_all(project["pid"])
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["early_event"]


def test_a_relay_backlog_never_makes_an_event_stale(project, memory_ledger, closing, settings):
    event_id = emit(project["pid"], "controls_rw", ev(closing))
    backlog = settings.WINDOW * 12                                   # both happened long ago, 0 s apart
    shift_witness(closing, -backlog)
    as_superuser(project["pid"], "UPDATE ledger.outbox SET occurred_at = occurred_at - %s WHERE event_id = %s",
                 (backlog, event_id))
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


# R4: a request that travels on (spec 4.3) ------------------------------------------------------------

def test_a_platform_event_caused_by_a_qualification_request_is_accepted(project, memory_ledger, witnessed):
    request_id = witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/qualify/new",
                           next_action="60aa")
    emit(project["pid"], "platform_rw", ev(request_id, action="card_version.created", item_type="card_version",
                                          item_id="1"))
    relay_all(project["pid"])
    [e] = trusted(memory_ledger, project["pid"], "card_version.created")
    assert e.source_app == "platform" and person(project["pid"], e.actor_ref)[0] == MEMBER


def test_the_same_event_caused_by_another_apps_request_is_rejected(project, memory_ledger, witnessed):
    request_id = witnessed(MEMBER, "POST", "control_objectives",
                           f"/control-objectives/p/{project['pid']}/api/projects/a1/ratings")
    emit(project["pid"], "platform_rw", ev(request_id, action="card_version.created", item_type="card_version",
                                          item_id="1"))
    relay_all(project["pid"])
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["cause"]


# R5: server actions (spec 4.5, G6) -------------------------------------------------------------------

def test_one_action_id_binds_to_one_event_action(project, memory_ledger, witnessed):
    page = f"/controls/p/{project['slug']}/submissions/s1"
    first = witnessed(MEMBER, "POST", "controls", page, next_action="40ab")
    emit(project["pid"], "controls_rw", ev(first, action="controls.submission.draft_saved"))
    relay_all(project["pid"])
    again = witnessed(MEMBER, "POST", "controls", page, next_action="40ab")
    emit(project["pid"], "controls_rw", ev(again, action="controls.submission.draft_saved"))
    other = witnessed(MEMBER, "POST", "controls", page, next_action="40ab")
    emit(project["pid"], "controls_rw", ev(other, action="controls.submission.renamed"))
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"], "controls.submission.draft_saved")) == 2
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["action_id"]
    assert verify.verify(project["pid"]).action_id_conflicts == 1


def test_an_action_id_binds_to_every_action_of_its_first_request(project, memory_ledger, witnessed):
    """A server action that saves and renames in one call: both are its actions from then on (N3)."""
    page = f"/controls/p/{project['slug']}/submissions/s1"
    first = witnessed(MEMBER, "POST", "controls", page, next_action="40cd")
    emit(project["pid"], "controls_rw", ev(first, action="controls.submission.draft_saved"))
    emit(project["pid"], "controls_rw", ev(first, action="controls.submission.renamed"))
    relay_all(project["pid"])
    later = witnessed(MEMBER, "POST", "controls", page, next_action="40cd")
    emit(project["pid"], "controls_rw", ev(later, action="controls.submission.renamed"))   # a subset is fine
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"], "controls.submission.draft_saved")) == 1
    assert len(trusted(memory_ledger, project["pid"], "controls.submission.renamed")) == 2
    assert rejected(memory_ledger, project["pid"]) == []


def test_another_apps_event_on_the_same_request_is_not_bound(project, memory_ledger, witnessed):
    """A step-1 submit: qualification records its own event and the platform the card version, both
    citing one request with one action id. Only the serving app's events bind the id (N3)."""
    submit = witnessed(MEMBER, "POST", "qualification", f"/qualification/p/{project['slug']}/qualify/new",
                       next_action="60ee")
    emit(project["pid"], "qualification_rw", ev(submit, action="qualification.created", item_type="qualification",
                                                item_id="q1"))
    emit(project["pid"], "platform_rw", ev(submit, action="card_version.created", item_type="card_version",
                                           item_id="1"))
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"], "qualification.created")) == 1
    assert len(trusted(memory_ledger, project["pid"], "card_version.created")) == 1
    assert rejected(memory_ledger, project["pid"]) == []


def test_a_server_action_event_needs_an_action_id(project, memory_ledger, witnessed):
    plain = witnessed(MEMBER, "POST", "controls", f"/controls/p/{project['slug']}/submissions/s1")
    emit(project["pid"], "controls_rw", ev(plain, action="controls.submission.draft_saved"))
    relay_all(project["pid"])
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["action_id"]


# R6: exactly once (I3, T8, T9) -----------------------------------------------------------------------

def test_running_the_relay_again_adds_nothing(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing))
    relay_all(project["pid"])
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


def test_a_crash_between_writing_and_marking_loses_and_duplicates_nothing(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing))
    memory_ledger.crash_after_appends = 2                            # test hook: dies after the 2nd append
    with pytest.raises(RuntimeError):
        relay_all(project["pid"])
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


def test_the_same_event_id_with_other_content_is_an_alarm_not_a_silent_drop(project, memory_ledger, closing,
                                                                            witnessed):
    e = ev(closing)
    emit(project["pid"], "controls_rw", e)
    relay_all(project["pid"])
    later = witnessed(MEMBER, "POST", "controls", close_uri(project, "s9"))
    as_superuser(project["pid"], "DELETE FROM ledger.delivered")     # as after a restore of the project DB
    as_superuser(project["pid"], "UPDATE ledger.outbox SET item_id = 's9', request_id = %s WHERE event_id = %s",
                 (later, e["event_id"]))
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1
    assert [r.details["reason"] for r in rejected(memory_ledger, project["pid"])] == ["duplicate_event_id"]


def test_a_late_commit_is_not_skipped(project, memory_ledger, witnessed):
    """Rows commit out of order: no high-water mark may skip the one that committed last (R4.7)."""
    a = witnessed(MEMBER, "POST", "controls", close_uri(project, "sa"))
    b = witnessed(MEMBER, "POST", "controls", close_uri(project, "sb"))
    with connect(project["pid"]) as slow:
        slow.execute('SET SESSION AUTHORIZATION "controls_rw"')
        slow.execute(EMIT, (json.dumps(ev(a, item_id="sa")),))      # first, still open
        emit(project["pid"], "controls_rw", ev(b, item_id="sb"))    # second, committed
        relay_all(project["pid"])
        slow.commit()
    relay_all(project["pid"])
    assert {e.item_id for e in trusted(memory_ledger, project["pid"])} == {"sa", "sb"}


# R7: availability and concurrency (I6, T24) ----------------------------------------------------------

def test_while_immudb_is_down_events_wait_and_none_is_rejected(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing))
    memory_ledger.down = True
    stats = relay_all(project["pid"])
    assert (stats.delivered, stats.rejected) == (0, 0) and stats.pending >= 1
    memory_ledger.down = False
    relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 1


def test_two_relays_at_once_still_honour_per_request(project, memory_ledger, closing):
    for _ in range(4):
        emit(project["pid"], "controls_rw", ev(closing))
    errors = []

    def run():
        try:
            relay_all(project["pid"])
        except Exception as exc:                                     # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    relay_all(project["pid"])
    assert not errors
    assert len(trusted(memory_ledger, project["pid"])) == 1
    assert len(rejected(memory_ledger, project["pid"])) == 3
    seqs = [e.seq for e in entries(memory_ledger, log_of(project["pid"]))]
    assert seqs == sorted(set(seqs))


# R8: modes, registry versions, item chain (R2.12, R2.14, I11) ---------------------------------------

def test_in_record_mode_an_unverified_request_gives_an_unverified_event(project, memory_ledger, call_witness, mode):
    mode("record")
    r = call_witness("not-a-token", "POST", "controls", close_uri(project))
    emit(project["pid"], "controls_rw", ev(r.headers["X-AISC-Request-Id"]))
    relay_all(project["pid"])
    [e] = trusted(memory_ledger, project["pid"])
    assert (e.verified, e.actor_ref) == (False, None)


def test_an_action_from_a_newer_registry_is_held_not_rejected(project, memory_ledger, closing):
    emit(project["pid"], "controls_rw", ev(closing, action="controls.submission.archived",
                                           registry_version=registry.VERSION + 1))
    stats = relay_all(project["pid"])
    assert stats.held == 1 and rejected(memory_ledger, project["pid"]) == []


def test_a_broken_item_chain_is_reported(project, memory_ledger, witnessed):
    first = witnessed(MEMBER, "POST", "controls", close_uri(project))
    emit(project["pid"], "controls_rw", ev(first, before={"state": "open"}, after={"state": "closed"}))
    second = witnessed(OWNER, "POST", "controls", close_uri(project))
    emit(project["pid"], "controls_rw", ev(second, before={"state": "draft"}, after={"state": "closed"}))
    many = Action(name=CLOSE.name, step=4, emitters=CLOSE.emitters, item_type="submission",
                  caused_by=CLOSE.caused_by, routes=(), actor_kinds=("user",), details_keys=(), per_request=None)
    with registry.override({CLOSE.name: many}):
        relay_all(project["pid"])
    assert len(trusted(memory_ledger, project["pid"])) == 2         # recorded, not rejected
    assert verify.verify(project["pid"]).chain_breaks == 1


def test_a_witnessed_write_with_no_event_is_reported(project, memory_ledger, closing, settings):
    shift_witness(closing, -(settings.WINDOW + timedelta(minutes=1)))
    relay_all(project["pid"])
    assert verify.verify(project["pid"]).witness_without_event == 1


def test_the_platforms_digest_ignores_key_order(project, memory_ledger, witnessed):
    """The platform digests canonical JSON (RFC 8785), so the app's key order changes nothing."""
    a = witnessed(MEMBER, "POST", "controls", close_uri(project, "sa"))
    b = witnessed(MEMBER, "POST", "controls", close_uri(project, "sb"))
    emit(project["pid"], "controls_rw", ev(a, item_id="sa", content={"b": 1, "a": [1, 2]}))
    emit(project["pid"], "controls_rw", ev(b, item_id="sb", content={"a": [1, 2], "b": 1}))
    relay_all(project["pid"])
    assert len({e.content_sha256 for e in trusted(memory_ledger, project["pid"])}) == 1
