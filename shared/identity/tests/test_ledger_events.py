"""aisc_identity.ledger_events: the event an app writes, and whose X-AISC-Request-Id it cites.

Caddy strips the header a client sends and puts back the one the platform's witness gave it, with
the gateway token (X-Auth-Request-Access-Token) oauth2-proxy holds for the person. A caller that
reaches the service directly on the backend network, with a token of its own, does not go through
that, so the id it presents is not cited: only a request that carries a verified gateway token
(aisc_identity.gateway, the witness's own rule) has its request id kept. With AUTH_ENABLED off
(local work) nothing is verified at all, and the id is kept as presented.
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from aisc_identity import ledger_events as ledger

ISSUER = "http://keycloak:8080/realms/aisc"
REQUEST = "a6a6a6a6-0000-4000-8000-000000000002"


@pytest.fixture()
def sign(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.delenv("AISC_GATEWAY_CLIENT_ID", raising=False)
    monkeypatch.setattr("aisc_identity.service.key_for_jwks", lambda url: (lambda _t: key.public_key()))

    def token(subject="alice", azp="aisc-gateway"):
        return jwt.encode({"sub": subject, "preferred_username": subject, "iss": ISSUER, "azp": azp,
                           "exp": int(time.time()) + 300}, key, algorithm="RS256")

    return token


def cited(headers: dict[str, str]) -> str | None:
    """The request id an app behind RequestId sees for a request with these headers."""
    import asyncio

    seen = []

    async def app(scope, receive, send):
        seen.append(ledger.current_request.get())

    scope = {"type": "http", "headers": [(k.lower().encode("latin-1"), v.encode("latin-1"))
                                         for k, v in headers.items()]}
    asyncio.run(ledger.RequestId(app)(scope, None, None))
    return seen[0]


def test_a_request_through_the_gateway_cites_its_request(sign):
    assert cited({"X-AISC-Request-Id": REQUEST, "X-Auth-Request-Access-Token": sign()}) == REQUEST


def test_a_direct_caller_with_its_own_token_cites_nothing(sign):
    # a service or API client on the backend network: a valid token, but not the gateway's
    assert cited({"X-AISC-Request-Id": REQUEST, "Authorization": f"Bearer {sign(azp='some-service')}"}) is None


def test_a_direct_caller_with_no_token_cites_nothing(sign):
    assert cited({"X-AISC-Request-Id": REQUEST}) is None


def test_a_token_from_another_client_in_the_gateway_header_cites_nothing(sign):
    assert cited({"X-AISC-Request-Id": REQUEST, "X-Auth-Request-Access-Token": sign(azp="other")}) is None


def test_a_bearer_naming_another_person_than_the_gateway_token_cites_nothing(sign):
    assert cited({"X-AISC-Request-Id": REQUEST, "X-Auth-Request-Access-Token": sign("alice"),
                  "Authorization": f"Bearer {sign('mallory', azp='other')}"}) is None


def test_a_forged_gateway_token_cites_nothing(sign):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "alice", "iss": ISSUER, "azp": "aisc-gateway", "exp": int(time.time()) + 300},
                        other, algorithm="RS256")
    assert cited({"X-AISC-Request-Id": REQUEST, "X-Auth-Request-Access-Token": forged}) is None


def test_with_auth_off_the_presented_id_is_kept(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert cited({"X-AISC-Request-Id": REQUEST}) == REQUEST


def test_with_auth_on_but_nothing_to_verify_with_nothing_is_cited(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("KEYCLOAK_ISSUER", raising=False)
    monkeypatch.delenv("KEYCLOAK_JWKS_URL", raising=False)
    assert cited({"X-AISC-Request-Id": REQUEST, "X-Auth-Request-Access-Token": "x"}) is None


def test_an_event_carries_the_cited_request_and_only_the_fields_given():
    token = ledger.current_request.set(REQUEST)
    try:
        event = ledger.event("risk.rated", item_type="risk_rating", item_id="a/risks/r1", details={"rating": 6},
                             before={"impact": 2}, run_id=None)
    finally:
        ledger.current_request.reset(token)
    assert set(event) == {"event_id", "request_id", "action", "item_type", "item_id", "details", "before"}
    assert (event["request_id"], event["action"], event["details"]) == (REQUEST, "risk.rated", {"rating": 6})


def test_an_event_without_details_has_an_empty_object():
    assert ledger.event("x.y", item_type="t", item_id="i")["details"] == {}


@pytest.mark.parametrize("value", [2 ** 53 + 1, -(2 ** 53) - 1, float("nan"), float("inf"), 2.0 ** 60,
                                   "\ud800", {1, 2}, b"bytes"])
def test_what_the_ledger_cannot_keep_is_refused_before_it_is_written(value):
    with pytest.raises(ledger.NotLedgerSafe):
        ledger.event("x.y", item_type="t", item_id="i", content={"v": [value]})


def test_what_the_ledger_keeps_is_accepted():
    ledger.event("x.y", item_type="t", item_id="i", content={"n": 2 ** 53, "f": 1.5, "s": "é", "l": [None, True]})


@pytest.mark.parametrize("mode,on", [("record", True), ("enforce", True), (" Record ", True), ("off", False),
                                     ("", False), (None, False)])
def test_the_ledger_is_on_only_in_record_or_enforce(monkeypatch, mode, on):
    if mode is None:
        monkeypatch.delenv("LEDGER_MODE", raising=False)
    else:
        monkeypatch.setenv("LEDGER_MODE", mode)
    assert ledger.on() is on
