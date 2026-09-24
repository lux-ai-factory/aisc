import uuid

import pytest
from fastapi.testclient import TestClient


class FakeEngine:
    """The engine as the service sees it: one project with an AI system and two components."""

    def __init__(self):
        self.project = uuid.uuid4()
        self.system = uuid.uuid4()
        self.components = [uuid.uuid4(), uuid.uuid4()]
        self.known = {self.project}

    def aisystem(self, project_pid):
        from aisc_connectors.engine import NotFound

        if uuid.UUID(str(project_pid)) not in self.known:
            raise NotFound(404, "not found")
        return {"pid": str(self.system), "name": "S",
                "components": [{"pid": str(c), "name": f"c{i}", "component_type": "model"}
                               for i, c in enumerate(self.components)]}


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def api(db, auth_on, engine):
    from aisc_connectors import routes_admin
    from aisc_connectors.app import app

    app.dependency_overrides[routes_admin.engine_for] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def create(api, as_user, engine, name="MCAS", environment="sandbox"):
    return api.post("/api/v1/connectors", headers=as_user(),
                    json={"project_pid": str(engine.project), "name": name, "environment": environment})


def test_non_admins_are_refused_everywhere(api, as_user, engine):
    user = as_user("bob", ("primary-user",))
    assert api.get(f"/api/v1/connectors?project_pid={engine.project}", headers=user).status_code == 403
    assert api.post("/api/v1/connectors", headers=user, json={}).status_code == 403


def test_the_first_connector_becomes_target_access(api, as_user, engine):
    first = create(api, as_user, engine).json()
    second = create(api, as_user, engine, name="Other").json()
    assert first["is_target_access"] is True
    assert second["is_target_access"] is False
    assert first["ai_system_pid"] == str(engine.system)


def test_an_unknown_project_is_refused(api, as_user, engine):
    response = api.post("/api/v1/connectors", headers=as_user(),
                        json={"project_pid": str(uuid.uuid4()), "name": "X", "environment": "sandbox"})
    assert response.status_code == 404


def test_the_last_target_access_connector_cannot_be_deleted(api, as_user, engine):
    first = create(api, as_user, engine).json()
    response = api.delete(f"/api/v1/connectors/{first['pid']}", headers=as_user())
    assert response.status_code == 409
    second = create(api, as_user, engine, name="Other").json()
    assert api.post(f"/api/v1/connectors/{second['pid']}/target-access", headers=as_user()).status_code == 200
    assert api.delete(f"/api/v1/connectors/{first['pid']}", headers=as_user()).status_code == 204


def test_an_orphaned_connector_can_be_deleted(api, as_user, engine):
    first = create(api, as_user, engine).json()
    engine.known.clear()
    listed = api.get(f"/api/v1/connectors/{first['pid']}", headers=as_user()).json()
    assert listed["orphaned"] is True
    assert api.delete(f"/api/v1/connectors/{first['pid']}", headers=as_user()).status_code == 204


def test_readiness_says_whether_a_target_access_connector_exists(api, as_user, engine):
    url = f"/api/v1/connectors/projects/{engine.project}/readiness"
    assert api.get(url, headers=as_user()).json() == {"has_target_access": False}
    create(api, as_user, engine)
    assert api.get(url, headers=as_user()).json() == {"has_target_access": True}


def test_secrets_are_write_only(api, as_user, engine):
    first = create(api, as_user, engine).json()
    put = api.put(f"/api/v1/connectors/{first['pid']}/secrets/api_key", headers=as_user(),
                  json={"value": "sk-abcdefghijk"})
    assert put.status_code == 200
    shown = api.get(f"/api/v1/connectors/{first['pid']}", headers=as_user()).text
    assert "sk-abcdefghijk" not in shown
    assert "sk****jk" in shown


def test_auth_scheme_fields_are_checked(api, as_user, engine):
    first = create(api, as_user, engine).json()
    bad = api.put(f"/api/v1/connectors/{first['pid']}/auth", headers=as_user(),
                  json={"scheme": "api_key", "in": "cookie", "name": "X"})
    assert bad.status_code == 422
    good = api.put(f"/api/v1/connectors/{first['pid']}/auth", headers=as_user(),
                   json={"scheme": "api_key", "in": "header", "name": "X-API-Key"})
    assert good.status_code == 200
    assert good.json()["auth"] == {"scheme": "api_key", "in": "header", "name": "X-API-Key"}


def test_settings_are_bounded(api, as_user, engine):
    first = create(api, as_user, engine).json()
    assert api.patch(f"/api/v1/connectors/{first['pid']}", headers=as_user(),
                     json={"settings": {"timeout_s": 0}}).status_code == 422
    ok = api.patch(f"/api/v1/connectors/{first['pid']}", headers=as_user(),
                   json={"settings": {"timeout_s": 10, "ollama_facade": True}})
    assert ok.json()["settings"]["timeout_s"] == 10


def test_engine_refusal_on_create_becomes_a_502(api, as_user, engine):
    from aisc_connectors.engine import EngineError

    def boom(project_pid):
        raise EngineError(503, "down")

    engine.aisystem = boom
    response = api.post("/api/v1/connectors", headers=as_user(),
                        json={"project_pid": str(engine.project), "name": "X", "environment": "sandbox"})
    assert response.status_code == 502
    assert "down" in response.json()["detail"]
