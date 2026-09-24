"""The configure form of report run v2, decided in Python (`report_composer.forms.form_fields`):
labels and help from the schema (R-U5.3), "More options" (R-U5.4), plugin blocks without annotations
(R-U5.5), all-or-list radios and checkbox lists (R-U4.2, R-U4.4, R-U4.5), fields shown per value
(R-V4.15), the key figures checkboxes (R-V6.12) and the commentary field (R-V3.13).

Field dicts gain (stage 4 implements): `help` (the description), `more` (bool), `show_if`
({option: [values]} or None), `hidden` (bool: the named option has another value), `filter` (bool, a
text filter over more than 10 choices); widgets `all-or-list` (radios + checkboxes) and `checkboxes`
replace `multiselect`, which is gone.
"""
from conftest import BLOCK_TYPES, need
from v2_fakes import BY_TYPE_V2

V1 = {t["type_id"]: t for t in BLOCK_TYPES}


def form_fields(schema, values, choices=None):
    return need("report_composer.forms", "form_fields")(schema, values, choices or {})


def fields(type_id, values=None, choices=None, types=BY_TYPE_V2):
    t = types[type_id]
    merged = {**t["default_options"], **(values or {})}
    return {f["name"]: f for f in form_fields(t["options_schema"], merged, choices)}


# ── R-U5.3 labels, help, enum labels ────────────────────────────────────────

def test_r_u5_3_title_is_the_label_and_description_the_help():
    f = fields("key_figures")["show_tool_headlines"]
    assert f["label"] == "Show tool headlines"
    assert f.get("help") == "One tile per tool."


def test_r_u5_3_enum_labels_come_from_the_schema():
    f = fields("chart")["orientation"]
    assert f["widget"] == "select"
    assert f["options"] == [{"value": "auto", "label": "Automatic"}, {"value": "vertical", "label": "Vertical"},
                            {"value": "horizontal", "label": "Horizontal"}]


# ── R-U5.4 more options ─────────────────────────────────────────────────────

def test_r_u5_4_more_options_are_flagged():
    f = fields("test_results", choices={"evaluations": [], "metrics": []})
    assert {n for n, x in f.items() if x.get("more")} == {"statuses", "show_measurements", "show_artifacts",
                                                          "show_charts", "title", "page_break_before",
                                                          "commentary_position"}
    assert f["evaluations"].get("more") is False and f["detail"].get("more") is False


def test_r_u5_4_more_fields_come_after_main_fields():
    names = [x["name"] for x in form_fields(BY_TYPE_V2["chart"]["options_schema"],
                                            BY_TYPE_V2["chart"]["default_options"], {})]
    more = [x["name"] for x in form_fields(BY_TYPE_V2["chart"]["options_schema"],
                                           BY_TYPE_V2["chart"]["default_options"], {}) if x.get("more")]
    assert more and names[-len(more):] == more


# ── R-U5.5 plugin blocks without annotations (today's behaviour) ────────────

def test_r_u5_5_a_plugin_block_without_annotations_keeps_generated_labels_all_main():
    f = fields("ai_card", types=V1)
    assert f["show_graph_stats"]["label"] == "Show graph stats"
    assert not f["show_graph_stats"].get("more") and not f["show_graph_stats"].get("help")


# ── R-U4.2, R-U4.4, R-U4.5 widgets ─────────────────────────────────────────

def test_r_u4_2_all_or_list_is_radios_and_checkboxes():
    choices = {"evaluations": [{"value": "e1", "label": "Evaluation 1"}], "metrics": []}
    f = fields("test_results", {"evaluations": ["e1"]}, choices)["evaluations"]
    assert f["widget"] == "all-or-list" and f["kind"] == "all-or-list"
    assert f["options"] == [{"value": "e1", "label": "Evaluation 1"}]
    assert not f.get("filter")


def test_r_u4_2_a_filter_box_above_10_choices():
    many = [{"value": f"e{i}", "label": f"Evaluation {i}"} for i in range(11)]
    f = fields("test_results", choices={"evaluations": many, "metrics": []})["evaluations"]
    assert f.get("filter") is True


def test_r_u4_4_a_plain_enum_list_is_a_checkbox_list():
    f = fields("key_figures")["figures"]
    assert f["widget"] == "checkboxes"
    assert f["options"][:2] == [{"value": "version", "label": "Version"}, {"value": "risks", "label": "Risks"}]


def test_r_u4_4_statuses_and_sections_are_checkbox_lists():
    assert fields("test_results", choices={"evaluations": [], "metrics": []})["statuses"]["widget"] == "checkboxes"
    assert fields("changes_since", choices={"compare_to": []})["sections"]["widget"] == "checkboxes"


def test_r_u4_5_single_choices_among_data_stay_selects():
    f = fields("changes_since", choices={"compare_to": [{"value": "v1", "label": "Version 1"}]})["compare_to"]
    assert f["widget"] == "select"
    f = fields("dashboard_chart", choices={"chart_id": [{"value": 33, "label": "Bias"}]})["chart_id"]
    assert f["widget"] == "select"


def test_r_u4_1_no_multiselect_widget_is_left():
    for type_id in BY_TYPE_V2:
        for f in form_fields(BY_TYPE_V2[type_id]["options_schema"], BY_TYPE_V2[type_id]["default_options"], {}):
            assert f["widget"] != "multiselect", (type_id, f["name"])


# ── R-V6.12 key figures ─────────────────────────────────────────────────────

def test_r_v6_12_key_figures_are_labelled_checkboxes_all_ticked_by_default():
    f = fields("key_figures")["figures"]
    assert f["widget"] == "checkboxes"
    assert [o["label"] for o in f["options"]] == ["Version", "Risks", "Objectives", "Coverage", "Tests", "Checklists"]
    assert f["value"] == ["version", "risks", "objectives", "coverage", "tests", "checklists"]


# ── R-V4.15 fields shown per value ──────────────────────────────────────────

def test_r_v4_15_show_if_is_passed_on_and_decides_hidden():
    f = fields("chart", {"dataset": "coverage_status"})
    assert f["tool_chart"].get("show_if") == {"dataset": ["tool_chart"]}
    assert f["tool_chart"].get("hidden") is True and f["metric"].get("hidden") is True
    assert f["dataset"].get("hidden") is False
    g = fields("chart", {"dataset": "metric_by_dimension"})
    assert g["metric"].get("hidden") is False and g["dimension"].get("hidden") is False
    assert g["tool_chart"].get("hidden") is True


# ── R-V3.13 the commentary field ────────────────────────────────────────────

def test_r_v3_13_commentary_is_a_six_row_textarea_of_its_own():
    f = fields("ai_card")["commentary"]
    assert f["widget"] == "commentary"
    assert f.get("more") is False
    p = fields("ai_card")["commentary_position"]
    assert p.get("more") is True and p["label"] == "Place the commentary"
    assert [o["label"] for o in p["options"]] == ["After the section", "Before the section"]
