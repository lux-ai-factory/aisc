"""The editor says what will happen and what happened around Generate and download and Save.

- Generate and download with unsaved changes says, in the composer's own words, that the report is made of the
  saved revision and not of the preview, before anything is generated (the browser's generic "leave site?" is
  not that warning).
- A save refused because the layout was saved meanwhile offers a way forward in the message region.
- After a failed Generate and download, a later successful one removes the old failure message and lists the
  new report without a reload.

Browser tests (system Chrome through Playwright) on the composer served over HTTP with the v2 fake renderer,
like test_v2_browser.py.
"""
import pytest

from conftest import put_layout
from test_v2_browser import live  # noqa: F401  (the browser fixture)
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _origin(page):
    return page.url.split("/p/", 1)[0]


def _open_download_menu(page):
    page.click('[data-control="download-report"] summary')


def test_generate_with_unsaved_changes_says_the_report_is_of_the_saved_revision(live):
    page, lay = live([v2blk("cover"), v2blk("free_text", text="Body")])
    native, sent = [], []

    def on_dialog(d):
        native.append((d.type, d.message))
        d.accept()                                 # leave the page if the browser asks: the generic prompt

    page.on("dialog", on_dialog)
    page.on("request", lambda r: sent.append(r.url) if r.url.endswith("/download-report") else None)
    page.click('[data-control="show_index"]')       # an unsaved change of the layout
    page.locator("[data-state]").filter(has_text="Unsaved").wait_for(timeout=5000)
    _open_download_menu(page)
    page.click('[data-control="download-report"] button[value="pdf"]', no_wait_after=True)
    page.wait_for_timeout(1500)
    own_words = [m for t, m in native if t != "beforeunload"]
    region = page.locator("main [data-message]")
    in_page = region.inner_text() if region.is_visible() else ""
    dialog = page.locator("dialog[data-confirm][open]")
    asked = dialog.inner_text() if dialog.count() else ""
    told = " ".join(own_words + [in_page, asked]).lower()
    assert "unsaved" in told or "not saved" in told, \
        (f"no word from the composer about the unsaved changes before generating; requests sent: {sent},"
         f" browser prompts: {native}")


def test_a_save_refused_as_stale_offers_a_way_forward(live, client_v2, auth):
    page, lay = live([v2blk("cover"), v2blk("free_text", text="Body")])
    elsewhere = put_layout(client_v2, lambda who: auth(who, origin=_origin(page)), lay, name="Changed elsewhere")
    assert elsewhere.status_code == 200, elsewhere.text
    page.click('[data-control="show_index"]')
    page.click('[data-control="save"]')
    region = page.locator("main [data-message]")
    page.wait_for_timeout(2500)                     # the save's answer and the preview that follows it
    shown = region.inner_text() if region.is_visible() else ""
    assert "revision 2" in shown, f"the refused save is not said on the page (or a later preview wiped it): {shown!r}"
    action = region.locator('[data-control="message-action"]')
    assert action.is_visible(), f"the stale-save message offers nothing to do: {shown!r}"


def test_a_later_successful_download_clears_the_old_failure_and_lists_the_report(live):
    page, lay = live([v2blk("cover"), v2blk("free_text", text="Body")])
    page.goto(page.url + "&report_error=The+report+renderer+is+not+available")   # where a failed one lands
    page.wait_for_selector("main[data-api]")
    assert page.locator("[data-report-error]").count() == 1
    _open_download_menu(page)
    with page.expect_download(timeout=10000):
        page.click('[data-control="download-report"] button[value="pdf"]')
    page.wait_for_timeout(1000)
    old = page.locator("[data-report-error]")
    assert not (old.count() and old.is_visible()), \
        f"the old failure is still shown after a successful download: {old.inner_text()!r}"
    rows = page.locator("table[data-reports] tbody tr")
    assert rows.count() == 1, "the new report is not listed until a reload"
