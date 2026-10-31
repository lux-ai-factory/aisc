"""Superset's session follows the gateway's: superset_gateway_config.py in a small Flask app.

Superset and the dashboard's own package are not imported: Flask-AppBuilder's two names and aisc_ext's
security manager are stand-ins that record what the config asks of them, so this runs with Flask and
Flask-Login alone, at the versions the dashboard image has (scripts/verify.sh pins them).

Run with: python -m unittest test_superset_gateway_config
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from flask import Flask
from flask_login import LoginManager, UserMixin, current_user
from gateway_identity import CLAIMS_KEY

HERE = Path(__file__).resolve().parent


class User(UserMixin):
    def __init__(self, username):
        self.username = username
        self.email = self.first_name = self.last_name = None

    def get_id(self):
        return self.username


def _expose(f):
    f._urls = [("/" + f.__name__, ["POST"])]   # what Flask-AppBuilder's @expose leaves on a routed method
    return f


class SecurityApi:
    @_expose
    def login(self):
        return "token"

    @_expose
    def refresh(self):
        return "token"


class KeycloakSecurityManager:
    """The dashboard's security manager, as far as the gateway config uses it."""

    def __init__(self):
        self.users, self.asked_for = {}, []

    def auth_user_remote_user(self, username):
        self.asked_for.append(username)
        return self.users.setdefault(username, User(username))

    def _member_projects(self, sub):
        return [f"project of {sub}"]

    def _sync_dashboard_ownership(self, *args):
        pass


SIGN_INS = []


def apply_sign_in(sm, user, roles, projects, sync_ownership):
    SIGN_INS.append({"user": user.username, "roles": list(roles), "projects": projects,
                     "sync": sync_ownership == sm._sync_dashboard_ownership})


def _module(name, **names):
    module = types.ModuleType(name)
    module.__dict__.update(names)
    sys.modules[name] = module
    return module


def load_config():
    """The config as Superset loads it, with a stand-in for the dashboard's superset_config.py."""
    _module("flask_appbuilder")
    _module("flask_appbuilder.security")
    _module("flask_appbuilder.security.api", SecurityApi=SecurityApi)
    _module("flask_appbuilder.security.manager", AUTH_REMOTE_USER=3)
    _module("aisc_ext")
    _module("aisc_ext.security", VIEWER_ROLE="Gamma", apply_sign_in=apply_sign_in)
    _module("aisc_ext.sso", KeycloakSecurityManager=KeycloakSecurityManager)
    original = Path(tempfile.mkdtemp()) / "superset_config.py"
    original.write_text("ROW_LIMIT = 7\n\n"
                        "def FLASK_APP_MUTATOR(app):\n"
                        "    app.config['ORIGINAL_MUTATOR_RAN'] = True\n")
    os.environ.update(AISC_ORIGINAL_SUPERSET_CONFIG=str(original), GATEWAY_TOKEN_ISSUER="http://issuer",
                      AISC_GATEWAY_CLIENT_ID="aisc-gateway", GATEWAY_JWKS_URL="http://keys.invalid/certs")
    spec = importlib.util.spec_from_file_location("gateway_config_under_test", HERE / "superset_gateway_config.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


CONFIG = load_config()


def claims(sub="sub-alice", roles=("viewer",), **more):
    return {"sub": sub, "realm_access": {"roles": list(roles)}, **more}


class FollowTheGatewayInFlask(unittest.TestCase):
    def setUp(self):
        SIGN_INS.clear()
        app = Flask(__name__)
        app.secret_key = "test"
        logins = LoginManager(app)
        self.sm = CONFIG.GatewaySecurityManager()
        logins.user_loader(lambda username: self.sm.users.get(username))
        app.appbuilder = types.SimpleNamespace(sm=self.sm)
        CONFIG.FLASK_APP_MUTATOR(app)

        @app.route("/")
        def who():
            return current_user.username if current_user.is_authenticated else "-"

        self.app, self.client = app, app.test_client()

    def get(self, path="/", user=None, token_claims=None):
        environ = {}
        if user:
            environ["REMOTE_USER"] = user
        if token_claims is not None:
            environ[CLAIMS_KEY] = token_claims
        return self.client.get(path, environ_base=environ)

    def test_the_original_config_is_kept_and_its_mutator_runs(self):
        self.assertEqual(CONFIG.ROW_LIMIT, 7)
        self.assertTrue(self.app.config["ORIGINAL_MUTATOR_RAN"])

    def test_someone_the_gateway_names_is_signed_in(self):
        self.assertEqual(self.get(user="alice", token_claims=claims()).text, "alice")
        self.assertEqual(self.sm.asked_for, ["alice"])

    def test_the_same_person_keeps_their_session(self):
        self.get(user="alice", token_claims=claims())
        self.assertEqual(self.get(user="alice", token_claims=claims()).text, "alice")
        self.assertEqual(self.sm.asked_for, ["alice"])

    def test_a_different_person_replaces_the_old_session(self):
        self.get(user="alice", token_claims=claims())
        self.assertEqual(self.get(user="bob", token_claims=claims(sub="sub-bob")).text, "bob")
        self.assertEqual(self.sm.asked_for, ["alice", "bob"])

    def test_no_one_at_the_gateway_ends_the_session(self):
        self.get(user="alice", token_claims=claims())
        self.assertEqual(self.get().text, "-")

    def test_signing_out_ends_the_session_and_goes_to_the_gateway(self):
        self.get(user="alice", token_claims=claims())
        r = self.get("/logout", user="alice", token_claims=claims())
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/oauth2/sign_out?rd=%2F"))
        self.assertEqual(self.get().text, "-")

    def test_each_sign_in_syncs_roles_and_profile_from_the_token(self):
        self.get(user="alice", token_claims=claims(roles=["viewer"], email="alice@example.org",
                                                   given_name="Alice", family_name="Liddell"))
        self.get()
        self.get(user="alice", token_claims=claims(roles=["admin"]))
        self.assertEqual([s["roles"] for s in SIGN_INS], [["viewer"], ["admin"]])
        self.assertEqual(SIGN_INS[0]["projects"], ["project of sub-alice"])
        self.assertTrue(SIGN_INS[0]["sync"])
        alice = self.sm.users["alice"]
        self.assertEqual((alice.email, alice.first_name, alice.last_name),
                         ("alice@example.org", "Alice", "Liddell"))

    def test_without_verified_claims_nothing_is_synced(self):
        self.assertEqual(self.get(user="alice").text, "alice")
        self.assertEqual(SIGN_INS, [])


class NoPasswordLogin(unittest.TestCase):
    def test_the_security_api_hands_out_no_token_for_a_password(self):
        api = CONFIG.GatewaySecurityManager.security_api
        self.assertIs(api, CONFIG.NoPasswordLoginApi)
        for name in ("login", "refresh"):
            self.assertFalse(hasattr(getattr(api, name), "_urls"), name)
            with self.assertRaises(NotImplementedError):
                getattr(api(), name)()

    def test_people_are_taken_from_the_gateway(self):
        self.assertEqual((CONFIG.AUTH_TYPE, CONFIG.AUTH_USER_REGISTRATION_ROLE, CONFIG.OAUTH_PROVIDERS),
                         (3, "Gamma", []))


if __name__ == "__main__":
    unittest.main()
