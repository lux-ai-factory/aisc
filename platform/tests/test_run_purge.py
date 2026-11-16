"""An owner may delete a run: its recorded calls, measures and artifacts go, and a tombstone keeps how many
calls there were and the chain's last hash, so the ledger still proves what was removed. Only an owner, only
by naming the run again, and with a reason. The app role still cannot delete a recorded call by itself; only
the purge function, owned by the schema's owner role, may. A file that cannot be deleted from the store is
kept in core.leftover_object for the next sweep. Runs on the throwaway."""
from __future__ import annotations

import importlib.util
import uuid

import psycopg
import pytest

from platform_service import run_trace
from platform_service.ledger import registry
from tests.conftest import needs_database, project_db


@pytest.fixture
def a_finished_run(make_project, monkeypatch):
    """A project of Alice with editor ed and viewer vic, and a test whose two calls were recorded."""
    project = make_project(editors=("ed",), viewers=("vic",))
    plugin = str(uuid.uuid4())
    run = "key:" + uuid.uuid4().hex + uuid.uuid4().hex
    monkeypatch.setattr(run_trace, "_evaluation_plugin", lambda _run: plugin)
    for question in ("first", "second"):
        started = run_trace.now()
        run_trace.record(project["pid"], run, "system-chat", "aisc", {"input": question}, "answered",
                         {"output": "ok"}, None, started, run_trace.now())
    return {"project": project, "plugin": plugin, "run": run, "evaluation": str(uuid.uuid4())}


def _purge(client, headers, project, evaluation, reason="asked by the data subject", confirm=None):
    return client.request("DELETE", f"/projects/{project['slug']}/runs/{evaluation}",
                          json={"reason": reason, "confirm": confirm or evaluation}, headers=headers)


@needs_database
def test_only_an_owner_deletes_a_run(client, as_user, a_finished_run):
    p, ev = a_finished_run["project"], a_finished_run["evaluation"]
    for who in ("ed", "vic"):
        assert _purge(client, as_user(who), p, ev).status_code == 403, \
            f"{who} is answered as if no run deletion existed"


@needs_database
def test_a_run_is_deleted_only_when_named_again_and_with_a_reason(client, as_user, a_finished_run):
    p, ev = a_finished_run["project"], a_finished_run["evaluation"]
    alice = as_user("00000000-0000-0000-0000-00000000a11c")
    assert _purge(client, alice, p, ev, confirm=str(uuid.uuid4())).status_code == 422
    assert _purge(client, alice, p, ev, reason="").status_code == 422


@needs_database
def test_the_trace_keeps_a_tombstone_with_the_chain_digest(dsn, a_finished_run):
    p, plugin, run = a_finished_run["project"], a_finished_run["plugin"], a_finished_run["run"]
    digest_before = run_trace.calls(p["pid"], run)[-1]["hash"]
    with project_db(dsn, p) as conn:
        purge = conn.execute("SELECT to_regprocedure('trace.purge_runs(uuid[], text, text)')").fetchone()[0]
        assert purge is not None, "no trace.purge_runs: a run's recorded calls can never be removed"
        conn.execute("SELECT trace.purge_runs(%s::uuid[], 'alice', 'asked')", ([plugin],))
        conn.commit()
        assert conn.execute("SELECT calls, digest FROM trace.purged").fetchone() == (2, digest_before)
        assert conn.execute("SELECT count(*) FROM trace.call").fetchone()[0] == 0


@needs_database
def test_the_app_role_still_cannot_delete_a_call(dsn, a_finished_run):
    # refused by its missing DELETE right, or by the append-only guard behind it
    with project_db(dsn, a_finished_run["project"]) as conn, \
            pytest.raises(psycopg.Error, match="append-only|permission denied"):
        conn.execute("DELETE FROM trace.call")


@needs_database
def test_a_file_left_behind_has_a_place_to_wait_for_the_sweep(dsn):
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT to_regclass('core.leftover_object')").fetchone()[0] is not None, \
            "no core.leftover_object: a file the store would not delete is forgotten"


def test_the_purge_lives_in_one_module_the_sweep_can_call():
    assert importlib.util.find_spec("platform_service.run_purge") is not None, \
        "no platform_service.run_purge (purge_run, retry_leftovers)"


def test_the_purge_is_in_the_ledger_with_what_remained():
    action = registry.REGISTRY.get("run.purged")
    assert action is not None, "the ledger has no run.purged action"
    assert action.content_required
    assert {"reason", "artifacts", "measures", "calls", "trace_digests", "leftover_objects"} <= set(action.details_keys)


class _RefusingStore:
    """A store that keeps every file it is asked to remove."""

    def remove_objects(self, bucket, names):
        return list(names)


@needs_database
def test_an_owner_deletes_a_run_and_a_file_the_store_kept_waits_for_the_sweep(client, as_user, dsn, a_finished_run,
                                                                             monkeypatch):
    import os

    from platform_service import proof_store, run_purge
    from tests.conftest import ALICE

    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("needs the throwaway's superuser to stand in for the engine's function")
    p, ev, plugin = a_finished_run["project"], a_finished_run["evaluation"], a_finished_run["plugin"]
    left = f"{ev}-calls.jsonl"
    with project_db(superuser, p, autocommit=True) as conn:              # the engine's function, stood in for
        conn.execute(
            "CREATE OR REPLACE FUNCTION engine.purge_evaluation(p uuid) RETURNS jsonb LANGUAGE sql AS"
            f" $$ SELECT CASE WHEN p = '{ev}'::uuid THEN jsonb_build_object('artifacts', jsonb_build_array('{left}'),"
            f" 'measures', 3, 'evaluation_plugins', jsonb_build_array('{plugin}')) END $$")
        conn.execute("GRANT USAGE ON SCHEMA engine TO platform_rw")
        conn.execute("GRANT EXECUTE ON FUNCTION engine.purge_evaluation(uuid) TO platform_rw")
    monkeypatch.setattr(proof_store, "store", lambda: _RefusingStore())
    answer = _purge(client, as_user(ALICE), p, ev)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"artifacts": 1, "measures": 3, "calls": 2, "leftover_objects": [left],
                             "trace_digests": {a_finished_run["run"]: answer.json()["trace_digests"][a_finished_run["run"]]}}
    assert ("artifacts", left) in run_purge.leftover_objects()
    assert _purge(client, as_user(ALICE), p, str(uuid.uuid4())).status_code == 404
    with project_db(dsn, p) as conn:
        assert conn.execute("SELECT count(*) FROM trace.call").fetchone()[0] == 0
