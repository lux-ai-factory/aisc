"""admit() against a real Postgres, driven by the shared truth table.

The same access-cases.json is run by the platform's /authz tests and by the
TypeScript client's tests, so the three cannot disagree without one of them
failing.
"""
import json
from pathlib import Path

import psycopg
import pytest

from aisc_identity.access import Admitted, Refused, admit
from aisc_identity.caller import Caller

CASES = json.loads((Path(__file__).parent.parent / "access-cases.json").read_text())


def caller(subject, admin=False):
    roles = ("admin",) if admin else ("primary-user",)
    return Caller(subject=subject, email=None, username=subject, roles=roles)


@pytest.fixture(scope="module")
def membership_db(scratch_database_url):
    with psycopg.connect(scratch_database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS core CASCADE")
        conn.execute("CREATE SCHEMA core")
        conn.execute("CREATE TABLE core.project (pid uuid PRIMARY KEY, slug text UNIQUE NOT NULL,"
                     " name text NOT NULL DEFAULT '')")
        conn.execute("CREATE TABLE core.project_member (project_id uuid REFERENCES core.project,"
                     " subject text NOT NULL, role text NOT NULL, PRIMARY KEY (project_id, subject))")
        for project in CASES["projects"]:
            conn.execute("INSERT INTO core.project (pid, slug) VALUES (%s, %s)",
                         (project["pid"], project["slug"]))
        for member in CASES["members"]:
            conn.execute("INSERT INTO core.project_member VALUES (%s, %s, %s)",
                         (member["project"], member["subject"], member["role"]))
    return scratch_database_url


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda case: case["name"])
def test_truth_table(membership_db, case):
    ref = case["ref"].upper() if case.get("upper") else case["ref"]

    def connect():
        return psycopg.connect(membership_db)

    if case["status"] == 200:
        admitted = admit(ref, caller(case["subject"], case["admin"]), case["want"], connect=connect)
        assert admitted.role == case["role"]
        assert admitted.may_write is case["may_write"]
        assert admitted.admin is case["admin"]
        if "pid" in case:
            assert admitted.pid == case["pid"]
    else:
        with pytest.raises(Refused) as refused:
            admit(ref, caller(case["subject"], case["admin"]), case["want"], connect=connect)
        assert refused.value.status == case["status"]


def test_admitted_carries_the_resolved_pid_and_slug(membership_db):
    admitted = admit("alpha", caller("viewer-1"), "GET", connect=lambda: psycopg.connect(membership_db))
    assert admitted == Admitted(pid="11111111-1111-4111-8111-111111111111", slug="alpha",
                                role="viewer", admin=False, may_write=False)


def test_a_database_that_cannot_answer_refuses_with_503():
    def broken():
        raise psycopg.OperationalError("connection refused")

    with pytest.raises(Refused) as refused:
        admit("alpha", caller("owner-1"), "GET", connect=broken)
    assert refused.value.status == 503
    assert refused.value.code == "unavailable"


def test_refusals_say_the_same_thing_everywhere(membership_db):
    def connect():
        return psycopg.connect(membership_db)

    with pytest.raises(Refused) as stranger:
        admit("alpha", caller("nobody"), "GET", connect=connect)
    with pytest.raises(Refused) as reader:
        admit("alpha", caller("viewer-1"), "POST", connect=connect)
    assert (stranger.value.code, stranger.value.message) == ("not-found", "No such project.")
    assert (reader.value.code, reader.value.message) == (
        "forbidden", "You can read this project but not change it.")


def test_want_outside_methods_and_manage_is_a_programming_error(membership_db):
    with pytest.raises(ValueError):
        admit("alpha", caller("owner-1"), "own", connect=lambda: psycopg.connect(membership_db))


def test_an_owner_only_refusal_names_the_owner(membership_db):
    with pytest.raises(Refused) as editor:
        admit("alpha", caller("editor-1"), "manage", connect=lambda: psycopg.connect(membership_db))
    assert (editor.value.status, editor.value.message) == (403, "Only an owner can do this.")


def test_a_pooled_connection_with_dict_rows_is_returned_not_closed(membership_db):
    from contextlib import contextmanager

    from psycopg.rows import dict_row

    returned = []

    @contextmanager
    def from_pool():
        conn = psycopg.connect(membership_db, row_factory=dict_row)
        yield conn
        returned.append(conn.closed)
        conn.close()

    admitted = admit("alpha", caller("owner-1"), "manage", connect=from_pool)
    assert admitted.role == "owner"
    assert returned == [False]


def test_the_ladder():
    from aisc_identity.access import at_least

    assert at_least("owner", "editor") and at_least("editor", "viewer") and at_least("viewer", "viewer")
    assert not at_least("viewer", "editor") and not at_least("editor", "owner")
    assert not at_least(None, "viewer")
    assert not at_least("superuser", "viewer")
