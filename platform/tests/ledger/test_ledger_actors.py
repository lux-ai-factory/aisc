"""The person mapping on its own. The privacy suite checks the same rules through events; these
call `actors` directly."""
from __future__ import annotations

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


def test_the_mapping_reuses_its_connections(platform_dsn):
    """The witness asks for a reference on every request without a fresh database login each time."""
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
    """A failed first use closes its pool, and the next call does not wait 30 s."""
    import time

    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql://platform_rw:x@127.0.0.1:1/platform")
    before = len(actors._pools)
    for _ in range(2):
        started = time.monotonic()
        with pytest.raises(Exception):
            actors.ref_for(P1, person(), "bob")
        assert time.monotonic() - started < 10
    assert len(actors._pools) == before
