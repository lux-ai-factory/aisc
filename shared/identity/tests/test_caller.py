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
