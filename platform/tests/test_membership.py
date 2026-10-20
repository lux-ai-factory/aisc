"""The roles a member route accepts: the three of aisc_identity.access, nothing guessed."""
import pytest

from platform_service.membership import InvalidMembership, validate_role


def test_a_role_that_is_not_one_of_the_three_is_refused_not_guessed():
    for bad in ("admin", "Owner", "", None, "superuser"):
        with pytest.raises(InvalidMembership):
            validate_role(bad)


def test_a_good_role_comes_back_as_given():
    assert validate_role("editor") == "editor"
