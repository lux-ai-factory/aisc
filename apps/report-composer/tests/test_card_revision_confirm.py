"""Generating a report asks once when only the AI card's state moved since the page was drawn
(docs/specs/who-does-what.md, section 3): the generate form and the JSON route name the card revision of the
chosen version the person was shown; when the version is now at another revision, nothing is generated and the
answer is upstream_moved_confirm, one question with one button that generates on the revision it names. A
request that names no card revision generates as before. A report stored before reports kept their card revision
says "card revision not recorded" in the list. Database tests, fake renderer."""
import json

import pytest
from bs4 import BeautifulSoup

from conftest import IDS, blk, new_layout, pdb_of

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _layout(client, auth):
    return new_layout(client, auth, name="Card moved", system_id=IDS["A_V3"], blocks=[blk("cover")])


def _reports(bed):
    return int(bed.scalar(pdb_of("A"), "SELECT count(*) FROM report_composer.generated_report"))


def _at_revision(bed, revision):
    bed.psql(pdb_of("A"), f"UPDATE project.system SET card_revision = {revision} WHERE pid = '{IDS['A_V3']}'")


def test_a_report_asked_on_an_earlier_card_revision_asks_once_and_generates_nothing(client, auth, bed):
    _at_revision(bed, 2)
    lay = _layout(client, auth)
    before = _reports(bed)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports",
                    json={"system_id": IDS["A_V3"], "card_revision": 1}, headers=auth("alice"))
    assert r.status_code == 409, r.text[:300]
    error = r.json()["error"]
    assert error["code"] == "upstream_moved_confirm"
    assert error["message"].startswith("The AI card is now v3 revision 2"), error["message"]
    assert error["message"].endswith("Generate on revision 2?"), error["message"]
    assert error["details"] == [{"card_version": IDS["A_V3"], "card_revision": 2}]
    assert _reports(bed) == before


def test_a_report_asked_again_on_the_revision_named_is_generated(client, auth, bed):
    _at_revision(bed, 2)
    lay = _layout(client, auth)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports",
                    json={"system_id": IDS["A_V3"], "card_revision": 2}, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]


def test_a_report_that_names_no_card_revision_is_generated_as_before(client, auth, bed):
    _at_revision(bed, 2)
    lay = _layout(client, auth)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V3"]},
                    headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]


def test_the_generate_form_names_the_card_revision_shown_and_asks_once_with_one_button(client, auth, bed):
    _at_revision(bed, 1)
    lay = _layout(client, auth)
    page = BeautifulSoup(client.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice")).text,
                         "html.parser")
    shown = page.find("input", attrs={"name": f"card_revision:{IDS['A_V3']}"})
    assert shown is not None and shown.get("value") == "1"
    _at_revision(bed, 2)
    before = _reports(bed)
    r = client.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"),
                    data={"system_id": IDS["A_V3"], "revision": str(lay["revision"]),
                          f"card_revision:{IDS['A_V3']}": "1"})
    assert r.status_code == 409, r.text[:300]
    asked = BeautifulSoup(r.text, "html.parser")
    assert "Generate on revision 2?" in asked.get_text(" ")
    again = asked.find("input", attrs={"name": f"card_revision:{IDS['A_V3']}"})
    assert again is not None and again.get("value") == "2"
    assert [b.get_text(strip=True) for b in asked.find_all("button", attrs={"type": "submit"})] == \
        ["Generate on revision 2"]
    assert _reports(bed) == before


def test_a_report_stored_without_its_card_revision_says_so_in_the_list(client, auth, bed):
    lay = _layout(client, auth)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V3"]},
                    headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    bed.psql(pdb_of("A"), "UPDATE report_composer.generated_report SET snapshot = snapshot - 'card_revision'"
                          f" WHERE id = '{r.json()['id']}'")
    page = BeautifulSoup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text, "html.parser")
    row = page.find("table", attrs={"data-reports": True}).find("tbody").find("tr")
    assert "card revision not recorded" in row.get_text(" ", strip=True)
    assert json.loads(bed.scalar(pdb_of("A"), "SELECT snapshot::text FROM report_composer.generated_report"
                                              f" WHERE id = '{r.json()['id']}'")).get("card_revision") is None
