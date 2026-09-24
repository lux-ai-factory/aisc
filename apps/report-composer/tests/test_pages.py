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
    for control in ("new-template", "import-template", "export-template", "delete-template", "edit-template"):
        assert doc.find(attrs={"data-control": control}) is not None, control


def test_a_viewer_sees_templates_but_cannot_change_them(client, auth):
    from conftest import new_template

    new_template(client, auth, name="Bank X")
    doc = soup(client.get("/p/alpha/templates", headers=auth("victor")).text)
    assert "Bank X" in doc.get_text()
    assert doc.find(attrs={"data-control": "export-template"}) is not None
    for control in ("new-template", "import-template", "delete-template", "edit-template"):
        assert doc.find(attrs={"data-control": control}) is None, control


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
