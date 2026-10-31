"""A project's database: its name and its address, against the shared cases.

projectdb-cases.json is also run by shared/access-ts (projectDb.mjs), so the Python and JavaScript
rules cannot differ without one of the two failing.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from aisc_identity import projectdb

CASES = json.loads((Path(__file__).parent.parent / "projectdb-cases.json").read_text())


@pytest.mark.parametrize("case", CASES["names"], ids=lambda c: repr(c["pid"]))
def test_a_pid_names_its_database(case):
    if case.get("refused"):
        with pytest.raises(projectdb.NotAPid):
            projectdb.database_name(case["pid"])
    else:
        assert projectdb.database_name(case["pid"]) == case["name"]


def test_a_uuid_names_the_same_database_as_its_text():
    pid = uuid.UUID(CASES["names"][0]["pid"])
    assert projectdb.database_name(pid) == CASES["names"][0]["name"]


@pytest.mark.parametrize("value", [None, 7, b"11111111-1111-4111-8111-111111111111"])
def test_what_is_not_text_is_refused(value):
    with pytest.raises(projectdb.NotAPid):
        projectdb.database_name(value)


@pytest.mark.parametrize("case", CASES["pids"], ids=lambda c: c["name"])
def test_a_database_name_gives_back_its_pid(case):
    assert projectdb.pid_of(case["name"]) == case["pid"]


@pytest.mark.parametrize("case", CASES["dsns"], ids=lambda c: c["name"])
def test_a_template_gives_the_databases_address(case):
    if case.get("refused"):
        with pytest.raises(ValueError):
            projectdb.dsn(case["template"], case["database"], driver=case.get("driver"))
    else:
        assert projectdb.dsn(case["template"], case["database"], driver=case.get("driver")) == case["dsn"]


def test_the_maintenance_address_is_the_postgres_database():
    template = "postgresql://reader:secret@postgres/{database}?sslmode=require"
    assert projectdb.maintenance_dsn(template) == "postgresql://reader:secret@postgres/postgres?sslmode=require"
