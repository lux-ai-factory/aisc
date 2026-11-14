"""A body nested deeper than the JSON parser can follow is, at every door of the connection facade, a body
that is not JSON: refused in the door's own words, never a 500, never sent to the system under test and
never counted on the run key."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database, one
from tests.test_connection_facades import DOORS, _env, base, connection, issue, keyed, stub  # noqa: F401

pytestmark = needs_database
DEEP = b"[" * 200_000 + b"]" * 200_000


@pytest.mark.parametrize("door", list(DOORS))
def test_a_deeply_nested_body_is_not_json_and_does_not_count(client, admin, project, stub, dsn, door):  # noqa: F811
    name = connection(client, admin, project, stub)
    key = issue(client, project, name).json()["key"]
    try:
        r = client.post(f"{base(project, name)}{DOORS[door](name)}", content=DEEP,
                        headers={**keyed(key), "Content-Type": "application/json"})
    except RecursionError:
        pytest.fail("the door let a RecursionError out: the person gets a 500")
    assert r.status_code < 500, r.text[:300]
    assert stub.requests("POST", "/chat") == []
    assert one(dsn, project, "select uses from connection.run_key")[0] == 0
