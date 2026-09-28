"""The layouts page (report modules spec 2026-09-28, sections 4 and 5): New and Import in the header, the
built-in and the project's layouts in one list, no Start from, no Save as preset, no presets section."""
import pytest

from conftest import new_layout
from v2_fakes import client_v2, fake_v2  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _page(client, auth, who="alice"):
    return soup(client.get("/p/alpha/", headers=auth(who)).text)


def test_new_and_import_are_the_pages_actions(client_v2, auth):
    actions = _page(client_v2, auth).find(class_="rc-header").find(class_="page-actions")
    new = actions.find("a", attrs={"data-control": "start-new-layout"})
    assert new.get_text(strip=True) == "New layout" and new["href"].endswith("/p/alpha/layouts/new")
    imp = actions.find("form", attrs={"data-control": "import-layout"})
    assert imp.find("input", attrs={"type": "file"}) is not None and imp.find("button") is None
    assert "Import from file" in imp.get_text()


def test_built_ins_and_project_layouts_in_one_list(client_v2, auth):
    new_layout(client_v2, auth, name="Mine")
    rows = _page(client_v2, auth).select("table.layouts tbody tr")
    names = [r.find("td").find("a").get_text(strip=True) + (" Built-in" if r.find("td").find(class_="badge") else "")
             for r in rows]
    assert names[:5] == ["Summary Built-in", "Management overview Built-in", "Assessment report Built-in",
                         "EU AI Act conformity Built-in", "Technical dossier Built-in"]
    assert names[5] == "Mine"


def test_a_built_in_row_opens_duplicates_and_exports(client_v2, auth):
    row = _page(client_v2, auth).select("table.layouts tbody tr")[0]
    assert row.find("a", attrs={"data-control": "open-layout"})["href"].endswith("/p/alpha/layouts/builtin-summary")
    assert row.find(attrs={"data-control": "duplicate"})["data-layout"] == "builtin-summary"
    assert row.find("a", attrs={"data-control": "export-structure"})["href"].endswith(
        "/api/p/alpha/builtin-layouts/builtin-summary/export")


def test_the_old_controls_are_gone(client_v2, auth):
    new_layout(client_v2, auth, name="Mine")
    doc = _page(client_v2, auth)
    text = doc.get_text()
    assert "Start from" not in text and "Save as preset" not in text
    for control in ("save-preset", "delete", "import-preset", "new-layout", "export-preset", "delete-preset"):
        assert doc.find(attrs={"data-control": control}) is None, control
    assert "Version" not in [th.get_text(strip=True) for th in doc.select("table.layouts th")]


def test_a_viewer_can_open_and_export_but_not_create_or_duplicate(client_v2, auth):
    doc = _page(client_v2, auth, who="victor")
    assert doc.find(attrs={"data-control": "start-new-layout"}) is None
    assert doc.find(attrs={"data-control": "import-layout"}) is None
    assert doc.find(attrs={"data-control": "duplicate"}) is None
    assert doc.find(attrs={"data-control": "open-layout"}) is not None


def test_the_script_imports_on_pick_and_opens_what_it_made():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "report_composer/static/composer.js").read_text()
    part = js[js.index('if (main.dataset.page === "layouts")'):js.index('if (main.dataset.page === "templates")')]
    assert '"import-layout"' in part and "requestSubmit()" in part
    assert 'base + "/layouts/" + res.data.id' in part
    assert "save-preset" not in part and "presetsApi" not in part
