from fastapi.testclient import TestClient


def test_health_answers_without_a_token():
    from aisc_connectors.app import app

    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_have_safe_defaults(monkeypatch):
    for name in ("CONNECTORS_DATABASE_URL", "CONNECTOR_SECRETS_KEY", "ENGINE_API_URL", "GATEWAY_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    from aisc_connectors.settings import settings

    s = settings()
    assert s.engine_api_url == "http://aisc-backend:8000/api/v1"
    assert s.gateway_base_url == "http://connectors:8097"
    assert s.secrets_key == ""
    assert s.max_response_bytes == 20 * 1024 * 1024
