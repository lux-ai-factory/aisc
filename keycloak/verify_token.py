#!/usr/bin/env python3
"""
Keycloak token verification — proof that the `aisc` realm issues valid, role-bearing tokens
and that they can be cryptographically verified against Keycloak's public keys (JWKS).

This is the standalone proof of the auth mechanism the backend will use in code:
  1. obtain a token from Keycloak (Direct Access Grant: username + password)
  2. fetch Keycloak's public keys (JWKS) and verify the token's RS256 signature + issuer + expiry
  3. read the user's roles from `realm_access.roles`
  4. confirm a tampered token is rejected

Requires: pip install "pyjwt[crypto]"

Reach Keycloak via the KC_REALM env var:
  - from the host (laptop):           KC_REALM=http://localhost:8081/realms/aisc
  - from inside the backend container: KC_REALM=http://keycloak:8080/realms/aisc   (docker service name)

Usage:
  KC_REALM=http://localhost:8081/realms/aisc python keycloak/verify_token.py
  KC_REALM=... KC_USERNAME=user KC_PASSWORD=user python keycloak/verify_token.py

Note: the credential env vars are KC_-prefixed on purpose — a plain USERNAME would collide
with the shell's own USERNAME variable and log in as the wrong user.
"""
import os
import sys
import json
import urllib.request
import urllib.parse

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:
    sys.exit('Missing dependency. Run: pip install "pyjwt[crypto]"')

KC_REALM = os.environ.get("KC_REALM", "http://localhost:8081/realms/aisc")
CLIENT_ID = os.environ.get("KC_CLIENT_ID", "aisc-webapp")
USERNAME = os.environ.get("KC_USERNAME", "admin")
PASSWORD = os.environ.get("KC_PASSWORD", "admin")

TOKEN_URL = f"{KC_REALM}/protocol/openid-connect/token"
JWKS_URL = f"{KC_REALM}/protocol/openid-connect/certs"


def get_token() -> str:
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as r:
        return json.load(r)["access_token"]


def verify(token: str) -> dict:
    """Verify signature (against JWKS) + issuer + expiry, and return the claims."""
    signing_key = PyJWKClient(JWKS_URL).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=KC_REALM,
        options={"verify_aud": False},  # audience check intentionally skipped here
    )


def main() -> int:
    print(f"Realm:    {KC_REALM}")
    print(f"User:     {USERNAME}\n")

    token = get_token()
    print("1) Obtained a token.")

    claims = verify(token)
    print("2) SIGNATURE VALID")
    print(f"   user : {claims.get('preferred_username')}")
    print(f"   roles: {claims.get('realm_access', {}).get('roles')}")
    print(f"   iss  : {claims.get('iss')}")

    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    try:
        verify(tampered)
        print("3) TAMPERED token ACCEPTED  <-- FAIL: validation is broken")
        return 1
    except Exception as e:
        print(f"3) TAMPERED token REJECTED ({type(e).__name__})  <-- OK")

    print("\nPASS: Keycloak issues verifiable, role-bearing tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
