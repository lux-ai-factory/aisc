"""A dict choice value (a metric pair the renderer offers) is written into a double-quoted attribute of
the block form. Jinja's tojson escapes < > & ' but not ", so the JSON must be escaped once more for the
attribute, or a metric name ends the attribute and adds its own (stored XSS)."""
import json
from html.parser import HTMLParser

from conftest import need
from v2_fakes import BY_TYPE_V2

EVIL = {"tool": "T", "metric": "x onmouseover=alert(1) y \" '"}


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))


def drawn(type_id, values):
    from report_composer.jinja_env import env

    t = BY_TYPE_V2[type_id]
    option = "metrics" if type_id == "test_results" else "metric"
    fields = need("report_composer.forms", "form_fields")(
        t["options_schema"], {**t["default_options"], **values}, {option: [{"value": EVIL, "label": "T"}]})
    html = env.from_string('{% from "_form.html.j2" import render_form %}{{ render_form(fields) }}').render(
        fields=fields)
    parser = Tags()
    parser.feed(html)
    return parser.tags


def test_a_metric_choice_checkbox_keeps_its_json_in_the_value():
    boxes = [a for tag, a in drawn("test_results", {"metrics": "all"})
             if tag == "input" and ("data-json", None) in a]
    assert len(boxes) == 1
    attrs = boxes[0]
    assert [name for name, _ in attrs] == ["type", "value", "data-json"]
    assert json.loads(dict(attrs)["value"]) == EVIL


def test_a_metric_choice_option_keeps_its_json_in_the_value():
    options = [dict(a) for tag, a in drawn("chart", {}) if tag == "option" and "{" in (dict(a).get("value") or "")]
    assert len(options) == 1
    assert not any(name.startswith("on") for name in options[0])
    assert json.loads(options[0]["value"]) == EVIL
