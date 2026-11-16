"""One delivery loop for the ledger outbox in Python: aisc_identity.ledger_delivery. An event the ledger refuses for
good (404, 409, 413, 422) is marked refused and the next one is sent; any other failure stops the pass, so the
order of the outbox is kept for the next one."""

import importlib
import importlib.util


def _delivery():
    assert importlib.util.find_spec("aisc_identity.ledger_delivery") is not None, \
        "no aisc_identity.ledger_delivery: the engine and the dashboard each keep their own delivery loop"
    return importlib.import_module("aisc_identity.ledger_delivery")


def test_the_refusals_are_the_ones_the_ledger_gives_for_good():
    assert _delivery().REFUSALS == (404, 409, 413, 422)


def test_a_refused_event_is_marked_and_the_next_one_sent():
    m = _delivery()
    rows = [{"id": 1}, {"id": 2}]
    sent, refused = [], []
    out = m.deliver(lambda n: rows, sent.append, lambda r, s, d: refused.append((r["id"], s)),
                    lambda e: (409, "dup") if e["id"] == 1 else (201, ""))
    assert out == (1, 1) and refused == [(1, 409)] and [r["id"] for r in sent] == [2]


def test_an_outage_stops_the_pass_and_keeps_the_order():
    m = _delivery()
    tried = []
    out = m.deliver(lambda n: [{"id": 1}, {"id": 2}], lambda r: None, lambda *a: None,
                    lambda e: tried.append(e["id"]) or (503, ""))
    assert out == (0, 0) and tried == [1]


def test_the_http_sender_tries_again_on_a_lost_connection_only():
    m = _delivery()
    calls = []

    def post(url, json, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise ConnectionError("lost")
        return 422, "bad"

    send = m.http_sender("http://ledger:8000/events", "fake-token", retries=(0, 0), post=post)
    assert send({"id": 1}) == (422, "bad") and len(calls) == 2
