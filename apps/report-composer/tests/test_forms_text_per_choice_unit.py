"""An option holding one text per choice of another option (`x-aisc-per-choice-of`), as the Exported results
block's `comments`: one comment box per block of the results dashboard, labelled with the block's title."""
import json
from html.parser import HTMLParser

from conftest import need

SCHEMA = {"type": "object", "properties": {
    "dashboards": {"title": "Blocks", "x-aisc-reference": True,
                   "oneOf": [{"const": "all"}, {"type": "array", "items": {"type": "string", "minLength": 1}}]},
    "comments": {"title": "Comment per block", "description": "Printed under the block's heading.",
                 "type": "object", "additionalProperties": {"type": "string", "maxLength": 10000, "x-aisc-prose": True},
                 "x-aisc-per-choice-of": "dashboards"},
}}
CHOICES = {"dashboards": [{"value": "12", "label": "LangBiTe (Mijke)"},
                          {"value": "14", "label": "StrongREJECT <Mijke> & co"}]}


def fields(values, choices=CHOICES):
    return {f["name"]: f for f in need("report_composer.forms", "form_fields")(SCHEMA, values, choices)}


def test_one_box_per_choice_labelled_with_its_title_and_holding_its_text():
    f = fields({"dashboards": "all", "comments": {"14": "Held."}})["comments"]
    assert f["widget"] == "text-per-choice" and f["kind"] == "text-map" and f["per_choice_of"] == "dashboards"
    assert [(o["value"], o["label"], o["text"], o["hidden"]) for o in f["options"]] == [
        ("12", "Commentary: LangBiTe (Mijke)", "", False), ("14", "Commentary: StrongREJECT <Mijke> & co", "Held.", False)]


def test_only_the_blocks_the_section_lists_get_a_visible_box():
    f = fields({"dashboards": ["14"], "comments": {}})["comments"]
    assert [(o["value"], o["hidden"]) for o in f["options"]] == [("12", True), ("14", False)]


def test_texts_of_blocks_not_offered_are_kept_aside():
    f = fields({"dashboards": "all", "comments": {"12": "Shown", "99": "Of a block gone"}})["comments"]
    assert f["kept"] == {"99": "Of a block gone"}
    assert fields({"dashboards": "all", "comments": {"12": "x"}}, choices={})["comments"]["kept"] == {"12": "x"}


def test_an_older_layout_without_the_option_gets_empty_boxes():
    f = fields({"dashboards": "all"})["comments"]
    assert [o["text"] for o in f["options"]] == ["", ""] and f["kept"] == {}


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.text = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def drawn(values, choices=CHOICES):
    from report_composer.jinja_env import env

    html = env.from_string('{% from "_form.html.j2" import render_form %}{{ render_form(fields) }}').render(
        fields=list(fields(values, choices).values()))
    parser = Tags()
    parser.feed(html)
    return html, parser


def test_the_form_draws_one_labelled_textarea_per_block():
    html, p = drawn({"dashboards": ["12"], "comments": {"12": 'A "quoted" <b>text</b>', "99": "kept"}})
    sets = [a for tag, a in p.tags if tag == "fieldset" and a.get("data-kind") == "text-map"]
    assert len(sets) == 1 and sets[0]["data-option"] == "comments" and sets[0]["data-per-choice-of"] == "dashboards"
    assert json.loads(sets[0]["data-value"]) == {"99": "kept"}
    boxes = [a for tag, a in p.tags if tag == "textarea" and "data-choice" in a]
    assert [b["data-choice"] for b in boxes] == ["12", "14"]
    assert "data-option" not in boxes[0]                       # the fieldset is the option, not each box
    assert "<b>text</b>" not in html and "&lt;b&gt;text&lt;/b&gt;" in html
    assert "StrongREJECT &lt;Mijke&gt; &amp; co" in html
    labels = [a for tag, a in p.tags if tag == "label" and "data-choice-box" in a]
    assert [("hidden" in a) for a in labels] == [False, True]


def test_without_blocks_to_comment_on_the_form_says_so():
    html, _ = drawn({"dashboards": "all"}, choices={})
    assert "No blocks saved to the report yet." in html


# One section per tool: every tool a checkbox, all checked for "all"; each tool's box reads as its Commentary and
# sits with the section's own Commentary.

TOOLS_SCHEMA = {"type": "object", "properties": {
    "dashboards": {**SCHEMA["properties"]["dashboards"], "x-aisc-section-per-choice": True},
    "comments": SCHEMA["properties"]["comments"],
    "commentary": {"type": "string", "title": "Commentary", "x-aisc-prose": True},
}}


def tools_fields(values, choices=CHOICES):
    return {f["name"]: f for f in need("report_composer.forms", "form_fields")(TOOLS_SCHEMA, values, choices)}


def tools_drawn(values, choices=CHOICES):
    from report_composer.jinja_env import env

    html = env.from_string('{% from "_form.html.j2" import render_form %}{{ render_form(fields) }}').render(
        fields=list(tools_fields(values, choices).values()))
    parser = Tags()
    parser.feed(html)
    return html, parser


def boxes_checked(p):
    return [(a["value"], "checked" in a) for tag, a in p.tags if tag == "input" and a.get("type") == "checkbox"]


def test_every_tool_is_checked_for_all_and_there_is_no_all_radio():
    f = tools_fields({"dashboards": "all"})["dashboards"]
    assert f["widget"] == "all-or-list" and f["every"] is True
    html, p = tools_drawn({"dashboards": "all"})
    assert boxes_checked(p) == [("12", True), ("14", True)]
    assert not [a for tag, a in p.tags if tag == "input" and a.get("type") == "radio"]
    sets = [a for tag, a in p.tags if tag == "fieldset" and a.get("data-option") == "dashboards"]
    assert "data-every" in sets[0] and sets[0]["data-kind"] == "all-or-list"


def test_only_the_listed_tools_are_checked():
    _, p = tools_drawn({"dashboards": ["14"]})
    assert boxes_checked(p) == [("12", False), ("14", True)]


def test_a_tool_box_is_labelled_as_its_commentary():
    f = tools_fields({"dashboards": "all"})["comments"]
    assert [o["label"] for o in f["options"]] == ["Commentary: LangBiTe (Mijke)",
                                                  "Commentary: StrongREJECT <Mijke> & co"]


def test_the_tool_boxes_come_first_in_the_commentary_box():
    html, _ = tools_drawn({"dashboards": "all"})
    options_box = html[html.index("options-box"):html.index("commentary-box")]
    assert 'data-option="comments"' not in options_box
    commentary_box = html[html.index("commentary-box"):]
    assert commentary_box.index('data-option="comments"') < commentary_box.index('data-option="commentary"')


def test_with_a_box_per_tool_the_section_box_reads_as_the_introduction_before_the_tools():
    html, _ = tools_drawn({"dashboards": "all"})
    own = html[html.index('data-option="commentary"'):]
    own = own[:own.index("</textarea>")]
    assert "<h3>Introduction</h3>" in html
    assert "Printed before the first tool&#39;s section. Left empty, there is none." in own


def test_without_a_box_per_tool_the_section_box_keeps_its_label():
    from report_composer.jinja_env import env

    plain = [f for f in tools_fields({"dashboards": "all"}).values() if f["name"] != "comments"]
    html = env.from_string('{% from "_form.html.j2" import render_form %}{{ render_form(fields) }}').render(fields=plain)
    assert "<h3>Commentary</h3>" in html and "Shown with the section in the report." in html


def test_an_option_without_the_mark_keeps_its_all_radio():
    _, p = drawn({"dashboards": "all"})
    assert [a["value"] for tag, a in p.tags if tag == "input" and a.get("type") == "radio"] == ["all", "list"]
    assert boxes_checked(p) == [("12", False), ("14", False)]
