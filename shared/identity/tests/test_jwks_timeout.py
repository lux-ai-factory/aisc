"""A Keycloak that accepts the connection but never answers must not hold a request for long.

PyJWKClient waits 30 seconds by default; key_for_jwks gives up after JWKS_TIMEOUT_S, and the token
does not verify (401), as in shared/ledger-ts/jwksTimeout.test.ts.
"""
import socket
import time

import pytest

from aisc_identity import service
from aisc_identity.tokens import TokenRejected, verify_token
from conftest import ISSUER


@pytest.fixture
def silent_keycloak():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)  # the kernel accepts; nobody ever reads or answers
    yield f"http://127.0.0.1:{listener.getsockname()[1]}/certs"
    listener.close()


def test_the_jwks_read_gives_up_in_time(silent_keycloak, token, monkeypatch):
    monkeypatch.setattr(service, "JWKS_TIMEOUT_S", 0.3)
    started = time.monotonic()
    with pytest.raises(TokenRejected, match="no signing key"):
        verify_token(token(), issuer=ISSUER, key_for=service.key_for_jwks(silent_keycloak))
    assert time.monotonic() - started < 3


def test_the_default_wait_is_short():
    assert service.JWKS_TIMEOUT_S <= 3
