"""What a FastAPI service gets: a caller, or a refusal with the right status."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency, requires_role

from conftest import ISSUER


@pytest.fixture
def app():
    api = FastAPI()

    @api.get("/who")
    def who(caller: Caller = Depends(caller_dependency)) -> dict:
        return {"username": caller.username, "roles": list(caller.roles)}

    @api.get("/admin-only", dependencies=[Depends(requires_role("admin"))])
    def admin_only() -> dict:
        return {"ok": True}

    return api


@pytest.fixture
def client(app, monkeypatch, key_for):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/does-not-matter")
    monkeypatch.setattr("aisc_identity.service.key_for_jwks", lambda url: key_for)
    return TestClient(app)


def test_no_token_is_401(client):
    assert client.get("/who").status_code == 401


def test_a_bad_token_is_401(client):
    r = client.get("/who", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_a_good_token_names_the_caller(client, token):
    r = client.get("/who", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 200
    assert r.json() == {"username": "user", "roles": ["primary-user"]}


def test_the_wrong_role_is_403_not_401(client, token):
    """401 says "who are you", 403 says "not you". A signed-in account that may
    not do this has answered the first question already."""
    r = client.get("/admin-only", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 403


def test_the_right_role_is_let_through(client, token):
    r = client.get("/admin-only", headers={"Authorization": f"Bearer {token(roles=['admin'])}"})
    assert r.status_code == 200


def test_no_token_on_an_admin_route_is_401(client):
    assert client.get("/admin-only").status_code == 401


def test_the_gateway_header_works_the_same(client, token):
    from aisc_identity.headers import GATEWAY_TOKEN_HEADER

    r = client.get("/who", headers={GATEWAY_TOKEN_HEADER: token(roles=["admin"])})
    assert r.status_code == 200


def test_auth_off_gives_a_development_caller(app, monkeypatch):
    """Local work without Keycloak running still has to be possible, and the
    identity it gets is obviously fake rather than quietly privileged."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.delenv("AUTH_DEV_ROLES", raising=False)
    client = TestClient(app)
    r = client.get("/who")
    assert r.status_code == 200
    assert r.json()["username"] == "development"
    assert client.get("/admin-only").status_code == 403


def test_auth_off_can_be_told_which_roles_to_pretend(app, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_DEV_ROLES", "admin,primary-user")
    client = TestClient(app)
    assert client.get("/admin-only").status_code == 200


def test_auth_on_without_a_jwks_url_refuses_rather_than_letting_through(app, monkeypatch, token):
    """A misconfigured service must fail closed. Letting requests through
    because the verifier was not configured is the failure mode that matters."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("KEYCLOAK_JWKS_URL", raising=False)
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/who", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 500          # not 401: no credentials the caller sends can fix it


def test_auth_on_without_an_issuer_refuses_with_500(app, monkeypatch, token):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/does-not-matter")
    monkeypatch.delenv("KEYCLOAK_ISSUER", raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/who", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 500


OTHER = "00000000-0000-0000-0000-000000000002"


def test_a_bearer_for_the_same_person_as_the_gateway_token_is_let_through(client, token):
    """The engine's web app sends its own keycloak-js token next to the gateway's."""
    from aisc_identity.headers import GATEWAY_TOKEN_HEADER

    r = client.get("/who", headers={GATEWAY_TOKEN_HEADER: token(azp="aisc-gateway"),
                                    "Authorization": f"Bearer {token(azp='webapp', roles=['admin'])}"})
    assert r.status_code == 200
    assert r.json()["roles"] == ["primary-user"]  # the gateway's person, as the gateway signed them in


def test_a_bearer_for_someone_else_than_the_gateway_token_is_401(client, token):
    """Access would otherwise be decided for the Bearer's person while the gateway signed in another."""
    from aisc_identity.headers import GATEWAY_TOKEN_HEADER

    r = client.get("/who", headers={GATEWAY_TOKEN_HEADER: token(azp="aisc-gateway"),
                                    "Authorization": f"Bearer {token(sub=OTHER, roles=['admin'])}"})
    assert r.status_code == 401


def test_a_gateway_token_that_does_not_verify_is_401_even_with_a_good_bearer(client, token):
    from aisc_identity.headers import GATEWAY_TOKEN_HEADER

    r = client.get("/who", headers={GATEWAY_TOKEN_HEADER: "nonsense", "Authorization": f"Bearer {token()}"})
    assert r.status_code == 401


def test_one_token_sent_under_both_headers_is_that_token(client, token):
    """A service calling as the person (the platform to the report composer) sends the token it was given
    both ways, whichever client it was issued to."""
    from aisc_identity.headers import GATEWAY_TOKEN_HEADER

    same = token(azp="webapp")
    r = client.get("/who", headers={GATEWAY_TOKEN_HEADER: same, "Authorization": f"Bearer {same}"})
    assert r.status_code == 200


@pytest.mark.parametrize("where", ["bearer", "gateway"])
def test_a_token_that_names_nobody_is_401_not_500(client, token, where):
    from aisc_identity.headers import GATEWAY_TOKEN_HEADER

    nobody = token(sub="")
    headers = {"Authorization": f"Bearer {nobody}"} if where == "bearer" else {GATEWAY_TOKEN_HEADER: nobody}
    r = TestClient(client.app, raise_server_exceptions=False).get("/who", headers=headers)
    assert r.status_code == 401
