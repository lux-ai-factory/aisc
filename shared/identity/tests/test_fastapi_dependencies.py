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
    assert r.status_code >= 400
