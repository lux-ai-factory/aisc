"""The conversation: the model sees the description and may only run queries on the mock database and propose a chart.
A stand-in model plays fixed tool calls; no network."""
import json

import pytest

from chart_assistant.loop import BudgetSpent, Conversation, Proposal

READERS = {"engine.aisc_backend_measurement"}
GOOD = "SELECT dimensions->>'category' AS category, 'all' AS series, avg(score) AS value FROM engine.aisc_backend_measurement GROUP BY 1"


class StandIn:
    """Answers each call with the next scripted message; records what it was sent."""

    def __init__(self, *script):
        self.script, self.sent = list(script), []

    def __call__(self, messages, tools):
        self.sent.append(json.loads(json.dumps(messages)))
        return self.script.pop(0)


def tool(name, **args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": f"c{len(args)}{name}", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}


CHART = {"kind": "radar", "title": "Mean score by category", "category": "category", "series": "series", "value": "value"}
mock_runs = []


def on_mock(sql):
    mock_runs.append(sql)
    return {"columns": ["category", "series", "value"], "rows": [["Age", "all", 0.5], ["Gender", "all", 0.4], ["Status", "all", 0.3]]}


def talk(*script, **kw):
    model = StandIn(*script)
    return Conversation(description="DESCRIPTION TEXT", readers=READERS, model=model, run_on_mock=on_mock, **kw), model


def test_a_request_ends_with_a_proposal_whose_rows_come_from_the_mock():
    c, model = talk(tool("run_on_mock", sql=GOOD),
                    tool("propose_chart", sql=GOOD, chart=CHART, description="the mean score per category"))
    p = c.ask("radar of the mean score by category")
    assert isinstance(p, Proposal) and p.sql == GOOD and p.chart == CHART and p.mock["rows"][0][0] == "Age"
    assert p.description == "the mean score per category" and len(p.fingerprint) == 64


def test_the_model_reads_the_description_and_never_anything_else_of_the_project():
    c, model = talk(tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    c.ask("x")
    assert "DESCRIPTION TEXT" in model.sent[0][0]["content"]


def test_a_refused_query_goes_back_to_the_model_as_an_error_and_never_runs():
    mock_runs.clear()
    c, model = talk(tool("run_on_mock", sql="DELETE FROM engine.aisc_backend_measurement"),
                    tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    c.ask("x")
    assert mock_runs == [GOOD]
    answer = model.sent[1][-1]
    assert answer["role"] == "tool" and "refused" in answer["content"].lower()


def test_a_proposal_with_a_refused_query_is_not_a_proposal():
    c, _ = talk(tool("propose_chart", sql="SELECT * FROM trace.call", chart=CHART, description="d"),
                tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    assert c.ask("x").sql == GOOD


def test_a_chart_without_its_required_settings_is_sent_back():
    bad = {"kind": "pie", "title": "t"}
    c, model = talk(tool("propose_chart", sql=GOOD, chart=bad, description="d"),
                    tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    assert c.ask("x").chart == CHART
    assert "chart" in model.sent[1][-1]["content"].lower()


def test_a_change_starts_from_the_last_proposal():
    c, model = talk(tool("propose_chart", sql=GOOD, chart=CHART, description="d"),
                    tool("propose_chart", sql=GOOD, chart={**CHART, "kind": "bar"}, description="d"))
    c.ask("radar")
    assert c.ask("make it a bar chart").chart["kind"] == "bar"
    assert any("make it a bar chart" in (m.get("content") or "") for m in model.sent[1])


def test_a_question_back_comes_only_through_ask_question():
    c, _ = talk(tool("ask_question", question="Which model do you mean?"))
    assert c.ask("x") == "Which model do you mean?"


def test_plain_text_from_the_model_never_reaches_the_person():
    c, model = talk({"role": "assistant", "content": "The average is 0.4 for AGE and 0.3 for GENDER."},
                    tool("ask_question", question="Which run do you mean?"))
    assert c.ask("x") == "Which run do you mean?"
    told = model.sent[1][-1]
    assert "ask_question" in told["content"] and "propose_chart" in told["content"]


def test_a_model_that_keeps_writing_text_gives_no_answer_at_all():
    c, _ = talk(*[{"role": "assistant", "content": "Here are the rows: ..."}] * 10, max_steps=3)
    with pytest.raises(BudgetSpent):
        c.ask("x")


def test_a_long_question_or_one_that_is_not_a_question_is_sent_back():
    c, model = talk(tool("ask_question", question="Here are the results: " + "AGE 0.4, " * 60),
                    tool("ask_question", question="Results: AGE 0.4"),
                    tool("ask_question", question="Which run?"))
    assert c.ask("x") == "Which run?"
    assert model.sent[1][-1]["content"].startswith("Refused")
    assert model.sent[2][-1]["content"].startswith("Refused")


def test_the_model_may_only_ask_a_question_run_on_the_mock_or_propose_a_chart():
    from chart_assistant.loop import SYSTEM, TOOLS
    assert {t["function"]["name"] for t in TOOLS} == {"run_on_mock", "propose_chart", "ask_question", "remove_chart",
                                                     "change_chart"}
    assert "never" in SYSTEM.lower() and "ask_question" in SYSTEM


def test_too_many_steps_stop_the_request():
    c, _ = talk(*[tool("run_on_mock", sql=GOOD)] * 20, max_steps=5)
    with pytest.raises(BudgetSpent):
        c.ask("x")


def test_too_many_messages_stop_the_conversation():
    c, _ = talk(*[tool("ask_question", question="?")] * 5, max_messages=2)
    c.ask("a"); c.ask("b")
    with pytest.raises(BudgetSpent):
        c.ask("c")


def test_the_mock_result_sent_back_to_the_model_is_capped():
    big = {"columns": ["category", "series", "value"], "rows": [[str(i), "s", i] for i in range(1000)]}
    model = StandIn(tool("run_on_mock", sql=GOOD), tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    Conversation(description="D", readers=READERS, model=model, run_on_mock=lambda s: big).ask("x")
    assert len(json.loads(model.sent[1][-1]["content"])["rows"]) <= 50


# ── plots it made: change them or remove them ──

MADE = [{"id": 12, "title": "Mean score by category", "kind": "radar", "sql": GOOD}]


def test_each_request_tells_the_model_which_plots_it_made_on_this_dashboard():
    c, model = talk(tool("ask_question", question="Which one?"))
    c.ask("change it", charts=MADE)
    told = model.sent[0][-1]["content"]
    assert "change it" in told and "12" in told and "Mean score by category" in told and GOOD in told


def test_a_clear_delete_comes_back_as_a_removal_of_that_plot():
    from chart_assistant.loop import Removal
    c, _ = talk(tool("remove_chart", chart=12))
    assert c.ask("delete the radar by category", charts=MADE) == Removal(charts=[(12, "Mean score by category")])


def test_a_plot_not_on_the_dashboard_is_never_removed():
    c, model = talk(tool("remove_chart", chart=99), tool("ask_question", question="Which plot?"))
    assert c.ask("delete it", charts=MADE) == "Which plot?"
    assert model.sent[1][-1]["content"].startswith("Refused")


def test_without_plots_of_its_own_nothing_can_be_removed():
    c, model = talk(tool("remove_chart", chart=12), tool("ask_question", question="Which plot?"))
    assert c.ask("delete it") == "Which plot?"
    assert model.sent[1][-1]["content"].startswith("Refused")


def test_a_change_to_a_plot_it_made_names_the_plot_it_replaces():
    c, _ = talk(tool("propose_chart", sql=GOOD, chart={**CHART, "kind": "bar"}, description="d", replaces=12))
    assert c.ask("make the radar a bar chart", charts=MADE).replaces == 12


def test_a_replacement_of_a_plot_it_did_not_make_is_refused():
    c, model = talk(tool("propose_chart", sql=GOOD, chart=CHART, description="d", replaces=99),
                    tool("propose_chart", sql=GOOD, chart=CHART, description="d"))
    p = c.ask("x", charts=MADE)
    assert p.replaces is None and model.sent[1][-1]["content"].startswith("Refused")


def test_the_prompt_says_a_plot_is_removed_only_when_the_person_clearly_asks():
    from chart_assistant.loop import SYSTEM, TOOLS
    assert "remove_chart" in {t["function"]["name"] for t in TOOLS}
    assert "remove_chart" in SYSTEM and "clearly" in SYSTEM and "replaces" in SYSTEM


def test_a_query_ending_with_a_semicolon_is_proposed_without_it():
    c, _ = talk(tool("propose_chart", sql=GOOD + " ;\n", chart=CHART, description="d"))
    p = c.ask("x")
    from chart_assistant.query_check import fingerprint
    assert p.sql == GOOD and p.fingerprint == fingerprint(GOOD)


def test_delete_all_removes_every_plot_it_names_in_one_answer():
    from chart_assistant.loop import Removal
    two = MADE + [{"id": 13, "title": "Second", "kind": "bar", "sql": GOOD}]
    reply = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "remove_chart", "arguments": '{"chart": 12}'}},
        {"id": "b", "type": "function", "function": {"name": "remove_chart", "arguments": '{"chart": 13}'}}]}
    c, _ = talk(reply)
    assert c.ask("delete all of them", charts=two) == Removal(charts=[(12, "Mean score by category"), (13, "Second")])


# ── every plot on the dashboard: any may be removed or replaced ──

ON_BOARD = [{"id": 5, "title": "Jailbreak success by language", "kind": "bar", "mine": False},
            {"id": 12, "title": "Mean score by category", "kind": "radar", "mine": True, "sql": GOOD}]


def test_the_model_sees_every_plot_and_which_ones_it_made():
    c, model = talk(tool("ask_question", question="Which one?"))
    c.ask("x", charts=ON_BOARD)
    told = model.sent[0][-1]["content"]
    assert "Jailbreak success by language" in told and "Mean score by category" in told
    line = next(l for l in told.splitlines() if "Jailbreak success" in l)
    assert "not made by you" in line


def test_a_plot_it_did_not_make_can_be_removed():
    from chart_assistant.loop import Removal
    c, _ = talk(tool("remove_chart", chart=5))
    assert c.ask("delete the bar plots", charts=ON_BOARD) == Removal(charts=[(5, "Jailbreak success by language")])


def test_a_plot_it_did_not_make_can_be_replaced_by_a_new_query():
    c, _ = talk(tool("propose_chart", sql=GOOD, chart=CHART, description="d", replaces=5))
    assert c.ask("show that one per run instead", charts=ON_BOARD).replaces == 5


def test_a_question_followed_by_a_short_hint_is_a_question():
    c, _ = talk(tool("ask_question", question="Which plot would you like to delete? Please give its number or title."))
    assert c.ask("delete a plot", charts=ON_BOARD).startswith("Which plot")


# ── it knows every plot by its definition and changes the matching one in place ──

DEFAULTS = [{"id": 126, "title": "Default · Jailbreak success by language", "kind": "bar", "mine": False,
             "definition": {"kind": "bar", "x": "language", "series": ["metric", "run"], "value": "AVG(score)",
                            "filters": ["metric IN Jailbreak success"], "axis_min": None, "axis_max": None,
                            "percent": True}, "can_change": ["axis_max", "axis_min", "kind", "percent", "title"], "same_as": []},
            {"id": 127, "title": "Default · Jailbreak success by language (radar)", "kind": "radar", "mine": False,
             "definition": {"kind": "radar", "axes": ["en", "nl"], "series": ["run"], "value": "AVG(score)",
                            "filters": ["metric IN Jailbreak success"], "axis_max": 1, "percent": True},
             "can_change": ["axis_max", "percent", "title"], "same_as": []}]


def test_the_model_is_told_how_each_plot_is_built():
    c, model = talk(tool("ask_question", question="Which one?"))
    c.ask("x", charts=DEFAULTS)
    told = model.sent[0][-1]["content"]
    assert '"x": "language"' in told and '"axes": ["en", "nl"]' in told and '"axis_max": 1' in told


def test_a_matching_plot_is_changed_in_place():
    from chart_assistant.loop import Change
    c, _ = talk(tool("change_chart", chart=127, changes={"axis_max": 0.4}))
    assert c.ask("scale the jailbreak radar to 40%", charts=DEFAULTS) == \
        Change(chart=127, title="Default · Jailbreak success by language (radar)", changes={"axis_max": 0.4})


def test_a_change_to_a_plot_not_on_the_dashboard_or_not_a_change_it_can_make_is_sent_back():
    c, model = talk(tool("change_chart", chart=99, changes={"axis_max": 0.4}),
                    tool("change_chart", chart=127, changes={"colour": "red"}),
                    tool("change_chart", chart=127, changes={}),
                    tool("ask_question", question="Which plot?"))
    assert c.ask("x", charts=DEFAULTS) == "Which plot?"
    assert all(m["content"].startswith("Refused") for m in [model.sent[i][-1] for i in (1, 2, 3)])


def test_the_prompt_says_to_change_the_matching_plot_ask_when_several_match_and_never_alter_values():
    from chart_assistant.loop import SYSTEM, TOOLS
    assert "change_chart" in {t["function"]["name"] for t in TOOLS}
    text = " ".join(SYSTEM.split()).lower()
    assert "never change the values" in text and "several plots could match" in text and "change_chart" in text


# ── a plot is removed only when the person's own words ask to delete ──

SCALED = DEFAULTS + [{"id": 138, "title": "Mean score per category (mine)", "kind": "radar", "mine": True,
                      "sql": GOOD, "definition": {"kind": "radar", "axes": ["en"], "axis_max": None},
                      "can_change": ["axis_max", "percent", "title"], "same_as": []}]


def test_a_request_that_does_not_ask_to_delete_never_removes_a_plot():
    from chart_assistant.loop import Change
    c, model = talk(tool("remove_chart", chart=138), tool("change_chart", chart=127, changes={"axis_max": 0.4}))
    assert isinstance(c.ask("scale the jailbreak success by language radar to 40%", charts=SCALED), Change)
    assert model.sent[1][-1]["content"].startswith("Refused")


@pytest.mark.parametrize("words", ["delete all bar plots", "Remove the radar", "elimina il radar",
                                   "cancella quel grafico", "togli le barre", "rimuovi il 138", "verwijder de radar",
                                   "get rid of the radar"])
def test_a_request_in_words_that_ask_to_delete_removes_the_plot(words):
    from chart_assistant.loop import Removal
    c, _ = talk(tool("remove_chart", chart=138))
    assert c.ask(words, charts=SCALED) == Removal(charts=[(138, "Mean score per category (mine)")])


@pytest.mark.parametrize("words", ["show the runs in the dropdown as bars", "I wish it were a line chart"])
def test_words_that_only_look_like_deleting_do_not_count(words):
    c, model = talk(tool("remove_chart", chart=138), tool("ask_question", question="Which plot?"))
    c.ask(words, charts=SCALED)
    assert model.sent[1][-1]["content"].startswith("Refused")


def test_the_prompt_says_two_plots_showing_the_same_thing_are_ambiguous():
    from chart_assistant.loop import SYSTEM
    text = " ".join(SYSTEM.split()).lower()
    assert "show the same thing" in text and "whoever made them" in text


# ── two plots that show the same thing: it asks which, unless the person already said ──

TWINS = [{"id": 126, "title": "Default · Jailbreak success by language", "kind": "bar", "mine": False,
          "can_change": ["axis_max", "axis_min", "kind", "percent", "title"], "same_as": []},
         {"id": 127, "title": "Default · Jailbreak success by language (radar)", "kind": "radar", "mine": False,
          "can_change": ["axis_max", "percent", "title"], "same_as": [138]},
         {"id": 138, "title": "Jailbreak success by language (scaled 40%)", "kind": "radar", "mine": True, "sql": GOOD,
          "can_change": ["axis_max", "percent", "title"], "same_as": [127]}]


def test_a_change_to_one_of_two_alike_plots_is_sent_back_to_ask_which():
    c, model = talk(tool("change_chart", chart=138, changes={"axis_max": 0.4}),
                    tool("ask_question", question="Which one: the default radar or the scaled one?"))
    assert c.ask("scale the jailbreak success by language radar to 40%", charts=TWINS).startswith("Which one")
    told = model.sent[1][-1]["content"]
    assert told.startswith("Refused") and "127" in told and "138" in told


def test_the_answer_to_its_question_settles_which_plot():
    from chart_assistant.loop import Change
    c, _ = talk(tool("ask_question", question="Which one: the default radar or the scaled one?"),
                tool("change_chart", chart=127, changes={"axis_max": 0.4}))
    c.ask("scale the jailbreak success by language radar to 40%", charts=TWINS)
    assert c.ask("the default one", charts=TWINS) == Change(chart=127, title=TWINS[1]["title"],
                                                          changes={"axis_max": 0.4})


@pytest.mark.parametrize("words, chart", [("make the bar chart of jailbreak success by language go up to 40%", 126),
                                          ("set plot 127 to 40%", 127)])
def test_a_plot_that_shows_nothing_else_or_is_named_by_its_number_is_changed_at_once(words, chart):
    from chart_assistant.loop import Change
    c, _ = talk(tool("change_chart", chart=chart, changes={"axis_max": 0.4}))
    assert isinstance(c.ask(words, charts=TWINS), Change)


def test_a_removal_of_one_of_two_alike_plots_is_sent_back_too():
    c, model = talk(tool("remove_chart", chart=138), tool("ask_question", question="Which one?"))
    assert c.ask("delete the jailbreak success by language radar", charts=TWINS) == "Which one?"
    assert model.sent[1][-1]["content"].startswith("Refused")


def test_the_answer_to_which_plot_to_delete_removes_it():
    from chart_assistant.loop import Removal
    c, _ = talk(tool("ask_question", question="Which one: the default radar or the scaled one?"),
                tool("remove_chart", chart=138))
    c.ask("delete the jailbreak success by language radar", charts=TWINS)
    assert c.ask("the scaled one", charts=TWINS) == Removal(charts=[(138, TWINS[2]["title"])])


def test_an_answer_to_a_question_that_was_not_about_deleting_removes_nothing():
    c, model = talk(tool("ask_question", question="Which one: the default radar or the scaled one?"),
                    tool("remove_chart", chart=138), tool("ask_question", question="Delete it?"))
    c.ask("scale the jailbreak success by language radar to 40%", charts=TWINS)
    assert c.ask("the scaled one", charts=TWINS) == "Delete it?"
    assert model.sent[2][-1]["content"].startswith("Refused")


@pytest.mark.parametrize("arguments", ['[12]', '"delete 12"', '12', 'null'])
def test_arguments_that_are_not_a_json_object_are_sent_back(arguments):
    call = tool("remove_chart", chart=12)
    call["tool_calls"][0]["function"]["arguments"] = arguments
    c, model = talk(call, tool("ask_question", question="Which plot?"))
    assert c.ask("delete it", charts=MADE) == "Which plot?"
    assert model.sent[1][-1]["content"] == "Refused: the arguments must be a JSON object."


PLOT_ONE = [{"id": 1, "title": "Mean score by category", "kind": "bar", "sql": GOOD}]


@pytest.mark.parametrize("call", [tool("remove_chart", chart=True),
                                  tool("change_chart", chart=True, changes={"title": "New"}),
                                  tool("propose_chart", sql=GOOD, chart=CHART, description="d", replaces=True)])
def test_true_is_not_the_number_of_plot_one(call):
    c, model = talk(call, tool("ask_question", question="Which plot?"))
    assert c.ask("delete or change plot one", charts=PLOT_ONE) == "Which plot?"
    assert model.sent[1][-1]["content"].startswith("Refused")


# ── the dashboard decides: what a plot can change (can_change) and which plots show the same thing (same_as) ──

def test_a_change_the_dashboard_does_not_list_for_that_plot_is_sent_back():
    plots = [{"id": 7, "title": "Pass rate", "kind": "bar", "mine": False, "can_change": ["title"], "same_as": []}]
    c, model = talk(tool("change_chart", chart=7, changes={"axis_max": 1}), tool("ask_question", question="Which?"))
    assert c.ask("scale it to 1", charts=plots) == "Which?"
    told = model.sent[1][-1]["content"]
    assert told.startswith("Refused") and "title" in told and "propose_chart" in told


def test_plots_the_dashboard_says_show_the_same_thing_are_asked_about_whatever_their_titles():
    plots = [{"id": 7, "title": "Pass rate", "kind": "bar", "mine": False, "can_change": ["title"], "same_as": [9]},
             {"id": 9, "title": "Something else entirely", "kind": "bar", "mine": True, "sql": GOOD,
              "can_change": ["title"], "same_as": [7]}]
    c, model = talk(tool("change_chart", chart=7, changes={"title": "New"}), tool("ask_question", question="Which?"))
    assert c.ask("rename it", charts=plots) == "Which?"
    told = model.sent[1][-1]["content"]
    assert told.startswith("Refused") and "7" in told and "9" in told


def test_the_wish_to_delete_is_held_from_the_request_that_said_it_through_the_answer_to_the_next_question():
    from chart_assistant.loop import Removal
    c, _ = talk(tool("ask_question", question="Which one: the default radar or the scaled one?"),
                tool("remove_chart", chart=138), tool("ask_question", question="Which?"))
    c.ask("delete the jailbreak success by language radar", charts=TWINS)
    assert c.delete_asked
    assert c.ask("the scaled one", charts=TWINS) == Removal(charts=[(138, TWINS[2]["title"])])
    assert c.delete_asked
    c.ask("now the bars", charts=TWINS)
    assert not c.delete_asked


def test_the_change_chart_schema_is_derived_from_the_changes_and_kinds_the_loop_names():
    from chart_assistant.loop import CHANGES, IN_PLACE_KINDS, KINDS, TOOLS
    schema = next(t for t in TOOLS if t["function"]["name"] == "change_chart")["function"]["parameters"]
    assert schema["properties"]["changes"]["properties"] == CHANGES
    assert CHANGES["kind"]["enum"] == list(IN_PLACE_KINDS) and set(IN_PLACE_KINDS) <= set(KINDS)
    propose = next(t for t in TOOLS if t["function"]["name"] == "propose_chart")["function"]["parameters"]
    assert propose["properties"]["chart"]["properties"]["kind"]["enum"] == list(KINDS)


# ── alike plots: asked about, unless the request names the plot's number, its kind or a word only its title has ──

def test_scaling_jailbreak_success_by_language_asks_which_of_the_default_radar_and_the_scaled_one():
    c, model = talk(tool("change_chart", chart=138, changes={"axis_max": 0.4}), tool("ask_question", question="Which?"))
    assert c.ask("scale jailbreak success by language to 40%", charts=TWINS) == "Which?"
    told = model.sent[1][-1]["content"]
    assert told.startswith("Refused") and "127" in told and "138" in told


@pytest.mark.parametrize("words, chart", [("scale the scaled jailbreak radar to 40%", 138),
                                          ("set plot 127 to 40%", 127)])
def test_a_word_only_its_title_has_or_its_number_settles_which(words, chart):
    from chart_assistant.loop import Change
    c, _ = talk(tool("change_chart", chart=chart, changes={"axis_max": 0.4}))
    assert isinstance(c.ask(words, charts=TWINS), Change)


SAME_SUBJECT = [{"id": 126, "title": "Default · Jailbreak success by language", "kind": "bar", "mine": False,
                 "can_change": ["axis_max", "axis_min", "kind", "percent", "title"], "same_as": [127]},
                {"id": 127, "title": "Default · Jailbreak success by language (radar)", "kind": "radar",
                 "mine": False, "can_change": ["axis_max", "percent", "title"], "same_as": [126]}]


def test_a_bar_and_a_radar_of_the_same_subject_are_asked_about_unless_the_request_names_the_kind():
    from chart_assistant.loop import Change
    c, model = talk(tool("change_chart", chart=126, changes={"axis_max": 0.4}), tool("ask_question", question="Which?"))
    assert c.ask("set jailbreak success by language to 40%", charts=SAME_SUBJECT) == "Which?"
    assert model.sent[1][-1]["content"].startswith("Refused")
    for words, chart in (("set the jailbreak success bars to 40%", 126), ("set il ragno to 40%", 127)):
        c, _ = talk(tool("change_chart", chart=chart, changes={"axis_max": 0.4}))
        assert isinstance(c.ask(words, charts=SAME_SUBJECT), Change), words
