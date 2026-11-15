"""Owner roles, migrator logins and the per-database setup that postgres-setup installs.

Every module schema belongs to a NOLOGIN owner role. A LOGIN migrator, member of that owner, starts its
sessions as the owner and is the only way to reach it; the runtime roles the apps connect as are not
members. A few superuser functions do what the owners may not do themselves, and an event trigger keeps
a listed guard trigger from being disabled or dropped by anyone but the superuser.

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        pytest -q -p no:cacheprovider test_owner_roles.py
"""

from __future__ import annotations

import pytest

import isolation_bed as ib
import owner_roles_bed as ob

MODULES = ("qualification", "controls", "control_objectives", "report_composer", "engine", "platform")
DB = ib.project_db(ib.A)


@pytest.fixture(scope="module")
def bed():
    b = ob.build("owners", modules=False)
    yield b
    b.stop()


def _login_kind(bed, role):
    return bed.scalar("platform", f"""SELECT coalesce((SELECT CASE WHEN rolcanlogin THEN 'login' ELSE 'nologin' END
                                        FROM pg_roles WHERE rolname = '{role}'), 'missing')""")


@pytest.mark.parametrize("module", MODULES)
def test_each_owner_role_exists_and_cannot_log_in(bed, module):
    assert _login_kind(bed, f"{module}_owner") == "nologin"


@pytest.mark.parametrize("module", MODULES)
def test_a_migrator_session_acts_as_its_owner(bed, module):
    out, err = ob.as_role(bed, "platform", f"{module}_migrator", "SELECT current_user")
    assert out == f"{module}_owner", f"{module}_migrator: {err[-200:]}"


@pytest.mark.parametrize("module", MODULES)
def test_runtime_roles_are_not_members_of_their_owner(bed, module):
    member = bed.scalar("platform", f"""
        SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{module}_owner') THEN 'no owner role'
                    WHEN pg_has_role('{module}_rw', '{module}_owner', 'MEMBER') THEN 'member'
                    ELSE 'not a member' END""")
    assert member == "not a member"


@pytest.mark.parametrize("module", MODULES)
def test_each_owner_can_act_for_its_runtime_role(bed, module):
    """So the reassignment migration can hand the runtime role's objects to the owner."""
    member = bed.scalar("platform", f"""
        SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{module}_owner') THEN 'no owner role'
                    WHEN pg_has_role('{module}_owner', '{module}_rw', 'MEMBER') THEN 'member'
                    ELSE 'not a member' END""")
    assert member == "member"


def test_only_the_platform_owner_may_create_databases(bed):
    assert bed.scalar("platform", "SELECT rolcreatedb FROM pg_roles WHERE rolname = 'platform_rw'") == "f"
    assert bed.scalar("platform", "SELECT coalesce((SELECT rolcreatedb::text FROM pg_roles"
                                  " WHERE rolname = 'platform_owner'), 'missing')") == "true"


def test_platform_rw_cannot_signal_other_sessions(bed):
    assert bed.scalar("platform", "SELECT pg_has_role('platform_rw', 'pg_signal_backend', 'MEMBER')") == "f"


def test_handing_a_schema_to_its_owner_refuses_a_platform_schema(bed):
    _, err = ob.as_role(bed, DB, "platform_migrator", "SELECT aisc_setup.hand_schema_to_owner('trace')")
    assert "refused" in err, err[-300:]


def test_the_runtime_role_may_not_hand_schemas_over(bed):
    _, err = ob.as_role(bed, DB, "platform_rw", "SELECT aisc_setup.hand_schema_to_owner('qualification')")
    assert "permission denied for function hand_schema_to_owner" in err, err[-300:]


def test_ending_sessions_refuses_a_database_that_is_not_a_project(bed):
    _, err = ob.as_role(bed, "platform", "platform_migrator", "SELECT aisc_setup.end_project_sessions('keycloak')")
    assert "refused" in err, err[-300:]


def test_the_runtime_role_may_not_end_sessions(bed):
    _, err = ob.as_role(bed, "platform", "platform_rw", f"SELECT aisc_setup.end_project_sessions('{DB}')")
    assert "permission denied for function end_project_sessions" in err, err[-300:]


def test_the_guard_catalogue_lists_the_trace_guard(bed):
    out, err = ob.as_su(bed, DB, "SELECT count(*) FROM aisc_setup.guard_trigger"
                                 " WHERE table_name = 'trace.call' AND trigger_name = 'call_append_only'")
    assert out == "1", err[-300:]


def _listed_probe(bed, name):
    """A guarded table owned by platform_owner, listed in the guard catalogue, as the superuser makes it."""
    out, err = ob.as_su(bed, DB, f"""
        CREATE TABLE trace.{name} (id int);
        CREATE FUNCTION trace.{name}_refuse() RETURNS trigger LANGUAGE plpgsql AS
          $$ BEGIN RAISE EXCEPTION 'append only'; END $$;
        CREATE TRIGGER {name}_append_only BEFORE UPDATE OR DELETE ON trace.{name}
          FOR EACH ROW EXECUTE FUNCTION trace.{name}_refuse();
        ALTER TABLE trace.{name} OWNER TO platform_owner;
        INSERT INTO aisc_setup.guard_trigger (table_name, trigger_name) VALUES ('trace.{name}', '{name}_append_only');
    """)
    assert not err, f"could not list a guard as the superuser: {err[-300:]}"


def test_disabling_a_listed_guard_is_refused_even_for_its_owner(bed):
    _listed_probe(bed, "probe_disable")
    _, err = ob.as_role(bed, DB, "platform_migrator",
                        "ALTER TABLE trace.probe_disable DISABLE TRIGGER probe_disable_append_only")
    assert "cannot be disabled or dropped" in err, err[-300:]
    assert bed.scalar(DB, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'probe_disable_append_only'") == "O"


def test_dropping_a_listed_guard_is_refused_even_for_its_owner(bed):
    _listed_probe(bed, "probe_drop")
    _, err = ob.as_role(bed, DB, "platform_migrator", "DROP TRIGGER probe_drop_append_only ON trace.probe_drop")
    assert "cannot be disabled or dropped" in err, err[-300:]


def test_a_project_database_made_after_setup_has_the_guard_alarm(bed):
    assert bed.scalar(DB, "SELECT count(*) FROM pg_event_trigger WHERE evtname = 'aisc_guard_triggers_stay'"
                          " AND evtenabled = 'O'") == "1"


def test_the_setup_runs_twice_without_change(bed):
    path = ob.INIT / "project-database-setup.sql"
    assert path.exists(), "init/project-database-setup.sql is missing"
    r = bed.psql(DB, path.read_text())
    assert r.returncode == 0, ib._redact(bed, r.stderr[-300:])


# the inspector reads by schema


def test_the_inspector_reads_no_connection_schema(bed):
    assert bed.scalar(DB, "SELECT has_schema_privilege('inspector_ro', 'connection', 'USAGE')") == "f"
    assert bed.scalar(DB, "SELECT has_schema_privilege('inspector_ro', 'llm', 'USAGE')") == "f"
    assert bed.scalar(DB, "SELECT has_schema_privilege('inspector_ro', 'helper', 'USAGE')") == "f"


def test_the_inspector_still_reads_the_run_trace(bed):
    assert bed.scalar(DB, "SELECT has_table_privilege('inspector_ro', 'trace.call', 'SELECT')") == "t"


def test_the_inspector_is_not_a_reader_of_all_data(bed):
    assert bed.scalar("platform", "SELECT pg_has_role('inspector_ro', 'pg_read_all_data', 'MEMBER')") == "f"


def test_nobody_connects_to_the_platform_database_by_default(bed):
    assert bed.scalar("platform", "SELECT has_database_privilege('public', 'platform', 'CONNECT')") == "f"
    assert bed.scalar("platform", "SELECT has_database_privilege('public', 'platform', 'TEMPORARY')") == "f"


def test_the_setup_lists_the_same_guards_as_the_guard_list():
    """postgres-setup runs the setup from standard input in the beds, so it holds the list itself."""
    import re

    text = (ob.INIT / "project-database-setup.sql").read_text()
    block = text[text.index("WITH listed"):text.index("), unlisted")]
    in_setup = set(re.findall(r"\('([^']+)', '([^']+)'\)", block))
    assert in_setup == set(ob.guards())
