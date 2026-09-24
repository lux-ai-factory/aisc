import uuid

import httpx
import pytest
import respx

BASE = "http://engine.test/api/v1"


@pytest.fixture
def engine():
    from aisc_connectors.engine import EngineClient

    return EngineClient("tok", base=BASE)


@respx.mock
def test_aisystem_sends_the_admins_token(engine):
    project = uuid.uuid4()
    route = respx.get(f"{BASE}/projects/{project}/aisystem").mock(
        return_value=httpx.Response(200, json={"pid": str(uuid.uuid4()), "name": "S", "components": []})
    )
    assert engine.aisystem(project)["name"] == "S"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_unknown_project_is_not_found(engine):
    project = uuid.uuid4()
    respx.get(f"{BASE}/projects/{project}/aisystem").mock(return_value=httpx.Response(404))
    from aisc_connectors.engine import NotFound

    with pytest.raises(NotFound):
        engine.aisystem(project)


@respx.mock
def test_create_secret_posts_a_secrets_category(engine):
    project, pid = uuid.uuid4(), uuid.uuid4()
    route = respx.post(f"{BASE}/project/settings/{project}").mock(
        return_value=httpx.Response(200, json={"pid": str(pid), "key": "K", "name": "n",
                                                "masked_value": "****", "json_value": {}, "category": "secrets"})
    )
    assert engine.create_secret(project, "K", "n", "v") == str(pid)
    sent = route.calls[0].request.read()
    assert b'"category":"secrets"' in sent.replace(b" ", b"")


@respx.mock
def test_create_component_returns_its_pid(engine):
    project, pid = uuid.uuid4(), uuid.uuid4()
    respx.post(f"{BASE}/projects/{project}/components").mock(
        return_value=httpx.Response(200, json={"pid": str(pid), "name": "n", "component_type": "resource",
                                                "json_value": {"value": "u"}})
    )
    assert engine.create_component(project, "n", "resource", {"value": "u"}) == str(pid)


@respx.mock
def test_engine_errors_keep_status_and_detail(engine):
    from aisc_connectors.engine import EngineError

    respx.delete(url__regex=rf"{BASE}/components/.*").mock(
        return_value=httpx.Response(403, json={"detail": "no"})
    )
    with pytest.raises(EngineError) as info:
        engine.delete_component(uuid.uuid4())
    assert info.value.status == 403
