"""One person holds a part of a task at a time, and only the holder saves on it.

The check runs inside the app's own transaction, in the project's database, so it cannot be got around from
outside a page and a take-over cannot slip in between the check and the write.
"""
from __future__ import annotations

import psycopg
import pytest

from tests.conftest import needs_database, project_db

pytestmark = needs_database

ANNA = ("anna-subject", "Anna Rossi")
LUCA = ("luca-subject", "Luca Bianchi")


def a_task_with_a_part(dsn, project, kind="fill_checklist", subject="submission-1", part="governance"):
    with project_db(dsn, project) as conn:
        task = conn.execute("insert into work.task (kind, subject) values (%s, %s) returning id",
                            (kind, subject)).fetchone()[0]
        conn.execute("insert into work.part (task, key, label) values (%s, %s, 'Governance')", (task, part))
    return kind, subject, part


def take(dsn, project, who, kind="fill_checklist", subject="submission-1", part="governance"):
    from platform_service.work import holds

    with project_db(dsn, project) as conn:
        return holds.take(conn, kind=kind, subject=subject, part=part, person_subject=who[0], person_name=who[1])


def holder_of(dsn, project, part="governance"):
    with project_db(dsn, project) as conn:
        row = conn.execute("select holder_name from work.hold where part = %s", (part,)).fetchone()
    return row[0] if row else None


def require(conn, who, kind="fill_checklist", subject="submission-1", part="governance"):
    conn.execute("select work.require_holder(%s, %s, %s, %s)", (kind, subject, part, who[0]))


def test_the_holder_may_save(dsn, project):
    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    with project_db(dsn, project, role="controls_rw") as conn:
        require(conn, ANNA)


def test_someone_who_does_not_hold_the_part_is_refused_with_who_holds_it(dsn, project):
    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.Error) as refused:
            require(conn, LUCA)
    assert refused.value.sqlstate == "AH001", refused.value
    assert "Anna Rossi" in (refused.value.diag.message_detail or ""), refused.value.diag.message_detail


def test_a_part_nobody_holds_cannot_be_saved_on(dsn, project):
    a_task_with_a_part(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.Error) as refused:
            require(conn, ANNA)
    assert refused.value.sqlstate == "AH001", refused.value


def test_the_second_of_two_people_taking_the_same_part_is_refused(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    assert take(dsn, project, ANNA).holder == ANNA[1]
    with pytest.raises(holds.AlreadyHeld) as refused:
        take(dsn, project, LUCA)
    assert refused.value.holder_name == "Anna Rossi"


def test_an_app_cannot_write_the_holds_itself(dsn, project):
    a_task_with_a_part(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into work.hold (task, part, holder_subject, holder_name)"
                         " select id, 'governance', 'luca-subject', 'Luca' from work.task")


def test_the_holder_releases_a_part_and_someone_else_can_take_it(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        holds.release(conn, kind="fill_checklist", subject="submission-1", part="governance", person_subject=ANNA[0])
    assert holder_of(dsn, project) is None
    assert take(dsn, project, LUCA).holder == LUCA[1]


def test_only_the_holder_releases_a_part(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        with pytest.raises(holds.NotHolder):
            holds.release(conn, kind="fill_checklist", subject="submission-1", part="governance",
                          person_subject=LUCA[0])


def test_a_part_handed_over_is_held_by_the_other_person_once_they_accept(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    where = dict(kind="fill_checklist", subject="submission-1", part="governance")
    with project_db(dsn, project) as conn:
        holds.offer(conn, **where, person_subject=ANNA[0], to_subject=LUCA[0], to_name=LUCA[1])
    with project_db(dsn, project, role="controls_rw") as conn:
        require(conn, ANNA)                       # still Anna's until Luca accepts
    with project_db(dsn, project) as conn:
        holds.accept(conn, **where, person_subject=LUCA[0])
    assert holder_of(dsn, project) == LUCA[1]
    with project_db(dsn, project, role="controls_rw") as conn:
        require(conn, LUCA)
        with pytest.raises(psycopg.Error):
            require(conn, ANNA)


def test_a_declined_hand_over_leaves_the_part_with_its_holder(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    where = dict(kind="fill_checklist", subject="submission-1", part="governance")
    with project_db(dsn, project) as conn:
        holds.offer(conn, **where, person_subject=ANNA[0], to_subject=LUCA[0], to_name=LUCA[1])
        holds.decline(conn, **where, person_subject=LUCA[0])
        with pytest.raises(holds.NotOffered):
            holds.accept(conn, **where, person_subject=LUCA[0])
    with project_db(dsn, project, role="controls_rw") as conn:
        require(conn, ANNA)


def test_a_take_over_gives_the_part_to_the_new_person(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        before = holds.take_over(conn, kind="fill_checklist", subject="submission-1", part="governance",
                                 to_subject=LUCA[0], to_name=LUCA[1], by_subject="owner",
                                 by_name="Owner", reason="away")
    assert before.holder == ANNA[1]
    with project_db(dsn, project, role="controls_rw") as conn:
        require(conn, LUCA)


def test_a_take_over_waits_for_a_save_in_progress(dsn, project):
    from platform_service.work import holds

    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    saving = project_db(dsn, project, role="controls_rw")
    saving.autocommit = False
    try:
        require(saving, ANNA)                     # Anna's save is between its check and its commit
        with project_db(dsn, project) as conn:
            conn.execute("set lock_timeout = '300ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                holds.take_over(conn, kind="fill_checklist", subject="submission-1", part="governance",
                                to_subject=LUCA[0], to_name=LUCA[1], by_subject="owner",
                                by_name="Owner", reason="away")
    finally:
        saving.rollback()
        saving.close()


def test_a_task_in_check_cannot_be_saved_on_even_by_its_holder(dsn, project):
    a_task_with_a_part(dsn, project)
    take(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        conn.execute("update work.task set state = 'in_check'")
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.Error) as refused:
            require(conn, ANNA)
    assert refused.value.sqlstate == "AH002", refused.value
