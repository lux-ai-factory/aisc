"""Part 2, D3.3 (10-specs-part2.md R2-D3.3.1): when the latest outline request fails, the editor removes
every indentation and outline hint, says so in the message region with a "Try again" button, still ignores an
older answer arriving afterwards, and redraws on the next successful answer. Browser test (system Chrome
through Playwright), on the composer served over HTTP with the v2 fake renderer, like test_v2_browser.py.
"""
import time

import pytest

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
