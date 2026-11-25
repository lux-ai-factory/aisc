"""Where conversation states are kept: in memory, or in the assistant's own database (never a project database)."""
import os

import pytest

from chart_assistant.conversation_store import DatabaseStore, MemoryStore

PID = "0b5446b0-3bcf-4747-9a47-996747111b86"


def check(store):
    assert store.load("c1", 60) is None
    store.save("c1", PID, {"metrics": []}, {"asked": 1})
    store.save("c1", PID, {"metrics": []}, {"asked": 2})
    assert store.load("c1", 60) == (PID, {"metrics": []}, {"asked": 2})
    assert store.load("c1", 0) is None                                # idle longer than allowed
    store.drop_idle(0)
    assert store.load("c1", 60) is None


def test_states_kept_in_memory():
    check(MemoryStore())


def test_a_state_kept_in_memory_is_dropped_only_once_it_is_idle_too_long():
    now = [100.0]
    store = MemoryStore(clock=lambda: now[0])
    store.save("c1", PID, {}, {"asked": 1})
    now[0] += 30
    store.drop_idle(60)
    assert store.load("c1", 60) == (PID, {}, {"asked": 1})
    now[0] += 31
    assert store.load("c1", 60) is None


@pytest.mark.db
@pytest.mark.skipif(not os.environ.get("ASSISTANT_TEST_DATABASE_URL"), reason="needs a postgres the assistant's role may use")
def test_states_kept_in_the_assistants_own_database():
    check(DatabaseStore(os.environ["ASSISTANT_TEST_DATABASE_URL"]))
