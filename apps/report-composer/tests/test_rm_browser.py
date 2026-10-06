"""The report composer's layout flows in a browser: a new
layout saved and generated, a built-in duplicated, an old layout file imported. The real composer app runs
with uvicorn on the bed; the system Chrome drives it through Playwright. RC_SCREENSHOTS=<dir> also saves a
picture of each screen.
"""
import contextlib
import json
import os
import socket
import threading
import time

import pytest

from conftest import FIXED_NOW, IDS, need
from v2_fakes import client_v2, fake_v2, unique  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live(client_v2, auth, token, fake_v2, bed, monkeypatch):
    """open(path) -> page at `path` (/p/alpha/...) of a composer served over HTTP, as alice;
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

    def open_page(path="/p/alpha/"):
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"http://127.0.0.1:{port}{path}")
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


def test_new_layout_save_then_generate(live, fake_v2):
    page = live("/p/alpha/")
    _shot(page, "1-layouts")
    page.click('.page-actions [data-control="start-new-layout"]')
    page.wait_for_url("**/layouts/new")
    page.fill('.toolbar input[name="name"]', "Browser layout")
    page.click('[data-palette] button[data-add="cover"]')
    page.click('[data-palette] button[data-add="test_runs"]')
    _shot(page, "2-new-layout")
    page.click('[data-control="save"]')
    page.wait_for_url(lambda u: "/layouts/new" not in u and "/layouts/" in u, timeout=10000)
    page.wait_for_selector("main[data-api]")
    _shot(page, "3-saved-layout")
    # Download report, next to Show in the preview's form (2026-10-06): generates and downloads, same page
    page.select_option('form[data-control="preview-with"] select[name="system_id"]', IDS["A_V2"])
    page.fill('form[data-control="preview-with"] input[name="period_from"]', "2026-09-10")
    page.click('[data-control="download-report"] summary')
    _shot(page, "4-download-menu")
    with page.expect_download(timeout=15000) as got:
        page.click('[data-control="download-report"] button[value="pdf"]')
    assert got.value.suggested_filename.endswith(".pdf")
    page.reload()
    assert page.locator("table[data-reports] tbody tr").count() == 1
    assert "Version 2" in page.locator("table[data-reports] tbody tr").inner_text()
    _shot(page, "5-generated")
    report = [x for x in fake_v2.snapshots if x["mode"] == "pdf"][-1]     # not the editor's later preview
    assert report["selection"]["period_from"] == "2026-09-10T00:00:00+00:00" and report["system_id"] == IDS["A_V2"]


def test_duplicate_a_built_in_opens_its_copy(live):
    page = live("/p/alpha/layouts/builtin-assessment-report")
    _shot(page, "6-built-in")
    page.click('.page-actions [data-control="duplicate"]')
    page.wait_for_url(lambda u: "builtin-" not in u and "/layouts/" in u, timeout=10000)
    page.wait_for_selector(".toolbar input[name=name]")
    assert page.locator('.toolbar input[name="name"]').input_value() == "Assessment report (copy)"


def test_import_a_file_opens_the_imported_layout(live, tmp_path):
    old = {"format": "aisc-report-preset", "version": 1, "name": "Imported old", "toc": "off",
           "blocks": [{"block_type": "test_results", "options": {"evaluations": [IDS["EVAL_M_V2_PF_FULL"]]}}]}
    file = tmp_path / "old.json"
    file.write_text(json.dumps(old))
    page = live("/p/alpha/")
    page.set_input_files('.page-actions [data-control="import-layout"] input[type="file"]', str(file))
    page.wait_for_url(lambda u: "/layouts/" in u and "/layouts/new" not in u, timeout=10000)
    page.wait_for_selector(".toolbar input[name=name]")
    assert page.locator('.toolbar input[name="name"]').input_value() == "Imported old"
    assert page.locator('.toolbar input[name="show_index"]').is_checked() is False


def test_delete_in_the_editor_goes_back_to_the_list(live, client_v2, auth):
    from conftest import new_layout
    with live.api():
        lay = new_layout(client_v2, auth, name=unique("Doomed"))
    page = live(f"/p/alpha/layouts/{lay['id']}")
    page.click('.toolbar [data-control="delete-layout"]')
    page.click("dialog[data-confirm] [data-confirm-ok]")
    page.wait_for_url(lambda u: u.rstrip("/").endswith("/p/alpha"), timeout=10000)
    assert page.locator(f'tr[data-layout="{lay["id"]}"]').count() == 0
