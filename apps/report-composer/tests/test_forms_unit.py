"""The per-block configure form, generated in Python from the options schema (report run
2026-09-23: R4.2.2, R4.1.1). `report_composer.forms.form_fields(schema, values, choices)`."""
from conftest import BLOCK_TYPES, need

BY = {t["type_id"]: t for t in BLOCK_TYPES}


def fields(type_id, values=None, choices=None):
    t = BY[type_id]
    return {f["name"]: f for f in need("report_composer.forms", "form_fields")(
        t["options_schema"], values or t["default_options"], choices or {})}


# R4.2.2
def test_r4_2_2_widgets_follow_the_schema():
    f = fields("dashboard_chart", choices={"chart_id": [{"value": 33, "label": "Bias rate by version"}]})
    assert f["show_comments"]["widget"] == "checkbox"
    assert f["width"]["widget"] == "number" and (f["width"]["min"], f["width"]["max"]) == (400, 1600)
    assert f["chart_id"]["widget"] == "select" and f["chart_id"]["required"] is True
    assert f["chart_id"]["options"] == [{"value": 33, "label": "Bias rate by version"}]
    assert f["title"]["widget"] == "text"


def test_r4_2_2_enums_are_selects():
    f = fields("control_objectives")
    assert f["group_by"]["widget"] == "select"
    assert [o["value"] for o in f["group_by"]["options"]] == ["objective", "risk"]


def test_r4_2_2_long_text_is_a_textarea():
    assert fields("free_text", values={"text": "x"})["text"]["widget"] == "textarea"


def test_r4_2_2_current_values_are_filled_in():
    f = fields("cover", values={"report_title": "Mine", "show_logo": False})
    assert f["report_title"]["value"] == "Mine" and f["show_logo"]["value"] is False
