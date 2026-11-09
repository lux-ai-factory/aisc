"""The Exported results section's comment boxes in the editor: one per block of the results dashboard, shown
while the section lists that block, saved into the layout's options and sent with the draft preview."""
import pytest

import v2_fakes
from conftest import IDS
from test_v2_browser import _li, live  # noqa: F401
from v2_fakes import ALL_OR_LIST, _p, _type, client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

EXPORTS = _type("superset_exports", "Exported results", {
    "dashboards": _p({**ALL_OR_LIST, "x-aisc-section-per-choice": True}, "Tools",
                     "Which tools of the results dashboard to show.", **{"x-aisc-reference": True}),
    "comments": _p({"type": "object", "additionalProperties": {"type": "string", "maxLength": 10000,
                                                               "x-aisc-prose": True}},
                   "Comment per block", "Your own words about a block, printed under its heading.",
                   **{"x-aisc-per-choice-of": "dashboards"}),
}, {"dashboards": "all", "comments": {}})


@pytest.fixture
def exports_type(monkeypatch):
    """The fake renderer also knows the Exported results block, with two blocks of the results dashboard."""
    monkeypatch.setattr(v2_fakes, "BLOCK_TYPES_V2", v2_fakes.BLOCK_TYPES_V2 + [EXPORTS])
    monkeypatch.setitem(v2_fakes.BY_TYPE_V2, "superset_exports", EXPORTS)
    monkeypatch.setitem(v2_fakes.CHOICES_V2, (IDS["A_V2"], "superset_exports"), {"dashboards": [
        {"value": "12", "label": "LangBiTe (Mijke)"}, {"value": "14", "label": "StrongREJECT (Mijke)"}]})


def test_one_comment_box_per_listed_block_saved_and_previewed(exports_type, live, client_v2, auth, fake_v2,
                                                             monkeypatch):
    block = v2blk("superset_exports", dashboards=["12"], comments={"99": "Of a block gone"})
    page, lay = live([v2blk("cover"), block])
    _li(page, block["instance_id"]).click()
    form = page.locator(f'[data-inspector] [data-body-for="{block["instance_id"]}"]')
    boxes = form.locator('fieldset[data-option="comments"] [data-choice-box]')
    assert boxes.count() == 2
    assert boxes.nth(0).is_visible() and not boxes.nth(1).is_visible()
    assert "LangBiTe (Mijke)" in boxes.nth(0).inner_text()

    form.locator('textarea[data-choice="12"]').fill("Bias held.\nSecond line")
    form.locator('fieldset[data-option="dashboards"] input[value="14"]').check()      # both checked: "all"
    boxes.nth(1).wait_for(state="visible", timeout=5000)
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/preview"), timeout=5000):
        page.click('[data-control="refresh-preview"]')
    page.wait_for_function("() => document.querySelector('main iframe').srcdoc.includes('superset_exports')",
                           timeout=5000)
    sent = [b for s in fake_v2.snapshots if s["mode"] == "preview" for b in s["blocks"]
            if b["instance_id"] == block["instance_id"]]
    assert sent[-1]["options"]["comments"] == {"99": "Of a block gone", "12": "Bias held.\nSecond line"}

    page.click('.toolbar [data-control="save"]')
    page.locator("[data-state]").filter(has_text="Saved (revision 2)").wait_for(timeout=5000)
    monkeypatch.setenv("PLATFORM_ORIGIN", "http://localhost")
    saved = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    options = next(b["options"] for b in saved["blocks"] if b["instance_id"] == block["instance_id"])
    assert options["dashboards"] == "all"
    assert options["comments"] == {"99": "Of a block gone", "12": "Bias held.\nSecond line"}


def parts_shown(page, iid):
    return page.locator(f'#blocks > li[data-instance-id="{iid}"] [data-parts] [data-part]').evaluate_all(
        "els => els.map(e => [e.dataset.number, e.textContent.trim()])")


def test_every_tool_checked_by_default_and_listed_numbered_in_the_outline(exports_type, live, fake_v2):
    chapter, block, after = v2blk("chapter", title="Tests"), v2blk("superset_exports"), v2blk("ai_card")
    page, _ = live([v2blk("cover"), chapter, block, after], numbering=True)
    _li(page, block["instance_id"]).click()
    form = page.locator(f'[data-inspector] [data-body-for="{block["instance_id"]}"]')
    tools = form.locator('fieldset[data-option="dashboards"] .choices input[type="checkbox"]')
    assert tools.count() == 2 and tools.nth(0).is_checked() and tools.nth(1).is_checked()
    assert form.locator('fieldset[data-option="dashboards"] input[type="radio"]').count() == 0
    commentary_box = form.locator("[data-commentary]")
    assert "Commentary: LangBiTe (Mijke)" in commentary_box.inner_text()
    assert parts_shown(page, block["instance_id"]) == [["1.1", "LangBiTe (Mijke)"], ["1.2", "StrongREJECT (Mijke)"]]
    assert _li(page, after["instance_id"]).get_attribute("data-number") == "1.3"

    tools.nth(0).uncheck()                                          # LangBiTe left out
    boxes = commentary_box.locator("[data-choice-box]")
    assert not boxes.nth(0).is_visible() and boxes.nth(1).is_visible()
    page.wait_for_function(
        f"() => document.querySelector('#blocks > li[data-instance-id=\"{after['instance_id']}\"]').dataset.number"
        " === '1.2'", timeout=5000)
    assert parts_shown(page, block["instance_id"]) == [["1.1", "StrongREJECT (Mijke)"]]
    with page.expect_request(lambda r: r.method == "POST" and r.url.endswith("/preview"), timeout=5000):
        page.click('[data-control="refresh-preview"]')
    def sent():
        return [b["options"].get("dashboards") for s in fake_v2.snapshots if s["mode"] == "preview"
                for b in s["blocks"] if b["instance_id"] == block["instance_id"]]

    for _ in range(50):                                             # the request reaches the fake renderer
        if sent() and sent()[-1] == ["14"]:
            break
        page.wait_for_timeout(100)
    assert sent()[-1] == ["14"]


def test_the_editor_page_lists_the_tools_numbered_under_the_section(exports_type, client_v2, auth):
    from test_v2_pages import editor, li_of

    chapter, block, after = v2blk("chapter", title="Tests"), v2blk("superset_exports", dashboards=["14"]), v2blk("ai_card")
    _, doc = editor(client_v2, auth, [chapter, block, after], numbering=True)
    row = li_of(doc, block["instance_id"])
    assert [(p["data-number"], p.get_text(strip=True)) for p in row.select("[data-parts] [data-part]")] == [
        ("1.1", "StrongREJECT (Mijke)")]
    assert row["data-number"] == "" and li_of(doc, after["instance_id"])["data-number"] == "1.2"


def test_the_outline_route_numbers_the_tools_it_is_told_of(exports_type, client_v2, auth):
    from test_v2_pages import editor

    chapter, block, after = v2blk("chapter", title="Tests"), v2blk("superset_exports"), v2blk("ai_card")
    lay, _ = editor(client_v2, auth, [chapter, block, after])
    url = f"/api/p/alpha/layouts/{lay['id']}/outline"
    body = {"blocks": [chapter, block, after], "numbering": True,
            "parts": {block["instance_id"]: ["LangBiTe (Mijke)", "StrongREJECT (Mijke)"]}}
    got = client_v2.post(url, json=body, headers=auth("alice")).json()["outline"]
    assert [o["number"] for o in got] == ["1", "", "1.3"]
    assert got[1]["parts"] == [{"title": "LangBiTe (Mijke)", "number": "1.1"},
                               {"title": "StrongREJECT (Mijke)", "number": "1.2"}]
    for bad in ({"x": "y"}, ["x"], {block["instance_id"]: [3]}):
        assert client_v2.post(url, json={**body, "parts": bad}, headers=auth("alice")).status_code == 422


def test_a_new_section_has_every_tool_checked_and_listed(exports_type, live):
    page, _ = live([v2blk("cover"), v2blk("ai_card")], numbering=True)
    page.click("details[data-palette] > summary")
    page.click('[data-add="superset_exports"]')
    iid = page.locator("#blocks > li").last.get_attribute("data-instance-id")
    form = page.locator(f'[data-inspector] [data-body-for="{iid}"]')
    tools = form.locator('fieldset[data-option="dashboards"] .choices input[type="checkbox"]')
    assert tools.count() == 2 and tools.nth(0).is_checked() and tools.nth(1).is_checked()
    page.wait_for_function(f"() => document.querySelectorAll('#blocks > li[data-instance-id=\"{iid}\"] [data-part]')"
                           ".length === 2", timeout=5000)
    assert parts_shown(page, iid) == [["2", "LangBiTe (Mijke)"], ["3", "StrongREJECT (Mijke)"]]
