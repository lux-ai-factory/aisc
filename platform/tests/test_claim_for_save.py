"""The first save takes the part, and only the holder saves: work.claim_for_save, called by every save on the
content of a part in the transaction that writes.

Holding is switched per project. While it is off the function neither takes nor refuses, so a project works as
before; while it is on, a save on a part nobody holds makes the person saving its holder (creating the task and
the part when they do not exist yet), and a save by anyone else is refused with who holds it and since when.
"""
from __future__ import annotations

import threading
import time

import psycopg
import pytest

from tests.conftest import needs_database, project_db

pytestmark = needs_database

ANNA = ("anna-subject", "Anna Rossi")
LUCA = ("luca-subject", "Luca Bianchi")
WHERE = ("fill_checklist", "submission-1", "governance", "Governance")


def holding_on(dsn, project):
    with project_db(dsn, project) as conn:
        conn.execute("insert into work.setting (name, enabled) values ('holds', true)"
                     " on conflict (name) do update set enabled = true")


def holding_off(dsn, project):
    """A project that has holding off (a new one starts with it on)."""
    with project_db(dsn, project) as conn:
        conn.execute("update work.setting set enabled = false where name = 'holds'")


def claim(conn, who, where=WHERE):
    conn.execute("select work.claim_for_save(%s, %s, %s, %s, %s, %s)", (*where, *who))


def holder_of(dsn, project, part="governance"):
    with project_db(dsn, project) as conn:
        row = conn.execute("select holder_name from work.hold where part = %s", (part,)).fetchone()
    return row[0] if row else None


def tasks(dsn, project):
    with project_db(dsn, project) as conn:
        return conn.execute("select t.kind, t.subject, p.key, p.label from work.task t"
                            " join work.part p on p.task = t.id order by p.key").fetchall()


def test_while_holding_is_off_a_save_neither_takes_nor_refuses(dsn, project):
    holding_off(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        claim(conn, ANNA)
        claim(conn, LUCA)
    assert tasks(dsn, project) == []
    assert holder_of(dsn, project) is None


def test_the_first_save_on_a_part_nobody_holds_takes_it_and_makes_the_task_and_the_part(dsn, project):
    holding_on(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        claim(conn, ANNA)
    assert tasks(dsn, project) == [("fill_checklist", "submission-1", "governance", "Governance")]
    assert holder_of(dsn, project) == "Anna Rossi"


def test_the_holder_saves_again(dsn, project):
    holding_on(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        claim(conn, ANNA)
        claim(conn, ANNA)
    assert holder_of(dsn, project) == "Anna Rossi"


def test_a_save_by_someone_else_is_refused_with_who_holds_the_part_and_since_when(dsn, project):
    holding_on(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        claim(conn, ANNA)
        with pytest.raises(psycopg.Error) as refused:
            claim(conn, LUCA)
    assert refused.value.sqlstate == "AH001", refused.value
    detail = refused.value.diag.message_detail or ""
    assert "Anna Rossi" in detail and '"since"' in detail, detail
    assert holder_of(dsn, project) == "Anna Rossi"


def test_a_save_on_a_task_in_check_is_refused_even_for_its_holder(dsn, project):
    holding_on(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        claim(conn, ANNA)
    with project_db(dsn, project) as conn:
        conn.execute("update work.task set state = 'in_check'")
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.Error) as refused:
            claim(conn, ANNA)
    assert refused.value.sqlstate == "AH002", refused.value


def test_two_people_saving_on_a_free_part_at_the_same_moment_end_with_one_holder_and_one_refusal(dsn, project):
    holding_on(dsn, project)
    first = project_db(dsn, project, role="controls_rw")
    first.autocommit = False
    outcome = {}

    def second_save():
        with project_db(dsn, project, role="controls_rw") as conn:
            try:
                claim(conn, LUCA)
                outcome["second"] = "saved"
            except psycopg.Error as error:
                outcome["second"] = error.sqlstate

    try:
        claim(first, ANNA)                       # Anna's save is between its claim and its commit
        other = threading.Thread(target=second_save)
        other.start()
        time.sleep(0.5)
        assert other.is_alive(), f"the second save did not wait for the first: {outcome}"
        first.commit()
        other.join(timeout=10)
    finally:
        first.rollback()
        first.close()
    assert outcome == {"second": "AH001"}
    assert holder_of(dsn, project) == "Anna Rossi"


def test_an_app_cannot_switch_holding_itself(dsn, project):
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into work.setting (name, enabled) values ('holds', true)")


@pytest.mark.parametrize("role", ["qualification_rw", "controls_rw", "control_objectives_rw"])
def test_an_app_reads_whether_holding_is_on(dsn, project, role):
    holding_off(dsn, project)
    with project_db(dsn, project, role=role) as conn:
        assert conn.execute("select work.holds_on()").fetchone()[0] is False
    holding_on(dsn, project)
    with project_db(dsn, project, role=role) as conn:
        assert conn.execute("select work.holds_on()").fetchone()[0] is True


def test_the_python_helper_answers_a_refusal_that_names_the_holder_and_writes_nothing(dsn, project):
    from aisc_identity import holds

    holding_on(dsn, project)
    with project_db(dsn, project, role="controls_rw") as conn:
        with conn.transaction():
            holds.claim_for_save(conn, *WHERE, *ANNA)
        with pytest.raises(holds.HoldRefused) as refused:
            with conn.transaction():
                holds.claim_for_save(conn, *WHERE, *LUCA)
                conn.execute("select 1")          # the save's write, never reached
    refusal = refused.value.refusal
    assert (refusal.code, refusal.what, refusal.current.changed_by) == ("not_holder", "Governance", "Anna Rossi")
    assert refusal.message.startswith("Anna Rossi holds Governance since "), refusal.message
