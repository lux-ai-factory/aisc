"""The views of the tests: the bias conversations beside their baseline, and the jailbreak attempts. Each is offered
only when the project has the test's metric, reads only the results view, and exposes no free text."""
from chart_assistant.description import READERS
from chart_assistant.query_check import check
from chart_assistant.views import BUILT_IN, expand
from chart_assistant.views_of_tests import TEST_VIEWS

ALL = {**BUILT_IN, **TEST_VIEWS}


def test_conversations_needs_the_conversation_metric_and_names_its_columns():
    v = TEST_VIEWS["conversations"]
    assert v.needs == {"Conversation"}
    assert set(v.columns) == {"target", "run", "run_name", "system_version", "category", "person", "language",
                              "register", "scenario", "referred", "same_as_baseline"}


def test_conversations_never_shows_the_organisations_named():
    assert "organisations" not in TEST_VIEWS["conversations"].columns


def test_a_query_on_conversations_expands_to_one_the_check_accepts():
    sql = "SELECT person AS category, target AS series, AVG(same_as_baseline) AS value FROM conversations GROUP BY 1, 2"
    check(sql, READERS, views=frozenset(ALL))
    check(expand(sql, ALL), READERS)


def test_its_example_is_a_query_on_the_view_itself():
    assert " FROM conversations" in TEST_VIEWS["conversations"].example


def test_jailbreak_attempts_needs_the_jailbreak_metric_and_names_its_columns():
    v = TEST_VIEWS["jailbreak_attempts"]
    assert v.needs == {"Jailbreak success"}
    assert set(v.columns) == {"target", "run", "run_name", "system_version", "category", "language", "technique",
                              "reply_language", "reasoning_shown", "worked"}


def test_a_query_on_jailbreak_attempts_expands_to_one_the_check_accepts():
    sql = "SELECT category, target AS series, AVG(worked) AS value FROM jailbreak_attempts GROUP BY 1, 2"
    check(expand(sql, ALL), READERS)
