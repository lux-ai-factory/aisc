"""One lock guards the card state of a project.

The card state (card version, revision) moves when a card is stored. The writer that stores a card takes the
lock exclusive; every writer that reads "the latest card" to stamp a record takes it shared, in its own
transaction, before it reads. The key is the one the platform's version counter already takes,
hashtext('project.system'), in the project's database. Two real connections and a held transaction: a wait is
seen as a lock timeout.
"""
from __future__ import annotations

import psycopg
import pytest

from aisc_identity import card_lock
from tests.conftest import needs_database, project_db

pytestmark = needs_database


@pytest.fixture
def two_connections(dsn, project):
    """Two connections to one project's database, each opened outside a transaction."""
    with project_db(dsn, project, autocommit=True) as first, project_db(dsn, project, autocommit=True) as second:
        yield first, second


def waits(conn, take) -> bool:
    """Whether `take(conn)`, in a transaction of its own on `conn`, has to wait for a lock."""
    try:
        with conn.transaction():
            conn.execute("set local lock_timeout = '300ms'")
            take(conn)
    except psycopg.errors.LockNotAvailable:
        return True
    return False


def test_a_stamping_writer_waits_while_a_card_is_being_stored(two_connections):
    storing, stamping = two_connections
    with storing.transaction():
        card_lock.exclusive(storing)
        assert waits(stamping, card_lock.shared), "the latest card was read while a card was being stored"


def test_a_stamping_writer_goes_on_once_the_card_is_stored(two_connections):
    storing, stamping = two_connections
    with storing.transaction():
        card_lock.exclusive(storing)
    # the storing transaction ended: a transaction lock needs no release
    assert not waits(stamping, card_lock.shared), "the lock outlived the transaction that stored the card"


def test_two_stamping_writers_do_not_wait_for_each_other(two_connections):
    one_writer, another = two_connections
    with one_writer.transaction():
        card_lock.shared(one_writer)
        assert not waits(another, card_lock.shared), "two writers that only read the latest card blocked each other"


def test_a_card_is_not_stored_while_a_stamping_writer_holds_the_lock(two_connections):
    stamping, storing = two_connections
    with stamping.transaction():
        card_lock.shared(stamping)
        assert waits(storing, card_lock.exclusive), "a card was stored between a writer's read and its commit"


def test_the_lock_is_the_one_the_version_counter_takes(two_connections):
    counter, stamping = two_connections
    with counter.transaction():
        counter.execute("select pg_advisory_xact_lock(hashtext('project.system'))")
        assert waits(stamping, card_lock.shared), "the helper locks another key than hashtext('project.system')"


@pytest.mark.parametrize("take", ["exclusive", "shared"])
def test_the_helper_refuses_to_run_outside_a_transaction(two_connections, take):
    conn, _ = two_connections
    # in autocommit a transaction lock is released at once and guards nothing
    with pytest.raises(Exception):  # the kind of error is not specified
        getattr(card_lock, take)(conn)
