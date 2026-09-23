"""A signing key and a token factory, so the tests exercise real signatures.

Verifying a token nobody signed proves nothing, so these tests mint real RS256
tokens with a throwaway key and hand the public half to the verifier the same
way Keycloak's JWKS endpoint would.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://keycloak:8080/realms/aisc"


@pytest.fixture(scope="session")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def key_for(key):
    """What verify_token calls to turn a token into the key that signed it."""
    public = key.public_key()
    return lambda token: public


@pytest.fixture
def token(key):
    def make(roles=("primary-user",), issuer=ISSUER, expires_in=300, **claims):
        payload = {
            "sub": "00000000-0000-0000-0000-000000000001",
            "email": "user@localhost",
            "preferred_username": "user",
            "iss": issuer,
            "exp": int(time.time()) + expires_in,
            "iat": int(time.time()),
            "realm_access": {"roles": list(roles)},
            **claims,
        }
        return jwt.encode(payload, key, algorithm="RS256")

    return make
