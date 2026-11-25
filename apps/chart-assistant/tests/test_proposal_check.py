"""The gates a proposal passes before a person sees it: it reads only dimension keys the project has, and its result
on the mock data has one filled row per chart point."""
from chart_assistant.proposal_check import dimension_keys, result_problem, unknown_keys


def test_the_keys_a_query_reads_from_dimensions():
    sql = ("SELECT dimensions->>'category', m.dimensions->'turns', dimensions->'a'->>'b' FROM results m "
           "WHERE dimensions->>'language' = 'en'")
    assert dimension_keys(sql) == {"category", "turns", "a", "language"}


def test_a_key_of_another_column_is_not_a_dimension_key():
    assert dimension_keys("SELECT value->>'x' FROM engine.aisc_backend_evaluationinput") == set()


def test_unknown_keys_are_case_sensitive_and_sorted():
    assert unknown_keys("SELECT dimensions->>'Category', dimensions->>'model', dimensions->>'language' FROM results",
                        frozenset({"category", "language"})) == ["Category", "model"]


CHART = {"kind": "bar", "title": "t", "category": "category", "series": "series", "value": "value"}
COLUMNS = ["category", "series", "value"]


def test_a_filled_result_with_one_row_per_point_is_fine():
    assert result_problem(CHART, {"columns": COLUMNS, "rows": [["cv", "A", 0.5], ["cv", "B", None]]}) is None


def test_no_rows_is_a_problem():
    assert "returns no rows" in result_problem(CHART, {"columns": COLUMNS, "rows": []})


def test_a_column_empty_in_every_row_is_a_problem():
    rows = [["cv", None, 0.5], ["health", None, 0.4]]
    assert "'series' is empty in every row" in result_problem(CHART, {"columns": COLUMNS, "rows": rows})


def test_several_rows_for_one_point_is_a_problem():
    rows = [["cv", "A", 0.5], ["cv", "A", 0.7]]
    assert "2 rows share" in result_problem(CHART, {"columns": COLUMNS, "rows": rows})


def test_a_table_may_repeat_a_point():
    rows = [["cv", "A", 0.5], ["cv", "A", 0.7]]
    assert result_problem({**CHART, "kind": "table"}, {"columns": COLUMNS, "rows": rows}) is None


def test_a_chart_without_series_is_checked_on_its_category():
    chart = {k: v for k, v in CHART.items() if k != "series"}
    assert "2 rows share" in result_problem(chart, {"columns": ["category", "value"], "rows": [["cv", 1], ["cv", 2]]})


def test_a_key_read_with_a_path_is_the_paths_first_key():
    assert dimension_keys("SELECT dimensions#>>'{category}', dimensions#>'{a,b}' FROM results") == {"category", "a"}
