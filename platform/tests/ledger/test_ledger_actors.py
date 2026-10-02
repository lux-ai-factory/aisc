"""AC1-AC6, phase 2: the person mapping on its own (spec 6.1 `actors`, 7.5; I10, S8; phase 2 review
m12). The privacy suite checks the same rules through events (phase 3); these call `actors` directly."""
from __future__ import annotations

import threading
import uuid

import pytest

from platform_service.ledger import actors
from tests.ledger.conftest import needs_db

pytestmark = needs_db
P1, P2 = str(uuid.uuid4()), str(uuid.uuid4())


def person():
    return str(uuid.uuid4())


def test_a_reference_is_random_stable_and_per_scope(platform_dsn):
    sub = person()
    ref = actors.ref_for(P1, sub, "bob")
    assert ref.startswith("actor:") and len(ref) == 38 and sub not in ref
    assert actors.ref_for(P1, sub, "bob") == ref
    assert actors.ref_for(P2, sub, "bob") != ref and actors.ref_for(None, sub, "bob") != ref
    assert actors.resolve(P1, ref) == (sub, "bob")
    assert actors.resolve(P2, ref) is None                       # a reference answers in its own scope only


def test_a_new_name_is_kept_current_and_still_checks(platform_dsn):
    sub = person()
    ref = actors.ref_for(P1, sub, "bob")
    assert actors.ref_for(P1, sub, "robert") == ref
    assert actors.resolve(P1, ref) == (sub, "robert")


@pytest.mark.parametrize("edit", [{"sub": "00000000-0000-0000-0000-0000000000ff"}, {"name": "mallory"}])
def test_an_edited_row_is_an_alarm(platform_dsn, edit):
    ref = actors.ref_for(P1, person(), "bob")
    actors.tamper(P1, ref, **edit)
    with pytest.raises(actors.MappingAlarm):
        actors.resolve(P1, ref)


def test_erasure_cuts_the_link_for_good(platform_dsn):
    sub = person()
    ref = actors.ref_for(P1, sub, "bob")
    assert actors.erase(P1, sub) == 1
    assert actors.resolve(P1, ref) is None
    assert actors.ref_for(P1, sub, "bob") != ref


def test_first_sightings_at_once_make_one_reference(platform_dsn):
    sub, refs, errors = person(), [], []

    def run():
        try:
            refs.append(actors.ref_for(P1, sub, "bob"))
        except Exception as exc:                                    # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(refs)) == 1


def test_the_mapping_reuses_its_connections(platform_dsn):
    """Phase 2 review m3: the witness asks for a reference on every request; no fresh login each time."""
    import psycopg

    from tests.conftest import DSN

    def sessions():                                       # every session ever opened on the database (PG14+)
        with psycopg.connect(DSN) as conn:
            conn.execute("SELECT pg_stat_clear_snapshot()")
            return conn.execute("SELECT sessions FROM pg_stat_database WHERE datname = 'ledger_identity'").fetchone()[0]
    actors.ref_for(P1, person(), "warm-up")
    before = sessions()
    for _ in range(20):
        actors.ref_for(P1, person(), "bob")
    import time
    time.sleep(0.6)                                       # the statistics collector reports with a delay
    assert sessions() - before <= 4, "a new session per call: the mapping has no pool"


def test_an_unreachable_mapping_fails_fast_and_leaks_nothing(platform_dsn, monkeypatch):
    """Phase 2 re-review n1: a failed first use closes its pool, and the next call doesn't wait 30 s."""
    import time

    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql://platform_rw:x@127.0.0.1:1/platform")
    before = len(actors._pools)
    for _ in range(2):
        started = time.monotonic()
        with pytest.raises(Exception):
            actors.ref_for(P1, person(), "bob")
        assert time.monotonic() - started < 10
    assert len(actors._pools) == before
