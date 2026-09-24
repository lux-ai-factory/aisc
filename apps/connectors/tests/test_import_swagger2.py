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
