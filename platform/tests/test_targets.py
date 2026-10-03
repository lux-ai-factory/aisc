"""Assessment targets: what an evaluation is
about, the system or one of its components. One row per target in the project's own database
(schema `target`, template 0014), each mirrored in the engine as a `resource` component that the
evaluation form offers. Runs on the throwaway; the engine is a local fake."""
from __future__ import annotations

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb, targets
from tests.conftest import needs_database
from tests.connection_support import EngineFake, Stub

pytestmark = needs_database
ALICE = "00000000-0000-0000-0000-00000000a11c"


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("ENGINE_URL", stub.base)


def one(dsn, pid, sql, params=()):
    with psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(pid))) as conn:
        return conn.execute(sql, params).fetchall()


def make(client, as_user, unique, stub, engine=False):
    made = client.post("/projects", json={"name": unique("tgt")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json(), None


# The table
def test_the_target_schema_is_made_in_every_project_database(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    cols = one(dsn, project["pid"], "select column_name from information_schema.columns where table_schema = 'target'"
                                    " and table_name = 'target' order by ordinal_position")
    assert [c[0] for c in cols] == ["key", "kind", "component_kind", "label", "first_card_number",
                                    "last_card_number", "engine_component", "created_at", "updated_at"]


def test_the_readers_read_targets_and_nothing_else_of_the_platform(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    rows = one(dsn, project["pid"], "select r, has_table_privilege(r, 'target.target', 'SELECT'),"
                                    " has_table_privilege(r, 'connection.endpoint', 'SELECT')"
                                    " from unnest(array['report_ro', 'dashboard_ro']) r"
                                    " where exists (select 1 from pg_roles where rolname = r)")
    assert rows and all(sel and not secret for _, sel, secret in rows)


# The system target, from the start

def test_tg1_a_new_project_has_its_system_target(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    assert one(dsn, project["pid"], "select key, kind, label from target.target") == [("system", "system", project["name"])]


def test_tg1_the_system_target_is_mirrored_in_the_engine_with_the_callers_token(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    engine = EngineFake(stub, project["pid"])
    targets.ensure_mirrors(project["pid"], "caller-token")
    mirror = engine.named(f"target:{project['pid']}/system")
    assert mirror and mirror["name"] == f"Target · System: {project['name']}" and mirror["component_type"] == "resource"
    assert one(dsn, project["pid"], "select engine_component::text from target.target where key = 'system'") == [(mirror["pid"],)]
    call = stub.requests("POST", f"/api/v1/projects/{engine.engine_pid}/components")[-1]
    assert call["headers"]["authorization"] == "Bearer caller-token"


def test_tg1_mirrors_are_made_once_and_found_again_by_their_value(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    engine = EngineFake(stub, project["pid"])
    targets.ensure_mirrors(project["pid"], "t")
    # the platform lost the pid (a half-finished sync): the next pass finds the mirror, makes no second one
    one(dsn, project["pid"], "update target.target set engine_component = null returning key")
    targets.ensure_mirrors(project["pid"], "t")
    assert len([c for c in engine.components if c["json_value"]["value"].endswith("/system")]) == 1
    assert one(dsn, project["pid"], "select engine_component is not null from target.target") == [(True,)]


def test_tg1_an_engine_that_does_not_answer_leaves_the_target_unmirrored_with_a_reason(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    stub.route("POST", f"/api/v1/projects/for-platform/{project['pid']}", (503, {"detail": "down"}))
    reason = targets.ensure_mirrors(project["pid"], "t")
    assert reason and "engine" in reason
    assert one(dsn, project["pid"], "select engine_component from target.target") == [(None,)]


def test_tg1_a_renamed_target_renames_its_mirror(client, as_user, unique, stub, dsn):
    project, _ = make(client, as_user, unique, stub, engine=False)
    engine = EngineFake(stub, project["pid"])
    targets.ensure_mirrors(project["pid"], "t")
    one(dsn, project["pid"], "update target.target set label = 'MCAS' where key = 'system' returning key")
    targets.ensure_mirrors(project["pid"], "t")
    assert engine.named(f"target:{project['pid']}/system")["name"] == "Target · System: MCAS"
