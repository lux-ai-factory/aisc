"""Where the token arrives: an Authorization header, or the gateway's copy of it."""
from aisc_identity.headers import GATEWAY_TOKEN_HEADER, token_from_headers


def test_an_authorization_bearer_header():
    assert token_from_headers({"Authorization": "Bearer abc"}) == "abc"


def test_header_names_are_case_insensitive():
    assert token_from_headers({"authorization": "bearer abc"}) == "abc"


def test_the_gateway_header_when_there_is_no_authorization():
    """A page behind oauth2-proxy holds no session of its own; the gateway
    passes the token it holds under its own name."""
    assert token_from_headers({GATEWAY_TOKEN_HEADER: "abc"}) == "abc"


def test_authorization_wins_when_both_are_present():
    headers = {"Authorization": "Bearer mine", GATEWAY_TOKEN_HEADER: "theirs"}
    assert token_from_headers(headers) == "mine"


def test_no_token_at_all():
    assert token_from_headers({}) is None
    assert token_from_headers({"Authorization": "Basic abc"}) is None
    assert token_from_headers({"Authorization": "Bearer "}) is None
