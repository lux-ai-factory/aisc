"""An "all or a list" option may name its "all" choice (`x-aisc-all-label`), as the Checklist answers block's
`submissions` ("Latest of each checklist"); without it the choice reads "All (also ones added later)"."""
from conftest import need

ALL = {"oneOf": [{"const": "all"}, {"type": "array", "items": {"type": "string"}}], "x-aisc-reference": True}
SCHEMA = {"type": "object", "properties": {
    "submissions": {**ALL, "title": "Submissions", "x-aisc-all-label": "Latest of each checklist"},
    "checklists": {**ALL, "title": "Checklists"},
}}
CHOICES = {"submissions": [{"value": "s1", "label": "FRAIA · report version · version 1 · Closed · 2026-11-08 22:32"}],
           "checklists": [{"value": "c1", "label": "FRAIA"}]}


def drawn():
    from report_composer.jinja_env import env

    fields = need("report_composer.forms", "form_fields")(SCHEMA, {"submissions": "all", "checklists": "all"}, CHOICES)
    return env.from_string('{% from "_form.html.j2" import render_form %}{{ render_form(fields) }}').render(fields=fields)


def test_the_all_choice_takes_the_label_the_option_names():
    html = drawn()
    part = html[html.index('data-option="submissions"'):]
    part = part[:part.index("</fieldset>")]
    assert "Latest of each checklist" in part and "All (also ones added later)" not in part


def test_without_a_label_the_all_choice_keeps_its_wording():
    html = drawn()
    part = html[html.index('data-option="checklists"'):]
    assert "All (also ones added later)" in part[:part.index("</fieldset>")]
