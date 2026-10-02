"""The one rule for who a gateway request is (ledger spec 3.3, review R1.4).

The gateway token (X-Auth-Request-Access-Token, set by oauth2-proxy and copied in by Caddy) is
authoritative and must have been issued to the gateway's client (azp). A Bearer token on the same
request must verify too and name the same subject, or the request is refused: an app that prefers the
Bearer would otherwise act as another person than the one the gateway signed in. A leeway covers a
token that expires while the request crosses the gateway.
"""
import time

import pytest

from aisc_identity.gateway import GatewayRefused, gateway_identity
from conftest import ISSUER

GATEWAY = "aisc-gateway"


def ask(headers, key_for, leeway=30):
    return gateway_identity(headers, issuer=ISSUER, key_for=key_for, gateway_client=GATEWAY, leeway=leeway)


def test_the_gateway_token_names_the_person(token, key_for):
    who = ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY, jti="token-1")}, key_for)
    assert who.token_id == "token-1"
    assert (who.subject, who.username) == ("00000000-0000-0000-0000-000000000001", "user")
    assert who.expires_at > time.time()


def test_no_gateway_token_is_refused_even_with_a_bearer(token, key_for):
    with pytest.raises(GatewayRefused, match="missing"):
        ask({"Authorization": f"Bearer {token(azp=GATEWAY)}"}, key_for)


@pytest.mark.parametrize("claims, reason", [({"azp": "webapp"}, "other_client"), ({}, "other_client"),
                                            ({"azp": GATEWAY, "iss": "http://evil/realms/aisc"}, "invalid")])
def test_a_gateway_token_from_elsewhere_is_refused(token, key_for, claims, reason):
    with pytest.raises(GatewayRefused, match=reason):
        ask({"X-Auth-Request-Access-Token": token(**claims)}, key_for)


def test_a_bearer_for_the_same_person_from_another_client_is_fine(token, key_for):
    """The engine's web app sends its own keycloak-js token (another azp) next to the gateway's."""
    who = ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY),
               "Authorization": f"Bearer {token(azp='webapp')}"}, key_for)
    assert who.subject.endswith("01")


def test_a_bearer_for_someone_else_is_refused(token, key_for):
    with pytest.raises(GatewayRefused, match="token_mismatch"):
        ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY),
             "Authorization": f"Bearer {token(sub='00000000-0000-0000-0000-000000000002')}"}, key_for)


def test_a_bearer_that_does_not_verify_is_refused(token, key_for):
    with pytest.raises(GatewayRefused, match="invalid"):
        ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY), "Authorization": "Bearer not-a-token"}, key_for)


def test_the_leeway_covers_a_token_just_past_expiry_and_no_more(token, key_for):
    ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY, expires_in=-10)}, key_for, leeway=30)
    with pytest.raises(GatewayRefused, match="invalid"):
        ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY, expires_in=-60)}, key_for, leeway=30)


def test_a_token_not_yet_valid_is_refused(token, key_for):
    with pytest.raises(GatewayRefused, match="invalid"):
        ask({"X-Auth-Request-Access-Token": token(azp=GATEWAY, nbf=int(time.time()) + 120)}, key_for)


def test_header_names_are_case_insensitive(token, key_for):
    assert ask({"x-auth-request-access-token": token(azp=GATEWAY)}, key_for).subject
