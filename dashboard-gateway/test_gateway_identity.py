"""Superset takes who is using it from the gateway, like every other module.

Run with: python -m unittest test_gateway_identity (needs PyJWT and cryptography,
which the dashboard image has).
"""
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway_identity import CLAIMS_KEY, GatewayIdentity, what_to_do

ISSUER = "http://localhost:8081/realms/aisc"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key=KEY, issuer=ISSUER, **claims):
    body = {"iss": issuer, "sub": "sub-1", "preferred_username": "alice",
            "exp": int(time.time()) + 300, **claims}
    return jwt.encode(body, key, algorithm="RS256")


def run(environ):
    seen = {}

    def app(env, start_response):
        seen.update(env)
        return [b""]

    GatewayIdentity(app, issuer=ISSUER, key_for=lambda _t: KEY.public_key())(environ, lambda *a: None)
    return seen


class WhoTheGatewaySays(unittest.TestCase):
    def test_a_verified_token_names_the_user(self):
        env = run({"HTTP_X_AUTH_REQUEST_ACCESS_TOKEN": token()})
        self.assertEqual(env["REMOTE_USER"], "alice")
        self.assertEqual(env[CLAIMS_KEY]["sub"], "sub-1")

    def test_no_token_is_nobody(self):
        self.assertNotIn("REMOTE_USER", run({}))

    def test_a_token_signed_by_someone_else_is_nobody(self):
        self.assertNotIn("REMOTE_USER", run({"HTTP_X_AUTH_REQUEST_ACCESS_TOKEN": token(key=OTHER_KEY)}))

    def test_a_token_from_another_issuer_is_nobody(self):
        env = run({"HTTP_X_AUTH_REQUEST_ACCESS_TOKEN": token(issuer="http://evil/realms/aisc")})
        self.assertNotIn("REMOTE_USER", env)

    def test_an_expired_token_is_nobody(self):
        env = run({"HTTP_X_AUTH_REQUEST_ACCESS_TOKEN": token(exp=int(time.time()) - 10)})
        self.assertNotIn("REMOTE_USER", env)

    def test_a_remote_user_sent_by_the_client_is_ignored(self):
        self.assertNotIn("REMOTE_USER", run({"REMOTE_USER": "admin"}))


class FollowTheGateway(unittest.TestCase):
    def test_the_same_person_keeps_their_session(self):
        self.assertEqual(what_to_do("alice", "alice"), "keep")

    def test_someone_new_is_signed_in(self):
        self.assertEqual(what_to_do(None, "alice"), "login")

    def test_a_different_person_replaces_the_old_session(self):
        self.assertEqual(what_to_do("bob", "alice"), "switch")

    def test_no_one_at_the_gateway_ends_the_session(self):
        self.assertEqual(what_to_do("bob", None), "logout")

    def test_no_one_anywhere_is_left_alone(self):
        self.assertEqual(what_to_do(None, None), "keep")


if __name__ == "__main__":
    unittest.main()
