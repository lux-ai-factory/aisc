"""Server-rendered screens (report run 2026-09-23: R4.1.1, R4.2.1, R4.2.2, R4.2.6, R7.3.4).
The frontend is one small script; what is on the page is decided in Python."""
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


# R4.2.1
def test_r4_2_1_layouts_list(client, auth):
    new_layout(client, auth, name="Board pack", system_id=IDS["A_V2"])
    page = client.get("/p/alpha/", headers=auth("alice"))
    assert page.status_code == 200
    t = page.text
    assert "Board pack" in t and "New layout" in t and "Delete" in t
    assert "New from template" not in t          # templates are looks now, not block recipes


# R4.2.6
def test_r4_2_6_a_viewer_sees_no_edit_controls(client, auth):
    lay = new_layout(client, auth, name="Viewed", system_id=IDS["A_V2"], blocks=[blk("free_text", text="x")])
    listing = client.get("/p/alpha/", headers=auth("victor")).text
    assert "Viewed" in listing and "New layout" not in listing and "Delete" not in listing
    editor = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("victor")).text)
    for control in ("palette", "save", "generate", "template", "move-up", "move-down", "remove", "configure"):
        assert editor.find(attrs={"data-control": control}) is None, control
    assert editor.find("iframe") is not None                        # preview is available


# R4.2.2
def test_r4_2_2_the_editor(client, auth):
    lay = new_layout(client, auth, name="Edited", system_id=IDS["A_V2"],
                     blocks=[blk("cover"), blk("dashboard_chart", chart_id=33)])
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text)
    palette = doc.find(attrs={"data-control": "palette"})
    assert palette is not None and "free_text" in str(palette)
    for control in ("save", "generate", "move-up", "move-down", "remove", "configure", "version", "template"):
        assert doc.find(attrs={"data-control": control}) is not None, control
    blocks = [el["data-instance-id"] for el in doc.find_all(attrs={"data-instance-id": True})]
    assert blocks == [b["instance_id"] for b in lay["blocks"]]
    version = doc.find(attrs={"data-control": "version"})
    assert [o.get_text(strip=True) for o in version.find_all("option")][:1] and "3" in version.get_text()
    # the configure form of the chart block offers the project's charts (R1.13 via the renderer)
    assert "Bias rate by version" in str(doc)


# R7.3.4
def test_r7_3_4_the_preview_iframe_is_sandboxed_without_scripts(client, auth):
    lay = new_layout(client, auth, name="Framed", system_id=IDS["A_V2"], blocks=[blk("free_text", text="x")])
    iframe = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text).find("iframe")
    assert iframe is not None and iframe.has_attr("sandbox")
    assert "allow-scripts" not in iframe["sandbox"]


# R4.1.1: one small script, no logic of its own
def test_r4_1_1_one_small_script(client, auth):
    lay = new_layout(client, auth, name="Scripted", system_id=IDS["A_V2"])
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text)
    scripts = [s.get("src") for s in doc.find_all("script") if s.get("src")]
    assert len(scripts) == 1 and scripts[0].endswith("composer.js")
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "report_composer/static/composer.js"
    assert js.exists() and len(js.read_text().splitlines()) < 500


# R7.3.3: the composer reads no module schema
def test_r7_3_3_the_composer_code_names_no_module_schema():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "report_composer"
    code = "\n".join(p.read_text() for p in root.rglob("*.py"))
    assert len(list(root.rglob("*.py"))) > 1, "missing feature: report_composer has no code yet"
    for schema in ("qualification.", "control_objectives.", "engine.", "controls.", "aisc_comment", "catalogue"):
        assert schema not in code, schema


# templates are chosen per layout, and live on their own screen
def test_the_editor_offers_the_projects_templates_with_the_saved_one_selected(client, auth):
    from conftest import new_template

    a = new_template(client, auth, name="Plain")
    b = new_template(client, auth, name="Bank X")
    lay = new_layout(client, auth, name="Picked", system_id=IDS["A_V2"], template_id=b["id"])
    doc = soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text)
    select = doc.find(attrs={"data-control": "template"})
    options = {o["value"]: o.get_text(strip=True) for o in select.find_all("option") if o.get("value")}
    assert options == {a["id"]: "Plain", b["id"]: "Bank X"}
    assert select.find("option", selected=True)["value"] == b["id"]


def test_the_new_layout_form_asks_for_a_template(client, auth):
    from conftest import new_template

    new_template(client, auth, name="Plain")
    doc = soup(client.get("/p/alpha/", headers=auth("alice")).text)
    form = doc.find(attrs={"data-control": "new-layout"})
    assert form.find("select", attrs={"name": "template_id"}) is not None


def test_the_templates_screen(client, auth):
    from conftest import new_template

    new_template(client, auth, name="Bank X", primary_color="#123456")
    page = client.get("/p/alpha/templates", headers=auth("alice"))
    assert page.status_code == 200
    doc = soup(page.text)
    assert "Bank X" in doc.get_text() and "#123456" in page.text
    for control in ("start-new-template", "import-template", "export-template", "open-template"):
        assert doc.find(attrs={"data-control": control}) is not None, control


# 2026-09-28, the user: one editor for new templates, reopened ones and just-imported ones, laid out by
# good practice: the page's actions in its header, the editor only while it is used, beside the list.
def _editors(doc):
    return doc.find_all("form", attrs={"data-control": ["new-template", "edit-template"]})


def _page(client, auth, query="", who="alice"):
    return soup(client.get(f"/p/alpha/templates{query}", headers=auth(who)).text)


def test_new_and_import_are_the_pages_actions_in_its_header(client, auth):
    doc = _page(client, auth)
    actions = doc.find(class_="rc-header").find(class_="page-actions")
    new = actions.find("a", attrs={"data-control": "start-new-template"})
    assert new.get_text(strip=True) == "New template"
    assert new["href"].endswith("/p/alpha/templates?new=1")
    imp = actions.find("form", attrs={"data-control": "import-template"})
    assert imp.find("input", attrs={"type": "file", "name": "file"}) is not None
    assert "Import from file" in imp.get_text()
    assert imp.find("button") is None                          # picking the file is the import


def test_the_list_alone_has_no_editor(client, auth):
    from conftest import new_template

    new_template(client, auth, name="Bank X")
    doc = _page(client, auth)
    assert _editors(doc) == [] and doc.find(id="template-editor") is None
    assert "with-editor" not in doc.find(class_="templates-workspace")["class"]


def test_new_opens_the_one_editor_empty(client, auth):
    from conftest import new_template

    new_template(client, auth, name="Bank X")
    doc = _page(client, auth, "?new=1")
    editors = _editors(doc)
    assert len(editors) == 1 and editors[0]["data-control"] == "new-template"
    name = editors[0].find("input", attrs={"name": "name"})
    assert name.get("value") == "" and name.has_attr("autofocus")       # a new template starts at its name
    assert editors[0].find_parent(id="template-editor") is not None
    assert "with-editor" in doc.find(class_="templates-workspace")["class"]
    assert editors[0].find("button", attrs={"type": "submit"}).get_text(strip=True) == "Create template"
    cancel = editors[0].find("a", attrs={"data-control": "cancel-template"})
    assert cancel.get_text(strip=True) == "Cancel" and cancel["href"].endswith("/p/alpha/templates")
    assert editors[0].find(attrs={"data-control": "delete-template"}) is None


def test_edit_on_a_card_opens_that_template_in_the_one_editor(client, auth):
    from conftest import new_template

    x = new_template(client, auth, name="Bank X")
    new_template(client, auth, name="Bank Y")
    doc = _page(client, auth)
    card = doc.find("article", attrs={"data-template": x["id"]})
    link = card.find("a", attrs={"data-control": "open-template"})
    assert link["href"].endswith(f"/p/alpha/templates?edit={x['id']}")
    assert card.find("form") is None                           # no editor inside a card
    assert card.find(attrs={"data-control": "delete-template"}) is None   # deleting is done in the editor

    doc = _page(client, auth, f"?edit={x['id']}")
    editors = _editors(doc)
    assert len(editors) == 1
    assert editors[0]["data-control"] == "edit-template" and editors[0]["data-template"] == x["id"]
    assert editors[0].find("input", attrs={"name": "name"})["value"] == "Bank X"
    assert not editors[0].find("input", attrs={"name": "name"}).has_attr("autofocus")
    assert "Bank X" in doc.find(id="template-editor").find("h2").get_text()
    assert editors[0].find("button", attrs={"type": "submit"}).get_text(strip=True) == "Save changes"
    assert editors[0].find("a", attrs={"data-control": "cancel-template"}) is not None
    delete = editors[0].find("button", attrs={"data-control": "delete-template"})
    assert delete["data-template"] == x["id"] and delete["type"] == "button"
    assert "editing" in doc.find("article", attrs={"data-template": x["id"]})["class"]


def test_an_unknown_template_to_edit_opens_no_editor(client, auth):
    assert _editors(_page(client, auth, "?edit=nope")) == []


def test_no_templates_yet_points_to_the_two_actions_once(client, auth):
    doc = _page(client, auth)
    empty = doc.find(class_="empty-state")
    assert empty is not None and "No templates yet" in empty.get_text()
    assert "New template" in empty.get_text() and "import a file" in empty.get_text()
    assert len(doc.find_all(attrs={"data-control": "start-new-template"})) == 1     # the header's, not twice
    assert empty.find(["a", "button", "label"]) is None
    empty = _page(client, auth, "?new=1").find(class_="empty-state")
    assert "New template" not in empty.get_text()                  # while creating, no pointer to it


def test_the_page_script_opens_created_and_imported_templates_and_leaves_after_delete():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "report_composer/static/composer.js").read_text()
    templates = js[js.index('if (main.dataset.page === "templates")'):js.index("// The editor")]
    assert "openInEditor(res.data.id)" in templates
    assert 'location.pathname + "?edit=" + encodeURIComponent(id)' in templates
    assert "requestSubmit()" in templates                      # a picked file imports at once
    assert "location.href = location.pathname" in templates     # after a delete, back to the list


def test_a_viewer_sees_templates_but_cannot_change_them(client, auth):
    from conftest import new_template

    new_template(client, auth, name="Bank X")
    doc = _page(client, auth, who="victor")
    assert "Bank X" in doc.get_text()
    assert doc.find(attrs={"data-control": "export-template"}) is not None
    for control in ("start-new-template", "new-template", "import-template", "delete-template", "edit-template",
                    "open-template"):
        assert doc.find(attrs={"data-control": control}) is None, control
    assert _editors(_page(client, auth, "?new=1", who="victor")) == []


def test_the_header_links_the_templates(client, auth):
    doc = soup(client.get("/p/alpha/", headers=auth("alice")).text)
    assert doc.find("a", href=lambda h: h and h.endswith("/p/alpha/templates")) is not None


# Generate PDF: the feedback is next to the button and the finished PDF downloads at once
# (it used to go to the "Generated reports" card below the preview, off screen, then reload)
def test_generate_answers_next_to_the_button_and_downloads_the_pdf():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "report_composer/static/composer.js").read_text()
    start = js.index('what === "generate"')
    handler = js[start:js.index("} else if", start + 1) if "} else if" in js[start + 1:] else len(js)]
    assert "[data-state]" in handler or "state.textContent" in handler, "status must show next to the button"
    assert '"/download"' in handler and ".download" in handler and ".click()" in handler, "a finished PDF must download"
    assert "location.reload" not in handler
