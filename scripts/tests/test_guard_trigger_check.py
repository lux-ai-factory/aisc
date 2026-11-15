"""The stack check alarms on a guard trigger that is missing, disabled, or on a table its owner role lost.

`scripts/verify.sh --stack` runs scripts/verify-guard-triggers.sh, which calls
stackcheck.guard_triggers.problems(dsn_template, guards) for every project database. The guards are the
lines of init/guard-triggers.txt. A clean bed, set up as postgres-setup and every module set up a stack,
reports nothing; each way of lifting a guard is reported.

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        pytest -q -p no:cacheprovider test_guard_trigger_check.py
"""

from __future__ import annotations

import importlib
import sys

import pytest

import isolation_bed as ib
import owner_roles_bed as ob
from conftest import ROOT

DB = ib.project_db(ib.B)

#: guards that exist today and those the owner-role and append-only work adds; each must be listed.
EXPECTED_GUARDS = {
    ("trace.call", "call_append_only"),
    ("trace.call", "call_no_truncate"),
    ("project.system", "system_no_delete"),
    ("project.system", "system_no_truncate"),
    ("qualification.card_history", "card_history_is_append_only"),
    ("qualification.card_history", "card_history_is_not_truncated"),
    ("qualification.qualification", "qualification_only_latest_changes"),
    ("control_objectives.mapping_archive", "mapping_archive_is_append_only"),
    ("control_objectives.mapping_archive", "mapping_archive_is_never_truncated"),
    ("report_composer.layout_revision", "layout_revision_is_append_only"),
    ("report_composer.layout_revision", "layout_revision_is_never_truncated"),
    ("engine.aisc_backend_measurement", "aisc_backend_measurement_append_only"),
    ("engine.aisc_backend_observation", "aisc_backend_observation_append_only"),
    ("engine.aisc_backend_ledgeroutbox", "ledgeroutbox_only_marks"),
    ("engine.aisc_backend_pluginconfig", "pluginconfig_is_fixed"),
    ("engine.aisc_backend_evaluation", "evaluation_system_is_fixed"),
}


def _check():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module("stackcheck.guard_triggers")
    except ModuleNotFoundError:
        pytest.fail("scripts/stackcheck/guard_triggers.py does not exist: nothing alarms on a lifted guard")


@pytest.fixture(scope="module")
def bed():
    b = ob.build("guard-check")
    yield b
    b.stop()


def _template(bed) -> str:
    return f"postgresql://{ib.SU}:{bed.t.password}@127.0.0.1:{bed.port}/{{database}}"


def _problems(bed) -> list[str]:
    return _check().problems(_template(bed), ob.guards())


def test_the_guard_list_names_every_guard():
    listed = set(ob.guards())
    assert ob.GUARD_LIST.exists(), "init/guard-triggers.txt is missing"
    assert EXPECTED_GUARDS <= listed, f"not listed: {sorted(EXPECTED_GUARDS - listed)}"


def test_a_clean_stack_reports_nothing(bed):
    assert _problems(bed) == []


def test_a_disabled_guard_is_reported_even_when_the_alarm_trigger_was_dropped_first(bed):
    """Only the superuser can do this: the event trigger refuses everyone else, so it is dropped first."""
    ob.as_su(bed, DB, "DROP EVENT TRIGGER IF EXISTS aisc_guard_triggers_stay")
    _, err = ob.as_su(bed, DB, "ALTER TABLE trace.call DISABLE TRIGGER call_append_only")
    assert not err, err
    try:
        found = _problems(bed)
        assert f"disabled: {DB} trace.call call_append_only" in found, found
    finally:
        ob.as_su(bed, DB, "ALTER TABLE trace.call ENABLE TRIGGER call_append_only")


def test_a_missing_guard_is_reported(bed):
    """The alarm on a drop is its own event trigger: only the superuser can drop it first."""
    ob.as_su(bed, DB, "DROP EVENT TRIGGER IF EXISTS aisc_guard_triggers_stay")
    ob.as_su(bed, DB, "DROP EVENT TRIGGER IF EXISTS aisc_guard_triggers_stay_on_drop")
    definition, _ = ob.as_su(bed, DB, "SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname = 'call_no_truncate'")
    _, err = ob.as_su(bed, DB, "DROP TRIGGER call_no_truncate ON trace.call")
    assert not err, err
    try:
        found = _problems(bed)
        assert f"missing: {DB} trace.call call_no_truncate" in found, found
    finally:
        ob.as_su(bed, DB, definition + ";")


def test_a_guarded_table_owned_by_the_runtime_role_is_reported(bed):
    owner = bed.scalar(DB, "SELECT tableowner FROM pg_tables WHERE schemaname = 'qualification'"
                           " AND tablename = 'card_history'")
    _, err = ob.as_su(bed, DB, "ALTER TABLE qualification.card_history OWNER TO qualification_rw")
    assert not err, err
    try:
        found = _problems(bed)
        assert f"owner: {DB} qualification.card_history is owned by qualification_rw" in found, found
    finally:
        ob.as_su(bed, DB, f"ALTER TABLE qualification.card_history OWNER TO {owner}")


def test_the_stack_check_runs_the_guard_check():
    script = ROOT / "scripts/verify-guard-triggers.sh"
    assert script.exists(), "scripts/verify-guard-triggers.sh is missing"
    assert "verify-guard-triggers.sh" in (ROOT / "scripts/verify.sh").read_text(), \
        "scripts/verify.sh --stack does not run the guard check"
