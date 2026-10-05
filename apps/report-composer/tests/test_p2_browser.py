"""When the latest outline request fails, the editor removes
every indentation and outline hint, says so in the message region with a "Try again" button, still ignores an
older answer arriving afterwards, and redraws on the next successful answer. Browser test (system Chrome
through Playwright), on the composer served over HTTP with the v2 fake renderer, like test_v2_browser.py.
"""
import json
import time

import pytest

from conftest import IDS
from test_p2_presets import FOREIGN, label, preset_file
from test_v2_browser import _li, live  # noqa: F401  (the browser fixture)
from v2_fakes import clean_presets, client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]
MESSAGE = "The chapter outline could not be updated."


def test_r2_d3_3_1_a_failed_outline_request_clears_the_outline_and_offers_try_again(live):
    cover, chapter, card = v2blk("cover"), v2blk("chapter", title="Evidence"), v2blk("ai_card")
    page, lay = live([cover, chapter, card])
    assert _li(page, card["instance_id"]).get_attribute("data-depth") == "1"
    held, aborted = [], []

    def route(r):
        if not held:
            held.append(r)                                 # the older request: answered after the failure
        elif not aborted:
            aborted.append(r.request.url)
            r.abort("internetdisconnected")                # the latest request fails
        else:
            r.continue_()

    page.route("**/outline", route)
    card_li = _li(page, card["instance_id"])
    card_li.locator('[data-control="move-up"]').click()
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    assert held, "the first outline request was not sent"
    card_li.locator('[data-control="move-down"]').click()
    region = page.locator("main [data-message]")
    region.filter(has_text=MESSAGE).wait_for(timeout=5000)
    assert aborted
    depths = page.eval_on_selector_all("#blocks li[data-instance-id]", "els => els.map(e => e.dataset.depth)")
    assert depths and set(depths) == {"0"}
    assert "This chapter is empty." not in page.locator("#blocks").inner_text()

    held[0].continue_()                                    # the older answer arrives last: still ignored
    page.wait_for_timeout(300)
    depths = page.eval_on_selector_all("#blocks li[data-instance-id]", "els => els.map(e => e.dataset.depth)")
    assert set(depths) == {"0"}

    with page.expect_response(lambda r: r.url.endswith("/outline"), timeout=5000):
        region.get_by_role("button", name="Try again").click()
    page.wait_for_function(
        f"""() => document.querySelector('#blocks li[data-instance-id="{card['instance_id']}"]').dataset.depth === "1" """,
        timeout=5000)
    assert MESSAGE not in region.inner_text()


def test_r2_d3_6_2_the_composer_shows_notices_as_information(live):
    """A preset file with another project's references is imported on the layouts page; the new layout's
    editor opens and its message region names every reset reference, as information (not an error)."""
    page, _ = live([v2blk("cover")])                        # any page of the served composer, to learn its address
    base = page.url.rsplit("/layouts/", 1)[0]
    page.goto(base + "/")
    # Import from file in the page header; picking the file imports it
    form = page.locator('.page-actions form[data-control="import-layout"]')
    with page.expect_navigation(url="**/layouts/*", timeout=10000):
        form.locator('input[name="file"]').set_input_files(
            files=[{"name": "preset.json", "mimeType": "application/json",
                    "buffer": json.dumps(preset_file(FOREIGN[:3])).encode()}])
    page.wait_for_selector("main[data-api]")
    region = page.locator("main [data-message]")
    tail = "pointed at data that is not in this project; it was reset to its default."
    region.filter(has_text=tail).wait_for(timeout=5000)
    text = region.inner_text()
    assert f"The {label('dashboard_chart', 'chart_id')} of block 2 {tail}" in text
    assert f"The {label('test_results', 'evaluations')} of block 3 {tail}" in text
    assert "ok" in (region.get_attribute("class") or "")      # information, not an error
    page.reload()                                             # shown once: the carried notices are used up
    page.wait_for_selector("main[data-api]")
    assert tail not in page.locator("main").inner_text()
