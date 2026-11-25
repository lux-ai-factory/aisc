"""Views: named queries the model reads instead of joining the engine's tables. A view is written into a query as a
WITH item before the query runs, so the query that runs, and is fingerprinted, holds it."""
from chart_assistant.views import BUILT_IN, View, available, describe, expand

V = {"results": View("results", "one row per result", {"metric": "its name"}, "SELECT 1 AS metric")}


def test_a_query_reading_a_view_gets_it_as_a_with_item():
    out = expand("SELECT metric FROM results", V)
    assert out.lower().startswith("with results as (select 1 as metric)")
    assert out.lower().rstrip().endswith("select metric from results")


def test_a_view_goes_before_the_query_s_own_with_items():
    out = expand("WITH a AS (SELECT metric FROM results) SELECT * FROM a", V).lower()
    assert out.index("results as (") < out.index("a as (")


def test_a_query_reading_no_view_is_left_as_it_is():
    sql = "SELECT 1 FROM engine.aisc_backend_metric"
    assert expand(sql, V) == sql


def test_a_with_item_the_query_calls_results_is_its_own():
    sql = "WITH results AS (SELECT 2 AS x) SELECT x FROM results"
    assert expand(sql, V) == sql


def test_the_built_in_view_names_its_columns_and_reads_reader_tables_only():
    from chart_assistant.description import READERS
    from chart_assistant.query_check import check
    view = BUILT_IN["results"]
    assert {"metric", "score", "dimensions", "target", "target_kind", "system_version", "run", "run_name",
            "run_status", "measured_at"} == set(view.columns)
    check(view.sql, READERS)                      # raises QueryRefused if it names anything else


def test_the_description_lists_each_view_with_its_columns():
    text = describe(V)
    assert "results: one row per result" in text and "- metric: its name" in text


BASE = View("results", "all results", {"metric": "m"}, "SELECT 1 AS metric")
ON_TOP = View("attempts", "one row per attempt", {"worked": "1 or 0"}, "SELECT 1 AS worked FROM results",
              needs=frozenset({"Jailbreak success"}),
              example="share that worked: SELECT 'all' AS category, AVG(worked) AS value FROM attempts")
BOTH = {"results": BASE, "attempts": ON_TOP}


def test_a_view_is_offered_only_when_the_project_has_the_metrics_it_needs():
    assert set(available(BOTH, ["Conversation"])) == {"results"}
    assert set(available(BOTH, ["Conversation", "Jailbreak success"])) == {"results", "attempts"}


def test_a_view_that_reads_results_brings_it_along_first():
    out = expand("SELECT AVG(worked) FROM attempts", BOTH).lower()
    assert out.index("results as (") < out.index("attempts as (") < out.index("select avg(worked)")


def test_a_query_reading_both_views_gets_each_once():
    out = expand("SELECT * FROM attempts a JOIN results r ON true", BOTH).lower()
    assert out.count("results as (") == 1 and out.count("attempts as (") == 1


def test_a_views_example_is_shown_to_the_model():
    assert "Example: share that worked: SELECT" in describe(BOTH)


def test_a_view_another_view_reads_is_written_first_even_when_the_query_names_it_second():
    out = expand("SELECT * FROM attempts a JOIN results r ON true", BOTH).lower()
    assert out.index("results as (") < out.index("attempts as (")
