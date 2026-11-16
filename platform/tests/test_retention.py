"""A project may keep its runs for a set number of days; it is off unless an owner sets it. Only an owner
sets it, between 1 and 3650 days, and a sweep purges the runs that finished before the period. Without a
period nothing is ever swept. Runs on the throwaway."""
from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime, timedelta, timezone

from tests.conftest import ALICE, needs_database


def _retention():
    assert importlib.util.find_spec("platform_service.retention") is not None, \
        "no platform_service.retention: nothing ever removes old runs"
    return importlib.import_module("platform_service.retention")


@needs_database
def test_retention_is_off_for_a_new_project(make_project):
    made = make_project()
    assert "retention_days" in made, "a project does not say how long it keeps its runs"
    assert made["retention_days"] is None


@needs_database
def test_only_an_owner_sets_retention_and_only_within_bounds(client, as_user, make_project):
    slug = make_project(editors=("ed",))["slug"]
    assert client.put(f"/projects/{slug}/retention", json={"days": 30}, headers=as_user("ed")).status_code == 403
    for bad in (0, 3651, -1):
        assert client.put(f"/projects/{slug}/retention", json={"days": bad},
                          headers=as_user(ALICE)).status_code == 422
    assert client.put(f"/projects/{slug}/retention", json={"days": 30}, headers=as_user(ALICE)).status_code == 200
    assert client.get(f"/projects/{slug}", headers=as_user(ALICE)).json()["retention_days"] == 30
    assert client.put(f"/projects/{slug}/retention", json={"days": None}, headers=as_user(ALICE)).status_code == 200
    assert client.get(f"/projects/{slug}", headers=as_user(ALICE)).json()["retention_days"] is None


@needs_database
def test_without_a_retention_period_nothing_is_ever_swept(make_project):
    make_project()
    far = datetime.now(timezone.utc) + timedelta(days=4000)
    assert _retention().sweep(now=far) == {}


def test_the_retention_setting_is_in_the_ledger():
    from platform_service.ledger import registry
    action = registry.REGISTRY.get("project.retention_set")
    assert action is not None, "setting a project's retention leaves no ledger event"
    assert {"days_before", "days_after"} <= set(action.details_keys)


@needs_database
def test_a_run_older_than_the_period_is_deleted_and_a_newer_one_kept(client, as_user, make_project, monkeypatch):
    """The engine's two functions are stood in for: one old run and one new, ended 40 and 5 days ago."""
    import os
    import uuid

    import pytest

    from platform_service import run_purge
    from tests.conftest import project_db

    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("needs the throwaway's superuser to stand in for the engine's functions")
    made = make_project()
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with project_db(superuser, made, autocommit=True) as conn:
        conn.execute("CREATE TABLE engine.ended (pid uuid, ended timestamptz)")
        conn.execute("INSERT INTO engine.ended VALUES (%s, %s), (%s, %s)",
                     (old, now - timedelta(days=40), new, now - timedelta(days=5)))
        conn.execute("CREATE OR REPLACE FUNCTION engine.runs_finished_before(p timestamptz) RETURNS SETOF uuid"
                     " LANGUAGE sql AS $$ SELECT pid FROM engine.ended WHERE ended < p $$")
        conn.execute("CREATE OR REPLACE FUNCTION engine.purge_evaluation(p uuid) RETURNS jsonb LANGUAGE sql AS"
                     " $$ SELECT jsonb_build_object('artifacts', '[]'::jsonb, 'measures', 0,"
                     " 'evaluation_plugins', '[]'::jsonb) $$")
        conn.execute("GRANT USAGE ON SCHEMA engine TO platform_rw")
        conn.execute("GRANT SELECT ON engine.ended TO platform_rw")
        conn.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA engine TO platform_rw")
    deleted = []
    real = run_purge.purge_run
    monkeypatch.setattr(run_purge, "purge_run",
                        lambda pid, ev, by, reason: deleted.append((ev, by, reason)) or real(pid, ev, by, reason))
    assert _retention().sweep(now=now) == {}                     # no period yet: nothing goes
    assert client.put(f"/projects/{made['slug']}/retention", json={"days": 30},
                      headers=as_user(ALICE)).status_code == 200
    assert _retention().sweep(now=now) == {made["pid"]: 1}
    assert deleted == [(old, "retention", "retention: 30 days")]
