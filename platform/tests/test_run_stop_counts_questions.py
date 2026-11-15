# ruff: noqa: F811  (pytest fixtures imported from the other run-stop tests)
"""The platform stops a run whose questions keep failing, not one whose plugin retried a single question.

A plugin that asks one question again after it failed (its own retry, with the same input) makes several failed
calls of one question. Counted as failures in a row, one bad question stopped a two-hour run. The rule counts
failed questions: retries of one question count once, and three different questions failing in a row still stop
the run. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

from tests.conftest import needs_database
from tests.test_run_passes import _env, stub  # noqa: F401  (fixtures)
from tests.test_run_trace import door, keyed, mint, project, run_key  # noqa: F401

pytestmark = needs_database

OK, FAILED = (200, {"answer": "Humanitas Eindhoven."}), (401, {"detail": "bad key"})


def ask(client, project, key, question):
    return client.post(door(project, "/aisc/ask"), json={"input": question}, headers=keyed(key))


def a_run(client, project):
    return run_key(client, project, mint(client, project))


def test_a_plugin_retrying_one_question_does_not_stop_the_run(client, project, stub):
    stub.route("POST", "/chat", FAILED, FAILED, FAILED, OK)
    key = a_run(client, project)
    retries = [ask(client, project, key, "Who helps with debts?").status_code for _ in range(3)]
    next_question = ask(client, project, key, "Where do I find a lawyer?")

    assert retries == [502, 502, 502]
    assert next_question.status_code == 200, next_question.text


def test_three_different_questions_failing_in_a_row_still_stop_the_run(client, project, stub):
    stub.route("POST", "/chat", FAILED)
    key = a_run(client, project)
    statuses = [ask(client, project, key, q).status_code for q in ("one?", "two?", "three?", "four?")]
    assert statuses == [502, 502, 502, 403]
