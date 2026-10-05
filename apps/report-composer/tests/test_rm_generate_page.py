"""The Generate report page: a form drawn and handled in
Python; the version is required, the period, the other-versions switch and Compare with are optional."""
import pytest

from conftest import IDS, new_layout
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def test_the_form_asks_for_version_period_switch_and_format(client_v2, auth):
    lay = new_layout(client_v2, auth, name="G", blocks=[v2blk("cover")])
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice")).text)
    form = doc.find("form", attrs={"data-control": "generate-report"})
    versions = [o.get_text(strip=True) for o in form.find("select", attrs={"name": "system_id"}).find_all("option")]
    assert versions[0].startswith("Version 3") and len(versions) == 3          # newest first
    for name in ("period_from", "period_to", "other_versions", "format"):
        assert form.find(attrs={"name": name}) is not None, name
    assert form.find(attrs={"name": "compare_to"}) is None       # no Changes since in this layout


def test_compare_with_appears_with_changes_since(client_v2, auth):
    lay = new_layout(client_v2, auth, name="C", blocks=[v2blk("changes_since")])
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice")).text)
    options = [o["value"] for o in doc.find("select", attrs={"name": "compare_to"}).find_all("option")]
    assert options[0] == "" and set(options[1:]) == {IDS["A_V1"], IDS["A_V2"], IDS["A_V3"]}


def test_submitting_generates_and_goes_back_to_the_layout(client_v2, auth, fake_v2):
    lay = new_layout(client_v2, auth, name="S", blocks=[v2blk("cover")])
    r = client_v2.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"), follow_redirects=False,
                       data={"system_id": IDS["A_V2"], "period_from": "2026-09-10", "period_to": "",
                             "format": "pdf"})
    assert r.status_code == 303, r.text[:300]
    assert r.headers["location"].endswith(f"/p/alpha/layouts/{lay['id']}#reports")
    snap = fake_v2.snapshots[-1]
    assert snap["system_id"] == IDS["A_V2"] and snap["selection"]["period_from"] == "2026-09-10T00:00:00+00:00"
    assert snap["selection"]["period_to"] is None and snap["selection"]["other_versions"] is False


def test_the_switch_is_sent_when_ticked(client_v2, auth, fake_v2):
    lay = new_layout(client_v2, auth, name="Sw", blocks=[v2blk("cover")])
    client_v2.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"), follow_redirects=False,
                   data={"system_id": IDS["A_V2"], "other_versions": "on", "format": "docx"})
    sent = fake_v2.snapshots[-2]                     # the Word render; [-1] is its PDF copy
    assert sent["selection"]["other_versions"] is True and sent["mode"] == "docx"


def test_an_upside_down_period_redraws_the_form_with_the_message(client_v2, auth):
    lay = new_layout(client_v2, auth, name="U", blocks=[v2blk("cover")])
    r = client_v2.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"),
                       data={"system_id": IDS["A_V2"], "period_from": "2026-09-12", "period_to": "2026-09-10",
                             "format": "pdf"})
    assert r.status_code == 422 and "The period ends before it starts." in r.text
    form = soup(r.text).find("form", attrs={"data-control": "generate-report"})
    assert form.find("input", attrs={"name": "period_from"})["value"] == "2026-09-12"   # what was typed stays


def test_a_cross_origin_post_is_refused(client_v2, auth):
    lay = new_layout(client_v2, auth, name="X", blocks=[v2blk("cover")])
    r = client_v2.post(f"/p/alpha/layouts/{lay['id']}/generate",
                       headers={**auth("alice"), "Origin": "https://evil.test"},
                       data={"system_id": IDS["A_V2"], "format": "pdf"})
    assert r.status_code == 403


def test_a_viewer_cannot_open_the_generate_page(client_v2, auth):
    lay = new_layout(client_v2, auth, name="V", blocks=[v2blk("cover")])
    assert client_v2.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("victor")).status_code == 403


def test_without_a_version_generate_explains():
    from report_composer.pages import generate_context
    ctx = generate_context(layout={"blocks": []}, systems=[])
    assert ctx["message"] == "This project has no AI card version yet. Save the AI card in qualification first."


def test_a_refused_generation_lists_every_problem_with_its_module(client_v2, auth):
    """The page names each module whose option the chosen version does not offer."""
    lay = new_layout(client_v2, auth, name="Refs", blocks=[v2blk("cover"),
                                                           v2blk("control_answers", checklists=["no-such-list"]),
                                                           v2blk("dashboard_chart", chart_id=999)])
    r = client_v2.post(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice"),
                       data={"system_id": IDS["A_V2"], "format": "pdf"})
    assert r.status_code == 422
    items = [li.get_text(" ", strip=True) for li in soup(r.text).select("[data-problems] li")]
    assert len(items) == 2, items
    assert items[0].startswith("Control answers") and items[1].startswith("Dashboard chart")
