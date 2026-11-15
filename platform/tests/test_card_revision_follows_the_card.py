"""The platform's card revision count never runs ahead of the cards qualification holds.

A correction is two writes: qualification's new card row (qualification.qualification, revision r+1) and
the platform's count (project.system.card_revision). Both live in the project's database. When the platform
counted the correction but qualification's transaction then failed (a timeout, a mismatch, a failed commit),
there is no card at r+1. The version must still read revision r, so the next correction from r is taken
and a report never pins a revision with no card behind it.
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


#: the version as its first card describes it
FIRST = {"name": "MCAS", "version": "v1", "provider": "Eindhoven Engine", "description": "first"}


def correction(**over):
    return {"name": "MCAS 2", "version": "v1.1", "provider": "Eindhoven Engine B.V.", "description": "corrected",
            "reason": "provider name", "requested_by": "the provider", "expected_card_revision": 1, **over}


@pytest.fixture
def version_with_its_first_card(client, as_user, project):
    """Version 1 and its card at revision 1, as qualification's save leaves them."""
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set")
    made = client.post(f"/projects/{project['slug']}/system-versions", json=FIRST, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"])),
                         autocommit=True) as conn:
        # the columns of qualification's card table that say which version and revision a card is
        # and the system's identity it describes (as qualification's Prisma schema names the columns)
        conn.execute("create table if not exists qualification.qualification"
                     " (id text primary key, system_id uuid not null, revision int not null default 1,"
                     ' "systemName" text not null, "systemVersion" text not null, company text not null,'
                     " description text not null)")
        # what qualification's migrations let the platform read of it
        conn.execute("grant select (system_id, revision) on qualification.qualification to platform_rw")
        conn.execute('grant select ("systemName", "systemVersion", company, description)'
                     " on qualification.qualification to platform_rw")
        conn.execute("insert into qualification.qualification"
                     ' (id, system_id, revision, "systemName", "systemVersion", company, description)'
                     " values ('card-r1', %s, 1, %s, %s, %s, %s)",
                     (made.json()["pid"], FIRST["name"], FIRST["version"], FIRST["provider"], FIRST["description"]))
    return made.json()


def test_a_correction_whose_card_was_never_written_leaves_the_revision_where_the_cards_are(
        client, as_user, project, version_with_its_first_card):
    pid = version_with_its_first_card["pid"]
    counted = client.patch(f"/projects/{project['slug']}/system-versions/{pid}", json=correction(),
                           headers=as_user(ALICE))
    assert counted.status_code in (200, 409), counted.text
    # qualification's transaction failed here: no card at revision 2 was ever written
    [kept] = client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE)).json()
    assert kept["card_revision"] == 1, (
        f"the version reads card revision {kept['card_revision']} while its latest card is revision 1")


def test_the_next_correction_from_the_cards_revision_is_taken(client, as_user, project, version_with_its_first_card):
    pid = version_with_its_first_card["pid"]
    client.patch(f"/projects/{project['slug']}/system-versions/{pid}", json=correction(), headers=as_user(ALICE))
    # the card was rolled back; the person tries again from the card they see, revision 1
    retry = client.patch(f"/projects/{project['slug']}/system-versions/{pid}",
                         json=correction(provider="Eindhoven Engine B.V."), headers=as_user(ALICE))
    assert retry.status_code == 200, (
        f"a correction from the card's own revision answered {retry.status_code}: {retry.text}")


def test_a_correction_whose_card_was_never_written_leaves_the_version_described_as_its_cards_describe_it(
        client, as_user, project, version_with_its_first_card):
    pid = version_with_its_first_card["pid"]
    counted = client.patch(f"/projects/{project['slug']}/system-versions/{pid}", json=correction(),
                           headers=as_user(ALICE))
    assert counted.status_code == 200, counted.text
    # qualification's transaction failed here: the card still describes the version as revision 1 does
    [kept] = client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE)).json()
    assert {k: kept[k] for k in FIRST} == FIRST, (
        f"the version reads {({k: kept[k] for k in FIRST})} while its latest card describes it as {FIRST}")
    latest = client.get(f"/projects/{project['slug']}/system-versions/latest", headers=as_user(ALICE))
    if latest.status_code == 200:
        assert {k: latest.json()[k] for k in FIRST} == FIRST


def test_a_stored_correction_describes_the_version_as_its_new_card_does(
        client, as_user, project, version_with_its_first_card):
    pid = version_with_its_first_card["pid"]
    corrected = correction()
    stored = client.patch(f"/projects/{project['slug']}/system-versions/{pid}", json=corrected,
                          headers=as_user(ALICE))
    assert stored.status_code == 200, stored.text
    superuser = os.environ["PLATFORM_TEST_SUPERUSER_URL"]
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(project["pid"])),
                         autocommit=True) as conn:
        # qualification's transaction committed: its card at revision 2 says what the platform was sent
        conn.execute("insert into qualification.qualification"
                     ' (id, system_id, revision, "systemName", "systemVersion", company, description)'
                     " values ('card-r2', %s, 2, %s, %s, %s, %s)",
                     (pid, corrected["name"], corrected["version"], corrected["provider"], corrected["description"]))
    [kept] = client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE)).json()
    assert kept["card_revision"] == 2
    assert {k: kept[k] for k in FIRST} == {k: corrected[k] for k in FIRST}
