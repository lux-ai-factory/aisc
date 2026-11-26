"""The two people of tests.two_sessions are two different members of one project, and both can write.

Every test of what happens between two people stands on this pair: were the two the same person, or one of
them unable to write, a lost update would never be reached and those tests would pass for nothing.
"""
from __future__ import annotations

from tests.conftest import needs_database, one
from tests.two_sessions import two_editors  # noqa: F401  (fixture)

pytestmark = needs_database


def test_the_two_are_different_members_and_both_editors(two_editors):
    project, a, b = two_editors.project, two_editors.a, two_editors.b
    members = {m["subject"]: m["role"] for m in a.get(f"/projects/{project['slug']}/members").json()}
    assert a.subject != b.subject and a.name != b.name
    assert (members.get(a.subject), members.get(b.subject)) == ("editor", "editor"), members


def test_each_of_the_two_writes_as_themself(two_editors, dsn):
    project, a, b = two_editors.project, two_editors.a, two_editors.b
    for person, release in ((a, "v1"), (b, "v2")):
        made = person.post(f"/projects/{project['slug']}/system-versions", json={"name": "MCAS", "version": release})
        assert made.status_code == 201, f"{person.name}'s write answered {made.status_code}: {made.text}"
    authors = one(dsn, project, "select array_agg(created_by order by number) from project.system")[0]
    assert authors == [a.subject, b.subject], f"the two writes are stored as made by {authors}"
