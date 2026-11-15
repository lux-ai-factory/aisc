"""A card version made for a card that was never saved is abandoned, not deleted.

Qualification asks the platform for a version before it writes the card. When the card write fails, it
withdraws the version by the attempt id it sent: the row stays in project.system (which refuses DELETE),
marked abandoned, and is never the latest again. A version a card or an evaluation names cannot be withdrawn.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"


def save(client, as_user, project, attempt=None, **body):
    body = {"name": "MCAS", "version": "v1", **body}
    if attempt is not None:
        body["attempt"] = attempt
    return client.post(f"/projects/{project['slug']}/system-versions", json=body, headers=as_user(ALICE))


def abandon(client, as_user, project, attempt, reason="card not saved"):
    return client.post(f"/projects/{project['slug']}/system-versions/abandon",
                       json={"attempt": attempt, "reason": reason}, headers=as_user(ALICE))


def in_project(dsn, project):
    return psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(project["pid"])))


def test_an_abandoned_version_is_kept_but_never_latest(client, as_user, project, dsn):
    attempt = str(uuid.uuid4())
    made = save(client, as_user, project, attempt=attempt)
    assert made.status_code == 201, made.text
    answer = abandon(client, as_user, project, attempt)
    assert answer.status_code == 200, f"withdrawing a version by its attempt answered {answer.status_code}"
    latest = client.get(f"/projects/{project['slug']}/system-versions/latest", headers=as_user(ALICE))
    assert latest.json() is None
    with in_project(dsn, project) as conn:
        [(kept,)] = conn.execute("select abandoned_at is not null from project.system where pid = %s",
                                 (made.json()["pid"],)).fetchall()
    assert kept


def test_the_list_leaves_an_abandoned_version_out(client, as_user, project):
    attempt = str(uuid.uuid4())
    save(client, as_user, project)
    save(client, as_user, project, attempt=attempt)
    assert abandon(client, as_user, project, attempt).status_code == 200
    listed = client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE)).json()
    assert [v["number"] for v in listed] == [1]


def test_an_unknown_attempt_is_404(client, as_user, project):
    save(client, as_user, project, attempt=str(uuid.uuid4()))
    answer = abandon(client, as_user, project, str(uuid.uuid4()))
    assert answer.status_code == 404, f"an attempt nobody made answered {answer.status_code}"


def test_a_version_that_is_not_the_latest_cannot_be_abandoned(client, as_user, project):
    attempt = str(uuid.uuid4())
    save(client, as_user, project, attempt=attempt)
    save(client, as_user, project)
    answer = abandon(client, as_user, project, attempt)
    assert answer.status_code == 409, f"withdrawing an older version answered {answer.status_code}"


def test_a_version_with_a_card_cannot_be_abandoned(client, as_user, project, dsn):
    attempt = str(uuid.uuid4())
    made = save(client, as_user, project, attempt=attempt).json()
    superuser = __import__("os").environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"])),
                         autocommit=True) as conn:
        # the smallest card table qualification's migrations make: a card names its version
        conn.execute("create table if not exists qualification.qualification"
                     " (id text primary key, system_id uuid references project.system(pid), revision int default 1)")
        # as qualification's owner-role migration grants it: the platform reads which version a card names
        conn.execute("grant select (system_id) on qualification.qualification to platform_rw")
        conn.execute("insert into qualification.qualification (id, system_id) values ('card-1', %s)",
                     (made["pid"],))
    answer = abandon(client, as_user, project, attempt)
    assert answer.status_code == 409, f"withdrawing a version a card names answered {answer.status_code}"


def test_a_viewer_cannot_abandon(client, as_user, project):
    attempt = str(uuid.uuid4())
    save(client, as_user, project, attempt=attempt)
    viewer = "00000000-0000-0000-0000-0000000000b0"
    client.post(f"/projects/{project['slug']}/members", json={"subject": viewer, "role": "viewer"},
                headers=as_user(ALICE))
    answer = client.post(f"/projects/{project['slug']}/system-versions/abandon",
                         json={"attempt": attempt, "reason": "x"}, headers=as_user(viewer))
    assert answer.status_code == 403, f"a viewer withdrawing a version answered {answer.status_code}"


def test_a_version_the_platform_cannot_check_is_kept(client, as_user, project):
    attempt = str(uuid.uuid4())
    save(client, as_user, project, attempt=attempt)
    superuser = __import__("os").environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"])),
                         autocommit=True) as conn:
        # a table of runs the platform was not granted to read: it cannot tell whether a run names the version
        conn.execute("create schema if not exists engine")
        conn.execute("create table if not exists engine.aisc_backend_evaluation (pid uuid primary key, system_id uuid)")
    answer = abandon(client, as_user, project, attempt)
    assert answer.status_code == 409, f"withdrawing a version nobody could check answered {answer.status_code}"
