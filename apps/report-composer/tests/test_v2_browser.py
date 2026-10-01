"""Browser behaviours of composer.js (report run v2, fix round 1).

The draft preview recovers after a network failure (05-verify.md note 5), and the chapter indentation and
the "This chapter is empty." hint follow the block order after a move (note 6, R-V5.8, R-V5.9).
The real composer app runs with uvicorn on the bed with the v2 fake renderer; the system Chrome drives the
editor page through Playwright (no browser download).
"""
import socket
import threading
import time

import pytest

from conftest import FIXED_NOW, IDS, need, new_layout
from v2_fakes import clean_presets, client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live(client_v2, auth, token, fake_v2, bed, monkeypatch):
    """(open_editor(blocks) -> (page, layout), fake renderer) on a composer served over HTTP."""
    import uvicorn
    from playwright.sync_api import sync_playwright

    client_v2.get("/health")                              # builds the app once: migrations, env
    port = _free_port()
    monkeypatch.setenv("PLATFORM_ORIGIN", f"http://127.0.0.1:{port}")
    app = need("report_composer.app", "create_app")(
        database_url=bed.dsn("report_composer_rw", "platform"),
        project_database_url=bed.project_db_template("report_composer_rw"), renderer=fake_v2, clock=lambda: FIXED_NOW)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "the composer did not start"
    pw = sync_playwright().start()
    browser = pw.chromium.launch(channel="chrome", headless=True)
    context = browser.new_context(extra_http_headers={"Authorization": f"Bearer {token('alice')}"})
    errors = []

    def open_editor(blocks, **body):
        monkeypatch.setenv("PLATFORM_ORIGIN", "http://localhost")
        lay = new_layout(client_v2, auth, name=unique("Browser"), blocks=blocks, system_id=IDS["A_V2"], **body)
        monkeypatch.setenv("PLATFORM_ORIGIN", f"http://127.0.0.1:{port}")
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{port}/p/alpha/layouts/{lay['id']}?system_id={IDS['A_V2']}")
        page.wait_for_selector("main[data-api]")
        return page, lay

    try:
        yield open_editor
    finally:
        context.close()
        browser.close()
        pw.stop()
        server.should_exit = True
        thread.join(timeout=10)
    assert not errors, f"JavaScript errors: {errors}"


def _li(page, iid):
    return page.locator(f'#blocks li[data-instance-id="{iid}"]')


def test_fix_the_preview_recovers_after_a_network_failure(live):
    page, lay = live([v2blk("cover"), v2blk("free_text", text="Body")])
    failed = []

    def drop_first_draft(route):
        if route.request.method == "POST" and not failed:
            failed.append(route.request.url)
            route.abort("internetdisconnected")
        else:
            route.continue_()

    page.route("**/preview", drop_first_draft)
    page.click('[data-control="refresh-preview"]')
    label = page.locator("[data-preview-label]")
    label.filter(has_text="could not be reached").wait_for(timeout=5000)
    assert failed and "error" in (label.get_attribute("class") or "")
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/preview"), timeout=5000):
        page.click('[data-control="refresh-preview"]')
    page.wait_for_function("() => document.querySelector('main iframe').srcdoc.includes('free_text')",
                           timeout=5000)
    assert "could not be reached" not in label.inner_text()


def test_fix_chapter_indentation_follows_a_move(live):
    cover, chapter, card = v2blk("cover"), v2blk("chapter", title="Evidence"), v2blk("ai_card")
    page, lay = live([cover, chapter, card])
    assert _li(page, card["instance_id"]).get_attribute("data-depth") == "1"
    assert "This chapter is empty." not in _li(page, chapter["instance_id"]).inner_text()

    _li(page, card["instance_id"]).locator('[data-control="move-up"]').click()
    page.wait_for_function(
        f"""() => document.querySelector('#blocks li[data-instance-id="{card['instance_id']}"]').dataset.depth === "0" """,
        timeout=5000)
    _li(page, chapter["instance_id"]).get_by_text("This chapter is empty.").wait_for(timeout=5000)

    _li(page, card["instance_id"]).locator('[data-control="move-down"]').click()
    page.wait_for_function(
        f"""() => document.querySelector('#blocks li[data-instance-id="{card['instance_id']}"]').dataset.depth === "1" """,
        timeout=5000)
    assert "This chapter is empty." not in _li(page, chapter["instance_id"]).inner_text()


def test_fix_r2_5_an_older_outline_answer_arriving_last_is_ignored(live):
    """Fix round 2, item 5: two quick moves whose outline answers arrive out of order leave the indentation
    and the empty-chapter hint of the latest order on screen."""
    cover, chapter, card = v2blk("cover"), v2blk("chapter", title="Evidence"), v2blk("ai_card")
    page, lay = live([cover, chapter, card])
    held = []

    def hold_first_outline(route):
        if not held:
            held.append(route)                            # answered later, after the second move's answer
        else:
            route.continue_()

    page.route("**/outline", hold_first_outline)
    card_li = _li(page, card["instance_id"])
    card_li.locator('[data-control="move-up"]').click()   # order 1: card before the chapter (depth 0)
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    assert held, "the first outline request was not sent"
    with page.expect_response(lambda r: r.url.endswith("/outline"), timeout=5000):
        card_li.locator('[data-control="move-down"]').click()  # order 2: card back in the chapter (depth 1)
    page.wait_for_timeout(300)
    assert card_li.get_attribute("data-depth") == "1"
    with page.expect_response(lambda r: r.url.endswith("/outline"), timeout=5000):
        held[0].continue_()                               # the answer for order 1 now arrives last
    page.wait_for_timeout(300)
    assert card_li.get_attribute("data-depth") == "1"
    assert "This chapter is empty." not in _li(page, chapter["instance_id"]).inner_text()


def test_numbers_follow_a_move_and_the_numbering_box(live):
    """2026-10-01: the outline's numbers are the report's, redrawn after a move and when Numbering changes."""
    cover, chapter, card = v2blk("cover"), v2blk("chapter", title="Evidence"), v2blk("ai_card")
    page, lay = live([cover, chapter, card], numbering=True)

    def number_is(b, want):
        page.wait_for_function(
            f"""() => document.querySelector('#blocks li[data-instance-id="{b['instance_id']}"]').dataset.number === "{want}" """,
            timeout=5000)

    number_is(card, "1.1")
    _li(page, card["instance_id"]).locator('[data-control="move-up"]').click()
    number_is(card, "1")
    number_is(chapter, "2")
    page.locator('[data-control="numbering"]').uncheck()
    number_is(card, "")
    number_is(chapter, "")
    page.locator('[data-control="numbering"]').check()
    number_is(card, "1")
