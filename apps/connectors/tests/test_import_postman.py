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
