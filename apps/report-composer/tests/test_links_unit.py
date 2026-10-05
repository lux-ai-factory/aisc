"""The launcher's step 6 link has no trailing slash: /report-composer/p/<pid>.

Behind Caddy's handle_path the app only sees /p/<pid>. The redirect to the
page's own address must keep the /report-composer prefix, or the browser lands
on the execution engine's catch-all route and its 404 page. No database: the
lifespan (migrations) does not run without the context manager.
"""
from fastapi.testclient import TestClient

PID = "01399e17-4b01-4be9-997a-7f5e3574ab22"


def _client(monkeypatch):
    monkeypatch.setenv("REPORT_COMPOSER_ROOT_PATH", "/report-composer")
    from report_composer.app import create_app

    return TestClient(create_app(database_url="postgresql://unused/none", renderer=object()),
                      base_url="http://localhost")


def test_the_launcher_link_without_a_slash_stays_in_the_composer(monkeypatch):
    response = _client(monkeypatch).get(f"/p/{PID}", follow_redirects=False)
    assert response.status_code in (301, 302, 303, 307, 308)
    assert response.headers["location"] == f"/report-composer/p/{PID}/"



def test_the_stylesheet_and_script_load_behind_the_stripped_prefix(monkeypatch):
    # Caddy strips /report-composer, so the browser's /report-composer/static/... arrives as /static/...
    client = _client(monkeypatch)
    for asset in ("composer.css", "composer.js", "laif-logo.svg"):
        assert client.get(f"/static/{asset}").status_code == 200, asset


def test_an_api_error_behind_the_prefix_is_still_json(monkeypatch):
    # errors choose JSON for /api/..., HTML for pages; the restored prefix must not change that
    response = _client(monkeypatch).get("/api/p/no-such-project/layouts")
    assert response.headers["content-type"].startswith("application/json"), response.text[:200]
