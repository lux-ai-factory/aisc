"""Who did the work, and a done task opening again on the next save.

Holds say who holds a part now; a release deletes the row and a take-over overwrites it. So every save that
passes work.claim_for_save also records its person in work.doer, once per person, part and round. A save on
a done task starts its next round instead of being refused; a save on a task in check is still refused.
"""
from __future__ import annotations

import psycopg
import pytest

from tests.conftest import needs_database, project_db

pytestmark = needs_database

ANNA = ("anna-subject", "Anna Rossi")
LUCA = ("luca-subject", "Luca Bianchi")
GOVERNANCE = ("fill_checklist", "submission-1", "governance", "Governance")
DATA = ("fill_checklist", "submission-1", "data", "Data")


def holding_on(dsn, project):
    with project_db(dsn, project) as conn:
        conn.execute("insert into work.setting (name, enabled) values ('holds', true)"
                     " on conflict (name) do update set enabled = true")


def claim(dsn, project, who, where=GOVERNANCE):
    with project_db(dsn, project, role="controls_rw") as conn:
        conn.execute("select work.claim_for_save(%s, %s, %s, %s, %s, %s)", (*where, *who))


def doers(dsn, project):
    with project_db(dsn, project) as conn:
        return conn.execute("select d.round, d.part, d.person_subject, d.person_name from work.doer d"
                            " order by d.round, d.part, d.person_subject").fetchall()


def task_row(dsn, project):
    with project_db(dsn, project) as conn:
        return conn.execute("select state, round from work.task").fetchone()


def test_a_new_task_is_in_its_first_round(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    assert task_row(dsn, project) == ("open", 1)


def test_a_save_records_its_doer_once_per_part_and_round(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    claim(dsn, project, ANNA)
    claim(dsn, project, ANNA, DATA)
    assert doers(dsn, project) == [(1, "data", *ANNA), (1, "governance", *ANNA)]


def test_taking_a_part_without_saving_records_nobody(dsn, project):
    from platform_service.work import holds

    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        conn.execute("insert into work.part (task, key, label) select id, 'data', 'Data' from work.task")
        holds.take(conn, kind="fill_checklist", subject="submission-1", part="data", person_subject=LUCA[0],
                   person_name=LUCA[1])
    assert doers(dsn, project) == [(1, "governance", *ANNA)]


def test_a_refused_save_records_no_doer(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with pytest.raises(psycopg.Error):
        claim(dsn, project, LUCA)
    assert doers(dsn, project) == [(1, "governance", *ANNA)]


def test_the_former_holder_and_the_new_one_are_both_doers_after_a_take_over(dsn, project):
    from platform_service.work import holds

    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        holds.take_over(conn, kind="fill_checklist", subject="submission-1", part="governance",
                        to_subject=LUCA[0], to_name=LUCA[1])
    claim(dsn, project, LUCA)
    assert doers(dsn, project) == [(1, "governance", *ANNA), (1, "governance", *LUCA)]


def test_a_save_on_a_done_task_starts_its_next_round(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        conn.execute("update work.task set state = 'done'")
    claim(dsn, project, ANNA)
    assert task_row(dsn, project) == ("open", 2)
    assert doers(dsn, project) == [(1, "governance", *ANNA), (2, "governance", *ANNA)]


def test_a_save_by_someone_else_on_a_done_task_is_refused_and_starts_no_round(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        conn.execute("update work.task set state = 'done'")
    with pytest.raises(psycopg.Error) as refused:
        claim(dsn, project, LUCA)
    assert refused.value.sqlstate == "AH001", refused.value
    assert task_row(dsn, project) == ("done", 1)


def test_a_save_on_a_task_in_check_is_still_refused_and_records_nobody(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with project_db(dsn, project) as conn:
        conn.execute("update work.task set state = 'in_check'")
    with pytest.raises(psycopg.Error) as refused:
        claim(dsn, project, ANNA, DATA)
    assert refused.value.sqlstate == "AH002", refused.value
    assert task_row(dsn, project) == ("in_check", 1)
    assert doers(dsn, project) == [(1, "governance", *ANNA)]


def test_an_app_cannot_write_the_doers_itself(dsn, project):
    holding_on(dsn, project)
    claim(dsn, project, ANNA)
    with project_db(dsn, project, role="controls_rw") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into work.doer (task, round, part, person_subject, person_name)"
                         " values (gen_random_uuid(), 1, 'governance', 'luca-subject', 'Luca')")
