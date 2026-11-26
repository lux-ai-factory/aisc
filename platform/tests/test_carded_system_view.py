"""Two views of "the versions of this project".

project.saved_system lists every version that was not withdrawn, including one whose card is not stored yet
(the platform numbers the version first, qualification stores the card after). project.carded_system holds
the rows of saved_system that have at least one stored card: the versions a person can open. It has the same
columns.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import ALICE, needs_database, project_db

pytestmark = needs_database


def new_version(client, as_user, project) -> str:
    """A card version as the platform numbers it, before qualification stores its card: its pid."""
    made = client.post(f"/projects/{project['slug']}/system-versions", json={"name": "MCAS", "version": "v1"},
                       headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()["pid"]


def store_a_card(project, version: str) -> None:
    """A card of `version` in qualification's card table, as qualification's save leaves it."""
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"])),
                         autocommit=True) as conn:
        # the columns of qualification's card table that say which version and revision a card is and the
        # system's identity it describes, and what qualification's migrations let the platform read of it
        conn.execute("create table if not exists qualification.qualification"
                     " (id text primary key, system_id uuid not null, revision int not null default 1,"
                     ' "systemName" text not null, "systemVersion" text not null, company text not null,'
                     " description text not null)")
        conn.execute("grant select (system_id, revision) on qualification.qualification to platform_rw")
        conn.execute('grant select ("systemName", "systemVersion", company, description)'
                     " on qualification.qualification to platform_rw")
        conn.execute("insert into qualification.qualification"
                     ' (id, system_id, revision, "systemName", "systemVersion", company, description)'
                     " values ('card-r1', %s, 1, 'MCAS', 'v1', 'Eindhoven Engine', 'first')", (version,))


def versions_in(dsn, project, view: str) -> list[str]:
    """The pids `view` lists in the project's database."""
    with project_db(dsn, project) as conn:
        assert conn.execute("select to_regclass(%s)", (view,)).fetchone()[0] is not None, (
            f"the project's database has no {view}")
        return [str(row[0]) for row in conn.execute(f"select pid from {view} order by number").fetchall()]


def columns_of(dsn, project, view: str) -> list[tuple[str, str]]:
    schema, name = view.split(".")
    with project_db(dsn, project) as conn:
        found = conn.execute("select column_name, data_type from information_schema.columns"
                             " where table_schema = %s and table_name = %s order by ordinal_position",
                             (schema, name)).fetchall()
    assert found, f"the project's database has no {view}"
    return found


def test_a_version_with_a_stored_card_is_in_carded_system(client, as_user, project, dsn):
    version = new_version(client, as_user, project)
    store_a_card(project, version)
    assert versions_in(dsn, project, "project.carded_system") == [version]


def test_a_version_with_no_card_is_left_out_of_carded_system(client, as_user, project, dsn):
    carded = new_version(client, as_user, project)
    store_a_card(project, carded)
    new_version(client, as_user, project)          # numbered by the platform, its card not stored yet
    assert versions_in(dsn, project, "project.carded_system") == [carded]


def test_saved_system_still_has_a_version_with_no_card(client, as_user, project, dsn):
    version = new_version(client, as_user, project)
    assert versions_in(dsn, project, "project.saved_system") == [version]


def test_carded_system_has_the_columns_of_saved_system(project, dsn):
    assert columns_of(dsn, project, "project.carded_system") == columns_of(dsn, project, "project.saved_system")
