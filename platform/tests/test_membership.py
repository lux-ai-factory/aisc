"""Who may do what inside a project.

Three roles, ordered. A viewer reads, an editor changes the work, an owner also
decides who else is in. The rules live here, with no database and no web
framework, because they are the part worth reasoning about on their own.
"""
import pytest

from platform_service.membership import (
    InvalidMembership,
    ROLES,
    at_least,
    may_manage_members,
    may_write,
    validate_role,
)


def test_the_three_roles_are_ordered_from_least_to_most():
    assert ROLES == ("viewer", "editor", "owner")


def test_a_role_covers_everything_below_it():
    assert at_least("owner", "viewer")
    assert at_least("owner", "editor")
    assert at_least("editor", "viewer")
    assert at_least("viewer", "viewer")


def test_a_role_does_not_cover_what_is_above_it():
    assert not at_least("viewer", "editor")
    assert not at_least("editor", "owner")


def test_no_role_at_all_covers_nothing():
    """A non-member is not a viewer. Absence is not the bottom of the ladder."""
    assert not at_least(None, "viewer")


def test_writing_takes_an_editor():
    assert may_write("owner")
    assert may_write("editor")
    assert not may_write("viewer")
    assert not may_write(None)


def test_deciding_who_is_in_takes_an_owner():
    assert may_manage_members("owner")
    assert not may_manage_members("editor")
    assert not may_manage_members("viewer")
    assert not may_manage_members(None)


def test_a_role_that_is_not_one_of_the_three_is_refused_not_guessed():
    for bad in ("admin", "Owner", "", None, "superuser"):
        with pytest.raises(InvalidMembership):
            validate_role(bad)


def test_a_good_role_comes_back_as_given():
    assert validate_role("editor") == "editor"
