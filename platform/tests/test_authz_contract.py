"""GET /authz/projects/{ref} answers with the shared truth table.

The TypeScript apps decide nothing themselves: they ask this endpoint. It runs
the same admit() the Python services call, so it is held to the same
access-cases.json as aisc_identity's own tests.
"""
import json
from pathlib import Path

import psycopg
import pytest

from tests.conftest import needs_database

pytestmark = needs_database

CASES = json.loads((Path(__file__).resolve().parents[2] / "shared/identity/access-cases.json").read_text())


@pytest.fixture
def truth_table_projects(dsn):
    pids = [p["pid"] for p in CASES["projects"]]
    with psycopg.connect(dsn) as conn:
        for project in CASES["projects"]:
            conn.execute("INSERT INTO core.project (pid, name, slug) VALUES (%s, %s, %s)",
                         (project["pid"], project["slug"], project["slug"]))
        for member in CASES["members"]:
            conn.execute("INSERT INTO core.project_member (project_id, subject, role) VALUES (%s, %s, %s)",
                         (member["project"], member["subject"], member["role"]))
    yield
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM core.project WHERE pid = ANY(%s::uuid[])", (pids,))


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda case: case["name"])
def test_truth_table(client, as_user, truth_table_projects, case):
    ref = case["ref"].upper() if case.get("upper") else case["ref"]
    roles = ("admin",) if case["admin"] else ("primary-user",)
    response = client.get(f"/authz/projects/{ref}", params={"want": case["want"]},
                          headers=as_user(case["subject"], roles))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == case["status"], body
    if case["status"] == 200:
        assert (body["verdict"], body["role"], body["may_write"]) == ("allow", case["role"], case["may_write"])
        if "pid" in case:
            assert body["pid"] == case["pid"]
    else:
        assert body["pid"] is None and body["slug"] is None


def test_without_want_it_answers_for_a_read(client, as_user, truth_table_projects):
    body = client.get("/authz/projects/alpha", headers=as_user("viewer-1")).json()
    assert (body["verdict"], body["status"], body["role"]) == ("allow", 200, "viewer")


def test_an_unknown_want_is_a_client_error(client, as_user, truth_table_projects):
    assert client.get("/authz/projects/alpha", params={"want": "own"},
                      headers=as_user("owner-1")).status_code == 422
