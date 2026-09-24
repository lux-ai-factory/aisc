import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "postman_collection.json"


def test_requests_in_folders_become_operations_on_one_server():
    from aisc_connectors.importers.postman import import_postman
    from aisc_connectors.model import operations

    result = import_postman(FIXTURE.read_text())
    ops = {o.operation_id: o for o in operations(result.document)}
    assert set(ops) == {"score_applicant", "health"}
    assert result.document["servers"] == [{"url": "https://api.acme.test"}]
    assert ops["score_applicant"].spec["requestBody"]["content"]["application/json"]["example"] == {"amount": 100}
    assert any("other.test" in w for w in result.warnings)


def test_unresolved_variables_are_named():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.postman import import_postman

    collection = json.loads(FIXTURE.read_text())
    collection["variable"] = []
    with pytest.raises(ImportFailed, match="baseUrl"):
        import_postman(json.dumps(collection))


def test_bearer_auth_is_detected():
    from aisc_connectors.importers.postman import import_postman

    collection = {"info": {"name": "x"}, "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "tkn"}]},
                  "item": [{"name": "Ping", "request": {"method": "GET", "url": "https://h.test/ping"}}]}
    result = import_postman(json.dumps(collection))
    assert result.auth_suggestion == {"scheme": "bearer"}
    assert result.detected_secrets == {"token": "tkn"}


def test_apikey_auth_in_query_is_not_silently_dropped():
    """A Postman `apikey` auth with "in": "query" must surface as a secret + auth suggestion,
    never as a value written into the document, and regardless of whether the key name happens
    to be one of the names one_operation's query-credential heuristic already recognises."""
    from aisc_connectors.importers.postman import import_postman

    collection = {
        "info": {"name": "x"},
        "auth": {"type": "apikey", "apikey": [
            {"key": "key", "value": "X-RapidAPI-Key"},
            {"key": "value", "value": "sekret"},
            {"key": "in", "value": "query"},
        ]},
        "item": [{"name": "Ping", "request": {"method": "GET", "url": "https://h.test/ping"}}],
    }
    result = import_postman(json.dumps(collection))
    assert result.auth_suggestion == {"scheme": "api_key", "in": "query", "name": "X-RapidAPI-Key"}
    assert result.detected_secrets == {"api_key": "sekret"}
    assert "sekret" not in str(result.document)
    assert "X-RapidAPI-Key" not in str(result.document)


def test_url_object_without_raw_is_built_from_parts():
    from aisc_connectors.importers.postman import import_postman
    from aisc_connectors.model import operations

    collection = {
        "info": {"name": "x"},
        "item": [{"name": "Score", "request": {"method": "GET", "url": {
            "protocol": "https", "host": ["api", "acme", "test"], "port": "8443",
            "path": ["v1", "score"],
            "query": [{"key": "lang", "value": "en"}, {"key": "debug", "value": "1", "disabled": True}],
        }}}],
    }
    result = import_postman(json.dumps(collection))
    op = operations(result.document)[0]
    assert result.document["servers"] == [{"url": "https://api.acme.test:8443"}]
    assert op.path == "/v1/score"
    assert op.spec["parameters"] == [{"in": "query", "name": "lang", "required": False,
                                      "schema": {"type": "string"}, "example": "en"}]


def test_url_object_with_nothing_usable_fails():
    from aisc_connectors.importers.errors import ImportFailed
    from aisc_connectors.importers.postman import import_postman

    collection = {"info": {"name": "x"},
                  "item": [{"name": "Broken request", "request": {"method": "GET", "url": {}}}]}
    with pytest.raises(ImportFailed, match="Broken request"):
        import_postman(json.dumps(collection))


def test_basic_auth_is_detected():
    from aisc_connectors.importers.postman import import_postman

    collection = {"info": {"name": "x"},
                  "auth": {"type": "basic", "basic": [{"key": "username", "value": "svc"},
                                                       {"key": "password", "value": "pa55"}]},
                  "item": [{"name": "Ping", "request": {"method": "GET", "url": "https://h.test/ping"}}]}
    result = import_postman(json.dumps(collection))
    assert result.auth_suggestion == {"scheme": "basic", "username": "svc"}
    assert result.detected_secrets == {"password": "pa55"}
    assert "pa55" not in json.dumps(result.document)


def test_basic_auth_values_are_resolved_from_variables():
    from aisc_connectors.importers.postman import import_postman

    collection = {"info": {"name": "x"}, "variable": [{"key": "svcPass", "value": "pa55"}],
                  "auth": {"type": "basic", "basic": [{"key": "username", "value": "svc"},
                                                       {"key": "password", "value": "{{svcPass}}"}]},
                  "item": [{"name": "Ping", "request": {"method": "GET", "url": "https://h.test/ping"}}]}
    result = import_postman(json.dumps(collection))
    assert result.detected_secrets == {"password": "pa55"}


@pytest.mark.parametrize("mode", ["formdata", "file"])
def test_formdata_and_file_bodies_are_not_imported_but_warn(mode):
    from aisc_connectors.importers.postman import import_postman
    from aisc_connectors.model import operations

    collection = {"info": {"name": "x"},
                  "item": [{"name": "Upload", "request": {"method": "POST", "url": "https://h.test/upload",
                            "body": {"mode": mode, mode: [{"key": "file", "type": "file"}]}}}]}
    result = import_postman(json.dumps(collection))
    op = operations(result.document)[0]
    assert "requestBody" not in op.spec
    assert "Upload: form-data bodies are not imported; add the fields by hand" in result.warnings
