"""Download report (2026-10-06): next to Show in the preview's form, a menu with PDF and Word (DOCX).
It generates the report with the form's version, period and other-versions switch, stores and lists it
like any report, and answers with the document, so the browser downloads it and stays on the page.
The same for a built-in layout and the project's own; editors only. Database tests, fake renderer."""
import pytest

from bs4 import BeautifulSoup

from conftest import IDS, PDF, new_layout
from v2_fakes import DOCX, client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

B = "builtin-summary"


def soup(html):
    return BeautifulSoup(html, "html.parser")


def own(client_v2, auth):
    return new_layout(client_v2, auth, name="Own", blocks=[v2blk("cover"), v2blk("free_text", text="x")])["id"]


def download(client_v2, auth, layout_id, fmt, who="alice", **form):
    data = {"system_id": IDS["A_V2"], "format": fmt, **form}
    return client_v2.post(f"/p/alpha/layouts/{layout_id}/download-report", headers=auth(who), data=data,
                          follow_redirects=False)


@pytest.mark.parametrize("which", ["own", "builtin"])
def test_the_preview_form_has_the_download_menu_next_to_show(client_v2, auth, which):
    lid = own(client_v2, auth) if which == "own" else B
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lid}", headers=auth("alice")).text)
    form = doc.find("form", attrs={"data-control": "preview-with"})
    menu = form.find(attrs={"data-control": "download-report"})
    assert menu is not None and "Download report" in menu.get_text()
    buttons = {b["value"]: b for b in menu.find_all("button")}
    assert set(buttons) == {"pdf", "docx"}
    for b in buttons.values():
        assert b["formaction"].endswith(f"/p/alpha/layouts/{lid}/download-report") and b["formmethod"] == "post"
    assert doc.find(attrs={"data-control": "open-generate"}) is None          # no page of its own any more


def test_a_viewer_has_no_download_menu(client_v2, auth):
    doc = soup(client_v2.get(f"/p/alpha/layouts/{B}", headers=auth("victor")).text)
    assert doc.find(attrs={"data-control": "download-report"}) is None
    assert download(client_v2, auth, B, "pdf", who="victor").status_code == 403


def test_pdf_downloads_and_is_listed(client_v2, auth):
    lid = own(client_v2, auth)
    r = download(client_v2, auth, lid, "pdf")
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment;") and r.headers["content-disposition"].endswith('.pdf"')
    assert len(client_v2.get(f"/api/p/alpha/layouts/{lid}/reports", headers=auth("victor")).json()) == 1


def test_word_of_a_built_in_downloads_and_keeps_its_pdf(client_v2, auth):
    r = download(client_v2, auth, B, "docx", other_versions="on", period_from="2026-09-01")
    assert r.status_code == 200 and r.content == DOCX and r.headers["content-disposition"].endswith('.docx"')
    [listed] = client_v2.get(f"/api/p/alpha/layouts/{B}/reports", headers=auth("victor")).json()
    assert listed["has_pdf"] is True and listed["other_versions"] is True


def test_a_refused_choice_comes_back_to_the_page_with_the_message(client_v2, auth):
    lid = own(client_v2, auth)
    r = download(client_v2, auth, lid, "pdf", period_from="2026-09-12", period_to="2026-09-10")
    assert r.status_code == 303 and f"/p/alpha/layouts/{lid}?" in r.headers["location"]
    page = client_v2.get(r.headers["location"].split("testserver")[-1], headers=auth("alice")).text
    assert "The period ends before it starts." in page
