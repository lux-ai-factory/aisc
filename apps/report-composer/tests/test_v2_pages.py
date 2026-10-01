"""Screens of report run v2, drawn in Python (01-specs.md sections 2.3, 4.4, 6.3, 9.3, 11 to 15).

Markup hooks these tests assume (stage 4 implements them; documented in 02-tests.md):
- the coverage map is gone (evidence links 2026-09-30, D5): test_evidence_links.py pins its absence
- editor toolbar (no language control since part 2, R2-D1.9): buttons `[data-control=generate]` "Generate PDF" and
  `[data-control=generate-docx]` "Generate Word (DOCX)"
- outline: `li[data-instance-id][data-depth]` (1 inside a chapter, 0 otherwise)
- block form: `details[data-more]` "More options" (closed), `details[data-commentary]` "Add a commentary",
  fields with `data-show-if` (JSON) and `hidden` when hidden
- every page: `div[data-message][role=alert][aria-live=polite]` first in `main`, and one `dialog[data-confirm]`
- layouts page: `select[name=preset]` in the new-layout form, `[data-control=import-preset]`, per row
  `[data-control=duplicate|export-structure|save-preset|delete]`, a presets section with
  `[data-control=export-preset|delete-preset]`
"""
import json
import re
from pathlib import Path

import pytest

from conftest import IDS, new_layout, new_template, pdb_of
from test_v2_browser import live  # noqa: F401  (the browser fixture)
from v2_fakes import clean_presets, client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]
JS = Path(__file__).resolve().parents[1] / "report_composer/static/composer.js"
CSS = Path(__file__).resolve().parents[1] / "report_composer/static/composer.css"
HELP = "Light formatting: **bold**, *italic*, lists with - or 1., links [text](https://...), tables with |."


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def editor(client, auth, blocks, who="alice", **body):
    body.setdefault("system_id", IDS["A_V2"])
    lay = new_layout(client, auth, name=unique("Page"), blocks=blocks, **body)
    return lay, soup(client.get(f"/p/alpha/layouts/{lay['id']}?system_id={IDS['A_V2']}", headers=auth(who)).text)


def li_of(doc, iid):
    return doc.find("li", attrs={"data-instance-id": iid})


# ── R-U4.1 no select multiple anywhere ──────────────────────────────────────

def test_r_u4_1_no_select_multiple_on_any_page(client_v2, auth):
    new_template(client_v2, auth, name=unique("Look"))
    blocks = [v2blk(t) for t in ("cover", "control_objectives", "test_results", "control_answers", "key_figures",
                                 "changes_since", "summary_coverage")]
    lay, doc = editor(client_v2, auth, blocks)
    pages = [str(doc), client_v2.get("/p/alpha/", headers=auth("alice")).text,
             client_v2.get("/p/alpha/templates", headers=auth("alice")).text]
    for html in pages:
        assert not soup(html).find("select", attrs={"multiple": True})
    assert "None selected means all" not in str(doc)


# ── R-U4.2, R-U4.3 the all-or-list widget ───────────────────────────────────

def test_r_u4_2_all_or_list_radios_then_checkboxes(client_v2, auth):
    tests = v2blk("test_results", evaluations=[IDS["EVAL_A_V2"]])
    lay, doc = editor(client_v2, auth, [tests])
    field = li_of(doc, tests["instance_id"]).find(attrs={"data-field": "evaluations"})
    radios = field.find_all("input", attrs={"type": "radio"})
    labels = [r.find_parent("label").get_text(" ", strip=True) for r in radios]
    assert labels == ["All (also ones added later)", "Only these:"]
    assert radios[1].has_attr("checked")
    boxes = field.find_all("input", attrs={"type": "checkbox"})
    assert {b["value"] for b in boxes} == {IDS["EVAL_A_V2"], IDS["EVAL_A_V2_NOCONFIG"]}
    assert [b["value"] for b in boxes if b.has_attr("checked")] == [IDS["EVAL_A_V2"]]


def test_r_u4_3_a_stored_empty_list_shows_only_these_and_the_problem(client_v2, auth, bed):
    tests = v2blk("test_results")
    lay, _ = editor(client_v2, auth, [tests])
    bed.psql(pdb_of("A"), "UPDATE report_composer.layout_block SET options = options || '{\"evaluations\": []}'"
                          f" WHERE instance_id = '{tests['instance_id']}'")
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lay['id']}?system_id={IDS['A_V2']}", headers=auth("alice")).text)
    field = li_of(doc, tests["instance_id"]).find(attrs={"data-field": "evaluations"})
    assert field.find_all("input", attrs={"type": "radio"})[1].has_attr("checked")
    assert "Pick at least one, or choose All." in li_of(doc, tests["instance_id"]).get_text()


def test_r_u4_3_composer_js_says_pick_at_least_one():
    assert "Pick at least one, or choose All." in JS.read_text()


# ── R-U5.4 More options, R-V3.13 to R-V3.16 commentary ──────────────────────

def test_r_u5_4_more_options_are_a_closed_disclosure_at_the_end(client_v2, auth):
    tests = v2blk("test_results")
    lay, doc = editor(client_v2, auth, [tests])
    li = li_of(doc, tests["instance_id"])
    more = li.find("details", attrs={"data-more": True})
    assert more is not None and not more.has_attr("open")
    assert more.find("summary").get_text(strip=True) == "More options"
    assert more.find(attrs={"data-field": "show_artifacts"}) is not None
    assert more.find(attrs={"data-field": "evaluations"}) is None


def test_r_u5_3_help_lines_are_shown(client_v2, auth):
    kf = v2blk("key_figures")
    lay, doc = editor(client_v2, auth, [kf])
    assert "One tile per tool." in li_of(doc, kf["instance_id"]).get_text()


def test_r_v3_13_commentary_disclosure_closed_when_empty_open_when_set(client_v2, auth):
    empty, filled = v2blk("ai_card"), v2blk("cover", commentary="Read this first")
    lay, doc = editor(client_v2, auth, [empty, filled])
    for iid, is_open in ((empty["instance_id"], False), (filled["instance_id"], True)):
        d = li_of(doc, iid).find("details", attrs={"data-commentary": True})
        assert d is not None and d.find("summary").get_text(strip=True) == "Add a commentary"
        assert d.has_attr("open") is is_open
        area = d.find("textarea", attrs={"data-option": "commentary"})
        assert area is not None and area.get("rows") == "6"
    more = li_of(doc, empty["instance_id"]).find("details", attrs={"data-more": True})
    assert more.find(attrs={"data-field": "commentary_position"}) is not None
    assert "After the section" in more.get_text() and "Place the commentary" in more.get_text()


def test_r_v3_15_help_line_under_light_formatting_textareas(client_v2, auth):
    ai, md = v2blk("ai_card"), v2blk("free_text", text="x", format="markdown")
    lay, doc = editor(client_v2, auth, [ai, md])
    assert HELP in li_of(doc, ai["instance_id"]).find("details", attrs={"data-commentary": True}).get_text(" ", strip=True)
    assert HELP in li_of(doc, md["instance_id"]).find(attrs={"data-field": "text"}).get_text(" ", strip=True)


def test_r_v3_16_the_composer_never_interprets_markup(client_v2, auth):
    b = v2blk("cover", commentary="**bold** <b>raw</b>")
    lay, doc = editor(client_v2, auth, [b])
    area = li_of(doc, b["instance_id"]).find("textarea", attrs={"data-option": "commentary"})
    assert area is not None and area.get_text() == "**bold** <b>raw</b>"
    assert "<strong>bold" not in str(doc)


def test_r_v3_14_the_palette_adds_free_text_in_light_formatting(client_v2, auth):
    lay, doc = editor(client_v2, auth, [v2blk("cover")])
    tpl = doc.find("template", attrs={"data-block-template": "free_text"})
    assert tpl is not None
    inner = soup(tpl.decode_contents())
    fmt = inner.find(attrs={"data-option": "format"})
    assert fmt is not None
    chosen = fmt.find("option", selected=True)
    assert chosen is not None and chosen["value"] == "markdown"


def test_r_u5_2_the_palette_shows_block_descriptions(client_v2, auth):
    lay, doc = editor(client_v2, auth, [v2blk("cover")])
    palette = doc.find(attrs={"data-control": "palette"})
    assert "A chart drawn in the report." in palette.get_text()


# ── R-V4.15 fields shown per value ──────────────────────────────────────────

def test_r_v4_15_show_if_fields_are_drawn_hidden(client_v2, auth):
    chart = v2blk("chart", dataset="coverage_status")
    lay, doc = editor(client_v2, auth, [chart])
    field = li_of(doc, chart["instance_id"]).find(attrs={"data-field": "tool_chart"})
    assert field is not None and json.loads(field.get("data-show-if") or "null") == {"dataset": ["tool_chart"]}
    assert field.has_attr("hidden")


def test_r_v4_15_composer_js_toggles_from_the_annotation_and_skips_hidden_fields():
    js = JS.read_text()
    assert "data-show-if" in js or "showIf" in js, "missing feature: show-if toggling in composer.js"
    assert "hidden" in js


# ── R-V5.8, R-V5.9 chapters in the outline ──────────────────────────────────

def test_r_v5_9_blocks_inside_a_chapter_are_indented(client_v2, auth):
    blocks = [v2blk("cover"), v2blk("ai_card"), v2blk("chapter", title="Evidence"), v2blk("test_results"),
              v2blk("control_answers"), v2blk("appendix"), v2blk("free_text", text="x")]
    lay, doc = editor(client_v2, auth, blocks)
    depths = [li_of(doc, b["instance_id"]).get("data-depth") for b in blocks]
    assert depths == ["0", "0", "0", "1", "1", "0", "0"]


def test_r_v5_8_an_empty_chapter_is_a_hint_not_an_error(client_v2, auth):
    ch = v2blk("chapter", title="Nothing here")
    lay, doc = editor(client_v2, auth, [v2blk("cover"), ch, v2blk("chapter", title="Next"), v2blk("ai_card")])
    assert "This chapter is empty." in li_of(doc, ch["instance_id"]).get_text()
    assert client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/validate", headers=auth("alice")).json()["valid"] is True


# ── R-V8.14 two generate buttons (the language select is gone: R2-D1.9, test_p2_english_only.py) ──

def test_r_v8_14_pdf_or_word_on_the_generate_page(client_v2, auth):
    """Report modules 2026-09-28: the two Generate buttons became a format choice on the Generate page."""
    lay, _ = editor(client_v2, auth, [v2blk("cover")])
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lay['id']}/generate", headers=auth("alice")).text)
    labels = [r.parent.get_text(strip=True) for r in doc.find_all("input", attrs={"name": "format"})]
    assert labels == ["PDF", "Word (DOCX)"]


def test_r_v8_16_the_composer_screens_stay_in_english(client_v2, auth):
    lay, doc = editor(client_v2, auth, [v2blk("cover")])
    assert doc.find("html").get("lang") == "en"


# ── R-U6.2, R-U6.3, R-U6.4 the platform default look ────────────────────────

def test_r_u6_2_template_select_starts_with_platform_default(client_v2, auth):
    lay, doc = editor(client_v2, auth, [v2blk("cover")], template_id=None)
    sel = doc.find(attrs={"data-control": "template"})
    first = sel.find("option")
    assert first["value"] == "" and first.get_text(strip=True) == "Platform default" and first.has_attr("selected")


def test_r_u6_3_create_is_never_disabled_for_lack_of_a_template(client_v2, auth):
    doc = soup(client_v2.get("/p/alpha/", headers=auth("alice")).text)     # clean_layouts: no template
    new = doc.find(attrs={"data-control": "start-new-layout"})
    assert new is not None and not new.has_attr("disabled") and not new.has_attr("aria-disabled")


def test_r_u6_4_a_deleted_template_shows_platform_default(client_v2, auth):
    t = new_template(client_v2, auth, name=unique("Going"))
    lay = new_layout(client_v2, auth, name=unique("Orphan"), system_id=IDS["A_V2"], template_id=t["id"],
                     blocks=[v2blk("cover")])
    client_v2.delete(f"/api/p/alpha/templates/{t['id']}", headers=auth("alice"))
    sel = soup(client_v2.get(f"/p/alpha/layouts/{lay['id']}?system_id={IDS['A_V2']}", headers=auth("alice")).text).find(
        attrs={"data-control": "template"})
    assert sel.find("option", selected=True).get_text(strip=True) == "Platform default"


# ── R-U7 no alert or confirm ────────────────────────────────────────────────

def test_r_u7_1_no_alert_confirm_or_prompt_in_composer_js():
    js = JS.read_text()
    for call in ("alert(", "confirm(", "prompt("):
        assert not re.search(r"(?<![\w.])" + re.escape(call), js), call


@pytest.mark.parametrize("page", ["/p/alpha/", "/p/alpha/templates", "editor"])
def test_r_u7_2_every_page_has_one_message_region_first_in_main(client_v2, auth, page):
    if page == "editor":
        lay = new_layout(client_v2, auth, name=unique("Msg"), system_id=IDS["A_V2"], blocks=[v2blk("cover")])
        page = f"/p/alpha/layouts/{lay['id']}"
    doc = soup(client_v2.get(page, headers=auth("alice")).text)
    regions = doc.find_all(attrs={"data-message": True})
    assert len(regions) == 1
    r = regions[0]
    assert r.get("role") == "alert" and r.get("aria-live") == "polite"
    assert doc.find("main").find(True) is r


def test_r_u7_3_composer_js_uses_the_dialog():
    js = JS.read_text()
    assert "data-confirm" in js and ("showModal" in js or ".show(" in js)


def test_r_u7_4_leaving_with_unsaved_changes_asks_the_browser():
    assert "beforeunload" in JS.read_text()


# ── 2.3 presets on the layouts page ─────────────────────────────────────────

@pytest.mark.usefixtures("clean_presets")
def test_r_v1_screens_row_menu_editor_and_viewer(client_v2, auth):
    new_layout(client_v2, auth, name=unique("Row"), system_id=IDS["A_V2"], blocks=[v2blk("cover")])
    ed = soup(client_v2.get("/p/alpha/", headers=auth("alice")).text)
    for control in ("open-layout", "duplicate", "export-structure"):
        assert ed.find(attrs={"data-control": control}) is not None, control
    vi = soup(client_v2.get("/p/alpha/", headers=auth("victor")).text)
    assert vi.find(attrs={"data-control": "export-structure"}) is not None
    assert vi.find(attrs={"data-control": "duplicate"}) is None


@pytest.mark.usefixtures("clean_presets")
# ── fix round 1 (05-verify note 6): the outline after a move comes from Python ──

def test_fix_outline_route_gives_depth_and_empty_chapter_for_any_order(client_v2, auth):
    cover, chapter, card = v2blk("cover"), v2blk("chapter", title="Evidence"), v2blk("ai_card")
    lay, _ = editor(client_v2, auth, [cover, chapter, card])
    order = [cover, card, chapter]
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/outline",
                       json={"blocks": [{"instance_id": b["instance_id"], "block_type": b["block_type"]}
                                        for b in order]}, headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert r.json() == {"outline": [
        {"instance_id": cover["instance_id"], "depth": 0, "empty_chapter": False, "unwritten": [],
         "unwritten_hint": None, "number": ""},
        {"instance_id": card["instance_id"], "depth": 0, "empty_chapter": False, "unwritten": [],
         "unwritten_hint": None, "number": ""},
        {"instance_id": chapter["instance_id"], "depth": 0, "empty_chapter": True, "unwritten": [],
         "unwritten_hint": None, "number": ""}]}


def test_fix_outline_route_is_for_editors_and_checks_its_input(client_v2, auth):
    lay, _ = editor(client_v2, auth, [v2blk("cover")])
    url = f"/api/p/alpha/layouts/{lay['id']}/outline"
    assert client_v2.post(url, json={"blocks": "x"}, headers=auth("alice")).status_code == 422
    assert client_v2.post(url, json={"blocks": []}, headers=auth("victor")).status_code in (403, 404)


# ── fix round 2, item 4: the outline route keeps the layouts' block limit ─────

def test_fix_r2_4_outline_route_refuses_more_blocks_than_a_layout_holds(client_v2, auth):
    from conftest import error_code

    lay, _ = editor(client_v2, auth, [v2blk("cover")])
    url = f"/api/p/alpha/layouts/{lay['id']}/outline"
    blocks = [{"instance_id": f"id-{i}", "block_type": "chapter"} for i in range(51)]
    r = client_v2.post(url, json={"blocks": blocks}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "too_many_blocks", r.text[:300]
    assert r.json()["error"]["details"][0]["pointer"] == "/blocks"
    r = client_v2.post(url, json={"blocks": blocks[:50]}, headers=auth("alice"))
    assert r.status_code == 200 and len(r.json()["outline"]) == 50


# ── 2026-10-01: the outline shows the report's numbers (1, 1.1, A), not the block's position ──

def test_outline_route_gives_the_report_number_when_numbering_is_on(client_v2, auth):
    cover, chapter, card = v2blk("cover"), v2blk("chapter", title="Evidence"), v2blk("ai_card")
    lay, _ = editor(client_v2, auth, [cover, chapter, card])
    url = f"/api/p/alpha/layouts/{lay['id']}/outline"
    blocks = [{"instance_id": b["instance_id"], "block_type": b["block_type"]} for b in (cover, chapter, card)]
    on = client_v2.post(url, json={"blocks": blocks, "numbering": True}, headers=auth("alice")).json()
    assert [o["number"] for o in on["outline"]] == ["", "1", "1.1"]
    off = client_v2.post(url, json={"blocks": blocks, "numbering": False}, headers=auth("alice")).json()
    assert [o["number"] for o in off["outline"]] == ["", "", ""]
    assert client_v2.post(url, json={"blocks": blocks, "numbering": "yes"}, headers=auth("alice")).status_code == 422


def test_editor_page_draws_the_report_numbers(client_v2, auth):
    blocks = [v2blk("cover"), v2blk("chapter", title="System"), v2blk("ai_card"), v2blk("appendix"),
              v2blk("free_text", text="x")]
    lay, doc = editor(client_v2, auth, blocks, numbering=True)
    assert [li_of(doc, b["instance_id"]).get("data-number") for b in blocks] == ["", "1", "1.1", "", "A"]
    lay, doc = editor(client_v2, auth, blocks, numbering=False)
    assert [li_of(doc, b["instance_id"]).get("data-number") for b in blocks] == [""] * 5


def test_the_outline_no_longer_counts_blocks_in_css():
    css = CSS.read_text(encoding="utf-8")
    assert "counter(block)" not in css and "attr(data-number)" in css
