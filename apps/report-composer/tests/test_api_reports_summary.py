"""What the sandbox page shows in its Report column: for one AI card version, how many reports were generated
(failed ones not counted) and the newest one, with where to download it. Database tests, fake renderer."""
import pytest

from conftest import IDS, blk, new_layout, pdb_of
from v2_fakes import client_v2, fake_v2  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def generate(client, auth, layout_id, system_id):
    r = client.post(f"/api/p/alpha/layouts/{layout_id}/reports", json={"system_id": system_id}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def summary(client, auth, system_id, who="victor"):
    return client.get(f"/api/p/alpha/reports?system_id={system_id}", headers=auth(who))


def made_at(bed, report_id, when):
    bed.psql(pdb_of("A"), f"UPDATE report_composer.generated_report SET created_at = '{when}' WHERE id = '{report_id}'")


def test_no_report_yet(client, auth):
    r = summary(client, auth, IDS["A_V2"])
    assert r.status_code == 200 and r.json() == {"count": 0, "latest": None}


def test_the_count_and_the_newest_report_of_the_version(client, auth, bed):
    quarterly = new_layout(client, auth, name="Quarterly report", system_id=IDS["A_V2"], blocks=[blk("cover")])
    annual = new_layout(client, auth, name="Annual report", system_id=IDS["A_V2"], blocks=[blk("cover")])
    older = generate(client, auth, quarterly["id"], IDS["A_V2"])
    newer = generate(client, auth, annual["id"], IDS["A_V2"])
    made_at(bed, older, "2026-10-01 09:00+00")
    made_at(bed, newer, "2026-10-02 09:00+00")
    body = summary(client, auth, IDS["A_V2"]).json()
    assert body["count"] == 2
    latest = body["latest"]
    assert latest["id"] == newer and latest["layout_name"] == "Annual report" and latest["layout_id"] == annual["id"]
    assert latest["format"] == "pdf" and latest["status"] == "done" and latest["created_at"].startswith("2026-10-02")
    assert latest["download"] == f"/api/p/alpha/reports/{newer}/download"


def test_another_versions_reports_and_failed_ones_are_not_counted(client, auth, bed):
    lay = new_layout(client, auth, name="Quarterly report", system_id=IDS["A_V2"], blocks=[blk("cover")])
    generate(client, auth, lay["id"], IDS["A_V3"])
    failed = generate(client, auth, lay["id"], IDS["A_V2"])
    bed.psql(pdb_of("A"), f"UPDATE report_composer.generated_report SET status = 'failed' WHERE id = '{failed}'")
    assert summary(client, auth, IDS["A_V2"]).json() == {"count": 0, "latest": None}
    assert summary(client, auth, IDS["A_V3"]).json()["count"] == 1


def test_a_built_in_layouts_report_links_to_the_built_in(client_v2, auth):
    """client_v2: a renderer that knows the built-ins' newer blocks (key figures, changes since)."""
    rid = generate(client_v2, auth, "builtin-summary", IDS["A_V2"])
    latest = summary(client_v2, auth, IDS["A_V2"]).json()["latest"]
    assert latest["id"] == rid and latest["layout_id"] == "builtin-summary"


def test_a_stranger_gets_nothing(client, auth):
    assert summary(client, auth, IDS["A_V2"], who="bob").status_code == 404
