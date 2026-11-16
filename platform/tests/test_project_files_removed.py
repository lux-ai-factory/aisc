"""Deleting a project removes its files from the shared buckets (datasets, models, artifacts), not only its
proof bucket: the engine names them with engine.stored_objects() before the database is dropped, and the
platform deletes them once it is. A file the store will not delete is kept in core.leftover_object with its
project, for the sweep. Runs on the throwaway; the store is in memory."""
from __future__ import annotations

import os

import psycopg
import pytest

from platform_service import proof_store
from tests.conftest import needs_database
from tests.proof_fake import FakeStore

ADMIN = ("root", ("admin",))


class SharedBucketsStore(FakeStore):
    """The in-memory store, with the bulk delete the platform is to use; `refuse_delete` keeps every file."""

    def __init__(self) -> None:
        super().__init__()
        self.refuse_delete = False

    def remove_objects(self, bucket: str, names: list[str]) -> list[str]:
        self._check()
        if self.refuse_delete:
            return list(names)
        for name in names:
            self.buckets.get(bucket, {}).pop(name, None)
        return []


@pytest.fixture
def store(monkeypatch):
    s = SharedBucketsStore()
    monkeypatch.setattr(proof_store, "store", lambda: s)
    monkeypatch.setenv("LEDGER_MODE", "off")
    monkeypatch.setattr("platform_service.dashboard_bridge.unregister", lambda pid: True)
    monkeypatch.setattr("platform_service.dashboard_bridge.register", lambda *a: True)
    return s


@pytest.fixture
def project_with_a_file(make_project, store):
    """A project whose engine holds one artifact, and another project's artifact in the same bucket."""
    made = make_project()
    ours, theirs = f"{made['pid']}-run.json", "another-projects-run.json"
    store.make_bucket("artifacts")
    store.put("artifacts", ours, b"{}", "application/json", {})
    store.put("artifacts", theirs, b"{}", "application/json", {})
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    if not superuser:
        pytest.skip("needs the throwaway's superuser to stand in for the engine's function")
    from psycopg.conninfo import make_conninfo
    from platform_service import projectdb
    with psycopg.connect(make_conninfo(superuser, dbname=projectdb.database_name(made["pid"])),
                         autocommit=True) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION engine.stored_objects() RETURNS TABLE(bucket text, name text)"
            f" LANGUAGE sql AS $$ SELECT 'artifacts'::text, '{ours}'::text $$")
        conn.execute("GRANT EXECUTE ON FUNCTION engine.stored_objects() TO PUBLIC")
    return made, ours, theirs


def _delete(client, made, headers):
    return client.request("DELETE", f"/projects/{made['slug']}", json={"confirm_name": made["name"]}, headers=headers)


@needs_database
def test_deleting_a_project_removes_its_files_from_the_shared_buckets(client, as_user, store, project_with_a_file):
    made, ours, theirs = project_with_a_file
    assert _delete(client, made, as_user(*ADMIN)).status_code == 204
    assert set(store.buckets["artifacts"]) == {theirs}, "the deleted project's run file is still stored"


@needs_database
def test_a_file_left_behind_is_recorded_with_its_project(client, as_user, dsn, store, project_with_a_file):
    made, ours, _ = project_with_a_file
    store.refuse_delete = True
    assert _delete(client, made, as_user(*ADMIN)).status_code == 204
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT to_regclass('core.leftover_object')").fetchone()[0] is not None, \
            "no core.leftover_object: a file the store kept is forgotten"
        rows = conn.execute("SELECT pid::text, bucket, name FROM core.leftover_object WHERE name = %s",
                            (ours,)).fetchall()
    assert rows == [(made["pid"], "artifacts", ours)]


def test_the_real_store_can_remove_files_and_say_which_it_kept():
    assert hasattr(proof_store.MinioStore, "remove_objects"), \
        "the store has no remove_objects(bucket, names) -> names it could not remove"
