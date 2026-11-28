"""The layout editor: grouped palette, Index and Numbering, a
Preview with choice that is never saved, Generate as a link, Delete inside the editor, built-ins read-only.

The page is three columns under one sticky toolbar: the outline (one row per section, `#blocks >
li[data-instance-id]`, with the "+ Add a section" menu `details[data-palette]` above it), the inspector (one
body per section, `[data-body-for=<instance_id>]`, only the selected one shown) and the preview."""
import json
from pathlib import Path

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
    menu = doc.find(attrs={"data-palette": True})
    assert menu.name == "details" and menu.find_parent(attrs={"data-outline": True}) is not None
    assert menu.find("summary").get_text(strip=True) == "+ Add a section"
    assert labels[:6] == ["AI card", "Control objectives and checklists", "Tests run", "Results", "Summary", "Document"]
    tests_run = doc.select("[data-palette] .palette-group")[2]
    assert [b["data-add"] for b in tests_run.find_all("button")] == ["test_runs"]


def test_who_did_what_is_offered_under_summary(client_v2, auth):
    lay = new_layout(client_v2, auth, name="W")
    groups = {g.find("h3").get_text(strip=True): [b["data-add"] for b in g.find_all("button")]
              for g in _editor(client_v2, auth, lay["id"]).select("[data-palette] .palette-group")}
    assert "who_did_what" in groups["Summary"]


def test_the_toolbar_has_name_index_and_numbering_and_no_version(client_v2, auth):
    lay = new_layout(client_v2, auth, name="T", show_index=False)
    tb = _editor(client_v2, auth, lay["id"]).find(class_="toolbar")
    assert tb.find("input", attrs={"name": "name"})["value"] == "T"
    assert not tb.find("input", attrs={"name": "show_index", "type": "checkbox"}).has_attr("checked")
    assert tb.find("input", attrs={"name": "numbering", "type": "checkbox"}) is not None
    assert tb.find(attrs={"data-control": "version"}) is None and tb.find(attrs={"data-control": "toc"}) is None
    assert tb.find(attrs={"data-control": "open-generate"}) is None      # Download report sits next to Show
    assert tb.find(attrs={"data-control": "delete-layout"}) is not None


def test_delete_asks_first_with_the_one_dialog(client_v2, auth):
    lay = new_layout(client_v2, auth, name="D")
    doc = _editor(client_v2, auth, lay["id"])
    assert len(doc.find_all("dialog", attrs={"data-confirm": True})) == 1
    delete = doc.find(attrs={"data-control": "delete-layout"})
    assert delete.get("data-confirm-action") == "Delete layout"
    # The reports are kept (a soft delete; the dialog once said they were deleted)
    assert delete.get("data-confirm-text") == "Delete the layout D? Its generated reports stay, under Reports of deleted layouts."


def test_a_built_in_opens_read_only(client_v2, auth):
    doc = _editor(client_v2, auth, "builtin-summary")
    assert doc.find(attrs={"data-control": "save"}) is None and doc.find(attrs={"data-palette": True}) is None
    assert doc.find(attrs={"data-control": "delete-layout"}) is None
    assert doc.find(attrs={"data-control": "duplicate"})["data-layout"] == "builtin-summary"
    assert "Summary" in doc.find("h1").get_text()
    assert doc.find("main")["data-read-only"] == "true"
    assert len(doc.select("#blocks > li")) == 5


def test_a_built_in_previews(client_v2, auth, fake_v2):
    r = client_v2.get("/api/p/alpha/builtin-layouts/builtin-summary/preview", headers=auth("victor"))
    assert r.status_code == 200 and fake_v2.snapshots[-1]["layout"]["id"] == "builtin-summary"


def test_the_new_layout_page_is_the_editor_with_nothing_saved(client_v2, auth):
    doc = _editor(client_v2, auth, "new")
    main = doc.find("main")
    assert main["data-page"] == "editor" and not main.get("data-layout")
    assert doc.find(attrs={"data-control": "delete-layout"}) is None
    assert doc.find(attrs={"data-control": "download-report"}) is None   # nothing saved, nothing to download
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


CSS = Path(__file__).resolve().parents[1] / "report_composer/static/composer.css"


def test_only_the_editor_drops_the_page_width_cap(client_v2, auth):
    lay = new_layout(client_v2, auth, name="Wide")
    assert "wide" in _editor(client_v2, auth, lay["id"]).find(class_="rc-page")["class"]
    listing = soup(client_v2.get("/p/alpha/", headers=auth("alice")).text)
    assert "wide" not in listing.find(class_="rc-page")["class"]
    css = CSS.read_text()
    assert ".rc-page { max-width: 1320px;" in css and ".rc-page.wide { max-width: none; }" in css


def test_the_toolbar_holds_the_preview_choice_and_generate(client_v2, auth):
    lay = new_layout(client_v2, auth, name="Bar")
    doc = _editor(client_v2, auth, lay["id"])
    assert len(doc.find_all(class_="toolbar")) == 1
    tb = doc.find(class_="toolbar")
    form = tb.find("form", attrs={"data-control": "preview-with"})
    assert form is not None and form.get("method") == "get"
    for name in ("system_id", "period_from", "period_to", "other_versions"):
        assert form.find(attrs={"name": name}) is not None, name
    assert form.find("button", attrs={"type": "submit"}, string="Show") is not None
    menu = form.find(attrs={"data-control": "download-report"})
    assert menu is not None and "Generate and download" in menu.get_text()
    assert tb.find(attrs={"data-control": "save"}) is not None and tb.find(attrs={"data-state": True}) is not None
    assert doc.find(class_="preview").find("form") is None              # nothing left in the preview pane


def test_three_columns_outline_inspector_preview(client_v2, auth):
    lay = new_layout(client_v2, auth, name="Cols", blocks=[v2blk("cover"), v2blk("ai_card")])
    work = _editor(client_v2, auth, lay["id"]).find(class_="workspace")
    columns = [c for c in work.find_all(recursive=False) if c.name]
    assert [("outline" if c.has_attr("data-outline") else "inspector" if c.has_attr("data-inspector")
             else "preview" if "preview" in c.get("class", []) else c.name) for c in columns] == \
        ["outline", "inspector", "preview"]
    assert work.find("iframe", attrs={"sandbox": ""}) is not None


def test_each_section_has_one_body_in_the_inspector_and_the_first_is_selected(client_v2, auth):
    blocks = [v2blk("cover"), v2blk("ai_card", commentary="Held.")]
    lay = new_layout(client_v2, auth, name="Bodies", blocks=blocks)
    doc = _editor(client_v2, auth, lay["id"])
    rows = doc.select("#blocks > li[data-instance-id]")
    assert [r["data-instance-id"] for r in rows] == [b["instance_id"] for b in blocks]
    assert rows[0].get("aria-current") == "true" and rows[1].get("aria-current") is None
    assert all(r.get("tabindex") == "0" and r.find(attrs={"data-option": True}) is None for r in rows)
    inspector = doc.find(attrs={"data-inspector": True})
    bodies = inspector.select("[data-body-for]")
    assert [b["data-body-for"] for b in bodies] == [b["instance_id"] for b in blocks]
    assert not bodies[0].has_attr("hidden") and bodies[1].has_attr("hidden")
    assert bodies[1].find("textarea", attrs={"data-option": "commentary"}).get_text() == "Held."
    for control in ("move-up", "move-down", "remove"):     # act on the selected section
        assert inspector.find(attrs={"data-control": control}) is not None, control


def test_the_outline_rows_show_the_flags_python_computes(client_v2, auth, bed):
    from conftest import pdb_of

    empty, full, noted = v2blk("chapter", title="Empty"), v2blk("chapter", title="Full"), v2blk("ai_card", commentary="Done.")
    unwritten, broken = v2blk("free_text", text="Write this section."), v2blk("test_results")
    lay = new_layout(client_v2, auth, name="Flags", blocks=[empty, full, noted, unwritten, broken],
                     system_id=IDS["A_V2"])
    bed.psql(pdb_of("A"), "UPDATE report_composer.layout_block SET options = options || '{\"evaluations\": []}'"
                          f" WHERE instance_id = '{broken['instance_id']}'")
    doc = _editor(client_v2, auth, f"{lay['id']}?system_id={IDS['A_V2']}")

    def flags(b):
        row = doc.find("li", attrs={"data-instance-id": b["instance_id"]})
        return [(f["data-flag"], f.get_text(strip=True)) for f in row.select("[data-flag]")]

    assert flags(empty) == [("empty", "empty")]
    assert flags(full) == []
    assert flags(noted) == [("note", "note")]
    assert flags(unwritten) == [("to-write", "to write")]
    assert flags(broken) == [("problems", "problems")]


def test_the_outline_route_answers_noted_and_flags(client_v2, auth):
    noted = v2blk("ai_card", commentary="Done.")
    lay = new_layout(client_v2, auth, name="Noted", blocks=[noted])
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/outline", headers=auth("alice"),
                       json={"blocks": [noted]})
    entry = r.json()["outline"][0]
    assert entry["noted"] is True and [f["name"] for f in entry["flags"]] == ["note"]
