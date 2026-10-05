def doc():
    return {
        "openapi": "3.1.0", "servers": [{"url": "http://t.example"}],
        "paths": {
            "/users/{id}": {"get": {"operationId": "getUser",
                                    "x-aisc-binding": {"protocol": "http", "method": "get", "path": "/users/{id}"}}},
            "/users": {"post": {"operationId": "createUser", "summary": "Create",
                                "x-aisc-binding": {"protocol": "http", "method": "post", "path": "/users"}}},
        },
    }


def test_operations_list_every_method_with_its_side_effect_flag():
    from aisc_connectors.model import operations

    ops = {o.operation_id: o for o in operations(doc())}
    assert ops["getUser"].changes_data is False
    assert ops["createUser"].changes_data is True
    assert ops["createUser"].summary == "Create"


def test_strip_aisc_removes_extensions_everywhere():
    from aisc_connectors.model import strip_aisc

    stripped = strip_aisc({**doc(), "x-aisc-auth": {"scheme": "bearer"}})
    assert "x-aisc-auth" not in stripped
    assert "x-aisc-binding" not in stripped["paths"]["/users"]["post"]


def test_server_url():
    from aisc_connectors.model import server_url

    assert server_url(doc()) == "http://t.example"
