"""Saved AI card versions of a project's one AI system, through the API.

WP2 of pipeline-2026-09-23 (03-specs.md): the versions 1, 2, ... of a project;
only the latest may change; old ones are read-only. Since the isolation
(2026-09-25, 01-specs.md I2.2) they are rows of project.system in the project's
own database, so the direct reads and writes below go there (S-D13: the rows
moved, the assertions are the same). A project whose database is gone has no
versions.
"""
import threading

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database

pytestmark = needs_database

ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-0000000000b0"
MALLORY = "00000000-0000-0000-0000-0000000000ma"


@pytest.fixture
def project(client, as_user, unique):
    response = client.post("/projects", json={"name": unique("ver")}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def viewer(client, as_user, project):
    response = client.post(f"/projects/{project['slug']}/members",
                           json={"subject": BOB, "role": "viewer"}, headers=as_user(ALICE))
    assert response.status_code in (200, 201), response.text
    return BOB


def save(client, as_user, project, who=ALICE, key="slug", **body):
    body = {"name": "MCAS", "version": "v1.2.0", **body}
    return client.post(f"/projects/{project[key]}/system-versions", json=body, headers=as_user(who))


def in_project(dsn, project, **kwargs):
    """The project's own database, where its versions are (project.system)."""
    return psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(project["pid"])), **kwargs)


def rows(dsn, project):
    with psycopg.connect(dsn) as conn:
        gone = conn.execute("select 1 from pg_database where datname = %s",
                            (projectdb.database_name(project["pid"]),)).fetchone() is None
    if gone:
        return []
    with in_project(dsn, project) as conn:
        return conn.execute("select pid, number, name, version from project.system order by number").fetchall()


# ── S2.1 ────────────────────────────────────────────────────────────────────


def test_s2_1_two_saves_make_versions_1_and_2_even_with_identical_name_and_version(client, as_user, project, dsn):
    first = save(client, as_user, project)
    second = save(client, as_user, project)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    a, b = first.json(), second.json()
    assert (a["number"], b["number"]) == (1, 2)
    assert a["project_id"] == b["project_id"] == project["pid"]
    assert (a["name"], a["version"]) == (b["name"], b["version"]) == ("MCAS", "v1.2.0")
    assert set(a) >= {"pid", "project_id", "number", "name", "version", "provider",
                      "description", "created_at", "created_by"}
    assert a["created_by"] == ALICE
    assert [r[1] for r in rows(dsn, project)] == [1, 2]


def test_s2_1_the_project_may_be_named_by_its_pid(client, as_user, project):
    response = save(client, as_user, project, key="pid")
    assert response.status_code == 201, response.text
    assert response.json()["number"] == 1


def test_s2_1_an_empty_name_is_422(client, as_user, project, dsn):
    assert save(client, as_user, project, name="   ").status_code == 422
    assert rows(dsn, project) == []


def test_s2_1_the_list_is_highest_number_first(client, as_user, project):
    for _ in range(3):
        save(client, as_user, project)
    response = client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE))
    assert response.status_code == 200, response.text
    assert [v["number"] for v in response.json()] == [3, 2, 1]


def test_s2_1_systems_pid_answers_with_number_and_created_by(client, as_user, project):
    made = save(client, as_user, project).json()
    response = client.get(f"/systems/{made['pid']}", headers=as_user(ALICE))
    assert response.status_code == 200, response.text
    assert response.json()["number"] == 1
    assert response.json()["created_by"] == ALICE


# ── S2.2 ────────────────────────────────────────────────────────────────────


def test_s2_2_a_viewer_may_read_but_not_save(client, as_user, project, viewer, dsn):
    assert save(client, as_user, project, who=viewer).status_code == 403
    assert rows(dsn, project) == []
    save(client, as_user, project)
    assert client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(viewer)).status_code == 200
    assert client.get(f"/projects/{project['slug']}/system-versions/latest", headers=as_user(viewer)).status_code == 200


def test_s2_2_a_stranger_gets_404_everywhere(client, as_user, project, dsn):
    made = save(client, as_user, project).json()
    assert save(client, as_user, project, who=MALLORY).status_code == 404
    for path in (f"/projects/{project['slug']}/system-versions",
                 f"/projects/{project['slug']}/system-versions/latest",
                 f"/systems/{made['pid']}"):
        assert client.get(path, headers=as_user(MALLORY)).status_code == 404, path
    assert len(rows(dsn, project)) == 1


def test_s2_2_an_unknown_project_is_404(client, as_user):
    admin = as_user("root", roles=("admin",))
    assert client.post("/projects/pytest-no-such-project/system-versions",
                       json={"name": "x"}, headers=admin).status_code == 404
    assert client.get("/projects/pytest-no-such-project/system-versions/latest", headers=admin).status_code == 404


# ── S2.3 ────────────────────────────────────────────────────────────────────


def test_s2_3_concurrent_saves_get_1_and_2_without_duplicate_or_gap(client, as_user, project, dsn):
    from platform_service.app import app

    results, barrier = [], threading.Barrier(2)

    def one():
        mine = TestClient(app)
        barrier.wait()
        results.append(mine.post(f"/projects/{project['slug']}/system-versions",
                                  json={"name": "MCAS"}, headers=as_user(ALICE)))

    threads = [threading.Thread(target=one) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(r.status_code for r in results) == [201, 201], [r.text for r in results]
    assert sorted(r.json()["number"] for r in results) == [1, 2]
    assert [r[1] for r in rows(dsn, project)] == [1, 2]


# ── S2.4 ────────────────────────────────────────────────────────────────────


def test_s2_4_version_1_cannot_change_once_2_exists_and_2_can(client, as_user, project, dsn):
    v1 = save(client, as_user, project).json()
    v2 = save(client, as_user, project).json()
    with in_project(dsn, project, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="is not the latest and cannot change"):
            conn.execute("update project.system set description = 'sneaky' where pid = %s", (v1["pid"],))
        conn.execute("update project.system set description = 'fine' where pid = %s", (v2["pid"],))


# ── S2.5 ────────────────────────────────────────────────────────────────────


def test_s2_5_deleting_the_project_deletes_its_versions(client, as_user, project, dsn):
    save(client, as_user, project)
    save(client, as_user, project)
    admin = as_user("root", roles=("admin",))
    response = client.request("DELETE", f"/projects/{project['slug']}",
                              json={"confirm_name": project["name"]}, headers=admin)
    assert response.status_code == 204, response.text
    assert rows(dsn, project) == []


# ── S2.9 and "POST /projects creates no system row" ─────────────────────────


def test_s2_9_latest_is_the_highest_number(client, as_user, project, dsn):
    for _ in range(3):
        save(client, as_user, project)
    response = client.get(f"/projects/{project['slug']}/system-versions/latest", headers=as_user(ALICE))
    assert response.status_code == 200, response.text
    with in_project(dsn, project) as conn:
        expected = conn.execute("select pid from project.system order by number desc limit 1").fetchone()[0]
    assert response.json()["pid"] == str(expected)
    assert response.json()["number"] == 3


def test_s2_9_a_new_project_has_no_version_and_latest_is_null(client, as_user, project, dsn):
    assert rows(dsn, project) == []
    response = client.get(f"/projects/{project['slug']}/system-versions/latest", headers=as_user(ALICE))
    assert response.status_code == 200, response.text
    assert response.json() is None


# ── removed routes ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("method, path", [
    ("POST", "/projects/{slug}/systems"),
    ("GET", "/projects/{slug}/systems"),
    ("GET", "/projects/{slug}/ai-system"),
    ("PATCH", "/projects/{slug}/ai-system"),
    ("POST", "/projects/{slug}/ai-system/draft"),
])
def test_wp2_the_old_system_routes_are_gone(client, as_user, project, method, path):
    response = client.request(method, path.format(slug=project["slug"]),
                              json={"name": "x"}, headers=as_user(ALICE))
    assert response.status_code in (404, 405), (method, path, response.status_code)


def test_wp2_the_old_version_routes_are_gone(client, as_user, project, dsn):
    made = save(client, as_user, project)
    if made.status_code == 201:
        pid = made.json()["pid"]
    else:  # before WP2: the draft 0002 made for the project, which the old routes do answer for
        with psycopg.connect(dsn) as conn:
            pid = str(conn.execute(
                "select v.pid from core.ai_system_version v join core.ai_system a on a.pid = v.ai_system_id"
                " where a.project_id = %s", (project["pid"],)).fetchone()[0])
    assert client.get(f"/ai-system-versions/{pid}", headers=as_user(ALICE)).status_code in (404, 405)
    assert client.post(f"/ai-system-versions/{pid}/freeze", json={"reason": "x"},
                       headers=as_user(ALICE)).status_code in (404, 405)
