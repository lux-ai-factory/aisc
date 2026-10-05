"""The layout editor: grouped palette, Index and Numbering, a
Preview with choice that is never saved, Generate as a link, Delete inside the editor, built-ins read-only."""
import json

import pytest

from conftest import IDS, new_layout
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _editor(client, auth, path, who="alice"):
    return soup(client.get(f"/p/alpha/layouts/{path}", headers=auth(who)).text)


def test_the_palette_is_grouped(client_v2, auth):
    lay = new_layout(client_v2, auth, name="P")
    doc = _editor(client_v2, auth, lay["id"])
    labels = [h.get_text(strip=True) for h in doc.select("[data-palette] .palette-group > h3")]
    assert labels[:6] == ["AI card", "Control objectives", "Tests run", "Results", "Summary", "Document"]
    tests_run = doc.select("[data-palette] .palette-group")[2]
    assert [b["data-add"] for b in tests_run.find_all("button")] == ["test_runs"]


def test_the_toolbar_has_name_index_and_numbering_and_no_version(client_v2, auth):
    lay = new_layout(client_v2, auth, name="T", show_index=False)
    tb = _editor(client_v2, auth, lay["id"]).find(class_="toolbar")
    assert tb.find("input", attrs={"name": "name"})["value"] == "T"
    assert not tb.find("input", attrs={"name": "show_index", "type": "checkbox"}).has_attr("checked")
    assert tb.find("input", attrs={"name": "numbering", "type": "checkbox"}) is not None
    assert tb.find(attrs={"data-control": "version"}) is None and tb.find(attrs={"data-control": "toc"}) is None
    assert tb.find("a", attrs={"data-control": "open-generate"})["href"].endswith(f"/layouts/{lay['id']}/generate")
    assert tb.find(attrs={"data-control": "delete-layout"}) is not None


def test_delete_asks_first_with_the_one_dialog(client_v2, auth):
    lay = new_layout(client_v2, auth, name="D")
    doc = _editor(client_v2, auth, lay["id"])
    assert len(doc.find_all("dialog", attrs={"data-confirm": True})) == 1
    delete = doc.find(attrs={"data-control": "delete-layout"})
    assert delete.get("data-confirm-text") and delete.get("data-confirm-action") == "Delete layout"


def test_a_built_in_opens_read_only(client_v2, auth):
    doc = _editor(client_v2, auth, "builtin-summary")
    assert doc.find(attrs={"data-control": "save"}) is None and doc.find(attrs={"data-palette": True}) is None
    assert doc.find(attrs={"data-control": "delete-layout"}) is None
    assert doc.find(attrs={"data-control": "duplicate"})["data-layout"] == "builtin-summary"
    assert "Summary" in doc.find("h1").get_text()
    assert doc.find("main")["data-read-only"] == "true"
    assert len(doc.select("#blocks > li")) == 4


def test_a_built_in_previews(client_v2, auth, fake_v2):
    r = client_v2.get("/api/p/alpha/builtin-layouts/builtin-summary/preview", headers=auth("victor"))
    assert r.status_code == 200 and fake_v2.snapshots[-1]["layout"]["id"] == "builtin-summary"


def test_the_new_layout_page_is_the_editor_with_nothing_saved(client_v2, auth):
    doc = _editor(client_v2, auth, "new")
    main = doc.find("main")
    assert main["data-page"] == "editor" and not main.get("data-layout")
    assert doc.find(attrs={"data-control": "delete-layout"}) is None
    assert doc.find(attrs={"data-control": "open-generate"}) is None
    assert doc.find(class_="toolbar").find("input", attrs={"name": "name"}).get("value", "") == ""


def test_a_viewer_cannot_open_the_new_layout_page(client_v2, auth):
    assert client_v2.get("/p/alpha/layouts/new", headers=auth("victor")).status_code == 403


def test_the_preview_with_choice_reaches_the_script(client_v2, auth):
    lay = new_layout(client_v2, auth, name="W")
    doc = _editor(client_v2, auth, f"{lay['id']}?system_id={IDS['A_V2']}&period_from=2026-09-10")
    pw = json.loads(doc.find("main")["data-preview-with"])
    assert pw["system_id"] == IDS["A_V2"] and pw["period_from"] == "2026-09-10"
    form = doc.find("form", attrs={"data-control": "preview-with"})
    assert form.find("select", attrs={"name": "system_id"}).find("option", selected=True)["value"] == IDS["A_V2"]


def test_the_reports_list_shows_what_each_report_covered(client_v2, auth):
    lay = new_layout(client_v2, auth, name="R", blocks=[v2blk("cover")])
    client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice"),
                   json={"system_id": IDS["A_V2"], "period_from": "2026-09-10", "period_to": "2026-09-12",
                         "other_versions": True})
    row = _editor(client_v2, auth, lay["id"]).select("table[data-reports] tbody tr")[0]
    cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
    assert "Version 2" in cells and "2026-09-10 to 2026-09-12" in cells and "Yes" in cells


def test_the_script_has_no_version_and_saves_a_new_layout_with_post():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "report_composer/static/composer.js").read_text()
    editor = js[js.index("// The editor"):]
    assert 'pick("version")' not in editor and 'pick("toc")' not in editor
    assert "show_index" in editor and "preview_with" in editor
    assert '"generate-docx"' not in editor and '"delete-layout"' in editor
