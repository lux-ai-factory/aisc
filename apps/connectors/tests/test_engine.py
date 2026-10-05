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


@respx.mock
def test_delete_secret_deletes_the_config(engine):
    project, cfg = uuid.uuid4(), uuid.uuid4()
    route = respx.delete(f"{BASE}/project/settings/{project}/{cfg}").mock(return_value=httpx.Response(204))
    engine.delete_secret(project, cfg)
    assert route.calls[0].request.method == "DELETE"


@respx.mock
def test_create_secret_redacts_the_value_from_engine_errors(engine):
    from aisc_connectors.engine import EngineError

    project = uuid.uuid4()
    respx.post(f"{BASE}/project/settings/{project}").mock(
        return_value=httpx.Response(422, json={"detail": [{"input": {"value": "sk-SECRET"}}]})
    )
    with pytest.raises(EngineError) as info:
        engine.create_secret(project, "K", "n", "sk-SECRET")
    assert "sk-SECRET" not in str(info.value)
    assert "sk-SECRET" not in info.value.detail


@respx.mock
def test_connect_timeout_is_a_504_and_names_no_secret(engine):
    from aisc_connectors.engine import EngineError

    project = uuid.uuid4()
    respx.get(f"{BASE}/projects/{project}/aisystem").mock(side_effect=httpx.ConnectTimeout("timed out"))
    with pytest.raises(EngineError) as info:
        engine.aisystem(project)
    assert info.value.status == 504
    assert "tok" not in str(info.value)


@respx.mock
def test_connect_error_is_a_502_and_names_no_secret(engine):
    from aisc_connectors.engine import EngineError

    project = uuid.uuid4()
    respx.get(f"{BASE}/projects/{project}/aisystem").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(EngineError) as info:
        engine.aisystem(project)
    assert info.value.status == 502
    assert "tok" not in str(info.value)


@respx.mock
def test_a_non_object_json_error_body_does_not_crash(engine):
    from aisc_connectors.engine import EngineError

    project = uuid.uuid4()
    respx.get(f"{BASE}/projects/{project}/aisystem").mock(return_value=httpx.Response(500, json=["bad", "stuff"]))
    with pytest.raises(EngineError) as info:
        engine.aisystem(project)
    assert info.value.status == 500
    assert "bad" in info.value.detail


def test_the_client_closes_as_a_context_manager():
    from aisc_connectors.engine import EngineClient

    with EngineClient("tok", base=BASE) as client:
        assert not client._http.is_closed
    assert client._http.is_closed
