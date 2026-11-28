"""The caller: the few claims the platform actually uses, named once."""
from aisc_identity import Caller, caller_from_claims


def test_the_claims_the_platform_uses():
    caller = caller_from_claims(
        {
            "sub": "abc",
            "email": "a@b.c",
            "preferred_username": "alice",
            "realm_access": {"roles": ["admin", "primary-user"]},
        }
    )
    assert caller == Caller(subject="abc", email="a@b.c", username="alice", roles=("admin", "primary-user"))


def test_a_missing_role_block_is_no_roles_not_an_error():
    assert caller_from_claims({"sub": "abc"}).roles == ()


def test_has_role():
    caller = caller_from_claims({"sub": "a", "realm_access": {"roles": ["admin"]}})
    assert caller.has_role("admin")
    assert not caller.has_role("primary-user")


def test_a_caller_without_a_subject_is_not_a_caller():
    """Every authorisation decision keys on the subject, so a token without one
    is unusable even if it verified."""
    import pytest

    from aisc_identity import IdentityMissing

    with pytest.raises(IdentityMissing):
        caller_from_claims({"email": "a@b.c"})


# One name per person (docs/specs/who-does-what.md, section 7): the display name the identity provider gives,
# else the user name, else the email, else the subject.

def test_the_display_name_is_read_from_the_claims():
    caller = caller_from_claims({"sub": "abc", "preferred_username": "anna", "name": "Anna Rossi"})
    assert caller.name == "Anna Rossi"


def test_a_person_is_named_by_their_display_name_first():
    from aisc_identity import display_name

    assert display_name(caller_from_claims(
        {"sub": "s", "email": "anna@aisc.local", "preferred_username": "anna", "name": "Anna Rossi"})) == "Anna Rossi"


def test_without_a_display_name_the_user_name_then_the_email_then_the_subject():
    from aisc_identity import display_name

    assert display_name(caller_from_claims({"sub": "s", "email": "anna@aisc.local", "preferred_username": "anna",
                                            "name": "  "})) == "anna"
    assert display_name(caller_from_claims({"sub": "s", "email": "anna@aisc.local"})) == "anna@aisc.local"
    assert display_name(caller_from_claims({"sub": "s"})) == "s"


def test_a_caller_shaped_object_without_the_newer_fields_is_named_too():
    from types import SimpleNamespace

    from aisc_identity import display_name

    assert display_name(SimpleNamespace(username="ada", subject="sub-ada")) == "ada"
