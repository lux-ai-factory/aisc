"""Verifying a token: the signature, the issuer and the clock all have to agree."""
import pytest

from aisc_identity.tokens import TokenRejected, verify_token

from conftest import ISSUER


def test_a_good_token_yields_its_claims(token, key_for):
    claims = verify_token(token(), issuer=ISSUER, key_for=key_for)
    assert claims["preferred_username"] == "user"


def test_an_expired_token_is_rejected(token, key_for):
    with pytest.raises(TokenRejected):
        verify_token(token(expires_in=-10), issuer=ISSUER, key_for=key_for)


def test_a_token_from_another_realm_is_rejected(token, key_for):
    with pytest.raises(TokenRejected):
        verify_token(token(issuer="http://evil/realms/other"), issuer=ISSUER, key_for=key_for)


def test_a_tampered_token_is_rejected(token, key_for):
    good = token()
    head, payload, sig = good.split(".")
    with pytest.raises(TokenRejected):
        verify_token(f"{head}.{payload}.{sig[:-4]}AAAA", issuer=ISSUER, key_for=key_for)


def test_an_unsigned_token_is_rejected(token, key_for):
    """A token with alg=none must not be accepted."""
    import jwt

    none_token = jwt.encode({"sub": "x", "iss": ISSUER}, key=None, algorithm="none")
    with pytest.raises(TokenRejected):
        verify_token(none_token, issuer=ISSUER, key_for=key_for)


def test_nonsense_is_rejected_rather_than_raising_something_else(key_for):
    with pytest.raises(TokenRejected):
        verify_token("not-a-token", issuer=ISSUER, key_for=key_for)
