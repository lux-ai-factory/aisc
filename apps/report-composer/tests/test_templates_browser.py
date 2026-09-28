"""The templates screen in a browser (2026-09-28): one editor for a new template, a reopened one and a
just-imported one. New opens it empty, Create and Import land in it on that template, Delete in it goes
back to the list. The real composer app runs with uvicorn on the bed; the system Chrome drives it through
Playwright, as in test_v2_browser.py. RC_SCREENSHOTS=<dir> also saves a picture of each state.
"""
import contextlib
import json
import os
import socket
import threading
import time

import pytest

from conftest import FIXED_NOW, need, new_template
from v2_fakes import client_v2, fake_v2, unique  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live(client_v2, auth, token, fake_v2, bed, monkeypatch):
    """open(query="") -> page on the templates screen of a composer served over HTTP, as alice;
    open.api() -> a block in which the test client's API calls are same-origin again."""
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
    context = browser.new_context(extra_http_headers={"Authorization": f"Bearer {token('alice')}"},
                                  viewport={"width": 1440, "height": 1000})
    errors = []

    def open_page(query=""):
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{port}/p/alpha/templates{query}")
        page.wait_for_selector("main[data-api]")
        return page

    @contextlib.contextmanager
    def api():
        monkeypatch.setenv("PLATFORM_ORIGIN", "http://localhost")
        try:
            yield
        finally:
            monkeypatch.setenv("PLATFORM_ORIGIN", f"http://127.0.0.1:{port}")

    open_page.api = api
    try:
        yield open_page
    finally:
        context.close()
        browser.close()
        pw.stop()
        server.should_exit = True
        thread.join(timeout=10)
    assert not errors, f"JavaScript errors: {errors}"


def _shot(page, name):
    where = os.environ.get("RC_SCREENSHOTS")
    if where:
        page.screenshot(path=os.path.join(where, f"{name}.png"), full_page=True)


def _in_editor(page, name):
    page.wait_for_url("**/templates?edit=*", timeout=5000)
    page.locator("#template-editor h2").filter(has_text=name).wait_for(timeout=5000)
    assert page.locator('#template-editor form[data-control="edit-template"]').count() == 1


def test_new_then_create_lands_in_the_editor_on_the_new_template(live):
    page = live()
    _shot(page, "1-empty")
    assert page.locator("#template-editor").count() == 0
    page.click('.page-actions [data-control="start-new-template"]')
    page.wait_for_selector('#template-editor form[data-control="new-template"]')
    _shot(page, "2-new")
    page.fill('#template-editor input[name="name"]', "Bank X")
    page.click('#template-editor button[type="submit"]')
    _in_editor(page, "Bank X")
    _shot(page, "3-created")


def test_a_picked_file_is_imported_and_opens_in_the_editor(live, client_v2, auth, tmp_path):
    with live.api():
        x = new_template(client_v2, auth, name="Bank X")
        new_template(client_v2, auth, name="Bank Y")
        exported = client_v2.get(f"/api/p/alpha/templates/{x['id']}/export", headers=auth("alice")).json()
    exported["name"] = "Imported look"
    file = tmp_path / "look.json"
    file.write_text(json.dumps(exported))
    page = live()
    _shot(page, "4-list")
    page.set_input_files('.page-actions [data-control="import-template"] input[type="file"]', str(file))
    _in_editor(page, "Imported look")
    _shot(page, "5-imported")


def test_delete_in_the_editor_goes_back_to_the_list(live, client_v2, auth):
    with live.api():
        x = new_template(client_v2, auth, name="Bank X")
        new_template(client_v2, auth, name="Bank Y")
    page = live(f"?edit={x['id']}")
    page.click('#template-editor [data-control="delete-template"]')
    page.click("dialog[data-confirm] [data-confirm-ok]")
    page.wait_for_url(lambda url: "edit=" not in url, timeout=5000)
    page.wait_for_selector("main[data-api]")
    assert page.locator(f'article[data-template="{x["id"]}"]').count() == 0
    assert page.locator("#template-editor").count() == 0
    _shot(page, "6-after-delete")


def test_cancel_closes_the_editor(live, client_v2, auth):
    with live.api():
        x = new_template(client_v2, auth, name="Bank X")
    page = live(f"?edit={x['id']}")
    page.click('#template-editor [data-control="cancel-template"]')
    page.wait_for_url(lambda url: "edit=" not in url, timeout=5000)
    assert page.locator("#template-editor").count() == 0
