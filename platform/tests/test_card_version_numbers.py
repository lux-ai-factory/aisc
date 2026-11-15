"""A card version number is handed out once per project, ever.

Ledger events, reports and checklist answers cite "Version 2" by its number. If a version row goes (an
operator's hand removal), the next save must not be numbered 2 again: the number comes from a counter that
never goes down, not from the rows that exist now.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"


def save(client, as_user, project):
    made = client.post(f"/projects/{project['slug']}/system-versions", json={"name": "MCAS"},
                       headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()


def remove_by_hand(project, pid):
    """What an operator did on the live stack: delete the row as the superuser."""
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"])),
                         autocommit=True) as conn:
        conn.execute("SET session_replication_role = replica")     # past any guard, as a hand removal is
        conn.execute("delete from project.system where pid = %s", (pid,))


def test_a_removed_versions_number_is_not_handed_out_again(client, as_user, project):
    save(client, as_user, project)
    second = save(client, as_user, project)
    remove_by_hand(project, second["pid"])
    third = save(client, as_user, project)
    assert third["number"] == 3, f"the save after version 2 was removed got number {third['number']} again"


def test_removing_the_only_version_does_not_restart_at_one(client, as_user, project):
    first = save(client, as_user, project)
    remove_by_hand(project, first["pid"])
    again = save(client, as_user, project)
    assert again["number"] == 2, f"the save after version 1 was removed got number {again['number']}"
