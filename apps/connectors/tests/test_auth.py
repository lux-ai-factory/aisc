from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def _app():
    from aisc_connectors.auth import Admin, admin_call

    app = FastAPI()

    @app.get("/who")
    def who(admin: Admin = Depends(admin_call)):
        return {"subject": admin.caller.subject, "forwarded": admin.token is not None}

    return TestClient(app)


def test_no_token_is_401(auth_on):
    assert _app().get("/who").status_code == 401


def test_a_user_without_admin_is_403(auth_on, as_user):
    assert _app().get("/who", headers=as_user("bob", ("primary-user",))).status_code == 403


def test_an_admin_passes_and_its_token_is_kept_for_the_engine(auth_on, as_user):
    response = _app().get("/who", headers=as_user("alice", ("admin",)))
    assert response.status_code == 200
    assert response.json() == {"subject": "alice", "forwarded": True}
