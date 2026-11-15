"""A call a run's plugin opened before its pass ended belongs to that run: when its answer comes back after the
worker ended the pass (a Stop, a sibling's failure, the plugin killed mid-call), the recorded call still names the
run's evaluation plugin, and the seal the ledger keeps counts the same calls as the trace. Runs on the throwaway;
the system under test is a local stub that answers only after the pass has ended."""
from __future__ import annotations

import threading
import time
import uuid

import psycopg
import pytest

from platform_service import run_passes
from tests.conftest import needs_database, project_db
from tests.http_stub import Canned
from tests.test_run_passes import _env, made_with_endpoints, stub  # noqa: F401  (fixtures)
from tests.test_run_trace import door, keyed, mint, run_key

pytestmark = needs_database


@pytest.fixture
def project(make_project, client, admin, stub):  # noqa: F811
    return made_with_endpoints(make_project, client, admin, stub)


def answer_after_the_pass_ends(run_pass, ended: list):
    """The stub's answer: it starts ending the pass while the call is open, and answers a little later."""
    def answer(_seen):
        worker = threading.Thread(target=lambda: ended.append(run_passes.revoke(run_pass)), daemon=True)
        worker.start()
        ended.append(worker)
        return Canned(200, b'{"answer": "late"}', delay=1.0)
    return answer


def ask_while_the_pass_ends(client, project, stub, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LEDGER_MODE", "record")
    plugin = str(uuid.uuid4())
    run_pass = mint(client, project, plugin)
    key = run_key(client, project, run_pass)
    stub.route("POST", "/chat", (200, {"answer": "first"}))
    assert client.post(door(project, "/aisc/ask"), json={"input": "q1"}, headers=keyed(key)).status_code == 200
    ended: list = []
    stub.route("POST", "/chat", answer_after_the_pass_ends(run_pass, ended))
    client.post(door(project, "/aisc/ask"), json={"input": "q2"}, headers=keyed(key))
    for item in ended:
        if isinstance(item, threading.Thread):
            item.join(timeout=30)
    time.sleep(0.2)
    return plugin


def test_a_call_answered_after_its_pass_ended_still_names_its_test(client, project, stub, dsn, monkeypatch):  # noqa: F811
    plugin = ask_while_the_pass_ends(client, project, stub, monkeypatch)
    with project_db(dsn, project) as conn:
        rows = conn.execute("SELECT seq, evaluation_plugin::text FROM trace.call ORDER BY seq").fetchall()
    assert [tuple(r) for r in rows] == [(1, plugin), (2, plugin)]


def test_the_seal_counts_every_call_the_trace_holds(client, project, stub, dsn, monkeypatch):  # noqa: F811
    from tests.conftest import DSN

    plugin = ask_while_the_pass_ends(client, project, stub, monkeypatch)
    with project_db(dsn, project) as conn:
        traced = conn.execute("SELECT count(*) FROM trace.call").fetchone()[0]
    with psycopg.connect(DSN) as conn:
        seals = [r[0] for r in conn.execute("SELECT details FROM core.outbox WHERE action = 'run.trace.sealed'"
                                            " AND item_id = %s", (plugin,)).fetchall()]
    assert traced == 2
    assert [s["calls"] for s in seals] == [traced]
