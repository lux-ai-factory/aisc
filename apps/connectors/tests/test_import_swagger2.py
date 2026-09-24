import json
import pathlib

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "petstore_swagger2.json"


def converted():
    from aisc_connectors.importers.swagger2 import convert

    return convert(json.loads(FIXTURE.read_text()))


def test_host_base_path_and_scheme_become_the_server():
    assert converted()["servers"] == [{"url": "https://petstore.example.com/v2"}]


def test_body_parameters_become_a_request_body_with_rewritten_refs():
    op = converted()["paths"]["/pet"]["post"]
    assert op["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Pet"}
    assert "parameters" not in op or all(p["in"] != "body" for p in op["parameters"])


def test_path_parameters_get_a_schema():
    param = converted()["paths"]["/pet/{petId}"]["get"]["parameters"][0]
    assert param == {"in": "path", "name": "petId", "required": True, "schema": {"type": "integer", "format": "int64"}}


def test_form_data_becomes_multipart():
    body = converted()["paths"]["/pet/{petId}/uploadImage"]["post"]["requestBody"]["content"]
    schema = body["multipart/form-data"]["schema"]
    assert schema["properties"]["file"] == {"type": "string", "format": "binary"}


def test_responses_and_definitions_and_security_move_to_openapi_3():
    doc = converted()
    assert doc["openapi"] == "3.1.0"
    assert "Pet" in doc["components"]["schemas"]
    assert doc["components"]["securitySchemes"]["key"] == {"type": "apiKey", "in": "header", "name": "api_key"}
    ok = doc["paths"]["/pet/{petId}"]["get"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Pet"}


def test_it_imports_end_to_end():
    from aisc_connectors.importers.openapi import import_openapi
    from aisc_connectors.model import operations

    result = import_openapi(FIXTURE.read_text())
    assert {o.operation_id for o in operations(result.document)} == {"addPet", "getPetById", "uploadFile"}
    assert result.auth_suggestion == {"scheme": "api_key", "in": "header", "name": "api_key"}


def test_operation_level_parameter_overrides_path_level_parameter():
    from aisc_connectors.importers.swagger2 import convert

    doc = {
        "swagger": "2.0",
        "info": {"title": "t", "version": "1"},
        "host": "h",
        "paths": {
            "/items": {
                "parameters": [{"in": "query", "name": "limit", "type": "integer"}],
                "get": {
                    "operationId": "listItems",
                    "parameters": [
                        {"in": "query", "name": "limit", "type": "integer", "required": True, "maximum": 100}
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
    }
    params = convert(doc)["paths"]["/items"]["get"]["parameters"]
    limit_params = [p for p in params if p["name"] == "limit" and p["in"] == "query"]
    assert len(limit_params) == 1
    assert limit_params[0] == {
        "in": "query", "name": "limit", "required": True, "schema": {"type": "integer", "maximum": 100}
    }


def test_shared_response_ref_is_kept_and_becomes_a_component():
    from aisc_connectors.importers.swagger2 import convert

    doc = {
        "swagger": "2.0",
        "info": {"title": "t", "version": "1"},
        "host": "h",
        "produces": ["application/json"],
        "paths": {
            "/items/{id}": {
                "get": {
                    "operationId": "getItem",
                    "parameters": [{"in": "path", "name": "id", "required": True, "type": "string"}],
                    "responses": {
                        "200": {"description": "ok"},
                        "404": {"$ref": "#/responses/NotFound"},
                    },
                }
            }
        },
        "responses": {
            "NotFound": {
                "description": "not found",
                "schema": {"type": "object", "properties": {"message": {"type": "string"}}},
            },
        },
    }
    result = convert(doc)
    ref = result["paths"]["/items/{id}"]["get"]["responses"]["404"]
    assert ref == {"$ref": "#/components/responses/NotFound"}
    assert result["components"]["responses"]["NotFound"] == {
        "description": "not found",
        "content": {"application/json": {"schema": {"type": "object", "properties": {"message": {"type": "string"}}}}},
    }


def test_ref_like_text_in_a_description_is_left_untouched():
    from aisc_connectors.importers.swagger2 import convert

    doc = {
        "swagger": "2.0",
        "info": {"title": "t", "version": "1"},
        "host": "h",
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "description": "see #/definitions/X for details",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "definitions": {"X": {"type": "object"}},
    }
    result = convert(doc)
    assert result["paths"]["/items"]["get"]["description"] == "see #/definitions/X for details"
    assert "X" in result["components"]["schemas"]


def test_shared_parameter_definitions_become_components_parameters():
    from aisc_connectors.importers.swagger2 import convert

    doc = {
        "swagger": "2.0",
        "info": {"title": "t", "version": "1"},
        "host": "h",
        "paths": {"/items": {"get": {"operationId": "listItems", "responses": {"200": {"description": "ok"}}}}},
        "parameters": {"Limit": {"in": "query", "name": "limit", "type": "integer", "maximum": 100}},
    }
    result = convert(doc)
    assert result["components"]["parameters"]["Limit"] == {
        "in": "query", "name": "limit", "schema": {"type": "integer", "maximum": 100},
    }
