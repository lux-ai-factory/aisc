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


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/v1/connectors?project_pid={project}", None),
    ("POST", "/api/v1/connectors", {}),
    ("GET", "/api/v1/connectors/{connector}", None),
    ("PATCH", "/api/v1/connectors/{connector}", {}),
    ("DELETE", "/api/v1/connectors/{connector}", None),
    ("POST", "/api/v1/connectors/{connector}/target-access", None),
    ("PUT", "/api/v1/connectors/{connector}/auth", {}),
    ("PUT", "/api/v1/connectors/{connector}/secrets/api_key", {"value": "x"}),
    ("DELETE", "/api/v1/connectors/{connector}/secrets/api_key", None),
    ("GET", "/api/v1/connectors/projects/{project}/readiness", None),
])
def test_non_admins_are_refused_everywhere(api, as_user, engine, method, path, body):
    user = as_user("bob", ("primary-user",))
    url = path.format(project=engine.project, connector=uuid.uuid4())
    response = api.request(method, url, headers=user, json=body)
    assert response.status_code == 403


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


def test_duplicate_name_in_the_same_project_is_refused(api, as_user, engine):
    create(api, as_user, engine, name="MCAS")
    dup = create(api, as_user, engine, name="MCAS")
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"]


def test_duplicate_name_on_rename_is_refused(api, as_user, engine):
    first = create(api, as_user, engine, name="MCAS").json()
    create(api, as_user, engine, name="Other")
    response = api.patch(f"/api/v1/connectors/{first['pid']}", headers=as_user(), json={"name": "Other"})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_settings_reject_bool_for_integer_fields(api, as_user, engine):
    first = create(api, as_user, engine).json()
    response = api.patch(f"/api/v1/connectors/{first['pid']}", headers=as_user(),
                         json={"settings": {"timeout_s": True}})
    assert response.status_code == 422


def test_auth_scope_is_dropped_outside_oauth2(api, as_user, engine):
    first = create(api, as_user, engine).json()
    response = api.put(f"/api/v1/connectors/{first['pid']}/auth", headers=as_user(),
                       json={"scheme": "api_key", "in": "header", "name": "X-API-Key", "scope": "read"})
    assert response.status_code == 200
    assert "scope" not in response.json()["auth"]


def test_auth_scope_is_kept_for_oauth2(api, as_user, engine):
    first = create(api, as_user, engine).json()
    response = api.put(f"/api/v1/connectors/{first['pid']}/auth", headers=as_user(),
                       json={"scheme": "oauth2_client_credentials", "token_url": "https://t", "client_id": "c",
                             "scope": "read"})
    assert response.status_code == 200
    assert response.json()["auth"]["scope"] == "read"
