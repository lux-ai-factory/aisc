"""Superset behind the gateway: the dashboard's own configuration, plus this.

Loaded through SUPERSET_CONFIG_PATH. It runs apps/results-dashboard's
superset_config.py unchanged and then changes one thing: who is signed in.
Instead of Superset logging people in itself (its own Keycloak client, and a
local admin account with a password), it takes who they are from the gateway,
like every other module: gateway_identity.py verifies the token Caddy passes and
sets REMOTE_USER, Flask-AppBuilder's AUTH_REMOTE_USER reads it, and the role
sync is the dashboard's own (KeycloakSecurityManager._member_projects and
aisc_ext.security.roles_for_login), called as it is.

Superset loads this file under the name superset_config, so the original is
loaded by its path rather than imported by name, which would find this file.
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ORIGINAL = os.environ.get("AISC_ORIGINAL_SUPERSET_CONFIG", "/app/pythonpath/superset_config.py")
_spec = importlib.util.spec_from_file_location("aisc_original_superset_config", _ORIGINAL)
_original = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_original)
for _name in dir(_original):
    if _name.isupper():
        globals()[_name] = getattr(_original, _name)

from flask_appbuilder.security.api import SecurityApi  # noqa: E402
from flask_appbuilder.security.manager import AUTH_REMOTE_USER  # noqa: E402

from aisc_ext.security import VIEWER_ROLE, roles_for_login  # noqa: E402
from aisc_ext.sso import KeycloakSecurityManager  # noqa: E402
from gateway_identity import CLAIMS_KEY, GatewayIdentity, what_to_do  # noqa: E402

AUTH_TYPE = AUTH_REMOTE_USER
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = VIEWER_ROLE
OAUTH_PROVIDERS = []

ADDITIONAL_MIDDLEWARE = [
    *getattr(_original, "ADDITIONAL_MIDDLEWARE", []),
    lambda app: GatewayIdentity(
        app,
        issuer=os.environ["GATEWAY_TOKEN_ISSUER"],
        jwks_url=os.environ["GATEWAY_JWKS_URL"],
    ),
]


class NoPasswordLoginApi(SecurityApi):
    """FAB's security API without /login and /refresh: those hand out a token
    for a username and password, whatever AUTH_TYPE says. Redefining them
    without @expose leaves them unrouted."""

    def login(self):  # noqa: D102
        raise NotImplementedError

    def refresh(self):  # noqa: D102
        raise NotImplementedError


class GatewaySecurityManager(KeycloakSecurityManager):
    security_api = NoPasswordLoginApi

    def auth_user_remote_user(self, username):
        user = super().auth_user_remote_user(username)
        from flask import request

        claims = request.environ.get(CLAIMS_KEY) or {}
        if user is None or not claims:
            return user
        desired = roles_for_login(
            (claims.get("realm_access") or {}).get("roles", []),
            self._member_projects(claims.get("sub")),
        )
        user.roles = [self.find_role(r) for r in desired if self.find_role(r)]
        user.email = claims.get("email") or user.email
        user.first_name = claims.get("given_name") or user.first_name
        user.last_name = claims.get("family_name") or user.last_name
        self.update_user(user)
        return user


CUSTOM_SECURITY_MANAGER = GatewaySecurityManager

_original_mutator = getattr(_original, "FLASK_APP_MUTATOR", None)


def FLASK_APP_MUTATOR(app):  # noqa: N802 (Superset hook name)
    if _original_mutator:
        _original_mutator(app)

    from flask import redirect, request
    from flask_login import current_user, login_user, logout_user

    @app.before_request
    def _follow_the_gateway():
        # Signing out is the gateway's: Superset's own logout alone would sign
        # the same person straight back in on the next request.
        if request.path.rstrip("/") == "/logout":
            logout_user()
            return redirect("/oauth2/sign_out?rd=%2F")
        signed_in_as = current_user.username if current_user.is_authenticated else None
        action = what_to_do(signed_in_as, request.environ.get("REMOTE_USER"))
        if action in ("logout", "switch"):
            logout_user()
        if action in ("login", "switch"):
            user = app.appbuilder.sm.auth_user_remote_user(request.environ["REMOTE_USER"])
            if user:
                login_user(user)
        return None
