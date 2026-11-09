"""The platform stops a run whose calls keep failing, whatever the plugin: after 3 failed calls in a row, or once
more than 5% of at least 20 calls failed, the next call of that run is not sent to the system under test. It is
recorded not_sent with the reason and refused to the plugin (403, never a status a client retries). Only calls
actually sent count; a new run starts from zero. Runs on the throwaway; the system under test is a local stub."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.test_run_passes import _env, stub  # noqa: F401  (fixtures)
from tests.test_run_trace import ASK, calls_of, door, keyed, mint, project, run_key, trace  # noqa: F401

pytestmark = needs_database

OK, FAILED = (200, {"answer": "Humanitas Eindhoven."}), (401, {"detail": "bad key"})


def ask(client, project, key, body=None):
    return client.post(door(project, "/aisc/ask"), json=body or {"input": "Who helps with debts?"}, headers=keyed(key))


def sent(stub):
    return len(stub.requests("POST", "/chat"))


def a_run(client, project):
    run_pass = mint(client, project)
    return run_pass, run_key(client, project, run_pass)


def test_three_failed_calls_in_a_row_stop_the_run_before_the_fourth_is_sent(client, project, stub):
    stub.route("POST", "/chat", FAILED)
    run_pass, key = a_run(client, project)
    for _ in range(3):
        assert ask(client, project, key).status_code == 502
    r = ask(client, project, key)

    assert r.status_code == 403, r.text
    assert r.json()["error"] == "run_stopped"
    assert r.json()["detail"].startswith("the platform stopped this run: 3 calls in a row failed; the last: auth")
    assert sent(stub) == 3
    last = calls_of(trace(client, run_pass))[-1]
    assert (last["outcome"], last["error"]["code"]) == ("not_sent", "run_stopped")


def test_a_call_that_works_resets_the_count_in_a_row(client, project, stub):
    stub.route("POST", "/chat", FAILED, FAILED, OK, FAILED, FAILED, OK)
    _, key = a_run(client, project)
    assert [ask(client, project, key).status_code for _ in range(6)] == [502, 502, 200, 502, 502, 200]
    assert sent(stub) == 6


def test_more_than_five_percent_failed_of_twenty_calls_stops_the_run(client, project, stub):
    stub.route("POST", "/chat", *([OK] * 9 + [FAILED] + [OK] * 9 + [FAILED] + [OK]))   # 2 of 20 failed
    _, key = a_run(client, project)
    statuses = [ask(client, project, key).status_code for _ in range(21)]

    assert statuses[:20] == [200] * 9 + [502] + [200] * 9 + [502]
    assert statuses[20] == 403
    assert sent(stub) == 20


def test_one_failed_call_of_twenty_is_within_the_rate(client, project, stub):
    stub.route("POST", "/chat", *([OK] * 10 + [FAILED] + [OK] * 10))
    _, key = a_run(client, project)
    assert [ask(client, project, key).status_code for _ in range(21)].count(403) == 0


def test_a_stopped_run_stays_stopped_and_a_new_run_starts_from_zero(client, project, stub):
    stub.route("POST", "/chat", FAILED)
    _, key = a_run(client, project)
    for _ in range(3):
        ask(client, project, key)
    stub.route("POST", "/chat", OK)                     # the system answers again

    assert ask(client, project, key).status_code == 403
    assert ask(client, project, key).status_code == 403
    _, fresh = a_run(client, project)
    assert ask(client, project, fresh).status_code == 200


def test_requests_the_platform_does_not_send_do_not_count(client, project, stub):
    stub.route("POST", "/chat", OK)
    _, key = a_run(client, project)
    for _ in range(5):
        assert ask(client, project, key, {"input": "q", "history": "not a list"}).status_code == 400
    assert ask(client, project, key).status_code == 200


@pytest.mark.parametrize("name", sorted(ASK))
def test_every_door_refuses_a_stopped_run_in_its_own_terms(client, project, stub, name):
    stub.route("POST", "/chat", FAILED)
    _, key = a_run(client, project)
    for _ in range(3):
        ask(client, project, key)
    path, body = ASK[name]
    r = client.post(door(project, path), json=body, headers=keyed(key))

    if name == "a2a":
        assert r.status_code == 200 and "the platform stopped this run" in r.json()["error"]["message"]
    else:
        assert r.status_code == 403, r.text
        assert "the platform stopped this run" in r.text
    if name == "openai":
        assert r.json()["error"]["code"] == "run_stopped"
    assert sent(stub) == 3


def test_the_rules_can_be_set_and_turned_off(client, project, stub, monkeypatch):
    monkeypatch.setenv("PLATFORM_RUN_STOP_IN_A_ROW", "0")
    monkeypatch.setenv("PLATFORM_RUN_STOP_RATE", "0")
    stub.route("POST", "/chat", FAILED)
    _, key = a_run(client, project)
    assert [ask(client, project, key).status_code for _ in range(25)] == [502] * 25

    monkeypatch.setenv("PLATFORM_RUN_STOP_IN_A_ROW", "5")
    _, key = a_run(client, project)
    assert [ask(client, project, key).status_code for _ in range(6)] == [502] * 5 + [403]


def test_a_setting_that_is_not_a_number_keeps_the_default(monkeypatch):
    from platform_service import run_stop

    monkeypatch.setenv("PLATFORM_RUN_STOP_IN_A_ROW", "many")
    monkeypatch.setenv("PLATFORM_RUN_STOP_RATE", "a lot")
    assert (run_stop.in_a_row(), run_stop.rate(), run_stop.after()) == (3, 0.05, 20)
