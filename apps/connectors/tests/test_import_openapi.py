import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def mcas_text():
    return (FIXTURES / "mcas_openapi.json").read_text()


def test_mcas_imports_all_ten_operations():
    from aisc_connectors.importers.openapi import import_openapi
    from aisc_connectors.model import operations

    result = import_openapi(mcas_text(), source_url="http://172.17.0.1:8500/openapi.json")
    ops = {o.path: o for o in operations(result.document)}
    assert len(ops) == 10
    assert result.document["servers"] == [{"url": "http://172.17.0.1:8500"}]
    assert ops["/chat"].binding == {"protocol": "http", "method": "post", "path": "/chat", "static_headers": {}}
    assert ops["/health"].changes_data is False
    assert ops["/halt"].changes_data is True


def test_a_missing_server_needs_a_base_url():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.openapi import import_openapi

    with pytest.raises(ImportFailed, match="base URL"):
        import_openapi(mcas_text())
    assert import_openapi(mcas_text(), base_url="http://h:1").document["servers"] == [{"url": "http://h:1"}]


def test_invalid_but_usable_spec_imports_with_warnings():
    from aisc_connectors.importers.openapi import import_openapi

    spec = {"openapi": "3.0.3", "info": {"title": "t"},  # no version: invalid
            "servers": [{"url": "/v1"}],
            "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}}}
    result = import_openapi(json.dumps(spec), source_url="https://api.example.com/spec.json")
    assert result.document["servers"] == [{"url": "https://api.example.com/v1"}]
    assert any("not valid" in w for w in result.warnings)
    assert result.document["paths"]["/ping"]["get"]["operationId"] == "get_ping"


def test_synthesized_ids_are_stable():
    from aisc_connectors.importers.openapi import import_openapi

    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "http://h"}],
                       "paths": {"/a/{id}/b": {"get": {}, "post": {}}, "/a_id_b": {"get": {}}}})
    first = import_openapi(spec).document
    second = import_openapi(spec).document
    ids = [first["paths"]["/a/{id}/b"]["get"]["operationId"], first["paths"]["/a/{id}/b"]["post"]["operationId"],
           first["paths"]["/a_id_b"]["get"]["operationId"]]
    assert len(set(ids)) == 3
    assert ids[0] == second["paths"]["/a/{id}/b"]["get"]["operationId"]


def test_a_spec_cannot_smuggle_in_bindings():
    from aisc_connectors.importers.openapi import import_openapi

    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "http://h"}],
                       "paths": {"/x": {"get": {"operationId": "x",
                                                "x-aisc-binding": {"protocol": "http", "path": "//evil"}}}}})
    op = import_openapi(spec).document["paths"]["/x"]["get"]
    assert op["x-aisc-binding"]["path"] == "/x"


def test_yaml_is_accepted():
    from aisc_connectors.importers.openapi import import_openapi

    text = "openapi: 3.1.0\ninfo: {title: t, version: '1'}\nservers: [{url: 'http://h'}]\npaths:\n  /p:\n    get: {operationId: p}\n"
    assert import_openapi(text).document["paths"]["/p"]["get"]["operationId"] == "p"


def test_security_schemes_become_an_auth_suggestion():
    from aisc_connectors.importers.openapi import import_openapi

    spec = json.dumps({"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "http://h"}],
                       "components": {"securitySchemes": {"k": {"type": "apiKey", "in": "header", "name": "X-Key"}}},
                       "paths": {}})
    assert import_openapi(spec).auth_suggestion == {"scheme": "api_key", "in": "header", "name": "X-Key"}


def test_swagger_two_is_routed_to_the_converter(monkeypatch):
    from aisc_connectors.importers import openapi

    called = {}
    monkeypatch.setattr("aisc_connectors.importers.swagger2.convert",
                        lambda d: called.setdefault("yes", {"openapi": "3.1.0", "info": {"title": "t", "version": "1"},
                                                            "servers": [{"url": "http://h"}], "paths": {}}))
    openapi.import_openapi(json.dumps({"swagger": "2.0", "info": {}, "paths": {}}))
    assert "yes" in called


def test_other_documents_are_refused():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.openapi import import_openapi

    with pytest.raises(ImportFailed):
        import_openapi("<html>not a spec</html>")
