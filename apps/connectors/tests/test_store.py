"""Store-level tests for the race-safety and column-safety the admin API tests don't reach directly."""
import uuid

import pytest


@pytest.fixture
def ids():
    return uuid.uuid4(), uuid.uuid4()  # project_pid, ai_system_pid


def test_create_connector_finds_an_existing_target_access_without_a_unique_violation(db, ids):
    """Forces the path make_target_access-races were added for: a target-access row already exists
    (inserted directly, bypassing the store, the way a concurrent create would leave one) when
    create_connector runs. Its own computed is_target_access must come out false, and it must not
    raise, i.e. it must not go through the retry-on-collision branch to get there."""
    from aisc_connectors import store

    project_pid, ai_system_pid = ids
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind, environment,"
            " is_target_access, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s)",
            (uuid.uuid4(), project_pid, ai_system_pid, "Existing", "existing", "manual", "sandbox", "seed"),
        )

    row = store.create_connector(project_pid, ai_system_pid, "New", "new", "manual", "sandbox", "alice")

    assert row["is_target_access"] is False


def test_create_connector_rejects_a_duplicate_slug(db, ids):
    from aisc_connectors import store

    project_pid, ai_system_pid = ids
    store.create_connector(project_pid, ai_system_pid, "N", "same", "manual", "sandbox", "alice")
    with pytest.raises(store.DuplicateName):
        store.create_connector(project_pid, ai_system_pid, "N2", "same", "manual", "sandbox", "alice")


def test_update_rejects_unknown_columns(db, ids):
    from aisc_connectors import store

    project_pid, ai_system_pid = ids
    row = store.create_connector(project_pid, ai_system_pid, "N", "n", "manual", "sandbox", "alice")
    with pytest.raises(ValueError):
        store.update(row["pid"], created_by="mallory")


def test_update_rejects_a_duplicate_slug(db, ids):
    from aisc_connectors import store

    project_pid, ai_system_pid = ids
    store.create_connector(project_pid, ai_system_pid, "N", "taken", "manual", "sandbox", "alice")
    other = store.create_connector(project_pid, ai_system_pid, "N2", "free", "manual", "sandbox", "alice")
    with pytest.raises(store.DuplicateName):
        store.update(other["pid"], slug="taken")
