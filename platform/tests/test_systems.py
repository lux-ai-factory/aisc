"""The AI system under assessment: named once, referenced by every module.

Qualification describes a system, the engine tests it, and the dashboard reads
what the tests produced. For any of that to join up they have to mean the same
system, which is what `core.system` is: one row, inside one project, written by
the platform and read by everyone else.

These tests are about identity rules, so they need no database.
"""
import pytest

from platform_service.systems import InvalidSystem, normalise_version, system_key


def test_a_system_is_known_by_its_name_and_version_inside_a_project():
    assert system_key("MCAS", "1.2.0") == ("MCAS", "1.2.0")


def test_surrounding_space_is_not_part_of_a_name():
    assert system_key("  MCAS  ", " 1.2.0 ") == ("MCAS", "1.2.0")


def test_a_system_with_no_name_is_refused_rather_than_stored_blank():
    with pytest.raises(InvalidSystem):
        system_key("   ", "1.0")


def test_a_version_is_optional_because_not_every_system_has_one():
    # An unversioned system is a system, and two of them in one project are the
    # same system: the empty version is stored as nothing, never as "".
    assert system_key("MCAS", "") == ("MCAS", None)
    assert system_key("MCAS", None) == ("MCAS", None)


def test_a_version_keeps_what_was_written_apart_from_space():
    # No opinion about v-prefixes or PEP 440 here: a system's version is
    # whatever its makers call it, and guessing would merge two real systems.
    assert normalise_version(" v1.2.0-rc1 ") == "v1.2.0-rc1"
    assert normalise_version("   ") is None
